"""Luminance, saturation and tonal-distribution computation.

Takes the RGB float arrays already produced by the histogram module and
returns a :class:`LuminanceStats` instance covering:

  * mean / std of perceptual luminance (``0.299R + 0.587G + 0.114B``)
  * mean HSV saturation
  * red/blue ratio for white balance estimation
  * shadows / midtones / highlights percent of pixels
    (thresholds 0.18 and 0.75, per architecture_proposal §2.1)
"""

from __future__ import annotations

import colorsys
from collections.abc import Iterable

import numpy as np

from .models import LuminanceStats

# Standard ITU-R BT.601 luma weights.
LUMA_R = 0.299
LUMA_G = 0.587
LUMA_B = 0.114

# Tonal boundaries from architecture_proposal §2.1.
SHADOWS_MAX = 0.18
HIGHLIGHTS_MIN = 0.75

# Tiny epsilon to avoid divide-by-zero or all-empty scene detection.
_EPS = 1e-6


def compute_luminance_stats(rgb_arrays: Iterable[float] | np.ndarray) -> LuminanceStats:
    """Compute luminance / saturation / WB / tonal distribution.

    Args:
        rgb_arrays: Either an ``(N, 3)`` float ndarray in [0, 1] or any
            iterable that can be converted with :func:`np.asarray`. The
            histogram module produces arrays in this exact shape/range.

    Returns:
        Populated :class:`LuminanceStats` instance.
    """
    rgb = np.asarray(rgb_arrays, dtype=np.float32)
    if rgb.ndim == 3:
        rgb = rgb.reshape(-1, 3)
    if rgb.ndim != 2 or rgb.shape[1] != 3:
        raise ValueError(f"rgb_arrays must have shape (N, 3) or (H, W, 3), got {rgb.shape}")
    if rgb.size == 0:
        # Empty image edge case — return safe zeros.
        return LuminanceStats(white_balance_ratio_rb=1.0)

    # Clamp to [0, 1] in case the histogram pass produced minor float drift.
    np.clip(rgb, 0.0, 1.0, out=rgb)

    r = rgb[:, 0]
    g = rgb[:, 1]
    b = rgb[:, 2]

    luma = LUMA_R * r + LUMA_G * g + LUMA_B * b

    saturation_mean = _mean_saturation(rgb)
    wb_ratio = _white_balance_ratio(float(r.mean()), float(b.mean()))

    shadows, midtones, highlights = _tonal_distribution(luma)

    return LuminanceStats(
        mean=float(luma.mean()),
        std=float(luma.std()),
        saturation_mean=saturation_mean,
        white_balance_ratio_rb=wb_ratio,
        shadows_pct=shadows,
        midtones_pct=midtones,
        highlights_pct=highlights,
    )


def _mean_saturation(rgb: np.ndarray) -> float:
    """Mean HSV saturation across all pixels (in [0, 1])."""
    # colorsys works pixel-by-pixel; for very large arrays this would be slow,
    # but analyzer is already operating on downsampled data, so it is fine.
    flat = rgb.reshape(-1, 3)
    total = 0.0
    count = flat.shape[0]
    for px in flat:
        _, _, s = colorsys.rgb_to_hls(float(px[0]), float(px[1]), float(px[2]))
        # saturation ``s`` is what we need (HSV-style saturation in [0, 1]).
        total += s
    return total / max(count, 1)


def _white_balance_ratio(mean_r: float, mean_b: float) -> float:
    """R/B ratio used as a coarse white-balance indicator.

    Returned value is clamped to ``[0.1, 10.0]`` to avoid extreme outliers
    dominating downstream heuristics.
    """
    ratio = mean_r / (mean_b + _EPS)
    return float(min(max(ratio, 0.1), 10.0))


def _tonal_distribution(luma: np.ndarray) -> tuple[float, float, float]:
    """Return (shadows%, midtones%, highlights%) summing to ~1.0."""
    shadows = float(np.mean(luma < SHADOWS_MAX))
    highlights = float(np.mean(luma >= HIGHLIGHTS_MIN))
    midtones = float(np.mean((luma >= SHADOWS_MAX) & (luma < HIGHLIGHTS_MIN)))
    # Normalise to guard against floating-point drift.
    total = shadows + midtones + highlights
    if total > _EPS:
        shadows /= total
        midtones /= total
        highlights /= total
        return shadows, midtones, highlights
    return 0.0, 0.0, 0.0
