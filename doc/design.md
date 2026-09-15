# md2anki Design

> This document describes the current architecture, behavior contracts, and boundaries of md2anki.
>
> It is not a historical record. Update it in place whenever the design changes.

---

## 1. Goals and Scope

### 1.1 Goal

md2anki synchronizes H4-based card blocks from Obsidian-style Markdown into Anki's built-in `Basic` and `Cloze` notes. Markdown remains the source of truth, while small metadata markers provide stable identity, deletion, skipping, and source navigation.

### 1.2 In Scope

- Parse Markdown documents containing:
  - frontmatter key `ankideck`
  - H1/H2/H3 parent hierarchy
  - H4 card blocks
  - standalone metadata lines: `^anki-<id>`, `^anki-<id> DEL|DELETE`, and `^noanki`
- Infer Basic or Cloze independently for each H4 block and map its Markdown into the corresponding Anki fields.
- Render question and answer-side Markdown into HTML.
- Normalize Obsidian wiki links, wiki images, and math delimiters.
- Render Mermaid fenced blocks to static SVG media through the local Mermaid CLI.
- Synchronize notes through AnkiConnect with ADD, UPDATE, DELETE, and SKIP behavior.
- Validate exact built-in model field contracts through read-only AnkiConnect queries before any apply-mode writes.
- Maintain `.md2anki-cache/sync_state.json` for content, deck, source URL, and media tracking.
- Write `^anki-<id>` after successful additions and `^noanki` after successful deletions.
- Provide a read-only dry-run mode and an explicit apply mode.

### 1.3 File-Level Eligibility

- A file is processed only when its frontmatter contains `ankideck`.
- A file without `ankideck` is silently skipped before card parsing, rendering, synchronization, or writeback.
- Omitting `ankideck` is the file-level opt-out mechanism.

### 1.4 Out of Scope

- Managing Anki note types or card templates. Sync targets the existing built-in `Basic` (`Front`, `Back`) and `Cloze` (`Text`, `Back Extra`) note types.
- Migrating an existing synchronized note between Basic and Cloze. An intentional type change requires a new note identity.
- Merging competing edits from multiple Markdown sources that target the same Anki note.
- Supporting historical inline metadata placed on heading lines.
- A graphical interface.

---

## 2. Architecture

The system uses four focused components and one procedural orchestrator:

1. `MarkdownProcessor`: Markdown parsing and localized metadata writeback.
2. `HtmlRenderer`: Markdown-to-HTML rendering and media collection.
3. `MermaidCliRenderer`: isolated `mmdc` process execution and SVG generation.
4. `AnkiClient`: AnkiConnect operations and sync-state management.
5. `run_pipeline`: parse, route, render, sync, and writeback orchestration.

### 2.1 Data Flow

- Inputs:
  - Markdown file paths
  - vault name and root
  - asset root
  - AnkiConnect and runtime options
- Intermediate records:
  - `ParsedDocument` and `ParsedNote`
  - `RenderedNote` and `MediaItem`
  - `SyncResult`
  - `PipelineReport`
- Outputs in apply mode:
  - Anki note and deck changes
  - uploaded Anki media
  - `.md2anki-cache/sync_state.json`
  - Markdown metadata writeback
  - summary counts and aggregated errors

---

## 3. Data Model

### 3.1 ParsedNote

Important fields:

- Source: `source_file`, `line_idx_h4`
- Deck: `ankideck_base`, `deck_full`
- Parent: `parent_title`, `parent_level`
- Heading: `h4_heading_raw`, `h4_heading_pure`
- Metadata: `anki_note_id`, `anki_meta_line_idx`, `delete_requested`, `no_anki`
- Content: `model_name`, `front_md`, `back_md`, `split_by_separator`

`front_md` and `back_md` are internal semantic slots. They map to `Front` and `Back` for Basic, or `Text` and `Back Extra` for Cloze.

### 3.2 Rendered Records

`RenderedNote` contains:

- `front_html`
- `back_html`
- `back_html_with_footer`
- `model_name`
- `anki_fields`, derived as `Front`/`Back` or `Text`/`Back Extra`
- `media_files`
- `warnings`
- `obsidian_url`

`MediaItem` contains:

- `filename`
- `abs_path`
- `base64_data`
- `source_ref`

Vault images carry an absolute source path. Generated Mermaid SVGs carry Base64 data directly and leave `abs_path` empty.

### 3.3 State File

The default state path is `<vault-root>/.md2anki-cache/sync_state.json`.

