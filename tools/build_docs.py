"""Compile the maintained Markdown operator guide for both offline and hosted docs.

Supported additions: tables, quoted callouts, <details>/<summary>, captioned
screenshots, and simple left-to-right Mermaid chains. Chains become inline SVG
at build time so diagrams work on a disconnected Jetson without JS dependencies.
Unsupported Mermaid syntax fails the build instead of displaying a broken chart.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path


def inline(text: str) -> str:
    # Protect code spans from further Markdown interpretation.
    fragments = re.split(r"(`[^`]+`)", text)
    for index, fragment in enumerate(fragments):
        if fragment.startswith("`") and fragment.endswith("`"):
            fragments[index] = "<code>" + html.escape(fragment[1:-1]) + "</code>"
        else:
            escaped = html.escape(fragment)
            escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
            fragments[index] = re.sub(
                r"\[([^\]]+)\]\((#[A-Za-z0-9_/-]+|https?://[^ )]+)\)",
                r'<a href="\2">\1</a>', escaped,
            )
    return "".join(fragments)


def heading_id(topic_id: str, text: str) -> str:
    return topic_id + "-" + re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def flowchart(lines: list[str], identity: str) -> str:
    """Render only the documented Mermaid subset: labelled nodes in one LR chain."""
    statements = [line.strip() for line in lines if line.strip()]
    if not statements or statements.pop(0) != "flowchart LR":
        raise ValueError("Docs diagrams require a simple flowchart LR chain")
    nodes = []
    edge = re.compile(r"(\w+)(?:\[([^\[\]]+)\])? --> (\w+)\[([^\[\]]+)\]")
    for statement in statements:
        match = edge.fullmatch(statement)
        if not match:
            raise ValueError(f"Unsupported docs Mermaid edge: {statement}")
        source, label, target, target_label = match.groups()
        if not nodes:
            if not label:
                raise ValueError("First diagram node needs a label")
            nodes.append((source, label))
        if source != nodes[-1][0] or (label and label != nodes[-1][1]):
            raise ValueError("Docs diagrams support a single connected chain")
        if target in {node[0] for node in nodes}:
            raise ValueError("Docs diagram chains cannot contain cycles")
        nodes.append((target, target_label))
    if len(nodes) < 2:
        raise ValueError("Docs diagrams need at least two nodes")
    box = max(110, max(len(label) for _, label in nodes) * 7 + 28)
    gap, height = 32, 74
    width = len(nodes) * box + (len(nodes) - 1) * gap + 4
    description = " → ".join(label for _, label in nodes)
    marker = identity + "-arrow"
    pieces = [
        f'<div class="docs-diagram"><svg viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{html.escape(description, quote=True)}" '
        'xmlns="http://www.w3.org/2000/svg">',
        f'<defs><marker id="{marker}" markerWidth="7" markerHeight="7" '
        'refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7Z" '
        'fill="currentColor"/></marker></defs>',
    ]
    for index, (_, label) in enumerate(nodes):
        x = 2 + index * (box + gap)
        pieces.append(f'<rect x="{x}" y="10" width="{box}" height="52" rx="8"/>')
        pieces.append(f'<text x="{x + box / 2}" y="41" text-anchor="middle">'
                      f'{html.escape(label)}</text>')
        if index < len(nodes) - 1:
            pieces.append(f'<path d="M{x + box} 36h{gap - 4}" '
                          f'marker-end="url(#{marker})"/>')
    return "".join(pieces) + "</svg></div>"


def render(markdown: str, topic_id: str, example: str) -> tuple[str, list]:
    output, headings, paragraph = [], [], []
    listing, code, language, table = None, None, "", []
    details_open = False
    diagram_count = 0

    def flush():
        if paragraph:
            output.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal listing
        if listing:
            output.append(f"</{listing}>")
            listing = None

    def close_table():
        if not table:
            return
        rows = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in table]
        if len(rows) < 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
            raise ValueError(f"Invalid table in {topic_id}")
        if any(len(row) != len(rows[0]) for row in rows):
            raise ValueError(f"Inconsistent table columns in {topic_id}")
        output.append('<div class="docs-table" tabindex="0" role="region" aria-label="Reference table"><table><thead><tr>')
        output.append("".join(f'<th scope="col">{inline(cell)}</th>' for cell in rows[0]))
        output.append("</tr></thead><tbody>")
        for row in rows[2:]:
            output.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
        output.append("</tbody></table></div>")
        table.clear()

    for line in markdown.splitlines():
        if line.startswith("```"):
            flush()
            close_list()
            close_table()
            if code is not None:
                if language == "mermaid":
                    diagram_count += 1
                    output.append(flowchart(code, f"{topic_id}-{diagram_count}"))
                else:
                    label = "java" if language == "java-example" else language
                    output.append('<div class="docs-code">'
                                  f'<span class="docs-code-language">{html.escape(label)}</span>'
                                  '<pre><code>' + html.escape("\n".join(code)) + '</code></pre></div>')
                code = None
            else:
                language = line[3:].strip()
                code = example.splitlines() if language == "java-example" else []
            continue
        if code is not None:
            code.append(line)
            continue
        if line.startswith("|"):
            flush()
            close_list()
            table.append(line)
            continue
        close_table()
        if line == "<details>" or line == "</details>" or line.startswith("<summary>"):
            flush()
            close_list()
            if line == "<details>" and not details_open:
                output.append('<details class="docs-details">')
                details_open = True
            elif line == "</details>" and details_open:
                output.append("</details>")
                details_open = False
            elif re.fullmatch(r"<summary>.+</summary>", line) and details_open:
                summary = line[9:-10]
                output.append(f'<summary id="{heading_id(topic_id, summary)}">' + inline(summary) + "</summary>")
            else:
                raise ValueError(f"Invalid details markup in {topic_id}")
            continue
        image_match = re.fullmatch(
            r"!\[([^\]]*)\]\(../../src/spot_vision/web/docs-images/([A-Za-z0-9_.-]+\.png)\)", line
        )
        if image_match:
            flush()
            close_list()
            alt, filename = image_match.groups()
            output.append(
                '<figure class="docs-figure">'
                f'<button type="button" class="docs-image-button" data-screenshot="/docs-images/{filename}" '
                f'aria-label="Enlarge: {html.escape(alt, quote=True)}">'
                f'<img class="docs-screenshot" src="/docs-images/{filename}" '
                f'alt="{html.escape(alt, quote=True)}" loading="lazy">'
                '<span class="docs-image-hint">Click to enlarge ↗</span></button></figure>'
            )
            continue
        caption = re.fullmatch(r"\*([^*]+)\*", line)
        if caption and output and output[-1].endswith("</figure>"):
            output[-1] = output[-1][:-9] + "<figcaption>" + inline(caption[1]) + "</figcaption></figure>"
            continue
        if line.startswith("> "):
            flush()
            close_list()
            output.append('<aside class="docs-callout">' + inline(line[2:]) + '</aside>')
            continue
        match = re.match(r"^(#{1,3}) (.+)", line)
        if match:
            flush()
            close_list()
            level = len(match[1])
            text = match[2]
            identity = heading_id(topic_id, text)
            output.append(f'<h{level + 1} id="{identity}">{inline(text)}</h{level + 1}>')
            if level > 1:
                headings.append({"id": identity, "text": text})
        elif re.match(r"^\d+\. ", line) or line.startswith("- "):
            flush()
            kind = "ol" if line[0].isdigit() else "ul"
            if listing != kind:
                close_list()
                listing = kind
                start = re.match(r"^(\d+)\. ", line)
                attribute = f' start="{int(start[1])}"' if start else ""
                output.append(f"<{kind}{attribute}>")
            output.append("<li>" + inline(re.sub(r"^(\d+\. |- )", "", line)) + "</li>")
        elif not line.strip():
            flush()
            close_list()
        else:
            close_list()
            paragraph.append(line)
    flush()
    close_list()
    close_table()
    if code is not None or details_open:
        raise ValueError(f"Unclosed code/details block in {topic_id}")
    return "\n".join(output), headings


class PlainText(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.parts = []
        self.feed(source)

    def handle_data(self, data):
        self.parts.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


def build(source: Path) -> dict:
    topics = []
    example = (source / "java-example.java").read_text()
    for path in sorted(source.glob("*.md")):
        lines = path.read_text().splitlines()
        topic_id = path.stem.split("-", 1)[1]
        body = "\n".join(lines[3:])
        content, headings = render(body, topic_id, example)
        # Index rendered sections so search snippets omit Markdown syntax and
        # include advanced details even when their disclosure is closed.
        sections = []
        chunks = re.split(r'<(?:h[234]|summary) id="([^"]+)">(.+?)</(?:h[234]|summary)>', content)
        for index in range(1, len(chunks), 3):
            sections.append({"id": chunks[index], "title": PlainText(chunks[index + 1]).text,
                             "text": PlainText(chunks[index + 2]).text})
        topics.append({
            "id": topic_id,
            "title": lines[0].removeprefix("Title: "),
            "group": lines[1].removeprefix("Group: "),
            "html": content,
            "headings": headings,
            "text": body,
            "sections": sections,
        })
    return {"schema_version": 1, "topics": topics}


def build_web_bundle(source: Path, web: Path, output: Path) -> None:
    """Stage docs with the matching UI, styles, fonts and screenshots."""
    web, output = web.resolve(), output.resolve()
    if output.is_relative_to(web) or web.is_relative_to(output):
        raise ValueError("Web bundle output must be separate from source assets")
    document = build(source)
    for topic in document["topics"]:
        for filename in re.findall(r'<img[^>]+src="/([^"]+)"', topic["html"]):
            asset = (web / filename).resolve()
            if not asset.is_relative_to(web) or not asset.is_file():
                raise ValueError(f"Missing docs image in {topic['id']}: {filename}")
    shutil.copytree(web, output, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("docs.json", ".DS_Store", "._*", "__pycache__"))
    (output / "docs.json").write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    # Source screenshots may be owner-only on the development Mac. The Jetson
    # serves these files as an unprivileged service account.
    for path in output.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--web-assets", type=Path,
                        help="Stage the complete web bundle beside the output docs.json")
    args = parser.parse_args()
    if args.web_assets:
        if args.output.name != "docs.json":
            parser.error("--web-assets requires an output named docs.json")
        build_web_bundle(args.source, args.web_assets, args.output.parent)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(build(args.source), ensure_ascii=False, separators=(",", ":")) + "\n")
