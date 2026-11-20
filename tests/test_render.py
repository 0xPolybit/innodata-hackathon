"""Tests for taskfactory.render.render_bar. Specs are hand-written dicts."""

from __future__ import annotations

import copy
import hashlib
import struct

import pytest
from PIL import Image

from taskfactory.render import render_bar

BAR_RGB = (0x4C, 0x72, 0xB0)
QUESTION = "Which region sold the most units?"


def make_spec(**overrides):
    spec = {
        "spec_version": 1,
        "family": "bar",
        "domain": "retail",
        "index": 0,
        "seed": 7,
        "title": "Units sold by region",
        "x_labels": ["North", "South", "East", "West"],
        "series": [
            {
                "name": "Units",
                "values": [120, 85, 143, 97],
                "labels": ["120", "85", "143", "97"],
            }
        ],
        "orientation": "vertical",
        "x_label_rotation": 0,
        "question_in_image": True,
    }
    spec.update(overrides)
    return spec


def boxes_with_role(boxes, role):
    return [box for box in boxes if box["role"] == role]


def assert_inside_canvas(boxes):
    for box in boxes:
        x0, y0, x1, y1 = box["bbox"]
        assert 0 <= x0 <= x1 <= 1200, box
        assert 0 <= y0 <= y1 <= 800, box


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
    path = tmp_path / "bar.png"
    render_bar(make_spec(), path, question=QUESTION)
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (1200, 800)


