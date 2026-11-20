"""Validator self-test: the checks must catch known defects.

:func:`run_selftest` takes packages from a run. A package is clean when every check
of its family passes on it. For each defect class, a clean package is copied into the
work folder, the defect is injected into the copy, and the full check list of the
family runs on the copy. The defect is caught when at least one check fails or
raises. The original folders are only read.

The check lists are the ones :func:`taskfactory.pipeline._run_checks` runs:

- bar: checks 1, 2, 3 and 7 (:func:`run_layout_checks`), then 4, 5 and 6;
- line: checks 1 and 2, then 3, 4, 5, 6 and 7 in their line form.

With ``content_only`` the redraw checks, ``7_redraw`` and ``7_line_redraw``, are left out
of every list. A pass then means the content checks alone agree with the package, and
:func:`run_selftest` reports those catches as ``content_only_per_class``.

Defect classes. Each edits the copy in place and returns a one-line description:

- ``wrong_answer``: task.json names a different category or value as its answer.
- ``hidden_label``: a white box covers the text the answer depends on in image.png: the
  value label for a value lookup, the category name for an extremum, a rank_k or a
  pair_compare, and the legend name for a series_at_x.
- ``forced_tie``: the second-largest bar becomes as large as the largest, and the
  picture is drawn again from the edited spec.
- ``mismatched_bar``: the shortest bar is painted white, so the bar count no longer
  matches the category count.
- ``absent_entity``: the question names a category that the spec does not have.

:data:`APPLIES_TO` lists the (family, task type) pairs each class applies to. A class
that does not apply to a package's task type is skipped and not counted. A class is
also skipped, and not counted, when the defect cannot be drawn into that package, for
example when the answer has no printed box (:class:`NotApplicable`).

Only packages that pass every check unmodified are injected into. A catch is never
credited to a package that was already failing.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import cv2
import numpy as np
from PIL import Image

from taskfactory.checks_counterfactual import check_6_counterfactual
from taskfactory.checks_layout import (
    check_1_schema,
    check_2_layout,
    pair_names_from_question,
    run_layout_checks,
)
from taskfactory.checks_line import (
    CHECK_3,
    CHECK_5,
    CHECK_6,
    CHECK_7,
    check_3_line_ambiguity,
    check_5_line_pixels,
    check_6_line_counterfactual,
    check_7_line_redraw,
)
from taskfactory.checks_ocr import check_4_ocr
from taskfactory.checks_pixels import (
    BAR_RGB,
    COLOR_TOLERANCE,
    MIN_AREA_PX,
    MIN_SIDE_PX,
    check_5_pixels,
)
from taskfactory.render import render_bar

__all__ = [
    "APPLIES_TO",
    "DEFECTS",
    "DEFECT_CLASSES",
    "NotApplicable",
    "absent_entity",
    "check_package",
    "forced_tie",
    "hidden_label",
    "mismatched_bar",
    "run_selftest",
    "wrong_answer",
]

DEFECT_CLASSES = ("wrong_answer", "hidden_label", "forced_tie", "mismatched_bar", "absent_entity")

# The run defaults for the two thresholds the checks take (see pipeline.py).
MIN_MARGIN = 0.05
MIN_FONT_PX = 9

PAINT_MARGIN_PX = 2  # the white box covers the text box plus this much on every side
WHITE = (255, 255, 255)
ABSENT_NAME = "Atlantis"  # a category name that no spec uses

_BAR_TASK_TYPES = ("value_lookup", "extremum", "rank_k", "pair_compare")
_BAR_PAIRS = frozenset(("bar", task_type) for task_type in _BAR_TASK_TYPES)
_ALL_PAIRS = _BAR_PAIRS | {("line", "series_at_x")}

# The text box hidden_label covers for each (family, task type): the printed text a correct
# answer depends on. A value lookup is answered by its category's value label, an extremum,
# a rank_k and a pair_compare by a category name, and a series_at_x by a legend name.
_ANSWER_ROLE: dict[tuple[str, str], str] = {
    ("bar", "value_lookup"): "value",
    ("bar", "extremum"): "category",
    ("bar", "rank_k"): "category",
    ("bar", "pair_compare"): "category",
    ("line", "series_at_x"): "legend",
}

# The (family, task type) pairs each defect class applies to. Any other pair is skipped.
APPLIES_TO: dict[str, frozenset[tuple[str, str]]] = {
    # Every task type names an answer, and that answer can be made wrong.
    "wrong_answer": _ALL_PAIRS,
    # Every answer is printed as one text box (see _ANSWER_ROLE), and that box can be covered.
    "hidden_label": frozenset(_ANSWER_ROLE),
    # Every bar question needs distinct bar values, so a tie breaks its ambiguity rule.
    "forced_tie": _BAR_PAIRS,
    # Every bar package draws one bar per category, so a missing bar breaks check 5.
    "mismatched_bar": _BAR_PAIRS,
    # Only the bar questions that name categories can name one the spec lacks.
    "absent_entity": frozenset({("bar", "value_lookup"), ("bar", "pair_compare")}),
}


class NotApplicable(Exception):
    """The defect cannot be drawn into this package. The run skips it and does not count it."""


def check_package(
    package: Path,
    family: str,
    tesseract_cmd: str | None = None,
    *,
    content_only: bool = False,
) -> list[dict[str, Any]]:
    """Run the check list of ``family`` on one package folder and return the results in order.

    With ``content_only`` the redraw check (``7_redraw`` or ``7_line_redraw``) is left out.
    A check that raises is recorded as a failed result whose details name the
    exception, so the package does not pass it.
    """
    results: list[dict[str, Any]] = []
    for name, step in _check_steps(package, family, tesseract_cmd, content_only):
        try:
            outcome = step()
        except Exception as exc:  # a check that raises has not passed
            results.append(
                {"check": name, "passed": False, "details": {"raised": f"{type(exc).__name__}: {exc}"}}
            )
            continue
        results.extend(outcome if isinstance(outcome, list) else [outcome])
    return results


def wrong_answer(package: Path) -> str:
    """Make the answer a different category or value, keeping the shape of task.json.

    The new answer is fixed by the task type. A value lookup takes the label of the
    next category in spec order. An extremum takes the next category, which is not
    the largest. A rank_k takes the largest category, which is not at the asked rank.
    A pair_compare takes the other category it names. A series_at_x takes the next
    series, which is not the highest at the year. ``answer_value`` follows the change.
    """
    spec = _read_json(package / "spec.json")
    task = _read_json(package / "task.json")
    task_type = task["task_type"]
    old = task["answer"]
    if spec["family"] == "line":
        names = [entry["name"] for entry in spec["series"]]
        year = spec["x_labels"].index(task["year"])
        other = names[(names.index(old) + 1) % len(names)]
        task["answer"] = task["answer_category"] = other
        task["answer_value"] = _series_value(spec, other, year)
    elif task_type == "value_lookup":
        labels = spec["series"][0]["labels"]
        values = spec["series"][0]["values"]
        other = (spec["x_labels"].index(task["answer_category"]) + 1) % len(labels)
        task["answer"] = labels[other]
        task["answer_value"] = values[other]
    else:
        other = _other_category(spec, task)
        task["answer"] = task["answer_category"] = spec["x_labels"][other]
        task["answer_value"] = spec["series"][0]["values"][other]
    _write_json(package / "task.json", task)
    return f"answer {old!r} changed to {task['answer']!r}"


def hidden_label(package: Path) -> str:
    """Paint white over the text the answer depends on, with a 2 px margin on every side.

    The text is the answer's value label for a value lookup, its category name for an
    extremum, a rank_k or a pair_compare, and its series name in the legend for a
    series_at_x. The box is the one that text_boxes.json gives that text, in the role
    that :data:`_ANSWER_ROLE` names for the task type.
    """
    spec = _read_json(package / "spec.json")
    task = _read_json(package / "task.json")
    boxes = _read_json(package / "text_boxes.json")
    role, text = _answer_text(spec, task)
    box = next(
        (item for item in boxes if item.get("role") == role and item.get("text") == text),
        None,
    )
    if box is None:
        raise NotApplicable(f"no {role} box reads {text!r}")
    x0, y0, x1, y1 = box["bbox"]
    margin = PAINT_MARGIN_PX
    _paint(package / "image.png", (x0 - margin, y0 - margin, x1 + margin, y1 + margin))
    return f"painted over the {role} box {text!r}"


def forced_tie(package: Path) -> str:
    """Make the two largest bars equal and draw the picture again from the edited spec.

    The second-largest value and its printed label become those of the largest. The
    picture is then drawn with :func:`render_bar`, so it still matches spec.json and
    check 7 is not what catches the tie. The tie has to be caught by the spec and
    pixel checks.

    Lengthening the bar in the picture was not used. The bar would have to grow over
    its own value label, which would hide that label as well as create the tie. A task
    whose answer is the changed category takes the new value, and a value lookup also
    takes the new label.
    """
    spec = _read_json(package / "spec.json")
    task = _read_json(package / "task.json")
    if spec["family"] != "bar":
        raise NotApplicable("a forced tie is drawn on bar packages only")
    x_labels = spec["x_labels"]
    series = spec["series"][0]
    values = series["values"]
    labels = series["labels"]
    order = sorted(range(len(values)), key=lambda position: values[position], reverse=True)
    top, second = order[0], order[1]
    if values[top] == values[second]:
        raise NotApplicable("the two largest values already tie")

    previous = values[second]
    values[second] = values[top]
    labels[second] = labels[top]
    if task["answer_category"] == x_labels[second]:
        task["answer_value"] = values[second]
        if task["task_type"] == "value_lookup":
            task["answer"] = labels[second]

    question = task["question"] if spec["question_in_image"] else None
    try:
        boxes = render_bar(spec, package / "image.png", question=question)
    except ValueError as exc:  # the tied spec does not fit the canvas: nothing is written
        raise NotApplicable(f"the tied picture cannot be drawn: {exc}") from exc
    _write_json(package / "spec.json", spec)
    _write_json(package / "text_boxes.json", boxes)
    _write_json(package / "task.json", task)
    return (
        f"{x_labels[second]} raised from {previous:,} to {values[top]:,}, "
        f"equal to {x_labels[top]}"
    )


def mismatched_bar(package: Path) -> str:
    """Paint the shortest bar white, over the bounding box of its bar-colour region.

    A bar is a region of the bar colour (within ``COLOR_TOLERANCE``) of at least
    ``MIN_AREA_PX`` in area and ``MIN_SIDE_PX`` on each side. Check 5 uses the same
    thresholds and also a fill test, which this does not need. The shortest bar is the
    one with the least length along the value axis: its height for vertical bars and
    its width for horizontal ones.
    """
    spec = _read_json(package / "spec.json")
    if spec["family"] != "bar":
        raise NotApplicable("a missing bar is drawn on bar packages only")
    png = package / "image.png"
    with Image.open(png) as picture:
        image = np.array(picture.convert("RGB"))
    target = np.array(BAR_RGB, dtype=np.int16)
    near = np.all(np.abs(image.astype(np.int16) - target) <= COLOR_TOLERANCE, axis=2)
    _, _, stats, _ = cv2.connectedComponentsWithStats(near.astype(np.uint8), connectivity=4)
    bars = [
        (int(x), int(y), int(w), int(h))
        for x, y, w, h, area in stats[1:]
        if area >= MIN_AREA_PX and w >= MIN_SIDE_PX and h >= MIN_SIDE_PX
    ]
    if len(bars) < 2:
        raise NotApplicable("fewer than two bars to choose from")

    vertical = spec["orientation"] == "vertical"
    x, y, w, h = min(bars, key=lambda bar: bar[3] if vertical else bar[2])
    length = h if vertical else w
    _paint(png, (x, y, x + w, y + h))
    return (
        f"painted over the shortest bar ({length} px), leaving {len(bars) - 1} bars "
        f"for {len(spec['x_labels'])} categories"
    )


def absent_entity(package: Path) -> str:
    """Rewrite the question so that it names ABSENT_NAME, a category the spec does not have.

    Only the question text in task.json changes. A value lookup names its category,
    so the category is replaced. A pair_compare names two, so its first category is
    replaced. Other task types name no category, and :data:`APPLIES_TO` leaves them out.
    """
    spec = _read_json(package / "spec.json")
    task = _read_json(package / "task.json")
    x_labels = spec["x_labels"]
    name = ABSENT_NAME
    counter = 2
    while name in x_labels:
        name = f"{ABSENT_NAME} {counter}"
        counter += 1

    if task["task_type"] == "value_lookup":
        question = f"What value is shown for {name}?"
    elif task["task_type"] == "pair_compare":
        pairs = pair_names_from_question(task["question"], x_labels)
        if len(pairs) != 1:
            raise NotApplicable("the question does not name two categories")
        question = f"Which is higher, {name} or {pairs[0][1]}?"
    else:
        raise NotApplicable(f"a {task['task_type']} question names no category")

    before = task["question"]
    task["question"] = question
    _write_json(package / "task.json", task)
    return f"question {before!r} now names {name!r}, which is not a category of the spec"


DEFECTS: dict[str, Callable[[Path], str]] = {
    "wrong_answer": wrong_answer,
    "hidden_label": hidden_label,
    "forced_tie": forced_tie,
    "mismatched_bar": mismatched_bar,
    "absent_entity": absent_entity,
}


class _Injection(NamedTuple):
    """One injected copy: its defect, the package it came from, that package's family and folder."""

    defect: str
    package: str
    family: str
    folder: Path
    description: str


