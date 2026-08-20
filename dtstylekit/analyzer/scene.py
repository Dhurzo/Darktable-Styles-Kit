"""Heuristic scene classification from analysis signals.

Combines luminance stats, histogram shape, EXIF tags and noise level to
emit a list of human-readable scene tags (e.g. ``"high-key"``, ``"portrait"``,
``"backlit"``, ``"night"``). The rules are intentionally simple — the VLM
produces the *aesthetic* tags; this module gives coarse, deterministic
ground truth that the prompt builder can rely on without re-implementing
the logic.
"""

from __future__ import annotations

from typing import Any

from .models import ImageAnalysis

# All thresholds are unitless floats in [0, 1] or luminance-means. They
# were chosen empirically from the architecture proposal §2.1; they can
# be tuned later without touching callers (the function signature is
# stable).

# Tonal luminance thresholds (see luminance.py SHADOWS_MAX / HIGHLIGHTS_MIN).
_TONAL_SHADOWS = 0.18
_TONAL_HIGHLIGHTS = 0.75

# Brightness buckets, applied to luminance mean.
_BRIGHT_HIGH_KEY = 0.65  # luma >= this → high-key
_BRIGHT_LOW_KEY = 0.30  # luma <  this → low-key

# Histogram dynamic-range heuristic: stdev across all channels.
_CONTRAST_HIGH = 0.18
_CONTRAST_LOW = 0.05

# Saturation buckets (HSV S, mean).
_SATURATION_HIGH = 0.55
_SATURATION_LOW = 0.10

# White balance R/B ratio — far from 1.0 indicates a warm or cool cast.
_WB_WARM = 1.15
_WB_COOL = 0.90

# Noise (variance on the central tile) buckets.
_NOISE_HIGH = 0.015
_NOISE_VERY_HIGH = 0.05


def detect_scene(analysis: ImageAnalysis) -> list[str]:
    """Return a list of heuristic scene tags for ``analysis``.

    The list is always non-empty when a valid analysis is supplied — even
    "neutral" or "unclassified" scenes get a tag — but may be empty for
    analyses that carry no signal (e.g. zero-pixel image with no EXIF).
    """
    tags: list[str] = []

    lum = analysis.luminance
    hist = analysis.histogram
    exif = analysis.exif

    # -- Brightness / key -------------------------------------------------
    mid_pct = lum.midtones_pct
    shadows_pct = lum.shadows_pct
    highlights_pct = lum.highlights_pct

    if lum.mean >= _BRIGHT_HIGH_KEY and highlights_pct > 0.40:
        tags.append("high-key")
    elif lum.mean <= _BRIGHT_LOW_KEY and shadows_pct > 0.55:
        tags.append("low-key")
    elif mid_pct > 0.65:
        tags.append("balanced-exposure")
    else:
        tags.append("mixed-exposure")

    # -- Contrast ---------------------------------------------------------
    # Use max channel stdev as a proxy for global contrast spread.
    ch_std = max(hist.std_red, hist.std_green, hist.std_blue)
    if ch_std >= _CONTRAST_HIGH:
        tags.append("high-contrast")
    elif ch_std <= _CONTRAST_LOW:
        tags.append("low-contrast")

    # -- Saturation -------------------------------------------------------
    if lum.saturation_mean >= _SATURATION_HIGH:
        tags.append("vivid")
    elif lum.saturation_mean <= _SATURATION_LOW:
        tags.append("desaturated")

    # -- White-balance / color cast --------------------------------------
    wb = lum.white_balance_ratio_rb
    if wb >= _WB_WARM:
        tags.append("warm-cast")
    elif wb <= _WB_COOL:
        tags.append("cool-cast")

    # -- Light direction (heuristic via histogram asymmetry) -------------
    # If the upper percentile is very bright while the 5th is dark, the
    # image likely has a strong key from behind/top (backlit/sidelit).
    p95_avg = (hist.p95_red + hist.p95_green + hist.p95_blue) / 3.0
    p5_avg = (hist.p5_red + hist.p5_green + hist.p5_blue) / 3.0
    if p95_avg >= 0.85 and p5_avg <= 0.10:
        tags.append("backlit")

    # -- Low-light / night ------------------------------------------------
    iso = _safe_float(exif.get("EXIF ISOSpeedRatings"))
    if lum.mean <= _BRIGHT_LOW_KEY and (
        analysis.noise_estimate >= _NOISE_HIGH or (iso is not None and iso >= 3200)
    ):
        tags.append("night")
    elif iso is not None and iso >= 1600 and lum.mean < 0.45:
        tags.append("low-light")

    # -- Golden hour / overcast (rough proxy via WB) ---------------------
    # Golden hour ≈ warm cast AND bright midtones AND not extreme contrast.
    if "warm-cast" in tags and mid_pct > 0.35 and ch_std < _CONTRAST_HIGH:
        # Coarse disambiguation: golden hour vs. indoor tungsten — both have
        # warm cast. Use ISO to bias toward "indoor-warm" only when very low
        # ISO + clearly indoors (we don't have a hard indoor signal here, so
        # we lean on the heuristic).
        if iso is None or iso <= 400:
            tags.append("golden-hour")

    # Overcast ≈ flat histogram + low contrast + cool/neutral cast.
    if ch_std <= _CONTRAST_LOW and abs(wb - 1.0) < 0.10 and lum.mean > 0.35:
        tags.append("overcast")

    # -- Indoor / outdoor cues (very rough) ------------------------------
    focal = _safe_float(exif.get("EXIF FocalLength"))
    aperture = _safe_float(exif.get("EXIF FNumber"))
    if focal is not None and aperture is not None:
        # Wide-angle + small aperture = likely outdoor landscape.
        if focal <= 35 and aperture <= 5.6:
            tags.append("outdoor")
        # Longer focal + wide aperture = likely portrait / indoor.
        if focal >= 50 and aperture >= 2.0:
            tags.append("portrait")

    # -- Noise-driven "high-iso" tag -------------------------------------
    if analysis.noise_estimate >= _NOISE_VERY_HIGH:
        tags.append("high-iso")

    # Fallback when no brightness bucket fired (degenerate analysis).
    if not tags:
        tags.append("unclassified")
    return tags


def _safe_float(value: Any) -> float | None:
    """Return ``value`` as float if coercible, else ``None``.

    EXIF scalars are emitted as Python ``int``/``float``/``str`` by
    :mod:`dtstylekit.analyzer.exif`; this helper normalises them for
    the heuristic rules without raising on odd values.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # Treat True/False as non-numeric so we don't confuse them with 1/0.
        return None
    if isinstance(value, int | float):
        return float(value)
    # ``values`` may be a list from ``tag.values``; pick the first scalar.
    if isinstance(value, list | tuple):
        for item in value:
            f = _safe_float(item)
            if f is not None:
                return f
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
