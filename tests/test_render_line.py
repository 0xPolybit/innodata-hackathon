"""Tests for taskfactory.render_line.render_line. Specs are hand-written dicts."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
from itertools import combinations
from pathlib import Path

import pytest
from matplotlib.figure import Figure
from PIL import Image

import taskfactory.render_line as render_line_module
from taskfactory.render import CANVAS_H
from taskfactory.render_line import (
    _check_legend,
    _check_legend_fits,
    _outward,
    _value_limits,
    render_line,
)

QUESTION = "Which campus grew fastest between 2017 and 2024?"
YEARS = ["2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"]
COLOURS = [(0x4C, 0x72, 0xB0), (0xDD, 0x84, 0x52), (0x55, 0xA8, 0x68)]
EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "out" / "examples" / "line_example.png"
EXAMPLE_QUESTION = "Which campus had the highest enrolment in 2024?"


def make_series(name, values):
    values = list(values)
    return {"name": name, "values": values, "labels": [str(v) for v in values]}


def three_series():
    return [
        make_series("North campus", [120, 128, 135, 131, 150, 162, 171, 169]),
        make_series("South campus", [95, 99, 104, 118, 115, 121, 127, 133]),
        make_series("Online", [60, 72, 88, 110, 131, 149, 170, 192]),
    ]


def make_spec(**overrides):
    spec = {
        "spec_version": 1,
        "family": "line",
        "domain": "education",
        "index": 0,
        "seed": 7,
        "title": "Enrolment by campus",
        "x_labels": list(YEARS),
        "series": three_series()[:2],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }
    spec.update(overrides)
    return spec


def spec_with_shape(years, series_count, rotation=0):
    labels = [str(2015 + i) for i in range(years)]
    series = [
        make_series(f"Series {k + 1}", [100 + (i * (k + 3) * 7) % 53 for i in range(years)])
        for k in range(series_count)
    ]
    return make_spec(x_labels=labels, series=series, x_label_rotation=rotation)


def boxes_with_role(boxes, role):
    return [box for box in boxes if box["role"] == role]


def assert_inside_canvas(boxes):
    for box in boxes:
        x0, y0, x1, y1 = box["bbox"]
        assert 0 <= x0 <= x1 <= 1200, box
        assert 0 <= y0 <= y1 <= 800, box


def boxes_overlap(a, b):
    ax0, ay0, ax1, ay1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def png_chunk_types(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    kinds, pos = [], 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kinds.append(data[pos + 4 : pos + 8].decode("ascii"))
        pos += 12 + length
    return kinds


def test_png_is_exactly_1200_by_800(tmp_path):
    path = tmp_path / "line.png"
    render_line(make_spec(), path, question=QUESTION)
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (1200, 800)


def test_same_spec_renders_identical_bytes(tmp_path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    spec = make_spec(series=three_series())
    boxes_a = render_line(spec, first, question=QUESTION)
    boxes_b = render_line(spec, second, question=QUESTION)
    sha_a = hashlib.sha256(first.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(second.read_bytes()).hexdigest()
    assert sha_a == sha_b
    assert boxes_a == boxes_b


def test_boxes_are_title_legend_categories_and_footer_in_order(tmp_path):
    spec = make_spec()
    boxes = render_line(spec, tmp_path / "line.png")
    assert [box["role"] for box in boxes] == (
        ["title"] + ["legend"] * 2 + ["category"] * 8 + ["footer"]
    )
    assert boxes[0]["text"] == spec["title"]
    assert [b["text"] for b in boxes_with_role(boxes, "legend")] == [
        "North campus",
        "South campus",
    ]
    assert [b["text"] for b in boxes_with_role(boxes, "category")] == YEARS
    assert boxes[-1]["text"] == "Synthetic data"


def test_caption_is_drawn_only_when_question_in_image_is_true_and_a_question_is_given(tmp_path):
    boxes = render_line(make_spec(question_in_image=True), tmp_path / "on.png", question=QUESTION)
    captions = boxes_with_role(boxes, "caption")
    assert [c["text"] for c in captions] == [QUESTION]
    caption = captions[0]
    footer = boxes_with_role(boxes, "footer")[0]
    assert boxes[-1] is caption  # captions come last in the list
    assert caption["bbox"][3] <= footer["bbox"][1]  # caption sits above the footer
    assert abs(caption["bbox"][0] - 40) <= 1  # left-aligned at x = 40

    off = render_line(make_spec(question_in_image=False), tmp_path / "off.png", question=QUESTION)
    assert boxes_with_role(off, "caption") == []

    no_question = render_line(make_spec(question_in_image=True), tmp_path / "none.png")
    assert boxes_with_role(no_question, "caption") == []


def test_text_sizes_are_fixed(tmp_path):
    boxes = render_line(make_spec(), tmp_path / "line.png", question=QUESTION)
    sizes = {box["role"]: box["font_px"] for box in boxes}
    assert sizes == {"title": 31, "legend": 19, "category": 19, "footer": 14, "caption": 19}


@pytest.mark.parametrize("years, series_count", [(6, 2), (10, 3), (8, 3)])
@pytest.mark.parametrize("rotation", [0, 30])
def test_every_box_lies_inside_canvas_and_no_two_boxes_overlap(
    tmp_path, years, series_count, rotation
):
    spec = spec_with_shape(years, series_count, rotation)
    boxes = render_line(spec, tmp_path / "line.png", question=QUESTION)
    assert_inside_canvas(boxes)
    for a, b in combinations(boxes, 2):
        assert not boxes_overlap(a, b), (a, b)


@pytest.fixture
def axes_made_by_render_line(monkeypatch):
    """Record each axes that render_line creates, so a test can read the geometry it drew."""
    made = []
    add_axes = Figure.add_axes

    def record(self, *args, **kwargs):
        ax = add_axes(self, *args, **kwargs)
        made.append(ax)
        return ax

    monkeypatch.setattr(Figure, "add_axes", record)
    return made


def plot_edges(ax):
    """The plot's top and bottom edges in image pixels, origin top-left."""
    box = ax.get_window_extent(ax.figure.canvas.get_renderer())
    return CANVAS_H - box.y1, CANVAS_H - box.y0


