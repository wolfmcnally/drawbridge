"""Non-PDF image adapters using Pillow; no PDF engine or converter dependency."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .errors import DrawbridgeError

MAX_IMAGE_PIXELS = 256 * 1024 * 1024 // 3


def _open(path: Path):
    try:
        image = Image.open(path)
        if image.width * image.height > MAX_IMAGE_PIXELS:
            image.close()
            raise DrawbridgeError("Image exceeds raster byte admission limit")
        return image
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise DrawbridgeError("image could not be decoded") from exc


def _dpi(image) -> tuple[float, float]:
    raw = image.info.get("dpi", (96, 96))
    try:
        return tuple(float(v) if float(v) > 0 else 96.0 for v in raw[:2])
    except (ValueError, TypeError):
        return (96.0, 96.0)


def image_size(path: Path, page_number: int = 1) -> tuple[float, float]:
    if page_number != 1:
        raise ValueError("image page number must be 1")
    with _open(path) as image:
        x, y = _dpi(image)
        return image.width * 72 / x, image.height * 72 / y


def _rgb(image):
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        white = Image.new("RGB", image.size, "white")
        white.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        return white
    return image.convert("RGB")


def image_jpeg(image_path: Path, *, max_side: int = 1568, quality: int = 85) -> bytes:
    """First image frame as bounded RGB JPEG, compositing alpha onto white."""
    if type(max_side) is not int or max_side < 1 or not 1 <= quality <= 95:
        raise ValueError("invalid JPEG size/quality")
    try:
        with _open(Path(image_path)) as source:
            image = _rgb(source)
            try:
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                image.save(out, format="JPEG", quality=quality)
                return out.getvalue()
            finally:
                image.close()
    except (OSError, ValueError) as exc:
        raise DrawbridgeError("image could not be decoded") from exc


def render_image(
    path: Path,
    page_number: int,
    target: Path,
    *,
    dpi: float = 300,
    rotation: int = 0,
    clip=None,
) -> Path:
    if page_number != 1 or dpi <= 0 or rotation not in {0, 90, 180, 270}:
        raise ValueError("invalid image render options")
    with _open(path) as source:
        sx, sy = _dpi(source)
        width, height = source.width * 72 / sx, source.height * 72 / sy
        box = clip or (0, 0, width, height)
        pixels = (
            max(1, round((box[2] - box[0]) * dpi / 72)),
            max(1, round((box[3] - box[1]) * dpi / 72)),
        )
        if pixels[0] * pixels[1] > MAX_IMAGE_PIXELS:
            raise DrawbridgeError("Image exceeds raster byte admission limit")
        if not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height:
            raise ValueError("image clip is outside bounds")
        image = source.crop(
            tuple(v * (sx if i % 2 == 0 else sy) / 72 for i, v in enumerate(box))
        )
        try:
            rgb = _rgb(image)
            image.close()
            image = rgb
            resized = image.resize(pixels, Image.Resampling.BICUBIC)
            image.close()
            image = resized
            rotated = image.rotate(-rotation, expand=True)
            image.close()
            image = rotated
            image.save(target, format="PPM" if target.suffix == ".pnm" else "PNG")
        finally:
            image.close()
    return target


def image_band_cuts(
    path: Path, page_number: int, band_height: float
) -> tuple[float, ...]:
    if band_height <= 0:
        raise ValueError("band height must be positive")
    width, height = image_size(path, page_number)
    if height <= band_height:
        return ()
    scale = min(1.0, (40_000_000 / max(width * height, 1.0)) ** 0.5)
    with _open(path) as source:
        preview = source.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.BILINEAR,
        )
        gray = preview.convert("L")
        preview.close()
        data = gray.tobytes()
        columns, rows = gray.size
        gray.close()
    spread = []
    for row in range(rows):
        line = data[row * columns : (row + 1) * columns]
        spread.append(max(line) - min(line) if line else 0)
    cuts = []
    top = 0.0
    while height - top > band_height:
        last = min(rows - 1, int((top + band_height) * scale))
        first = max(int(top * scale) + 1, int((top + band_height * 0.75) * scale))
        first = min(first, last)
        row = min(range(first, last + 1), key=lambda c: (spread[c], -c))
        cut = row / scale
        if cut <= top:
            cut = top + band_height
        cuts.append(cut)
        top = cut
    return tuple(cuts)
