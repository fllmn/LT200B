import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from flask import Flask
from flask.testing import FlaskClient

from lt200b.app import create_app
from lt200b.config import ConfigStore


def make_client(tmp_path: Path) -> FlaskClient:
    app: Flask = create_app(ConfigStore(config_dir=tmp_path))
    app.config["TESTING"] = True
    return app.test_client()


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def test_index_is_served_without_caching(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/")
    assert response.status_code == 200
    assert b"LT200B Label Maker" in response.data
    assert response.headers["Cache-Control"] == "no-store"


def test_preview_empty_label_is_blank_tape(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/preview", data={"assets": "[]"}, content_type="multipart/form-data"
    )
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    image = Image.open(io.BytesIO(response.data))
    assert not (image.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox() or [])


def test_preview_with_text_asset(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/preview",
        data={
            "assets": json.dumps([{"type": "text", "text": "Hej", "font_size": 4}]),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    image = np.array(Image.open(io.BytesIO(response.data)).convert("L"))
    assert image.min() < 128  # contains ink


def test_preview_with_image_asset_and_invert(tmp_path: Path) -> None:
    black_square = Image.new("RGB", (64, 64), "black")
    data = {
        "assets": json.dumps([
            {"type": "image", "file": 0, "invert": False},
            {"type": "image", "file": 0, "invert": True},
        ]),
        "image-0": (io.BytesIO(png_bytes(black_square)), "square.png", "image/png"),
    }
    response = make_client(tmp_path).post("/api/preview", data=data)
    assert response.status_code == 200
    # one black square and one white square side by side: preview must
    # contain both ink and blank areas
    array = np.array(Image.open(io.BytesIO(response.data)).convert("L"))
    assert (array < 128).any() and (array > 128).any()


def test_preview_rejects_bad_font_size(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/preview",
        data={"assets": json.dumps([{"type": "text", "text": "x", "font_size": 99}])},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert b"Font size must be between" in response.data


def test_preview_ignores_empty_assets(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/preview",
        data={"assets": json.dumps([{"type": "text", "text": "   "}])},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200


def test_print_requires_mac(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/print",
        data={"assets": json.dumps([{"type": "text", "text": "x"}])},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert b"MAC address" in response.data


def test_print_rejects_empty_label(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/print", data={"mac": "00:11:22:33:44:55", "assets": "[]"}
    )
    assert response.status_code == 400
    assert b"label is empty" in response.data


def test_print_rejects_empty_text_field(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/print",
        data={
            "mac": "00:11:22:33:44:55",
            "assets": json.dumps([{"type": "text", "text": "   "}]),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert b"text field is empty" in response.data


def test_print_rejects_missing_image(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/print",
        data={
            "mac": "00:11:22:33:44:55",
            "assets": json.dumps([{"type": "image", "file": 0}]),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert b"no file selected" in response.data


def test_print_rejects_malformed_assets(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/print", data={"mac": "00:11:22:33:44:55", "assets": "{not json"}
    )
    assert response.status_code == 400
    assert b"Malformed" in response.data


def test_all_routes_are_registered(tmp_path: Path) -> None:
    app = create_app(ConfigStore(config_dir=tmp_path))
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert {"/", "/api/preview", "/api/print", "/api/scan"} <= rules
