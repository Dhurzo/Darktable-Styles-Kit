"""Image analysis orchestrator.

Combines every analyzer module into a single :func:`analyze_image` call
that loads the file once and runs histogram, luminance, EXIF, noise and
scene-classification passes in order. Errors in any single sub-extractor
do not abort the whole pipeline — they are recorded in
``ImageAnalysis.errors`` and the rest of the analysis still completes.

The orchestrator is intentionally *pure* (apart from disk I/O for loading
the image and reading EXIF) so it can be unit-tested with synthetic
fixtures and reused by batch tools.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .exif import extract_exif
from .histogram import compute_histogram
from .luminance import compute_luminance_stats
from .models import HistogramStats, ImageAnalysis, LuminanceStats
from .noise import estimate_noise
from .scene import detect_scene


def analyze_image(
    path: str | Path,
    *,
    bins: int = 64,
    exif_path: str | Path | None = None,
) -> ImageAnalysis:
    """Run the full analyzer on ``path`` and return an :class:`ImageAnalysis`.

    Args:
        path: Path to a JPEG / TIFF / PNG readable by Pillow. RAW formats are
            intentionally rejected (the MVP expects the user to export to TIFF
            first).
        bins: Histogram bins per channel (default 64).
        exif_path: Optional path to use for EXIF. Defaults to ``path`` itself.
            When ``path`` is a side-car ``.xmp`` or other non-image file with
            embedded preview, callers may pass the preview path to drive
            EXIF extraction from the actual raster. If ``None`` falls back
            to ``path``.

    Returns:
        Always returns an ``ImageAnalysis`` instance. Even on failure the
        instance is fully populated; the failure is recorded in
        ``errors``. This makes batch callers' life simpler — they always
        get the same shape back.
    """
    p = Path(path)
    analysis = ImageAnalysis()
    errors: list[str] = []

    # -- Load image ------------------------------------------------------
    try:
        image = Image.open(p)
        # Force materialisation so corrupt-after-header files surface here
        # rather than at histogram time.
        image.load()
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        return _failed_analysis(p, [f"image load failed: {exc!s}"])

    analysis.width, analysis.height = image.size
    analysis.mode = image.mode
    analysis.format = image.format or ""

    # -- Histogram + raw RGB channels (re-used by luminance) -------------
    try:
        rgb_image = _ensure_rgb(image)
        rgb_array = _to_float_array(rgb_image)
        analysis.histogram = compute_histogram(rgb_image, bins=bins)
        analysis.luminance = compute_luminance_stats(rgb_array)
    except Exception as exc:  # pragma: no cover — defensive
        errors.append(f"histogram/luminance failed: {exc!s}")
        analysis.histogram = HistogramStats(bins=bins)
        analysis.luminance = LuminanceStats()

    # -- Noise -----------------------------------------------------------
    try:
        analysis.noise_estimate = estimate_noise(image)
    except Exception as exc:  # pragma: no cover — defensive
        errors.append(f"noise estimation failed: {exc!s}")
        analysis.noise_estimate = 0.0

    # -- EXIF ------------------------------------------------------------
    exif_source = Path(exif_path) if exif_path is not None else p
    try:
        analysis.exif = extract_exif(str(exif_source))
    except Exception as exc:  # pragma: no cover — defensive
        errors.append(f"exif extraction failed: {exc!s}")
        analysis.exif = {}

    if not analysis.exif:
        # Use a sentinel tag so downstream prompt builders can tell the
        # difference between "EXIF present but empty after filtering" and
        # "EXIF absent entirely".
        errors.append("EXIF missing")

    # -- Scene classification --------------------------------------------
    try:
        analysis.scene_tags = detect_scene(analysis)
    except Exception as exc:  # pragma: no cover — defensive
        errors.append(f"scene detection failed: {exc!s}")
        analysis.scene_tags = []

    analysis.errors = errors
    return analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_rgb(image: Image.Image) -> Image.Image:
    """Convert any PIL image into RGB (drops alpha)."""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "P"):
        return image.convert("RGB")
    return image.convert("RGB")


def _to_float_array(image: Image.Image) -> "object":  # numpy.ndarray — kept untyped
    """Return the RGB image as a ``(H, W, 3)`` float32 array in [0, 1]."""
    import numpy as np

    arr = np.asarray(image, dtype=np.float32) / 255.0
    if arr.ndim == 2:
        # Grayscale input — broadcast to 3 identical channels.
        arr = np.stack([arr, arr, arr], axis=-1)
    return arr


def _failed_analysis(source: Path, errors: list[str]) -> ImageAnalysis:
    """Build a structured "all-empty" analysis with the given errors."""
    analysis = ImageAnalysis()
    analysis.width = 0
    analysis.height = 0
    analysis.mode = ""
    analysis.format = source.suffix.lstrip(".").upper() if source.suffix else ""
    analysis.errors = list(errors)
    return analysis
