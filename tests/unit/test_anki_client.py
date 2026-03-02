from dataclasses import dataclass, field
from pathlib import Path

from md2anki.anki_client import AnkiClient


@dataclass
class FakeParsed:
    source_file: str = "a.md"
    line_idx_h4: int | None = 1
    deck_full: str = "Deck::Parent"
    h4_heading_pure: str = "Question"
    anki_note_id: str | None = None
    delete_requested: bool = False
    no_anki: bool = False


@dataclass
class FakeMedia:
    filename: str
    source_ref: str
    base64_data: str = "ZGF0YQ=="


@dataclass
class FakeRendered:
    parsed: FakeParsed
    front_html: str = "<p>F</p>"
    back_html_with_footer: str = "<p>B</p>"
    media_files: list[FakeMedia] = field(default_factory=list)


def _new_client(tmp_path: Path, apply_changes: bool = False) -> AnkiClient:
    return AnkiClient(
        anki_connect_url="http://127.0.0.1:8765",
        sync_state_file=tmp_path / "sync_state.json",
        apply_changes=apply_changes,
    )


def test_sync_dry_run_has_no_side_effects(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=False)

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("invoke should not be called in dry-run")

    client.invoke = _unexpected_invoke

    notes = [
        FakeRendered(parsed=FakeParsed(anki_note_id=None)),
        FakeRendered(parsed=FakeParsed(anki_note_id="123", delete_requested=True)),
        FakeRendered(parsed=FakeParsed(no_anki=True)),
    ]

    result = client.sync(notes)

    assert result.added == 0
    assert result.updated == 0
    assert result.deleted == 0
    assert result.failed == 0
    assert result.skipped == 1
    assert {item["action"] for item in result.dry_run_actions} == {"would_add", "would_delete", "skip_noanki"}
    assert not (tmp_path / "sync_state.json").exists()


def test_sync_add_creates_note_and_state(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=False)
    client.apply_changes = True
    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            return True, 321
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    note = FakeRendered(parsed=FakeParsed(), media_files=[FakeMedia(filename="a.png", source_ref="a.png")])

    result = client.sync([note])

    assert result.added == 1
    assert result.failed == 0
    assert result.bindings_to_writeback[0]["anki_note_id"] == "321"
    assert "321" in client.state["items"]
    assert (tmp_path / "sync_state.json").exists()
    assert calls == ["createDeck", "storeMediaFile", "addNote"]


def test_sync_skips_when_hash_unchanged(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=False)
    client.apply_changes = True
    note = FakeRendered(parsed=FakeParsed(anki_note_id="555"))
    digest = client.compute_content_hash(note)
    client.state["items"]["555"] = {
        "content_hash": digest,
        "updated_ts": "2026-03-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Question",
    }

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("invoke should not be called when hash unchanged")

    client.invoke = _unexpected_invoke

    result = client.sync([note])

    assert result.skipped == 1
    assert result.updated == 0


def test_sync_delete_success_removes_state_and_returns_writeback(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=False)
    client.apply_changes = True
    client.state["items"]["777"] = {
        "content_hash": "old",
        "updated_ts": "2026-03-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Question",
    }

    def _delete_ok(note_id: str):
        assert note_id == "777"
        return True, None

    client.delete_note = _delete_ok
    note = FakeRendered(parsed=FakeParsed(anki_note_id="777", delete_requested=True, line_idx_h4=10))

    result = client.sync([note])

    assert result.deleted == 1
    assert "777" not in client.state["items"]
    assert result.deletions_to_writeback == [{"source_file": "a.md", "line_idx_h4": 10, "anki_note_id": "777"}]


def test_sync_delete_missing_id_reports_failure(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=False)
    client.apply_changes = True
    note = FakeRendered(parsed=FakeParsed(anki_note_id=None, delete_requested=True))

    result = client.sync([note])

    assert result.failed == 1
    assert any("delete requested but missing anki_note_id" in err for err in result.errors)
