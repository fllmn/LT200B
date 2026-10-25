"""Rendering of label assets into images ready for the print encoder.

Text is rendered at ``render_scale`` times the print resolution for clean
antialiasing before it is downscaled into the 1-bit print bitmap. Emoji and
other characters missing from the text font fall back to a bundled
monochrome emoji font, drawn on the same baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from lt200b.geometry import DEFAULT_GEOMETRY, PrintGeometry
from lt200b.job import prepare_image

FONTS_DIR = Path(__file__).parent / "fonts"
BUNDLED_FONT_PATH = FONTS_DIR / "LiberationSans-Regular.ttf"
EMOJI_FONT_PATH = FONTS_DIR / "NotoEmoji-Regular.ttf"

# padding kept around the ink when cropping line tiles
_CROP_PAD = 2

# character ranges rendered with the emoji font; variation selectors and
# zero-width joiners are absorbed into emoji runs (Pillow does no shaping,
# so ZWJ sequences and flags render as their base glyphs)
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F000, 0x1FFFF),  # pictographs, transport, regional indicators, ...
    (0x2600, 0x27BF),    # misc symbols and dingbats (warning sign, heart, ...)
    (0x2B00, 0x2BFF),    # arrows and stars
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0xFE0F, 0xFE0F),
    (0x200D, 0x200D),
)


@dataclass(frozen=True)
class TextAsset:
    """A text block printed with the bundled font at a given ink height."""

    text: str
    font_size_mm: float = 4.0


@dataclass(frozen=True)
class ImageAsset:
    """An image printed inline between text, optionally color-inverted."""

    image: Image.Image
    invert: bool = False


Asset = TextAsset | ImageAsset


def _is_emoji_char(char: str) -> bool:
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _EMOJI_RANGES)


def _split_runs(text: str) -> list[tuple[bool, str]]:
    """Split a line into (is_emoji, chunk) runs of consecutive same-font characters."""
    runs: list[tuple[bool, str]] = []
    for char in text:
        emoji = _is_emoji_char(char)
        if runs and runs[-1][0] == emoji:
            last_emoji, last_chunk = runs[-1]
            runs[-1] = (last_emoji, last_chunk + char)
        else:
            runs.append((emoji, char))
    result: list[tuple[bool, str]] = []
    for emoji, chunk in runs:
        if emoji:
            chunk = chunk.replace("\uFE0F", "").replace("\u200D", "")
            if not chunk:
                continue
        result.append((emoji, chunk))
    return result


def _load_font(path: Path, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size_px)


class LabelRenderer:
    """Renders ordered text and image assets into label images."""

    def __init__(self, geometry: PrintGeometry = DEFAULT_GEOMETRY) -> None:
        self._geometry = geometry

    def render_label(self, assets: list[Asset]) -> Image.Image:
        """Render an ordered asset list into one label image.

        Assets are laid out side by side along the tape, each fitted into
        the print span height, separated by a small gap.
        """
        tiles = [self._render_asset(asset) for asset in assets]
        gap = round(0.5 * self._geometry.dots_per_mm * self._geometry.render_scale)
        total_width = sum(tile.width for tile in tiles) + gap * (len(tiles) - 1)
        label = Image.new(
            "RGB", (max(total_width, 1), self._geometry.canvas_height_px), "white"
        )
        x = 0
        for tile in tiles:
            label.paste(tile, (x, 0))
            x += tile.width + gap
        return label

    def render_text(
        self, text: str, font_size_mm: float, font_path: Path | None = None
    ) -> Image.Image:
        """Render text onto a canvas as tall as the print span.

        ``font_size_mm`` is the desired ink height on the tape: the font is
        scaled so the actual glyphs of this exact text (cap height,
        ascenders, descenders) measure that size - a font's em size is not
        its glyph height. Sizes above the print span are clamped;
        multi-line text taller than the span is scaled down to fit.
        """
        geometry = self._geometry
        text = text.replace("\r\n", "\n")
        target_ink_px = min(
            font_size_mm * geometry.dots_per_mm * geometry.render_scale,
            float(geometry.canvas_height_px),
        )

        lines = text.split("\n")
        nonempty = [line for line in lines if line.strip()]
        if not nonempty:
            return Image.new("RGB", (1, geometry.canvas_height_px), "white")

        # measure the real ink height of the tallest line at a trial size
        # and scale the font so the ink matches the requested height
        trial_heights = [
            self._render_line(line, 100, font_path).height - 2 * _CROP_PAD
            for line in nonempty
        ]
        font_px = max(1, round(100 * target_ink_px / max(trial_heights)))

        tiles: list[Image.Image | None] = [
            self._render_line(line, font_px, font_path) if line.strip() else None
            for line in lines
        ]

        if len(lines) == 1:
            assert tiles[0] is not None  # the single line is non-empty
            tile = self._fit_single_line(tiles[0], target_ink_px)
            return self._center_on_canvas(tile)

        return self._center_on_canvas(self._stack_lines(tiles, target_ink_px))

    def render_preview(self, label: Image.Image) -> Image.Image:
        """Render a preview of the printed tag at the full tape height.

        The print bitmap (head dots across the print span) is rotated so
        the label reads horizontally, padded with the blank tape above and
        below the print span, and resampled so one screen pixel corresponds
        to the same physical distance in both directions.
        """
        geometry = self._geometry
        bitmap_bits, length_rows, tape_dots = prepare_image(label, geometry)
        bitmap = Image.new("L", (tape_dots, length_rows), 255)
        bitmap.putdata([0 if bit else 255 for bit in bitmap_bits])
        preview = bitmap.rotate(90, expand=True)

        # pad to the full tape height, print band centered
        extra = (geometry.tape_dots_total - tape_dots) // 2
        if extra > 0:
            full = Image.new("L", (preview.width, preview.height + 2 * extra), 255)
            full.paste(preview, (0, extra))
            preview = full

        out_width = max(
            1, round(preview.width * geometry.data_feed_mm * geometry.preview_px_per_mm)
        )
        out_height = max(
            1,
            round(preview.height * geometry.across_dot_mm * geometry.preview_px_per_mm),
        )
        return preview.resize((out_width, out_height), Image.Resampling.NEAREST)

    # internals ------------------------------------------------------------

    def _render_asset(self, asset: Asset) -> Image.Image:
        if isinstance(asset, TextAsset):
            return self.render_text(asset.text, asset.font_size_mm)
        img = asset.image.convert("RGB")
        if asset.invert:
            img = ImageOps.invert(img)
        height = self._geometry.canvas_height_px
        width = max(1, round(img.width * height / img.height))
        return img.resize((width, height), Image.Resampling.LANCZOS)

    def _fit_single_line(self, tile: Image.Image, target_ink_px: float) -> Image.Image:
        """Rescale a cropped line tile so its ink matches the target exactly."""
        ink_px = tile.height - 2 * _CROP_PAD
        if ink_px <= 0:
            return tile
        scale = target_ink_px / ink_px
        if abs(scale - 1.0) <= 0.02:
            return tile
        return tile.resize(
            (max(1, round(tile.width * scale)), max(1, round(tile.height * scale))),
            Image.Resampling.LANCZOS,
        )

    def _stack_lines(
        self, tiles: list[Image.Image | None], target_ink_px: float
    ) -> Image.Image:
        """Stack line tiles vertically, scaled down if they exceed the print span."""
        geometry = self._geometry
        rendered = [tile for tile in tiles if tile is not None]
        gap = round(0.25 * target_ink_px)
        block_height = sum(t.height for t in rendered) + gap * (len(rendered) - 1)
        if block_height > geometry.canvas_height_px:
            scale = geometry.canvas_height_px / block_height
            rendered = [
                t.resize(
                    (max(1, round(t.width * scale)), max(1, round(t.height * scale))),
                    Image.Resampling.LANCZOS,
                )
                for t in rendered
            ]
            gap = round(gap * scale)
        width = max(t.width for t in rendered)
        block = Image.new(
            "RGB",
            (width, sum(t.height for t in rendered) + gap * (len(rendered) - 1)),
            "white",
        )
        y = 0
        for tile in rendered:
            block.paste(tile, (0, y))
            y += tile.height + gap
        return block

    def _center_on_canvas(self, tile: Image.Image) -> Image.Image:
        """Center a tile on a canvas as tall as the print span."""
        height = self._geometry.canvas_height_px
        tag = Image.new("RGB", (max(tile.width, 1), height), "white")
        y = max(0, (height - tile.height) // 2)
        tag.paste(tile, (0, y))
        if tile.height > height:
            tag.paste(tile.crop((0, 0, tile.width, height)), (0, 0))
        return tag

    def _render_line(
        self, line: str, size_px: int, font_path: Path | None = None
    ) -> Image.Image:
        """Render one line of text with font fallback as a tight-cropped tile."""
        runs = _split_runs(line)
        text_font = _load_font(font_path or BUNDLED_FONT_PATH, size_px)
        emoji_font = (
            _load_font(EMOJI_FONT_PATH, size_px)
            if any(is_emoji for is_emoji, _ in runs)
            else None
        )

        fonts: list[ImageFont.FreeTypeFont] = []
        for is_emoji, _ in runs:
            if is_emoji:
                assert emoji_font is not None
                fonts.append(emoji_font)
            else:
                fonts.append(text_font)

        ascent, descent = text_font.getmetrics()
        width = max(
            1,
            round(sum(font.getlength(chunk) for font, (_, chunk) in zip(fonts, runs)) + 2),
        )
        tile = Image.new("RGB", (width, ascent + descent), "white")
        draw = ImageDraw.Draw(tile)

        x = 0.0
        for font, (_, chunk) in zip(fonts, runs):
            draw.text((x, ascent), chunk, font=font, fill="black", anchor="ls")
            x += font.getlength(chunk)

        # crop to the actual ink so the font's empty line-box space does not
        # affect the layout
        mask = tile.convert("L").point(lambda v: 255 if v < 128 else 0)
        ink_bbox = mask.getbbox()
        if ink_bbox is None:
            return Image.new("RGB", (1, 2 * _CROP_PAD), "white")
        left, top, right, bottom = ink_bbox
        return tile.crop(
            (
                max(0, left - 1),
                max(0, top - _CROP_PAD),
                min(tile.width, right + 1),
                min(tile.height, bottom + _CROP_PAD),
            )
        )

