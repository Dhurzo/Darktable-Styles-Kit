"""Rough noise estimator.

Uses variance of a downsampled luminance field as a fast statistical proxy
for sensor noise. The pipeline computes noise on a 64×64 downsample of
the image so the estimator is roughly resolution-independent.

The implementation follows the architecture_proposal §2.1: take a
central 32×32 "flat" tile, measure luminance variance. Higher variance
→ noisier capture. For images too small to extract a 32×32 tile, we
fall back to either: (a) the entire image variance, or (b) zero.

A positive scalar is always returned (the analyses are float scalars
consumed downstream).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Luminance weights -- keep consistent with luminance.py.
LUMA_R = 0.299
LUMA_G = 0.587
LUMA_B = 0.114

# Tile size targeted after downsampling. If the source image is smaller
# than this, we fall back to the entire (downsampled) image.
_TARGET_TILE = 32

# Downsample target (longest side) used for noise estimation.
_DOWNSAMPLE_LONG_SIDE = 256


def estimate_noise(image: Image.Image) -> float:
    """Estimate image sensor/shot noise as a positive float variance.

    Args:
        image: PIL ``Image.Image`` (any mode; will be converted to RGB).

    Returns:
        A positive float representing luminance variance on a downsampled
        central tile. Always > 0.0 — small images that produce zero
        variance on the central tile return ``1e-6`` instead.
    """
    rgb = _ensure_rgb(image)
    # Downsample to a manageable size first.
    ds = _downsample_for_noise(rgb)
    arr = np.asarray(ds, dtype=np.float32) / 255.0  # H, W, 3

    h, w = arr.shape[:2]
    if h == 0 or w == 0:
        return 1e-6

    luma = LUMA_R * arr[:, :, 0] + LUMA_G * arr[:, :, 1] + LUMA_B * arr[:, :, 2]  # H, W

    tile = _central_tile(luma)
    variance = float(tile.var())
    # Guard against zero/negative variance — happens on flat synthetic tiles.
    return max(variance, 1e-6)


def _ensure_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    return image.convert("RGB")


def _downsample_for_noise(image: Image.Image) -> Image.Image:
    """Resize so the longest side equals ``_DOWNSAMPLE_LONG_SIDE`` pixels."""
    w, h = image.size
    long_side = max(w, h)
    if long_side <= _DOWNSAMPLE_LONG_SIDE:
        return image
    factor = _DOWNSAMPLE_LONG_SIDE / long_side
    new_w = max(1, int(round(w * factor)))
    new_h = max(1, int(round(h * factor)))
    return image.resize((new_w, new_h), Image.Resampling.BILINEAR)


def _central_tile(luma: np.ndarray) -> np.ndarray:
    """Return either a ``_TARGET_TILE``×``_TARGET_TILE`` central crop or the
    full image if the source is too small.
    """
    h, w = luma.shape
    t = _TARGET_TILE
    if h < t or w < t:
        return luma
    cy, cx = h // 2, w // 2
    y0 = max(0, cy - t // 2)
    x0 = max(0, cx - t // 2)
    y1 = min(h, y0 + t)
    x1 = min(w, x0 + t)
    return luma[y0:y1, x0:x1]
