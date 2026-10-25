"""The local web UI: a Flask app for composing and printing labels."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import webbrowser
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from flask import Flask, jsonify, make_response, render_template, request, send_file
from flask.typing import ResponseReturnValue
from PIL import Image
from bleak.exc import BleakDeviceNotFoundError

from lt200b.config import ConfigStore
from lt200b.geometry import DEFAULT_GEOMETRY
from lt200b.job import JobEncoder
from lt200b.printer import PrinterClient
from lt200b.render import Asset, ImageAsset, LabelRenderer, TextAsset

HOST = "127.0.0.1"
PORT = 8000

# the 32-dot head spans ~5.2 mm of the 12 mm tape; that is the maximum text height
FONT_SIZES_MM = [2, 3, 4, 5]
DEFAULT_FONT_SIZE_MM = 4.0
MIN_FONT_SIZE_MM = 1.5
MAX_FONT_SIZE_MM = DEFAULT_GEOMETRY.print_span_mm


def create_app(config_store: ConfigStore) -> Flask:
    """Create the Flask app. Routes close over the given collaborators."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
    )
    renderer = LabelRenderer()
    encoder = JobEncoder()
    client = PrinterClient()

    @app.before_request
    def restrict_to_local() -> ResponseReturnValue | None:
        # binding to 127.0.0.1 is the primary guard; this rejects anyway if
        # the app is ever exposed on a wider interface
        if request.remote_addr not in ("127.0.0.1", "::1"):
            return "Forbidden: this server only accepts local connections", 403
        return None

    @app.get("/")
    def index() -> ResponseReturnValue:
        response = make_response(
            render_template(
                "index.html",
                last_printer=config_store.load().get("last_printer", ""),
                font_sizes=FONT_SIZES_MM,
                default_font_size=int(DEFAULT_FONT_SIZE_MM),
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/preview")
    def preview() -> ResponseReturnValue:
        assets, error = _parse_assets(strict=False)
        if error is not None:
            return jsonify(error=error), 400

        if assets:
            label = renderer.render_label(assets)
        else:
            # empty label previews as blank tape (only the fed white space)
            label = Image.new("RGB", (1, DEFAULT_GEOMETRY.canvas_height_px), "white")

        with label:
            return _png_response(renderer.render_preview(label))

    @app.post("/api/print")
    def print_label() -> ResponseReturnValue:
        mac_addr = (request.form.get("mac") or "").strip()
        if not mac_addr:
            return jsonify(error="Please provide the MAC address of the printer."), 400

        assets, error = _parse_assets(strict=True)
        if error is not None:
            return jsonify(error=error), 400
        if not assets:
            return jsonify(error="The label is empty. Add text or an image first."), 400

        job = encoder.encode(renderer.render_label(assets))
        try:
            _run_async(client.print_job(mac_addr, job))
        except BleakDeviceNotFoundError:
            return jsonify(
                error=f"The device with MAC address {mac_addr} is not found. "
                "Is the device powered on?"
            ), 400
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            return jsonify(error=f"Unexpected error: {exc}"), 500

        config_store.save({"last_printer": mac_addr})
        return jsonify(ok=True)

    @app.post("/api/scan")
    def scan() -> ResponseReturnValue:
        try:
            devices = _run_async(client.scan())
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            return jsonify(error=f"Scan failed: {exc}"), 500
        return jsonify(devices=[
            {"name": device.name, "address": device.address} for device in devices
        ])

    return app


def _parse_assets(strict: bool) -> tuple[list[Asset], str | None]:
    """Build the asset list from the multipart form payload.

    The client posts an ordered asset list as a JSON form field "assets",
    where image entries reference their file as "file": <n>, uploaded as
    form field "image-<n>". With strict=True, empty text fields and missing
    images are errors; otherwise they are skipped (used for previews).
    """
    try:
        entries = json.loads(request.form.get("assets") or "[]")
    except ValueError:
        return [], "Malformed label data."
    if not isinstance(entries, list):
        return [], "Malformed label data."

    assets: list[Asset] = []
    for entry in entries:
        kind = entry.get("type") if isinstance(entry, dict) else None

        if kind == "text":
            text = (entry.get("text") or "").replace("\r\n", "\n").strip()
            font_size = _font_size_mm(entry.get("font_size", DEFAULT_FONT_SIZE_MM))
            if font_size is None:
                return [], (
                    f"Font size must be between {MIN_FONT_SIZE_MM} and "
                    f"{MAX_FONT_SIZE_MM} mm."
                )
            if not text:
                if strict:
                    return [], "A text field is empty."
                continue
            assets.append(TextAsset(text=text, font_size_mm=font_size))

        elif kind == "image":
            file = request.files.get(f"image-{entry.get('file', 0)}")
            if not file or not file.filename:
                if strict:
                    return [], "An image has no file selected."
                continue
            try:
                img = Image.open(file.stream)
                img.load()
            except Exception:
                return [], f"Could not read {file.filename} as an image."
            assets.append(ImageAsset(image=img, invert=bool(entry.get("invert"))))

    return assets, None


def _font_size_mm(value: object) -> float | None:
    try:
        size = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return size if MIN_FONT_SIZE_MM <= size <= MAX_FONT_SIZE_MM else None


def _png_response(image: Image.Image) -> ResponseReturnValue:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=0)


T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion and return its result; BLE needs its
    own event loop, so run it in a worker thread to keep Flask request
    handling synchronous."""
    result: list[T] = []
    error: list[Exception] = []

    def run() -> None:
        try:
            result.append(asyncio.run(coro))
        except Exception as exc:  # noqa: BLE001 - re-raised in the caller
            error.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    return result[0]


def main() -> None:
    """Start the local web server and open the UI in the browser."""
    config_store = ConfigStore()
    app = create_app(config_store)

    url = f"http://{HOST}:{PORT}"
    print(f"LT200B Label Maker running at {url} (local connections only)")

    # give the server a moment to start, then open the UI in the browser
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, threaded=True)
