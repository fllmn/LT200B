from pathlib import Path

from bleak import BleakClient
from PIL import Image, ImageDraw, ImageFont, ImageOps
from utils.jobmanager import DOTS_PER_MM, PRINT_HEAD_DOTS

# The default font bundled with Pillow has no glyphs for characters like
# å, ä, ö, so ship a font with full Latin-1/Latin Extended coverage instead.
# Lives inside utils/ so PyInstaller's --add-data "utils:utils" bundles it.
BUNDLED_FONT_PATH = Path(__file__).parent / "fonts" / "LiberationSans-Regular.ttf"
# monochrome emoji font for fallback rendering of pictographs
EMOJI_FONT_PATH = Path(__file__).parent / "fonts" / "NotoEmoji-Regular.ttf"

# character ranges rendered with the emoji font; variation selectors and
# zero-width joiners are absorbed into emoji runs (Pillow does no shaping,
# so ZWJ sequences and flags render as their base glyphs)
_EMOJI_RANGES = (
    (0x1F000, 0x1FFFF), # pictographs, transport, regional indicators, ...
    (0x2600, 0x27BF),   # misc symbols and dingbats (⚠, ❤, ✓, ...)
    (0x2B00, 0x2BFF),   # arrows and stars (⭐, ⬆, ...)
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0xFE0F, 0xFE0F),
    (0x200D, 0x200D),
)


def _is_emoji_char(char):
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _EMOJI_RANGES)


def _split_runs(text):
    """Split a line into (is_emoji, chunk) runs of consecutive same-font chars."""
    runs = []
    for char in text:
        emoji = _is_emoji_char(char)
        if runs and runs[-1][0] == emoji:
            runs[-1][1] += char
        else:
            runs.append([emoji, char])
    result = []
    for emoji, chunk in runs:
        if emoji:
            chunk = chunk.replace("\uFE0F", "").replace("\u200D", "")
            if not chunk:
                continue
        result.append((emoji, chunk))
    return result

# Text is rendered at RENDER_SCALE times the print resolution for clean
# antialiasing before it is downscaled into the print bitmap. The canvas is
# the full ~5.2 mm print span of the head.
RENDER_SCALE = 4
CANVAS_HEIGHT_PX = PRINT_HEAD_DOTS * RENDER_SCALE
# padding added around the ink when cropping line tiles
_CROP_PAD = 2


def _load_font(font_path, size_px):
    if font_path:
        return ImageFont.truetype(font_path, size_px)
    return ImageFont.truetype(str(BUNDLED_FONT_PATH), size_px)


def create_text_image(text, font_path, font_size_mm):
    """Render text onto a canvas as tall as the ~5.2 mm print span.

    font_size_mm is the desired ink height of the text on the tape: the
    font is scaled so the actual glyphs of this exact text (cap height,
    ascenders, descenders) measure font_size_mm - a font's em size is not
    its glyph height, caps are only ~0.7 em. Sizes above the print span
    are clamped; multi-line text taller than the span is scaled down so
    the tag always fits.

    Emoji and other characters missing from the text font are rendered
    with the bundled monochrome emoji font on the same baseline.
    """
    text = text.replace("\r\n", "\n")
    target_ink_px = min(
        font_size_mm * DOTS_PER_MM * RENDER_SCALE,
        float(CANVAS_HEIGHT_PX),
    )

    lines = text.split("\n")
    nonempty = [line for line in lines if line.strip()]

    if not nonempty:
        # whitespace-only text: blank canvas
        return Image.new("RGB", (1, CANVAS_HEIGHT_PX), "white")

    # measure the real ink height of the tallest line at a trial size and
    # scale the font so the ink matches the requested height
    trial_tiles = {line: _render_line(line, font_path, 100) for line in nonempty}
    tallest = max(tile.height - 2 * _CROP_PAD for tile in trial_tiles.values())
    font_px = max(1, round(100 * target_ink_px / tallest))

    tiles = []
    for line in lines:
        if line.strip():
            tiles.append(_render_line(line, font_path, font_px))
        else:
            tiles.append(None) # blank line -> spacing

    # single-line text: correct the rendered ink to the exact target
    # (font hinting makes it deviate a few percent from the linear estimate)
    if len(tiles) == 1:
        tile = tiles[0]
        ink_px = tile.height - 2 * _CROP_PAD
        scale = target_ink_px / ink_px
        if abs(scale - 1.0) > 0.02:
            tiles[0] = tile.resize(
                (max(1, round(tile.width * scale)), max(1, round(tile.height * scale))),
                Image.Resampling.LANCZOS,
            )
    else:
        # multi-line: scale down to fit the print span
        gap = round(0.25 * font_px)
        block = sum(t.height for t in tiles if t is not None) + gap * (len(tiles) - 1)
        if block > CANVAS_HEIGHT_PX:
            scale = CANVAS_HEIGHT_PX / block
            tiles = [
                None if t is None else t.resize(
                    (max(1, round(t.width * scale)), max(1, round(t.height * scale))),
                    Image.Resampling.LANCZOS,
                )
                for t in tiles
            ]
            gap = round(gap * scale)
        # rebuild: blank lines collapse to the gap
        tiles = [t for t in tiles if t is not None]
        if len(tiles) == 1:
            return _center_on_canvas(tiles[0])
        width = max(t.width for t in tiles)
        block_img = Image.new("RGB", (width, sum(t.height for t in tiles) + gap * (len(tiles) - 1)), "white")
        y = 0
        for t in tiles:
            block_img.paste(t, (0, y))
            y += t.height + gap
        return _center_on_canvas(block_img)

    return _center_on_canvas(tiles[0])


