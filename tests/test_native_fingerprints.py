"""Ordinary raster bytes must bind the external fingerprint claim."""

import hashlib

import pytest
from drawbridge.errors import ConversionOperationalError
from drawbridge.pdf_tools import _fingerprint_pixels
from PIL import Image


def test_fingerprint_claim_binds_actual_rgb_pixels(tmp_path):
    path = tmp_path / "raster.png"
    image = Image.new("RGB", (9, 8), "white")
    image.save(path)
    pixels = image.tobytes()
    record = {
        "width": 9,
        "height": 8,
        "pixel_sha256": hashlib.sha256(b"9:8:3:" + pixels).hexdigest(),
    }
    assert _fingerprint_pixels(path, record) == pixels
    image.putpixel((4, 3), (0, 0, 0))
    image.save(path)
    with pytest.raises(ConversionOperationalError, match="contradict canonical fingerprint"):
        _fingerprint_pixels(path, record)