def _new_counts() -> dict[str, dict[str, int]]:
    """Injected and caught counts for every defect class, all at zero."""
    return {name: {"injected": 0, "caught": 0} for name in DEFECT_CLASSES}


def _per_class(counts: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    """The per_class block for ``counts``: injected, caught and catch_rate for each defect class."""
    return {
        name: {
            "injected": counts[name]["injected"],
            "caught": counts[name]["caught"],
            "catch_rate": (
                round(counts[name]["caught"] / counts[name]["injected"], 4)
                if counts[name]["injected"]
                else None
            ),
        }
        for name in DEFECT_CLASSES
    }


def _failed_checks(
    package: Path, family: str, tesseract_cmd: str | None, *, content_only: bool
) -> list[str]:
    """The names of the checks that fail or raise on ``package``, in run order."""
    return [
        result["check"]
        for result in check_package(package, family, tesseract_cmd, content_only=content_only)
        if not result["passed"]
    ]


def run_selftest(
    package_dirs: Sequence[Path],
    work_dir: Path,
    *,
    tesseract_cmd: str | None = None,
    content_only: bool = False,
) -> dict[str, Any]:
    """Inject every applicable defect into clean copies of ``package_dirs`` and report the catches.

    ``work_dir`` receives the copies: the clean ones under ``clean/`` and the injected
    ones under ``injected/<defect class>/``. Its ``clean`` and ``injected`` folders
    are replaced on each call. The package folders are read and never written, and
    ``work_dir`` must not overlap any of them.

    A package is clean when it passes every check of the list this run uses, and only
    clean packages are injected into. ``content_only`` is keyword-only. It selects the
    list: with it True the redraw check is left out of every check, as :func:`check_package`
    does.

    The result has these keys:

    - ``per_class``: for each defect class, ``injected`` (injections made), ``caught``
      (injections with at least one failed or raised check) and ``catch_rate``
      (``caught / injected`` to four places, or None when nothing was injected). It uses
      the list this run uses: the full list, or the content checks alone.
    - ``content_only_per_class``: the same counts with the content checks alone. It is
      computed on the same injected folders, which are not made again, so its
      ``injected`` counts match ``per_class``. When ``content_only`` is True it equals
      ``per_class``, because the run already used the content checks alone.
    - ``content_only``: the value of the ``content_only`` argument.
    - ``clean_passed`` and ``clean_total``: how many of the packages passed every check
      of the list unmodified, and how many packages there were.
    - ``details``: one record per injection, with ``class``, ``package``, ``caught``,
      ``failed_checks`` (the names of the checks that failed or raised, from the list this
      run uses) and ``description`` (what the defect did).

    Raises FileNotFoundError for a missing package folder, ValueError for a package
    that is neither bar nor line, and ValueError when ``work_dir`` overlaps a package.
    """
    work = Path(work_dir)
    sources = [Path(package) for package in package_dirs]
    for source in sources:
        if _overlaps(source.resolve(), work.resolve()):
            raise ValueError(f"work_dir {work} must not overlap the package folder {source}")
    kinds = [_package_kind(source) for source in sources]

    for stale in ("clean", "injected"):
        if (work / stale).exists():
            shutil.rmtree(work / stale)

    injections: list[_Injection] = []
    clean_passed = 0
    for position, (source, (family, task_type)) in enumerate(zip(sources, kinds)):
        label = f"{position:03d}-{source.name}"
        clean = _fresh_copy(source, work / "clean" / label)
        clean_results = check_package(clean, family, tesseract_cmd, content_only=content_only)
        if not all(result["passed"] for result in clean_results):
            continue  # a package that already fails is not used to measure the checks
        clean_passed += 1

        for defect in DEFECT_CLASSES:
            if (family, task_type) not in APPLIES_TO[defect]:
                continue
            copy = _fresh_copy(source, work / "injected" / defect / label)
            try:
                description = DEFECTS[defect](copy)
            except NotApplicable:
                continue
            injections.append(_Injection(defect, source.name, family, copy, description))

    # Each injected folder is checked with the list this run uses. A full run then checks
    # the same folders again with the content checks alone; nothing is injected twice.
    counts = _new_counts()
    details: list[dict[str, Any]] = []
    for injection in injections:
        failed = _failed_checks(
            injection.folder, injection.family, tesseract_cmd, content_only=content_only
        )
        counts[injection.defect]["injected"] += 1
        counts[injection.defect]["caught"] += int(bool(failed))
        details.append(
            {
                "class": injection.defect,
                "package": injection.package,
                "caught": bool(failed),
                "failed_checks": failed,
                "description": injection.description,
            }
        )

    content_counts = counts
    if not content_only:
        content_counts = _new_counts()
        for injection in injections:
            failed = _failed_checks(
                injection.folder, injection.family, tesseract_cmd, content_only=True
            )
            content_counts[injection.defect]["injected"] += 1
            content_counts[injection.defect]["caught"] += int(bool(failed))

    return {
        "clean_passed": clean_passed,
        "clean_total": len(sources),
        "content_only": bool(content_only),
        "details": details,
        "per_class": _per_class(counts),
        "content_only_per_class": _per_class(content_counts),
    }


def _check_steps(
    package: Path, family: str, tesseract_cmd: str | None, content_only: bool = False
) -> list[tuple[str, Callable[[], Any]]]:
    """The checks of ``family`` as (name, call) pairs, in the order the pipeline runs them.

    With ``content_only`` the redraw check is left out: check 7 of a bar package and
    ``7_line_redraw`` of a line package.
    """
    if family == "bar":
        return [
            (
                "layout_checks",
                lambda: run_layout_checks(
                    package,
                    min_margin=MIN_MARGIN,
                    min_font_px=MIN_FONT_PX,
                    include_redraw=not content_only,
                ),
            ),
            ("4_ocr", lambda: check_4_ocr(package, tesseract_cmd)),
            ("5_pixels", lambda: check_5_pixels(package)),
            ("6_counterfactual", lambda: check_6_counterfactual(package)),
        ]
    if family == "line":
        steps: list[tuple[str, Callable[[], Any]]] = [
            ("1_schema", lambda: check_1_schema(package)),
            ("2_layout", lambda: check_2_layout(package, min_font_px=MIN_FONT_PX)),
            (CHECK_3, lambda: check_3_line_ambiguity(package, min_margin=MIN_MARGIN)),
            ("4_ocr", lambda: check_4_ocr(package, tesseract_cmd)),
            (CHECK_5, lambda: check_5_line_pixels(package)),
            (CHECK_6, lambda: check_6_line_counterfactual(package)),
        ]
        if not content_only:
            steps.append((CHECK_7, lambda: check_7_line_redraw(package)))
        return steps
    raise ValueError(f"no check list for family {family!r}")


def _package_kind(package: Path) -> tuple[str, str]:
    """The (family, task type) of a package, read from its spec.json and task.json."""
    family = _read_json(package / "spec.json")["family"]
    if family not in ("bar", "line"):
        raise ValueError(f"{package}: the self-test covers bar and line packages, not {family!r}")
    return family, _read_json(package / "task.json")["task_type"]


def _answer_text(spec: dict[str, Any], task: dict[str, Any]) -> tuple[str, str]:
    """The text-box role and text that hidden_label covers for a package's answer."""
    role = _ANSWER_ROLE.get((spec["family"], task["task_type"]))
    if role is None:
        raise NotApplicable(f"no answer text is covered for a {task['task_type']} question")
    if role == "value":
        position = spec["x_labels"].index(task["answer_category"])
        return role, spec["series"][0]["labels"][position]
    return role, task["answer"]


def _other_category(spec: dict[str, Any], task: dict[str, Any]) -> int:
    """The position of a category that is not the answer, for a bar task that is not a value lookup."""
    x_labels = spec["x_labels"]
    values = spec["series"][0]["values"]
    task_type = task["task_type"]
    if task_type == "extremum":
        return (x_labels.index(task["answer"]) + 1) % len(x_labels)
    if task_type == "rank_k":
        return max(range(len(values)), key=lambda position: values[position])
    if task_type == "pair_compare":
        pairs = pair_names_from_question(task["question"], x_labels)
        if len(pairs) != 1:
            raise NotApplicable("the question does not name two categories")
        first, second = pairs[0]
        return x_labels.index(second if task["answer"] == first else first)
    raise NotApplicable(f"no other category for a {task_type} question")


def _series_value(spec: dict[str, Any], name: str, year: int) -> int:
    """The value of the series called ``name`` at position ``year``."""
    return next(entry["values"][year] for entry in spec["series"] if entry["name"] == name)


def _paint(png: Path, box: Sequence[int]) -> None:
    """Fill the pixel box (x0, y0, x1, y1), clipped to the picture, with white and save the PNG."""
    with Image.open(png) as picture:
        image = np.array(picture.convert("RGB"))
    height, width = image.shape[:2]
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(width, int(box[2])), min(height, int(box[3]))
    image[y0:y1, x0:x1] = WHITE
    Image.fromarray(image).save(png, format="PNG")


def _fresh_copy(source: Path, destination: Path) -> Path:
    """Copy a package folder to ``destination``, replacing whatever was there."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return destination


def _overlaps(first: Path, second: Path) -> bool:
    """True when one path is the other or lies inside it."""
    return first == second or first in second.parents or second in first.parents


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
