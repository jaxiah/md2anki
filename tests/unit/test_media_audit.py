import pytest

from md2anki.media_audit import html_images, markdown_images


def test_markdown_image_extraction_excludes_code_examples():
    text = '''![[Pasted image.png|800]]
![plot](plot%20one.png)
<img src="a&amp;b.png">
`![[inline-example.png]]`

```mermaid
![[fenced-example.png]]
```

    ![[indented-example.png]]
'''
    assert markdown_images(text) == ["Pasted image.png", "plot%20one.png", "a&b.png"]


@pytest.mark.parametrize("text", [
    '<img src="a&amp;b.png"><img src="a&amp;b.png">',
    "<IMG SRC='a&amp;b.png' />",
])
def test_html_image_extraction_decodes_entities_and_deduplicates(text):
    assert html_images(text) == ["a&b.png"]
