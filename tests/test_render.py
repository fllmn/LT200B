import numpy as np
from PIL import Image

from lt200b.geometry import DEFAULT_GEOMETRY
from lt200b.render import (
    ImageAsset,
    LabelRenderer,
    TextAsset,
    _split_runs,
)

renderer = LabelRenderer()


def ink_height_mm(image: Image.Image) -> float:
    array = np.array(image.convert("L"))
    rows = np.flatnonzero((array < 128).any(axis=1))
    assert len(rows) > 0, "expected ink in the rendered label"
    return float(rows[-1] - rows[0] + 1) / (
        DEFAULT_GEOMETRY.dots_per_mm * DEFAULT_GEOMETRY.render_scale
    )


def test_text_height_matches_requested_size() -> None:
    for size_mm in (2, 3, 4, 5):
        label = renderer.render_text("Smörgåsbord", size_mm)
        assert abs(ink_height_mm(label) - size_mm) <= 0.3, f"{size_mm} mm text height"


def test_oversized_request_is_clamped_to_print_span() -> None:
    label = renderer.render_text("Test", 12.0)
    assert ink_height_mm(label) <= DEFAULT_GEOMETRY.print_span_mm + 0.3


def test_emoji_fallback_renders_distinct_glyphs() -> None:
    renders = [
        np.array(renderer.render_text(emoji, 5).convert("L").resize((64, 64)))
        for emoji in ("🙂", "❤", "😀")
    ]
    for first, second in zip(renders, renders[1:]):
        assert not (first == second).all()


def test_emoji_and_text_share_the_line() -> None:
    label = renderer.render_text("a🙂b", 5)
    array = np.array(label.convert("L"))
    columns = np.flatnonzero((array < 128).any(axis=0))
    # the gap between text and emoji must stay small (emoji side bearing);
    # a missing glyph or layout bug would leave a wide empty stretch
    gaps = 0
    longest = 0
    for column in range(columns[0], columns[-1]):
        if not (array[:, column] < 128).any():
            gaps += 1
            longest = max(longest, gaps)
        else:
            gaps = 0
    assert longest < 0.2 * DEFAULT_GEOMETRY.canvas_height_px


def test_split_runs_groups_emoji() -> None:
    assert _split_runs("Hej 🙂") == [(False, "Hej "), (True, "🙂")]
    # variation selectors and zero-width joiners are absorbed
    assert _split_runs("\U0001F44D\u200d\U0001F468\u200d\U0001F469\uFE0F") == [
        (True, "\U0001F44D\U0001F468\U0001F469")
    ]


def test_multi_line_text_fits_the_print_span() -> None:
    label = renderer.render_text("rad1\nrad2\nrad3", 5)
    assert label.height == DEFAULT_GEOMETRY.canvas_height_px
    assert ink_height_mm(label) <= DEFAULT_GEOMETRY.print_span_mm + 0.3


def test_label_layout_orders_assets_with_gaps() -> None:
    icon = Image.new("RGB", (64, 64), "black")
    label = renderer.render_label([
        TextAsset(text="A", font_size_mm=4),
        ImageAsset(image=icon),
        TextAsset(text="B", font_size_mm=4),
    ])
    assert label.height == DEFAULT_GEOMETRY.canvas_height_px
    array = np.array(label.convert("L"))
    ink_columns = np.flatnonzero((array < 128).any(axis=0))
    # two text tiles and one image tile -> three blocks of ink columns
    blocks = 1 + int((ink_columns[1:] - ink_columns[:-1] > 1).sum())
    assert blocks == 3


def test_inverted_image_is_complement_of_normal() -> None:
    icon = Image.new("RGB", (64, 64), "white")
    for y in range(20, 44):
        for x in range(20, 44):
            icon.putpixel((x, y), (0, 0, 0))

    normal = renderer.render_label([ImageAsset(image=icon)])
    inverted = renderer.render_label([ImageAsset(image=icon, invert=True)])
    normal_bits = np.array(normal.convert("L")) < 128
    inverted_bits = np.array(inverted.convert("L")) < 128
    # inverted ink is the complement; antialiasing edge pixels may differ
    assert (normal_bits == ~inverted_bits).mean() > 0.95
    # and the inverted tile actually carries inverted ink
    assert inverted_bits.sum() > normal_bits.sum()


def test_preview_has_full_tape_height_and_blank_margins() -> None:
    label = renderer.render_label([TextAsset(text="Hej", font_size_mm=4)])
    preview = renderer.render_preview(label)
    array = np.array(preview.convert("L"))

    expected_height = round(
        DEFAULT_GEOMETRY.tape_dots_total
        * DEFAULT_GEOMETRY.across_dot_mm
        * DEFAULT_GEOMETRY.preview_px_per_mm
    )
    assert preview.height == expected_height
    # blank tape above and below the print band
    band = DEFAULT_GEOMETRY.head_dots * DEFAULT_GEOMETRY.preview_px_per_mm * 0.161
    margin = (preview.height - band) / 2
    assert not (array[: int(margin) - 2] < 128).any()
    assert not (array[-int(margin) + 2 :] < 128).any()


def test_empty_text_renders_blank() -> None:
    label = renderer.render_text("   ", 4)
    assert label.height == DEFAULT_GEOMETRY.canvas_height_px
    assert not (np.array(label.convert("L")) < 128).any()
