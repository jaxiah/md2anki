import json
import os
from dataclasses import asdict
from pathlib import Path

from md2anki import HtmlRenderer, MarkdownProcessor


FIXTURE_VAULT = Path(__file__).resolve().parent.parent / "fixtures" / "parser_renderer" / "vault"

DUMP_INTEGRATION_PARSER_JSON = os.getenv("DUMP_INTEGRATION_PARSER_JSON", "1") == "1"
DUMP_INTEGRATION_RENDERER_HTML = os.getenv("DUMP_INTEGRATION_RENDERER_HTML", "1") == "1"
INTEGRATION_DUMP_DIR = Path(__file__).resolve().parent / "_parser_renderer_debug"
PARSER_DUMP_DIR = INTEGRATION_DUMP_DIR / "parser"
RENDERER_DUMP_DIR = INTEGRATION_DUMP_DIR / "renderer"


def _build_pipeline():
    processor = MarkdownProcessor(vault_root=FIXTURE_VAULT)
    renderer = HtmlRenderer(vault_name="sample-notes", vault_root=FIXTURE_VAULT, asset_root="assets")
    return processor, renderer


def _dump_parser_result(case_name: str, doc) -> None:
    if not DUMP_INTEGRATION_PARSER_JSON:
        return

    PARSER_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "case": case_name,
        "source_file": doc.source_file,
        "frontmatter": doc.frontmatter,
        "warnings": doc.warnings,
        "notes": [asdict(note) for note in doc.notes],
    }
    (PARSER_DUMP_DIR / f"{case_name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _dump_renderer_result(case_name: str, rendered_notes: list) -> None:
    if not DUMP_INTEGRATION_RENDERER_HTML:
        return

    RENDERER_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    note_sections: list[str] = []
    for idx, rendered in enumerate(rendered_notes, start=1):
        warning_html = "<br/>".join(rendered.warnings) if rendered.warnings else "(none)"
        media_items = "".join(
            f"<li>{item.filename} | {item.source_ref} | {item.abs_path} | base64_len={len(item.base64_data)}</li>" for item in rendered.media_files
        )
        if not media_items:
            media_items = "<li>(none)</li>"

        note_sections.append(
            f"""
    <section>
      <h2>Note {idx}: {rendered.parsed.source_file}</h2>
      <h3>Front HTML</h3>
      {rendered.front_html}
      <h3>Back HTML</h3>
      {rendered.back_html}
      <h3>Back HTML With Footer</h3>
      {rendered.back_html_with_footer}
      <h3>Warnings</h3>
      <pre>{warning_html}</pre>
      <h3>Media Files</h3>
      <ul>{media_items}</ul>
    </section>
"""
        )

    html_doc = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <title>{case_name}</title>
    <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['\\\\(', '\\\\)']],
                displayMath: [['\\\\[', '\\\\]']]
            }}
        }};
    </script>
    <script defer src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js\"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 1.5rem; }}
        section {{ margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid #ddd; }}
        pre {{ background: #f6f8fa; padding: 0.75rem; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <h1>{case_name}</h1>
    {''.join(note_sections)}
</body>
</html>
"""

    (RENDERER_DUMP_DIR / f"{case_name}.html").write_text(html_doc, encoding="utf-8")


def _dump_case_result(case_name: str, doc, rendered_notes: list) -> None:
    _dump_parser_result(case_name, doc)
    _dump_renderer_result(case_name, rendered_notes)


def test_basic_note_extraction_and_rendering():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "01_basic.md")

    assert len(doc.notes) == 2

    note1 = doc.notes[0]
    assert note1.deck_full == "DeckA::Parent One"
    assert note1.parent_level == 3
    assert note1.parent_block_id == "id-p111aaaa"
    assert note1.anki_note_id == "1001"

    rendered1 = renderer.render(note1)
    assert "Card One" in rendered1.front_html
    assert "Front detail" in rendered1.front_html
    assert "Back detail" in rendered1.back_html

    note2 = doc.notes[1]
    rendered2 = renderer.render(note2)
    assert "<ul>" in rendered2.back_html
    assert "item 1" in rendered2.back_html

    _dump_case_result("basic_note_extraction_and_rendering", doc, [rendered1, rendered2])


def test_parent_fallback_to_h2_is_extracted_correctly():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "02_parent_fallback_h2.md")

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.parent_level == 2
    assert note.parent_title == "Section Parent"
    assert note.deck_full == "DeckB::Section Parent"

    rendered = renderer.render(note)
    assert "Body text." in rendered.back_html

    _dump_case_result("parent_fallback_to_h2_is_extracted_correctly", doc, [rendered])


def test_math_and_code_block_rendering_pipeline():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "03_math_code.md")

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.anki_note_id == "2001"

    rendered = renderer.render(note)
    assert "\\(E=mc^2\\)" in rendered.back_html
    assert "\\[" in rendered.back_html
    assert "x^2 + y^2 = z^2" in rendered.back_html
    assert "<pre><code" in rendered.back_html
    assert "def add" in rendered.back_html

    _dump_case_result("math_and_code_block_rendering_pipeline", doc, [rendered])


def test_lists_table_link_and_image_rendering_pipeline():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "04_lists_table_link_image.md")

    assert len(doc.notes) == 1
    note = doc.notes[0]
    rendered = renderer.render(note)

    assert "<ul>" in rendered.back_html
    assert "<table>" in rendered.back_html
    assert "obsidian://open?vault=sample-notes&file=Knowledge/Topic%20A" in rendered.back_html
    assert ">TopicA<" in rendered.back_html
    assert '<img src="diagram.png" width="280">' in rendered.back_html
    assert '<img src="plot.png">' in rendered.back_html

    media_names = [item.filename for item in rendered.media_files]
    assert "diagram.png" in media_names
    assert "plot.png" in media_names

    _dump_case_result("lists_table_link_and_image_rendering_pipeline", doc, [rendered])


def test_ambiguous_image_resolution_warns_but_renders():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "05_ambiguous_image.md")

    assert len(doc.notes) == 1
    rendered = renderer.render(doc.notes[0])

    assert '<img src="dup.png">' in rendered.back_html
    assert any("Image ambiguous: dup.png" in warning for warning in rendered.warnings)

    _dump_case_result("ambiguous_image_resolution_warns_but_renders", doc, [rendered])


def test_blank_lines_between_header_and_metadata_are_handled_end_to_end():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "06_blank_lines_metadata.md")

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.parent_level == 2
    assert note.parent_block_id == "id-blank2222"
    assert note.anki_note_id == "6001"
    assert "^anki-6001" not in note.back_md

    rendered = renderer.render(note)
    assert "Line one" in rendered.back_html
    assert "file=06_blank_lines_metadata%23%5Eid-blank2222" in rendered.back_html_with_footer

    _dump_case_result("blank_lines_between_header_and_metadata_are_handled_end_to_end", doc, [rendered])


def test_noanki_marked_h4_is_skipped_from_parser_renderer_flow():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "07_noanki.md")

    assert len(doc.notes) == 0

    _dump_case_result("noanki_marked_h4_is_skipped_from_parser_renderer_flow", doc, [])


def test_h4_without_parent_uses_base_deck_and_file_stem_footer():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "08_h4_without_parent.md")

    assert len(doc.notes) == 2
    for note in doc.notes:
        assert note.parent_title is None
        assert note.parent_level is None
        assert note.deck_full == "DeckNoParent"

    rendered_notes = [renderer.render(note) for note in doc.notes]
    assert ">08_h4_without_parent<" in rendered_notes[0].back_html_with_footer
    assert "file=08_h4_without_parent" in rendered_notes[0].back_html_with_footer

    _dump_case_result("h4_without_parent_uses_base_deck_and_file_stem_footer", doc, rendered_notes)


def test_h4_without_parent_in_subdir_uses_subfile_stem_footer():
    processor, renderer = _build_pipeline()
    doc = processor.parse_file(FIXTURE_VAULT / "sub" / "09_h4_without_parent_sub.md")

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.parent_title is None
    assert note.deck_full == "DeckNoParentSub"

    rendered = renderer.render(note)
    assert ">09_h4_without_parent_sub<" in rendered.back_html_with_footer
    assert "file=sub/09_h4_without_parent_sub" in rendered.back_html_with_footer

    _dump_case_result("h4_without_parent_in_subdir_uses_subfile_stem_footer", doc, [rendered])