```json
{
  "schema_version": 1,
  "items": {
    "1234567890": {
      "content_hash": "...",
      "updated_ts": "2026-...",
      "source_file": "Engineering/pumps.md",
      "h4_heading_pure": "What does a pump volute do?",
      "deck_full": "Engineering::Pumps",
      "obsidian_url": "obsidian://open?..."
    }
  },
  "uploaded_media": {
    "pump.png": "..."
  }
}
```

Keys in `items` are string forms of Anki note IDs. `uploaded_media` maps Anki media filenames to content fingerprints so unchanged files are not uploaded repeatedly.

---

## 4. Markdown Contract

### 4.1 Card and Deck Rules

- Every H4 starts one candidate Anki note.
- The nearest preceding H3 is the preferred parent, followed by H2 and H1.
- When a parent exists, `deck_full = ankideck + "::" + parent_title`.
- Without a parent, `deck_full = ankideck`.
- A file may contain multiple H4 notes and multiple parent sections.

### 4.2 Metadata

Metadata must be on standalone lines below the H4. Blank lines between the heading and metadata are allowed.

- `^anki-<digits>` binds the block to an existing Anki note.
- `^anki-<digits> DEL` requests deletion.
- `^anki-<digits> DELETE` is the long-form deletion syntax.
- `^noanki` skips the block without adding, updating, or deleting a note.

Only `^anki-*` and `^noanki` are synchronization metadata. `^srs-*` and `^nosrs` are not recognized.

### 4.3 Skip and Delete Precedence

- `^noanki` without a delete request skips the H4 block.
- `^anki-<id> DEL|DELETE` enters the delete path.
- If delete metadata and `^noanki` coexist, deletion takes precedence. A successful delete leaves one canonical `^noanki` marker.

### 4.4 Note Type Inference and Field Mapping

- Inference is performed independently for each H4 block, so one file may mix Basic and Cloze notes.
- The inference candidate is the H4 heading plus content above the first thematic break line (`---`, with surrounding whitespace allowed), or the entire body when no separator exists.
- A candidate containing `{{cN::...}}`, where `N` is a positive integer, is Cloze. The optional `{{cN::text::hint}}` form is also recognized.
- Cloze syntax below the separator belongs to Back Extra and does not affect inference.
- For Basic with a separator, the H4 and content above it map to `Front`; content below it maps to `Back`.
- For Basic without a separator, the H4 maps to `Front`; the entire body maps to `Back`.
- For Cloze with a separator, the H4 and content above it map to `Text`; content below it maps to `Back Extra`.
- For Cloze without a separator, the H4 and entire body map to `Text`; authored `Back Extra` is empty.
- The inferred type of an existing synchronized note must remain stable. No implicit type migration is attempted; an intentional change requires a new note identity.

---

## 5. HTML and Media Rendering

### 5.1 Markdown Rendering

- `markdown-it-py` uses the `gfm-like` preset with raw HTML and line breaks enabled and automatic linkification disabled.
- The two internal content slots are rendered separately.
- The answer-side field (`Back` or `Back Extra`) receives an `open in Obsidian` source footer, including when authored Cloze Back Extra is empty.

### 5.2 Wiki Links

`[[target|alias]]` becomes an Obsidian URL:

```html
<a href="obsidian://open?vault=<vault>&file=<target>">alias</a>
```

### 5.3 Source URL

- With an Anki note ID, the footer targets `file_without_md#^anki-<id>` through the `file` query parameter.
- The entire file-and-anchor target is URL-encoded so the block fragment survives external webviews.
- After a new ID is written to Markdown, the note is rendered again and its Anki fields are finalized with the block-level URL.
- Because the anchor uses the stable Anki note ID, renaming the H4 heading does not break the source link.

### 5.4 Wiki Images

For `![[image.png]]` and `![[image.png|300]]`:

- First try an explicit path under `asset_root`.
- Otherwise search recursively under `asset_root` by filename.
- If multiple files match, choose the first path in stable relative-path order and emit a warning.
- Accept numeric widths in `300` and `300px` forms and render `width="300"`.
- Read the selected file, encode it, and upload it through AnkiConnect `storeMediaFile`.

### 5.5 Math

Outside fenced code blocks:

- `$$...$$` becomes `\[...\]`.
- `$...$` becomes `\(...\)`.

Fenced code is protected from math normalization. Anki's built-in MathJax renders the normalized delimiters.

### 5.6 Mermaid

