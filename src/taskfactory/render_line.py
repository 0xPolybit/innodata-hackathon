"""Line chart renderer: one line-family spec in, one 1200 x 800 PNG out.

``render_line`` uses the canvas, fonts, margins and text-box format of
``render_bar``, so the two families look like one set. It also returns the box
of every text element it draws, so callers can check layout without reading
pixels. Each category box carries an ``anchor``, the exact pixel where that
category's data point meets the x axis, so a reader need not infer it from a
rotated label. The legend sits in a strip above the plot, so it cannot cover
data. The figure is built with ``Figure`` and ``FigureCanvasAgg`` instead of
pyplot, so no global state is touched and one spec always produces the same PNG
bytes.
"""

from __future__ import annotations

import math
import numbers
import os
from pathlib import Path
from typing import Any, NamedTuple

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox

from taskfactory.render import (
    AXIS_COLOR,
    BLOCK_GAP,
    CANVAS_H,
    CANVAS_W,
    CAPTION_GAP,
    DPI,
    FONT,
    FOOTER_BOTTOM,
    FOOTER_COLOR,
    FOOTER_PT,
    FOOTER_TEXT,
    LABEL_COLOR,
    LABEL_GAP,
    LABEL_PT,
    MIN_PLOT_PX,
    PLOT_RIGHT,
    SIDE,
    TITLE_COLOR,
    TITLE_GAP,
    TITLE_PT,
    TOP,
    _fx,
    _fy,
    _measure,
    _text_box,
    _wrap,
)

__all__ = ["render_line"]

LINE_COLORS = ("#4C72B0", "#DD8452", "#55A868")  # series 1, 2, 3 in the given order
LINE_WIDTH = 2.5
MARKER_SIZE = 6  # circle markers
LEGEND_PT = LABEL_PT
LEGEND_EDGE = "#CCCCCC"
DATA_PAD = 0.08  # empty share of the value range below the lowest value and above the highest
LEGEND_STRIP_PX = 48  # height reserved between the title block and the top of the plot
LEGEND_GAP_PX = 8  # gap between the legend frame's bottom edge and the top of the plot


class _Lines(NamedTuple):
    title: str
    categories: list[str]
    names: list[str]
    values: list[list[int]]
    rotation: int


def _require(mapping: dict[str, Any], key: str, owner: str = "spec") -> Any:
    if key not in mapping:
        raise ValueError(f"{owner} is missing {key!r}")
    return mapping[key]


def _parse(spec: dict[str, Any]) -> _Lines:
    """Check a line spec and return the fields the renderer draws."""
    if spec.get("spec_version") != 1:
        raise ValueError(f"spec_version must be 1, not {spec.get('spec_version')!r}")
    if spec.get("family") != "line":
        raise ValueError(f"render_line only draws family 'line', not {spec.get('family')!r}")
    if spec.get("orientation") != "vertical":
        raise ValueError(
            f"a line chart needs orientation 'vertical', not {spec.get('orientation')!r}"
        )
    rotation = spec.get("x_label_rotation")
    if isinstance(rotation, bool) or rotation not in (0, 30):
        raise ValueError(f"x_label_rotation must be 0 or 30, not {rotation!r}")

    x_labels = _require(spec, "x_labels")
    if not isinstance(x_labels, (list, tuple)) or len(x_labels) < 2:
        raise ValueError("a line spec needs a list of at least 2 x labels")
    categories = [str(c) for c in x_labels]

    series = _require(spec, "series")
    if not isinstance(series, (list, tuple)):
        raise ValueError("series must be a list")
    if not 2 <= len(series) <= 3:
        raise ValueError(f"a line spec needs 2 or 3 series, not {len(series)}")

    names: list[str] = []
    values: list[list[int]] = []
    for entry in series:
        if not isinstance(entry, dict):
            raise ValueError("each series must be a dict with 'name' and 'values'")
        name = str(_require(entry, "name", "a series"))
        raw = _require(entry, "values", f"series {name!r}")
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"series {name!r} needs a list of values")
        if len(raw) != len(categories):
            raise ValueError(
                f"series {name!r} has {len(raw)} values for {len(categories)} x labels"
            )
        for v in raw:
            if isinstance(v, bool) or not isinstance(v, numbers.Integral):
                raise ValueError(f"series {name!r} has {v!r}; values must be finite integers")
        names.append(name)
        values.append([int(v) for v in raw])

    return _Lines(
        title=str(_require(spec, "title")),
        categories=categories,
        names=names,
        values=values,
        rotation=int(rotation),
    )


