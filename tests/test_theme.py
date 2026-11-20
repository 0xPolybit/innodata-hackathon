"""Tests for the shared theme: the page shell, the nav and the inline icons."""

from __future__ import annotations

from taskfactory.web.theme import ICONS, STYLESHEET, page_shell

REPO_URL = "https://github.com/0xPolybit/innodata-hackathon"
NAV_HREFS = ("/", "/sample/", "/about", REPO_URL)
EXPECTED_ICONS = {
    "beaker",
    "sliders-horizontal",
    "database",
    "list-checks",
    "gauge",
    "image",
    "play",
    "file-text",
    "github",
    "info",
    "alert-triangle",
    "check-circle",
    "x-circle",
    "arrow-left",
}


def test_page_shell_has_the_document_structure() -> None:
    page = page_shell("About", "<p>Hello</p>", active="about")

    assert page.startswith("<!doctype html>")
    assert '<html lang="en">' in page
    assert '<meta charset="utf-8">' in page
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page
    assert "<title>About \u00b7 TaskFactory</title>" in page
    assert "<p>Hello</p>" in page
    assert '<div class="container footer-inner">' in page


def test_page_shell_nav_has_the_four_links_and_one_current_link() -> None:
    page = page_shell("About", "", active="about")

    for href in NAV_HREFS:
        assert f'href="{href}"' in page
    for label in ("Generate", "Sample report", "About", "GitHub"):
        assert label in page
    assert page.count(' aria-current="page"') == 1
    assert 'href="/about" aria-current="page"' in page


def test_page_shell_marks_no_link_current_by_default() -> None:
    page = page_shell("TaskFactory", "<p>Body</p>")

    assert ' aria-current="page"' not in page
    assert "<title>TaskFactory</title>" in page


def test_page_shell_has_no_script_tag() -> None:
    page = page_shell("TaskFactory", "<p>Body</p>", active="generate")

    assert "<script" not in page.lower()


def test_stylesheet_has_tokens_components_and_reduced_motion() -> None:
    for token in (
        "background",
        "foreground",
        "card",
        "card-foreground",
        "primary",
        "primary-foreground",
        "secondary",
        "muted",
        "muted-foreground",
        "accent",
        "destructive",
        "success",
        "warning",
        "border",
        "input",
        "ring",
        "radius",
    ):
        assert f"--{token}:" in STYLESHEET

    for component in (
        "container",
        "site-header",
        "brand",
        "nav",
        "btn",
        "btn-primary",
        "btn-outline",
        "btn-ghost",
        "btn-lg",
        "card",
        "card-header",
        "card-title",
        "card-description",
        "card-content",
        "card-footer",
        "field",
        "label",
        "input",
        "select",
        "hint",
        "checkbox-group",
        "checkbox",
        "badge",
        "badge-success",
        "badge-destructive",
        "badge-muted",
        "alert",
        "alert-destructive",
        "alert-warning",
        "alert-info",
        "separator",
        "stat",
        "footer",
        "hero",
    ):
        assert f".{component}" in STYLESHEET

    assert "@media (prefers-reduced-motion: no-preference)" in STYLESHEET
    assert "@media (prefers-color-scheme: dark)" in STYLESHEET
    assert STYLESHEET.count("\n") < 350


def test_every_icon_is_a_valid_inline_svg() -> None:
    assert EXPECTED_ICONS <= set(ICONS)
    for name, icon in ICONS.items():
        assert icon.startswith("<svg "), name
        assert 'viewBox="0 0 24 24"' in icon, name
        assert 'stroke="currentColor"' in icon, name
        assert 'stroke-width="2"' in icon, name
        assert 'stroke-linecap="round"' in icon, name
        assert 'stroke-linejoin="round"' in icon, name
        assert 'fill="none"' in icon, name
        assert 'class="icon"' in icon, name
        assert icon.endswith("</svg>"), name
