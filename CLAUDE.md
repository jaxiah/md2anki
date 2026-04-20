# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**md2anki** syncs Obsidian-style Markdown notes (H4 headings as flashcards) to Anki via the AnkiConnect API. H4 headings become card fronts; content after a `---` separator becomes the back. Deck hierarchy derives from the YAML frontmatter `ankideck` field combined with parent H1–H3 headings.

## Commands

```bash
# Install
pip install -e .
pip install -e .[test]      # include test dependencies

# Run tests
pytest -q                   # all unit/integration tests
pytest tests/unit/test_markdown_processor.py -q   # single test file

# Manual E2E (requires live Anki with AnkiConnect + a vault)
MD2ANKI_E2E="1" pytest tests/e2e/test_manual_e2e_flow.py -m e2e_manual -q

# CLI dry-run (safe, no writes)
md2anki --vault-root <path>

# Apply changes
md2anki --vault-root <path> --apply-anki-changes
```

## Architecture

Three sequential stages orchestrated by `pipeline.py::run_pipeline()`:

```
Markdown files
  → MarkdownProcessor   (markdown_processor.py)  parse → ParsedDocument / ParsedNote
  → HtmlRenderer        (html_renderer.py)        render → RenderedNote
  → AnkiClient          (anki_client.py)          sync → SyncResult + state
  → writeback           (pipeline.py)             insert ^anki-<id> into markdown
```

**Parse (`markdown_processor.py`):** Extracts frontmatter (`ankideck`), H4 cards, parent hierarchy (H1–H3), and inline metadata lines (`^anki-<id>`, `^noanki`, `DELETE`, `^id-xxxx`). Front/back split on bare `---`.

**Render (`html_renderer.py`):** Converts markdown to HTML. Handles wiki links (`[[...]]` → Obsidian URL), wiki images (`![[img]]` → base64), math normalization (`$...$` → `\(...\)` with pre-tokenization to avoid markdown-it corruption), and appends an Obsidian deeplink footer to the back side.

**Sync (`anki_client.py`):** Calls AnkiConnect HTTP API. Maintains `sync_state.json` (note IDs, content hashes, uploaded media fingerprints) to determine ADD/UPDATE/DELETE/SKIP. Media is fingerprinted (mtime+size) to avoid re-uploading.

**Pipeline (`pipeline.py`):** Dry-run by default — no network calls, no file writes. Requires `--apply-anki-changes` for real changes. After sync, writes `^anki-<id>` bindings back into the source markdown.

## Markdown Metadata Conventions

| Marker | Meaning |
|---|---|
| `^anki-<id>` | Bound Anki note ID (written by tool after first add) |
| `^anki-<id> DELETE` | Mark note for deletion from Anki |
| `^noanki` | Skip this H4 entirely |
| `^id-<alphanum>` | Obsidian block ID on a parent heading |

These must appear as **standalone lines** directly beneath their heading (blank lines permitted between).

## Session Archive Protocol

When the user says "存档", update `MEMORY.md` at the repo root with a new time-ordered entry covering: completed items, problems encountered, solutions, risks, standing instructions, and a task status checklist (`[x]`/`[-]`/`[ ]`).

## Complex Task Protocol

For complex code-generation tasks, **always** produce a design document first (goals, module boundaries, data structures, test plan, risks/migration) and wait for explicit user approval before writing any code.