def _center_on_canvas(tile):
    tag = Image.new("RGB", (max(tile.width, 1), CANVAS_HEIGHT_PX), "white")
    y = max(0, (CANVAS_HEIGHT_PX - tile.height) // 2) # center on the tape
    tag.paste(tile, (0, y))
    if tile.height > CANVAS_HEIGHT_PX:
        tag.paste(tile.crop((0, 0, tile.width, CANVAS_HEIGHT_PX)), (0, 0))
    return tag


def _render_line(line, font_path, size_px):
    """Render one line of text with font fallback as a tight-cropped tile."""
    runs = _split_runs(line)
    text_font = _load_font(font_path, size_px)
    ascent, descent = text_font.getmetrics()
    line_height = ascent + descent

    width = max(1, round(sum(
        (_load_font(EMOJI_FONT_PATH, size_px) if emoji else text_font).getlength(chunk)
        for emoji, chunk in runs
    )) + 2)
    tile = Image.new("RGB", (width, line_height), "white")
    draw = ImageDraw.Draw(tile)

    x = 0
    for emoji, chunk in runs:
        font = _load_font(EMOJI_FONT_PATH, size_px) if emoji else text_font
        draw.text((x, ascent), chunk, font=font, fill="black", anchor="ls") # baseline aligned
        x += font.getlength(chunk)

    # crop to the actual ink so the font's empty line-box space does not
    # affect layout
    mask = tile.convert("L").point(lambda v: 255 if v < 128 else 0)
    ink_bbox = mask.getbbox()
    if ink_bbox is None:
        return Image.new("RGB", (1, 2 * _CROP_PAD), "white")
    left, top, right, bottom = ink_bbox
    return tile.crop((
        max(0, left - 1), max(0, top - _CROP_PAD),
        min(tile.width, right + 1), min(tile.height, bottom + _CROP_PAD),
    ))

# gap between assets along the tape (~0.5 mm)
GAP_PX = round(0.5 * DOTS_PER_MM * RENDER_SCALE)

def create_label_image(assets):
    """Render an ordered list of assets into one label image.

    assets: list of ("text", text, font_size_mm) or ("image", PIL.Image,
    invert) entries. They are laid out side by side along the tape, each
    fitted into the print span height, separated by a small gap.
    """
    tiles = []
    for asset in assets:
        if asset[0] == "text":
            tiles.append(create_text_image(asset[1], None, asset[2]))
        else:
            img = asset[1].convert("RGB")
            if len(asset) > 2 and asset[2]:
                img = ImageOps.invert(img)
            height = CANVAS_HEIGHT_PX
            width = max(1, round(img.width * height / img.height))
            tiles.append(img.resize((width, height), Image.Resampling.LANCZOS))

    total_width = sum(tile.width for tile in tiles) + GAP_PX * (len(tiles) - 1)
    label = Image.new("RGB", (max(total_width, 1), CANVAS_HEIGHT_PX), "white")
    x = 0
    for tile in tiles:
        label.paste(tile, (x, 0))
        x += tile.width + GAP_PX

    return label

async def print_image(address, job):
    async with BleakClient(address) as client:
        # unsure if every device has the same uuid, so we search for it
        for service in client.services:
            first, second, _, _, _ = service.uuid.split('-')
            if first == 'be3dd650':
                uuid = second
                break

        for chunk in job:
            await client.write_gatt_char(f'be3dd651-{uuid}-42f1-99c1-f0f749dd0678', bytearray(chunk))
