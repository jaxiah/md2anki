import os
import re
import json
import hashlib
import urllib.parse
import secrets
import base64
import html
import yaml
import requests
from pathlib import Path
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

# --- 配置区 ---
VAULT_NAME = "sample-notes"
VAULT_ROOT = Path("D:/sample-notes")  # 你的库根目录
ASSETS_DIR = VAULT_ROOT / "assets"
SYNC_STATE_FILE = VAULT_ROOT / "sync_state.json"
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
GENERATE_PARSED_OUTPUT = False
GENERATE_NOTE_HTML = True
APPLY_ANKI_CHANGES = False

# --- 正则匹配 ---
RE_ANKI_ID = re.compile(r" \^anki-(\d+)$")
RE_BLOCK_ID = re.compile(r" \^([A-Za-z0-9-]+)$")
RE_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
RE_WIKI_IMAGE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
RE_BLOCK_MATH = re.compile(r"(^|\n)\s*\$\$(.+?)\$\$\s*(?=\n|$)", re.DOTALL)


class AnkiSync:
    def __init__(self):
        self.md = MarkdownIt("commonmark", {"html": True, "breaks": True, "linkify": True}).use(front_matter_plugin)
        self.vault_root = VAULT_ROOT.absolute()
        self.output_dir = Path.cwd()
        self.apply_changes = APPLY_ANKI_CHANGES
        self.state = self.load_state()
        self.deck_cache = self.load_deck_cache()

    def load_state(self):
        if SYNC_STATE_FILE.exists():
            try:
                with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"[ERROR] load_state failed: {e}")
        return {}

    def save_state(self):
        with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4, ensure_ascii=False)

    def log(self, message):
        print(f"[sync] {message}")

    def is_dry_run(self):
        return not self.apply_changes

    def invoke(self, action, **params):
        if self.is_dry_run():
            self.log(f"[DRY-RUN] skip invoke {action}")
            return True, None
        payload = {"action": action, "version": 6, "params": params}
        try:
            response = requests.post(
                ANKI_CONNECT_URL,
                json=payload,
                timeout=15,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                self.log(f"[ANKI-ERR] {action}: {data['error']}")
                return False, None
            return True, data.get("result")
        except Exception as exc:
            self.log(f"[ERROR] invoke {action}: {exc}")
            return False, None

    def load_deck_cache(self):
        if self.is_dry_run():
            self.log("[INFO] Dry-run: skipping deck cache load")
            return set()
        success, result = self.invoke("deckNamesAndIds")
        if success and isinstance(result, dict):
            return set(result.keys())
        self.log("[WARN] Unable to load deck list; will create decks on demand")
        return set()

    def ensure_deck(self, deck_name):
        if not deck_name:
            return False
        if deck_name in self.deck_cache or self.is_dry_run():
            return True
        success, _ = self.invoke("createDeck", deck=deck_name)
        if success:
            self.deck_cache.add(deck_name)
            self.log(f"[DECK] ensured '{deck_name}'")
            return True
        self.log(f"[ERROR] Failed to create deck '{deck_name}'")
        return False

    def sanitize_rel_path(self, file_path):
        rel_path = os.path.relpath(file_path, self.vault_root)
        sanitized = rel_path.replace("\\", "__").replace("/", "__")
        if sanitized.lower().endswith(".md"):
            sanitized = sanitized[:-3]
        return sanitized

    def generate_block_id(self):
        return f"md2anki-h3-{secrets.token_hex(4)}"

    def append_block_id_to_line(self, line, block_id):
        newline = ""
        if line.endswith("\r\n"):
            newline = "\r\n"
            core = line[:-2]
        elif line.endswith("\n"):
            newline = "\n"
            core = line[:-1]
        else:
            core = line
        if RE_BLOCK_ID.search(core):
            return line
        return f"{core} ^{block_id}{newline}"

    def append_id_to_line(self, line, new_id):
        newline = ""
        if line.endswith("\r\n"):
            newline = "\r\n"
            core = line[:-2]
        elif line.endswith("\n"):
            newline = "\n"
            core = line[:-1]
        else:
            core = line
        if RE_ANKI_ID.search(core):
            return line
        return f"{core} ^anki-{new_id}{newline}"

    def ensure_parent_block_id(self, parent_meta, file_lines, rel_path):
        if not parent_meta:
            return None, False
        block_id = parent_meta.get("block_id")
        if block_id or self.is_dry_run():
            return block_id, False
        line_idx = parent_meta.get("line_idx")
        if line_idx is None or line_idx >= len(file_lines):
            self.log(f"[WARN] Unable to insert H3 block id for '{parent_meta.get('title', 'H3')}' in {rel_path}")
            return None, False
        block_id = self.generate_block_id()
        file_lines[line_idx] = self.append_block_id_to_line(file_lines[line_idx], block_id)
        parent_meta["block_id"] = block_id
        self.log(f"[H3-ID] {rel_path} line {line_idx + 1} -> ^{block_id}")
        return block_id, True

    def compute_note_hash(self, front, back):
        raw = f"{front}\n<<<BACK>>>\n{back}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def write_note_preview_html(self, sanitized_base, note_idx, heading, front_html, back_html):
        html_path = self.output_dir / f"{sanitized_base}_note_{note_idx}.html"
        title = html.escape(heading)
        content = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 1.5rem; }}
