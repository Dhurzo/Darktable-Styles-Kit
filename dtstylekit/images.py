"""Shared image loading and encoding helpers."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image


def load_rgb_array(
    image_path: str | Path,
    max_dim: int | None = None,
) -> np.ndarray:
    """Load an image as an ``(H, W, 3)`` float32 RGB array in ``[0, 1]``.

    Args:
        image_path: Image file readable by Pillow.
        max_dim: Optional maximum side length; the image is downscaled
            in memory before conversion to an array.
    """
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        if max_dim is not None and max(rgb.size) > max_dim:
            rgb.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        arr: np.ndarray = np.asarray(rgb, dtype=np.float32) / 255.0
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    return arr


def encode_base64(
    image_path: str | Path,
    max_dim: int = 768,
    quality: int = 88,
) -> str:
    """Encode an image as a base64 JPEG, downscaled to ``max_dim``."""
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        if max(rgb.size) > max_dim:
            rgb.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