@pytest.mark.parametrize("rotation", [0, 30])
def test_category_boxes_carry_the_pixel_of_their_data_point(
    tmp_path, axes_made_by_render_line, rotation
):
    spec = make_spec(x_label_rotation=rotation)
    boxes = render_line(spec, tmp_path / "line.png", question=QUESTION)
    (ax,) = axes_made_by_render_line
    _, axis_y = plot_edges(ax)
    categories = boxes_with_role(boxes, "category")
    assert [box["text"] for box in categories] == YEARS
    for i, box in enumerate(categories):
        data_x, _ = ax.transData.transform((i, 0.0))
        assert box["anchor"] == [int(round(float(data_x))), int(round(axis_y))]
    assert all("anchor" not in box for box in boxes if box["role"] != "category")


def test_legend_is_one_row_centred_on_the_plot_in_the_order_given(
    tmp_path, axes_made_by_render_line
):
    boxes = render_line(make_spec(series=three_series()), tmp_path / "line.png", question=QUESTION)
    (ax,) = axes_made_by_render_line
    renderer = ax.figure.canvas.get_renderer()
    frame = _outward(ax.get_legend().get_window_extent(renderer))
    plot = ax.get_window_extent(renderer)
    assert abs((frame[0] + frame[2]) / 2 - (plot.x0 + plot.x1) / 2) <= 1
    entries = boxes_with_role(boxes, "legend")
    assert [entry["text"] for entry in entries] == ["North campus", "South campus", "Online"]
    tops = [entry["bbox"][1] for entry in entries]
    assert max(tops) - min(tops) <= 1  # one row
    lefts = [entry["bbox"][0] for entry in entries]
    assert lefts == sorted(lefts)  # left to right, in the order given


@pytest.mark.parametrize("rotation", [0, 30])
def test_legend_box_lies_above_the_plot_and_no_data_point_is_above_its_bottom_edge(
    tmp_path, axes_made_by_render_line, rotation
):
    spec = make_spec(series=three_series(), x_label_rotation=rotation)
    boxes = render_line(spec, tmp_path / "line.png", question=QUESTION)
    (ax,) = axes_made_by_render_line
    frame = _outward(ax.get_legend().get_window_extent(ax.figure.canvas.get_renderer()))
    plot_top, _ = plot_edges(ax)
    title = boxes_with_role(boxes, "title")[0]
    assert frame[3] < plot_top  # bottom of the legend box is above the top of the plot
    assert frame[1] > title["bbox"][3]  # and the legend sits below the title
    for entry in spec["series"]:
        for i, value in enumerate(entry["values"]):
            _, display_y = ax.transData.transform((i, value))
            point_y = CANVAS_H - display_y  # image coordinates, origin top-left
            assert point_y > frame[3], (entry["name"], i)


