# md2anki

A lightweight tool to sync Obsidian-style Markdown (using `####` as cards) to Anki.

Current release baseline: `v0.1.0`

---

## What this tool does

- Extracts cards from Markdown and syncs them to Anki (Basic note type, `Front/Back` fields).
- Supports `ADD / UPDATE / DELETE / SKIP`.
- Supports image uploads (`![[...]]`) and wiki links (`[[...]]`).
- Uses `dry-run` by default for safe preview; only writes to Anki when `apply` is explicitly enabled.
- In apply mode, it can write metadata back to Markdown (such as `^anki-123`, `^noanki`, parent `^id-xxxx`).

---

## Installation

### 1) Requirements

- Python `>=3.10`
- Anki desktop installed
- AnkiConnect installed and enabled (default URL: `http://127.0.0.1:8765`)

### 2) Install the project

Run in repository root:

```bash
pip install -e .
```

If you need test dependencies:

```bash
pip install -e .[test]
```

---

## Get running in 3 minutes (recommended)

### Step 1: Run dry-run first (default)

```bash
md2anki --vault-root <your-vault-path>
```

Example (PowerShell):

```powershell
md2anki --vault-root D:/Notes/MyVault
```

You will see a summary similar to:

- `added / updated / deleted / skipped / failed`
- number of `dry-run actions`

> dry-run does not write to Anki, does not write state, and does not modify Markdown.

### Step 2: Run apply after verification

```bash
md2anki --vault-root <your-vault-path> --apply-anki-changes
```

> apply writes to Anki for real and updates `sync_state.json`.

---

## Common arguments

- `--vault-root`: Vault root directory (required)
- `vault_name` is inferred from the `vault-root` directory name (used for `obsidian://open` links)
- `--asset-root`: asset directory (default: `assets`)
- `--anki-connect-url`: AnkiConnect URL (default: `http://127.0.0.1:8765`)
- `--sync-state-file`: state file path (default: `<vault-root>/sync_state.json`)
- `--file`: only process specific Markdown file(s) (repeatable)
- `--apply-anki-changes`: enable real writes (off by default)
- `--no-write-back-markdown`: disable Markdown write-back in apply mode

Single-file example:

```powershell
md2anki --vault-root D:/Notes/MyVault --file "DeckA/topic.md"
```

---

## Markdown conventions (v0.1)

### 1) frontmatter `ankideck` is required

```yaml
---
ankideck: md2ankiTest
---
```

If a Markdown file does not include `ankideck`, md2anki fully skips that file (no render, no sync, no write-back).
This is an explicit file-level opt-out switch.

### 2) `####` defines a card

- H4 title becomes the default Front.
- H4 body becomes Back.
- If the first `---` separator appears in the body:
  - content before separator is merged into Front
  - content after separator is Back

### 3) Metadata must be on standalone lines

- `^anki-1234567890`: bind to existing note
- `^anki-1234567890 DELETE`: delete this note
- `^noanki`: skip this H4
- `^id-xxxx`: parent heading block id

> Blank lines between heading and metadata are allowed.

### 4) Parent heading rule

`deck_full` uses the nearest parent heading in priority: `H3 > H2 > H1`

---

## Images, links, formulas

### Images

- Supports `![[name.png]]`, `![[path/to/name.png]]`, `![[name.png|300]]`
- Tries explicit path `asset_root/<ref>` first; otherwise recursively searches `asset_root` by filename
- If multiple files share the same name, it picks one deterministically and emits a warning

### Wiki links

- `[[target|alias]]` is converted to `obsidian://open?vault=...&file=...`

### Formulas

- Outside code blocks:
  - `$...$` normalizes to `\(...\)`
  - `$$...$$` normalizes to `\[...\]`
- No conversion inside fenced code blocks

---

## What is `sync_state.json`

The state file is used to decide whether an update is needed and avoid duplicate writes.

- Default location: `<vault-root>/sync_state.json`
- Primary key: `anki_note_id`
- Stores: content hash, update time, source file, etc.

If you need to rebuild sync relations from scratch, back up and delete this file, then run apply again.

---

## Safe usage recommendations

- Always run dry-run first, then apply.
- For the first apply, use `--file` to validate with 1-2 files first.
- Back up your Vault and Anki before release or large changes.

---

## FAQ

### Q1: Why is nothing written to Anki?

Check:

- whether `--apply-anki-changes` is provided
- whether Anki is running
- whether AnkiConnect is reachable (default `127.0.0.1:8765`)

### Q2: Why was a specific H4 skipped?

Common reasons:

- `^noanki` exists
- frontmatter is missing `ankideck`
- content hash did not change (classified as `skip`)

### Q3: Why is `^noanki` written after deletion?

This is by design: to prevent the same H4 from being auto-added again in later runs.

---

## Development and testing

Run automated tests:

```bash
pytest -q
```

Manual real E2E (must be explicitly enabled):

```powershell
$env:MD2ANKI_E2E="1"
python -m pytest tests/e2e/test_manual_e2e_flow.py -m e2e_manual -q
```

---

## References

- Gold Reference design doc: `doc/design_gold_reference_v0.1.md`
- Release checklist: `doc/release_checklist_v0.1.md`
