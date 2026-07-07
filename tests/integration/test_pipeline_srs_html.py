from pathlib import Path

from md2anki.pipeline import run_pipeline
from md2anki.srs_collection import SrsSyncResult


class CapturingSrsCollection:
    def __init__(self):
        self.rendered_notes = []

    def sync(self, rendered_notes, progress_callback=None):
        self.rendered_notes = list(rendered_notes)
        return SrsSyncResult(added=len(rendered_notes), files=[f"{note.parsed.srs_note_id}.html" for note in rendered_notes])


def test_pipeline_html_mode_generates_srs_ids_and_renders_srs_footer(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "cards.md"
    md_file.write_text(
        """---
ankideck: DeckA
---
### Parent
#### Card A
Answer A

#### Card B
Answer B
""",
        encoding="utf-8",
    )
    srs_collection = CapturingSrsCollection()
    monkeypatch.setattr("md2anki.pipeline.time.time", lambda: 1783400717.267)

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        output_mode="html",
        collection_root=tmp_path / "collection",
        srs_collection=srs_collection,
    )

    updated = md_file.read_text(encoding="utf-8")
    assert "^srs-1783400717267" in updated
    assert "^srs-1783400717268" in updated
    assert report.added == 2
    assert report.markdown_writebacks == ["cards.md"]
    assert [note.parsed.srs_note_id for note in srs_collection.rendered_notes] == ["1783400717267", "1783400717268"]
    assert "srs-1783400717267" in srs_collection.rendered_notes[0].obsidian_url
    assert "file=cards%23%5Esrs-1783400717267" in srs_collection.rendered_notes[0].back_html_with_footer


def test_pipeline_html_mode_reuses_existing_srs_id(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    md_file = vault_root / "cards.md"
    original = """---
ankideck: DeckA
---
### Parent
#### Card A
^srs-1783400717267
Answer A
"""
    md_file.write_text(original, encoding="utf-8")
    srs_collection = CapturingSrsCollection()

    report = run_pipeline(
        markdown_files=[md_file],
        vault_root=vault_root,
        vault_name="sample-notes",
        output_mode="html",
        collection_root=tmp_path / "collection",
        srs_collection=srs_collection,
    )

    assert md_file.read_text(encoding="utf-8") == original
    assert report.markdown_writebacks == []
    assert [note.parsed.srs_note_id for note in srs_collection.rendered_notes] == ["1783400717267"]
