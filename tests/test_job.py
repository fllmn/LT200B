import numpy as np
from PIL import Image

from lt200b.geometry import DEFAULT_GEOMETRY
from lt200b.job import JobEncoder, prepare_image


def test_header_bytes() -> None:
    encoder = JobEncoder()
    header = encoder._header_bytes(5)  # noqa: SLF001 - testing internals
    assert header[:4] == [0xFF, 0xF0, 0x12, 0x34]
    assert header[4:8] == list((5).to_bytes(4, byteorder="little"))
    assert header[8] == sum(header[:8]) & 0xFF


def test_chunks_carry_sequence_numbers_and_terminator() -> None:
    data = list(range(1200))
    chunks = JobEncoder._split_chunks(data, chunk_size=500)
    assert [chunk[0] for chunk in chunks] == [0, 1, 2]
    assert chunks[-1][-2:] == [0x12, 0x34]
    reassembled = [byte for chunk in chunks for byte in chunk[1:]]
    assert reassembled[:-2] == data


def test_print_data_rejects_size_mismatch() -> None:
    try:
        JobEncoder()._print_data([0] * 10, 4, 8)
    except ValueError as exc:
        assert "does not match dimensions" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_encode_white_label_produces_blank_bitmap() -> None:
    label = Image.new("RGB", (200, 128), "white")
    chunks = JobEncoder().encode(label)

    # first chunk is the header, the body follows in 500-byte chunks, each
    # prefixed with its sequence number
    assert len(chunks) > 2
    assert chunks[0][:4] == [0xFF, 0xF0, 0x12, 0x34]
    body = [byte for chunk in chunks[1:] for byte in chunk[1:]]

    # [1B, 73(start job), 9A 02 00 00, 1B, 44(print data), 01, 02, w4, h4, data...]
    assert body[0] == 0x1B
    assert body[1:3] == [0x73, 0x9A]
    assert body[6] == 0x1B
    assert body[7:9] == [0x44, 0x01]

    # the printer expects width = number of raster columns along the tape
    # and height = dots per column (32); the bitmap streams column-by-column
    columns = int.from_bytes(body[10:14], "little")
    dots_per_column = int.from_bytes(body[14:18], "little")
    assert dots_per_column == DEFAULT_GEOMETRY.head_dots
    data = body[18:-8]  # trailing: form feed, status, end, chunk terminator
    assert columns * dots_per_column == len(data) * 8

    # a white label contains no ink: all data bytes are zero
    assert all(byte == 0 for byte in data)


def test_prepare_image_adds_margins() -> None:
    label = Image.new("RGB", (256, 256), "white")
    bits, height, width = prepare_image(label, DEFAULT_GEOMETRY)
    assert width == DEFAULT_GEOMETRY.head_dots
    array = np.array(bits, dtype=np.uint8).reshape(height, width)
    margin = DEFAULT_GEOMETRY.margin_rows
    assert not array[:margin].any()
    assert not array[-margin:].any()


def test_prepare_image_black_bar_lands_at_label_start() -> None:
    # a black bar at the left edge of the label spans the full tape width
    # after rotation and appears in the first printed rows
    label = Image.new("RGB", (128, 128), "white")
    for y in range(128):
        for x in range(8):
            label.putpixel((x, y), (0, 0, 0))
    bits, height, width = prepare_image(label, DEFAULT_GEOMETRY)
    array = np.array(bits, dtype=np.uint8).reshape(height, width)
    body = array[DEFAULT_GEOMETRY.margin_rows : height - DEFAULT_GEOMETRY.margin_rows]
    # the first printed rows carry ink across the full head width, the
    # rest of the label is blank
    assert body[0].all()
    assert body[1].all()
    assert not body[-3:].any()
