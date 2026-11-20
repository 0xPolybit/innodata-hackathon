"""Design-contract tests for the redesigned results page."""

from __future__ import annotations

import json
import re

import pytest

from taskfactory.web import forms
from taskfactory.web.generate import CheckOutcome, GenerationResult, TaskSummary
from taskfactory.web.results_page import render_results_page
from taskfactory.web.theme import REPO_URL

CHECK_NAMES = (
    "1_schema",
    "2_layout",
    "3_ambiguity",
    "7_redraw",
    "4_ocr",
    "5_pixels",
    "6_counterfactual",
)


def _checks(*, failed: bool = False) -> tuple[CheckOutcome, ...]:
    """Seven outcomes, the last failed when ``failed`` is true."""
    return tuple(
        CheckOutcome(
            name=name,
            passed=not (failed and name == CHECK_NAMES[-1]),
            reason="pixels differ" if failed and name == CHECK_NAMES[-1] else "",
        )
        for name in CHECK_NAMES
    )


def _result() -> GenerationResult:
    """One accepted and one rejected task, each with an image and a payload."""
    accepted = TaskSummary(
        task_id="bar-tourism-000000-value_lookup",
        family="bar",
        question_type="value_lookup",
        domain="tourism",
        checks=_checks(),
    )
    rejected = TaskSummary(
        task_id="bar-tourism-000000-rank_k",
        family="bar",
        question_type="rank_k",
        domain="tourism",
        checks=_checks(failed=True),
    )
    artifacts: dict[str, bytes] = {}
    for task, folder in ((accepted, "tasks"), (rejected, "rejected")):
        artifacts[f"{folder}/{task.task_id}/image.png"] = b"png"
        artifacts[f"{folder}/{task.task_id}/task.json"] = json.dumps(
            {"question": "Which bar is tallest?", "answer": "North"}
        ).encode("utf-8")
    return GenerationResult(
        run_id="ui-1234abcd",
        commit="abcdef1" + "0" * 33,
        seed=20261206,
        attempted=2,
        accepted=1,
        rejected=1,
        yield_=0.5,
        elapsed_seconds=1.25,
        accepted_tasks=(accepted,),
        rejected_tasks=(rejected,),
        artifacts=artifacts,
    )


@pytest.fixture(scope="module")
def page() -> str:
    """A rendered results page for the fake run."""
    form = forms.parse_form(forms.default_form_payload())
    return render_results_page(_result(), form)


def test_page_has_exactly_one_h1(page: str) -> None:
    assert page.count("<h1") == 1
    assert page.count("</h1>") == 1
    assert "<h1>Results</h1>" in page


def test_every_image_has_alt_text_from_the_question(page: str) -> None:
    images = re.findall(r"<img\b[^>]*>", page)
    assert len(images) == 2
    for tag in images:
        alt = re.search(r'alt="([^"]*)"', tag)
        assert alt is not None, tag
        assert alt.group(1).strip(), tag
    assert 'alt="Which bar is tallest?"' in page


def test_download_zip_form_posts_the_hidden_fields(page: str) -> None:
    assert '<form method="post" action="/api/zip">' in page
    assert 'name="seed" value="20261206"' in page
    assert "Download ZIP" in page


def test_page_has_no_script_tag(page: str) -> None:
    assert "<script" not in page.lower()


def test_no_external_urls_except_the_github_link(page: str) -> None:
    assert "http://" not in page
    # page_shell links the same repo from the header nav and the footer.
    assert page.count("https://") == page.count(REPO_URL)
    footer = page.split('<footer class="footer">', 1)[1]
    assert REPO_URL in footer
