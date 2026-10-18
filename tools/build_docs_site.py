"""Build Netlify docs using the same renderer, shell and assets as the Jetson UI."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from build_docs import build

ROOT = Path(__file__).resolve().parents[1]


def between(source: str, start: str, end: str) -> str:
    """Select shared UI code; fail visibly if its source boundaries change."""
    return start + source.split(start, 1)[1].split(end, 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/docs')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    web = ROOT / 'src/spot_vision/web'
    documentation = build(ROOT / 'docs/operator')
    app = (web / 'app.js').read_text()
    # Reuse the deployed renderer verbatim so search, grouping, outline and
    # previous/next links stay identical when the Jetson UI changes.
    javascript = between(app, '"use strict";', 'const fmt =')
    javascript += '\nlet docs = null, viewer = null, pageUpdate = () => {};\n'
    javascript += between(app, 'function currentRoute()', 'async function mutation(')
    javascript += between(app, 'function theme()', 'function feed(')
    javascript += between(app, 'async function docsPage(id)', 'function render()')
    javascript += '''
function renderDocs() {
  if (currentRoute().page !== "docs") {
    location.replace("#docs/connect");
    return;
  }
  docsPage(currentRoute().id).catch(error => {
    $("#page").textContent = "Documentation unavailable: " + error.message;
  });
  scrollTo(0, 0);
}
$("#nav").innerHTML = `<a class="active" href="#docs/connect" title="Docs" aria-label="Docs">${icon("docs")}<span class="nav-label">Docs</span></a>`;
theme();
addEventListener("hashchange", renderDocs);
renderDocs();
'''
    page = (web / 'index.html').read_text()
    page = page.replace('<title>Spot</title>', '<title>Spot documentation</title>')
    page = page.replace('    <script defer src="/ui-state.js"></script>\n', '')
    page = page.replace('src="/app.js"', 'src="/docs-site.js"')
    page = page.replace('href="#overview"', 'href="#docs/connect"')
    page = page.replace('        <div id="updated">Time unavailable</div>\n', '')
    page = page.replace('        <small id="release-id">Release unavailable</small>\n', '')
    (args.output / 'index.html').write_text(page)
    (args.output / 'docs-site.js').write_text(javascript)
    (args.output / 'docs.json').write_text(json.dumps(documentation, ensure_ascii=False))
    for name in ('app.css', 'theme.js', 'blazing-bulldogs.svg',
                 'source-sans-pro.woff2', 'source-sans-pro-semibold.woff2', 'FONT-LICENSE.md'):
        shutil.copy2(web / name, args.output / name)
    shutil.copytree(web / 'docs-images', args.output / 'docs-images', dirs_exist_ok=True)
    archive = args.output.parent / 'spot-docs-netlify.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(args.output.rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(args.output))
    print(f'Built {len(documentation["topics"])} topics in {args.output}; archive: {archive}')


if __name__ == '__main__':
    main()
