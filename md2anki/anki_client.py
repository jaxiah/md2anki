import hashlib
import json
import time
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


@dataclass
class PrewarmResult:
    attempted: int = 0
    uploaded: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class AnkiClient:
    """封装 AnkiConnect 与 sync_state 管理。

    约定：
    - dry-run 下不触发任何网络请求，也不写 state。
    - sync_state 仅按 anki_note_id 跟踪已创建卡片。
    """

    def __init__(
        self,
        anki_connect_url: str,
        sync_state_file: Path,
        apply_changes: bool = False,
        request_timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.75,
        fail_fast: bool = True,
    ):
        self.anki_connect_url = anki_connect_url
        self.sync_state_file = Path(sync_state_file)
        self.apply_changes = apply_changes
        self.request_timeout_seconds = request_timeout_seconds
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.fail_fast = fail_fast
        self.state = self.load_state()
        self.deck_cache = self.load_deck_cache()
        # filename → content fingerprint；在进程间和跨进程两个维度去重。
        self._uploaded_media: dict[str, str] = dict(self.state.get("uploaded_media", {}))

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
        self.state["uploaded_media"] = self._uploaded_media
        tmp_file = self.sync_state_file.with_suffix(self.sync_state_file.suffix + ".tmp")
        tmp_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.sync_state_file)

    def invoke(self, action: str, **params) -> tuple[bool, Any]:
        if self.is_dry_run():
            return True, None

        payload = {"action": action, "version": 6, "params": params}
        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    self.anki_connect_url,
                    json=payload,
                    timeout=self.request_timeout_seconds,
                    proxies={"http": None, "https": None},
                )
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    return False, data.get("error")
                return True, data.get("result")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt >= max_attempts - 1:
                    return False, str(exc)
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is None or status_code < 500 or attempt >= max_attempts - 1:
                    return False, str(exc)
            except Exception as exc:
                return False, str(exc)

            backoff_seconds = self.retry_backoff_seconds * (2**attempt)
            if backoff_seconds > 0:
                time.sleep(backoff_seconds)

        return False, f"invoke failed after {max_attempts} attempts: {action}"

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

    @staticmethod
    def _compute_media_fingerprint(media: Any) -> str:
        """Content fingerprint used to skip re-uploading unchanged media across runs.

        对有文件路径的 media，用 mtime+size（不读文件内容，对大文件友好）。
        仅有 base64_data 时，用 sha256(内容)。
        """
        abs_path = getattr(media, "abs_path", None)
        if abs_path:
            try:
                stat = Path(abs_path).stat()
                return f"mtime:{stat.st_mtime_ns}:size:{stat.st_size}"
            except OSError:
                pass
        base64_data = getattr(media, "base64_data", None)
        if base64_data:
            return hashlib.sha256(base64_data.encode()).hexdigest()
        return ""

    def _move_note_to_deck(self, note_id: str, deck_full: str) -> tuple[bool, str | None]:
        """Move all cards of a note to deck_full, preserving Anki review scheduling."""
        if not self.ensure_deck(deck_full):
            return False, f"ensure_deck failed for {deck_full!r}"
        ok, result = self.invoke("notesInfo", notes=[int(note_id)])
        if not ok:
            return False, f"notesInfo failed: {result}"
        notes_data = result if isinstance(result, list) else []
        card_ids: list[int] = [cid for note_data in notes_data for cid in note_data.get("cards", [])]
        if not card_ids:
            return False, f"no cards found for note {note_id}"
        ok, result = self.invoke("changeDeck", cards=card_ids, deck=deck_full)
        if not ok:
            return False, f"changeDeck failed: {result}"
        return True, None

    @staticmethod
    def _looks_like_timeout(error: Any) -> bool:
        message = str(error).lower()
        return "timed out" in message or "timeout" in message

    def _verify_media_uploaded(self, filename: str) -> bool:
        ok, result = self.invoke("retrieveMediaFile", filename=filename)
        if not ok:
            return False
        return bool(result)

    def _store_media(self, media: Any) -> tuple[bool, str | None, str]:
        filename = getattr(media, "filename", None)
        if not filename:
            return False, "missing media filename", "failed"

        path_error: Any = None
        abs_path = getattr(media, "abs_path", None)
        if abs_path:
            ok, result = self.invoke("storeMediaFile", filename=filename, path=abs_path)
            if ok:
                return True, None, "uploaded(path)"
            path_error = result
            if self._looks_like_timeout(result) and self._verify_media_uploaded(filename):
                return True, None, "uploaded(verified)"

        data_payload = getattr(media, "base64_data", None)
        if data_payload:
            ok, result = self.invoke("storeMediaFile", filename=filename, data=data_payload)
            if ok:
                return True, None, "uploaded(data)"
            if self._looks_like_timeout(result) and self._verify_media_uploaded(filename):
                return True, None, "uploaded(verified)"
            if path_error is not None:
                return False, f"path={path_error}; data={result}", "failed"
            return False, str(result), "failed"

        if path_error is not None:
            return False, str(path_error), "failed"
        return False, "missing media path and base64 payload", "failed"

    def _collect_unique_media(self, rendered_notes) -> list[Any]:
        unique_media: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for rendered in rendered_notes:
            for media in getattr(rendered, "media_files", []):
                key = (media.filename, media.base64_data)
                if key in seen:
                    continue
                seen.add(key)
                unique_media.append(media)
        return unique_media

    def prewarm_media(self, rendered_notes, progress_callback=None) -> PrewarmResult:
        result = PrewarmResult()
        if self.is_dry_run():
            return result

        unique_media = self._collect_unique_media(rendered_notes)
        total = len(unique_media)

        for index, media in enumerate(unique_media, start=1):
            fingerprint = self._compute_media_fingerprint(media)
            if fingerprint and self._uploaded_media.get(media.filename) == fingerprint:
                if progress_callback:
                    progress_callback("media", index, total, media.filename, "cached")
                continue

            result.attempted += 1
            media_ok, media_err, media_status = self._store_media(media)
            if not media_ok:
                result.failed += 1
                result.errors.append(f"storeMediaFile failed for {media.filename}: {media_err}")
                if progress_callback:
                    progress_callback("media", index, total, media.filename, media_status)
                if self.fail_fast:
                    break
                continue

            if fingerprint:
                self._uploaded_media[media.filename] = fingerprint
            result.uploaded += 1
            if progress_callback:
                progress_callback("media", index, total, media.filename, media_status)

        if result.uploaded > 0:
            self.save_state()
        return result

    def sync(self, rendered_notes, progress_callback=None, skip_media_upload: bool = False):
        # 单条失败不终止全局；统一聚合到 SyncResult。
        result = SyncResult()
        items = self.state.setdefault("items", {})
        state_changed = False
        total_notes = len(rendered_notes)

        for index, rendered in enumerate(rendered_notes, start=1):
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
                if progress_callback:
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "skip_noanki")
                continue

            if getattr(parsed, "delete_requested", False):
                # DELETE 分支：有 id 才允许删除，成功后给回写层处理 ^anki -> ^noanki。
                if not note_id:
                    result.failed += 1
                    result.errors.append(f"delete requested but missing anki_note_id for {getattr(parsed, 'source_file', '<unknown>')}")
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "delete_failed")
                    if self.fail_fast:
                        break
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
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "would_delete")
                    continue

                success, err = self.delete_note(note_id)
                if not success:
                    result.failed += 1
                    result.errors.append(f"delete failed for ^anki-{note_id}: {err}")
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "delete_failed")
                    if self.fail_fast:
                        break
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
                if progress_callback:
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "deleted")
                continue

            content_hash = self.compute_content_hash(rendered)

            if note_id and note_id in items and items[note_id].get("content_hash") == content_hash:
                deck_in_state = items[note_id].get("deck_full")
                new_deck_check = getattr(parsed, "deck_full", None)
                if deck_in_state == new_deck_check:
                    # 内容与 deck 均未变化，完全跳过。
                    result.skipped += 1
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "skip_unchanged")
                    continue
                # 内容未变但 deck 需要更新（父节点重命名，或 legacy state 无 deck_full 记录）。
                if self.is_dry_run():
                    result.dry_run_actions.append(
                        {
                            "action": "would_move_deck",
                            "anki_note_id": note_id,
                            "source_file": getattr(parsed, "source_file", None),
                            "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                            "deck_move": True,
                            "old_deck": deck_in_state,
                            "new_deck": new_deck_check,
                        }
                    )
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "would_move_deck")
                    continue
                move_ok, move_err = self._move_note_to_deck(note_id, new_deck_check)
                if move_ok:
                    items[note_id]["deck_full"] = new_deck_check
                    state_changed = True
                    result.updated += 1
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "deck_moved")
                else:
                    result.errors.append(
                        f"changeDeck failed for ^anki-{note_id} ({deck_in_state!r} \u2192 {new_deck_check!r}): {move_err}"
                    )
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "deck_move_failed")
                continue

            if self.is_dry_run():
                _new_deck = getattr(parsed, "deck_full", None)
                _old_deck = items.get(note_id, {}).get("deck_full") if note_id else None
                _deck_will_move = note_id is not None and _old_deck != _new_deck
                result.dry_run_actions.append(
                    {
                        "action": "would_update" if note_id else "would_add",
                        "anki_note_id": note_id,
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                        "deck_move": _deck_will_move,
                        "old_deck": _old_deck if _deck_will_move else None,
                        "new_deck": _new_deck if _deck_will_move else None,
                    }
                )
                if progress_callback:
                    action = "would_update" if note_id else "would_add"
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), action)
                continue

            if not self.ensure_deck(getattr(parsed, "deck_full", None)):
                result.failed += 1
                result.errors.append(f"ensure deck failed for {getattr(parsed, 'deck_full', '<none>')} ({getattr(parsed, 'source_file', '<unknown>')})")
                if progress_callback:
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "deck_failed")
                if self.fail_fast:
                    break
                continue

            if not skip_media_upload:
                media_failed = False
                for media in rendered.media_files:
                    # 媒体任一失败则该 note 终止，避免字段与媒体不一致。
                    fingerprint = self._compute_media_fingerprint(media)
                    if fingerprint and self._uploaded_media.get(media.filename) == fingerprint:
                        continue
                    media_ok, media_err, _ = self._store_media(media)
                    if not media_ok:
                        result.failed += 1
                        result.errors.append(f"storeMediaFile failed for {media.filename}: {media_err}")
                        media_failed = True
                        break
                    if fingerprint:
                        self._uploaded_media[media.filename] = fingerprint
                    state_changed = True
                if media_failed:
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "media_failed")
                    if self.fail_fast:
                        break
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
                    if progress_callback:
                        progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "update_failed")
                    if self.fail_fast:
                        break
                    continue
                # 字段更新成功；检查是否需要同时迁移 deck。
                result.updated += 1
                new_deck = getattr(parsed, "deck_full", None)
                old_deck = items.get(note_id, {}).get("deck_full")
                deck_to_persist = new_deck
                if old_deck != new_deck:
                    move_ok, move_err = self._move_note_to_deck(note_id, new_deck)
                    if not move_ok:
                        result.errors.append(
                            f"changeDeck failed for ^anki-{note_id} ({old_deck!r} → {new_deck!r}): {move_err}"
                        )
                        deck_to_persist = old_deck  # 保留旧 deck，下次 sync 自动重试
                items[note_id] = {
                    "content_hash": content_hash,
                    "updated_ts": self._now_iso(),
                    "source_file": getattr(parsed, "source_file", None),
                    "h4_heading_pure": getattr(parsed, "h4_heading_pure", None),
                    "deck_full": deck_to_persist,
                }
                state_changed = True
                if progress_callback:
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "updated")
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
                if progress_callback:
                    progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "add_failed")
                if self.fail_fast:
                    break
                continue

            new_note_id = str(add_result)
            result.added += 1
            items[new_note_id] = {
                "content_hash": content_hash,
                "updated_ts": self._now_iso(),
                "source_file": getattr(parsed, "source_file", None),
                "h4_heading_pure": getattr(parsed, "h4_heading_pure", None),
                "deck_full": getattr(parsed, "deck_full", None),
            }
            result.bindings_to_writeback.append(
                {
                    "source_file": getattr(parsed, "source_file", None),
                    "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    "anki_note_id": new_note_id,
                }
            )
            state_changed = True
            if progress_callback:
                progress_callback("sync", index, total_notes, getattr(parsed, "h4_heading_pure", None), "added")

        if state_changed and not self.is_dry_run():
            self.save_state()

        return result
