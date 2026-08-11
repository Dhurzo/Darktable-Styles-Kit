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


def analyze_reference_hues(reference_paths: list[Path]) -> dict:
    """
    Extract dominant hue and saturation per tonal range (shadows/midtones/highlights)
    from a list of reference images. Returns weighted average values across references.
    
    Only computes hue where saturation is above threshold and enough valid pixels exist.
    Returns None for hue if insufficient color data (lets VLM decide visually).
    
    Args:
        reference_paths: List of paths to reference JPEG/PNG images.
        
    Returns:
        Dict with keys: shadows_hue, midtones_hue, highlights_hue (or None),
                        shadows_sat, midtones_sat, highlights_sat,
                        shadows_hue_confidence, midtones_hue_confidence, highlights_hue_confidence
    """
    import numpy as np
    from PIL import Image
    
    # Configuration
    MIN_SATURATION_FOR_HUE = 0.12      # Minimum saturation to compute meaningful hue
    MIN_VALID_PIXELS = 50              # Minimum pixels with valid color in tonal range
    SATURATION_WEIGHT_POWER = 2.0      # Power for saturation weighting (higher = more weight to saturated pixels)
    
    # Collect per-reference data
    ref_data = []
    
    for ref_path in reference_paths:
        try:
            img = Image.open(ref_path).convert('RGB')
            arr = np.asarray(img, dtype=np.float32) / 255.0
            h, w = arr.shape[:2]
            
            # HSV-like conversion
            max_c = np.max(arr, axis=2)
            min_c = np.min(arr, axis=2)
            delta = max_c - min_c
            
            # Luminance
            lum = 0.2126 * arr[:,:,0] + 0.7152 * arr[:,:,1] + 0.0722 * arr[:,:,2]
            
            # Tonal masks
            shadows_mask = lum < 0.25
            midtones_mask = (lum >= 0.25) & (lum < 0.75)
            highlights_mask = lum >= 0.75
            
            def analyze_tonal_range(mask, tonal_name):
                """Analyze a single tonal range. Returns (hue, saturation, pixel_count, confidence)."""
                if not np.any(mask):
                    return None, 0.0, 0, 0.0
                
                # Saturation in this range
                sat_in_range = delta[mask]
                mean_sat = float(np.mean(sat_in_range))
                
                # Only analyze hue if saturation is sufficient
                if mean_sat < MIN_SATURATION_FOR_HUE:
                    return None, mean_sat, 0, 0.0
                
                # Valid pixels: in tonal range AND have sufficient saturation
                valid_mask = mask & (delta > MIN_SATURATION_FOR_HUE * 0.5)
                valid_count = int(np.sum(valid_mask))
                
                if valid_count < MIN_VALID_PIXELS:
                    return None, mean_sat, valid_count, 0.0
                
                # Extract RGB for valid pixels
                r = arr[valid_mask, 0]
                g = arr[valid_mask, 1]
                b = arr[valid_mask, 2]
                
                max_c = np.maximum(np.maximum(r, g), b)
                min_c = np.minimum(np.minimum(r, g), b)
                delta_c = max_c - min_c
                
                # Compute hue
                hue = np.zeros_like(r)
                idx = delta_c > 0.01
                r_idx = (max_c == r) & idx
                g_idx = (max_c == g) & idx
                b_idx = (max_c == b) & idx
                
                hue[r_idx] = (60 * ((g[r_idx] - b[r_idx]) / delta_c[r_idx]) + 360) % 360
                hue[g_idx] = (60 * ((b[g_idx] - r[g_idx]) / delta_c[g_idx]) + 120) % 360
                hue[b_idx] = (60 * ((r[b_idx] - g[b_idx]) / delta_c[b_idx]) + 240) % 360
                
                # Weight by saturation^power (more saturated pixels dominate)
                weights = delta_c[idx] ** SATURATION_WEIGHT_POWER
                if np.sum(weights) > 0:
                    weighted_hue = float(np.average(hue[idx], weights=weights))
                else:
                    weighted_hue = 0.0
                
                # Confidence based on valid pixel count and saturation
                confidence = min(1.0, valid_count / (MIN_VALID_PIXELS * 10)) * min(1.0, mean_sat / 0.3)
                
                return weighted_hue, mean_sat, valid_count, confidence
            
            def mean_saturation(mask):
                if not np.any(mask):
                    return 0.0
                return float(np.mean(delta[mask]))
            
            shadows = analyze_tonal_range(shadows_mask, "shadows")
            midtones = analyze_tonal_range(midtones_mask, "midtones")
            highlights = analyze_tonal_range(highlights_mask, "highlights")
            
            if shadows and midtones and highlights:
                ref_data.append({
                    "shadows_hue": shadows[0],
                    "shadows_sat": shadows[1],
                    "shadows_conf": shadows[3],
                    "midtones_hue": midtones[0],
                    "midtones_sat": midtones[1],
                    "midtones_conf": midtones[3],
                    "highlights_hue": highlights[0],
                    "highlights_sat": highlights[1],
                    "highlights_conf": highlights[3],
                })
            else:
                # Still collect saturation even if hue failed
                ref_data.append({
                    "shadows_hue": shadows[0] if shadows else None,
                    "shadows_sat": shadows[1] if shadows else 0.0,
                    "shadows_conf": shadows[3] if shadows else 0.0,
                    "midtones_hue": midtones[0] if midtones else None,
                    "midtones_sat": midtones[1] if midtones else 0.0,
                    "midtones_conf": midtones[3] if midtones else 0.0,
                    "highlights_hue": highlights[0] if highlights else None,
                    "highlights_sat": highlights[1] if highlights else 0.0,
                    "highlights_conf": highlights[3] if highlights else 0.0,
                })
                
        except Exception as e:
            print(f"Warning: failed to analyze reference {ref_path}: {e}")
            continue
    
    if not ref_data:
        return {
            "shadows_hue": None, "midtones_hue": None, "highlights_hue": None,
            "shadows_sat": 0.0, "midtones_sat": 0.0, "highlights_sat": 0.0,
            "shadows_hue_confidence": 0.0, "midtones_hue_confidence": 0.0, "highlights_hue_confidence": 0.0,
        }
    
    # Weighted average by confidence (not median!)
    def weighted_avg(key_hue, key_conf):
        hues = [d[key_hue] for d in ref_data if d[key_hue] is not None]
        confs = [d[key_conf] for d in ref_data if d[key_hue] is not None]
        if not hues or sum(confs) == 0:
            return None
        return float(np.average(hues, weights=confs))
    
    def avg_sat(key_sat):
        sats = [d[key_sat] for d in ref_data]
        return float(np.mean(sats)) if sats else 0.0
    
    # Overall confidence per tonal range
    def avg_conf(key_conf):
        confs = [d[key_conf] for d in ref_data]
        return float(np.mean(confs)) if confs else 0.0
    
    return {
        "shadows_hue": weighted_avg("shadows_hue", "shadows_conf"),
        "midtones_hue": weighted_avg("midtones_hue", "midtones_conf"),
        "highlights_hue": weighted_avg("highlights_hue", "highlights_conf"),
        "shadows_sat": avg_sat("shadows_sat"),
        "midtones_sat": avg_sat("midtones_sat"),
        "highlights_sat": avg_sat("highlights_sat"),
        "shadows_hue_confidence": avg_conf("shadows_conf"),
        "midtones_hue_confidence": avg_conf("midtones_conf"),
        "highlights_hue_confidence": avg_conf("highlights_conf"),
    }