section {{ margin-bottom: 1.5rem; }}
pre {{ background: #f4f4f4; padding: 0.75rem; overflow-x: auto; }}
</style>
</head>
<body>
<h1>{title}</h1>
<section>
<h2>Front</h2>
{front_html}
</section>
<hr />
<section>
<h2>Back</h2>
{back_html}
</section>
</body>
</html>"""
        html_path.write_text(content, encoding="utf-8")
        self.log(f"[HTML] {html_path.name}")

    def get_obsidian_url(self, file_path, heading=None):
        rel_path = os.path.relpath(file_path, self.vault_root)
        name = rel_path.replace(".md", "").replace("\\", "/")
        url = f"obsidian://open?vault={urllib.parse.quote(VAULT_NAME)}&file={urllib.parse.quote(name)}"
        if heading:
            url += f"#{urllib.parse.quote(heading, safe='^')}"
        return url

    def normalize_block_math(self, text):
        def repl(match):
            leading = match.group(1)
            body = match.group(2).strip()
            return f"{leading}\\[\n{body}\n\\]"

        return RE_BLOCK_MATH.sub(repl, text)

    def process_content(self, text, file_path):
        media_payloads = []
        text = self.normalize_block_math(text)

        def replace_image(match):
            img_name = match.group(1).strip()
            width_token = (match.group(2) or "").strip()
            width_attr = ""
            if width_token:
                width_token = width_token.rstrip("px")
                if width_token.isdigit():
                    width_attr = f' width="{width_token}"'
            img_path = ASSETS_DIR / img_name
            if not img_path.exists():
                self.log(f"[WARN] Image missing: {img_name} ({file_path.name})")
                return f"[Image Missing: {img_name}]"
            try:
                data = base64.b64encode(img_path.read_bytes()).decode("utf-8")
                media_payloads.append({"filename": img_name, "data": data})
                return f'<img src="{img_name}"{width_attr}>'
            except Exception as exc:
                self.log(f"[ERROR] Failed to read image {img_name}: {exc}")
                return f"[Image Error: {img_name}]"

        text_with_images = RE_WIKI_IMAGE.sub(replace_image, text)

        def replace_link(match):
            target = match.group(1).strip()
            alias = match.group(2) or target
            url = f"obsidian://open?vault={urllib.parse.quote(VAULT_NAME)}&file={urllib.parse.quote(target)}"
            return f'<a href="{url}">{alias}</a>'

        text_with_links = RE_WIKI_LINK.sub(replace_link, text_with_images)
        html_content = self.md.render(text_with_links)
        return html_content, media_payloads

    def run(self):
        self.log(f"Scanning vault: {self.vault_root}")
        generated_outputs = 0
        for root, dirs, files in os.walk(self.vault_root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".venv"]
            for file in files:
                if not file.endswith(".md"):
                    continue
                file_path = Path(root) / file
                notes = self.process_file(file_path)
                if not notes:
                    continue
                if GENERATE_PARSED_OUTPUT:
                    self.write_parse_output(file_path, notes)
                self.sync_notes(file_path, notes)
                generated_outputs += 1
        self.save_state()
        self.log(f"Done. Generated {generated_outputs} parse files.")

    def process_file(self, file_path):
        content = file_path.read_text(encoding="utf-8")
        tokens = self.md.parse(content)
        lines_all = content.splitlines()
        frontmatter = {}
        if tokens and tokens[0].type == "front_matter":
            try:
                frontmatter = yaml.safe_load(tokens[0].content)
            except Exception as e:
                self.log(f"[ERROR] YAML parse error in {file_path.name}: {e}")
        anki_deck_base = (frontmatter or {}).get("ankideck")
        if not anki_deck_base:
            self.log(f"[SKIP] {os.path.relpath(file_path, self.vault_root)} missing ankideck")
            return []
        current_l3_meta = None
        notes_to_sync = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.type == "heading_open" and token.tag == "h3":
                inline_token = tokens[i + 1]
                heading_text = inline_token.content.strip()
                block_match = RE_BLOCK_ID.search(heading_text)
                if block_match:
                    block_id = block_match.group(1)
                    heading_pure = RE_BLOCK_ID.sub("", heading_text).strip()
                else:
                    block_id = None
                    heading_pure = heading_text.strip()
                current_l3_meta = {
                    "title": heading_pure,
                    "line_idx": token.map[0] if token.map else None,
                    "block_id": block_id,
                }
                i += 2
                continue
            if token.type == "heading_open" and token.tag == "h4":
                inline_token = tokens[i + 1]
                heading_text = inline_token.content.strip()
                heading_line_idx = token.map[0] if token.map else None
                anki_id = None
                match = RE_ANKI_ID.search(heading_text)
                if match:
                    anki_id = match.group(1)
                    heading_pure = RE_ANKI_ID.sub("", heading_text).strip()
                else:
                    heading_pure = heading_text.strip()
                body_start_line = token.map[1] if token.map else 0
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
                    if re.match(r"^[ \t]*---+[ \t]*$", line.strip()):
                        sep_idx = idx
                        break
                if sep_idx != -1:
                    front_extra = "\n".join(block_lines[:sep_idx]).strip()
                    front_part = f"{heading_pure}\n\n{front_extra}".strip() if front_extra else heading_pure
                    back_part = "\n".join(block_lines[sep_idx + 1 :]).strip()
                else:
                    front_part = heading_pure
                    back_part = "\n".join(block_lines).strip()
                parent_title = current_l3_meta["title"] if current_l3_meta else None
                notes_to_sync.append(
                    {
                        "id": anki_id,
                        "front": front_part,
                        "back": back_part,
                        "deck": f"{anki_deck_base}::{parent_title}" if parent_title else anki_deck_base,
                        "l3_heading": parent_title,
                        "l3_meta": current_l3_meta,
                        "line_idx": heading_line_idx,
                        "original_heading": heading_text,
                    }
                )
                if next_heading_token_idx != -1:
                    i = next_heading_token_idx
                else:
                    i = len(tokens)
                continue
            i += 1
        return notes_to_sync

    def write_parse_output(self, file_path, notes):
        sanitized = self.sanitize_rel_path(file_path)
        output_name = f"{sanitized}_parsed.md"
        output_path = self.output_dir / output_name
        rel_path = os.path.relpath(file_path, self.vault_root)
        lines = [f"# Parsed Notes - {rel_path}", ""]
        for note in notes:
            lines.append("--- PARSED NOTE ---")
            lines.append(f"Deck: {note['deck']}")
            lines.append("Front:")
            lines.append(note["front"] or "")
            lines.append("Back:")
            lines.append(note["back"] or "")
            lines.append("-------------------")
            lines.append("")
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def sync_notes(self, file_path, notes):
        if not notes:
            return
        rel_path = os.path.relpath(file_path, self.vault_root)
        sanitized = self.sanitize_rel_path(file_path) if GENERATE_NOTE_HTML else None
        file_lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        file_changed = False
        dry_run = self.is_dry_run()
        for idx, note in enumerate(notes, 1):
            note_id = note.get("id")
            note_key = f"^anki-{note_id}" if note_id else None
            note_hash = self.compute_note_hash(note["front"], note["back"])
            if not self.ensure_deck(note["deck"]):
                self.log(f"[ERROR] Cannot sync note without deck: {note['original_heading']} ({rel_path})")
                continue
            front_html, front_media = self.process_content(note["front"], file_path)
            back_html, back_media = self.process_content(note["back"], file_path)
            parent_meta = note.get("l3_meta")
            if parent_meta:
                block_id, inserted = self.ensure_parent_block_id(parent_meta, file_lines, rel_path)
                if inserted:
                    file_changed = True
                parent_label = parent_meta.get("title") or file_path.stem
                if block_id:
                    parent_url = self.get_obsidian_url(file_path, f"^{block_id}")
                else:
                    parent_url = self.get_obsidian_url(file_path, parent_label)
            else:
                parent_label = file_path.stem
                parent_url = self.get_obsidian_url(file_path)
            parent_footer = f'\n<div class="md2anki-parent"><a href="{parent_url}">Jump to {html.escape(parent_label)}</a></div>'
            back_html_with_footer = f"{back_html}{parent_footer}"
            if GENERATE_NOTE_HTML and sanitized:
                self.write_note_preview_html(sanitized, idx, note["original_heading"], front_html, back_html_with_footer)
            prev_hash = self.state.get(note_key) if note_key else None
            if note_key and prev_hash == note_hash:
                self.log(f"[SKIP] {note_key} unchanged ({rel_path})")
                continue
            if dry_run:
                action = "UPDATE" if note_id else "ADD"
                ident = note_key or note["original_heading"]
                self.log(f"[DRY-RUN] Would {action} {ident} deck={note['deck']} ({rel_path})")
                continue
            media_payloads = front_media + back_media
            media_failed = False
            for media in media_payloads:
                success, _ = self.invoke("storeMediaFile", filename=media["filename"], data=media["data"])
                if not success:
                    self.log(f"[ERROR] Failed to store media '{media['filename']}' for {rel_path}")
                    media_failed = True
                    break
            if media_failed:
                continue
            if note_id:
                update_params = {
                    "note": {
                        "id": int(note_id),
                        "fields": {"Front": front_html, "Back": back_html_with_footer},
                    }
                }
                success, _ = self.invoke("updateNoteFields", **update_params)
                if not success:
                    self.log(f"[ERROR] update failed for {note_key} ({rel_path})")
                    continue
                self.log(f"[UPDATE] {note_key} deck={note['deck']}")
                self.state[note_key] = note_hash
            else:
                add_payload = {
                    "deckName": note["deck"],
                    "modelName": "Basic",
                    "fields": {"Front": front_html, "Back": back_html_with_footer},
                    "options": {"allowDuplicate": False},
                    "tags": ["md2anki"],
                }
                success, result = self.invoke("addNote", note=add_payload)
                if not success or result is None:
                    self.log(f"[ERROR] addNote failed for heading '{note['original_heading']}' in {rel_path}")
                    continue
                note_id = str(result)
                note["id"] = note_id
                note_key = f"^anki-{note_id}"
                line_idx = note.get("line_idx")
                if line_idx is not None and 0 <= line_idx < len(file_lines):
                    file_lines[line_idx] = self.append_id_to_line(file_lines[line_idx], note_id)
                    file_changed = True
                    self.log(f"[ID] {rel_path} line {line_idx + 1} -> ^anki-{note_id}")
                else:
                    self.log(f"[WARN] Unable to write ID for '{note['original_heading']}' (line unavailable).")
                self.state[note_key] = note_hash
                self.log(f"[ADD] {note_key} deck={note['deck']}")
        if file_changed and self.apply_changes:
            file_path.write_text("".join(file_lines), encoding="utf-8")
            self.log(f"[WRITE] Updated IDs in {rel_path}")


if __name__ == "__main__":
    sync = AnkiSync()
    sync.run()
