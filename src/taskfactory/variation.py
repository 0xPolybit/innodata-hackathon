"""Perceptual hashes and variation metrics for one run.

:func:`phash` gives a rendered picture a 64-bit perceptual hash, and
:func:`hamming` counts the bits in which two hashes differ. The pipeline uses
them for the near-duplicate rule of PLAN.md section 4.6: a candidate whose hash
lies within ``checks.near_dup_phash_max`` bits of a kept candidate of the same
family and task type is removed before it is packaged.

:func:`variation_metrics` builds the ``variation`` block of ``metrics.json`` as
PLAN.md section 4.8 defines it. Only the packages that passed every check are
final tasks, so only they feed the entropy, the structural difference and the
reasoning-depth histogram. Cell coverage counts every cell that had a generated
package, because it asks how many attempted cells reached the bar.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

import cv2
import numpy as np
from PIL import Image

__all__ = [
    "MIN_TASKS_PER_CELL",
    "Candidate",
    "hamming",
    "phash",
    "structure_signature",
    "variation_metrics",
]

HASH_BITS = 64
MIN_TASKS_PER_CELL = 5  # a cell is covered when it holds at least this many passed tasks

_GREY_SIZE = 32  # a picture is shrunk to 32 x 32 pixels before the DCT
_BLOCK = 8  # the top-left 8 x 8 block of DCT coefficients is the hash
_DECIMALS = 4


class Candidate(NamedTuple):
    """One generated package, as the variation metrics see it.

    ``structure`` is :func:`structure_signature` of the package's spec and
    ``passed`` is True when every check passed, which makes it a final task.
    """

    package_id: str
    family: str
    domain: str
    task_type: str
    phash: int
    structure: tuple[Any, ...]
    reasoning_steps: int
    passed: bool


def phash(png_path: str | os.PathLike[str]) -> int:
    """Return the 64-bit perceptual hash of the picture at ``png_path``.

    The picture is converted to greyscale, shrunk to 32 x 32 pixels with
    ``cv2.INTER_AREA`` and passed through a 2-D DCT in float32. The top-left
    8 x 8 block of coefficients is kept. Its median is taken over the 63 AC
    terms, leaving out the DC term at position 0, and bit ``k`` (row-major order
    in the block) is 1 when coefficient ``k`` is above that median. The DC term's
    own bit is always 0.
    """
    with Image.open(png_path) as image:
        grey = np.asarray(image.convert("L"), dtype=np.uint8)
    small = cv2.resize(grey, (_GREY_SIZE, _GREY_SIZE), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(small.astype(np.float32))
    block = coefficients[:_BLOCK, :_BLOCK].reshape(-1)
    median = float(np.median(block[1:]))
    value = 0
    for position in range(1, HASH_BITS):
        if block[position] > median:
            value |= 1 << position
    return value


def hamming(first: int, second: int) -> int:
    """Return the number of bit positions at which two hashes differ."""
    return (int(first) ^ int(second)).bit_count()


def structure_signature(spec: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the structural fields of a spec that the structural-difference metric compares.

    The fields are the number of x labels, the orientation, the x-label rotation,
    the number of series, and for each series the order its values sort into,
    largest first. Two specs with different signatures differ in at least one of
    them. The values themselves, the category names and the title are not
    structure, so they are left out.
    """
    series = spec["series"]
    return (
        len(spec["x_labels"]),
        spec["orientation"],
        spec["x_label_rotation"],
        len(series),
        tuple(_sorted_order(entry["values"]) for entry in series),
    )


def variation_metrics(
    candidates: Iterable[Candidate], near_duplicates_removed: int
) -> dict[str, Any]:
    """Return the ``variation`` block of ``metrics.json``, with floats rounded to four places.

    ``candidates`` holds every generated package, passed or rejected. Near-duplicates
    removed before packaging are not among them and are counted by
    ``near_duplicates_removed`` alone. The keys are:

    - ``cell_coverage``: the share of attempted (family, domain, task type) cells that
      hold at least :data:`MIN_TASKS_PER_CELL` passed tasks. A cell is attempted when
      it has at least one generated package. 0.0 when no cell was attempted.
    - ``question_type_entropy``: Shannon entropy of the task-type counts over the
      passed tasks, divided by the log of the number of types present. 0.0 when
      one type or none is present.
    - ``structural_difference``: the share of nearest-neighbour pairs whose specs
      differ in a structural field. Nearest neighbours are found by pHash Hamming
      distance within each family and task type, and a pair found from both ends
      counts once. 1.0 when there are no pairs, which includes fewer than two tasks.
    - ``reasoning_depth_histogram``: counts of ``reasoning_steps`` over the passed
      tasks, keyed by the step count as a string.
    - ``near_duplicates_removed``: the count passed in.
    """
    generated = list(candidates)
    final = sorted((c for c in generated if c.passed), key=lambda c: c.package_id)
    return {
        "cell_coverage": _cell_coverage(generated),
        "near_duplicates_removed": near_duplicates_removed,
        "question_type_entropy": _question_type_entropy(final),
        "reasoning_depth_histogram": _reasoning_depth_histogram(final),
        "structural_difference": _structural_difference(final),
    }


def _sorted_order(values: Sequence[int]) -> tuple[int, ...]:
    """Positions of ``values`` from largest to smallest; equal values keep their position order."""
    return tuple(sorted(range(len(values)), key=lambda position: values[position], reverse=True))


def _cell_coverage(generated: Sequence[Candidate]) -> float:
    attempted = {_cell(candidate) for candidate in generated}
    if not attempted:
        return 0.0
    passed = Counter(_cell(candidate) for candidate in generated if candidate.passed)
    covered = sum(1 for cell in attempted if passed[cell] >= MIN_TASKS_PER_CELL)
    return _round(covered / len(attempted))


def _cell(candidate: Candidate) -> tuple[str, str, str]:
    return (candidate.family, candidate.domain, candidate.task_type)


def _question_type_entropy(final: Sequence[Candidate]) -> float:
    counts = Counter(candidate.task_type for candidate in final)
    if len(counts) < 2:
        return 0.0
    total = sum(counts.values())
    entropy = -sum((n / total) * math.log(n / total) for n in counts.values())
    return _round(entropy / math.log(len(counts)))


def _reasoning_depth_histogram(final: Sequence[Candidate]) -> dict[str, int]:
    counts = Counter(candidate.reasoning_steps for candidate in final)
    return {str(steps): counts[steps] for steps in sorted(counts)}


def _structural_difference(final: Sequence[Candidate]) -> float:
    pairs = _nearest_neighbour_pairs(final)
    if not pairs:
        return 1.0
    differing = sum(1 for first, second in pairs if final[first].structure != final[second].structure)
    return _round(differing / len(pairs))


def _nearest_neighbour_pairs(final: Sequence[Candidate]) -> set[tuple[int, int]]:
    """Unordered (lower, higher) index pairs, each candidate joined to its nearest neighbour.

    A candidate's neighbours are the other candidates of its own family and task
    type. The nearest is the smallest Hamming distance, and on a tie the earliest
    in ``final``.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for index, candidate in enumerate(final):
        groups.setdefault((candidate.family, candidate.task_type), []).append(index)

    pairs: set[tuple[int, int]] = set()
    for members in groups.values():
        for index in members:
            others = [other for other in members if other != index]
            if not others:
                continue
            nearest = min(
                others,
                key=lambda other: (hamming(final[index].phash, final[other].phash), other),
            )
            pairs.add((min(index, nearest), max(index, nearest)))
    return pairs


def _round(value: float) -> float:
    return round(float(value), _DECIMALS)
