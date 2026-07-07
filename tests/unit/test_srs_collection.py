import json
from pathlib import Path
from types import SimpleNamespace

from md2anki.srs_collection import SrsCollection, StaticHtmlBackend


class FakeHtmlBackend:
    def __init__(self):
        self.written: list[Path] = []

    def write_note_html(self, rendered_note, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<html></html>", encoding="utf-8")
        self.written.append(output_path)


def _rendered_note(srs_id: str = "1783400717267", deck_full: str = "DeckA::Parent"):
    parsed = SimpleNamespace(
        srs_note_id=srs_id,
        source_file="notes/a.md",
        line_idx_h4=4,
        h4_heading_pure="Question",
        deck_full=deck_full,
        front_md="Question",
        back_md="Answer",
        no_anki=False,
        no_srs=False,
        delete_requested=False,
    )
    return SimpleNamespace(
        parsed=parsed,
        front_html="<p>Question</p>",
        back_html="<p>Answer</p>",
        back_html_with_footer='<p>Answer</p><a href="obsidian://open?vault=v&file=notes/a%23%5Esrs-1783400717267">open in Obsidian</a>',
        media_files=[],
        obsidian_url="obsidian://open?vault=v&file=notes/a%23%5Esrs-1783400717267",
    )


def test_srs_collection_adds_html_under_deck_path_and_state(tmp_path: Path):
    backend = FakeHtmlBackend()
    collection = SrsCollection(collection_root=tmp_path / "collection", html_backend=backend)

    result = collection.sync([_rendered_note()])

    assert result.added == 1
    assert result.files == ["DeckA/Parent/1783400717267.html"]
    assert (tmp_path / "collection" / "DeckA" / "Parent" / "1783400717267.html").exists()
    state = json.loads((tmp_path / "collection" / "srs_sync_state.json").read_text(encoding="utf-8"))
    assert state["items"]["1783400717267"]["html_path"] == "DeckA/Parent/1783400717267.html"
    assert state["items"]["1783400717267"]["obsidian_url"].endswith("srs-1783400717267")


def test_srs_collection_skips_unchanged_existing_html(tmp_path: Path):
    backend = FakeHtmlBackend()
    collection = SrsCollection(collection_root=tmp_path / "collection", html_backend=backend)
    first = collection.sync([_rendered_note()])
    second = collection.sync([_rendered_note()])

    assert first.added == 1
    assert second.skipped == 1
    assert len(backend.written) == 1


def test_srs_collection_rebuilds_when_state_matches_but_html_file_is_missing(tmp_path: Path):
    backend = FakeHtmlBackend()
    collection = SrsCollection(collection_root=tmp_path / "collection", html_backend=backend)
    first = collection.sync([_rendered_note()])
    html_file = tmp_path / "collection" / "DeckA" / "Parent" / "1783400717267.html"
    html_file.unlink()

    second = collection.sync([_rendered_note()])

    assert first.added == 1
    assert second.updated == 1
    assert html_file.exists()
    assert len(backend.written) == 2


def test_srs_collection_skips_nosrs_note(tmp_path: Path):
    backend = FakeHtmlBackend()
    collection = SrsCollection(collection_root=tmp_path / "collection", html_backend=backend)
    rendered = _rendered_note()
    rendered.parsed.no_srs = True

    result = collection.sync([rendered])

    assert result.skipped == 1
    assert result.dry_run_actions[0]["action"] == "skip_nosrs"
    assert backend.written == []


def test_srs_collection_moves_html_when_deck_changes(tmp_path: Path):
    backend = FakeHtmlBackend()
    collection = SrsCollection(collection_root=tmp_path / "collection", html_backend=backend)

    collection.sync([_rendered_note(deck_full="DeckA::Old")])
    result = collection.sync([_rendered_note(deck_full="DeckA::New")])

    assert result.updated == 1
    assert (tmp_path / "collection" / "DeckA" / "New" / "1783400717267.html").exists()
    assert not (tmp_path / "collection" / "DeckA" / "Old" / "1783400717267.html").exists()


def test_static_html_backend_highlights_code_blocks_without_changing_renderer_contract(tmp_path: Path):
    backend = StaticHtmlBackend(vault_root=tmp_path / "vault")
    rendered = _rendered_note()
    rendered.front_html = '<pre><code class="language-python">def add(a, b):\n    return a + b\n</code></pre>'

    html = backend.build_note_html(rendered, tmp_path / "collection" / "DeckA" / "Parent" / "1783400717267.html")

    assert '<pre class="highlight">' in html
    assert 'class="language-python"' in html
    assert 'class="k">def</span>' in html
    assert 'class="k">return</span>' in html
