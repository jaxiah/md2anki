"""Read-only comparison of Markdown images, Anki fields, and media files."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests
from markdown_it import MarkdownIt

from .html_renderer import HtmlRenderer, HtmlRenderError, RE_WIKI_IMAGE
from .markdown_processor import MarkdownProcessor


class _Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def html_images(text: str) -> list[str]:
    parser = _Images()
    parser.feed(text)
    return list(dict.fromkeys(parser.sources))


def markdown_images(text: str) -> list[str]:
    """Exclude code examples while supporting wiki, Markdown, and HTML images."""
    refs = []
    for token in MarkdownIt("commonmark", {"html": True}).parse(text):
        if token.type == "html_block":
            refs.extend(html_images(token.content))
        for child in token.children or []:
            if child.type == "image":
                refs.append(child.attrGet("src"))
            elif child.type == "text":
                refs.extend(match.group(1).strip() for match in RE_WIKI_IMAGE.finditer(child.content))
            elif child.type == "html_inline":
                refs.extend(html_images(child.content))
    return list(dict.fromkeys(refs))


def _local_name(ref: str) -> str | None:
    if urlsplit(ref).scheme or ref.startswith("//"):
        return None
    return unquote(ref)


def audit_media(
    vault_root: Path,
    markdown_files: list[Path],
    anki_media_dir: Path,
    anki_connect_url: str = "http://127.0.0.1:8765",
    asset_root: str = "assets",
) -> dict:
    vault_root = Path(vault_root).absolute()
    anki_media_dir = Path(anki_media_dir).absolute()
    if not anki_media_dir.is_dir():
        raise ValueError(f"Anki media directory does not exist: {anki_media_dir}")
    processor = MarkdownProcessor(vault_root)
    resolver = HtmlRenderer(vault_root.name, vault_root, asset_root)
    notes = []
    warnings = []
    for file in markdown_files:
        path = Path(file)
        doc = processor.parse_file(path if path.is_absolute() else vault_root / path)
        notes.extend(note for note in doc.notes if not note.delete_requested)
        warnings.extend(doc.warnings)

    # Read directory entries, not Path.exists(), so Windows cannot hide case errors.
    names = {path.name for path in anki_media_dir.iterdir() if path.is_file()}
    folded = defaultdict(list)
    for name in sorted(names):
        folded[name.casefold()].append(name)

    info = {}
    ids = list(dict.fromkeys(int(note.anki_note_id) for note in notes if note.anki_note_id))
    with requests.Session() as session:
        for offset in range(0, len(ids), 100):
            response = session.post(anki_connect_url, json={
                "action": "notesInfo", "version": 6, "params": {"notes": ids[offset:offset + 100]},
            }, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if payload.get("error") is not None:
                raise ValueError(f"notesInfo failed: {payload['error']}")
            result = payload.get("result")
            if not isinstance(result, list):
                raise ValueError("notesInfo returned a non-list result")
            info.update({str(item["noteId"]): item for item in result if item.get("noteId")})

    digests = {}

    def digest(path):
        if path not in digests:
            digests[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digests[path]

    def check_media(ref):
        name = _local_name(ref)
        if name is None:
            return {"ref": ref, "status": "external"}
        # A literal percent sequence may itself be part of the filename.
        if ref in names:
            name = ref
        matches = [name] if name in names else folded.get(name.casefold(), [])
        status = "ok" if name in names else "case_mismatch" if len(matches) == 1 else "ambiguous" if matches else "missing"
        row = {"ref": ref, "filename": name, "status": status, "actual_names": matches}
        if len(matches) == 1:
            path = anki_media_dir / matches[0]
            row.update(size=path.stat().st_size, sha256=digest(path))
            if not row["size"]:
                row["status"] = "empty"
        return row

    rows = []
    for note in notes:
        remote = info.get(note.anki_note_id)
        row = {
            "source_file": note.source_file, "line": note.line_idx_h4 + 1,
            "heading": note.h4_heading_pure, "anki_note_id": note.anki_note_id,
            "anki_status": "ok" if remote else "not_synced" if not note.anki_note_id else "note_missing",
            "card_ids": remote.get("cards", []) if remote else [],
            "source_images": [], "anki_images": [], "issues": [],
        }
        if remote:
            for field, value in remote.get("fields", {}).items():
                for ref in html_images(value["value"]):
                    image = {"field": field, **check_media(ref)}
                    row["anki_images"].append(image)
                    if image["status"] not in ("ok", "external"):
                        row["issues"].append(f"anki_media_{image['status']}: {ref}")
        for ref in markdown_images(note.front_md + "\n\n" + note.back_md):
            local = _local_name(ref)
            if local is None:
                row["source_images"].append({"ref": ref, "status": "external"})
                continue
            try:
                path, source_warnings = resolver._resolve_image_path(local, note.source_file)
            except HtmlRenderError as error:
                row["source_images"].append({"ref": ref, "status": "ambiguous", "error": str(error)})
                row["issues"].append(f"source_ambiguous: {ref}")
                continue
            source = {"ref": ref, "status": "ok" if path else "missing", "warnings": source_warnings}
            row["source_images"].append(source)
            if path is None:
                row["issues"].append(f"source_missing: {ref}")
                continue
            source.update(path=str(path), size=path.stat().st_size, sha256=digest(path))
            source["media_by_source_name"] = check_media(path.name)
            linked = [image for image in row["anki_images"]
                      if image.get("filename", "").casefold() == path.name.casefold()]
            source["anki_refs"] = [image["ref"] for image in linked]
            if remote and not linked:
                row["issues"].append(f"source_not_referenced_in_anki: {ref}")
            for image in linked:
                if image.get("sha256") and image["sha256"] != source["sha256"]:
                    row["issues"].append(f"content_mismatch: {ref} -> {image['ref']}")
        if row["anki_status"] != "ok":
            row["issues"].append(row["anki_status"])
        rows.append(row)
    counts = Counter(issue.split(":", 1)[0] for row in rows for issue in row["issues"])
    return {
        "vault_root": str(vault_root), "anki_media_dir": str(anki_media_dir),
        "summary": {"notes": len(rows), "source_image_refs": sum(len(row["source_images"]) for row in rows),
                    "anki_image_refs": sum(len(row["anki_images"]) for row in rows),
                    "notes_with_issues": sum(bool(row["issues"]) for row in rows), "issues": dict(counts)},
        "warnings": warnings, "notes": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--file", required=True, action="append", type=Path)
    parser.add_argument("--anki-media-dir", required=True, type=Path)
    parser.add_argument("--anki-connect-url", default="http://127.0.0.1:8765")
    parser.add_argument("--asset-root", default="assets")
    parser.add_argument("--report", type=Path, help="Write a detailed UTF-8 JSON report")
    args = parser.parse_args(argv)
    try:
        report = audit_media(args.vault_root, args.file, args.anki_media_dir, args.anki_connect_url, args.asset_root)
    except (OSError, ValueError, requests.RequestException) as error:
        parser.exit(2, f"Audit failed: {error}\n")
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True))
    for row in report["notes"]:
        if row["issues"]:
            print(json.dumps({key: row[key] for key in ("source_file", "line", "heading", "anki_note_id", "issues")}, ensure_ascii=True))
    return 1 if report["summary"]["notes_with_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
