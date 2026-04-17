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
    request_timeout_seconds: float = 30.0,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.75,
    fail_fast: bool = True,
    show_progress: bool = False,
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
        request_timeout_seconds=request_timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        fail_fast=fail_fast,
    )

    parsed_docs = []
    rendered_payloads: list[Any] = []
    report = PipelineReport()
    writeback_files_seen: set[str] = set()

    def _emit_progress(stage: str, current: int, total: int, name: str | None = None, status: str | None = None) -> None:
        if not show_progress:
            return
        remaining = max(total - current, 0)
        suffix = ""
        if name:
            suffix += f" item={name}"
        if status:
            suffix += f" status={status}"
        print(f"[md2anki][progress] stage={stage} current={current}/{total} remaining={remaining}{suffix}")

    def _record_writeback(source_file: str) -> None:
        if source_file not in writeback_files_seen:
            writeback_files_seen.add(source_file)
            report.markdown_writebacks.append(source_file)

    total_files = len(markdown_files)

    for file_index, markdown_file in enumerate(markdown_files, start=1):
        # 支持相对路径输入，统一转为 vault_root 下绝对路径处理。
        abs_file = Path(markdown_file)
        if not abs_file.is_absolute():
            abs_file = vault_root / abs_file
        doc = processor.parse_file(abs_file)
        parsed_docs.append(doc)
        _emit_progress("parse", file_index, total_files, doc.source_file, "parsed")

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

            rendered = renderer.render(note)
            if rendered.warnings:
                report.errors.extend(rendered.warnings)
            rendered_payloads.append(rendered)

    if apply_anki_changes:
        prewarm_result = anki_client.prewarm_media(rendered_payloads, progress_callback=_emit_progress)
        report.failed += prewarm_result.failed
        report.errors.extend(prewarm_result.errors)
        if prewarm_result.failed > 0 and fail_fast:
            return report

    sync_result = anki_client.sync(
        rendered_payloads,
        progress_callback=_emit_progress,
        skip_media_upload=apply_anki_changes,
    )

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

            if file_changed:
                abs_path.write_text("".join(file_lines), encoding="utf-8")
                _record_writeback(source_file)

    return report