def test_points_have_no_value_labels(tmp_path):
    boxes = render_line(make_spec(series=three_series()), tmp_path / "line.png", question=QUESTION)
    roles = {box["role"] for box in boxes}
    assert roles <= {"title", "legend", "category", "footer", "caption"}


def test_series_are_drawn_in_the_fixed_colours(tmp_path):
    path = tmp_path / "line.png"
    render_line(make_spec(series=three_series()), path, question=QUESTION)
    with Image.open(path) as img:
        counts = {colour: n for n, colour in img.convert("RGB").getcolors(maxcolors=1200 * 800)}
    for rgb in COLOURS:
        assert counts.get(rgb, 0) > 1000, rgb


def test_legend_names_are_printed_as_given_even_with_dollar_signs(tmp_path):
    # Mathtext would drop both "$" signs and the spaces, so the literal name is wider.
    def first_name_width(name):
        series = [make_series(name, range(1, 9)), make_series("Other", range(2, 10))]
        boxes = render_line(make_spec(series=series), tmp_path / "w.png")
        legend = boxes_with_role(boxes, "legend")
        assert legend[0]["text"] == name
        return legend[0]["bbox"][2] - legend[0]["bbox"][0]

    assert first_name_width("$12 and $34") > first_name_width("12 and 34") + 10


def test_long_category_labels_fit_when_rotated(tmp_path):
    categories = [
        "Northern metropolitan campus",
        "Southern coastal campus",
        "Eastern highland campus",
        "Western plains campus",
        "Central river campus",
        "Island campus",
        "Hill campus",
        "Harbour campus",
    ]
    boxes = render_line(make_spec(x_labels=categories, x_label_rotation=30), tmp_path / "rot.png")
    assert_inside_canvas(boxes)
    assert [b["text"] for b in boxes_with_role(boxes, "category")] == categories


def test_long_title_and_question_wrap_inside_canvas(tmp_path):
    short_title = render_line(make_spec(), tmp_path / "short.png")[0]
    title = (
        "Quarterly enrolment by campus across every faculty and intake in the catalogue " * 2
    ).strip()
    question = (
        "Which campus grew fastest between the spring intake and the autumn intake "
        "after the new programmes started? " * 2
    ).strip()
    boxes = render_line(make_spec(title=title), tmp_path / "long.png", question=question)
    assert_inside_canvas(boxes)
    title_box = boxes_with_role(boxes, "title")[0]
    assert title_box["text"] == title
    assert (title_box["bbox"][3] - title_box["bbox"][1]) > (
        short_title["bbox"][3] - short_title["bbox"][1]
    )
    assert boxes_with_role(boxes, "caption")[0]["text"] == question


def test_legend_frame_that_touches_another_box_is_refused():
    title = {"role": "title", "text": "T", "bbox": [40, 26, 400, 60], "font_px": 31}
    with pytest.raises(ValueError, match="legend overlaps"):
        _check_legend([350, 50, 600, 200], [title])
    _check_legend([400, 50, 600, 200], [title])  # sharing only an edge is allowed


def test_legend_that_does_not_fit_its_strip_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(render_line_module, "LEGEND_STRIP_PX", 12)
    path = tmp_path / "line.png"
    with pytest.raises(ValueError, match="legend does not fit"):
        render_line(make_spec(), path)
    assert not path.exists()


def test_legend_row_wider_than_the_text_width_is_refused(tmp_path):
    series = [make_series("Campus " + "x" * 120, range(1, 9)), make_series("Other", range(2, 10))]
    path = tmp_path / "line.png"
    with pytest.raises(ValueError, match="legend does not fit"):
        render_line(make_spec(series=series), path)
    assert not path.exists()


def test_legend_frame_must_sit_inside_its_strip_above_the_plot():
    _check_legend_fits([100, 60, 300, 90], strip_top=60, plot_top=100)  # inside: accepted
    with pytest.raises(ValueError, match="legend does not fit"):
        _check_legend_fits([100, 55, 300, 90], strip_top=60, plot_top=100)  # above the strip
    with pytest.raises(ValueError, match="legend does not fit"):
        _check_legend_fits([100, 60, 300, 101], strip_top=60, plot_top=100)  # reaches the plot


def test_series_missing_a_name_or_values_gets_a_clear_message(tmp_path):
    spec = make_spec()
    del spec["series"][1]["name"]
    with pytest.raises(ValueError, match="a series is missing 'name'"):
        render_line(spec, tmp_path / "line.png")
    spec = make_spec()
    del spec["series"][0]["values"]
    with pytest.raises(ValueError, match="series 'North campus' is missing 'values'"):
        render_line(spec, tmp_path / "line.png")


