import json
import re
from pathlib import Path

from md2anki import run_pipeline

from mock_ankiconnect_server import MockAnkiConnectServer


def _write_vault(vault_root: Path) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    (vault_root / "assets").mkdir(parents=True, exist_ok=True)
    (vault_root / "assets" / "diagram.png").write_bytes(b"diagram")
    (vault_root / "assets" / "plot.png").write_bytes(b"plot")
    (vault_root / "assets" / "dup.png").write_bytes(b"dup")

    (vault_root / "01_flow.md").write_text(
        """---
ankideck: md2ankiTest::Flow
---

### Parent Flow

#### Card AddUpdate

Update baseline line.

#### Card DeleteTarget

Delete baseline line.

#### Card ConflictTarget

Conflict baseline line.

### Parent Extra

#### Card MultiParent

Extra parent baseline line.
""",
        encoding="utf-8",
    )
    (vault_root / "02_media_math.md").write_text(
        """---
ankideck: md2ankiTest::MediaMath
---

### Parent Media Math

#### Card MediaMath

front hint line

---

- list item 1
- list item 2

| a | b |
|---|---|
| 1 | 2 |

inline math: $E=mc^2$

display math:
$$
x^2 + y^2 = z^2
$$

code:
```python
def add(a, b):
    return a + b
```

link: [[Knowledge/Topic A|TopicA]]

images:
![[diagram.png|280]]
![[plot.png]]
![[dup.png]]
""",
        encoding="utf-8",
    )
    (vault_root / "03_blank_lines.md").write_text(
        """---
ankideck: md2ankiTest::BlankLines
---

### Parent Blank


#### Card BlankLines



Body line one.


Body line two.
""",
        encoding="utf-8",
    )


