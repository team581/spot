"""Compile the one maintained offline Markdown documentation source."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


def inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(
        r"\[([^\]]+)\]\((#[A-Za-z0-9_/-]+|https?://[^ )]+)\)", r'<a href="\2">\1</a>', escaped
    )


def render(markdown: str, topic_id: str, example: str) -> tuple[str, list]:
    output, headings, paragraph, listing, code = [], [], [], None, None

    def flush():
        if paragraph:
            output.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal listing
        if listing:
            output.append(f"</{listing}>")
            listing = None

    for line in markdown.splitlines():
        if line.startswith("```"):
            flush()
            close_list()
            if code is not None:
                output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code = None
            elif line == "```java-example":
                code = example.splitlines()
            else:
                code = []
            continue
        if code is not None:
            code.append(line)
            continue
        match = re.match(r"^(#{1,3}) (.+)", line)
        if match:
            flush()
            close_list()
            level = len(match[1])
            text = match[2]
            identity = topic_id + "-" + re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            output.append(f'<h{level + 1} id="{identity}">{inline(text)}</h{level + 1}>')
            if level > 1:
                headings.append({"id": identity, "text": text})
        elif re.match(r"^\d+\. ", line) or line.startswith("- "):
            flush()
            kind = "ol" if line[0].isdigit() else "ul"
            if listing != kind:
                close_list()
                listing = kind
                output.append(f"<{kind}>")
            output.append("<li>" + inline(re.sub(r"^(\d+\. |- )", "", line)) + "</li>")
        elif not line.strip():
            flush()
            close_list()
        else:
            close_list()
            paragraph.append(line)
    flush()
    close_list()
    return "\n".join(output), headings


def build(source: Path) -> dict:
    topics = []
    example = (source / "java-example.java").read_text()
    for path in sorted(source.glob("*.md")):
        raw = path.read_text()
        lines = raw.splitlines()
        topic_id = path.stem.split("-", 1)[1]
        body = "\n".join(lines[3:])
        content, headings = render(body, topic_id, example)
        topics.append(
            {
                "id": topic_id,
                "title": lines[0].removeprefix("Title: "),
                "group": lines[1].removeprefix("Group: "),
                "html": content,
                "headings": headings,
                "text": body,
            }
        )
    return {"schema_version": 1, "topics": topics}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build(args.source), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
