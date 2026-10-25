import numpy as np
from PIL import Image

# Print geometry, calibrated against measured printouts:
# * the 32-dot head prints a ~5.2 mm band on the 12 mm tape
#   (0.161 mm per dot), the rest of the tape width stays blank
# * each raster column is doubled in the data to match the stepper motor
#   cadence (as in the official app), so one data row = half a physical
#   feed line (0.0806 mm)
TAPE_WIDTH_MM = 12.0
PRINT_SPAN_MM = 5.16
PRINT_HEAD_DOTS = 32
DOTS_PER_MM = PRINT_HEAD_DOTS / PRINT_SPAN_MM # ~6.2 dots per mm
DATA_FEED_MM = PRINT_SPAN_MM / PRINT_HEAD_DOTS / 2 # 0.0806 mm per data row
# blank tape fed before and after the label (~2 mm each side, in data rows)
MARGIN_ROWS = 25
# full tape width in head dots, for rendering the preview at true tape height
TAPE_DOTS_TOTAL = round(TAPE_WIDTH_MM / (PRINT_SPAN_MM / PRINT_HEAD_DOTS)) # ~74

def _calculate_checksum(data):
    checksum = 0
    for byte in data:
        checksum += byte
    return checksum & 0xFF

def _split_chunks(data, chunk_size = 500):
    chunks = []
    for i in range(0, len(data), chunk_size):
        chunks.append([i // chunk_size, *data[i:i + chunk_size]])
    chunks[-1].extend([0x12, 0x34])
    return chunks

def _prepare_image(img):
    # convert to 1-bit monochrome
    img = img.convert('1', dither=Image.Dither.NONE)
    # rotate since the printer expects a portrait image
    img = img.rotate(-90, expand=1)
    # resize to the full 32-dot head width; each column is doubled for the
    # stepper cadence, hence the factor of 2
    width = PRINT_HEAD_DOTS
    height = max(1, int(2 * width * (img.height / img.width)))
    img = img.resize((width, height)).convert('L')
    # pad with blank tape before and after the label
    padded = Image.new('L', (width, height + 2 * MARGIN_ROWS), 255)
    padded.paste(img, (0, MARGIN_ROWS))
    # convert to zeroes and ones
    return [1 if x < 128 else 0 for x in padded.getdata()], padded.height, padded.width

def _get_header_bytes(length):
    return [
        0xFF, # preamble
        0xF0, # flags, always this value
        0x12, 0x34, # magic
        *(length_bytes := length.to_bytes(4, byteorder='little')), # data length
        _calculate_checksum([0xFF, 0xF0, 0x12, 0x34, *length_bytes])
    ]

def _get_start_job():
    return [
        0x1B,
        0x73, # type: start job
        0x9A, 0x02, 0x00, 0x00 # job id, always this value
    ]

def _get_print_data(data, width, height):
    if width*height != len(data)*8:
        raise ValueError(f'data does not match dimensions ({width}*{height}!={len(data)*8})')
    
    return [
        0x1B,
        0x44, # type: print data
        0x01, # bits per pixel
        0x02, # alignment
        *width.to_bytes(4, byteorder='little'), # width
        *height.to_bytes(4, byteorder='little'), # height
        *data # data
    ]

def _get_form_feed():
    return [
        0x1B,
        0x45 # type: form feed
    ]

def _get_status():
    return [
        0x1B,
        0x41 # type: status
    ]

def _get_end():
    return [
        0x1B,
        0x51 # type: end
    ]

def render_preview(img, px_per_mm=8):
    """Return a preview of the printed tag at the full 12 mm tape height.

    The print bitmap (32 dots across the ~5.2 mm print span) is rotated so
    the label reads horizontally, padded with the blank tape above and
    below the print span, and resampled so that one screen pixel
    corresponds to the same distance in both directions.
    """
    bits, length_rows, tape_dots = _prepare_image(img)
    # the print data is laid out tape-across (32 dots) x length-down
    bitmap = Image.new("L", (tape_dots, length_rows), 255)
    bitmap.putdata([0 if bit else 255 for bit in bits])
    preview = bitmap.rotate(90, expand=True)
    # pad to the full 12 mm tape height, print band centered
    extra = (TAPE_DOTS_TOTAL - tape_dots) // 2
    if extra > 0:
        full = Image.new("L", (preview.width, preview.height + 2 * extra), 255)
        full.paste(preview, (0, extra))
        preview = full
    out_width = max(1, round(preview.width * DATA_FEED_MM * px_per_mm))
    out_height = max(1, round(preview.height * (TAPE_WIDTH_MM / TAPE_DOTS_TOTAL) * px_per_mm))
    return preview.resize((out_width, out_height), Image.Resampling.NEAREST)

def create_job(image):
    # a job always consists of the following parts:
    # * header bytes
    # * chunked body consisting of:
    #   * start job
    #   * print data
    #   * form feed
    #   * status
    #   * end

    data, width, height = _prepare_image(image)
    packed_data = np.packbits(np.array(data), bitorder='little').tolist()

    body = [
        *_get_start_job(),
        *_get_print_data(packed_data, width, height),
        *_get_form_feed(),
        *_get_status(),
        *_get_end()
    ]
    header = _get_header_bytes(len(body))
    chunks = _split_chunks(body)

    return [header, *chunks]
