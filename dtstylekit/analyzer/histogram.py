"""Per-channel histogram and basic statistics.

Computes a downsampled (default 64 bin) histogram per RGB channel plus
per-channel mean / standard deviation / 5/50/95 percentiles. Inputs are
PIL ``Image.Image`` instances; consumers (typically ``pipeline.py``) handle
loading.

All numeric stats (mean/std/percentiles) are expressed in the
[0.0, 1.0] normalised range so they match the rest of the analyzer.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .models import HistogramStats


def compute_histogram(image: Image.Image, bins: int = 64) -> HistogramStats:
    """Compute per-channel histogram + stats for an RGB image.

    Args:
        image: Input image. Will be converted to RGB if needed.
        bins: Number of bins per channel (default 64).

    Returns:
        :class:`HistogramStats` with arrays of length ``bins`` and
        normalised floats for mean/std/percentiles.
    """
    if bins <= 0:
        raise ValueError(f"bins must be a positive integer, got {bins}")

    rgb = _ensure_rgb(image)
    arr = np.asarray(rgb, dtype=np.float32) / 255.0  # H, W, 3 in [0,1]
    flat = arr.reshape(-1, 3)  # N x 3

    red_hist, _ = _hist_channel(flat[:, 0], bins)
    green_hist, _ = _hist_channel(flat[:, 1], bins)
    blue_hist, _ = _hist_channel(flat[:, 2], bins)

    return HistogramStats(
        bins=bins,
        red=red_hist.tolist(),
        green=green_hist.tolist(),
        blue=blue_hist.tolist(),
        mean_red=float(flat[:, 0].mean()),
        mean_green=float(flat[:, 1].mean()),
        mean_blue=float(flat[:, 2].mean()),
        std_red=float(flat[:, 0].std()),
        std_green=float(flat[:, 1].std()),
        std_blue=float(flat[:, 2].std()),
        p5_red=float(np.percentile(flat[:, 0], 5)),
        p50_red=float(np.percentile(flat[:, 0], 50)),
        p95_red=float(np.percentile(flat[:, 0], 95)),
        p5_green=float(np.percentile(flat[:, 1], 5)),
        p50_green=float(np.percentile(flat[:, 1], 50)),
        p95_green=float(np.percentile(flat[:, 1], 95)),
        p5_blue=float(np.percentile(flat[:, 2], 5)),
        p50_blue=float(np.percentile(flat[:, 2], 50)),
        p95_blue=float(np.percentile(flat[:, 2], 95)),
    )


def _hist_channel(channel: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute a histogram of a single channel over [0, 1] into ``bins`` bins."""
    counts, edges = np.histogram(channel, bins=bins, range=(0.0, 1.0))
    return counts.astype(int), edges


def _ensure_rgb(image: Image.Image) -> Image.Image:
    """Convert any PIL image into an RGB image, dropping alpha if present."""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "P"):
        return image.convert("RGB")
    # Generic fallback: convert whatever mode the file is in.
    return image.convert("RGB")
