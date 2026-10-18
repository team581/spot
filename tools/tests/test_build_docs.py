"""Regression checks for the shared offline/hosted documentation compiler."""

import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_docs import build, render

ROOT = Path(__file__).resolve().parents[2]


class Structure(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.stack = []
        self.ids = []
        self.links = []
        self.images = []
        self.feed(source)
        assert not self.stack, self.stack

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link'}:
            self.stack.append(tag)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs['href'])
        if tag == 'img':
            assert attrs.get('alt')
            self.images.append(attrs['src'])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, (tag, self.stack)


class DocsBuildTests(unittest.TestCase):
    def test_all_pages_have_valid_structure_assets_and_links(self):
        topics = build(ROOT / 'docs/operator')['topics']
        self.assertEqual(len(topics), 13)
        by_id = {t['id']: t for t in topics}
        for topic in topics:
            with self.subTest(topic=topic['id']):
                parsed = Structure(topic['html'])
                self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
                self.assertTrue(topic['sections'])
                self.assertTrue(all(h['id'] in parsed.ids for h in topic['headings']))
                for src in parsed.images:
                    self.assertTrue((ROOT / 'src/spot_vision/web' / src.lstrip('/')).is_file())
                for href in parsed.links:
                    if href.startswith('#docs/'):
                        self.assertIn(href.split('/')[1], by_id)
                self.assertNotIn('```', topic['html'])
                self.assertNotIn('<p>|', topic['html'])

    def test_tables_callouts_disclosures_and_code_are_rendered_and_escaped(self):
        source = '''# Guide

> **Before editing:** disable the robot.

| Setting | Value |
| --- | --- |
| `gain` | <unsafe> |

<details>
<summary>Advanced</summary>

```java-example
```

</details>
'''
        output, _ = render(source, 'test', 'if (x < 2) {}')
        Structure(output)
        self.assertIn('<th scope="col">Setting</th>', output)
        self.assertIn('&lt;unsafe&gt;', output)
        self.assertIn('docs-callout', output)
        self.assertIn('<summary id="test-advanced">Advanced</summary>', output)
        self.assertIn('if (x &lt; 2) {}', output)
        self.assertNotIn('<unsafe>', output)

    def test_screenshot_caption_and_numbered_list_continuation(self):
        source = '''1. Open the page.

![Camera](../../src/spot_vision/web/docs-images/camera.png)

*Check the preview.*

2. Confirm the feed.
'''
        output, _ = render(source, 'test', '')
        Structure(output)
        self.assertIn('<figcaption>Check the preview.</figcaption>', output)
        self.assertIn('<ol start="2">', output)
        self.assertIn('data-screenshot="/docs-images/camera.png"', output)

    def test_mermaid_is_accessible_offline_svg_and_rejects_unsupported_syntax(self):
        source = '```mermaid\nflowchart LR\n A[Fit] --> B[Validate]\n B --> C[Apply]\n```'
        output, _ = render(source, 'test', '')
        Structure(output)
        self.assertIn('aria-label="Fit → Validate → Apply"', output)
        self.assertIn('<svg', output)
        self.assertNotIn('<script', output)
        with self.assertRaises(ValueError):
            render('```mermaid\nflowchart TD\n A --> B\n```', 'test', '')

    def test_search_indexes_collapsed_advanced_details_without_markdown(self):
        topics = build(ROOT / 'docs/operator')['topics']
        reference = next(t for t in topics if t['id'] == 'camera-configuration')
        section = next(s for s in reference['sections'] if 'v4l2-ctl' in s['text'])
        self.assertEqual(section['title'], 'Read raw device capabilities on the Jetson')
        self.assertNotIn('```', section['text'])
        self.assertNotRegex(section['text'], r'</?(?:details|summary)>')
        self.assertTrue(section['id'].startswith('camera-configuration-'))

    def test_unclosed_blocks_fail_the_build(self):
        for source in ['```java\nx', '<details>\n<summary>Missing end</summary>']:
            with self.assertRaises(ValueError):
                render(source, 'test', '')


if __name__ == '__main__':
    unittest.main()
