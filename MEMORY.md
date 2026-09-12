# MEMORY

> Session archive. Add new entries at the top in reverse chronological order.

## Persistent Instructions

- When the user explicitly says "archive":
	- Update the root `MEMORY.md` file.
	- Record completed work, encountered problems, solutions, cautions and risks, and persistent instructions from the session.
	- Update the task status checklist (`[x]` complete / `[-]` in progress / `[ ]` next).

---

## Session Archive - 2026-03-01 (E2E Milestone)

### Time
- 2026-03-01 (local time)

### Completed Work
- Completed the key Phase 3/4 implementation: `AnkiClient` (ADD/UPDATE/DELETE/SKIP, state management, and dry-run), procedural `run_pipeline` orchestration, and Markdown writeback.
- Added and completed end-to-end `DELETE` + `^noanki` support:
	- The parser recognizes `^anki-<id> DELETE` and `^noanki`.
	- After a successful deletion, writeback removes the `^anki` line and adds `^noanki`.
	- Conflict precedence is `DELETE > ^noanki`.
- Fixed writeback offsets when a file contains multiple H4 notes by applying write operations in descending anchor-line order.
- Added parent block ID writeback and fixed a secondary offset bug caused by stale H4 line numbers after parent writeback by reparsing the file immediately afterward.
- Changed content hashing to use Markdown semantics (`deck + front_md + back_md + media_refs`) instead of `front_html/back_html_with_footer`.
- Added a minimal CLI entry point, with dry-run as the default, and script registration. It supports explicitly selecting the vault, sync state, and source file.
- Built a manual E2E suite and a stable real vault fixture:
	- `tests/e2e/manual_vault`, including several Markdown forms and a copied real `gwyn.jpg` image asset.
	- `tests/e2e/test_manual_e2e_flow.py`, containing eight order-dependent cases for manual Anki-side inspection.
- Completed regression verification: all unit tests passed (40 passed), all pipeline integration tests passed (9 passed), and several important manual E2E cases passed.

### Problems Encountered
- `test_01_rerun_should_skip` unexpectedly produced UPDATE because the footer link changed after parent block ID writeback and therefore changed the hash.
- Writing multiple `^anki-...` markers into one file produced incorrect insertion positions.
- Parent block IDs were initially not written back. Adding the writeback then caused a chain of stale-line-number failures.
- Manual E2E runs looked inactive under quiet output, making progress difficult to observe.

### Solutions
- Changed hashing to be Markdown-based so HTML and footer changes do not affect it.
- Changed pipeline writeback to use one operation list (bind/delete/parent), applied in descending line-number order.
- Reparsed each file immediately after parent writeback so subsequent H4 writeback uses refreshed line numbers.
- Added integration regression cases with multiple parents and multiple H4 notes, covering writeback positions and parent ID insertion.
- Changed the manual E2E gate to fail with an explicit, copyable command and removed global pytest quiet mode to improve observability.

### Cautions And Risks
- Manual E2E cases depend on strict ordering and existing state. Before rerunning them, restore or clean up `manual_vault` and the Anki test decks.
- `sync_state` currently includes auxiliary `source_file` and `h4_heading_pure` fields for observability. Business decisions depend only on `anki_note_id -> content_hash`.
- Real E2E tests write to local Anki decks prefixed with `md2ankiTest`. Continue isolating them by prefix and clean them up in batches.

### Persistent User Instructions
- When the user says "archive", update the root `MEMORY.md` first and record every standard section.
- For complex code-generation tasks, use this default workflow: write the design document, obtain user review, and then implement.
- Keep project refactoring lightweight: three classes plus a procedural pipeline, without overengineering.
- Communicate in Chinese by default unless the user explicitly requests English.

### Task Status
- [x] Complete: current Phase 1-4 core capabilities (parsing, rendering, synchronization, and writeback), DELETE + `^noanki`, CLI, unit and integration regressions, and design and implementation of eight manual E2E cases.
- [-] In progress: review the real manual E2E cases in order while the user runs them.
- [ ] Next: make final corrections based on manual E2E results, and add an Anki-side manual verification checklist plus an optional one-command reset script.

## Session Archive - 2026-03-01 (Continued)

### Time
- 2026-03-01 (local time)

### Completed Work
- Completed and verified the Phase 2 `HtmlRenderer` implementation: formulas remain unchanged without special conversion, and wiki links and wiki images render consistently.
- Completed parser and renderer integration tests by adding independent Markdown and asset fixtures and verifying important scenarios.
- Replaced the integration-test image fixture with the contents of the real root-level `gwyn.jpg`, as requested, and verified it through hashes and regression tests.
- Added integration-test result export switches:
	- Parser results export as JSON.
	- Renderer results export as an HTML preview page.
- Renamed the integration renderer export variable to `DUMP_INTEGRATION_RENDERER_HTML` and removed obsolete renderer JSON artifacts.
- Updated [refactor_design.md](refactor_design.md) to correct discrepancies between the document and the implementation, including formula handling, test organization, exported artifacts, and switch names.

