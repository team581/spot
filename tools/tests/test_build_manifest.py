"""Release identity covers the generated documentation actually shipped in the wheel."""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_manifest import generate

ROOT = Path(__file__).resolve().parents[2]


def test_generated_docs_changes_alter_release_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1792454400")
    native = tmp_path / "native.so"
    native.write_bytes(b"native module")
    web = tmp_path / "web"
    article = web / "docs/operator/calibrate/index.html"
    article.parent.mkdir(parents=True)
    article.write_bytes(b"original documentation")
    search = web / "docs/pagefind/pagefind.wasm"
    search.parent.mkdir()
    search.write_bytes(b"search index")

    original = generate(ROOT, native, False, web)
    key = "web/docs/operator/calibrate/index.html"
    assert original["artifact_hashes"][key] == hashlib.sha256(article.read_bytes()).hexdigest()
    assert (
        original["artifact_hashes"]["web/docs/pagefind/pagefind.wasm"]
        == hashlib.sha256(search.read_bytes()).hexdigest()
    )

    article.write_bytes(b"updated documentation")
    updated = generate(ROOT, native, False, web)
    assert updated["source_tree_sha256"] == original["source_tree_sha256"]
    assert updated["native_sha256"] == original["native_sha256"]
    assert updated["release_id"] != original["release_id"]
