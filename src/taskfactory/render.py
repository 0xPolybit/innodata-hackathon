"""Bar chart renderer: one single-series bar spec in, one 1200 x 800 PNG out.

``render_bar`` also returns the box of every text element it draws, so callers
can check layout without reading pixels. The figure is built with ``Figure``
and ``FigureCanvasAgg`` instead of pyplot, so no global state is touched and
one spec always produces the same PNG bytes.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, NamedTuple

from matplotlib.artist import Artist
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

__all__ = ["render_bar"]

CANVAS_W = 1200
CANVAS_H = 800
DPI = 100
FONT = "DejaVu Sans"

TITLE_PT = 22
LABEL_PT = 14  # category labels, value labels and caption
FOOTER_PT = 10

BAR_COLOR = "#4C72B0"
TITLE_COLOR = "#222222"
LABEL_COLOR = "#333333"
VALUE_COLOR = "#222222"
AXIS_COLOR = "#444444"
FOOTER_TEXT = "Synthetic data"
FOOTER_COLOR = "#666666"

# Layout in image pixels, origin top-left.
SIDE = 40  # left/right margin; x of title, caption and footer
PLOT_RIGHT = CANVAS_W - SIDE
TOP = 26  # top of the title block
TITLE_GAP = 28  # title block to plot area
BLOCK_GAP = 14  # plot area or category labels to caption (or footer)
CAPTION_GAP = 10  # caption to footer
FOOTER_BOTTOM = 22  # footer to bottom edge
CATEGORY_GAP = 12  # horizontal bars: category labels to y axis
LABEL_GAP = 8  # vertical bars: x axis to category labels
VALUE_PAD_PT = 4  # bar end to value label
ROOM_PX = 2  # spare pixels beyond each value label
BAR_WIDTH = 0.6  # bar thickness as a fraction of its category slot
MIN_PLOT_PX = 120  # smallest plot-area extent accepted
TEXT_WIDTH = CANVAS_W - 2 * SIDE  # wrap width for title and caption


class _Bars(NamedTuple):
    title: str
    categories: list[str]
    values: list[float]
    labels: list[str]
    horizontal: bool
    rotation: int


def _parse(spec: dict[str, Any]) -> _Bars:
    """Check a bar spec and return the fields the renderer draws."""
    if spec.get("spec_version") != 1:
        raise ValueError(f"spec_version must be 1, not {spec.get('spec_version')!r}")
    if spec.get("family") != "bar":
        raise ValueError(f"render_bar only draws family 'bar', not {spec.get('family')!r}")
    series = spec.get("series")
    if not isinstance(series, (list, tuple)) or len(series) != 1:
        raise ValueError("a bar spec needs exactly one series")

    categories = [str(c) for c in spec["x_labels"]]
    values = [float(v) for v in series[0]["values"]]
    labels = [str(s) for s in series[0]["labels"]]
    if len({len(categories), len(values), len(labels)}) != 1:
        raise ValueError(
            "x_labels, values and labels must have the same length; got "
            f"{len(categories)}, {len(values)} and {len(labels)}"
        )
    if not values:
        raise ValueError("a bar spec needs at least one category")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("bar values must be finite numbers")
    orientation = spec["orientation"]
    if orientation not in ("vertical", "horizontal"):
        raise ValueError(f"orientation must be 'vertical' or 'horizontal', not {orientation!r}")
    rotation = spec["x_label_rotation"]
    if rotation not in (0, 30):
        raise ValueError(f"x_label_rotation must be 0 or 30, not {rotation!r}")

    return _Bars(
        title=str(spec["title"]),
        categories=categories,
        values=values,
        labels=labels,
        horizontal=orientation == "horizontal",
        rotation=rotation,
    )


def _fx(x_px: float) -> float:
    """Image x in pixels to a figure fraction."""
    return x_px / CANVAS_W


def _fy(y_px: float) -> float:
    """Image y in pixels (top-left origin) to a figure fraction (bottom-left origin)."""
    return 1.0 - y_px / CANVAS_H


def _measure(fig: Figure, text: str, size_pt: float, rotation: float = 0.0) -> tuple[float, float]:
    """Width and height in pixels of ``text`` as it will be drawn."""
    artist = fig.text(
        0, 0, text, fontsize=size_pt, fontfamily=FONT, rotation=rotation, parse_math=False
    )
    try:
        box = artist.get_window_extent(fig.canvas.get_renderer())
    finally:
        artist.remove()
    return box.width, box.height


def _wrap(fig: Figure, text: str, size_pt: float) -> str:
    """Break ``text`` at spaces so each line fits TEXT_WIDTH. Only the drawn copy changes."""
    words = text.split()
    if not words:
        return ""
    lines = [words[0]]
    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        if _measure(fig, candidate, size_pt)[0] <= TEXT_WIDTH:
            lines[-1] = candidate
        else:
            lines.append(word)
    return "\n".join(lines)


def _value_limits(
    values: list[float], extents: list[float], span_px: float, pad_px: float
) -> tuple[float, float]:
    """Data limits for the value axis, with room past each bar end for its label.

    ``extents`` is each label's size along the value axis. Bars start at zero,
    so zero is always inside the limits.
    """
    lo = min(0.0, min(values))
    hi = max(0.0, max(values))
    if hi == lo:
        hi = lo + 1.0  # all zeros: keep the axis from collapsing
    # Labels of zero and positive bars go past the high end; negative ones past the low end.
    hi_extents = [e for e, v in zip(extents, values) if v >= 0]
    lo_extents = [e for e, v in zip(extents, values) if v < 0]
    hi_room = max(hi_extents) + pad_px + ROOM_PX if hi_extents else 0.0
    lo_room = max(lo_extents) + pad_px + ROOM_PX if lo_extents else 0.0
    free_px = span_px - hi_room - lo_room
    if free_px < MIN_PLOT_PX:
        raise ValueError("the value labels leave too little room for the bars")
    scale = free_px / (hi - lo)
    return lo - lo_room / scale, hi + hi_room / scale


def _text_box(
    fig: Figure, role: str, text: str, artist: Artist, size_pt: float
) -> dict[str, Any]:
    """Text box in image pixels (top-left origin), rounded outward to whole pixels."""
    box = artist.get_window_extent(fig.canvas.get_renderer())
    return {
        "role": role,
        "text": text,
        "bbox": [
            math.floor(box.x0),
            math.floor(CANVAS_H - box.y1),
            math.ceil(box.x1),
            math.ceil(CANVAS_H - box.y0),
        ],
        "font_px": round(size_pt * DPI / 72),
    }


def render_bar(
    spec: dict[str, Any],
    png_path: str | os.PathLike[str],
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Render a bar spec to ``png_path`` and return the text boxes.

    The PNG is 1200 x 800 and has no metadata (no software tag, no dpi chunk).
    ``question`` is printed as a caption above the footer only when it is not
    None and ``spec["question_in_image"]`` is True.

    Each box is ``{"role", "text", "bbox", "font_px"}``. ``bbox`` is
    ``[x0, y0, x1, y1]`` in image pixels with the origin at the top-left.
    Boxes come in the order title, categories, values, footer, caption.
    ``text`` is the string as given, even when a title or caption was wrapped.

    Raises ValueError for an unsupported family, a series count other than one,
    lists of different lengths, an empty category list, an unknown orientation
    or rotation, or a layout that cannot fit on the canvas.
    """
    bars = _parse(spec)
    show_caption = question is not None and spec.get("question_in_image") is True
    # Category labels are only rotated in vertical mode.
    rotation = 0 if bars.horizontal else bars.rotation
    n = len(bars.values)

    fig = Figure(figsize=(CANVAS_W / DPI, CANVAS_H / DPI), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)  # attaches itself as fig.canvas

    # Fixed blocks: title at the top; footer at the bottom with the caption above it.
    title_text = _wrap(fig, bars.title, TITLE_PT)
    _, title_h = _measure(fig, title_text, TITLE_PT)
    _, footer_h = _measure(fig, FOOTER_TEXT, FOOTER_PT)
    footer_top = CANVAS_H - FOOTER_BOTTOM - footer_h
    caption_text: str | None = None
    stack_top = footer_top  # top edge of the lowest block above the footer
    if show_caption:
        caption_text = _wrap(fig, str(question), LABEL_PT)
        _, caption_h = _measure(fig, caption_text, LABEL_PT)
        caption_bottom = footer_top - CAPTION_GAP
        stack_top = caption_bottom - caption_h
    content_bottom = stack_top - BLOCK_GAP
    plot_top = TOP + title_h + TITLE_GAP

    # Plot area. Its left or bottom edge depends on the size of the category labels.
    if bars.horizontal:
        cat_widths = [_measure(fig, c, LABEL_PT)[0] for c in bars.categories]
        plot_left = SIDE + max(cat_widths) + CATEGORY_GAP
        plot_bottom = content_bottom
    else:
        cat_sizes = [_measure(fig, c, LABEL_PT, rotation) for c in bars.categories]
        plot_bottom = content_bottom - LABEL_GAP - max(h for _, h in cat_sizes)
        # Rotated labels extend left of their anchor by their full width; upright
        # labels extend half a width each way. Category i is centred in its slot,
        # so solve (plot_left + slot / 2) - overhang >= SIDE for plot_left.
        overhang = max(w if rotation else w / 2 for w, _ in cat_sizes)
        plot_left = max(SIDE, (SIDE + overhang - PLOT_RIGHT / (2 * n)) / (1 - 1 / (2 * n)))
    plot_w = PLOT_RIGHT - plot_left
    plot_h = plot_bottom - plot_top
    if min(plot_w, plot_h) < MIN_PLOT_PX:
        raise ValueError(
            "the title, category labels or question leave too little room for the plot"
        )

    # Value axis is y for vertical bars and x for horizontal bars.
    value_sizes = [_measure(fig, label, LABEL_PT) for label in bars.labels]
    extents = [w if bars.horizontal else h for w, h in value_sizes]
    span_px = plot_w if bars.horizontal else plot_h
    axis_lo, axis_hi = _value_limits(bars.values, extents, span_px, VALUE_PAD_PT * DPI / 72)

    ax = fig.add_axes([_fx(plot_left), _fy(plot_bottom), plot_w / CANVAS_W, plot_h / CANVAS_H])
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS_COLOR)
        ax.spines[side].set_linewidth(1.0)
    # Category and value text is placed by hand, so the tick machinery stays off.
    ax.set_xticks([])
    ax.set_yticks([])

    positions = list(range(n))
    bar_kwargs = {"color": BAR_COLOR, "edgecolor": "none", "linewidth": 0}
    if bars.horizontal:
        container = ax.barh(positions, bars.values, height=BAR_WIDTH, **bar_kwargs)
        ax.set_xlim(axis_lo, axis_hi)
        ax.set_ylim(n - 0.5, -0.5)  # first category at the top
    else:
        container = ax.bar(positions, bars.values, width=BAR_WIDTH, **bar_kwargs)
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(axis_lo, axis_hi)
    value_artists = ax.bar_label(
        container,
        labels=bars.labels,
        padding=VALUE_PAD_PT,
        fontsize=LABEL_PT,
        fontfamily=FONT,
        color=VALUE_COLOR,
        parse_math=False,
    )

    category_artists = []
    for i, text in enumerate(bars.categories):
        if bars.horizontal:
            x, y = plot_left - CATEGORY_GAP, plot_top + (i + 0.5) * plot_h / n
            align = {"ha": "right", "va": "center"}
        else:
            x, y = plot_left + (i + 0.5) * plot_w / n, plot_bottom + LABEL_GAP
            align = {"ha": "right" if rotation else "center", "va": "top"}
        category_artists.append(
            fig.text(
                _fx(x),
                _fy(y),
                text,
                fontsize=LABEL_PT,
                fontfamily=FONT,
                color=LABEL_COLOR,
                rotation=rotation,
                rotation_mode="anchor",
                parse_math=False,
                **align,
            )
        )

    title_artist = fig.text(
        _fx(SIDE),
        _fy(TOP),
        title_text,
        fontsize=TITLE_PT,
        fontfamily=FONT,
        color=TITLE_COLOR,
        ha="left",
        va="top",
        multialignment="left",
        parse_math=False,
    )
    footer_artist = fig.text(
        _fx(SIDE),
        _fy(CANVAS_H - FOOTER_BOTTOM),
        FOOTER_TEXT,
        fontsize=FOOTER_PT,
        fontfamily=FONT,
        color=FOOTER_COLOR,
        ha="left",
        va="bottom",
        parse_math=False,
    )
    caption_artist = None
    if caption_text is not None:
        caption_artist = fig.text(
            _fx(SIDE),
            _fy(caption_bottom),
            caption_text,
            fontsize=LABEL_PT,
            fontfamily=FONT,
            color=LABEL_COLOR,
            ha="left",
            va="bottom",
            multialignment="left",
            parse_math=False,
        )

    fig.canvas.draw()
    boxes = [_text_box(fig, "title", bars.title, title_artist, TITLE_PT)]
    boxes += [
        _text_box(fig, "category", text, artist, LABEL_PT)
        for text, artist in zip(bars.categories, category_artists)
    ]
    boxes += [
        _text_box(fig, "value", text, artist, LABEL_PT)
        for text, artist in zip(bars.labels, value_artists)
    ]
    boxes.append(_text_box(fig, "footer", FOOTER_TEXT, footer_artist, FOOTER_PT))
    if caption_artist is not None:
        boxes.append(_text_box(fig, "caption", str(question), caption_artist, LABEL_PT))

    for box in boxes:
        x0, y0, x1, y1 = box["bbox"]
        if x0 < 0 or y0 < 0 or x1 > CANVAS_W or y1 > CANVAS_H:
            raise ValueError(
                f"{box['role']} text {box['text']!r} falls outside the "
                f"{CANVAS_W} x {CANVAS_H} canvas"
            )

    png_path = os.fspath(png_path)
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    # metadata drops the Software tag. pil_kwargs drops the pHYs chunk that dpi would
    # otherwise write, so the PNG carries no metadata chunks at all.
    fig.savefig(
        png_path,
        format="png",
        dpi=DPI,
        metadata={"Software": None},
        pil_kwargs={"dpi": None},
        bbox_inches=None,
    )
    return boxes
