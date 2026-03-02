from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .anki_client import AnkiClient
from .html_renderer import HtmlRenderer
from .markdown_processor import MarkdownProcessor


@dataclass
class PipelineReport:
    """pipeline 聚合报告：统计、错误、回写记录与 dry-run 计划。"""

    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    markdown_writebacks: list[str] = field(default_factory=list)
    dry_run_actions: list[dict[str, Any]] = field(default_factory=list)


def run_pipeline(
    markdown_files: list[Path],
    vault_root: Path,
    vault_name: str,
    asset_root: str = "assets",
    anki_connect_url: str = "http://127.0.0.1:8765",
    sync_state_file: Path | None = None,
    apply_anki_changes: bool = False,
    write_back_markdown: bool = True,
    processor: MarkdownProcessor | None = None,
    renderer: HtmlRenderer | None = None,
    anki_client: AnkiClient | None = None,
) -> PipelineReport:
    """最小过程式编排：parse -> (route) -> render -> sync -> writeback。"""

    vault_root = Path(vault_root).absolute()
    state_file = sync_state_file or (vault_root / "sync_state.json")

    processor = processor or MarkdownProcessor(vault_root=vault_root)
    renderer = renderer or HtmlRenderer(vault_name=vault_name, vault_root=vault_root, asset_root=asset_root)
    anki_client = anki_client or AnkiClient(
        anki_connect_url=anki_connect_url,
        sync_state_file=state_file,
        apply_changes=apply_anki_changes,
    )

    parsed_docs = []
    rendered_payloads: list[Any] = []
    report = PipelineReport()
    writeback_files_seen: set[str] = set()

    def _record_writeback(source_file: str) -> None:
        if source_file not in writeback_files_seen:
            writeback_files_seen.add(source_file)
            report.markdown_writebacks.append(source_file)

    for markdown_file in markdown_files:
        # 支持相对路径输入，统一转为 vault_root 下绝对路径处理。
        abs_file = Path(markdown_file)
        if not abs_file.is_absolute():
            abs_file = vault_root / abs_file
        doc = processor.parse_file(abs_file)
        parsed_docs.append(doc)

        if write_back_markdown and apply_anki_changes:
            # 先确保父节点 block id 落地，再进行渲染与 hash 计算，避免首轮后续出现“全量 update”。
            parent_meta_by_line: dict[int, dict[str, Any]] = {}
            for note in doc.notes:
                if note.parent_line_idx is None:
                    continue
                meta = parent_meta_by_line.setdefault(
                    note.parent_line_idx,
                    {
                        "title": note.parent_title,
                        "line_idx": note.parent_line_idx,
                        "block_id": note.parent_block_id,
                    },
                )
                if not meta.get("block_id") and note.parent_block_id:
                    meta["block_id"] = note.parent_block_id

            if parent_meta_by_line:
                file_lines = abs_file.read_text(encoding="utf-8").splitlines(keepends=True)
                parent_changed = False
                parent_ops = sorted(parent_meta_by_line.values(), key=lambda item: item.get("line_idx", -1), reverse=True)
                for parent_meta in parent_ops:
                    _, inserted = processor.ensure_parent_block_id(parent_meta, file_lines)
                    if inserted:
                        parent_changed = True

                # 将最新 block_id 回填到本轮 notes，保证后续渲染与 hash 稳定。
                for note in doc.notes:
                    if note.parent_line_idx in parent_meta_by_line:
                        note.parent_block_id = parent_meta_by_line[note.parent_line_idx].get("block_id")

                if parent_changed:
                    abs_file.write_text("".join(file_lines), encoding="utf-8")
                    _record_writeback(doc.source_file)
                    # 父节点插入会改变后续 H4 行号，需重解析刷新 line_idx_h4 后再继续。
                    doc = processor.parse_file(abs_file)
                    parsed_docs[-1] = doc

        report.errors.extend(doc.warnings)

        for note in doc.notes:
            if note.no_anki and not note.delete_requested:
                # noanki 直接跳过后续阶段。
                report.skipped += 1
                report.dry_run_actions.append(
                    {
                        "action": "skip_noanki",
                        "source_file": note.source_file,
                        "line_idx_h4": note.line_idx_h4,
                    }
                )
                continue

            if note.delete_requested:
                # 删除分支不需要渲染 HTML，仅传递 parsed 元信息即可。
                rendered_payloads.append(
                    SimpleNamespace(
                        parsed=note,
                        front_html="",
                        back_html_with_footer="",
                        media_files=[],
                    )
                )
                continue

            rendered_payloads.append(renderer.render(note))

    sync_result = anki_client.sync(rendered_payloads)

    report.added += sync_result.added
    report.updated += sync_result.updated
    report.deleted += sync_result.deleted
    report.skipped += sync_result.skipped
    report.failed += sync_result.failed
    report.errors.extend(sync_result.errors)
    report.dry_run_actions.extend(sync_result.dry_run_actions)

    if write_back_markdown and apply_anki_changes:
        # 仅在 apply 模式回写，dry-run 永远不触碰 markdown 文件。
        writeback_by_file: dict[str, dict[str, list[dict[str, Any]]]] = {}
        parent_ops_by_file: dict[str, dict[int, dict[str, Any]]] = {}

        for doc in parsed_docs:
            for note in doc.notes:
                if note.no_anki and not note.delete_requested:
                    continue
                if note.parent_line_idx is None:
                    continue

                per_file = parent_ops_by_file.setdefault(note.source_file, {})
                existing = per_file.get(note.parent_line_idx)
                if existing is None:
                    per_file[note.parent_line_idx] = {
                        "title": note.parent_title,
                        "line_idx": note.parent_line_idx,
                        "block_id": note.parent_block_id,
                    }
                elif not existing.get("block_id") and note.parent_block_id:
                    existing["block_id"] = note.parent_block_id

        for binding in sync_result.bindings_to_writeback:
            source_file = binding.get("source_file")
            if not source_file:
                continue
            writeback_by_file.setdefault(source_file, {"bind": [], "delete": []})["bind"].append(binding)

        for deletion in sync_result.deletions_to_writeback:
            source_file = deletion.get("source_file")
            if not source_file:
                continue
            writeback_by_file.setdefault(source_file, {"bind": [], "delete": []})["delete"].append(deletion)

        for source_file in parent_ops_by_file:
            writeback_by_file.setdefault(source_file, {"bind": [], "delete": []})

        for source_file, ops in writeback_by_file.items():
            abs_path = vault_root / source_file
            if not abs_path.exists():
                report.errors.append(f"writeback file missing: {source_file}")
                continue

            file_lines = abs_path.read_text(encoding="utf-8").splitlines(keepends=True)
            file_changed = False

            # 将 bind/delete/parent 合并后统一按锚点行号倒序执行，避免跨类型操作引发行号漂移。
            all_ops: list[dict[str, Any]] = []
            for bind in ops["bind"]:
                all_ops.append(
                    {
                        "kind": "bind",
                        "line_idx": bind.get("line_idx_h4", -1),
                        "payload": bind,
                        "priority": 3,
                    }
                )
            for deletion in ops["delete"]:
                all_ops.append(
                    {
                        "kind": "delete",
                        "line_idx": deletion.get("line_idx_h4", -1),
                        "payload": deletion,
                        "priority": 3,
                    }
                )
            for parent_meta in parent_ops_by_file.get(source_file, {}).values():
                all_ops.append(
                    {
                        "kind": "parent",
                        "line_idx": parent_meta.get("line_idx", -1),
                        "payload": parent_meta,
                        "priority": 1,
                    }
                )

            all_ops.sort(key=lambda item: (item.get("line_idx", -1), item.get("priority", 0)), reverse=True)

            for op in all_ops:
                kind = op["kind"]
                payload = op["payload"]
                if kind == "bind":
                    # add 成功后，将新 ^anki-id 写回对应 H4 元信息区。
                    if processor.append_anki_id_at_line(
                        file_lines,
                        payload.get("line_idx_h4"),
                        payload.get("anki_note_id"),
                    ):
                        file_changed = True
                elif kind == "delete":
                    # delete 成功后，删除 ^anki 行并补 ^noanki。
                    if processor.remove_anki_metadata_and_mark_noanki(file_lines, payload.get("line_idx_h4")):
                        file_changed = True
                else:
                    _, inserted = processor.ensure_parent_block_id(payload, file_lines)
                    if inserted:
                        file_changed = True

            if file_changed:
                abs_path.write_text("".join(file_lines), encoding="utf-8")
                _record_writeback(source_file)

    return report
