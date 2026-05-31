# Repository Guidelines

## Project Structure & Module Organization

`md2anki/` contains the installable Python package. The main flow is `pipeline.py`, which connects parsing, rendering, Anki sync, and Markdown writeback. Parsing lives in `markdown_processor.py`, HTML conversion in `html_renderer.py`, AnkiConnect/state handling in `anki_client.py`, and CLI entry points in `cli.py` and `__main__.py`.

Tests are organized by scope: `tests/unit/`, `tests/integration/`, and `tests/e2e/`. Fixtures for parser and renderer behavior are under `tests/fixtures/`. Project notes and release/design references live in `doc/`. `baseline.py` is a legacy/reference implementation, not the package entry point.

## Build, Test, and Development Commands

Install the package in editable mode:

```bash
pip install -e .
pip install -e .[test]
```

Run the test suite:

```bash
pytest -q
pytest tests/unit/test_markdown_processor.py -q
pytest tests/e2e/test_mock_ankiconnect_flow.py -q
```

Run the CLI safely in dry-run mode:

```bash
md2anki --vault-root <path>
```

Apply real Anki and Markdown changes only after reviewing dry-run output:

```bash
md2anki --vault-root <path> --apply-anki-changes
```

E2E tests use a local mock AnkiConnect server and do not touch a real Anki database.

## Coding Style & Naming Conventions

Use Python 3.10+ and keep code compatible with the dependencies in `pyproject.toml`. Follow existing style: 4-space indentation, type hints on public data flow, small dataclasses for structured records, and explicit names such as `ParsedNote`, `RenderedNote`, and `SyncResult`. Keep side effects concentrated in `pipeline.py` and `anki_client.py`; parser and renderer changes should stay deterministic and fixture-testable.

## Testing Guidelines

Use `pytest`. Add unit tests for isolated parser, renderer, CLI, and client behavior. Add integration tests when Markdown fixtures, rendering, and pipeline behavior interact. Use mock AnkiConnect e2e tests for HTTP-boundary behavior without touching a real Anki database. Name files `test_<module_or_behavior>.py` and tests `test_<expected_behavior>`.

## Commit & Pull Request Guidelines

Prefer concise, imperative commits. Existing history mostly uses conventional prefixes such as `feat:` and `fix:`; continue that style for user-visible changes and bug fixes. Pull requests should include the problem, the solution, test commands run, and any AnkiConnect or fixture implications. Include screenshots only for rendered HTML or UI-visible output changes.

## Agent-Specific Instructions

Use CodeGraph for structural code questions in this repository, especially symbol lookup, caller/callee tracing, and impact analysis. Dry-run is the default operational posture: never run apply-mode commands against a real vault unless the task explicitly requires it.
