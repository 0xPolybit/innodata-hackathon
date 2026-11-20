"""Tests for the static sample site: the landing page, the copied report and ``vercel.json``.

The site is plain HTML with relative links, so these tests only read files and parse JSON.
Nothing here starts a server or runs the generator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"
LANDING = SITE / "index.html"
SAMPLE = SITE / "sample" / "index.html"
VERCEL = REPO_ROOT / "vercel.json"

REF_PATTERN = re.compile(r"""(?:href|src)\s*=\s*["']([^"']*)["']""")
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data", "javascript"}
ROUTE_LINKS = {"/", "/about", "/sample/"}


def _relative_refs(html: str) -> list[str]:
    """Return the on-site links and asset paths in ``html``, skipping anchors and URLs."""
    refs = []
    for ref in REF_PATTERN.findall(html):
        ref = ref.strip()
        if not ref or ref.startswith(("#", "//")):
            continue
        if urlsplit(ref).scheme.lower() in EXTERNAL_SCHEMES:
            continue
        refs.append(ref.split("#", 1)[0].split("?", 1)[0])
    return refs


def test_landing_page_has_title_and_sample_link() -> None:
    assert LANDING.is_file(), "site/index.html is missing"
    html = LANDING.read_text(encoding="utf-8")
    assert "TaskFactory" in html
    assert any(ref == "/sample/" for ref in _relative_refs(html))


def test_sample_report_exists() -> None:
    assert SAMPLE.is_file(), "site/sample/index.html is missing"


def test_landing_page_links_use_routes_and_existing_files() -> None:
    html = LANDING.read_text(encoding="utf-8")
    refs = _relative_refs(html)
    route_links = {ref for ref in refs if ref.startswith("/")}
    file_links = {ref for ref in refs if not ref.startswith("/")}

    assert route_links == ROUTE_LINKS, (
        f"site/index.html must use only these routes: {sorted(ROUTE_LINKS)}; "
        f"found: {sorted(route_links)}"
    )
    html_links = sorted(ref for ref in refs if ref.endswith(".html"))
    assert not html_links, f"site/index.html must link to routes, not .html files: {html_links}"
    missing = sorted(ref for ref in file_links if not (SITE / ref).is_file())
    assert not missing, f"site/index.html points at missing files: {missing}"


def test_sample_report_relative_links_resolve() -> None:
    html = SAMPLE.read_text(encoding="utf-8")
    missing = sorted({ref for ref in _relative_refs(html) if not (SAMPLE.parent / ref).is_file()})
    assert not missing, f"site/sample/index.html points at missing files: {missing}"


def test_vercel_config_uses_container() -> None:
    assert VERCEL.is_file(), "vercel.json is missing"
    config = json.loads(VERCEL.read_text(encoding="utf-8"))
    assert config["framework"] == "container"
    assert "outputDirectory" not in config
