import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

RE_ANKI_ID_LINE = re.compile(r"^[ \t]*\^anki-(\d+)[ \t]*$")
RE_ANKI_META_LINE = re.compile(r"^[ \t]*\^anki-(\d+)(?:[ \t]+(DELETE))?[ \t]*$", re.IGNORECASE)
RE_NOANKI_LINE = re.compile(r"^[ \t]*\^noanki[ \t]*$", re.IGNORECASE)
RE_BLOCK_ID_LINE = re.compile(r"^[ \t]*\^(id-[A-Za-z0-9-]+)[ \t]*$")


@dataclass
class ParsedNote:
    source_file: str
    line_idx_h4: int | None
    ankideck_base: str
    deck_full: str
    parent_title: str | None
    parent_block_id: str | None
    parent_line_idx: int | None
    parent_level: int | None
    h4_heading_raw: str
    h4_heading_pure: str
    anki_note_id: str | None
    anki_meta_line_idx: int | None
    delete_requested: bool
    no_anki: bool
    front_md: str
    back_md: str
    split_by_separator: bool


@dataclass
class ParsedDocument:
    source_file: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    notes: list[ParsedNote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MarkdownProcessor:
    """负责 markdown 的解析与局部回写。

    约定：
    - 父节点 id 使用独立行：^id-xxxx（位于 H1/H2/H3 标题之后，可有空行）
    - H4 的 anki id 使用独立行：^anki-<数字>（位于 H4 标题之后，可有空行）
    """

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root).absolute()
        self.md = MarkdownIt("commonmark", {"html": True, "breaks": True, "linkify": True}).use(front_matter_plugin)

    def generate_block_id(self) -> str:
        return f"id-{secrets.token_hex(4)}"

    def _new_block_id_line(self, template_line: str, block_id: str) -> str:
        newline, _ = self._split_newline(template_line)
        newline = newline or "\n"
        return f"^{block_id}{newline}"

    def _read_block_id_below_heading(self, heading_end_line_idx: int | None, lines_all: list[str]) -> str | None:
        block_id, _ = self._find_metadata_line(heading_end_line_idx, lines_all, RE_BLOCK_ID_LINE)
        return block_id

    def _read_anki_id_below_h4(self, h4_end_line_idx: int | None, lines_all: list[str]) -> str | None:
        anki_id, _ = self._find_metadata_line(h4_end_line_idx, lines_all, RE_ANKI_ID_LINE)
        return anki_id

    def _read_h4_metadata_block(self, start_line_idx: int | None, lines_all: list[str]) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "anki_note_id": None,
            "anki_meta_line_idx": None,
            "delete_requested": False,
            "no_anki": False,
            "noanki_line_idx": None,
            "last_meta_line_idx": None,
        }
        if start_line_idx is None or start_line_idx >= len(lines_all):
            return metadata

        idx = start_line_idx
        while idx < len(lines_all):
            while idx < len(lines_all) and lines_all[idx].strip() == "":
                idx += 1
            if idx >= len(lines_all):
                break

            candidate = lines_all[idx]
            anki_match = RE_ANKI_META_LINE.match(candidate)
            if anki_match:
                metadata["anki_note_id"] = anki_match.group(1)
                metadata["anki_meta_line_idx"] = idx
                metadata["delete_requested"] = bool(anki_match.group(2))
                metadata["last_meta_line_idx"] = idx
                idx += 1
                continue

            noanki_match = RE_NOANKI_LINE.match(candidate)
            if noanki_match:
                metadata["no_anki"] = True
                metadata["noanki_line_idx"] = idx
                metadata["last_meta_line_idx"] = idx
                idx += 1
                continue

            break

        return metadata

    def _find_metadata_line(
        self,
        start_line_idx: int | None,
        lines_all: list[str],
        regex: re.Pattern,
    ) -> tuple[str | None, int | None]:
        # 从起始行向下扫描：先跳过空行，再检查第一条非空行是否匹配元信息。
        # 若第一条非空行不是目标元信息，则视为“不存在元信息”，避免误吞正文。
        if start_line_idx is None or start_line_idx >= len(lines_all):
            return None, None

        idx = start_line_idx
        while idx < len(lines_all):
            candidate = lines_all[idx]
            if candidate.strip() == "":
                idx += 1
                continue
            match = regex.match(candidate)
            if not match:
                return None, None
            return match.group(1), idx
        return None, None

    def append_anki_id_to_line(self, line: str, note_id: str | int) -> str:
        newline, _ = self._split_newline(line)
        newline = newline or "\n"
        return f"^anki-{note_id}{newline}"

    def ensure_parent_block_id(self, parent_meta: dict[str, Any] | None, file_lines: list[str]) -> tuple[str | None, bool]:
        # parent_meta 来自最近父节点（H3/H2/H1）解析结果。
        # 若无 id，则在标题下一行插入 ^id-xxxx；若空行后已存在，则复用并不重复插入。
        if not parent_meta:
            return None, False
        block_id = parent_meta.get("block_id")
        if block_id:
            return block_id, False

        line_idx = parent_meta.get("line_idx")
        if line_idx is None or line_idx >= len(file_lines):
            return None, False

        block_id = self.generate_block_id()
        insert_idx = line_idx + 1
        existing_id, _ = self._find_metadata_line(insert_idx, file_lines, RE_BLOCK_ID_LINE)
        if existing_id:
            parent_meta["block_id"] = existing_id
            return existing_id, False
        template_line = file_lines[line_idx]
        file_lines.insert(insert_idx, self._new_block_id_line(template_line, block_id))
        parent_meta["block_id"] = block_id
        return block_id, True

    def append_anki_id_at_line(self, file_lines: list[str], line_idx: int | None, note_id: str | int) -> bool:
        # 在 H4 标题下一行插入 ^anki-...；允许中间有空行并做去重。
        if line_idx is None or not (0 <= line_idx < len(file_lines)):
            return False
        insert_idx = line_idx + 1
        metadata = self._read_h4_metadata_block(insert_idx, file_lines)
        if metadata["anki_note_id"] or metadata["no_anki"]:
            return False
        file_lines.insert(insert_idx, self.append_anki_id_to_line(file_lines[line_idx], note_id))
        return True

    def append_noanki_to_line(self, line: str) -> str:
        newline, _ = self._split_newline(line)
        newline = newline or "\n"
        return f"^noanki{newline}"

    def remove_anki_metadata_and_mark_noanki(self, file_lines: list[str], line_idx_h4: int | None) -> bool:
        if line_idx_h4 is None or not (0 <= line_idx_h4 < len(file_lines)):
            return False

        start_idx = line_idx_h4 + 1
        metadata = self._read_h4_metadata_block(start_idx, file_lines)
        changed = False

        anki_line_idx = metadata.get("anki_meta_line_idx")
        if anki_line_idx is not None and 0 <= anki_line_idx < len(file_lines):
            file_lines.pop(anki_line_idx)
            changed = True
            noanki_line_idx = metadata.get("noanki_line_idx")
            if noanki_line_idx is not None and noanki_line_idx > anki_line_idx:
                metadata["noanki_line_idx"] = noanki_line_idx - 1

        if metadata.get("noanki_line_idx") is None:
            file_lines.insert(start_idx, self.append_noanki_to_line(file_lines[line_idx_h4]))
            changed = True

        return changed

    def parse_file(self, file_path: Path) -> ParsedDocument:
        file_path = Path(file_path)
        content = file_path.read_text(encoding="utf-8")
        return self.parse_content(content, source_file=file_path)

    def parse_content(self, content: str, source_file: str | Path = "<memory>") -> ParsedDocument:
        source_path = Path(source_file) if source_file != "<memory>" else Path("<memory>")
        source_rel = str(source_path)
        if source_path != Path("<memory>"):
            try:
                source_rel = str(source_path.relative_to(self.vault_root)).replace("\\", "/")
            except ValueError:
                source_rel = str(source_path)

        tokens = self.md.parse(content)
        lines_all = content.splitlines()

        frontmatter: dict[str, Any] = {}
        warnings: list[str] = []
        if tokens and tokens[0].type == "front_matter":
            try:
                loaded = yaml.safe_load(tokens[0].content)
                if isinstance(loaded, dict):
                    frontmatter = loaded
            except Exception as exc:
                warnings.append(f"YAML parse error: {exc}")

        anki_deck_base = (frontmatter or {}).get("ankideck")
        if not anki_deck_base:
            return ParsedDocument(source_file=source_rel, frontmatter=frontmatter, notes=[], warnings=warnings)

        # 始终维护“最近父节点”上下文：H3 > H2 > H1。
        # 进入更高层标题时会清空更低层缓存，避免父子关系串层。
        latest_parents: dict[int, dict[str, Any] | None] = {1: None, 2: None, 3: None}
        notes: list[ParsedNote] = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.type == "heading_open" and token.tag in ["h1", "h2", "h3"]:
                level = int(token.tag[1])
                inline_token = tokens[i + 1]
                heading_text = inline_token.content.strip()
                heading_pure = heading_text.strip()
                heading_end_line_idx = token.map[1] if token.map else None
                block_id = self._read_block_id_below_heading(heading_end_line_idx, lines_all)

                latest_parents[level] = {
                    "title": heading_pure,
                    "line_idx": token.map[0] if token.map else None,
                    "block_id": block_id,
                    "level": level,
                }
                # 遇到新父级后，清空其下层最近节点，保持“最近上层”语义正确。
                for lower_level in range(level + 1, 4):
                    latest_parents[lower_level] = None
                i += 2
                continue

            if token.type == "heading_open" and token.tag == "h4":
                inline_token = tokens[i + 1]
                heading_text = inline_token.content.strip()
                heading_line_idx = token.map[0] if token.map else None

                heading_pure = heading_text.strip()
                h4_end_line_idx = token.map[1] if token.map else None
                h4_metadata = self._read_h4_metadata_block(h4_end_line_idx, lines_all)
                anki_id = h4_metadata["anki_note_id"]
                anki_line_idx = h4_metadata["anki_meta_line_idx"]
                delete_requested = h4_metadata["delete_requested"]
                no_anki = h4_metadata["no_anki"]

                if no_anki and not delete_requested:
                    if anki_id:
                        warnings.append(f"noanki with anki id on h4 '{heading_pure}' in {source_rel}; skip this note")
                    if (
                        next((k for k in range(i + 1, len(tokens)) if tokens[k].type == "heading_open" and tokens[k].tag in ["h1", "h2", "h3", "h4"]), None)
                        is not None
                    ):
                        next_heading_token_idx = next(
                            k for k in range(i + 1, len(tokens)) if tokens[k].type == "heading_open" and tokens[k].tag in ["h1", "h2", "h3", "h4"]
                        )
                        i = next_heading_token_idx
                    else:
                        i = len(tokens)
                    continue

                body_start_line = token.map[1] if token.map else 0
                if h4_metadata["last_meta_line_idx"] is not None:
                    # 若识别到元信息行，正文应从元信息之后开始，避免 metadata 混入 back/front。
                    body_start_line = h4_metadata["last_meta_line_idx"] + 1
                next_heading_line = len(lines_all)
                next_heading_token_idx = -1

                for k in range(i + 1, len(tokens)):
                    next_token = tokens[k]
                    if next_token.type == "heading_open" and next_token.tag in ["h1", "h2", "h3", "h4"]:
                        if next_token.map:
                            candidate_line = next_token.map[0]
                            if body_start_line is not None and candidate_line <= body_start_line:
                                continue
                            next_heading_line = candidate_line
                            next_heading_token_idx = k
                        break

                block_lines = lines_all[body_start_line:next_heading_line]
                sep_idx = -1
                for idx, line in enumerate(block_lines):
                    if re.match(r"^[ \t]*---+[ \t]*$", line):
                        sep_idx = idx
                        break

                if sep_idx != -1:
                    front_extra = "\n".join(block_lines[:sep_idx]).strip()
                    front_part = f"{heading_pure}\n\n{front_extra}".strip() if front_extra else heading_pure
                    back_part = "\n".join(block_lines[sep_idx + 1 :]).strip()
                else:
                    front_part = heading_pure
                    back_part = "\n".join(block_lines).strip()

                # 父节点选择优先级：最近 H3，其次 H2，再次 H1。
                parent_meta = latest_parents[3] or latest_parents[2] or latest_parents[1]
                parent_title = parent_meta["title"] if parent_meta else None
                note = ParsedNote(
                    source_file=source_rel,
                    line_idx_h4=heading_line_idx,
                    ankideck_base=anki_deck_base,
                    deck_full=f"{anki_deck_base}::{parent_title}" if parent_title else anki_deck_base,
                    parent_title=parent_title,
                    parent_block_id=parent_meta.get("block_id") if parent_meta else None,
                    parent_line_idx=parent_meta.get("line_idx") if parent_meta else None,
                    parent_level=parent_meta.get("level") if parent_meta else None,
                    h4_heading_raw=heading_text,
                    h4_heading_pure=heading_pure,
                    anki_note_id=anki_id,
                    anki_meta_line_idx=anki_line_idx,
                    delete_requested=delete_requested,
                    no_anki=no_anki,
                    front_md=front_part,
                    back_md=back_part,
                    split_by_separator=sep_idx != -1,
                )
                notes.append(note)

                if next_heading_token_idx != -1:
                    i = next_heading_token_idx
                else:
                    i = len(tokens)
                continue

            i += 1

        return ParsedDocument(source_file=source_rel, frontmatter=frontmatter, notes=notes, warnings=warnings)

    @staticmethod
    def _split_newline(line: str) -> tuple[str, str]:
        if line.endswith("\r\n"):
            return "\r\n", line[:-2]
        if line.endswith("\n"):
            return "\n", line[:-1]
        return "", line