- A fenced block whose language is exactly `mermaid` is detected from markdown-it tokens rather than regular-expression matching.
- Mermaid blocks are protected before wiki-link and math transformations, so Mermaid syntax such as `[[subroutine]]` is not interpreted as an Obsidian link.
- `MermaidCliRenderer` finds `mmdc` on `PATH` and invokes it with the neutral theme, a white background, and SVG output.
- An installed Chrome, Edge, or Chromium is preferred when available. Otherwise Mermaid CLI selects its bundled Puppeteer browser.
- The generated Anki media filename is `md2anki-mermaid-<sha256(source)>.svg`.
- Rendered SVGs are persisted in the flat `<vault>/.md2anki-cache/mermaid/` directory. The cache key includes the Mermaid source and an internal renderer revision, so unchanged diagrams avoid `mmdc` across pipeline runs while rendering changes invalidate old entries automatically.
- Equal Mermaid source is rendered once and reuses the same media filename across notes and fields.
- Cache reads and writes are best-effort. Missing, empty, or inaccessible cache entries fall back to normal rendering, and deleting the cache directory forces regeneration.
- The SVG bytes are Base64-encoded in `MediaItem` and uploaded through the existing `storeMediaFile` path.
- Missing prerequisites, invalid Mermaid, timeouts, missing output, and empty output are rendering failures rather than warnings.
- Normal non-Mermaid fenced blocks remain ordinary highlighted code and do not require `mmdc`.

---

## 6. Synchronization Semantics

### 6.1 Runtime Modes

- Dry-run is the default. It performs no AnkiConnect requests and writes neither state nor Markdown.
- Apply mode is enabled with `--apply-anki-changes` and performs the requested external and local writes.

### 6.2 Action Selection

- DELETE: `delete_requested=True` with an `anki_note_id`.
- SKIP(noanki): `no_anki=True` without a delete request.
- SKIP(unchanged): the content hash, deck, and source URL all match state.
- UPDATE: a note ID exists and content, deck, or source URL requires synchronization.
- ADD: no note ID exists.

An existing `^anki-<id>` that is absent from state is still treated as an existing Anki note and updated rather than added.
For Cloze notes, one Anki note may generate multiple cards. Synchronization and Markdown metadata continue to track only the Anki note ID.

### 6.3 Content Hash

The content hash is based on Markdown-derived semantics, not generated HTML or footer markup:

- `deck_full`
- `front_md`
- `back_md`
- sorted media references in `filename:source_ref` form

This keeps Markdown as the source of truth and prevents renderer-only changes from creating false content updates.
Mermaid media names and source references are derived only from the Mermaid source. Generated SVG bytes and Mermaid CLI versions do not enter the content hash.

### 6.4 AnkiConnect Operations

- Before any apply-mode write, validate every locally generated field map and call `modelFieldNames` for each model used in the run.
- Require the exact ordered contracts `Basic` (`Front`, `Back`) and `Cloze` (`Text`, `Back Extra`); abort the run on any mismatch or query failure.
- Load existing deck names with `deckNamesAndIds` in apply mode.
- Create missing decks with `createDeck`.
- Upload changed media with `storeMediaFile` before note synchronization.
- ADD with `addNote`, using the inferred model and its fields: `Basic` with `Front`/`Back`, or `Cloze` with `Text`/`Back Extra`.
- UPDATE with `updateNoteFields`, using the same model-specific field mapping.
- Move cards between decks with `notesInfo` and `changeDeck` when `deck_full` changes.
- DELETE with `deleteNotes`.

Transient connection, timeout, and server errors use the configured retry count and exponential backoff.

---

## 7. Markdown Writeback

### 7.1 Preconditions

Markdown writeback requires both:

- `apply_anki_changes=True`
- `write_back_markdown=True`

### 7.2 Changes

- After ADD, insert `^anki-<id>` below the corresponding H4.
- After DELETE, remove the Anki ID metadata and insert one `^noanki` marker.
- Normalize deleted metadata to one blank line before and after the canonical `^noanki` marker.

### 7.3 Stability

- Apply operations for the same file are processed in descending H4 line order to avoid line-index drift.
- A successful ADD is rendered again after ID writeback so the final Anki footer contains the block anchor.
- Metadata scanning tolerates blank lines but stops at the first nonblank, unrecognized line so normal body content is not consumed.

---

## 8. Pipeline

`run_pipeline(...)` follows this sequence:

1. Parse all requested Markdown files.
2. Route `^noanki`, deletion, and renderable notes. Abort before Anki writes when fail-fast rendering fails.
3. In apply mode, validate local field maps and live Anki model field contracts with read-only queries.
4. In apply mode, pre-upload changed media.
5. Synchronize rendered payloads with `AnkiClient.sync(...)`.
6. In apply mode with writeback enabled, update Markdown metadata and finalize source footers for new notes.
7. Return `PipelineReport`.

`PipelineReport` aggregates `added`, `updated`, `deleted`, `skipped`, `failed`, `errors`, `markdown_writebacks`, and `dry_run_actions`.

---

## 9. CLI

