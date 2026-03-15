from dataclasses import dataclass, field
from pathlib import Path

import requests

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
    abs_path: str | None = None


@dataclass
class FakeRendered:
    parsed: FakeParsed
    front_html: str = "<p>F</p>"
    back_html_with_footer: str = "<p>B</p>"
    media_files: list[FakeMedia] = field(default_factory=list)


def _new_client(tmp_path: Path, apply_changes: bool = False) -> AnkiClient:
    client = AnkiClient(
        anki_connect_url="http://127.0.0.1:8765",
        sync_state_file=tmp_path / "sync_state.json",
        apply_changes=False,
    )
    client.apply_changes = apply_changes
    return client


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
        "deck_full": "Deck::Parent",  # matches note.parsed.deck_full → fully skipped
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


def test_sync_media_upload_is_deduplicated_across_notes(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            return True, 1000 + len([x for x in calls if x == "addNote"])
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    shared_media = FakeMedia(filename="same.png", source_ref="same.png", base64_data="ZGF0YQ==")
    note1 = FakeRendered(parsed=FakeParsed(h4_heading_pure="Q1"), media_files=[shared_media])
    note2 = FakeRendered(parsed=FakeParsed(h4_heading_pure="Q2"), media_files=[shared_media])

    result = client.sync([note1, note2])

    assert result.added == 2
    assert calls.count("storeMediaFile") == 1


def test_sync_fail_fast_stops_after_first_failure(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    client.fail_fast = True

    def _invoke(action, **params):
        if action == "createDeck":
            return True, None
        if action == "addNote":
            return False, "simulated add failure"
        return True, None

    client.invoke = _invoke

    notes = [
        FakeRendered(parsed=FakeParsed(h4_heading_pure="Q1")),
        FakeRendered(parsed=FakeParsed(h4_heading_pure="Q2")),
    ]
    result = client.sync(notes)

    assert result.failed == 1
    assert result.added == 0
    assert len(result.errors) == 1


def test_invoke_retries_on_timeout(monkeypatch, tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    client.max_retries = 2
    client.retry_backoff_seconds = 0
    client.request_timeout_seconds = 1

    attempts = {"count": 0}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"error": None, "result": 123}

    def _post(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise requests.exceptions.Timeout("timeout")
        return _Resp()

    monkeypatch.setattr("md2anki.anki_client.requests.post", _post)

    ok, result = client.invoke("deckNamesAndIds")

    assert ok is True
    assert result == 123
    assert attempts["count"] == 3


def test_prewarm_then_sync_skips_store_media(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "storeMediaFile"}:
            return True, None
        if action == "addNote":
            return True, 888
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke

    media = FakeMedia(filename="x.png", source_ref="x.png", base64_data="AAAA")
    note = FakeRendered(parsed=FakeParsed(), media_files=[media])

    prewarm = client.prewarm_media([note])
    result = client.sync([note], skip_media_upload=True)

    assert prewarm.uploaded == 1
    assert prewarm.failed == 0
    assert result.added == 1
    assert calls.count("storeMediaFile") == 1


def test_media_upload_prefers_path_when_available(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    captured_params = {}

    def _invoke(action, **params):
        if action == "storeMediaFile":
            captured_params.update(params)
            return True, None
        return True, None

    client.invoke = _invoke

    media = FakeMedia(filename="big.gif", source_ref="big.gif", base64_data="AAAA", abs_path="D:/x/big.gif")
    result = client.prewarm_media([FakeRendered(parsed=FakeParsed(), media_files=[media])])

    assert result.uploaded == 1
    assert captured_params.get("path") == "D:/x/big.gif"
    assert "data" not in captured_params


def test_media_upload_falls_back_to_data_when_path_fails(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    store_calls: list[dict] = []

    def _invoke(action, **params):
        if action == "storeMediaFile":
            store_calls.append(params)
            if "path" in params:
                return False, "path failed"
            return True, None
        return True, None

    client.invoke = _invoke

    media = FakeMedia(filename="big.gif", source_ref="big.gif", base64_data="AAAA", abs_path="D:/x/big.gif")
    result = client.prewarm_media([FakeRendered(parsed=FakeParsed(), media_files=[media])])

    assert result.uploaded == 1
    assert len(store_calls) == 2
    assert "path" in store_calls[0]
    assert "data" in store_calls[1]


def test_media_timeout_then_verify_uploaded_counts_success(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)

    def _invoke(action, **params):
        if action == "storeMediaFile":
            return False, "Read timed out. (read timeout=30.0)"
        if action == "retrieveMediaFile":
            return True, "R0lGODlh"
        return True, None

    client.invoke = _invoke

    media = FakeMedia(filename="big.gif", source_ref="big.gif", base64_data="AAAA", abs_path="D:/x/big.gif")
    result = client.prewarm_media([FakeRendered(parsed=FakeParsed(), media_files=[media])])

    assert result.failed == 0
    assert result.uploaded == 1


def test_prewarm_progress_reports_upload_mode(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    statuses: list[str] = []

    def _invoke(action, **params):
        if action == "storeMediaFile":
            return True, None
        return True, None

    def _progress(stage, current, total, name, status):
        if stage == "media":
            statuses.append(status)

    client.invoke = _invoke

    media = FakeMedia(filename="ok.png", source_ref="ok.png", base64_data="AAAA", abs_path="D:/x/ok.png")
    result = client.prewarm_media([FakeRendered(parsed=FakeParsed(), media_files=[media])], progress_callback=_progress)

    assert result.uploaded == 1
    assert statuses == ["uploaded(path)"]


# ---------------------------------------------------------------------------
# Deck move: state schema
# ---------------------------------------------------------------------------


def test_sync_add_stores_deck_full_in_state(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)

    def _invoke(action, **params):
        if action == "createDeck":
            return True, None
        if action == "addNote":
            return True, 500
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    note = FakeRendered(parsed=FakeParsed(deck_full="MyDeck::Chapter1"))

    result = client.sync([note])

    assert result.added == 1
    assert client.state["items"]["500"]["deck_full"] == "MyDeck::Chapter1"


def test_sync_update_stores_deck_full_in_state(tmp_path: Path):
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="600", deck_full="MyDeck::Chapter1"))
    # pre-populate state with a different hash so update branch fires, same deck
    client.state["items"]["600"] = {
        "content_hash": "stale",
        "deck_full": "MyDeck::Chapter1",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    def _invoke(action, **params):
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert client.state["items"]["600"]["deck_full"] == "MyDeck::Chapter1"


# ---------------------------------------------------------------------------
# Deck move: skip condition
# ---------------------------------------------------------------------------


def test_sync_skip_unchanged_when_deck_full_matches_state(tmp_path: Path):
    """Hash unchanged + deck matches state → card is skipped."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="700", deck_full="Deck::A"))
    digest = client.compute_content_hash(note)
    client.state["items"]["700"] = {
        "content_hash": digest,
        "deck_full": "Deck::A",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    def _unexpected_invoke(*args, **kwargs):
        raise AssertionError("invoke should not be called")

    client.invoke = _unexpected_invoke
    result = client.sync([note])

    assert result.skipped == 1
    assert result.updated == 0


def test_sync_deck_only_move_for_legacy_state_without_deck_full(tmp_path: Path):
    """Legacy state without deck_full: content unchanged but deck-only move is triggered."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="701", deck_full="Deck::A"))
    digest = client.compute_content_hash(note)
    client.state["items"]["701"] = {
        "content_hash": digest,
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
        # no "deck_full" key → legacy
    }

    calls: list[tuple] = []

    def _invoke(action, **params):
        calls.append((action, params))
        if action == "createDeck":
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [9001]}]
        if action == "changeDeck":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert result.skipped == 0
    action_names = [c[0] for c in calls]
    assert "updateNoteFields" not in action_names
    assert "changeDeck" in action_names
    assert client.state["items"]["701"]["deck_full"] == "Deck::A"


# ---------------------------------------------------------------------------
# Deck move: happy path
# ---------------------------------------------------------------------------


def test_sync_update_moves_deck_when_deck_changed(tmp_path: Path):
    """Deck changes → notesInfo + changeDeck invoked; state updated with new deck."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="800", deck_full="Deck::NewParent"))
    new_hash = client.compute_content_hash(note)
    client.state["items"]["800"] = {
        "content_hash": "stale",
        "deck_full": "Deck::OldParent",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    calls: list[tuple] = []

    def _invoke(action, **params):
        calls.append((action, params))
        if action == "createDeck":
            return True, None
        if action == "updateNoteFields":
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [1001, 1002]}]
        if action == "changeDeck":
            assert params["cards"] == [1001, 1002]
            assert params["deck"] == "Deck::NewParent"
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert result.failed == 0
    assert result.errors == []
    action_names = [c[0] for c in calls]
    assert "notesInfo" in action_names
    assert "changeDeck" in action_names
    assert client.state["items"]["800"]["deck_full"] == "Deck::NewParent"


def test_sync_update_no_deck_move_when_deck_unchanged(tmp_path: Path):
    """State has same deck as current note → changeDeck must NOT be called."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="801", deck_full="Deck::Same"))
    client.state["items"]["801"] = {
        "content_hash": "stale",
        "deck_full": "Deck::Same",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert "changeDeck" not in calls
    assert "notesInfo" not in calls


def test_sync_update_triggers_deck_move_when_legacy_state_has_no_deck(tmp_path: Path):
    """Content changed + legacy state without deck_full → fields updated AND deck move triggered."""
    client = _new_client(tmp_path, apply_changes=True)
    # old hash was computed with OldParent deck; new note has NewParent (hash will differ)
    old_note = FakeRendered(parsed=FakeParsed(anki_note_id="802", deck_full="Deck::OldParent"))
    old_hash = client.compute_content_hash(old_note)
    client.state["items"]["802"] = {
        "content_hash": old_hash,  # stale → will trigger update
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
        # no deck_full key → legacy; old_deck will be None → triggers move
    }

    note = FakeRendered(parsed=FakeParsed(anki_note_id="802", deck_full="Deck::NewParent"))
    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [8001]}]
        if action == "changeDeck":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert result.failed == 0
    assert "changeDeck" in calls
    assert client.state["items"]["802"]["deck_full"] == "Deck::NewParent"


# ---------------------------------------------------------------------------
# Deck move: failure handling and retry
# ---------------------------------------------------------------------------


def test_sync_deck_move_failure_retains_old_deck_in_state(tmp_path: Path):
    """changeDeck failure → state keeps old deck_full so next sync can retry."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="900", deck_full="Deck::New"))
    client.state["items"]["900"] = {
        "content_hash": "stale",
        "deck_full": "Deck::Old",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    def _invoke(action, **params):
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [2001]}]
        if action == "changeDeck":
            return False, "AnkiConnect timeout"
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    client.sync([note])

    assert client.state["items"]["900"]["deck_full"] == "Deck::Old"


def test_sync_deck_move_failure_reports_error_but_counts_as_updated(tmp_path: Path):
    """changeDeck failure → updated counter still incremented, error appended."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="901", deck_full="Deck::New"))
    client.state["items"]["901"] = {
        "content_hash": "stale",
        "deck_full": "Deck::Old",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    def _invoke(action, **params):
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [2002]}]
        if action == "changeDeck":
            return False, "deck move error"
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert result.failed == 0
    assert len(result.errors) == 1
    assert "changeDeck failed" in result.errors[0]
    assert "Deck::Old" in result.errors[0]
    assert "Deck::New" in result.errors[0]


def test_sync_deck_move_failure_triggers_retry_on_next_sync(tmp_path: Path):
    """After a failed move (state: new hash + old deck), next sync is NOT skipped and retries."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="902", deck_full="Deck::New"))
    new_hash = client.compute_content_hash(note)

    # Simulate state left by a previous sync where move failed:
    # content_hash was updated (fields are correct) but deck is still old.
    client.state["items"]["902"] = {
        "content_hash": new_hash,
        "deck_full": "Deck::Old",  # move failed previously
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action in {"createDeck", "updateNoteFields"}:
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [3001]}]
        if action == "changeDeck":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.skipped == 0
    assert result.updated == 1
    # deck-only move path: no updateNoteFields needed (content unchanged)
    assert "updateNoteFields" not in calls
    assert "changeDeck" in calls
    assert client.state["items"]["902"]["deck_full"] == "Deck::New"


# ---------------------------------------------------------------------------
# Deck-only move: new code path (content unchanged, deck changed)
# ---------------------------------------------------------------------------


def test_sync_deck_only_move_when_content_unchanged_but_deck_changed(tmp_path: Path):
    """Hash unchanged but deck changed → only changeDeck, no updateNoteFields."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="850", deck_full="Deck::NewParent"))
    digest = client.compute_content_hash(note)
    client.state["items"]["850"] = {
        "content_hash": digest,
        "deck_full": "Deck::OldParent",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    calls: list[str] = []

    def _invoke(action, **params):
        calls.append(action)
        if action == "createDeck":
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [5001]}]
        if action == "changeDeck":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 1
    assert result.skipped == 0
    assert "updateNoteFields" not in calls
    assert "changeDeck" in calls
    assert client.state["items"]["850"]["deck_full"] == "Deck::NewParent"