### Problems Encountered
- Changing integration-test output from JSON to HTML introduced an `IndentationError` in the test file.
- Documentation had diverged from the implementation, including outdated math-normalization language and inaccurate test-organization details.

### Solutions
- Corrected the indentation in `tests/integration/test_parser_renderer_integration.py` and reran the regression tests.
- Made a minimal update to `refactor_design.md`, changing only outdated descriptions while preserving its overall structure.

### Cautions And Risks
- Integration-test debug artifacts are enabled by default. Repeated runs continue writing to `tests/integration/_parser_renderer_debug/`, which can create workspace noise.
- Renderer output has changed to HTML. Local scripts that still use the old `DUMP_INTEGRATION_RENDERER_JSON` environment variable will no longer work.
- Phase 3 (`AnkiClient` + `sync_state`) had not yet started at this point. Its design needed confirmation before integration work.

### Persistent User Instructions
- When the user says "archive", update the root `MEMORY.md` first and record every standard section.
- For complex code-generation tasks, use this default workflow: write the design document, obtain user review, and then implement.
- Keep project refactoring lightweight: three classes plus a procedural pipeline, without overengineering.
- Communicate in Chinese by default unless the user explicitly requests English.

### Task Status
- [x] Complete: core Phase 2 `HtmlRenderer`, unit tests, parser-renderer integration tests, debug exports (parser JSON and renderer HTML), and documentation updates.
- [-] In progress: none.
- [ ] Next: design and implement Phase 3 (`AnkiClient` + `sync_state`) with mock integration tests, then verify the procedural pipeline end to end.

## Session Archive - 2026-03-01

### Time
- 2026-03-01 (local time)

### Completed Work
- Created and iteratively updated [refactor_design.md](refactor_design.md), converging the architecture on three core classes (`MarkdownProcessor`, `HtmlRenderer`, and `AnkiClient`) plus a procedural pipeline.
- Established the Phase 1 project skeleton: `pyproject.toml`, the `md2anki/` package, a minimal runnable entry point, and placeholder implementations.
- Implemented and iterated on `MarkdownProcessor`:
	- H4 parent selection uses the nearest enclosing heading (H3 > H2 > H1).
	- Parent block IDs are standalone lines below the heading and use the form `^id-xxxx`.
	- H4 Anki IDs are standalone lines below the heading and use the form `^anki-<id>`.
	- Any number of blank lines may appear between a heading and its metadata line.
	- Recognized `^anki-...` markers are excluded from front and back content.
- Expanded and refactored [tests/unit/test_markdown_processor.py](tests/unit/test_markdown_processor.py) to cover multiple blank lines, parent fallback, separators, invalid YAML, writeback deduplication, and related behavior.
- Enabled JSON test exports by default so parsed output can show `raw_md` and `raw_md_lines` side by side.
- Removed test-generated `__pycache__` directories to keep the workspace clean.

### Problems Encountered
- A large documentation patch failed once because its context had drifted.
- The environment initially lacked the `pytest` package.
- Parsing rules evolved quickly, including parent rules, ID placement, naming, and blank-line tolerance, creating temporary inconsistency risks between early tests and implementation.

### Solutions
- Split the patch into smaller sections with precise context instead of applying one large replacement.
- Installed `pytest` in the virtual environment before running targeted tests.
- Used a closed implementation loop: change the implementation, add or update tests, then run `pytest tests/unit/test_markdown_processor.py` after each requirement change.

### Cautions And Risks
- The specification at this point explicitly did not support the legacy form with an ID at the end of a heading line. Importing historical notes would require a separate migration script.
- `MarkdownProcessor` rules had become strict. Future `HtmlRenderer` and pipeline work needed to share the same metadata semantics to avoid divergence.
- Test JSON exports were enabled by default and would continue generating files. An environment variable could disable them when less workspace noise was desired.

### Persistent User Instructions
- When the user says "archive", update the root `MEMORY.md` first and record every standard section.
- For complex code-generation tasks, use this default workflow: write the design document, obtain user review, and then implement.
- Keep project refactoring lightweight: three classes plus a procedural pipeline, without overengineering.

### Task Status
- [x] Complete: Phase 1 skeleton, initial `MarkdownProcessor` and rule iterations, expanded unit tests, JSON comparison exports, and design-document updates.
- [-] In progress: none.
- [ ] Next: implement Phase 2 `HtmlRenderer` (wiki links and images, math normalization, and parent-navigation footer) and complete the corresponding tests.

## Session Archive Template

### Time
- YYYY-MM-DD HH:mm (local time)

### Completed Work
-

### Problems Encountered
-

### Solutions
-

### Cautions And Risks
-

### Persistent User Instructions
-

### Task Status
- [x] Complete:
- [-] In progress:
- [ ] Next:
