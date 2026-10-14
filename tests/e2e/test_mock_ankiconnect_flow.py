import base64
import json
import re
from pathlib import Path

import pytest
import requests

from md2anki import MermaidCliRenderer, run_pipeline

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
    (vault_root / "04_mixed_types.md").write_text(
        """---
ankideck: md2ankiTest::Mixed
---

### Parent Mixed

#### Card MixedBasic

Basic answer.

#### Card MixedCloze

The volute converts {{c1::velocity}} into {{c2::pressure}}.

---

Additional cloze context.

#### Card MixedClozeNoExtra

The impeller adds {{c1::velocity}} to the fluid.
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


def _invoke_mock(server: MockAnkiConnectServer, action: str, **params):
    response = requests.post(
        server.url,
        json={"action": action, "version": 6, "params": params},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


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
    assert report.added == 9
    assert report.updated == 0
    assert server.state.action_count("addNote") == 9
    assert server.state.action_count("updateNoteFields") == 9
    queried_models = {
        request["params"]["modelName"]
        for request in server.state.requests_for("modelFieldNames")
    }
    assert queried_models == {"Basic", "Cloze"}

    flow_after = _read(vault_root / "01_flow.md")
    assert flow_after.count("^anki-") == 4
    assert "^anki-" in _read(vault_root / "02_media_math.md")
    assert "^anki-" in _read(vault_root / "03_blank_lines.md")
    assert _read(vault_root / "04_mixed_types.md").count("^anki-") == 3

    state = _load_state(vault_root)
    assert len(state["items"]) == 9
    assert all(item.get("obsidian_url") for item in state["items"].values())
    assert all("%23%5Eanki-" in item["obsidian_url"] for item in state["items"].values())


def test_add_initial_notes_finalizes_footer_without_real_anki(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)


def test_mock_read_only_contract_shapes_match_observed_ankiconnect():
    with MockAnkiConnectServer() as server:
        decks = _invoke_mock(server, "deckNamesAndIds")
        basic_fields = _invoke_mock(server, "modelFieldNames", modelName="Basic")
        cloze_fields = _invoke_mock(server, "modelFieldNames", modelName="Cloze")
        cloze_templates = _invoke_mock(server, "modelTemplates", modelName="Cloze")
        missing_note = _invoke_mock(server, "notesInfo", notes=[9999999999999])
        missing_media = _invoke_mock(server, "retrieveMediaFile", filename="missing.bin")

        assert isinstance(decks["result"]["Default"], int)
        assert basic_fields == {"result": ["Front", "Back"], "error": None}
        assert cloze_fields == {"result": ["Text", "Back Extra"], "error": None}
        assert cloze_templates["result"]["Cloze"]["Back"] == "{{cloze:Text}}<br>\n{{Back Extra}}"
        assert missing_note == {"result": [{}], "error": None}
        assert missing_media == {"result": False, "error": None}


def test_model_contract_mismatch_stops_before_any_write(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        server.state.model_fields["Cloze"] = ["Text", "Extra"]

        report = _run_apply(vault_root, server)

        assert report.failed == 1
        assert any("Cloze field contract mismatch" in error for error in report.errors)
        assert server.state.action_count("createDeck") == 0
        assert server.state.action_count("storeMediaFile") == 0
        assert server.state.action_count("addNote") == 0
        assert server.state.action_count("updateNoteFields") == 0


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
        assert report.skipped == 9
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
        assert "^noanki\n\nDelete baseline line." in delete_section
        assert re.search(r"\^anki-\d+", delete_section) is None


def test_noanki_after_delete_is_not_readded(tmp_path: Path):
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
        assert "^noanki\n\nDelete baseline line." in delete_section
        assert re.search(r"\^anki-\d+", delete_section) is None


def test_delete_noanki_conflict_prefers_delete(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        flow_file = vault_root / "01_flow.md"
        conflict_note_id = _note_id_from_section(_read(flow_file), "Card ConflictTarget")

        def _mark_delete_and_noanki(section: str) -> str:
            section = re.sub(
                rf"\^anki-{conflict_note_id}\s*$",
                f"^anki-{conflict_note_id} DELETE",
                section,
                flags=re.MULTILINE,
            )
            return section.replace(f"^anki-{conflict_note_id} DELETE", f"^anki-{conflict_note_id} DELETE\n\n^noanki", 1)

        _replace_in_section(flow_file, "Card ConflictTarget", _mark_delete_and_noanki)
        report = _run_apply(vault_root, server)
        assert report.failed == 0
        assert report.deleted == 1
        conflict_section = _extract_section(_read(flow_file), "Card ConflictTarget")
        assert conflict_section.count("^noanki") == 1
        assert "^noanki\n\nConflict baseline line." in conflict_section
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


def test_anki_normalized_media_name_is_used_without_persistent_mapping(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    assets = vault_root / "assets"
    assets.mkdir(parents=True)
    media_name = "Pasted image 20260915064330.png"
    (assets / media_name).write_bytes(b"image-data")
    note_file = vault_root / "case-sensitive-media.md"
    note_file.write_text(
        f"""---
ankideck: md2ankiTest::MediaCase
---

#### Preserve Anki's actual media name

![[{media_name}|800]]
""",
        encoding="utf-8",
    )

    with MockAnkiConnectServer() as server:
        first = _run_apply(vault_root, server)

        assert first.failed == 0
        assert first.added == 1
        stored_name = media_name.lower()
        assert stored_name in server.state.media
        note = next(iter(server.state.notes.values()))
        assert f'<img src="{stored_name}" width="800">' in note["fields"]["Back"]

        state = json.loads((vault_root / "sync_state.json").read_text(encoding="utf-8"))
        assert "stored_media_names" not in state
        assert media_name in state["uploaded_media"]

        note_file.write_text(
            note_file.read_text(encoding="utf-8").replace(
                "Preserve Anki's actual media name",
                "Use Anki's actual media name after an update",
            ),
            encoding="utf-8",
        )
        second = _run_apply(vault_root, server)

        assert second.failed == 0
        assert second.updated == 1
        assert server.state.action_count("storeMediaFile") == 2
        note = next(iter(server.state.notes.values()))
        assert f'<img src="{stored_name}" width="800">' in note["fields"]["Back"]


@pytest.mark.parametrize("model_name", ["Basic", "Cloze"])
@pytest.mark.parametrize("preexisting_media", [False, True])
def test_media_case_regression_and_cache_reset_repair(
    tmp_path: Path, model_name: str, preexisting_media: bool
):
    vault_root = tmp_path / "mock_vault"
    assets = vault_root / "assets"
    assets.mkdir(parents=True)
    media_name = "Pasted image 20261012205508.png"
    stored_name = media_name.lower()
    image_data = b"case-sensitive-image"
    (assets / media_name).write_bytes(image_data)
    note_file = vault_root / "media-case.md"
    front_text = "Front context." if model_name == "Basic" else "Recall {{c1::this image}}."
    note_file.write_text(
        f"---\nankideck: md2ankiTest::MediaCase\n---\n\n"
        f"#### Media case regression\n\n{front_text}\n\n![[{media_name}|800]]\n\n"
        f"---\n\nAnswer context.\n\n![[{media_name}|400]]\n",
        encoding="utf-8",
    )
    state_file = vault_root / "sync_state.json"

    with MockAnkiConnectServer() as server:
        server.state.reuse_media_request_case = True
        if preexisting_media:
            server.state.media[stored_name] = base64.b64encode(image_data).decode("ascii")
        first = _run_apply(vault_root, server)
        assert first.failed == 0 and first.added == 1
        note_id = next(iter(server.state.notes))
        note = server.state.notes[note_id]
        front_field = "Front" if model_name == "Basic" else "Text"
        back_field = "Back" if model_name == "Basic" else "Back Extra"
        assert f'<img src="{stored_name}" width="800">' in note["fields"][front_field]
        assert f'<img src="{stored_name}" width="400">' in note["fields"][back_field]

        note_file.write_text(
            note_file.read_text(encoding="utf-8").replace("Answer context.", "Updated answer context."),
            encoding="utf-8",
        )
        second = _run_apply(vault_root, server)
        assert second.failed == 0 and second.updated == 1
        assert server.state.action_count("storeMediaFile") == 2
        assert media_name not in note["fields"][front_field]
        assert media_name not in note["fields"][back_field]
        state_before = json.loads(state_file.read_text(encoding="utf-8"))

        # Seed the previously broken HTML, then rebuild only local sync state.
        for field_name in (front_field, back_field):
            note["fields"][field_name] = note["fields"][field_name].replace(stored_name, media_name)
        for card_id in note["cards"]:
            server.state.cards[card_id].update(due=123, ivl=7, reps=3)
        cards_before = {card_id: dict(server.state.cards[card_id]) for card_id in note["cards"]}
        markdown_before = note_file.read_text(encoding="utf-8")
        state_file.unlink()

        repaired = _run_apply(vault_root, server)

        assert repaired.failed == 0 and repaired.updated == 1 and repaired.added == 0
        assert list(server.state.notes) == [note_id]
        assert f'<img src="{stored_name}" width="800">' in note["fields"][front_field]
        assert f'<img src="{stored_name}" width="400">' in note["fields"][back_field]
        assert {card_id: server.state.cards[card_id] for card_id in note["cards"]} == cards_before
        assert note_file.read_text(encoding="utf-8") == markdown_before
        state_after = json.loads(state_file.read_text(encoding="utf-8"))
        assert state_after["items"][str(note_id)]["content_hash"] == state_before["items"][str(note_id)]["content_hash"]
        assert "stored_media_names" not in state_after
        assert server.state.action_count("addNote") == 1
        assert server.state.action_count("deleteNotes") == 0

        server.state.clear_requests()
        unchanged = _run_apply(vault_root, server)
        assert unchanged.failed == 0 and unchanged.updated == 0 and unchanged.skipped == 1
        assert server.state.action_count("storeMediaFile") == 0
        assert server.state.action_count("getMediaFilesNames") == 0
        assert server.state.action_count("updateNoteFields") == 0


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


def test_mixed_basic_and_cloze_create_correct_notes_and_cards(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_file = _read(vault_root / "04_mixed_types.md")
        basic_id = int(_note_id_from_section(mixed_file, "Card MixedBasic"))
        cloze_id = int(_note_id_from_section(mixed_file, "Card MixedCloze"))
        no_extra_id = int(_note_id_from_section(mixed_file, "Card MixedClozeNoExtra"))
        basic_note = server.state.notes[basic_id]
        cloze_note = server.state.notes[cloze_id]
        no_extra_note = server.state.notes[no_extra_id]

        assert basic_note["modelName"] == "Basic"
        assert set(basic_note["fields"]) == {"Front", "Back"}
        assert len(basic_note["cards"]) == 1

        assert cloze_note["modelName"] == "Cloze"
        assert set(cloze_note["fields"]) == {"Text", "Back Extra"}
        assert "Card MixedCloze" in cloze_note["fields"]["Text"]
        assert "{{c1::velocity}}" in cloze_note["fields"]["Text"]
        assert "Additional cloze context." in cloze_note["fields"]["Back Extra"]
        assert "open in Obsidian" in cloze_note["fields"]["Back Extra"]
        assert f"%23%5Eanki-{cloze_id}" in cloze_note["fields"]["Back Extra"]
        assert len(cloze_note["cards"]) == 2
        assert [server.state.cards[card_id]["ord"] for card_id in cloze_note["cards"]] == [0, 1]

        assert no_extra_note["modelName"] == "Cloze"
        assert "Card MixedClozeNoExtra" in no_extra_note["fields"]["Text"]
        assert "open in Obsidian" in no_extra_note["fields"]["Back Extra"]
        assert len(no_extra_note["cards"]) == 1

        assert server.state.media["diagram.png"] == base64.b64encode(b"diagram").decode("ascii")


def test_mermaid_svg_media_roundtrip_without_real_anki(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "mock_vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    source = "flowchart LR\nA[Markdown] --> B[SVG]\n"
    (vault_root / "mermaid.md").write_text(
        f"""---
ankideck: md2ankiTest::Mermaid
---

#### Render a Mermaid diagram

```mermaid
{source}```
""",
        encoding="utf-8",
    )
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text>mock Mermaid</text></svg>'
    monkeypatch.setattr(MermaidCliRenderer, "render_svg", lambda self, diagram: svg)

    with MockAnkiConnectServer() as server:
        report = _run_apply(vault_root, server)

        assert report.failed == 0
        assert report.added == 1
        assert len(server.state.media) == 1
        filename, stored_data = next(iter(server.state.media.items()))
        assert filename.startswith("md2anki-mermaid-")
        assert filename.endswith(".svg")
        assert stored_data == base64.b64encode(svg).decode("ascii")

        note = next(iter(server.state.notes.values()))
        assert f'<img src="{filename}" alt="Mermaid diagram">' in note["fields"]["Back"]
        assert "language-mermaid" not in note["fields"]["Back"]


def test_cloze_update_preserves_existing_cards_and_adds_new_ordinal(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_path = vault_root / "04_mixed_types.md"
        cloze_id = int(_note_id_from_section(_read(mixed_path), "Card MixedCloze"))
        original_cards = set(server.state.notes[cloze_id]["cards"])

        _replace_in_section(
            mixed_path,
            "Card MixedCloze",
            lambda section: section.replace(
                "into {{c2::pressure}}.",
                "into {{c2::pressure}} with {{c3::increasing area}}.",
            ),
        )
        report = _run_apply(vault_root, server)

        updated_cards = set(server.state.notes[cloze_id]["cards"])
        assert report.failed == 0
        assert report.updated == 1
        assert original_cards < updated_cards
        assert len(updated_cards) == 3


def test_delete_cloze_removes_all_derived_cards(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_path = vault_root / "04_mixed_types.md"
        cloze_id = int(_note_id_from_section(_read(mixed_path), "Card MixedCloze"))
        card_ids = set(server.state.notes[cloze_id]["cards"])

        _replace_in_section(
            mixed_path,
            "Card MixedCloze",
            lambda section: re.sub(
                rf"\^anki-{cloze_id}\s*$",
                f"^anki-{cloze_id} DEL",
                section,
                flags=re.MULTILINE,
            ),
        )
        report = _run_apply(vault_root, server)

        assert report.failed == 0
        assert report.deleted == 1
        assert cloze_id not in server.state.notes
        assert card_ids.isdisjoint(server.state.cards)


def test_cloze_deck_move_moves_every_derived_card(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_path = vault_root / "04_mixed_types.md"
        cloze_id = int(_note_id_from_section(_read(mixed_path), "Card MixedCloze"))
        card_ids = list(server.state.notes[cloze_id]["cards"])

        mixed_path.write_text(
            _read(mixed_path).replace(
                "ankideck: md2ankiTest::Mixed",
                "ankideck: md2ankiTest::Moved",
            ),
            encoding="utf-8",
        )
        report = _run_apply(vault_root, server)

        assert report.failed == 0
        assert report.updated == 3
        assert all(
            server.state.cards[card_id]["deckName"] == "md2ankiTest::Moved::Parent Mixed"
            for card_id in card_ids
        )


def test_unsupported_basic_to_cloze_change_fails_without_replacing_note(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_path = vault_root / "04_mixed_types.md"
        basic_id = int(_note_id_from_section(_read(mixed_path), "Card MixedBasic"))
        (vault_root / "assets" / "new-diagram.png").write_bytes(b"new diagram")

        _replace_in_section(
            mixed_path,
            "Card MixedBasic",
            lambda section: section.replace(
                "Basic answer.", "Basic {{c1::answer}}.\n\n![[new-diagram.png]]"
            ),
        )
        server.state.clear_requests()
        report = _run_apply(vault_root, server)

        assert report.failed == 1
        assert server.state.notes[basic_id]["modelName"] == "Basic"
        assert any(f"^anki-{basic_id}" in error and "Basic" in error and "Cloze" in error for error in report.errors)
        assert server.state.action_count("notesInfo") >= 1
        assert server.state.action_count("storeMediaFile") == 0
        assert server.state.action_count("updateNoteFields") == 0
        assert server.state.action_count("addNote") == 0


def test_unsupported_cloze_to_basic_change_fails_before_writes_without_state(tmp_path: Path):
    vault_root = tmp_path / "mock_vault"
    _write_vault(vault_root)

    with MockAnkiConnectServer() as server:
        _assert_initial_add(vault_root, server)
        mixed_path = vault_root / "04_mixed_types.md"
        cloze_id = int(_note_id_from_section(_read(mixed_path), "Card MixedCloze"))
        _replace_in_section(
            mixed_path,
            "Card MixedCloze",
            lambda section: section.replace("{{c1::velocity}}", "velocity").replace(
                "{{c2::pressure}}", "pressure"
            ),
        )
        (vault_root / "sync_state.json").unlink()
        server.state.clear_requests()

        report = _run_apply(vault_root, server)

        assert report.failed == 1
        assert server.state.notes[cloze_id]["modelName"] == "Cloze"
        assert any(f"^anki-{cloze_id}" in error and "Cloze" in error and "Basic" in error for error in report.errors)
        assert server.state.action_count("notesInfo") >= 1
        assert server.state.action_count("storeMediaFile") == 0
        assert server.state.action_count("updateNoteFields") == 0
        assert server.state.action_count("addNote") == 0
