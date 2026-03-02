import json
import os
import re
from pathlib import Path

import pytest

from md2anki import run_pipeline


pytestmark = pytest.mark.e2e_manual
RUN_MANUAL_E2E = os.getenv("MD2ANKI_E2E") == "1"

E2E_DIR = Path(__file__).resolve().parent
VAULT_ROOT = E2E_DIR / "manual_vault"
SYNC_STATE_FILE = VAULT_ROOT / "sync_state.json"
VAULT_NAME = VAULT_ROOT.name


def _ensure_enabled():
    if not RUN_MANUAL_E2E:
        pytest.fail(
            "manual e2e disabled.\n"
            "Set environment variable before running:\n"
            '  PowerShell: $env:MD2ANKI_E2E="1"\n'
            "Then run:\n"
            "  python -m pytest tests/e2e/test_manual_e2e_flow.py::test_00_add_initial_notes -m e2e_manual -q"
        )


def _run_apply():
    markdown_files = sorted(VAULT_ROOT.rglob("*.md"))
    return run_pipeline(
        markdown_files=markdown_files,
        vault_root=VAULT_ROOT,
        vault_name=VAULT_NAME,
        asset_root="assets",
        sync_state_file=SYNC_STATE_FILE,
        apply_anki_changes=True,
        write_back_markdown=True,
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_state() -> dict:
    if not SYNC_STATE_FILE.exists():
        return {"schema_version": 1, "items": {}}
    return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))


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


def _replace_in_section(file_path: Path, heading: str, transform):
    content = _read(file_path)
    lines = content.splitlines(keepends=True)

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

    section = "".join(lines[start:end])
    updated = transform(section)
    lines[start:end] = [updated]
    file_path.write_text("".join(lines), encoding="utf-8")


def _assert_manual_vault_exists():
    assert VAULT_ROOT.exists(), f"manual vault missing: {VAULT_ROOT}"
    assert (VAULT_ROOT / "01_flow.md").exists()
    assert (VAULT_ROOT / "02_media_math.md").exists()
    assert (VAULT_ROOT / "03_blank_lines.md").exists()


def test_00_add_initial_notes():
    _ensure_enabled()
    _assert_manual_vault_exists()

    # 建议从一份全新复制的 vault 开始该 case。
    flow_before = _read(VAULT_ROOT / "01_flow.md")
    assert "^anki-" not in flow_before, "precondition failed: 01_flow.md already has anki ids"

    report = _run_apply()

    assert report.failed == 0
    assert report.added >= 5
    assert SYNC_STATE_FILE.exists()

    flow_after = _read(VAULT_ROOT / "01_flow.md")
    assert "^anki-" in flow_after
    assert re.search(r"### Parent Flow\n\^id-[0-9a-f]{8}\n", flow_after)
    assert re.search(r"### Parent Extra\n\^id-[0-9a-f]{8}\n", flow_after)
    extra_section = _extract_section(flow_after, "Card MultiParent")
    assert re.search(r"\^anki-\d+", extra_section)

    state = _load_state()
    assert len(state.get("items", {})) >= 5


def test_01_rerun_should_skip():
    _ensure_enabled()

    assert SYNC_STATE_FILE.exists(), "precondition failed: run test_00 first"

    report = _run_apply()

    assert report.failed == 0
    assert report.added == 0
    assert report.updated == 0
    assert report.deleted == 0


def test_02_update_existing_note():
    _ensure_enabled()

    flow_file = VAULT_ROOT / "01_flow.md"
    flow_before = _read(flow_file)
    assert "^anki-" in flow_before, "precondition failed: run test_00 first"

    def _transform(section: str) -> str:
        return section.replace("Update baseline line.", "Update baseline line.\n\nUPDATED_MARKER_ROUND_02")

    _replace_in_section(flow_file, "Card AddUpdate", _transform)

    report = _run_apply()

    assert report.failed == 0
    assert report.updated >= 1


