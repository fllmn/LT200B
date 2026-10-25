import asyncio
import io
import json
import threading
import webbrowser

from flask import Flask, jsonify, make_response, render_template, request, send_file
from PIL import Image
from bleak import BleakScanner
from bleak import exc as bleak_exc

from utils import config, lt200b
from utils.jobmanager import PRINT_SPAN_MM, create_job, render_preview

app = Flask(__name__)

# the 32-dot head spans ~5.2 mm of the 12 mm tape; that is the maximum text height
FONT_SIZES_MM = [2, 3, 4, 5]
DEFAULT_FONT_SIZE_MM = 4.0
MIN_FONT_SIZE_MM = 1.5
MAX_FONT_SIZE_MM = PRINT_SPAN_MM


def _font_size_mm(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return None
    return size if MIN_FONT_SIZE_MM <= size <= MAX_FONT_SIZE_MM else None


def _png_response(image):
    buf = io.BytesIO()
    image.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=0)


def _parse_assets(strict):
    """Build the asset list for create_label_image from the form payload.

    The client posts an ordered asset list as a JSON form field "assets",
    where image entries reference their file as "file": <n>, uploaded as
    form field "image-<n>". Returns (assets, error); with strict=True,
    empty text fields and missing images are errors, otherwise they are
    skipped (used for previews).
    """
    try:
        entries = json.loads(request.form.get("assets") or "[]")
    except ValueError:
        return None, "Malformed label data."

    if not isinstance(entries, list):
        return None, "Malformed label data."

    assets = []
    for entry in entries:
        kind = entry.get("type") if isinstance(entry, dict) else None

        if kind == "text":
            text = (entry.get("text") or "").replace("\r\n", "\n").strip()
            font_size = _font_size_mm(entry.get("font_size", DEFAULT_FONT_SIZE_MM))
            if font_size is None:
                return None, f"Font size must be between {MIN_FONT_SIZE_MM} and {MAX_FONT_SIZE_MM} mm."
            if not text:
                if strict:
                    return None, "A text field is empty."
                continue
            assets.append(("text", text, font_size))

        elif kind == "image":
            file = request.files.get(f"image-{entry.get('file', 0)}")
            if not file or not file.filename:
                if strict:
                    return None, "An image has no file selected."
                continue
            try:
                img = Image.open(file.stream)
                img.load()
            except Exception:
                return None, f"Could not read {file.filename} as an image."
            assets.append(("image", img, bool(entry.get("invert"))))

    return assets, None


@app.before_request
def restrict_to_local():
    # bind to 127.0.0.1 as the primary guard; this rejects anyway if the
    # app is ever exposed on a wider interface
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return "Forbidden: this server only accepts local connections", 403


@app.get("/")
def index():
    response = make_response(render_template(
        "index.html",
        last_printer=config.load_config().get("last_printer", ""),
        font_sizes=FONT_SIZES_MM,
        default_font_size=int(DEFAULT_FONT_SIZE_MM),
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/preview")
def preview():
    assets, error = _parse_assets(strict=False)
    if error:
        return jsonify(error=error), 400

    if assets:
        label = lt200b.create_label_image(assets)
    else:
        # empty label previews as blank tape (only the fed white space)
        label = Image.new("RGB", (1, lt200b.CANVAS_HEIGHT_PX), "white")

    with label:
        return _png_response(render_preview(label))


@app.post("/api/print")
def print_label():
    mac_addr = (request.form.get("mac") or "").strip()
    if not mac_addr:
        return jsonify(error="Please provide the MAC address of the printer."), 400

    assets, error = _parse_assets(strict=True)
    if error:
        return jsonify(error=error), 400
    if not assets:
        return jsonify(error="The label is empty. Add text or an image first."), 400

    try:
        with lt200b.create_label_image(assets) as label:
            job = create_job(label)
        _print(mac_addr, job)
    except bleak_exc.BleakDeviceNotFoundError:
        return jsonify(error=f"The device with MAC address {mac_addr} is not found. Is the device powered on?"), 400
    except Exception as e:
        return jsonify(error=f"Unexpected error: {e}"), 500

    config.save_config({"last_printer": mac_addr})
    return jsonify(ok=True)


@app.post("/api/scan")
def scan():
    try:
        devices = asyncio.run(BleakScanner.discover(timeout=5.0))
    except Exception as e:
        return jsonify(error=f"Scan failed: {e}"), 500

    return jsonify(devices=[
        {"name": d.name, "address": d.address}
        for d in devices if d.name
    ])


def _print(mac_addr, job):
    # bleak needs its own event loop; run it in a worker thread so Flask
    # request handling stays simple and synchronous
    error = []

    def run():
        try:
            asyncio.run(lt200b.print_image(mac_addr, job))
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if error:
        raise error[0]


if __name__ == "__main__":
    url = "http://127.0.0.1:8000"
    print(f"LT200B Label Maker running at {url} (local connections only)")

    # give the server a moment to start, then open the UI in the browser
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=8000, threaded=True)
