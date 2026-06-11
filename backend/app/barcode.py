"""
Server-side barcode decoding from an uploaded photo (adapted from a sibling project).

A full, natively-autofocused still photo + zxing-cpp's detector (rotation / off-centre /
downscale tolerant) is far more forgiving than a single client-side video pass, so the
barcode need only be visible and in focus — not perfectly framed.
"""
from __future__ import annotations

import io

import numpy as np
import zxingcpp as zxing_cpp
from PIL import Image, ImageOps

_FORMATS = (
    zxing_cpp.BarcodeFormat.EAN13
    | zxing_cpp.BarcodeFormat.EAN8
    | zxing_cpp.BarcodeFormat.UPCA
    | zxing_cpp.BarcodeFormat.UPCE
)


def decode_isbn_from_image(data: bytes) -> str | None:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    arr = np.asarray(img.convert("L"))
    for r in zxing_cpp.read_barcodes(arr, formats=_FORMATS, try_rotate=True, try_downscale=True):
        if r.text:
            return r.text
    return None