def _value_limits(values: list[int]) -> tuple[float, float]:
    """Value-axis limits with ``DATA_PAD`` of the value range free past both extremes.

    The lowest value sits ``DATA_PAD`` of the range above the bottom edge, and the
    highest sits as far below the top edge, so a marker at either end stays inside
    the plot. The legend takes no room here: it has its own strip above the plot.
    """
    lo, hi = float(min(values)), float(max(values))
    span = (hi - lo) or 1.0  # all values equal: keep the axis from collapsing
    return lo - DATA_PAD * span, hi + DATA_PAD * span


def _outward(box: Bbox) -> list[int]:
    """A display box (bottom-left origin) as whole image pixels, top-left origin, rounded outward.

    Same rounding as ``render._text_box``.
    """
    return [
        math.floor(box.x0),
        math.floor(CANVAS_H - box.y1),
        math.ceil(box.x1),
        math.ceil(CANVAS_H - box.y0),
    ]


def _overlaps(a: list[int], b: list[int]) -> bool:
    """True when two boxes share an area. Boxes that only touch along an edge do not overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside_canvas(bbox: list[int]) -> bool:
    x0, y0, x1, y1 = bbox
    return x0 >= 0 and y0 >= 0 and x1 <= CANVAS_W and y1 <= CANVAS_H


def _check_legend(frame: list[int], others: list[dict[str, Any]]) -> None:
    """Refuse the image when the legend frame shares an area with any other text box."""
    if any(_overlaps(frame, box["bbox"]) for box in others):
        raise ValueError("legend overlaps")


def _check_legend_fits(frame: list[int], strip_top: int, plot_top: int) -> None:
    """Refuse the image when the legend frame is not inside its strip above the plot.

    The strip runs from the bottom of the title block down to the top of the plot,
    across the text width. A frame that rises above the strip, reaches the plot's
    top edge or runs past the margins does not fit.
    """
    x0, y0, x1, y1 = frame
    if y0 < strip_top or y1 > plot_top or x0 < SIDE or x1 > PLOT_RIGHT:
        raise ValueError("legend does not fit")


def render_line(
    spec: dict[str, Any],
    png_path: str | os.PathLike[str],
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Render a line spec to ``png_path`` and return the text boxes.

    The PNG is 1200 x 800 and has no metadata (no software tag, no dpi chunk).
    ``question`` is printed as a caption above the footer only when it is not
    None and ``spec["question_in_image"]`` is True.

    Each box is ``{"role", "text", "bbox", "font_px"}``. ``bbox`` is
    ``[x0, y0, x1, y1]`` in image pixels with the origin at the top-left.
    Boxes come in the order title, legend entries, categories, footer, caption.
    ``text`` is the string as given, even when a title or caption was wrapped.
    Each category box also has ``"anchor": [x, y]``: ``x`` is the pixel column of
    that category's data point and ``y`` the row of the x axis line, both whole
    pixels with the origin at the top-left. No other box has an anchor.

    The legend is one row centred above the plot, in a strip reserved between the
    title and the plot, so it never covers a data point.

    Raises ValueError for an unsupported family, orientation or rotation, a
    series count other than 2 or 3, a series whose length differs from
    x_labels, values that are not finite integers, a legend that overlaps other
    text or does not fit its strip (``"legend does not fit"``), or a layout that
    cannot fit on the canvas. No file is written then.
    """
    lines = _parse(spec)
    show_caption = question is not None and spec.get("question_in_image") is True
    n = len(lines.categories)
    rotation = lines.rotation
    all_values = [v for series in lines.values for v in series]

    fig = Figure(figsize=(CANVAS_W / DPI, CANVAS_H / DPI), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)  # attaches itself as fig.canvas

    # Fixed blocks: title at the top; footer at the bottom with the caption above it.
    title_text = _wrap(fig, lines.title, TITLE_PT)
    _, title_h = _measure(fig, title_text, TITLE_PT)
    _, footer_h = _measure(fig, FOOTER_TEXT, FOOTER_PT)
    footer_top = CANVAS_H - FOOTER_BOTTOM - footer_h
    caption_text: str | None = None
    caption_bottom = footer_top
    stack_top = footer_top  # top edge of the lowest block above the footer
    if show_caption:
        caption_text = _wrap(fig, str(question), LABEL_PT)
        _, caption_h = _measure(fig, caption_text, LABEL_PT)
        caption_bottom = footer_top - CAPTION_GAP
        stack_top = caption_bottom - caption_h
    content_bottom = stack_top - BLOCK_GAP
    # The legend strip starts below the title block and is reserved above the plot.
    strip_top = TOP + title_h + TITLE_GAP
    plot_top = strip_top + LEGEND_STRIP_PX

    # Plot area. Category i is centred in slot i, as in render_bar, so the left
    # edge depends on the first and last labels.
    cat_sizes = [_measure(fig, c, LABEL_PT, rotation) for c in lines.categories]
    plot_bottom = content_bottom - LABEL_GAP - max(h for _, h in cat_sizes)
    # Rotated labels extend left of their anchor by their full width; upright labels
    # extend half a width each way. Solve (plot_left + slot / 2) - overhang >= SIDE.
    overhang = max(w if rotation else w / 2 for w, _ in cat_sizes)
    plot_left = max(SIDE, (SIDE + overhang - PLOT_RIGHT / (2 * n)) / (1 - 1 / (2 * n)))
    plot_w = PLOT_RIGHT - plot_left
    plot_h = plot_bottom - plot_top
    if min(plot_w, plot_h) < MIN_PLOT_PX:
        raise ValueError(
            "the title, category labels or question leave too little room for the plot"
        )

    ax = fig.add_axes([_fx(plot_left), _fy(plot_bottom), plot_w / CANVAS_W, plot_h / CANVAS_H])
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS_COLOR)
        ax.spines[side].set_linewidth(1.0)
    # Category text is placed by hand, so the tick machinery stays off.
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlim(-0.5, n - 0.5)  # point i sits at the centre of slot i
    ax.set_ylim(*_value_limits(all_values))

    positions = list(range(n))
    handles = [
        ax.plot(
            positions,
            values,
            color=colour,
            linewidth=LINE_WIDTH,
            marker="o",
            markersize=MARKER_SIZE,
        )[0]
        for values, colour in zip(lines.values, LINE_COLORS)
    ]

    # One row, centred on the plot, its bottom edge LEGEND_GAP_PX above the plot top.
    # The anchor is in figure coordinates, so the legend sits outside the axes.
    legend = ax.legend(
        handles,
        lines.names,
        loc="lower center",
        bbox_to_anchor=(_fx(plot_left + plot_w / 2), _fy(plot_top - LEGEND_GAP_PX)),
        bbox_transform=fig.transFigure,
        ncol=len(lines.names),
        borderaxespad=0.0,
        prop={"family": FONT, "size": LEGEND_PT},
        facecolor="white",
        edgecolor=LEGEND_EDGE,
        framealpha=1.0,
        fancybox=False,
    )
    for text in legend.get_texts():
        text.set_parse_math(False)  # a "$" in a series name is printed, not read as maths
        text.set_color(LABEL_COLOR)

    category_artists = []
    anchors = []
    for i, text in enumerate(lines.categories):
        data_x = plot_left + (i + 0.5) * plot_w / n  # the data point's x, image pixels
        category_artists.append(
            fig.text(
                _fx(data_x),
                _fy(plot_bottom + LABEL_GAP),
                text,
                fontsize=LABEL_PT,
                fontfamily=FONT,
                color=LABEL_COLOR,
                rotation=rotation,
                rotation_mode="anchor",
                ha="right" if rotation else "center",
                va="top",
                parse_math=False,
            )
        )
        anchors.append([round(data_x), round(plot_bottom)])
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
    renderer = fig.canvas.get_renderer()
    boxes = [_text_box(fig, "title", lines.title, title_artist, TITLE_PT)]
    boxes += [
        _text_box(fig, "legend", name, text, LEGEND_PT)
        for name, text in zip(lines.names, legend.get_texts())
    ]
    category_boxes = [
        _text_box(fig, "category", text, artist, LABEL_PT)
        for text, artist in zip(lines.categories, category_artists)
    ]
    for box, anchor in zip(category_boxes, anchors):
        box["anchor"] = anchor
    boxes += category_boxes
    boxes.append(_text_box(fig, "footer", FOOTER_TEXT, footer_artist, FOOTER_PT))
    if caption_artist is not None:
        boxes.append(_text_box(fig, "caption", str(question), caption_artist, LABEL_PT))

    frame = _outward(legend.get_window_extent(renderer))
    _check_legend_fits(frame, strip_top, plot_top)
    _check_legend(frame, [box for box in boxes if box["role"] != "legend"])
    for box in boxes:
        if not _inside_canvas(box["bbox"]):
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
