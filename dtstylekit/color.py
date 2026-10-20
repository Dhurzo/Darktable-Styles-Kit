"""Colour and numeric helpers shared by analysis, validation and refinement."""

from __future__ import annotations

from collections.abc import Sequence

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


def as_float(value: object, default: float = 0.0) -> float:
    """Narrow an arbitrary analysis value to float without bool leakage."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
