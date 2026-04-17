import json
import os
from dataclasses import asdict
from pathlib import Path

from md2anki import MarkdownProcessor


def _new_processor() -> MarkdownProcessor:
    return MarkdownProcessor(vault_root=Path("."))


DUMP_PARSED_NOTE_JSON = os.getenv("DUMP_PARSED_NOTE_JSON", "1") == "1"
PARSED_NOTE_DUMP_DIR = Path(__file__).resolve().parent / "_parsed_note_json"


def _dump_doc(case_name: str, content: str, doc):
    if not DUMP_PARSED_NOTE_JSON:
        return
    PARSED_NOTE_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "case": case_name,
        "raw_md": content,
        "raw_md_lines": content.splitlines(),
        "source_file": doc.source_file,
        "frontmatter": doc.frontmatter,
        "warnings": doc.warnings,
        "notes": [asdict(note) for note in doc.notes],
    }
    output_file = PARSED_NOTE_DUMP_DIR / f"{case_name}.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_case(case_name: str, content: str, source_file: str = "sample.md"):
    doc = _new_processor().parse_content(content, source_file=source_file)
    _dump_doc(case_name, content, doc)
    return doc


def test_parse_skips_when_ankideck_missing():
    content = """# Title

### Parent
#### Question
Answer
"""
    doc = _parse_case("parse_skips_when_ankideck_missing", content)

    assert doc.notes == []
    assert doc.warnings == []


def test_parse_h3_h4_and_separator():
    content = """---
ankideck: ABC
---
### Parent Topic
#### Question A
^anki-123
front extra
---
back line 1
back line 2
#### Question B
back only
"""
    doc = _parse_case("parse_h3_h4_and_separator", content)

    assert len(doc.notes) == 2

    note1 = doc.notes[0]
    assert note1.deck_full == "ABC::Parent Topic"
    assert note1.parent_title == "Parent Topic"
    assert note1.parent_level == 3
    assert note1.anki_note_id == "123"
    assert note1.front_md == "Question A\n\nfront extra"
    assert note1.back_md == "back line 1\nback line 2"
    assert note1.split_by_separator is True

    note2 = doc.notes[1]
    assert note2.deck_full == "ABC::Parent Topic"
    assert note2.anki_note_id is None
    assert note2.front_md == "Question B"
    assert note2.back_md == "back only"


def test_setext_like_separator_does_not_break_next_heading_detection():
    content = """---
ankideck: Deck
---
### Parent
#### Q1
context line
---
answer line
#### Q2
answer2
"""
    doc = _parse_case("setext_like_separator", content)

    assert len(doc.notes) == 2
    assert doc.notes[0].front_md == "Q1\n\ncontext line"
    assert doc.notes[0].back_md == "answer line"
    assert doc.notes[1].front_md == "Q2"


def test_parse_without_h3_uses_base_deck_only():
    content = """---
ankideck: Solo
---
#### Standalone Question
Standalone Answer
"""
    doc = _parse_case("parse_without_h3_uses_base_deck_only", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].parent_title is None
    assert doc.notes[0].parent_level is None
    assert doc.notes[0].deck_full == "Solo"


def test_parse_yaml_error_adds_warning_and_skips_notes():
    content = """---
ankideck: [broken
---
### Parent
#### Q
A
"""
    doc = _parse_case("parse_yaml_error", content)

    assert len(doc.notes) == 0
    assert any(msg.startswith("YAML parse error:") for msg in doc.warnings)


def test_separator_with_spaces_is_recognized():
    content = """---
ankideck: SpaceDeck
---
### Parent
#### Q spaced
front line
  ---
back line
"""
    doc = _parse_case("separator_with_spaces", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].split_by_separator is True
    assert doc.notes[0].front_md == "Q spaced\n\nfront line"
    assert doc.notes[0].back_md == "back line"


def test_multiple_h3_groups_map_to_correct_subdecks():
    content = """---
ankideck: GroupDeck
---
### Group A
#### QA1
A1
### Group B
#### QB1
B1
"""
    doc = _parse_case("multiple_h3_groups", content)

    assert len(doc.notes) == 2
    assert doc.notes[0].deck_full == "GroupDeck::Group A"
    assert doc.notes[1].deck_full == "GroupDeck::Group B"


def test_h4_suffix_anki_id_parsed_and_heading_purified():
    content = """---
ankideck: IDS
---
### Parent
#### What is this?
^anki-999001
Answer body
"""
    doc = _parse_case("h4_suffix_anki_id", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].anki_note_id == "999001"
    assert doc.notes[0].h4_heading_pure == "What is this?"
    assert doc.notes[0].h4_heading_raw == "What is this?"


