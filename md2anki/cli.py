import argparse
from pathlib import Path

from .pipeline import run_pipeline


def _collect_markdown_files(vault_root: Path, file_args: list[str]) -> list[Path]:
    # 显式传 --file 时仅处理指定文件；否则扫描 vault 下全部 .md。
    if file_args:
        files: list[Path] = []
        for raw in file_args:
            p = Path(raw)
            if not p.is_absolute():
                p = vault_root / p
            files.append(p)
        return files
    return sorted(vault_root.rglob("*.md"))


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数。

    默认是 dry-run，只有显式传 --apply-anki-changes 才会写 Anki。
    """

    parser = argparse.ArgumentParser(description="Run md2anki pipeline")
    parser.add_argument("--vault-root", required=True, help="Vault root directory")
    parser.add_argument("--asset-root", default="assets", help="Asset root under vault")
    parser.add_argument("--anki-connect-url", default="http://127.0.0.1:8765", help="AnkiConnect URL")
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout for each AnkiConnect request in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry count for transient AnkiConnect failures.",
    )
    parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=0.75,
        help="Base exponential backoff seconds between retries.",
    )
    parser.add_argument(
        "--no-fail-fast",
        action="store_true",
        help="Continue syncing remaining notes after a note failure.",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show per-stage progress for parse/media/sync.",
    )
    parser.add_argument(
        "--sync-state-file",
        default=None,
        help="Sync state file path, default <vault_root>/sync_state.json",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Markdown file path (repeatable). Relative paths are resolved from vault root.",
    )
    parser.add_argument(
        "--apply-anki-changes",
        action="store_true",
        help="Actually write to AnkiConnect. Default is dry-run.",
    )
    parser.add_argument(
        "--no-write-back-markdown",
        action="store_true",
        help="Disable markdown writeback even when apply mode is enabled.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数、执行 pipeline、输出摘要并返回退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root).absolute()
    vault_name = vault_root.name
    sync_state_file = Path(args.sync_state_file).absolute() if args.sync_state_file else (vault_root / "sync_state.json")
    markdown_files = _collect_markdown_files(vault_root, args.files)

    report = run_pipeline(
        markdown_files=markdown_files,
        vault_root=vault_root,
        vault_name=vault_name,
        asset_root=args.asset_root,
        anki_connect_url=args.anki_connect_url,
        sync_state_file=sync_state_file,
        apply_anki_changes=args.apply_anki_changes,
        write_back_markdown=not args.no_write_back_markdown,
        request_timeout_seconds=args.request_timeout_seconds,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        fail_fast=not args.no_fail_fast,
        show_progress=args.show_progress,
    )

    mode = "apply" if args.apply_anki_changes else "dry-run"
    print(
        "[md2anki] "
        f"mode={mode} added={report.added} updated={report.updated} deleted={report.deleted} "
        f"skipped={report.skipped} failed={report.failed} writebacks={len(report.markdown_writebacks)}"
    )

    if report.errors:
        print("[md2anki] errors:")
        for err in report.errors:
            print(f"- {err}")

    if report.dry_run_actions:
        print(f"[md2anki] dry-run actions: {len(report.dry_run_actions)}")

    return 1 if report.failed else 0
