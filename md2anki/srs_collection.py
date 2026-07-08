import base64
import hashlib
import html
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound


@dataclass
class SrsSyncResult:
    """一次本地 SRS collection 同步的聚合结果。"""

    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    dry_run_actions: list[dict[str, Any]] = field(default_factory=list)
    bindings_to_writeback: list[dict[str, Any]] = field(default_factory=list)
    deletions_to_writeback: list[dict[str, Any]] = field(default_factory=list)


class HtmlBackend(Protocol):
    def write_note_html(self, rendered_note: Any, output_path: Path) -> None:
        ...


class StaticHtmlBackend:
    """Write rendered front/back fields as a standalone two-panel HTML note."""

    def __init__(self, collection_root: Path | None = None, asset_root: str = "assets", **kwargs):
        if collection_root is None:
            collection_root = kwargs.pop("vault_root", None)
        if collection_root is None:
            raise TypeError("collection_root is required")
        self.collection_root = Path(collection_root).absolute()
        self.asset_root = asset_root
        self.assets_dir = self.collection_root / asset_root

    def write_note_html(self, rendered_note: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.build_note_html(rendered_note, output_path), encoding="utf-8")

    def build_note_html(self, rendered_note: Any, output_path: Path) -> str:
        parsed = getattr(rendered_note, "parsed", None)
        title = html.escape(getattr(parsed, "h4_heading_pure", "") or "SRS note")
        asset_urls = deque(self._materialize_media_assets(rendered_note, output_path))
        front_html = self._prepare_note_html(getattr(rendered_note, "front_html", ""), output_path, asset_urls)
        back_html = self._prepare_note_html(
            getattr(rendered_note, "back_html_with_footer", getattr(rendered_note, "back_html", "")),
            output_path,
            asset_urls,
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)']],
        displayMath: [['\\\\[', '\\\\]']]
      }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --border: #d1d5db;
      --code-bg: #f3f4f6;
      --code-fg: #24292f;
      --link: #0b57d0;
      --syntax-comment: #6a737d;
      --syntax-keyword: #d73a49;
      --syntax-string: #032f62;
      --syntax-number: #005cc5;
      --syntax-function: #6f42c1;
      --syntax-variable: #e36209;
      --syntax-operator: #24292f;
      --syntax-punctuation: #586069;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #111827;
        --panel: #1f2937;
        --text: #f9fafb;
        --muted: #9ca3af;
        --border: #374151;
        --code-bg: #111827;
        --code-fg: #d1d5db;
        --link: #8ab4f8;
        --syntax-comment: #8b949e;
        --syntax-keyword: #ff7b72;
        --syntax-string: #a5d6ff;
        --syntax-number: #79c0ff;
        --syntax-function: #d2a8ff;
        --syntax-variable: #ffa657;
        --syntax-operator: #d8dee4;
        --syntax-punctuation: #c9d1d9;
      }}
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, "Helvetica Neue", sans-serif;
      font-size: 16px;
      line-height: 1.55;
    }}
    main {{
      width: min(980px, calc(100% - 32px));
      margin: 24px auto;
      display: grid;
      gap: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      overflow-wrap: anywhere;
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.3;
      color: var(--muted);
      font-weight: 600;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 14px;
      line-height: 1.2;
      color: var(--muted);
      text-transform: uppercase;
    }}
    p {{
      margin: 0 0 12px;
    }}
    p:last-child {{
      margin-bottom: 0;
    }}
    img {{
      max-width: 100%;
      height: auto;
    }}
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      overflow: auto;
      white-space: pre-wrap;
    }}
    pre code {{
      display: block;
      background: transparent;
      border: none;
      color: inherit;
      padding: 0;
      white-space: pre-wrap;
      overflow-x: auto;
    }}
    pre code span {{
      background: transparent;
    }}
    code {{
      font-family: Consolas, "Liberation Mono", monospace;
      font-size: 0.92em;
      color: var(--code-fg);
    }}
    :not(pre) > code {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      vertical-align: top;
    }}
    a {{
      color: var(--link);
    }}
    .highlight {{
      color: inherit;
      background: transparent;
    }}
    .hljs,
    pre code.hljs,
    pre code[class*="language-"] {{
      color: inherit;
      background: transparent;
    }}
    .codehilite {{
      background: transparent;
    }}
    .highlight .c,
    .highlight .ch,
    .highlight .c1,
    .highlight .cm,
    .highlight .cp,
    .highlight .cpf,
    .highlight .cs,
    .hljs-comment,
    .token.comment,
    .token.prolog,
    .token.doctype,
    .token.cdata {{
      color: var(--syntax-comment) !important;
      font-style: italic;
    }}
    .highlight .k,
    .highlight .kd,
    .highlight .kc,
    .highlight .kn,
    .highlight .kp,
    .highlight .kr,
    .highlight .kt,
    .highlight .ow,
    .hljs-keyword,
    .hljs-literal,
    .token.keyword,
    .token.boolean,
    .token.constant {{
      color: var(--syntax-keyword) !important;
      font-weight: 600;
    }}
    .highlight .s,
    .highlight .sa,
    .highlight .s1,
    .highlight .s2,
    .highlight .sb,
    .highlight .sc,
    .highlight .sd,
    .highlight .se,
    .highlight .sh,
    .highlight .si,
    .highlight .sx,
    .highlight .sr,
    .highlight .ss,
    .highlight .dl,
    .hljs-string,
    .token.string,
    .token.char,
    .token.regex {{
      color: var(--syntax-string) !important;
    }}
    .highlight .m,
    .highlight .mb,
    .highlight .mf,
    .highlight .mh,
    .highlight .mi,
    .highlight .mo,
    .highlight .il,
    .hljs-number,
    .token.number {{
      color: var(--syntax-number) !important;
    }}
    .highlight .nc,
    .highlight .nd,
    .highlight .nf,
    .highlight .fm,
    .hljs-title,
    .hljs-function,
    .hljs-title.function_,
    .hljs-title.class_,
    .token.function,
    .token.class-name,
    .token.decorator {{
      color: var(--syntax-function) !important;
    }}
    .highlight .na,
    .highlight .nb,
    .highlight .bp,
    .highlight .no,
    .highlight .nv,
    .highlight .vc,
    .highlight .vg,
    .highlight .vi,
    .highlight .vm,
    .hljs-variable,
    .hljs-built_in,
    .hljs-params,
    .token.variable,
    .token.builtin,
    .token.parameter {{
      color: var(--syntax-variable) !important;
    }}
    .highlight .o,
    .hljs-operator,
    .token.operator {{
      color: var(--syntax-operator) !important;
    }}
    .highlight .p,
    .hljs-punctuation,
    .token.punctuation {{
      color: var(--syntax-punctuation) !important;
    }}
    .highlight .nt,
    .hljs-meta,
    .hljs-attr,
    .hljs-name,
    .token.property,
    .token.attr-name {{
      color: var(--syntax-variable) !important;
    }}
    .highlight span[style],
    .codehilite span[style] {{
      color: var(--code-fg) !important;
    }}
    .note-title {{
      background: transparent;
      border: 0;
      padding: 0;
    }}
  </style>