Node.js and `@mermaid-js/mermaid-cli` are external runtime prerequisites. `mmdc` must be available on `PATH` when a rendered note contains a Mermaid fence. Notes without Mermaid do not invoke or require the executable at runtime.

### 9.1 Entry Points

- Console script: `md2anki`
- Module: `python -m md2anki`

### 9.2 Options

- `--vault-root` is required.
- The vault name is derived from the vault root directory name.
- `--asset-root` defaults to `assets` under the vault.
- `--anki-connect-url` defaults to `http://127.0.0.1:8765`.
- Synchronization state is always stored at `<vault-root>/.md2anki-cache/sync_state.json` by the CLI.
- `--file` may be repeated. Without it, all `.md` files under the vault are scanned recursively.
- `--apply-anki-changes` enables writes.
- `--no-write-back-markdown` disables Markdown writeback in apply mode.
- Interactive terminals show one compact progress bar that is reused across parse, media, and sync stages.
- `--verbose` replaces the compact bar with per-stage, per-item details for troubleshooting.
- `--request-timeout-seconds`, `--max-retries`, and `--retry-backoff-seconds` control AnkiConnect resilience.
- `--no-fail-fast` continues after note-level failures.

### 9.3 Exit Codes

- Return `1` when `PipelineReport.failed > 0`.
- Return `0` otherwise.

---

## 10. Test Coverage

### 10.1 Unit Tests

- `MarkdownProcessor`: parsing, parent hierarchy, Basic/Cloze inference, field splitting, metadata spacing, DEL/DELETE, noanki, and writeback helpers.
- `HtmlRenderer`: model-specific fields, source URLs, wiki links and images, ambiguous media, math normalization, fenced-code protection, Mermaid SVG generation, cache reuse, and prerequisite failures.
- `AnkiClient`: strict local/live model contract validation, model-specific add/update payloads, dry-run behavior, retries, media caching, add/update/skip/delete, deck moves, URL drift, and state changes.
- CLI: defaults, option forwarding, the legacy hidden `--to-anki` alias, and rejection of the removed HTML mode.

### 10.2 Integration Tests

- Parser and renderer behavior across Basic/Cloze mixtures, optional Cloze Back Extra, lists, tables, links, images, math, and Mermaid media.
- Pipeline behavior in temporary vaults, including writeback positions, multiple cards, multiple parent groups, noanki, deletion conflicts, and media failures.

### 10.3 Mock AnkiConnect E2E

- File: `tests/e2e/test_mock_ankiconnect_flow.py`
- Uses a local mock HTTP server and never touches a real Anki database.
- Covers strict model-contract preflight before writes, observed read-only AnkiConnect response shapes, mixed Basic/Cloze addition, multiple cards per Cloze note, optional Back Extra, card-preserving updates, sibling-card deck moves, deletion, strict mock rejection of invalid type transitions, unchanged reruns, noanki persistence, image/MathJax/Mermaid media round trips, and blank-line robustness.

---

## 11. Failure and Warning Behavior

- Fail-fast is enabled by default.
- With `--no-fail-fast`, note-level failures are aggregated into `errors` and `failed`, and processing continues.
- Warnings include YAML parse failures, missing images, and ambiguous image matches.
- Failures include deletion without a note ID, Mermaid CLI/rendering errors, AnkiConnect errors, missing decks or note types, and media-upload failures.
- A failed deck move keeps the previous deck in state so a later run can retry it.

---

## 12. Known Boundaries

- Anki model names and fields are fixed to the built-in `Basic` (`Front`, `Back`) and `Cloze` (`Text`, `Back Extra`) contracts.
- Existing notes cannot transition between Basic and Cloze through synchronization.
- Real AnkiConnect may silently ignore unknown fields. md2anki and its mock server intentionally reject non-exact outbound field maps before synchronization.
- AnkiConnect requests use API version 6.
- Synchronization metadata must use standalone lines and numeric note IDs.
- Image resolution is limited to the configured asset root.
- Anki media uses global filenames; vault assets should use unique filenames to avoid unintended replacement.
- Mermaid rendering requires the external `mmdc` executable and a browser supported by Mermaid CLI.
- Mermaid SVGs use a fixed neutral theme and white background so they remain readable in both light and dark Anki themes.
- Renderer or card-template changes do not participate in the Markdown content hash.
- The tool does not manage card-template HTML, JavaScript, or CSS. `anki-card-style.css` is provided for manual installation.

---

## 13. Documentation Policy

- README presents the user-facing workflow and current supported syntax.
- This document presents the current implementation design only.
- `release_checklist.md` contains the current release procedure.
- When behavior changes, update these files in place rather than preserving versioned design copies.
