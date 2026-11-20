"""Check 4: OCR read-back.

Tesseract reads ``image.png`` with sparse-text page segmentation (``--psm 11``)
and the check confirms that the strings a correct answer depends on are
visibly printed in the picture. The returned dict is
``{"check": "4_ocr", "passed": bool, "details": {...}}`` and every value in
``details`` is JSON-serialisable.

Required strings
----------------
Always the task's ``answer``. For a ``value_lookup`` task the
``answer_category`` is required too, because the question names it. An
``extremum`` question names no category, so only the answer is required. A
``series_at_x`` answer is a legend name and is required on its own.
``question_in_image`` adds no requirement of its own: the question text is not
required to be readable.

Matching rule
-------------
The OCR words are joined with single spaces, lower-cased and whitespace
collapsed. Every required string is normalised the same way, with a trailing
period removed. A required string counts as found when either

* the normalised string occurs in the normalised OCR text, or
* every token of it occurs as a whole word among the OCR words and those
  words sit within 40 px horizontally and 25 px vertically of each other,
  measured between nearest box edges. This fallback covers a multi-word
  category name that Tesseract splits into separate tokens.

Case folding and surrounding punctuation are the only OCR confusions
tolerated; a numeric label such as ``40.6M`` must otherwise match exactly.

Caption mask
------------
The question printed in the picture is a ``caption`` text box, and it often
names a category or a value that the chart itself does not have to show. So
when ``text_boxes.json`` holds a ``caption`` box, a copy of the picture is made
with every caption box painted white over its bbox grown by four pixels, and
every pass below reads that copy: the full-image pass, the crop passes and the
match for every required string, the answer included. ``details["caption_masked"]``
is True then and False otherwise, and a package without a caption box is read
exactly as before. A caption box with no usable bbox, or an image that cannot
be opened to be masked, fails the check; it is not read unmasked.

Rotated labels
--------------
Full-image OCR cannot read category labels drawn at an angle. When a required
string is still missing after that first pass, and ``text_boxes.json`` holds a
``category`` box whose normalised text is the required string, the image is
cropped to that box padded by six pixels (clipped to the canvas) and the crop
is read at 0, +30 and -30 degrees with the same matching rule. ``details``
records where each string was read in ``found_via``: ``"full"`` for the
first pass, or ``"crop_rot_0"``, ``"crop_rot_30"`` and ``"crop_rot_-30"`` for
the category crop pass.

Value labels
------------
Sparse full-text segmentation also drops small value labels printed at the end
of a bar. When a required string is still missing after the category crop
pass, and ``text_boxes.json`` holds a ``value`` box whose normalised text is
the required string, the image is cropped to that box padded by six pixels
(clipped to the canvas) and the crop is upscaled three times with Pillow's
LANCZOS resampling before OCR at 0 degrees only, since value labels are not
rotated. A match is recorded in ``found_via`` as ``"crop_value_x3"``. Strings
that every pass misses stay False.

Legend labels
-------------
A line chart's answer is a series name printed in its legend. When a required
string is still missing after the value pass, and ``text_boxes.json`` holds a
``legend`` box whose normalised text is the required string, the image is
cropped to that box padded by six pixels, upscaled three times and read at 0
degrees, as for value labels. A match is recorded in ``found_via`` as
``"crop_legend_x3"``.

A check that fails on bad content returns ``passed`` False instead of raising.
``FileNotFoundError`` is raised only when ``image.png`` or ``task.json`` is
missing from the package folder.
"""

from __future__ import annotations

import json
import os
import re
import string
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

__all__ = ["check_4_ocr", "run_ocr_check"]

_DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSERACT_CONFIG = "--psm 11"
_MAX_GAP_X = 40
_MAX_GAP_Y = 25
_CROP_PAD_PX = 6
_CROP_ROTATIONS = (0, 30, -30)
_VALUE_CROP_SCALE = 3
_VALUE_CROP_VIA = "crop_value_x3"
_VALUE_ROLE = "value"
_LEGEND_ROLE = "legend"
_LEGEND_CROP_VIA = "crop_legend_x3"
_CAPTION_ROLE = "caption"
_CAPTION_MASK_PX = 4  # each caption box is painted over with this much margin on every side
_WHITE = "white"
_WHITE_RGB = (255, 255, 255)
_WHITESPACE = re.compile(r"\s+")