def test_parse_anki_id_allows_blank_lines_before_id_and_not_in_body():
    content = """---
ankideck: D
---
### Parent
#### Q with gaps


^anki-777888
answer line 1
answer line 2
"""
    doc = _parse_case("anki_id_with_blank_lines", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].anki_note_id == "777888"
    assert "^anki-777888" not in doc.notes[0].back_md
    assert doc.notes[0].back_md == "answer line 1\nanswer line 2"


def test_parse_file_returns_relative_source_path():
    content = """---
ankideck: ABC
---
### Parent
#### Q
A
"""
    path = Path("temp_parse_file_case.md")
    path.write_text(content, encoding="utf-8")
    try:
        doc = _new_processor().parse_file(path)
    finally:
        path.unlink(missing_ok=True)

    assert doc.source_file.endswith("temp_parse_file_case.md")


def test_h4_uses_nearest_parent_h2_when_h3_absent():
    content = """---
ankideck: D
---
## Topic H2
#### Q
A
"""
    doc = _parse_case("h4_uses_h2_parent", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].parent_title == "Topic H2"
    assert doc.notes[0].parent_level == 2
    assert doc.notes[0].deck_full == "D::Topic H2"


def test_h4_uses_nearest_parent_h1_when_h2_h3_absent():
    content = """---
ankideck: D
---
# Topic H1
#### Q
A
"""
    doc = _parse_case("h4_uses_h1_parent", content)

    assert len(doc.notes) == 1
    assert doc.notes[0].parent_title == "Topic H1"
    assert doc.notes[0].parent_level == 1
    assert doc.notes[0].deck_full == "D::Topic H1"


def test_append_anki_id_at_line_returns_false_on_out_of_range():
    lines = ["#### Q\n"]
    processor = _new_processor()

    wrote = processor.append_anki_id_at_line(lines, 9, "111")
    assert wrote is False
    assert lines[0].strip() == "#### Q"


def test_append_anki_id_to_line_creates_standalone_id_line():
    processor = _new_processor()
    line = "#### Q\n"

    updated = processor.append_anki_id_to_line(line, "999")
    assert updated == "^anki-999\n"


def test_append_anki_id_at_line_noop_when_next_line_already_has_id():
    lines = ["#### Q\n", "\n", "\n", "^anki-123\n", "answer\n"]
    processor = _new_processor()

    wrote = processor.append_anki_id_at_line(lines, 0, "999")
    assert wrote is False
    assert lines[3].strip() == "^anki-123"


def test_parse_delete_requested_from_anki_meta_line():
    content = """---
ankideck: D
---
### Parent
#### Q
^anki-123456 delete
answer
"""
    doc = _parse_case("parse_delete_requested", content)

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.anki_note_id == "123456"
    assert note.delete_requested is True
    assert note.no_anki is False
    assert note.anki_meta_line_idx is not None
    assert "^anki-123456" not in note.back_md


def test_parse_noanki_skips_h4_note():
    content = """---
ankideck: D
---
### Parent
#### Q
^noanki
answer
"""
    doc = _parse_case("parse_noanki_skips", content)

    assert len(doc.notes) == 0


def test_parse_noanki_and_delete_keeps_note_for_delete_flow():
    content = """---
ankideck: D
---
### Parent
#### Q
^anki-123456 DELETE
^noanki
answer
"""
    doc = _parse_case("parse_noanki_and_delete", content)

    assert len(doc.notes) == 1
    note = doc.notes[0]
    assert note.anki_note_id == "123456"
    assert note.delete_requested is True
    assert note.no_anki is True
    assert "^noanki" not in note.back_md


def test_remove_anki_metadata_and_mark_noanki():
    lines = ["#### Q\n", "\n", "^anki-123456 DELETE\n", "body\n"]
    processor = _new_processor()

    changed = processor.remove_anki_metadata_and_mark_noanki(lines, 0)

    assert changed is True
    assert all("^anki-123456" not in line for line in lines)
    assert any(line.strip() == "^noanki" for line in lines)


def test_append_anki_id_at_line_noop_when_noanki_exists():
    lines = ["#### Q\n", "\n", "^noanki\n", "answer\n"]
    processor = _new_processor()

    wrote = processor.append_anki_id_at_line(lines, 0, "777")

    assert wrote is False
    assert all("^anki-777" not in line for line in lines)