def test_same_spec_renders_identical_bytes(tmp_path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    spec = make_spec()
    boxes_a = render_bar(spec, first, question=QUESTION)
    boxes_b = render_bar(spec, second, question=QUESTION)
    sha_a = hashlib.sha256(first.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(second.read_bytes()).hexdigest()
    assert sha_a == sha_b
    assert boxes_a == boxes_b


def test_boxes_cover_title_categories_values_and_footer(tmp_path):
    spec = make_spec()
    boxes = render_bar(spec, tmp_path / "bar.png")
    assert [box["role"] for box in boxes] == (
        ["title"] + ["category"] * 4 + ["value"] * 4 + ["footer"]
    )
    assert boxes[0]["text"] == spec["title"]
    assert [b["text"] for b in boxes_with_role(boxes, "category")] == spec["x_labels"]
    assert [b["text"] for b in boxes_with_role(boxes, "value")] == spec["series"][0]["labels"]
    assert boxes[-1]["text"] == "Synthetic data"


def test_question_is_printed_only_when_question_in_image_is_true(tmp_path):
    boxes = render_bar(make_spec(question_in_image=True), tmp_path / "on.png", question=QUESTION)
    captions = boxes_with_role(boxes, "caption")
    assert [c["text"] for c in captions] == [QUESTION]
    caption = captions[0]
    footer = boxes_with_role(boxes, "footer")[0]
    assert boxes[-1] is caption  # captions come last in the list
    assert caption["bbox"][3] <= footer["bbox"][1]  # caption sits above the footer
    assert abs(caption["bbox"][0] - 40) <= 1  # left-aligned at x = 40

    off = render_bar(make_spec(question_in_image=False), tmp_path / "off.png", question=QUESTION)
    assert boxes_with_role(off, "caption") == []

    no_question = render_bar(make_spec(question_in_image=True), tmp_path / "none.png")
    assert boxes_with_role(no_question, "caption") == []


def test_text_sizes_are_fixed_and_at_least_9px_tall(tmp_path):
    boxes = render_bar(make_spec(), tmp_path / "bar.png", question=QUESTION)
    sizes = {box["role"]: box["font_px"] for box in boxes}
    assert sizes == {"title": 31, "category": 19, "value": 19, "footer": 14, "caption": 19}
    for box in boxes:
        x0, y0, x1, y1 = box["bbox"]
        assert y1 - y0 >= 9, box
        assert box["font_px"] >= 9, box


@pytest.mark.parametrize(
    "orientation, rotation",
    [("vertical", 0), ("vertical", 30), ("horizontal", 0), ("horizontal", 30)],
)
def test_every_box_lies_inside_canvas(tmp_path, orientation, rotation):
    spec = make_spec(orientation=orientation, x_label_rotation=rotation)
    boxes = render_bar(spec, tmp_path / "bar.png", question=QUESTION)
    assert_inside_canvas(boxes)


def test_long_category_labels_fit_when_rotated(tmp_path):
    categories = [
        "Northern metropolitan region",
        "Southern coastal region",
        "Eastern highland region",
        "Western plains region",
    ]
    boxes = render_bar(make_spec(x_labels=categories, x_label_rotation=30), tmp_path / "rot.png")
    assert_inside_canvas(boxes)
    assert [b["text"] for b in boxes_with_role(boxes, "category")] == categories


def test_long_title_and_question_wrap_inside_canvas(tmp_path):
    short_title = render_bar(make_spec(), tmp_path / "short.png")[0]
    title = "Quarterly units sold by region across every product line in the catalogue " * 2
    question = (
        "Which region sold the most units in the third quarter after the spring promotion ended? "
        * 2
    )
    boxes = render_bar(
        make_spec(title=title.strip()), tmp_path / "long.png", question=question.strip()
    )
    assert_inside_canvas(boxes)
    title_box = boxes_with_role(boxes, "title")[0]
    assert title_box["text"] == title.strip()
    assert (title_box["bbox"][3] - title_box["bbox"][1]) > (
        short_title["bbox"][3] - short_title["bbox"][1]
    )
    assert boxes_with_role(boxes, "caption")[0]["text"] == question.strip()


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_negative_and_zero_values_fit_on_canvas(tmp_path, orientation):
    labels = ["-40", "25", "0", "60"]
    spec = make_spec(
        orientation=orientation,
        series=[{"name": "delta", "values": [-40, 25, 0, 60], "labels": labels}],
    )
    boxes = render_bar(spec, tmp_path / "bar.png")
    assert_inside_canvas(boxes)
    assert [b["text"] for b in boxes_with_role(boxes, "value")] == labels


def test_all_zero_values_render(tmp_path):
    spec = make_spec(series=[{"name": "z", "values": [0, 0], "labels": ["0", "0"]}], x_labels=["A", "B"])
    boxes = render_bar(spec, tmp_path / "zero.png")
    assert_inside_canvas(boxes)


def test_bars_are_drawn_in_the_fixed_colour(tmp_path):
    path = tmp_path / "bar.png"
    render_bar(make_spec(), path)
    with Image.open(path) as img:
        counts = {colour: n for n, colour in img.convert("RGB").getcolors(maxcolors=1200 * 800)}
    assert counts.get(BAR_RGB, 0) > 5000


def test_bars_keep_the_given_order_and_are_not_sorted(tmp_path):
    spec = make_spec(
        x_labels=["A", "B", "C", "D"],
        series=[{"name": "Units", "values": [50, 10, 90, 30], "labels": ["50", "10", "90", "30"]}],
    )
    boxes = render_bar(spec, tmp_path / "bar.png")
    values = boxes_with_role(boxes, "value")
    centres = [(box["bbox"][0] + box["bbox"][2]) / 2 for box in values]
    assert centres == sorted(centres)
    assert [box["text"] for box in values] == ["50", "10", "90", "30"]


def test_horizontal_bars_run_top_to_bottom_in_given_order(tmp_path):
    boxes = render_bar(make_spec(orientation="horizontal"), tmp_path / "bar.png")
    categories = boxes_with_role(boxes, "category")
    values = boxes_with_role(boxes, "value")
    tops = [box["bbox"][1] for box in categories]
    assert tops == sorted(tops) and len(set(tops)) == len(tops)
    for category, value in zip(categories, values):
        category_mid = (category["bbox"][1] + category["bbox"][3]) / 2
        value_mid = (value["bbox"][1] + value["bbox"][3]) / 2
        assert abs(category_mid - value_mid) <= 3
        assert value["bbox"][0] > category["bbox"][2]  # value labels sit right of the names


def test_png_has_no_software_or_text_metadata(tmp_path):
    path = tmp_path / "bar.png"
    render_bar(make_spec(), path, question=QUESTION)
    with Image.open(path) as img:
        assert "Software" not in img.info
        assert img.info == {}  # no dpi (pHYs) either: nothing but pixels
    assert not {"tEXt", "zTXt", "iTXt", "pHYs"} & set(png_chunk_types(path))


def test_dollar_signs_in_labels_are_printed_as_given(tmp_path):
    labels = ["$1,200 - $1,500", "$2 and $3", "$4", "$5"]
    series = [{"name": "Revenue", "values": [1200, 2000, 4000, 5000], "labels": labels}]
    spec = make_spec(series=series)
    boxes = render_bar(spec, tmp_path / "bar.png")
    assert [b["text"] for b in boxes_with_role(boxes, "value")] == labels
    assert_inside_canvas(boxes)


def test_dollar_signs_are_not_read_as_maths(tmp_path):
    # Mathtext would drop both "$" signs and the spaces, so the literal label is wider.
    def first_value_width(label):
        labels = [label, "2", "3", "4"]
        spec = make_spec(series=[{"name": "x", "values": [1, 2, 3, 4], "labels": labels}])
        box = boxes_with_role(render_bar(spec, tmp_path / "w.png"), "value")[0]
        return box["bbox"][2] - box["bbox"][0]

    assert first_value_width("$12 and $34") > first_value_width("12 and 34") + 10


def test_input_spec_is_not_modified(tmp_path):
    spec = make_spec()
    before = copy.deepcopy(spec)
    render_bar(spec, tmp_path / "bar.png", question=QUESTION)
    assert spec == before


def test_missing_output_folder_is_created(tmp_path):
    path = tmp_path / "nested" / "dir" / "bar.png"
    render_bar(make_spec(), path)
    assert path.exists()


def test_line_family_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        render_bar(make_spec(family="line"), tmp_path / "bar.png")


def test_two_series_are_rejected(tmp_path):
    spec = make_spec()
    spec["series"].append(dict(spec["series"][0], name="Other"))
    with pytest.raises(ValueError):
        render_bar(spec, tmp_path / "bar.png")


@pytest.mark.parametrize("field", ["values", "labels"])
def test_series_length_mismatch_is_rejected(tmp_path, field):
    spec = make_spec()
    spec["series"][0][field] = spec["series"][0][field][:-1]
    with pytest.raises(ValueError):
        render_bar(spec, tmp_path / "bar.png")


def test_x_labels_length_mismatch_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        render_bar(make_spec(x_labels=["North", "South"]), tmp_path / "bar.png")


@pytest.mark.parametrize(
    "overrides",
    [
        {"orientation": "diagonal"},
        {"x_label_rotation": 45},
        {"spec_version": 2},
        {"x_labels": [], "series": [{"name": "Units", "values": [], "labels": []}]},
        {"series": [{"name": "Units", "values": [1, float("nan"), 3, 4], "labels": list("abcd")}]},
    ],
)
def test_invalid_options_are_rejected(tmp_path, overrides):
    with pytest.raises(ValueError):
        render_bar(make_spec(**overrides), tmp_path / "bar.png")


def test_empty_title_question_and_labels_render(tmp_path):
    spec = make_spec(
        title="",
        x_labels=["", "South", "East", "West"],
        series=[{"name": "Units", "values": [120, 85, 143, 97], "labels": ["", "85", "143", "97"]}],
    )
    boxes = render_bar(spec, tmp_path / "bar.png", question="   ")
    assert_inside_canvas(boxes)
    assert boxes_with_role(boxes, "title")[0]["text"] == ""
    assert boxes_with_role(boxes, "caption")[0]["text"] == "   "


def test_unbreakable_text_wider_than_canvas_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        render_bar(make_spec(title="X" * 200), tmp_path / "bar.png")
