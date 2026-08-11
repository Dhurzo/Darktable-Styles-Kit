"""dtstylekit.analyzer - Image analysis (histogram, EXIF, scene detection).

Public surface:

* :func:`analyze_image` — top-level orchestrator (use this 99% of the time).
* Sub-module functions for fine-grained access (e.g. when batch-processing
  you may want to share a single histogram across many analyses).
* :class:`ImageAnalysis` — dataclass returned by :func:`analyze_image`,
  fully JSON-serializable via :meth:`to_dict` / :meth:`to_prompt_dict`.
"""

from __future__ import annotations

from .exif import extract_exif
from .histogram import compute_histogram
from .luminance import compute_luminance_stats
from .models import HistogramStats, ImageAnalysis, LuminanceStats
from .noise import estimate_noise
from .pipeline import analyze_image
from .scene import detect_scene

__all__ = [
    # Orchestrator
    "analyze_image",
    # Sub-module functions
    "compute_histogram",
    "compute_luminance_stats",
    "estimate_noise",
    "extract_exif",
    "detect_scene",
    # Data classes
    "HistogramStats",
    "ImageAnalysis",
    "LuminanceStats",
]
