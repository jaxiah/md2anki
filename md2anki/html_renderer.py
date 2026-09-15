import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

RE_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
RE_WIKI_IMAGE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
RE_FENCED_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
RE_DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
RE_INLINE_MATH = re.compile(r"(?<!\\)\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)")


class HtmlRenderError(RuntimeError):
    """Raised when authored Markdown cannot be rendered safely for Anki."""


class MermaidRenderError(HtmlRenderError):
    """Raised when a Mermaid block cannot be converted to SVG."""


class MermaidCliRenderer:
    """Render Mermaid source to SVG with the external `mmdc` executable."""

    CACHE_REVISION = "neutral-white"

    def __init__(
        self,
        executable: str = "mmdc",
        timeout_seconds: float = 60.0,
        browser_executable: str | None = None,
        cache_dir: Path | None = None,
    ):
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.browser_executable = browser_executable
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    def render_svg(self, source: str) -> bytes:
        cached_svg = self._read_cached_svg(source)
        if cached_svg is not None:
            return cached_svg

        executable = shutil.which(self.executable)
        if executable is None:
            raise MermaidRenderError(
                "Mermaid CLI executable 'mmdc' was not found on PATH; "
                "install it with: npm install -g @mermaid-js/mermaid-cli"
            )

        with tempfile.TemporaryDirectory(prefix="md2anki-mermaid-") as temp_dir:
            input_path = Path(temp_dir) / "diagram.mmd"
            output_path = Path(temp_dir) / "diagram.svg"
            input_path.write_text(source, encoding="utf-8")
            command = [
                executable,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--theme",
                "neutral",
                "--backgroundColor",
                "white",
                "--quiet",
            ]
            browser_executable = self._resolve_browser_executable()
            if browser_executable is not None:
                puppeteer_config_path = Path(temp_dir) / "puppeteer.json"
                puppeteer_config_path.write_text(
                    json.dumps({"executablePath": browser_executable}),
                    encoding="utf-8",
                )
                command.extend(["--puppeteerConfigFile", str(puppeteer_config_path)])

            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise MermaidRenderError(
                    f"Mermaid CLI timed out after {self.timeout_seconds:g} seconds"
                ) from exc
            except OSError as exc:
                raise MermaidRenderError(f"Mermaid CLI could not be started: {exc}") from exc

            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout or "unknown error").strip()
                raise MermaidRenderError(f"Mermaid CLI failed: {details}")
            if not output_path.is_file():
                raise MermaidRenderError("Mermaid CLI completed without producing an SVG file")

            svg = output_path.read_bytes()
            if not svg.strip():
                raise MermaidRenderError("Mermaid CLI produced an empty SVG file")
            self._write_cached_svg(source, svg)
            return svg

    def _cache_path(self, source: str) -> Path | None:
        if self.cache_dir is None:
            return None
        cache_key = f"{self.CACHE_REVISION}\0{source}"
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.svg"

    def _read_cached_svg(self, source: str) -> bytes | None:
        cache_path = self._cache_path(source)
        if cache_path is None:
            return None
        try:
            svg = cache_path.read_bytes()
        except OSError:
            return None
        return svg if svg.strip() else None

    def _write_cached_svg(self, source: str, svg: bytes) -> None:
        cache_path = self._cache_path(source)
        if cache_path is None:
            return

        temp_path: Path | None = None
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=cache_path.parent,
                prefix=f".{cache_path.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(svg)
                temp_path = Path(temp_file.name)
            temp_path.replace(cache_path)
        except OSError:
            # Caching is an optimization; a read-only or unavailable cache must
            # not turn a successful Mermaid render into a sync failure.
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _resolve_browser_executable(self) -> str | None:
        if self.browser_executable:
            explicit = shutil.which(self.browser_executable)
            if explicit is None and Path(self.browser_executable).is_file():
                explicit = str(Path(self.browser_executable).absolute())
            if explicit is None:
                raise MermaidRenderError(
                    f"configured Mermaid browser executable was not found: {self.browser_executable}"
                )
            return explicit

        candidates: list[Path] = []
        if os.name == "nt":
            for root, relative in [
                (os.getenv("PROGRAMFILES"), "Google/Chrome/Application/chrome.exe"),
                (os.getenv("PROGRAMFILES(X86)"), "Google/Chrome/Application/chrome.exe"),
                (os.getenv("LOCALAPPDATA"), "Google/Chrome/Application/chrome.exe"),
                (os.getenv("PROGRAMFILES"), "Microsoft/Edge/Application/msedge.exe"),
                (os.getenv("PROGRAMFILES(X86)"), "Microsoft/Edge/Application/msedge.exe"),
            ]:
                if root:
                    candidates.append(Path(root) / relative)
        elif os.name == "posix":
            candidates.extend(
                [
                    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                ]
            )

        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

        for command in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"]:
            resolved = shutil.which(command)
            if resolved:
                return resolved
        return None


