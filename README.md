# md2anki

Turn Obsidian-style Markdown into Anki cards, without leaving your vault.

`md2anki` treats each `####` heading as a flashcard, renders the card body to HTML, uploads local images through AnkiConnect, and adds an "open in Obsidian" link back to the exact source block. Later runs only add, update, delete, or skip what changed.

<table>
<tr>
<th width="50%">Obsidian source</th>
<th width="50%">Anki HTML</th>
</tr>
<tr>
<td width="50%" valign="top">

<pre><code>---
ankideck: Engineering::Pumps
---

#### What does a pump volute do?

![[pump.png|900]]

---

The volute is the spiral casing
around the impeller.

It collects high-velocity flow
from the impeller and helps
convert velocity into pressure.
</code></pre>

</td>
<td width="50%" valign="top">

<div>
  <p><strong>Front</strong></p>
  <p>What does a pump volute do?</p>
  <img src="pump.png" alt="Centrifugal pump diagram" width="900">
  <hr>
  <p><strong>Back</strong></p>
  <p>The volute is the spiral casing around the impeller. It collects high-velocity flow from the impeller and helps convert velocity into pressure.</p>
  <p><a href="#">open in Obsidian</a></p>
</div>

</td>
</tr>
</table>

## Why Use It

- **Vault-native cards:** write normal Markdown; `####` headings become Anki notes.
- **Safe sync loop:** dry-run by default; apply mode writes only when requested.
- **One-click source return:** every Anki card includes an `open in Obsidian` footer that jumps back to the exact Markdown block.
- **Stable anchors:** new cards get `^anki-<id>` written back to Markdown, so future syncs and source links stay attached to the right card.
- **Rich rendering:** supports Markdown, tables, code blocks, math, wiki links, and `![[image.png|width]]` embeds.
- **Incremental sync:** repeat runs skip unchanged cards and update only the notes that changed.

## Install

Requirements:

- Python `>=3.10`
- Anki desktop
- AnkiConnect enabled at `http://127.0.0.1:8765`

```bash
pip install -e .
pip install -e .[test]
```

## Run

Preview first. This does not write to Anki, state, or Markdown:

```bash
md2anki --vault-root D:/Notes/MyVault
```

Apply changes:

```bash
md2anki --vault-root D:/Notes/MyVault --apply-anki-changes
```

Process one file:

```bash
md2anki --vault-root D:/Notes/MyVault --file "Biology/cells.md"
```

Windows launcher: copy `md2anki.cmd` into a vault root and double-click it. The launcher uses its own directory as `vault-root` and runs in apply mode.

## Markdown Rules

- A file must have frontmatter `ankideck`.
- Each `####` starts one card.
- Text before the first body `---` is appended to the front; text after it becomes the back.
- `^anki-123` binds a Markdown block to an Anki note.
- `^anki-123 DELETE` deletes the note and writes `^noanki`.
- `^noanki` skips that card.

## Safety

Dry-run is the default command-line behavior. Apply mode writes to Anki and may write metadata such as `^anki-<id>` or `^noanki` back into Markdown.

Back up your vault and Anki before large migrations.

## Development

```bash
pytest -q
pytest tests/e2e/test_mock_ankiconnect_flow.py -q
```

E2E tests use a local mock AnkiConnect server and do not touch a real Anki database.

## References

- Design notes: [doc/design_gold_reference_v0.1.md](doc/design_gold_reference_v0.1.md)
- Release checklist: [doc/release_checklist_v0.1.md](doc/release_checklist_v0.1.md)