def test_value_axis_pads_both_ends_of_the_data_by_the_same_share():
    bottom, top = _value_limits([10, 40, 25])
    pad = render_line_module.DATA_PAD * 30
    assert math.isclose(bottom, 10 - pad)
    assert math.isclose(top, 40 + pad)


def test_value_axis_does_not_collapse_when_all_values_are_equal():
    bottom, top = _value_limits([7, 7])
    assert bottom < 7 < top


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"family": "bar"}, "family"),
        ({"spec_version": 2}, "spec_version"),
        ({"orientation": "horizontal"}, "vertical"),
        ({"x_label_rotation": 45}, "rotation"),
        ({"series": three_series()[:1]}, "2 or 3 series"),
        ({"series": three_series() + [make_series("Extra", [1] * 8)]}, "2 or 3 series"),
        ({"x_labels": ["2017"], "series": [make_series("a", [1]), make_series("b", [2])]}, "2 x labels"),
    ],
)
def test_invalid_specs_are_rejected(tmp_path, overrides, message):
    path = tmp_path / "line.png"
    with pytest.raises(ValueError, match=message):
        render_line(make_spec(**overrides), path)
    assert not path.exists()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1.5, "12", None, True])
def test_values_must_be_finite_integers(tmp_path, bad):
    spec = make_spec()
    spec["series"][1]["values"][3] = bad
    with pytest.raises(ValueError, match="finite integers"):
        render_line(spec, tmp_path / "line.png")


@pytest.mark.parametrize("which", ["values", "x_labels"])
def test_length_mismatch_is_rejected(tmp_path, which):
    spec = make_spec()
    if which == "values":
        spec["series"][1]["values"] = spec["series"][1]["values"][:-1]
    else:
        spec["x_labels"] = spec["x_labels"][:-1]
    with pytest.raises(ValueError, match="x labels"):
        render_line(spec, tmp_path / "line.png")


def test_png_has_no_software_or_text_metadata(tmp_path):
    path = tmp_path / "line.png"
    render_line(make_spec(), path, question=QUESTION)
    with Image.open(path) as img:
        assert "Software" not in img.info
        assert img.info == {}  # no dpi (pHYs) either: nothing but pixels
    assert not {"tEXt", "zTXt", "iTXt", "pHYs"} & set(png_chunk_types(path))


def test_same_spec_gives_identical_pngs_when_rendered_in_a_new_folder(tmp_path):
    spec = make_spec(series=three_series())
    render_line(spec, tmp_path / "a" / "line.png", question=QUESTION)
    render_line(spec, tmp_path / "b" / "line.png", question=QUESTION)
    assert (tmp_path / "a" / "line.png").read_bytes() == (tmp_path / "b" / "line.png").read_bytes()


def test_input_spec_is_not_modified(tmp_path):
    spec = make_spec(series=three_series())
    before = copy.deepcopy(spec)
    render_line(spec, tmp_path / "line.png", question=QUESTION)
    assert spec == before


def test_missing_output_folder_is_created(tmp_path):
    path = tmp_path / "nested" / "dir" / "line.png"
    render_line(make_spec(), path)
    assert path.exists()


def test_unbreakable_text_wider_than_canvas_is_rejected(tmp_path):
    path = tmp_path / "line.png"
    with pytest.raises(ValueError):
        render_line(make_spec(title="X" * 200), path)
    assert not path.exists()


def example_spec():
    return {
        "spec_version": 1,
        "family": "line",
        "domain": "education",
        "index": 0,
        "seed": 11,
        "title": "Enrolment by campus, 2017 to 2024",
        "x_labels": list(YEARS),
        "series": [
            make_series("North campus", [210, 205, 198, 190, 184, 171, 165, 158]),
            make_series("South campus", [150, 158, 166, 172, 181, 190, 199, 207]),
            make_series("Online", [90, 105, 121, 138, 160, 183, 207, 236]),
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }


def test_example_png_is_written_to_out_examples():
    boxes = render_line(example_spec(), EXAMPLE_PATH, question=EXAMPLE_QUESTION)
    assert EXAMPLE_PATH.is_file()
    with Image.open(EXAMPLE_PATH) as img:
        assert img.size == (1200, 800)
    assert_inside_canvas(boxes)
    assert len(boxes_with_role(boxes, "legend")) == 3
    assert len(boxes_with_role(boxes, "category")) == 8


if __name__ == "__main__":
    print(json.dumps(render_line(example_spec(), EXAMPLE_PATH, question=EXAMPLE_QUESTION), indent=2))
