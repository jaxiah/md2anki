import json
from pathlib import Path

from md2anki import AnkiClient, run_pipeline


def _make_client(tmp_path: Path, apply_changes: bool = True) -> AnkiClient:
    client = AnkiClient(
        anki_connect_url="http://127.0.0.1:8765",
        sync_state_file=tmp_path / "sync_state.json",
        apply_changes=False,
    )
    client.apply_changes = apply_changes
    return client


def test_pipeline_add_writeback_and_state_in_temp_vault(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "01_add.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card
Back line
""",
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)
    calls: list[str] = []
    update_payloads: list[dict] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            return True, 9001
        if action == "updateNoteFields":
            update_payloads.append(params["note"])
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "^anki-9001" in updated
    assert report.added == 1
    assert report.markdown_writebacks == ["01_add.md"]

    state = json.loads((tmp_path / "sync_state.json").read_text(encoding="utf-8"))
    assert "9001" in state["items"]
    final_url = "obsidian://open?vault=sample-notes&file=01_add%23%5Eanki-9001"
    assert state["items"]["9001"]["obsidian_url"] == final_url
    assert calls == ["createDeck", "addNote", "updateNoteFields"]
    assert update_payloads[0]["id"] == 9001
    assert final_url in update_payloads[0]["fields"]["Back"]

    client_second_run = _make_client(tmp_path, apply_changes=True)

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("second run should skip without Anki calls")

    client_second_run.invoke = _unexpected_invoke

    second_report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client_second_run,
    )

    assert second_report.skipped == 1
    assert second_report.updated == 0
    assert second_report.failed == 0
    assert second_report.markdown_writebacks == []


def test_pipeline_delete_writeback_and_state_cleanup_in_temp_vault(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "02_delete.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card
^anki-9002 DELETE
Back line
""",
        encoding="utf-8",
    )

    state_file = tmp_path / "sync_state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "9002": {
                        "content_hash": "old",
                        "updated_ts": "2026-03-01T00:00:00Z",
                        "source_file": "02_delete.md",
                        "h4_heading_pure": "Card",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)

    def _delete_ok(note_id: str):
        assert note_id == "9002"
        return True, None

    client.delete_note = _delete_ok

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=state_file,
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "^anki-9002" not in updated
    assert "^nosrs" in updated
    assert report.deleted == 1
    assert report.markdown_writebacks == ["02_delete.md"]

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "9002" not in state["items"]


def test_pipeline_dry_run_does_not_touch_markdown_or_state(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "03_dryrun.md"
    original = """---
ankideck: DeckA
---
### Parent
#### Card
Back line
"""
    md_file.write_text(original, encoding="utf-8")

    client = _make_client(tmp_path, apply_changes=False)

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("invoke should not be called in dry-run")

    client.invoke = _unexpected_invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=False,
        write_back_markdown=True,
        anki_client=client,
    )

    assert md_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / "sync_state.json").exists()
    assert any(item["action"] == "would_add" for item in report.dry_run_actions)


def test_pipeline_add_with_multiple_blank_lines_layout(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "04_add_blank_lines.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent


#### Card With Gaps


Back line 1

Back line 2
""",
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)

    def _invoke(action, **params):
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            return True, 9101
        if action == "updateNoteFields":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "#### Card With Gaps\n\n^anki-9101\n" in updated
    assert report.added == 1
    assert report.markdown_writebacks == ["04_add_blank_lines.md"]


def test_pipeline_delete_with_multiple_blank_lines_layout(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "05_delete_blank_lines.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card


^anki-9003   DELETE


Back line
""",
        encoding="utf-8",
    )

    state_file = tmp_path / "sync_state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "9003": {
                        "content_hash": "old",
                        "updated_ts": "2026-03-01T00:00:00Z",
                        "source_file": "05_delete_blank_lines.md",
                        "h4_heading_pure": "Card",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)

    def _delete_ok(note_id: str):
        assert note_id == "9003"
        return True, None

    client.delete_note = _delete_ok

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=state_file,
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "^anki-9003" not in updated
    assert "#### Card\n\n^nosrs\n" in updated
    assert report.deleted == 1
    assert report.markdown_writebacks == ["05_delete_blank_lines.md"]


def test_pipeline_nosrs_with_multiple_blank_lines_is_skipped(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "06_nosrs_blank_lines.md"
    original = """---
ankideck: DeckA
---
### Parent
#### Card


^nosrs


Back line
"""
    md_file.write_text(original, encoding="utf-8")

    client = _make_client(tmp_path, apply_changes=True)

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("invoke should not be called for nosrs-only note")

    client.invoke = _unexpected_invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    assert report.skipped == 0
    assert md_file.read_text(encoding="utf-8") == original
    assert report.markdown_writebacks == []


def test_pipeline_delete_and_nosrs_conflict_with_blank_lines_prefers_delete(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "07_delete_nosrs_conflict.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card


^anki-9010 DELETE


^nosrs


Back line
""",
        encoding="utf-8",
    )

    state_file = tmp_path / "sync_state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "9010": {
                        "content_hash": "old",
                        "updated_ts": "2026-03-01T00:00:00Z",
                        "source_file": "07_delete_nosrs_conflict.md",
                        "h4_heading_pure": "Card",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)

    def _delete_ok(note_id: str):
        assert note_id == "9010"
        return True, None

    client.delete_note = _delete_ok

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=state_file,
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "^anki-9010" not in updated
    assert updated.count("^nosrs") == 1
    assert report.deleted == 1
    assert report.markdown_writebacks == ["07_delete_nosrs_conflict.md"]

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "9010" not in state["items"]


def test_pipeline_add_multiple_h4_in_single_file_writeback_positions(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "08_multi_h4_add.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card A
Body A

#### Card B
Body B

#### Card C
Body C
""",
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)
    next_id = {"value": 9200}

    def _invoke(action, **params):
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            next_id["value"] += 1
            return True, next_id["value"]
        if action == "updateNoteFields":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "#### Card A\n\n^anki-9201\n" in updated
    assert "#### Card B\n\n^anki-9202\n" in updated
    assert "#### Card C\n\n^anki-9203\n" in updated
    assert report.added == 3


def test_pipeline_add_multi_parent_groups_writeback_positions(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "09_multi_parent_add.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent A
#### QA1
Body A1

#### QA2
Body A2

### Parent B
#### QB1
Body B1
""",
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)
    next_id = {"value": 9300}

    def _invoke(action, **params):
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            next_id["value"] += 1
            return True, next_id["value"]
        if action == "updateNoteFields":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "#### QA1\n\n^anki-9301\n" in updated
    assert "#### QA2\n\n^anki-9302\n" in updated
    assert "#### QB1\n\n^anki-9303\n" in updated
    assert report.added == 3


def test_pipeline_media_prewarm_failure_stops_before_note_sync(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    (vault_root / "assets").mkdir(parents=True, exist_ok=True)
    (vault_root / "assets" / "x.png").write_bytes(b"png")

    md_file = vault_root / "10_media_fail.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card
![[x.png]]
""",
        encoding="utf-8",
    )

    client = _make_client(tmp_path, apply_changes=True)
    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action == "createDeck":
            return True, None
        if action == "storeMediaFile":
            return False, "simulated media failure"
        if action == "addNote":
            return True, 9999
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        sync_state_file=tmp_path / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
        anki_client=client,
    )

    assert report.failed == 1
    assert report.added == 0
    assert any("storeMediaFile failed" in err for err in report.errors)
    assert calls.count("addNote") == 0