def check_4_ocr(pkg_dir: Path, tesseract_cmd: str | None = None) -> dict[str, Any]:
    """Run the OCR read-back check on one package folder.

    ``pkg_dir`` must contain ``image.png`` and ``task.json``; either missing
    file raises :class:`FileNotFoundError`. ``tesseract_cmd`` overrides the
    executable path. When it is None, ``TESSERACT_CMD`` is used if set, then
    the standard Windows install path, then ``tesseract`` from ``PATH``.

    When the package has a caption box, every pass reads the picture with the
    caption painted over (see the module docstring), and
    ``details["caption_masked"]`` is True.

    Returns the check record described in the module docstring. Bad content
    (unreadable JSON, a missing answer, an OCR failure, a caption box that
    cannot be masked) produces ``passed`` False with an ``error`` entry in
    ``details`` rather than an exception.
    """
    pkg_dir = Path(pkg_dir)
    image_path = pkg_dir / "image.png"
    task_path = pkg_dir / "task.json"
    if not image_path.is_file():
        raise FileNotFoundError(f"missing image: {image_path}")
    if not task_path.is_file():
        raise FileNotFoundError(f"missing task file: {task_path}")

    details: dict[str, Any] = {
        "ocr_text": "",
        "required": [],
        "found": {},
        "found_via": {},
        "tesseract_version": "unknown",
        "caption_masked": False,
    }

    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        details["error"] = f"cannot read task.json: {exc}"
        return _result(False, details)
    if not isinstance(task, dict):
        details["error"] = "task.json is not a JSON object"
        return _result(False, details)

    required = _required_strings(task)
    details["required"] = required
    if not required:
        details["error"] = "task.json has no usable 'answer'"
        return _result(False, details)

    _set_tesseract_cmd(tesseract_cmd)
    details["tesseract_version"] = _tesseract_version()

    # The picture every pass reads: the image itself, or a copy with the caption painted over.
    picture = _open_rgb(image_path)
    captions = _caption_bboxes(pkg_dir)
    if captions is None:
        details["error"] = "a caption box in text_boxes.json has no usable bbox"
        details["found"] = {text: False for text in required}
        return _result(False, details)
    if captions:
        if picture is None:
            details["error"] = "cannot read image.png to paint over the caption"
            details["found"] = {text: False for text in required}
            return _result(False, details)
        picture = _paint_boxes(picture, captions, _CAPTION_MASK_PX)
        details["caption_masked"] = True

    full_source: Image.Image | str = picture if details["caption_masked"] else str(image_path)
    try:
        data = pytesseract.image_to_data(
            full_source,
            output_type=pytesseract.Output.DICT,
            config=_TESSERACT_CONFIG,
        )
    except Exception as exc:  # any OCR failure is a failed check, not a crash
        details["error"] = f"OCR failed: {type(exc).__name__}: {exc}"
        details["found"] = {text: False for text in required}
        return _result(False, details)

    words = _ocr_words(data)
    details["ocr_text"] = _normalise(" ".join(word["raw"] for word in words))
    details["found"] = {
        text: _is_found(text, details["ocr_text"], words) for text in required
    }
    details["found_via"] = {
        text: "full" for text, found in details["found"].items() if found
    }

    missing = [text for text in required if not details["found"][text]]
    if missing:
        _crop_pass(picture, pkg_dir, missing, details)
        missing = [text for text in required if not details["found"][text]]
    if missing:
        _upscaled_crop_pass(
            picture, pkg_dir, missing, details, _VALUE_ROLE, _VALUE_CROP_VIA
        )
        missing = [text for text in required if not details["found"][text]]
    if missing:
        _upscaled_crop_pass(
            picture, pkg_dir, missing, details, _LEGEND_ROLE, _LEGEND_CROP_VIA
        )

    return _result(all(details["found"].values()), details)


def run_ocr_check(pkg_dir: Path, tesseract_cmd: str | None = None) -> dict[str, Any]:
    """Alias for :func:`check_4_ocr`, kept as the simpler caller-facing name."""
    return check_4_ocr(pkg_dir, tesseract_cmd)