def test_sync_deck_only_move_failure_keeps_old_deck_and_appends_error(tmp_path: Path):
    """Deck-only move failure: old deck kept in state, error appended, updated not incremented."""
    client = _new_client(tmp_path, apply_changes=True)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="851", deck_full="Deck::NewParent"))
    digest = client.compute_content_hash(note)
    client.state["items"]["851"] = {
        "content_hash": digest,
        "deck_full": "Deck::OldParent",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    def _invoke(action, **params):
        if action == "createDeck":
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [5002]}]
        if action == "changeDeck":
            return False, "network timeout"
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    result = client.sync([note])

    assert result.updated == 0
    assert result.failed == 0
    assert len(result.errors) == 1
    assert "changeDeck failed" in result.errors[0]
    assert client.state["items"]["851"]["deck_full"] == "Deck::OldParent"


def test_sync_dry_run_records_would_move_deck_when_hash_unchanged(tmp_path: Path):
    """Dry-run: hash unchanged but deck differs → would_move_deck action recorded."""
    client = _new_client(tmp_path, apply_changes=False)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="960", deck_full="Deck::New"))
    digest = client.compute_content_hash(note)
    client.state["items"]["960"] = {
        "content_hash": digest,
        "deck_full": "Deck::Old",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    result = client.sync([note])

    assert len(result.dry_run_actions) == 1
    action = result.dry_run_actions[0]
    assert action["action"] == "would_move_deck"
    assert action["deck_move"] is True
    assert action["old_deck"] == "Deck::Old"
    assert action["new_deck"] == "Deck::New"


# ---------------------------------------------------------------------------
# Deck move: _move_note_to_deck unit test
# ---------------------------------------------------------------------------


def test_move_note_to_deck_calls_notesinfo_then_changedeck(tmp_path: Path):
    """_move_note_to_deck fetches card IDs via notesInfo then calls changeDeck."""
    client = _new_client(tmp_path, apply_changes=True)
    calls: list[tuple] = []

    def _invoke(action, **params):
        calls.append((action, params))
        if action == "createDeck":
            return True, None
        if action == "notesInfo":
            return True, [{"cards": [456, 789]}]
        if action == "changeDeck":
            return True, None
        raise AssertionError(f"unexpected action: {action}")

    client.invoke = _invoke
    ok, err = client._move_note_to_deck("123", "Deck::Target")

    assert ok is True
    assert err is None
    action_names = [c[0] for c in calls]
    assert action_names == ["createDeck", "notesInfo", "changeDeck"]
    notes_info_params = calls[1][1]
    assert notes_info_params["notes"] == [123]
    change_deck_params = calls[2][1]
    assert change_deck_params["cards"] == [456, 789]
    assert change_deck_params["deck"] == "Deck::Target"


# ---------------------------------------------------------------------------
# Deck move: dry-run reporting
# ---------------------------------------------------------------------------


def test_sync_dry_run_records_deck_move_in_action(tmp_path: Path):
    """Dry-run would_update action includes deck_move=True when deck changed."""
    client = _new_client(tmp_path, apply_changes=False)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="950", deck_full="Deck::New"))
    new_hash = client.compute_content_hash(note)
    # Deck differs from state even though hash is stale (content also changed for simplicity)
    client.state["items"]["950"] = {
        "content_hash": "stale",
        "deck_full": "Deck::Old",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    result = client.sync([note])

    assert len(result.dry_run_actions) == 1
    action = result.dry_run_actions[0]
    assert action["action"] == "would_update"
    assert action["deck_move"] is True
    assert action["old_deck"] == "Deck::Old"
    assert action["new_deck"] == "Deck::New"


def test_sync_dry_run_no_deck_move_flag_when_deck_unchanged(tmp_path: Path):
    """Dry-run would_update action has deck_move=False when deck unchanged."""
    client = _new_client(tmp_path, apply_changes=False)
    note = FakeRendered(parsed=FakeParsed(anki_note_id="951", deck_full="Deck::Same"))
    client.state["items"]["951"] = {
        "content_hash": "stale",
        "deck_full": "Deck::Same",
        "updated_ts": "2026-01-01T00:00:00Z",
        "source_file": "a.md",
        "h4_heading_pure": "Q",
    }

    result = client.sync([note])

    assert len(result.dry_run_actions) == 1
    action = result.dry_run_actions[0]
    assert action["deck_move"] is False
    assert action["old_deck"] is None
    assert action["new_deck"] is None
