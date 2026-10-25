"""Encoding of label images into the LT200B Bluetooth print job format."""

from __future__ import annotations

import numpy as np
from PIL import Image

from lt200b.geometry import DEFAULT_GEOMETRY, PrintGeometry

Chunk = list[int]


class JobEncoder:
    """Encodes label images into chunked print jobs."""

    def __init__(self, geometry: PrintGeometry = DEFAULT_GEOMETRY) -> None:
        self._geometry = geometry

    def encode(self, label: Image.Image) -> list[Chunk]:
        """Encode a label image into a list of chunks to send to the printer.

        A job consists of the header bytes followed by a chunked body of:
        start job, print data, form feed, status, end.

        In the print data command, "width" is the number of raster columns
        along the tape and "height" the dots per column (the head width);
        the bitmap is streamed column-by-column.
        """
        bits, width, height = prepare_image(label, self._geometry)
        packed = np.packbits(np.array(bits), bitorder="little").tolist()

        body: list[int] = [
            *self._start_job(),
            *self._print_data(packed, width, height),
            *self._form_feed(),
            *self._status(),
            *self._end(),
        ]
        header = self._header_bytes(len(body))
        return [header, *self._split_chunks(body)]

    @staticmethod
    def _calculate_checksum(data: list[int]) -> int:
        return sum(data) & 0xFF

    @staticmethod
    def _split_chunks(data: list[int], chunk_size: int = 500) -> list[Chunk]:
        chunks: list[Chunk] = []
        for i in range(0, len(data), chunk_size):
            chunks.append([i // chunk_size, *data[i : i + chunk_size]])
        chunks[-1].extend([0x12, 0x34])
        return chunks

    def _header_bytes(self, length: int) -> list[int]:
        length_bytes = list(length.to_bytes(4, byteorder="little"))
        prefix = [0xFF, 0xF0, 0x12, 0x34, *length_bytes]
        return [*prefix, self._calculate_checksum(prefix)]

    @staticmethod
    def _start_job() -> list[int]:
        return [0x1B, 0x73, 0x9A, 0x02, 0x00, 0x00]  # start job, fixed job id

    def _print_data(self, data: list[int], width: int, height: int) -> list[int]:
        if width * height != len(data) * 8:
            raise ValueError(
                f"data does not match dimensions ({width}*{height}!={len(data) * 8})"
            )
        return [
            0x1B,
            0x44,  # print data
            0x01,  # bits per pixel
            0x02,  # alignment
            *width.to_bytes(4, byteorder="little"),
            *height.to_bytes(4, byteorder="little"),
            *data,
        ]

    @staticmethod
    def _form_feed() -> list[int]:
        return [0x1B, 0x45]

    @staticmethod
    def _status() -> list[int]:
        return [0x1B, 0x41]

    @staticmethod
    def _end() -> list[int]:
        return [0x1B, 0x51]


def prepare_image(
    img: Image.Image, geometry: PrintGeometry
) -> tuple[list[int], int, int]:
    """Convert a label image to the 1-bit print bitmap.

    Returns ``(bits, height, width)`` where bits use 1 for ink, the bitmap
    is laid out width (= head dots) across and height (= data rows) down,
    and blank tape margins are prepended and appended.
    """
    img = img.convert("1", dither=Image.Dither.NONE)
    img = img.rotate(-90, expand=1)
    width = geometry.head_dots
    height = max(1, int(2 * width * (img.height / img.width)))
    img = img.resize((width, height)).convert("L")
    padded = Image.new("L", (width, height + 2 * geometry.margin_rows), 255)
    padded.paste(img, (0, geometry.margin_rows))
    # convert to zeroes and ones
    pixels = np.asarray(padded)
    bits = np.where(pixels < 128, 1, 0).ravel().tolist()
    return bits, padded.height, padded.width