def _run_apply(vault_root: Path, server: MockAnkiConnectServer):
    return run_pipeline(
        markdown_files=sorted(vault_root.rglob("*.md")),
        vault_root=vault_root,
        vault_name=vault_root.name,
        asset_root="assets",
        anki_connect_url=server.url,
        sync_state_file=vault_root / "sync_state.json",
        apply_anki_changes=True,
        write_back_markdown=True,
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_state(vault_root: Path) -> dict:
    return json.loads((vault_root / "sync_state.json").read_text(encoding="utf-8"))


def _extract_section(content: str, heading: str) -> str:
    lines = content.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"#### {heading}":
            start = idx
            break
    if start is None:
        raise AssertionError(f"missing heading: {heading}")

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("#### "):
            end = idx
            break
    return "\n".join(lines[start:end])


def _replace_in_section(file_path: Path, heading: str, transform) -> None:
    lines = _read(file_path).splitlines(keepends=True)
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"#### {heading}":
            start = idx
            break
    if start is None:
        raise AssertionError(f"missing heading: {heading}")

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("#### "):
            end = idx
            break

    lines[start:end] = [transform("".join(lines[start:end]))]
    file_path.write_text("".join(lines), encoding="utf-8")


def _note_id_from_section(content: str, heading: str) -> str:
    section = _extract_section(content, heading)
    match = re.search(r"\^anki-(\d+)\s*$", section, flags=re.MULTILINE)
    if not match:
        raise AssertionError(f"missing ^anki id in section: {heading}")
    return match.group(1)


def _assert_initial_add(vault_root: Path, server: MockAnkiConnectServer) -> None:
    report = _run_apply(vault_root, server)

    assert report.failed == 0
    assert report.added == 6
    assert report.updated == 0
    assert server.state.action_count("addNote") == 6
    assert server.state.action_count("updateNoteFields") == 6

    flow_after = _read(vault_root / "01_flow.md")
    assert flow_after.count("^anki-") == 4
    assert "^anki-" in _read(vault_root / "02_media_math.md")
    assert "^anki-" in _read(vault_root / "03_blank_lines.md")

    state = _load_state(vault_root)
    assert len(state["items"]) == 6
    assert all(item.get("obsidian_url") for item in state["items"].values())
    assert all("%23%5Eanki-" in item["obsidian_url"] for item in state["items"].values())


def test_add_initial_notes_finalizes_footer_without_real_anki(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)


def test_rerun_skips_after_initial_add(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        update_count_after_add = server.state.action_count("updateNoteFields")

        report = _run_apply(vault_root, server)

        assert report.failed == 0
        assert report.added == 0
        assert report.updated == 0
        assert report.deleted == 0
        assert report.skipped == 6
        assert server.state.action_count("updateNoteFields") == update_count_after_add


def test_update_existing_note(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        update_count_after_add = server.state.action_count("updateNoteFields")
        flow_file = vault_root / "01_flow.md"
        _replace_in_section(
            flow_file,
            "Card AddUpdate",
            lambda section: section.replace("Update baseline line.", "Update baseline line.\n\nUPDATED_MARKER_ROUND_02"),
        )
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.updated == 1
        assert server.state.action_count("updateNoteFields") == update_count_after_add + 1


def test_delete_existing_note(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        flow_file = vault_root / "01_flow.md"
        delete_note_id = _note_id_from_section(_read(flow_file), "Card DeleteTarget")
        _replace_in_section(
            flow_file,
            "Card DeleteTarget",
            lambda section: re.sub(
                rf"\^anki-{delete_note_id}\s*$",
                f"^anki-{delete_note_id} DELETE",
                section,
                flags=re.MULTILINE,
            ),
        )
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.deleted == 1
        assert int(delete_note_id) not in server.state.notes
        assert delete_note_id not in _load_state(vault_root)["items"]
        delete_section = _extract_section(_read(flow_file), "Card DeleteTarget")
        assert "^nosrs" in delete_section
        assert re.search(r"\^anki-\d+", delete_section) is None


def test_nosrs_after_delete_is_not_readded(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        flow_file = vault_root / "01_flow.md"
        delete_note_id = _note_id_from_section(_read(flow_file), "Card DeleteTarget")
        _replace_in_section(
            flow_file,
            "Card DeleteTarget",
            lambda section: re.sub(
                rf"\^anki-{delete_note_id}\s*$",
                f"^anki-{delete_note_id} DELETE",
                section,
                flags=re.MULTILINE,
            ),
        )
        delete_report = _run_apply(vault_root, server)
        assert delete_report.deleted == 1

        add_count_after_delete = server.state.action_count("addNote")
        report = _run_apply(vault_root, server)

        assert report.failed == 0
        assert report.added == 0
        assert server.state.action_count("addNote") == add_count_after_delete
        delete_section = _extract_section(_read(flow_file), "Card DeleteTarget")
        assert "^nosrs" in delete_section
        assert re.search(r"\^anki-\d+", delete_section) is None


def test_delete_nosrs_conflict_prefers_delete(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        flow_file = vault_root / "01_flow.md"
        conflict_note_id = _note_id_from_section(_read(flow_file), "Card ConflictTarget")

        def _mark_delete_and_nosrs(section: str) -> str:
            section = re.sub(
                rf"\^anki-{conflict_note_id}\s*$",
                f"^anki-{conflict_note_id} DELETE",
                section,
                flags=re.MULTILINE,
            )
            return section.replace(f"^anki-{conflict_note_id} DELETE", f"^anki-{conflict_note_id} DELETE\n\n^nosrs", 1)

        _replace_in_section(flow_file, "Card ConflictTarget", _mark_delete_and_nosrs)
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.deleted == 1
        conflict_section = _extract_section(_read(flow_file), "Card ConflictTarget")
        assert conflict_section.count("^nosrs") == 1
        assert re.search(r"\^anki-\d+", conflict_section) is None


def test_media_link_table_math_roundtrip(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        media_file = vault_root / "02_media_math.md"
        _replace_in_section(media_file, "Card MediaMath", lambda section: section + "\n\nROUNDTRIP_MEDIA_MARKER_06\n")
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.updated == 1
        media_section = _extract_section(_read(media_file), "Card MediaMath")
        assert "![[diagram.png|280]]" in media_section
        assert "![[plot.png]]" in media_section
        assert "![[dup.png]]" in media_section
        assert {"diagram.png", "plot.png", "dup.png"}.issubset(server.state.media)


def test_blank_lines_robustness(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        blank_file = vault_root / "03_blank_lines.md"
        blank_note_id = _note_id_from_section(_read(blank_file), "Card BlankLines")

        def _move_blank_id_and_update(section: str) -> str:
            section = re.sub(rf"\^anki-{blank_note_id}\s*$", f"\n\n^anki-{blank_note_id}", section, flags=re.MULTILINE)
            return section.replace("Body line two.", "Body line two.\n\nROUNDTRIP_BLANK_MARKER_07")

        _replace_in_section(blank_file, "Card BlankLines", _move_blank_id_and_update)
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.updated == 1
        assert re.search(r"\^anki-\d+", _extract_section(_read(blank_file), "Card BlankLines"))