def _result(passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    """One check record in the shape every check returns."""
    return {"check": "4_ocr", "passed": bool(passed), "details": details}


def _required_strings(task: dict[str, Any]) -> list[str]:
    """Normalised strings a correct answer depends on, in a stable order."""
    candidates: list[Any] = [task.get("answer")]
    if task.get("task_type") == "value_lookup":
        candidates.append(task.get("answer_category"))

    required: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        text = _normalise(candidate)
        if text and text not in required:
            required.append(text)
    return required


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace and drop one trailing period."""
    collapsed = _WHITESPACE.sub(" ", str(text)).strip().lower()
    return collapsed[:-1] if collapsed.endswith(".") else collapsed


def _open_rgb(image_path: Path) -> Image.Image | None:
    """``image.png`` as RGB, or None when Pillow cannot read it."""
    try:
        with Image.open(image_path) as source:
            return source.convert("RGB")
    except Exception:  # the full-image pass reports an unreadable picture as its own error
        return None


def _paint_boxes(
    picture: Image.Image, bboxes: list[tuple[int, int, int, int]], margin: int
) -> Image.Image:
    """A copy of ``picture`` with each bbox, grown by ``margin`` pixels, painted white.

    The grown box is clipped to the picture. ``picture`` itself is not changed.
    """
    painted = picture.copy()
    for x0, y0, x1, y1 in bboxes:
        left = max(0, x0 - margin)
        top = max(0, y0 - margin)
        right = min(painted.width, x1 + margin)
        bottom = min(painted.height, y1 + margin)
        if right > left and bottom > top:
            painted.paste(_WHITE_RGB, (left, top, right, bottom))
    return painted


def _crop_pass(
    picture: Image.Image | None,
    pkg_dir: Path,
    missing: list[str],
    details: dict[str, Any],
) -> None:
    """Read padded category crops at 0, +30 and -30 degrees for missing strings."""
    boxes = _category_boxes(pkg_dir)
    if picture is None or not boxes:
        return

    for text in missing:
        for bbox in (box for label, box in boxes if label == text):
            crop = _crop(picture, bbox, _CROP_PAD_PX)
            if crop is None:
                continue
            for angle in _CROP_ROTATIONS:
                rotated = crop.rotate(angle, expand=True, fillcolor=_WHITE)
                try:
                    data = pytesseract.image_to_data(
                        rotated,
                        output_type=pytesseract.Output.DICT,
                        config=_TESSERACT_CONFIG,
                    )
                except Exception:  # one unreadable crop must not fail the check
                    continue
                words = _ocr_words(data)
                crop_text = _normalise(" ".join(word["raw"] for word in words))
                if _is_found(text, crop_text, words):
                    details["found"][text] = True
                    details["found_via"][text] = f"crop_rot_{angle}"
                    break
            if details["found"][text]:
                break


def _upscaled_crop_pass(
    picture: Image.Image | None,
    pkg_dir: Path,
    missing: list[str],
    details: dict[str, Any],
    role: str,
    found_via: str,
) -> None:
    """Read 3x upscaled crops of the ``role`` boxes at 0 degrees for missing strings.

    Used for value labels and legend labels. Both are drawn unrotated, so one
    0-degree read of each crop is enough.
    """
    boxes = _role_boxes(pkg_dir, role)
    if picture is None or not boxes:
        return

    for text in missing:
        for bbox in (box for label, box in boxes if label == text):
            crop = _crop(picture, bbox, _CROP_PAD_PX)
            if crop is None:
                continue
            upscaled = crop.resize(
                (crop.width * _VALUE_CROP_SCALE, crop.height * _VALUE_CROP_SCALE),
                Image.LANCZOS,
            )
            try:
                data = pytesseract.image_to_data(
                    upscaled,
                    output_type=pytesseract.Output.DICT,
                    config=_TESSERACT_CONFIG,
                )
            except Exception:  # one unreadable crop must not fail the check
                continue
            words = _ocr_words(data)
            crop_text = _normalise(" ".join(word["raw"] for word in words))
            if _is_found(text, crop_text, words):
                details["found"][text] = True
                details["found_via"][text] = found_via
                break


def _text_box_list(pkg_dir: Path) -> list[Any]:
    """The entries of text_boxes.json, or an empty list when it is missing or not a list."""
    try:
        boxes = json.loads((pkg_dir / "text_boxes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return boxes if isinstance(boxes, list) else []


def _pixel_bbox(box: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """The box's ``bbox`` as four whole pixel values, or None when it is not usable."""
    bbox = box.get("bbox")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    ):
        return None
    try:
        x0, y0, x1, y1 = (int(value) for value in bbox)
    except (OverflowError, ValueError):  # infinity or NaN
        return None
    return x0, y0, x1, y1


