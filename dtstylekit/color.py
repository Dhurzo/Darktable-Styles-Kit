"""Colour and numeric helpers shared by analysis, validation and refinement."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np


def circular_mean(
    hues_deg: Sequence[float],
    weights: Sequence[float] | None = None,
) -> float:
    """Circular mean of hue angles in degrees (handles 350°+10°→0°).

    Returns a hue in ``[0, 360)``.  ``weights`` enables a weighted mean;
    empty input returns ``0.0``.
    """
    if not hues_deg:
        return 0.0
    radians = np.deg2rad(np.asarray(hues_deg, dtype=np.float32))
    if weights is None:
        sin_sum = float(np.sin(radians).sum())
        cos_sum = float(np.cos(radians).sum())
    else:
        weight_array: np.ndarray = np.asarray(weights, dtype=np.float32)
        sin_sum = float((np.sin(radians) * weight_array).sum())
        cos_sum = float((np.cos(radians) * weight_array).sum())
    if abs(sin_sum) < 1e-9 and abs(cos_sum) < 1e-9:
        return 0.0
    return float(np.rad2deg(np.arctan2(sin_sum, cos_sum)) % 360.0)


def circular_diff(a: float, b: float) -> float:
    """Shortest circular distance between two hue angles in degrees."""
    distance = abs(float(a) - float(b)) % 360.0
    return min(distance, 360.0 - distance)


_LUMA_R = 0.2126
_LUMA_G = 0.7152
_LUMA_B = 0.0722
_RED_CAST_R_OVER_G = 1.3
_RED_CAST_B_FACTOR = 1.2
_CRUSHED_LUMINANCE = 0.1
_CRUSHED_STD_LUMINANCE = 0.05
_BLOWN_LUMINANCE = 0.9
_BLOWN_HIGHLIGHTS_PCT = 0.5


def luminance_array(rgb: np.ndarray) -> np.ndarray:
    """Return the BT.709 luminance channel of an RGB float array."""
    return cast(np.ndarray, _LUMA_R * rgb[..., 0] + _LUMA_G * rgb[..., 1] + _LUMA_B * rgb[..., 2])


def hsv_saturation_array(rgb: np.ndarray) -> np.ndarray:
    """Return HSV saturation ``(max - min) / max`` for an RGB float array."""
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    return cast(np.ndarray, np.where(mx > 1e-9, (mx - mn) / np.maximum(mx, 1e-9), 0.0))


def is_red_cast(r_over_g: float, r_mean: float, b_mean: float) -> bool:
    """Shared red-cast heuristic used by render and look metrics."""
    return r_over_g > _RED_CAST_R_OVER_G and r_mean > b_mean * _RED_CAST_B_FACTOR


def is_crushed(mean_luminance: float, std_luminance: float | None = None) -> bool:
    """Shared crushed-shadow heuristic.

    ``std_luminance`` is optional because some profile layers (look profiles)
    do not carry std deviation yet.
    """
    if mean_luminance < _CRUSHED_LUMINANCE:
        return True
    return std_luminance is not None and std_luminance < _CRUSHED_STD_LUMINANCE


def is_blown(mean_luminance: float, highlights_pct: float) -> bool:
    """Shared blown-highlight heuristic used by render and look metrics."""
    return mean_luminance > _BLOWN_LUMINANCE or highlights_pct > _BLOWN_HIGHLIGHTS_PCT


def as_float(value: object, default: float = 0.0) -> float:
    """Narrow an arbitrary analysis value to float without bool leakage."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
