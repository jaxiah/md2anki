import json
from pathlib import Path

from md2anki.cli import main as cli_main


def _write_html_vault(vault_root: Path) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    assets_dir = vault_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "diagram.png").write_bytes(b"diagram")
    (assets_dir / "plot.png").write_bytes(b"plot")
    (vault_root / "cards.md").write_text(
        """---
ankideck: HtmlDeck
---

### Parent

#### Media Card

front hint

---

Back with image:

![[diagram.png|280]]

```python
def add(a, b):
    return a + b
```

#### Delete Card

delete me
""",
        encoding="utf-8",
    )


def _run_html_cli(vault_root: Path, collection_root: Path, *extra_args: str) -> int:
    return cli_main(
        [
            "--to-html",
            "--vault-root",
            str(vault_root),
            "--collection-root",
            str(collection_root),
            *extra_args,
        ]
    )


def test_html_collection_cli_generates_portable_files_and_skips_rerun(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "vault"
    collection_root = tmp_path / "collection"
    mathjax_source = tmp_path / "tex-mml-chtml.js"
    mathjax_source.write_text("window.MathJax = window.MathJax || {};", encoding="utf-8")
    _write_html_vault(vault_root)
    monkeypatch.setenv("MD2ANKI_MATHJAX_SOURCE", str(mathjax_source))
    monkeypatch.setattr("md2anki.pipeline.time.time", lambda: 1783400717.267)

    first_code = _run_html_cli(vault_root, collection_root)
    second_code = _run_html_cli(vault_root, collection_root)

    assert first_code == 0
    assert second_code == 0
    markdown = (vault_root / "cards.md").read_text(encoding="utf-8")
    assert "^srs-1783400717267" in markdown
    assert "^srs-1783400717268" in markdown

    state = json.loads((collection_root / "srs_sync_state.json").read_text(encoding="utf-8"))
    assert len(state["items"]) == 2
    media_html = collection_root / "HtmlDeck" / "Parent" / "1783400717267.html"
    delete_html = collection_root / "HtmlDeck" / "Parent" / "1783400717268.html"
    assert media_html.exists()
    assert delete_html.exists()
    assert (collection_root / "assets" / "diagram.png").read_bytes() == b"diagram"
    assert (collection_root / "assets" / "mathjax" / "tex-mml-chtml.js").exists()

    html = media_html.read_text(encoding="utf-8")
    assert 'src="../../assets/diagram.png"' in html
    assert "vault/assets" not in html
    assert "assets/mathjax/tex-mml-chtml.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert 'class="k">def</span>' in html
    assert "file=cards%23%5Esrs-1783400717267" in html


def test_html_collection_cli_delete_writes_nosrs_and_removes_file(tmp_path: Path, monkeypatch):
    vault_root = tmp_path / "vault"
    collection_root = tmp_path / "collection"
    _write_html_vault(vault_root)
    monkeypatch.setattr("md2anki.pipeline.time.time", lambda: 1783400717.267)

    assert _run_html_cli(vault_root, collection_root) == 0
    delete_html = collection_root / "HtmlDeck" / "Parent" / "1783400717268.html"
    assert delete_html.exists()

    markdown_path = vault_root / "cards.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown = markdown.replace("^srs-1783400717268", "^srs-1783400717268 DEL")
    markdown_path.write_text(markdown, encoding="utf-8")

    assert _run_html_cli(vault_root, collection_root) == 0

    updated = markdown_path.read_text(encoding="utf-8")
    assert "^srs-1783400717268" not in updated
    assert "^nosrs" in updated
    assert not delete_html.exists()
    state = json.loads((collection_root / "srs_sync_state.json").read_text(encoding="utf-8"))
    assert "1783400717268" not in state["items"]
