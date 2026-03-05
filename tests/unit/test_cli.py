from pathlib import Path

import md2anki.cli as cli
from md2anki.pipeline import PipelineReport


def test_cli_defaults_to_dry_run_and_collects_files(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "a.md").write_text("# A\n", encoding="utf-8")
    (vault / "b.md").write_text("# B\n", encoding="utf-8")

    captured = {}

    def _fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return PipelineReport()

    monkeypatch.setattr(cli, "run_pipeline", _fake_run_pipeline)

    code = cli.main(["--vault-root", str(vault)])

    assert code == 0
    assert captured["apply_anki_changes"] is False
    assert captured["write_back_markdown"] is True
    assert len(captured["markdown_files"]) == 2
    assert captured["vault_name"] == vault.name
    assert captured["request_timeout_seconds"] == 30.0
    assert captured["max_retries"] == 2
    assert captured["retry_backoff_seconds"] == 0.75
    assert captured["fail_fast"] is True
    assert captured["show_progress"] is False


def test_cli_apply_mode_with_explicit_file(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    target = vault / "only.md"
    target.write_text("# only\n", encoding="utf-8")

    captured = {}

    def _fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return PipelineReport(failed=1)

    monkeypatch.setattr(cli, "run_pipeline", _fake_run_pipeline)

    code = cli.main(
        [
            "--vault-root",
            str(vault),
            "--file",
            "only.md",
            "--apply-anki-changes",
            "--no-write-back-markdown",
            "--request-timeout-seconds",
            "45",
            "--max-retries",
            "4",
            "--retry-backoff-seconds",
            "1.5",
            "--no-fail-fast",
            "--show-progress",
        ]
    )

    assert code == 1
    assert captured["apply_anki_changes"] is True
    assert captured["write_back_markdown"] is False
    assert captured["markdown_files"] == [target]
    assert captured["vault_name"] == vault.name
    assert captured["request_timeout_seconds"] == 45.0
    assert captured["max_retries"] == 4
    assert captured["retry_backoff_seconds"] == 1.5
    assert captured["fail_fast"] is False
    assert captured["show_progress"] is True
