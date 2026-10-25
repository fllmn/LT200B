from pathlib import Path

from bleak import BleakClient
from PIL import Image, ImageDraw, ImageFont, ImageOps
from utils.jobmanager import DOTS_PER_MM, PRINT_HEAD_DOTS

# The default font bundled with Pillow has no glyphs for characters like
# å, ä, ö, so ship a font with full Latin-1/Latin Extended coverage instead.
# Lives inside utils/ so PyInstaller's --add-data "utils:utils" bundles it.
BUNDLED_FONT_PATH = Path(__file__).parent / "fonts" / "LiberationSans-Regular.ttf"

# Text is rendered at RENDER_SCALE times the print resolution for clean
# antialiasing before it is downscaled into the print bitmap. The canvas is
# the full ~5.2 mm print span of the head.
RENDER_SCALE = 4
CANVAS_HEIGHT_PX = PRINT_HEAD_DOTS * RENDER_SCALE


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
    """
    target_ink_px = min(
        font_size_mm * DOTS_PER_MM * RENDER_SCALE,
        float(CANVAS_HEIGHT_PX),
    )

    # measure the real ink height of the tallest text line at a trial size
    # and scale the font so the ink matches the requested height
    trial_font = _load_font(font_path, 100)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_ink_heights = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        _, top, _, bottom = measure.textbbox((0, 0), line, font=trial_font)
        line_ink_heights.append(bottom - top)

    if line_ink_heights:
        font_px = max(1, round(100 * target_ink_px / max(line_ink_heights)))
    else:
        font_px = max(1, round(target_ink_px)) # whitespace-only text
    font = _load_font(font_path, font_px)

    text_width, text_height = textsize(text, font)

    img_width = int(text_width)
    img_height = int(text_height)

    tight = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(tight)

    draw.multiline_text((0, img_height / 2), text, font=font, fill="black", anchor="lm") # align middle left anchored in the middle

    # constrain and correct using the actual rasterized ink: font hinting
    # makes glyph ink deviate a few percent from the linear estimate
    mask = tight.convert("L").point(lambda v: 255 if v < 128 else 0)
    ink_bbox = mask.getbbox()
    if ink_bbox is not None:
        pad = 2
        left, top, right, bottom = ink_bbox
        # crop to the ink so the font's empty line-box space cannot push the
        # text out of the canvas when scaling
        tight = tight.crop((
            max(0, left - pad), max(0, top - pad),
            min(tight.width, right + pad), min(tight.height, bottom + pad),
        ))
        ink_px = bottom - top
        if len(text.split("\n")) == 1:
            scale = target_ink_px / ink_px # exact height for single-line text
        elif ink_px > CANVAS_HEIGHT_PX:
            scale = CANVAS_HEIGHT_PX / ink_px # fit constraint for multi-line
        else:
            scale = 1.0
        if abs(scale - 1.0) > 0.02:
            tight = tight.resize(
                (max(1, round(tight.width * scale)), max(1, round(tight.height * scale))),
                Image.Resampling.LANCZOS,
            )

    tag = Image.new("RGB", (max(tight.width, 1), CANVAS_HEIGHT_PX), "white")
    y = max(0, (CANVAS_HEIGHT_PX - tight.height) // 2) # center on the tape
    tag.paste(tight, (0, y))
    if tight.height > CANVAS_HEIGHT_PX:
        tag.paste(tight.crop((0, 0, tight.width, CANVAS_HEIGHT_PX)), (0, 0))

    return tag

def textsize(text, font):
    im = Image.new(mode="P", size=(0, 0))
    draw = ImageDraw.Draw(im)
    _, _, width, height = draw.textbbox((0, 0), text=text, font=font)
    return width, height

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