def test_03_delete_existing_note():
    _ensure_enabled()

    flow_file = VAULT_ROOT / "01_flow.md"
    section_before = _extract_section(_read(flow_file), "Card DeleteTarget")
    match = re.search(r"\^anki-(\d+)\s*$", section_before, flags=re.MULTILINE)
    assert match, "precondition failed: Card DeleteTarget missing ^anki-id"

    note_id = match.group(1)

    def _transform(section: str) -> str:
        return re.sub(rf"\^anki-{note_id}\s*$", f"^anki-{note_id} DELETE", section, flags=re.MULTILINE)

    _replace_in_section(flow_file, "Card DeleteTarget", _transform)

    report = _run_apply()

    assert report.failed == 0
    assert report.deleted >= 1

    section_after = _extract_section(_read(flow_file), "Card DeleteTarget")
    assert re.search(r"\^anki-\d+", section_after) is None
    assert "^noanki" in section_after

    state = _load_state()
    assert note_id not in state.get("items", {})


def test_04_noanki_should_not_readd():
    _ensure_enabled()

    flow_file = VAULT_ROOT / "01_flow.md"
    section_before = _extract_section(_read(flow_file), "Card DeleteTarget")
    assert "^noanki" in section_before, "precondition failed: run test_03 first"

    report = _run_apply()

    assert report.failed == 0
    assert report.added == 0

    section_after = _extract_section(_read(flow_file), "Card DeleteTarget")
    assert "^noanki" in section_after
    assert re.search(r"\^anki-\d+", section_after) is None


def test_05_delete_noanki_conflict_prefers_delete():
    _ensure_enabled()

    flow_file = VAULT_ROOT / "01_flow.md"
    section_before = _extract_section(_read(flow_file), "Card ConflictTarget")
    match = re.search(r"\^anki-(\d+)\s*$", section_before, flags=re.MULTILINE)
    assert match, "precondition failed: Card ConflictTarget missing ^anki-id"
    note_id = match.group(1)

    def _transform(section: str) -> str:
        section = re.sub(rf"\^anki-{note_id}\s*$", f"^anki-{note_id} DELETE", section, flags=re.MULTILINE)
        if "^noanki" not in section:
            section = section.replace(f"^anki-{note_id} DELETE", f"^anki-{note_id} DELETE\n\n^noanki", 1)
        return section

    _replace_in_section(flow_file, "Card ConflictTarget", _transform)

    report = _run_apply()

    assert report.failed == 0
    assert report.deleted >= 1

    section_after = _extract_section(_read(flow_file), "Card ConflictTarget")
    assert re.search(r"\^anki-\d+", section_after) is None
    assert section_after.count("^noanki") == 1

    state = _load_state()
    assert note_id not in state.get("items", {})


def test_06_media_link_table_math_roundtrip():
    _ensure_enabled()

    media_file = VAULT_ROOT / "02_media_math.md"
    before = _extract_section(_read(media_file), "Card MediaMath")
    assert re.search(r"\^anki-\d+", before), "precondition failed: run test_00 first"

    def _transform(section: str) -> str:
        return section + "\n\nROUNDTRIP_MEDIA_MARKER_06\n"

    _replace_in_section(media_file, "Card MediaMath", _transform)

    report = _run_apply()

    assert report.failed == 0
    assert report.updated >= 1

    after = _extract_section(_read(media_file), "Card MediaMath")
    assert "![[diagram.png|280]]" in after
    assert "![[plot.png]]" in after
    assert "![[dup.png]]" in after


def test_07_blank_lines_robustness():
    _ensure_enabled()

    blank_file = VAULT_ROOT / "03_blank_lines.md"
    before = _extract_section(_read(blank_file), "Card BlankLines")
    match = re.search(r"\^anki-(\d+)\s*$", before, flags=re.MULTILINE)
    assert match, "precondition failed: run test_00 first"
    note_id = match.group(1)

    def _transform(section: str) -> str:
        section = re.sub(rf"\^anki-{note_id}\s*$", f"\n\n^anki-{note_id}", section, flags=re.MULTILINE)
        section = section.replace("Body line two.", "Body line two.\n\nROUNDTRIP_BLANK_MARKER_07")
        return section

    _replace_in_section(blank_file, "Card BlankLines", _transform)

    report = _run_apply()

    assert report.failed == 0
    assert report.updated >= 1

    after = _extract_section(_read(blank_file), "Card BlankLines")
    assert re.search(r"\^anki-\d+", after)