@dataclass
class MediaItem:
    filename: str
    abs_path: str
    base64_data: str
    source_ref: str


@dataclass
class RenderedNote:
    parsed: Any
    front_html: str
    back_html: str
    back_html_with_footer: str
    model_name: str
    media_files: list[MediaItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    obsidian_url: str | None = None

    @property
    def anki_fields(self) -> dict[str, str]:
        if self.model_name == "Basic":
            return {"Front": self.front_html, "Back": self.back_html_with_footer}
        if self.model_name == "Cloze":
            return {"Text": self.front_html, "Back Extra": self.back_html_with_footer}
        raise ValueError(f"unsupported Anki model: {self.model_name}")


class HtmlRenderer:
    """将 ParsedNote 渲染为 HTML，并收集媒体上传所需的 payload。"""

    def __init__(
        self,
        vault_name: str,
        vault_root: Path,
        asset_root: str = "assets",
        mermaid_renderer: MermaidCliRenderer | None = None,
    ):
        self.vault_name = vault_name
        self.vault_root = Path(vault_root).absolute()
        self.asset_root = asset_root
        self.assets_dir = self.vault_root / asset_root
        self.mermaid_renderer = mermaid_renderer or MermaidCliRenderer(
            cache_dir=self.vault_root / ".md2anki-cache" / "mermaid"
        )
        self._mermaid_cache: dict[str, MediaItem] = {}
        self.md = MarkdownIt("gfm-like", {"html": True, "breaks": True, "linkify": False})

    def render(self, note) -> RenderedNote:
        # front/back 分别渲染，最后统一拼接跳转 footer（指向笔记自身）。
        warnings: list[str] = []
        front_html, front_media, front_warnings = self._render_markdown(note.front_md)
        back_html, back_media, back_warnings = self._render_markdown(note.back_md)
        warnings.extend(front_warnings)
        warnings.extend(back_warnings)

        note_url = self._build_note_url(note)
        footer = (
            '\n<div class="md2anki-source" style="margin-top:8px; font-size:0.85em; opacity:0.75;">'
            f'<a href="{note_url}">open in Obsidian</a></div>'
        )
        back_html_with_footer = f"{back_html}{footer}"

        return RenderedNote(
            parsed=note,
            front_html=front_html,
            back_html=back_html,
            back_html_with_footer=back_html_with_footer,
            model_name=note.model_name,
            media_files=front_media + back_media,
            warnings=warnings,
            obsidian_url=note_url,
        )

    def _render_markdown(self, text: str) -> tuple[str, list[MediaItem], list[str]]:
        # Mermaid must be protected before wiki-link replacement because its own
        # node syntax may contain double square brackets.
        warnings: list[str] = []
        text_with_mermaid_tokens, mermaid_html, mermaid_media = self._protect_mermaid_blocks(text)
        media_payloads: list[MediaItem] = list(mermaid_media)

        def replace_image(match: re.Match) -> str:
            img_ref = match.group(1).strip()
            width_token = (match.group(2) or "").strip()
            width_attr = ""
            if width_token:
                # 兼容 "300" / "300px" 两种宽度写法；非数字值忽略。
                normalized = width_token.rstrip("px")
                if normalized.isdigit():
                    width_attr = f' width="{normalized}"'

            resolved_path, resolve_warnings = self._resolve_image_path(img_ref)
            warnings.extend(resolve_warnings)

            if resolved_path is None:
                warnings.append(f"Image missing: {img_ref}")
                return f"[Image Missing: {img_ref}]"

            try:
                data = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
                media_payloads.append(
                    MediaItem(
                        filename=resolved_path.name,
                        abs_path=str(resolved_path),
                        base64_data=data,
                        source_ref=img_ref,
                    )
                )
                return f'<img src="{resolved_path.name}"{width_attr}>'
            except Exception as exc:
                warnings.append(f"Image read error: {img_ref} ({exc})")
                return f"[Image Error: {img_ref}]"

        text_with_images = RE_WIKI_IMAGE.sub(replace_image, text_with_mermaid_tokens)

        def replace_link(match: re.Match) -> str:
            target = match.group(1).strip()
            alias = (match.group(2) or target).strip()
            url = f"obsidian://open?vault={urllib.parse.quote(self.vault_name)}&file={urllib.parse.quote(target)}"
            return f'<a href="{url}">{html.escape(alias)}</a>'

        text_with_links = RE_WIKI_LINK.sub(replace_link, text_with_images)
        text_with_display_tokens, display_math_map = self._protect_display_math_blocks(text_with_links)
        text_normalized_math = self._normalize_math_delimiters(text_with_display_tokens)
        html_content = self.md.render(text_normalized_math)
        html_content = self._restore_display_math_blocks(html_content, display_math_map)
        html_content = self._restore_mermaid_blocks(html_content, mermaid_html)
        return html_content, media_payloads, warnings

    def _protect_mermaid_blocks(self, text: str) -> tuple[str, dict[str, str], list[MediaItem]]:
        tokens = self.md.parse(text)
        lines = text.splitlines(keepends=True)
        replacements: list[tuple[int, int, str]] = []
        mermaid_html: dict[str, str] = {}
        media_items: list[MediaItem] = []

        for index, token in enumerate(tokens):
            if token.type != "fence" or token.map is None:
                continue
            language = token.info.strip().split(maxsplit=1)[0].lower() if token.info.strip() else ""
            if language != "mermaid":
                continue

            media = self._render_mermaid_media(token.content)
            placeholder = f"MD2ANKI_MERMAID_{index}_{media.filename.removesuffix('.svg')}"
            mermaid_html[placeholder] = (
                '<div class="md2anki-mermaid">'
                f'<img src="{media.filename}" alt="Mermaid diagram">'
                "</div>"
            )
            media_items.append(media)
            replacements.append((token.map[0], token.map[1], placeholder))

        for start_line, end_line, placeholder in reversed(replacements):
            lines[start_line:end_line] = [f"{placeholder}\n"]

        return "".join(lines), mermaid_html, media_items

    def _render_mermaid_media(self, source: str) -> MediaItem:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        cached = self._mermaid_cache.get(digest)
        if cached is not None:
            return cached

        svg = self.mermaid_renderer.render_svg(source)
        media = MediaItem(
            filename=f"md2anki-mermaid-{digest}.svg",
            abs_path="",
            base64_data=base64.b64encode(svg).decode("ascii"),
            source_ref=f"mermaid:{digest}",
        )
        self._mermaid_cache[digest] = media
        return media

    @staticmethod
    def _restore_mermaid_blocks(html_content: str, mermaid_html: dict[str, str]) -> str:
        for placeholder, replacement in mermaid_html.items():
            html_content = html_content.replace(f"<p>{placeholder}</p>\n", f"{replacement}\n")
            html_content = html_content.replace(f"<p>{placeholder}</p>", replacement)
        return html_content

    def _protect_display_math_blocks(self, text: str) -> tuple[str, dict[str, str]]:
        # 对显示公式做 token 保护，避免 markdown-it 改写 LaTeX 反斜杠。
        display_math_map: dict[str, str] = {}
        segments: list[str] = []
        last = 0
        token_index = 0

        for fenced_match in RE_FENCED_CODE_BLOCK.finditer(text):
            normal_part = text[last : fenced_match.start()]
            replaced, token_index = self._replace_display_math_tokens(normal_part, display_math_map, token_index)
            segments.append(replaced)
            segments.append(fenced_match.group(0))
            last = fenced_match.end()

        tail_replaced, _ = self._replace_display_math_tokens(text[last:], display_math_map, token_index)
        segments.append(tail_replaced)
        return "".join(segments), display_math_map

    @staticmethod
    def _replace_display_math_tokens(
        text: str,
        display_math_map: dict[str, str],
        token_index: int,
    ) -> tuple[str, int]:
        def repl_display(match: re.Match) -> str:
            nonlocal token_index
            token = f"MD2ANKI_DISPLAY_MATH_{token_index}"
            token_index += 1
            raw_math = match.group(1)
            display_math_map[token] = f"\\[{raw_math}\\]"
            return f"\n{token}\n"

        def repl_inline(match: re.Match) -> str:
            nonlocal token_index
            token = f"MD2ANKI_INLINE_MATH_{token_index}"
            token_index += 1
            raw_math = match.group(1)
            display_math_map[token] = f"\\({raw_math}\\)"
            return token

        replaced = RE_DISPLAY_MATH.sub(repl_display, text)
        replaced = RE_INLINE_MATH.sub(repl_inline, replaced)
        return replaced, token_index

    @staticmethod
    def _restore_display_math_blocks(html_content: str, display_math_map: dict[str, str]) -> str:
        # Sort longest token first to prevent short tokens from being treated as
        # prefixes of longer ones (e.g. MATH_1 corrupting MATH_10, MATH_11, ...).
        for token, display_math in sorted(display_math_map.items(), key=lambda kv: -len(kv[0])):
            escaped = html.escape(display_math)
            html_content = html_content.replace(f"<p>{token}</p>\n", f"<p>{escaped}</p>\n")
            html_content = html_content.replace(f"<p>{token}</p>", f"<p>{escaped}</p>")
            html_content = html_content.replace(token, escaped)
        return html_content

    def _normalize_math_delimiters(self, text: str) -> str:
        # 仅在非 fenced code 区域执行数学分隔符替换。
        segments: list[str] = []
        last = 0

        for match in RE_FENCED_CODE_BLOCK.finditer(text):
            normal_part = text[last : match.start()]
            segments.append(self._normalize_math_in_plain_text(normal_part))
            segments.append(match.group(0))
            last = match.end()

        segments.append(self._normalize_math_in_plain_text(text[last:]))
        return "".join(segments)

    @staticmethod
    def _normalize_math_in_plain_text(text: str) -> str:
        # Display and inline math are both tokenized before this step;
        # these substitutions are kept only as a safety fallback for any
        # $...$ that somehow escaped tokenization (e.g. edge cases).
        text = RE_DISPLAY_MATH.sub(lambda m: f"\\\\[{m.group(1)}\\\\]", text)
        return text

    def _resolve_image_path(self, img_ref: str) -> tuple[Path | None, list[str]]:
        # 解析优先级：显式路径命中 > asset_root 递归按文件名匹配。
        warnings: list[str] = []

        explicit_candidate = self.assets_dir / img_ref
        if explicit_candidate.exists() and explicit_candidate.is_file():
            return explicit_candidate, warnings

        file_name = Path(img_ref).name
        matches = sorted(
            [path for path in self.assets_dir.rglob(file_name) if path.is_file()],
            key=lambda p: str(p.relative_to(self.assets_dir)).replace("\\", "/"),
        )

        if not matches:
            return None, warnings

        if len(matches) > 1:
            # 同名冲突时保持稳定选择，避免不同机器上行为不一致。
            warnings.append(f"Image ambiguous: {img_ref}; choose {matches[0].relative_to(self.assets_dir)}")

        return matches[0], warnings

    def _build_note_url(self, note: Any) -> str:
        # 将锚点并入 file 参数整体编码，避免在外部 webview 中 fragment 丢失。
        # 若 note 已有 anki_note_id，深链到具体卡片（^anki-<id>）；否则仅链接到文件。
        source_rel = str(note.source_file).replace("\\", "/")
        file_without_md = source_rel[:-3] if source_rel.lower().endswith(".md") else source_rel
        anki_note_id = getattr(note, "anki_note_id", None)
        if anki_note_id:
            target = f"{file_without_md}#^anki-{anki_note_id}"
        else:
            target = file_without_md

        encoded_target = urllib.parse.quote(target, safe="/")
        return f"obsidian://open?vault={urllib.parse.quote(self.vault_name)}&file={encoded_target}"
