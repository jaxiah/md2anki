# Anki Card Templates

Use the matching Basic or Cloze templates with [anki-card-style.css](anki-card-style.css) in that Anki note type's Styling section. Updating the templates and Styling applies to existing cards without running md2anki again.

The first paragraph inside `md2anki-front` is the Markdown H4 title. The stylesheet emphasizes that paragraph while leaving front-side context and the answer at their normal size and weight.

Body text uses a compact `1.5` line height for automatic wrapping, while paragraphs have `1em` vertical margins. A blank line in Markdown separates paragraphs; their visual spacing comes from these margins rather than from preserving literal empty lines. A single newline within a paragraph remains an ordinary line break.

## Basic Front Template

```html
<div class="md2anki-front">{{Front}}</div>

<script src="_highlight.min.js"></script>
<script>
(function () {
  if (!window.hljs) return;
  document.querySelectorAll('.md2anki-front pre code').forEach(function (el) {
    if (el.dataset.hljsDone === "1" || el.dataset.highlighted === "yes") return;
    window.hljs.highlightElement(el);
    el.dataset.hljsDone = "1";
  });
})();
</script>
```

## Basic Back Template

```html
{{FrontSide}}

<hr id="answer">

<div class="md2anki-back">{{Back}}</div>

<script src="_highlight.min.js"></script>
<script>
(function () {
  if (!window.hljs) return;
  document.querySelectorAll('.md2anki-front pre code, .md2anki-back pre code').forEach(function (el) {
    if (el.dataset.hljsDone === "1" || el.dataset.highlighted === "yes") return;
    window.hljs.highlightElement(el);
    el.dataset.hljsDone = "1";
  });
})();
</script>
```

## Cloze Front Template

```html
<div class="md2anki-front">{{cloze:Text}}</div>

<script src="_highlight.min.js"></script>
<script>
(function () {
  if (!window.hljs) return;
  document.querySelectorAll('.md2anki-front pre code').forEach(function (el) {
    if (el.dataset.hljsDone === "1" || el.dataset.highlighted === "yes") return;
    window.hljs.highlightElement(el);
    el.dataset.hljsDone = "1";
  });
})();
</script>
```

## Cloze Back Template

```html
<div class="md2anki-front">{{cloze:Text}}</div>

{{#Back Extra}}
<hr id="answer">
<div class="md2anki-back">{{Back Extra}}</div>
{{/Back Extra}}

<script src="_highlight.min.js"></script>
<script>
(function () {
  if (!window.hljs) return;
  document.querySelectorAll('.md2anki-front pre code, .md2anki-back pre code').forEach(function (el) {
    if (el.dataset.hljsDone === "1" || el.dataset.highlighted === "yes") return;
    window.hljs.highlightElement(el);
    el.dataset.hljsDone = "1";
  });
})();
</script>
```

Both Cloze templates use `{{cloze:Text}}`, so Anki hides the active deletion on the front and reveals it on the back. The H4 title is emphasized on both sides. `Back Extra` appears only on the back, at normal body weight; its container and separator are omitted when the field is empty. md2anki includes the Obsidian source link in this field even when the authored note has no extra content.

## How the Templates Work

- Basic's `{{FrontSide}}` repeats the front, including its title container. Cloze renders `{{cloze:Text}}` again to reveal the answer.
- `<hr id="answer">` separates the question from the answer.
- `{{Back}}` (Basic) or `{{Back Extra}}` (Cloze) inserts the answer-side content, including the generated Obsidian source link.
- The script highlights code blocks after the field content has been inserted. The front script highlights front-side code during recall; the back script also highlights answer-side code. Already-highlighted blocks are skipped.

Keep your existing `_highlight.min.js` file in Anki's `collection.media`, and sync media to other devices. The library must provide `hljs.highlightElement`, as in the previous template. If it is unavailable, code remains readable without syntax colors.

These templates omit `_github.min.css`: `anki-card-style.css` already defines highlight.js token colors for both light and dark themes. No additional highlight.js stylesheet is needed.

Install each pair in its matching note type. Cloze uses the built-in `Text` and `Back Extra` fields; do not substitute `{{FrontSide}}` for its back-side `{{cloze:Text}}` replacement. See the [Anki manual's Cloze template documentation](https://docs.ankiweb.net/templates/generation.html#cloze-templates) for the cloze filter and card generation rules.
