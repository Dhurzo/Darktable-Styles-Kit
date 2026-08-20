"""Image analysis data model and serialization.

Defines the ``ImageAnalysis`` dataclass that aggregates all signals extracted
from an input JPEG/TIFF by the analyzer modules. Provides both a full ``to_dict``
view (for JSON persistence / debugging) and a compact ``to_prompt_dict`` view
that is sized for inclusion in a VLM prompt (~200-500 tokens).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HistogramStats:
    """Per-channel histogram and summary statistics.

    All arrays are length ``bins`` (default 64). All numerical stats are in
    the [0.0, 1.0] float range, expressed as normalised pixel intensities.
    """

    bins: int = 64
    red: list[int] = field(default_factory=list)
    green: list[int] = field(default_factory=list)
    blue: list[int] = field(default_factory=list)
    mean_red: float = 0.0
    mean_green: float = 0.0
    mean_blue: float = 0.0
    std_red: float = 0.0
    std_green: float = 0.0
    std_blue: float = 0.0
    p5_red: float = 0.0
    p50_red: float = 0.0
    p95_red: float = 0.0
    p5_green: float = 0.0
    p50_green: float = 0.0
    p95_green: float = 0.0
    p5_blue: float = 0.0
    p50_blue: float = 0.0
    p95_blue: float = 0.0


@dataclass
class LuminanceStats:
    """Luminance (brightness/contrast) and tonal distribution."""

    mean: float = 0.0
    std: float = 0.0
    saturation_mean: float = 0.0
    white_balance_ratio_rb: float = 1.0
    shadows_pct: float = 0.0
    midtones_pct: float = 0.0
    highlights_pct: float = 0.0


@dataclass
class ImageAnalysis:
    """Aggregate image analysis result.

    Compactly describes visual signals from an input image. Designed to be
    serialised to JSON (~200-500 tokens for the compact VLM view).
    """

    width: int = 0
    height: int = 0
    mode: str = ""
    format: str = ""
    histogram: HistogramStats = field(default_factory=HistogramStats)
    luminance: LuminanceStats = field(default_factory=LuminanceStats)
    noise_estimate: float = 0.0
    exif: dict[str, Any] = field(default_factory=dict)
    scene_tags: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Full dataclass view, recursing into nested dataclasses.

        Returns a plain ``dict`` representation suitable for ``json.dump``.
        """
        return asdict(self)

    def to_prompt_dict(self, max_bins_in_prompt: int = 16) -> dict[str, Any]:
        """Compact view tailored for inclusion in a VLM prompt.

        Histograms are downsampled to ``max_bins_in_prompt`` bins to keep
        the total JSON under ~500 tokens even for high-resolution sources.
        """
        hist = self.histogram
        if hist.bins > max_bins_in_prompt and max_bins_in_prompt > 0:
            factor = hist.bins // max_bins_in_prompt
            # Truncate the right edge if bins is not an exact multiple
            usable = (len(hist.red) // factor) * factor
            red_compact = _downsample_bins(hist.red[:usable], factor)
            green_compact = _downsample_bins(hist.green[:usable], factor)
            blue_compact = _downsample_bins(hist.blue[:usable], factor)
        else:
            red_compact = list(hist.red)
            green_compact = list(hist.green)
            blue_compact = list(hist.blue)

        return {
            "dimensions": {"w": self.width, "h": self.height, "format": self.format},
            "histogram": {
                "bins": len(red_compact),
                "r": red_compact,
                "g": green_compact,
                "b": blue_compact,
                "mean": [hist.mean_red, hist.mean_green, hist.mean_blue],
                "std": [hist.std_red, hist.std_green, hist.std_blue],
                "p5": [hist.p5_red, hist.p5_green, hist.p5_blue],
                "p50": [hist.p50_red, hist.p50_green, hist.p50_blue],
                "p95": [hist.p95_red, hist.p95_green, hist.p95_blue],
            },
            "luminance": {
                "mean": self.luminance.mean,
                "std": self.luminance.std,
                "saturation": self.luminance.saturation_mean,
                "wb_rb_ratio": self.luminance.white_balance_ratio_rb,
                "tonal": [
                    self.luminance.shadows_pct,
                    self.luminance.midtones_pct,
                    self.luminance.highlights_pct,
                ],
            },
            "noise": self.noise_estimate,
            "exif": _filter_exif_for_prompt(self.exif),
            "scene_tags": self.scene_tags,
        }


def _downsample_bins(bins: list[int], factor: int) -> list[int]:
    """Sum consecutive ``factor`` bins into one (used to compact histograms)."""
    if factor <= 1:
        return list(bins)
    return [sum(bins[i : i + factor]) for i in range(0, len(bins), factor)]


# EXIF keys safe/useful to expose to a VLM. ``private`` exifread tags
# (numeric IDs) are always promoted to ``exif:<id>`` strings by ``exif.py``
# and pass through this filter as-is.
_PROMPT_EXIF_KEYS = {
    "EXIF FNumber",  # aperture
    "EXIF ExposureTime",  # shutter speed
    "EXIF ISOSpeedRatings",  # ISO
    "EXIF FocalLength",
    "EXIF WhiteBalance",
    "EXIF Make",
    "EXIF Model",
    "EXIF DateTimeOriginal",
    "EXIF Flash",
    "Image Make",
    "Image Model",
    "Image DateTime",
}


def _filter_exif_for_prompt(exif: dict[str, Any]) -> dict[str, Any]:
    """Keep only VLM-relevant EXIF keys, dropping unknown/private noise."""
    if not exif:
        return {}
    return {k: _stringify(v) for k, v in exif.items() if k in _PROMPT_EXIF_KEYS}


def _stringify(value: Any) -> Any:
    """Make a value JSON-friendly (exifread returns ``IfdTag`` objects)."""
    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_stringify(v) for v in value]
    # exifread.classes.IfdTag and friends implement __str__
    return str(value)
