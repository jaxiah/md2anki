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
