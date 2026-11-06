import copy
import json

import pytest

from md2anki.media_audit import audit_media, main
from mock_ankiconnect_server import MockAnkiConnectServer


@pytest.mark.parametrize("cloze", [False, True])
@pytest.mark.parametrize("scenario,expected", [
    ("ok", None),
    ("missing", "anki_media_missing"),
    ("case", "anki_media_case_mismatch"),
    ("content", "content_mismatch"),
    ("empty", "anki_media_empty"),
    ("unreferenced", "source_not_referenced_in_anki"),
    ("source_missing", "source_missing"),
])
def test_media_audit_reads_only_and_classifies_failures(tmp_path, cloze, scenario, expected):
    vault = tmp_path / "vault"
    assets = vault / "assets"
    assets.mkdir(parents=True)
    media = tmp_path / "collection.media"
    media.mkdir()
    if scenario != "source_missing":
        (assets / "Diagram.png").write_bytes(b"image")
    heading = "Recall {{c1::diagram}}" if cloze else "Question"
    md = vault / "note.md"
    content = f"---\nankideck: Test\n---\n#### {heading}\n\n^anki-1001\n\n![[Diagram.png|800]]\n"
    md.write_text(content, encoding="utf-8")
    if scenario != "missing":
        (media / "diagram.png").write_bytes(b"different" if scenario == "content" else b"" if scenario == "empty" else b"image")
    ref = "Diagram.png" if scenario == "case" else "diagram.png"
    html = "No image" if scenario == "unreferenced" else f'<img src="{ref}">'
    fields = {"Text": "{{c1::diagram}}" + html, "Back Extra": ""} if cloze else {"Front": "Question", "Back": html}
    with MockAnkiConnectServer() as server:
        server.state.add_note("Test", "Cloze" if cloze else "Basic", fields, note_id=1001)
        original = copy.deepcopy(server.state.notes)
        report = audit_media(vault, [md], media, server.url)

        assert {request["action"] for request in server.state.requests} == {"notesInfo"}
        assert server.state.notes == original
        assert md.read_text(encoding="utf-8") == content
        assert not (vault / ".md2anki-cache").exists()
        assert report["summary"]["source_image_refs"] == 1
        assert report["summary"]["notes_with_issues"] == (0 if expected is None else 1)
        if expected:
            assert expected in report["summary"]["issues"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_audit_uses_note_context_and_vault_fallback(tmp_path, ambiguous):
    vault = tmp_path / "vault"
    image = vault / "HDLBits/official/assets/Vector.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"vector")
    if ambiguous:
        duplicate = vault / "Other/Vector.png"
        duplicate.parent.mkdir()
        duplicate.write_bytes(b"other")
    media = tmp_path / "media"
    media.mkdir()
    (media / "vector.png").write_bytes(b"vector")
    md = vault / "HDLBits/cards.md"
    md.write_text("---\nankideck: Test\n---\n#### Question\n\n^anki-1001\n\n![[Vector.png]]\n", encoding="utf-8")
    with MockAnkiConnectServer() as server:
        server.state.add_note("Test", "Basic", {"Front": "Question", "Back": '<img src="vector.png">'}, note_id=1001)
        report = audit_media(vault, [md], media, server.url)
        assert report["summary"]["notes_with_issues"] == int(ambiguous)
        if ambiguous:
            assert report["summary"]["issues"] == {"source_ambiguous": 1}
        else:
            assert report["notes"][0]["source_images"][0]["path"] == str(image)
        md.write_text(md.read_text(encoding="utf-8").replace("![[Vector.png]]", "![[official/assets/Vector.png]]"), encoding="utf-8")
        report = audit_media(vault, [md], media, server.url)
        assert report["summary"]["notes_with_issues"] == 0


def test_audit_reports_unbound_and_missing_notes_and_writes_report(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    md = vault / "note.md"
    md.write_text("---\nankideck: Test\n---\n#### Missing\n\n^anki-1001\n\nAnswer\n\n#### New\nAnswer\n", encoding="utf-8")
    report_path = tmp_path / "report.json"
    with MockAnkiConnectServer() as server:
        result = main(["--vault-root", str(vault), "--file", "note.md", "--anki-media-dir", str(media),
                       "--anki-connect-url", server.url, "--report", str(report_path)])
        assert result == 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["summary"]["issues"] == {"note_missing": 1, "not_synced": 1}
        assert {request["action"] for request in server.state.requests} == {"notesInfo"}