</head>
<body>
  <main>
    <section class="note-title">
      <h1>{title}</h1>
    </section>
    <section class="front">
      <h2>Front</h2>
      {front_html}
    </section>
    <section class="back">
      <h2>Back</h2>
      {back_html}
    </section>
  </main>
</body>
</html>"""

    def expected_asset_paths(self, rendered_note: Any) -> list[Path]:
        return [self._asset_path_for_media(media) for media in getattr(rendered_note, "media_files", [])]

    def assets_exist_for(self, rendered_note: Any) -> bool:
        for media in getattr(rendered_note, "media_files", []):
            asset_path = self._asset_path_for_media(media)
            if not asset_path.exists():
                return False
            if asset_path.read_bytes() != base64.b64decode(getattr(media, "base64_data", "")):
                return False
        return True

    def _materialize_media_assets(self, rendered_note: Any, output_path: Path) -> list[str]:
        asset_urls: list[str] = []
        media_files = list(getattr(rendered_note, "media_files", []))
        if media_files:
            self.assets_dir.mkdir(parents=True, exist_ok=True)

        for media in media_files:
            asset_path = self._asset_path_for_media(media)
            data = base64.b64decode(getattr(media, "base64_data", ""))
            if not asset_path.exists() or asset_path.read_bytes() != data:
                asset_path.write_bytes(data)
            rel = os.path.relpath(asset_path, output_path.parent).replace("\\", "/")
            asset_urls.append(rel)

        return asset_urls

    def _asset_path_for_media(self, media: Any) -> Path:
        filename = self._sanitize_asset_filename(getattr(media, "filename", "") or "asset")
        return self.assets_dir / filename

    @staticmethod
    def _sanitize_asset_filename(filename: str) -> str:
        cleaned = Path(filename).name
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", cleaned).strip().rstrip(" .")
        return cleaned or "asset"

    def _rewrite_image_sources(self, html_content: str, output_path: Path, asset_urls: deque[str]) -> str:
        def replace_src(match: re.Match) -> str:
            quote = match.group(1)
            src = match.group(2)
            if "://" in src or src.startswith(("data:", "/", "#")):
                return match.group(0)
            if not asset_urls:
                return match.group(0)
            rel = asset_urls.popleft()
            return f"src={quote}{html.escape(rel, quote=True)}{quote}"

        return re.sub(r"\bsrc=(['\"])([^'\"]+)\1", replace_src, html_content)

    def _prepare_note_html(self, html_content: str, output_path: Path, asset_urls: deque[str]) -> str:
        html_content = self._rewrite_image_sources(html_content, output_path, asset_urls)
        return self._highlight_code_blocks(html_content)

    def _highlight_code_blocks(self, html_content: str) -> str:
        pattern = re.compile(
            r'<pre><code(?: class="language-([^"]+)")?>(.*?)</code></pre>',
            flags=re.DOTALL,
        )

        def replace_code(match: re.Match) -> str:
            language = (match.group(1) or "").strip()
            raw_code = html.unescape(match.group(2))
            try:
                lexer = get_lexer_by_name(language) if language else TextLexer()
            except ClassNotFound:
                lexer = TextLexer()
            highlighted = highlight(raw_code, lexer, HtmlFormatter(nowrap=True, noclasses=False))
            class_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
            return f'<pre class="highlight"><code{class_attr}>{highlighted}</code></pre>'

        return pattern.sub(replace_code, html_content)


class SrsCollection:
    """Synchronize rendered notes into a filesystem-backed SRS HTML collection."""

    def __init__(
        self,
        collection_root: Path,
        state_file: Path | None = None,
        html_backend: HtmlBackend | None = None,
        apply_changes: bool = True,
        fail_fast: bool = True,
    ):
        self.collection_root = Path(collection_root).absolute()
        self.state_file = Path(state_file).absolute() if state_file else self.collection_root / "srs_sync_state.json"
        self.html_backend = html_backend or StaticHtmlBackend(self.collection_root)
        self.apply_changes = apply_changes
        self.fail_fast = fail_fast
        self.state = self.load_state()

    def is_dry_run(self) -> bool:
        return not self.apply_changes

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"schema_version": 1, "items": {}}

        try:
            loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("items"), dict):
                loaded.setdefault("schema_version", 1)
                return loaded
        except Exception:
            pass

        return {"schema_version": 1, "items": {}}

    def save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.state_file)

    def compute_content_hash(self, rendered_note: Any) -> str:
        parsed = getattr(rendered_note, "parsed", None)
        media_payload = [
            {
                "filename": getattr(media, "filename", None),
                "source_ref": getattr(media, "source_ref", None),
                "data_hash": hashlib.sha256(getattr(media, "base64_data", "").encode("utf-8")).hexdigest(),
            }
            for media in getattr(rendered_note, "media_files", [])
        ]
        payload = {
            "srs_note_id": getattr(parsed, "srs_note_id", None),
            "deck_full": getattr(parsed, "deck_full", None),
            "front_md": getattr(parsed, "front_md", None),
            "back_md": getattr(parsed, "back_md", None),
            "obsidian_url": getattr(rendered_note, "obsidian_url", None),
            "media": media_payload,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def output_path_for(self, rendered_note: Any) -> Path:
        parsed = getattr(rendered_note, "parsed", None)
        srs_note_id = getattr(parsed, "srs_note_id", None)
        if not srs_note_id:
            raise ValueError("missing srs_note_id")

        deck_full = getattr(parsed, "deck_full", None) or "Default"
        deck_parts = [self._sanitize_path_segment(part) for part in str(deck_full).split("::") if part.strip()]
        return self.collection_root.joinpath(*deck_parts, f"{srs_note_id}.html")

    def sync(self, rendered_notes: list[Any], progress_callback=None) -> SrsSyncResult:
        result = SrsSyncResult()
        items = self.state.setdefault("items", {})
        state_changed = False
        total_notes = len(rendered_notes)

        for index, rendered in enumerate(rendered_notes, start=1):
            parsed = getattr(rendered, "parsed", None)
            srs_note_id = getattr(parsed, "srs_note_id", None)

            if getattr(parsed, "no_anki", False) and not getattr(parsed, "delete_requested", False):
                result.skipped += 1
                result.dry_run_actions.append(
                    {
                        "action": "skip_nosrs",
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    }
                )
                if progress_callback:
                    progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), "skip_nosrs")
                continue

            if getattr(parsed, "no_srs", False) and not getattr(parsed, "delete_requested", False):
                result.skipped += 1
                result.dry_run_actions.append(
                    {
                        "action": "skip_nosrs",
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    }
                )
                if progress_callback:
                    progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), "skip_nosrs")
                continue

            if getattr(parsed, "delete_requested", False):
                if not srs_note_id:
                    result.failed += 1
                    result.errors.append(f"delete requested but missing srs_note_id for {getattr(parsed, 'source_file', '<unknown>')}")
                    if self.fail_fast:
                        break
                    continue
                old_item = items.get(srs_note_id)
                if self.is_dry_run():
                    result.dry_run_actions.append({"action": "would_delete_html", "srs_note_id": srs_note_id})
                    continue
                if old_item:
                    old_html = self.collection_root / old_item.get("html_path", "")
                    old_html.unlink(missing_ok=True)
                    del items[srs_note_id]
                    state_changed = True
                result.deleted += 1
                result.deletions_to_writeback.append(
                    {
                        "source_file": getattr(parsed, "source_file", None),
                        "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                        "srs_note_id": srs_note_id,
                    }
                )
                if progress_callback:
                    progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), "deleted")
                continue

            if not srs_note_id:
                result.failed += 1
                result.errors.append(f"missing srs_note_id for {getattr(parsed, 'source_file', '<unknown>')}")
                if self.fail_fast:
                    break
                continue

            try:
                output_path = self.output_path_for(rendered)
                rel_html_path = str(output_path.relative_to(self.collection_root)).replace("\\", "/")
                content_hash = self.compute_content_hash(rendered)
                old_item = items.get(srs_note_id)
                old_html_path = old_item.get("html_path") if old_item else None
                assets_exist = True
                if hasattr(self.html_backend, "assets_exist_for"):
                    assets_exist = bool(self.html_backend.assets_exist_for(rendered))

                if (
                    old_item
                    and old_item.get("content_hash") == content_hash
                    and old_html_path == rel_html_path
                    and output_path.exists()
                    and assets_exist
                ):
                    result.skipped += 1
                    if progress_callback:
                        progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), "skip_unchanged")
                    continue

                action = "updated" if old_item else "added"
                if self.is_dry_run():
                    result.dry_run_actions.append(
                        {
                            "action": f"would_{action}_html",
                            "srs_note_id": srs_note_id,
                            "html_path": rel_html_path,
                            "source_file": getattr(parsed, "source_file", None),
                        }
                    )
                    continue

                self.html_backend.write_note_html(rendered, output_path)
                if old_item and old_html_path and old_html_path != rel_html_path:
                    old_output_path = self.collection_root / old_html_path
                    old_output_path.unlink(missing_ok=True)

                items[srs_note_id] = {
                    "content_hash": content_hash,
                    "updated_ts": self._now_iso(),
                    "source_file": getattr(parsed, "source_file", None),
                    "line_idx_h4": getattr(parsed, "line_idx_h4", None),
                    "h4_heading_pure": getattr(parsed, "h4_heading_pure", None),
                    "deck_full": getattr(parsed, "deck_full", None),
                    "html_path": rel_html_path,
                    "obsidian_url": getattr(rendered, "obsidian_url", None),
                }
                state_changed = True
                result.files.append(rel_html_path)
                if old_item:
                    result.updated += 1
                else:
                    result.added += 1
                if progress_callback:
                    progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), action)
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"html sync failed for ^srs-{srs_note_id}: {exc}")
                if progress_callback:
                    progress_callback("html", index, total_notes, getattr(parsed, "h4_heading_pure", None), "failed")
                if self.fail_fast:
                    break

        if state_changed and not self.is_dry_run():
            self.save_state()

        return result

    @staticmethod
    def _sanitize_path_segment(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
        cleaned = cleaned.rstrip(" .")
        return cleaned or "_"
