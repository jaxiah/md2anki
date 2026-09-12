# md2anki Release Checklist

> Use this checklist before publishing a release. Complete the applicable items in order and stop when a required check fails.

---

## A. Pre-Release

### A1. Code and Documentation

- [ ] `README.md` matches current installation, commands, metadata, and sync behavior.
- [ ] `doc/design.md` matches the implementation.
- [ ] The release preserves or explicitly changes the documented core contracts: `Basic` fields, standalone metadata, and asset-root boundaries.
- [ ] Removed or renamed features are absent from CLI help, package exports, examples, and tests.

### A2. Environment

- [ ] Python satisfies `>=3.10`.
- [ ] Test dependencies are installed with `python -m pip install -e ".[test]"`.
- [ ] Anki Desktop is installed for the real-vault smoke test.
- [ ] AnkiConnect is enabled at the configured URL, normally `http://127.0.0.1:8765`.
- [ ] The Anki profile contains a `Basic` note type with `Front` and `Back` fields.

### A3. Full Automated Suite

Run from the repository root:

```powershell
pytest -q
```

Required result:

- [ ] Unit tests pass.
- [ ] Integration tests pass.
- [ ] E2E tests pass.
- [ ] No unrelated failures are waived without documentation.

### A4. Mock AnkiConnect E2E

```powershell
python -m pytest tests/e2e/test_mock_ankiconnect_flow.py -q
```

Required result:

- [ ] All mock E2E scenarios pass.
- [ ] Add, unchanged rerun, update, and delete all behave as expected.
- [ ] A successful delete leaves `^noanki` and removes the deleted note from state.
- [ ] Media and source-footer behavior remain covered.
- [ ] The test does not connect to or modify a real Anki database.

---

## B. Release Execution

### B1. Release Metadata

- [ ] The version in `pyproject.toml` matches the intended release.
- [ ] Release notes describe user-visible behavior, compatibility changes, and migration requirements.
- [ ] Known boundaries are documented, including the fixed `Basic` note type and standalone metadata format.

### B2. Small Real-Vault Smoke Test

Use a backed-up test file and Anki profile. Preview is optional:

```powershell
md2anki --vault-root <VAULT_ROOT> --file <RELATIVE_FILE>
```

Apply only to that file:

```powershell
md2anki --vault-root <VAULT_ROOT> --file <RELATIVE_FILE> --show-progress --apply-anki-changes
```

- [ ] Only the selected Markdown file is processed.
- [ ] A new note is created with correct Front, Back, deck, and `md2anki` tag.
- [ ] `^anki-<id>` is written below the correct H4.
- [ ] The `open in Obsidian` footer opens the exact H4 block.
- [ ] Images, code blocks, and math render correctly.
- [ ] A content edit updates the existing note rather than adding another note.
- [ ] A second unchanged run skips the note.

### B3. Delete and Skip Smoke Test

- [ ] `^anki-<id> DEL` deletes the intended Anki note.
- [ ] Successful deletion replaces ID metadata with one `^noanki` marker.
- [ ] The resulting Markdown has no extra metadata blank lines.
- [ ] A later run does not recreate a `^noanki` block.

### B4. Full Apply

Run only after the small smoke test succeeds and backups exist:

```powershell
md2anki --vault-root <VAULT_ROOT> --show-progress --apply-anki-changes
```

- [ ] The full run completes without failures.
- [ ] `sync_state.json` is updated.
- [ ] An unchanged rerun is primarily SKIP operations.
- [ ] Deck moves preserve scheduling and land in the expected destination decks.

---

## C. Post-Release

### C1. Record the Release

- [ ] Record the release date, version, and commit.
- [ ] Save the relevant apply summary.
- [ ] Record known issues and rollback steps.

### C2. Quick Regression Check

- [ ] Inspect one or two decks for Front/Back rendering, source links, images, code blocks, and math.
- [ ] Confirm that DELETE does not cause automatic re-addition.
- [ ] Confirm that installation from a fresh checkout exposes both `md2anki` and `python -m md2anki`.

---

## D. Troubleshooting

### D1. Apply Produces No Changes

Check, in order:

1. `--apply-anki-changes` is present.
2. Anki is running.
3. AnkiConnect is reachable at the configured URL.
4. The file contains `ankideck` frontmatter.
5. The target H4 is not marked `^noanki`.
6. The note content, deck, and source URL are not already unchanged.

### D2. Images Are Missing or Incorrect

- Confirm that the image exists under the configured asset root.
- Confirm that the Obsidian image reference uses the expected filename or relative path.
- Review warnings for duplicate filenames and the selected stable path.
- Prefer globally unique asset filenames because Anki media filenames are global.

### D3. Rebuild Sync State

- Back up the vault, `sync_state.json`, and Anki profile first.
- Move the existing state file aside rather than permanently deleting it.
- Run apply on one file and confirm that existing `^anki-*` notes are updated instead of duplicated.
- Continue with a full apply only after the small verification succeeds.

---

## E. Go / No-Go

A release is ready only when all required conditions are true:

- [ ] Full automated test suite passes.
- [ ] Mock AnkiConnect E2E passes.
- [ ] Small real-vault apply smoke test passes.
- [ ] README, design, and release checklist are current.
- [ ] User-visible migrations and known risks are documented.

If a required item fails, the release is **No-Go**.
