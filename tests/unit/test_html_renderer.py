import os
from dataclasses import dataclass
from pathlib import Path

from md2anki import HtmlRenderer


@dataclass
class FakeParsedNote:
    source_file: str
    front_md: str
    back_md: str
    parent_title: str | None = None
    anki_note_id: str | None = None


DUMP_RENDERED_NOTE_HTML = os.getenv("DUMP_RENDERED_NOTE_HTML", "1") == "1"
RENDERED_NOTE_DUMP_DIR = Path(__file__).resolve().parent / "_rendered_note_html"


def _dump_rendered_html(case_name: str, rendered) -> None:
    if not DUMP_RENDERED_NOTE_HTML:
        return
    RENDERED_NOTE_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    html_doc = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <title>{case_name}</title>
    <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['\\\\(', '\\\\)']],
                displayMath: [['\\\\[', '\\\\]']]
            }}
        }};
    </script>
    <script defer src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js\"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 1.5rem; }}
        pre {{ background: #f6f8fa; padding: 0.75rem; white-space: pre-wrap; }}
        section {{ margin-bottom: 1.25rem; }}
    </style>
</head>
<body>
    <h1>{case_name}</h1>
    <section>
        <h2>Front HTML</h2>
        {rendered.front_html}
    </section>
    <section>
        <h2>Back HTML</h2>
        {rendered.back_html}
    </section>
    <section>
        <h2>Back HTML With Footer</h2>
        {rendered.back_html_with_footer}
    </section>
    <section>
        <h2>Warnings</h2>
        <pre>{"\n".join(rendered.warnings) if rendered.warnings else "(none)"}</pre>
    </section>
</body>
</html>"""
    (RENDERED_NOTE_DUMP_DIR / f"{case_name}.html").write_text(html_doc, encoding="utf-8")


def _render_case(case_name: str, renderer: HtmlRenderer, note: FakeParsedNote):
    rendered = renderer.render(note)
    _dump_rendered_html(case_name, rendered)
    return rendered


def _new_renderer(tmp_path: Path) -> HtmlRenderer:
    vault_root = tmp_path / "vault"
    (vault_root / "assets").mkdir(parents=True, exist_ok=True)
    return HtmlRenderer(vault_name="sample-notes", vault_root=vault_root, asset_root="assets")


def test_footer_links_to_note_with_anki_id(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="folder/a.md",
        front_md="**Front**",
        back_md="Back text",
        parent_title="Parent",
        anki_note_id="a1b2c3d4",
    )

    rendered = _render_case("footer_links_to_note_with_anki_id", renderer, note)

    assert "<strong>Front</strong>" in rendered.front_html
    assert "Back text" in rendered.back_html
    # Footer links to the note itself via ^anki-<id>
    assert "file=folder/a%23%5Eanki-a1b2c3d4" in rendered.back_html_with_footer
    # Label is the file stem, not the parent title
    assert ">a<" in rendered.back_html_with_footer
    assert "font-size:0.85em" in rendered.back_html_with_footer
    # obsidian_url is exposed for URL drift tracking
    assert rendered.obsidian_url is not None
    assert "anki-a1b2c3d4" in rendered.obsidian_url


def test_footer_links_to_file_only_when_no_anki_id(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="folder/a.md",
        front_md="F",
        back_md="B",
        parent_title="Parent Topic",
        # no anki_note_id → file-only URL, no anchor
    )

    rendered = _render_case("footer_links_to_file_only_when_no_anki_id", renderer, note)

    assert "file=folder/a" in rendered.back_html_with_footer
    assert "%23" not in rendered.back_html_with_footer
    assert ">a<" in rendered.back_html_with_footer
    assert rendered.obsidian_url is not None
    assert "#" not in rendered.obsidian_url


def test_wiki_link_conversion_with_alias(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md="[[RL/Policy Gradient|PG]]",
        back_md="ok",
    )

    rendered = _render_case("wiki_link_with_alias", renderer, note)

    assert "obsidian://open?vault=sample-notes&file=RL/Policy%20Gradient" in rendered.front_html
    assert ">PG<" in rendered.front_html


def test_wiki_image_explicit_nested_path_and_width(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    asset = renderer.assets_dir / "figures" / "chart.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"pngdata")

    note = FakeParsedNote(
        source_file="x.md",
        front_md="![[figures/chart.png|300]]",
        back_md="ok",
    )

    rendered = _render_case("wiki_image_explicit_nested_path", renderer, note)

    assert '<img src="chart.png" width="300">' in rendered.front_html
    assert len(rendered.media_files) == 1
    assert rendered.media_files[0].filename == "chart.png"
    assert rendered.media_files[0].source_ref == "figures/chart.png"


def test_wiki_image_recursive_filename_resolution(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    asset = renderer.assets_dir / "deep" / "nested" / "a.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"abc")

    note = FakeParsedNote(
        source_file="x.md",
        front_md="![[a.png]]",
        back_md="ok",
    )

    rendered = _render_case("wiki_image_recursive_filename", renderer, note)

    assert '<img src="a.png">' in rendered.front_html
    assert len(rendered.media_files) == 1
    assert rendered.media_files[0].filename == "a.png"


def test_wiki_image_ambiguous_filename_uses_stable_pick_and_warning(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    p1 = renderer.assets_dir / "a" / "dup.png"
    p2 = renderer.assets_dir / "z" / "dup.png"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p2.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"one")
    p2.write_bytes(b"two")

    note = FakeParsedNote(
        source_file="x.md",
        front_md="![[dup.png]]",
        back_md="ok",
    )

    rendered = _render_case("wiki_image_ambiguous_filename", renderer, note)

    assert '<img src="dup.png">' in rendered.front_html
    assert len(rendered.media_files) == 1
    assert any("Image ambiguous: dup.png" in warning for warning in rendered.warnings)
    assert rendered.media_files[0].abs_path.endswith(str(p1).replace("/", "\\"))


def test_wiki_image_missing_adds_warning_and_placeholder(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md="![[missing.png]]",
        back_md="ok",
    )

    rendered = _render_case("wiki_image_missing", renderer, note)

    assert "[Image Missing: missing.png]" in rendered.front_html
    assert any("Image missing: missing.png" in warning for warning in rendered.warnings)
    assert rendered.media_files == []


def test_math_delimiters_are_normalized_by_renderer(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md="Inline: $E=mc^2$\n\n$$x^2 + 1$$",
        back_md="ok",
    )

    rendered = _render_case("math_delimiters_normalized", renderer, note)

    assert "\\(E=mc^2\\)" in rendered.front_html
    assert "\\[x^2 + 1\\]" in rendered.front_html
    assert "x^2 + 1" in rendered.front_html


def test_math_delimiters_inside_fenced_code_remain_untouched(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md="""Inline: $E=mc^2$\n\n```python\nexpr = "$E=mc^2$"\nblock = "$$x^2 + 1$$"\n```""",
        back_md="ok",
    )

    rendered = _render_case("math_delimiters_fenced_code_untouched", renderer, note)

    assert "\\(E=mc^2\\)" in rendered.front_html
    assert "$E=mc^2$" in rendered.front_html
    assert "$$x^2 + 1$$" in rendered.front_html


def test_multiline_display_math_preserves_backslashes(tmp_path: Path):
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md="""$$
\\begin{aligned}
&A+A'\\cdot B\\\\
=&A+A\\cdot B+A'\\cdot B \\\\
=&A+(A+A')\\cdot B \\\\
=&A+B
\\end{aligned}
$$""",
        back_md="ok",
    )

    rendered = _render_case("multiline_display_math_preserves_backslashes", renderer, note)

    assert "\\[" in rendered.front_html
    assert "\\begin{aligned}" in rendered.front_html
    assert "\\end{aligned}" in rendered.front_html
    assert "\\\\" in rendered.front_html


def test_inline_math_preserves_escaped_braces(tmp_path: Path):
    """\\{ and \\} inside $...$ must not be stripped by markdown-it backslash escaping."""
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md=r"Set: $\left\{C_{i,j,0} \mid i,j \in M\times N\right\}$ and $\{A_{ik} B_{kj}\}$",
        back_md="ok",
    )

    rendered = _render_case("inline_math_escaped_braces", renderer, note)

    assert r"\left\{" in rendered.front_html
    assert r"\right\}" in rendered.front_html
    assert r"\{A_{ik}" in rendered.front_html
    assert r"\}" in rendered.front_html


def test_inline_math_preserves_other_backslash_commands(tmp_path: Path):
    """\\frac, \\cdot and other letter-based commands must be untouched."""
    renderer = _new_renderer(tmp_path)
    note = FakeParsedNote(
        source_file="x.md",
        front_md=r"$\frac{a}{b} + \alpha \cdot \beta$",
        back_md="ok",
    )

    rendered = _render_case("inline_math_backslash_commands", renderer, note)

    assert r"\frac{a}{b}" in rendered.front_html
    assert r"\alpha" in rendered.front_html
    assert r"\cdot" in rendered.front_html