def _caption_bboxes(pkg_dir: Path) -> list[tuple[int, int, int, int]] | None:
    """Pixel bbox of every caption box, or None when a caption box has no usable bbox."""
    bboxes: list[tuple[int, int, int, int]] = []
    for box in _text_box_list(pkg_dir):
        if isinstance(box, dict) and box.get("role") == _CAPTION_ROLE:
            bbox = _pixel_bbox(box)
            if bbox is None:
                return None
            bboxes.append(bbox)
    return bboxes


def _category_boxes(pkg_dir: Path) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Normalised text and pixel bbox of every category box, when usable."""
    return _role_boxes(pkg_dir, "category")


def _role_boxes(
    pkg_dir: Path, role: str
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Normalised text and pixel bbox of every text box with ``role``."""
    result: list[tuple[str, tuple[int, int, int, int]]] = []
    for box in _text_box_list(pkg_dir):
        if not isinstance(box, dict) or box.get("role") != role:
            continue
        text = _normalise(str(box.get("text", "")))
        bbox = _pixel_bbox(box)
        if text and bbox is not None:
            result.append((text, bbox))
    return result


def _crop(image: Image.Image, bbox: tuple[int, int, int, int], pad: int) -> Image.Image | None:
    """The bbox grown by ``pad`` pixels on every side, clipped to the canvas."""
    x0, y0, x1, y1 = bbox
    left = max(0, x0 - pad)
    top = max(0, y0 - pad)
    right = min(image.width, x1 + pad)
    bottom = min(image.height, y1 + pad)
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def _word_token(word: str) -> str:
    """Normalise one OCR word and strip punctuation wrapped around it."""
    return _normalise(word).strip(string.punctuation)


def _ocr_words(data: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Word rows from ``image_to_data`` with text and pixel boxes."""
    words: list[dict[str, Any]] = []
    for index, raw in enumerate(data.get("text", [])):
        if not isinstance(raw, str) or not raw.strip():
            continue
        token = _word_token(raw)
        if not token:
            continue
        words.append(
            {
                "raw": raw.strip(),
                "text": token,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )
    return words


def _is_found(text: str, ocr_text: str, words: list[dict[str, Any]]) -> bool:
    """True when ``text`` is in the OCR text, or its tokens are nearby words."""
    if text in ocr_text:
        return True
    tokens = [token for token in text.split(" ") if token]
    if len(tokens) < 2:
        return False
    return _tokens_nearby(tokens, words)


def _tokens_nearby(tokens: list[str], words: list[dict[str, Any]]) -> bool:
    """True when every token has an OCR word occurrence near every other token."""
    candidates = [[word for word in words if word["text"] == token] for token in tokens]
    if any(not matches for matches in candidates):
        return False

    # Anchor on the rarest token so the fewest combinations are tried.
    order = sorted(range(len(tokens)), key=lambda i: len(candidates[i]))
    for anchor in candidates[order[0]]:
        if all(
            any(_near(anchor, other) for other in candidates[index])
            for index in order[1:]
        ):
            return True
    return False


def _near(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """True when two word boxes are within the allowed edge gaps."""
    return (
        _edge_gap(
            first["left"],
            first["left"] + first["width"],
            second["left"],
            second["left"] + second["width"],
        )
        <= _MAX_GAP_X
        and _edge_gap(
            first["top"],
            first["top"] + first["height"],
            second["top"],
            second["top"] + second["height"],
        )
        <= _MAX_GAP_Y
    )


def _edge_gap(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    """Pixels between two 1-D spans; zero when they overlap."""
    return max(0, max(start_a, start_b) - min(end_a, end_b))


def _resolve_tesseract_cmd(tesseract_cmd: str | None) -> str:
    """Explicit path, then ``TESSERACT_CMD``, then the install path or PATH."""
    if tesseract_cmd:
        return tesseract_cmd
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd:
        return env_cmd
    if Path(_DEFAULT_TESSERACT_CMD).is_file():
        return _DEFAULT_TESSERACT_CMD
    return "tesseract"


def _set_tesseract_cmd(tesseract_cmd: str | None) -> None:
    """Point pytesseract at the executable for this call."""
    pytesseract.pytesseract.tesseract_cmd = _resolve_tesseract_cmd(tesseract_cmd)


def _tesseract_version() -> str:
    """Tesseract version string, or ``"unknown"`` when it cannot be read."""
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:  # a missing or broken executable only loses the version
        return "unknown"
