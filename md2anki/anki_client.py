import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


@dataclass
class SyncResult:
    """一次同步的聚合结果，供 pipeline 统计与回写使用。"""

    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    bindings_to_writeback: list[dict[str, Any]] = field(default_factory=list)
    deletions_to_writeback: list[dict[str, Any]] = field(default_factory=list)
    dry_run_actions: list[dict[str, Any]] = field(default_factory=list)


class AnkiClient:
    """封装 AnkiConnect 与 sync_state 管理。

    约定：
    - dry-run 下不触发任何网络请求，也不写 state。
    - sync_state 仅按 anki_note_id 跟踪已创建卡片。
    """

    def __init__(self, anki_connect_url: str, sync_state_file: Path, apply_changes: bool = False):
        self.anki_connect_url = anki_connect_url
        self.sync_state_file = Path(sync_state_file)
        self.apply_changes = apply_changes
        self.state = self.load_state()
        self.deck_cache = self.load_deck_cache()

    def is_dry_run(self) -> bool:
        return not self.apply_changes

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def load_state(self) -> dict[str, Any]:
        # state 损坏或格式异常时回退为空结构，避免阻塞主流程。
        if not self.sync_state_file.exists():
            return {"schema_version": 1, "items": {}}

        try:
            loaded = json.loads(self.sync_state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), dict):
                loaded.setdefault("schema_version", 1)
                return loaded
        except Exception:
            pass

        return {"schema_version": 1, "items": {}}

    def save_state(self) -> None:
        # 采用临时文件替换，减少中途中断导致的 state 损坏风险。
        self.sync_state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.sync_state_file.with_suffix(self.sync_state_file.suffix + ".tmp")
        tmp_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.sync_state_file)

    def invoke(self, action: str, **params) -> tuple[bool, Any]:
        if self.is_dry_run():
            return True, None

        payload = {"action": action, "version": 6, "params": params}
        try:
            response = requests.post(
                self.anki_connect_url,
                json=payload,
                timeout=15,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                return False, data.get("error")
            return True, data.get("result")
        except Exception as exc:
            return False, str(exc)

    def load_deck_cache(self) -> set[str]:
        # apply 模式下预热 deck 列表，减少重复 createDeck 调用。
        if self.is_dry_run():
            return set()
        success, result = self.invoke("deckNamesAndIds")
        if success and isinstance(result, dict):
            return set(result.keys())
        return set()

    def ensure_deck(self, deck_name: str | None) -> bool:
        if not deck_name:
            return False
        if self.is_dry_run() or deck_name in self.deck_cache:
            return True
        success, _ = self.invoke("createDeck", deck=deck_name)
        if success:
            self.deck_cache.add(deck_name)
            return True
        return False

    def compute_content_hash(self, rendered_note: Any) -> str:
        # hash 仅基于 markdown 语义与媒体引用，不依赖渲染后的 HTML/footer。
        parsed = getattr(rendered_note, "parsed", None)
        payload = {
            "deck_full": getattr(parsed, "deck_full", None),
            "front_md": getattr(parsed, "front_md", None),
            "back_md": getattr(parsed, "back_md", None),
            "media_refs": sorted([f"{item.filename}:{item.source_ref}" for item in rendered_note.media_files]),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def delete_note(self, note_id: str) -> tuple[bool, str | None]:
        success, result = self.invoke("deleteNotes", notes=[int(note_id)])
        if success:
            return True, None
        return False, str(result)

    def sync(self, rendered_notes):
        # 单条失败不终止全局；统一聚合到 SyncResult。
        result = SyncResult()
        items = self.state.setdefault("items", {})
        state_changed = False

        for rendered in rendered_notes:
            parsed = rendered.parsed
            note_id = getattr(parsed, "anki_note_id", None)

            if getattr(parsed, "no_anki", False) and not getattr(parsed, "delete_requested", False):
                # noanki 只跳过，不触发 add/update/delete。
                result.skipped += 1
                result.dry_run_actions.append(
                    {
                        "action": "skip_noanki",
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    }
                )
                continue

            if getattr(parsed, "delete_requested", False):
                # DELETE 分支：有 id 才允许删除，成功后给回写层处理 ^anki -> ^noanki。
                if not note_id:
                    result.failed += 1
                    result.errors.append(f"delete requested but missing anki_note_id for {getattr(parsed, 'source_file', '<unknown>')}")
                    continue

                if self.is_dry_run():
                    result.dry_run_actions.append(
                        {
                            "action": "would_delete",
                            "anki_note_id": note_id,
                            "source_file": getattr(parsed, "source_file", None),
                            "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                        }
                    )
                    continue

                success, err = self.delete_note(note_id)
                if not success:
                    result.failed += 1
                    result.errors.append(f"delete failed for ^anki-{note_id}: {err}")
                    continue

                result.deleted += 1
                if note_id in items:
                    del items[note_id]
                    state_changed = True
                result.deletions_to_writeback.append(
                    {
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                        "anki_note_id": note_id,
                    }
                )
                continue

            content_hash = self.compute_content_hash(rendered)

            if note_id and note_id in items and items[note_id].get("content_hash") == content_hash:
                # 已存在且内容未变化，直接跳过。
                result.skipped += 1
                continue

            if self.is_dry_run():
                result.dry_run_actions.append(
                    {
                        "action": "would_update" if note_id else "would_add",
                        "anki_note_id": note_id,
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    }
                )
                continue

            if not self.ensure_deck(getattr(parsed, "deck_full", None)):
                result.failed += 1
                result.errors.append(f"ensure deck failed for {getattr(parsed, 'deck_full', '<none>')} ({getattr(parsed, 'source_file', '<unknown>')})")
                continue

            media_failed = False
            for media in rendered.media_files:
                # 媒体任一失败则该 note 终止，避免字段与媒体不一致。
                media_ok, media_err = self.invoke("storeMediaFile", filename=media.filename, data=media.base64_data)
                if not media_ok:
                    result.failed += 1
                    result.errors.append(f"storeMediaFile failed for {media.filename}: {media_err}")
                    media_failed = True
                    break
            if media_failed:
                continue

            if note_id:
                update_ok, update_err = self.invoke(
                    "updateNoteFields",
                    note={
                        "id": int(note_id),
                        "fields": {
                            "Front": rendered.front_html,
                            "Back": rendered.back_html_with_footer,
                        },
                    },
                )
                if not update_ok:
                    result.failed += 1
                    result.errors.append(f"update failed for ^anki-{note_id}: {update_err}")
                    continue
                result.updated += 1
                items[note_id] = {
                    "content_hash": content_hash,
                    "updated_ts": self._now_iso(),
                    "source_file": getattr(parsed, "source_file", None),
                    "h4_heading_pure": getattr(parsed, "h4_heading_pure", None),
                }
                state_changed = True
                continue

            add_ok, add_result = self.invoke(
                "addNote",
                note={
                    "deckName": getattr(parsed, "deck_full", None),
                    "modelName": "Basic",
                    "fields": {
                        "Front": rendered.front_html,
                        "Back": rendered.back_html_with_footer,
                    },
                    "options": {"allowDuplicate": False},
                    "tags": ["md2anki"],
                },
            )
            if not add_ok or add_result is None:
                result.failed += 1
                result.errors.append(f"addNote failed for {getattr(parsed, 'h4_heading_pure', '<unknown>')}: {add_result}")
                continue

            new_note_id = str(add_result)
            result.added += 1
            items[new_note_id] = {
                "content_hash": content_hash,
                "updated_ts": self._now_iso(),
                "source_file": getattr(parsed, "source_file", None),
                "h4_heading_pure": getattr(parsed, "h4_heading_pure", None),
            }
            result.bindings_to_writeback.append(
                {
                    "source_file": getattr(parsed, "source_file", None),
                    "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    "anki_note_id": new_note_id,
                }
            )
            state_changed = True

        if state_changed and not self.is_dry_run():
            self.save_state()

        return result
