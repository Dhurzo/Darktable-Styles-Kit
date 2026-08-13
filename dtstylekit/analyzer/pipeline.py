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


def _to_float_array(image: Image.Image) -> object:  # numpy.ndarray — kept untyped
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


def _circular_mean(hues_deg: list[float], weights: list[float] | None = None) -> float:
    """Circular mean of hue angles in degrees (handles 350°+10°→0° wraparound).

    Returns a hue in [0, 360). If `weights` given, weighted circular mean.
    Empty input → 0.0.
    """
    import numpy as np
    if not hues_deg:
        return 0.0
    rad = np.deg2rad(np.asarray(hues_deg, dtype=np.float32))
    if weights is None:
        s = float(np.sin(rad).sum())
        c = float(np.cos(rad).sum())
    else:
        w = np.asarray(weights, dtype=np.float32)
        s = float((np.sin(rad) * w).sum())
        c = float((np.cos(rad) * w).sum())
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return 0.0
    return float(np.rad2deg(np.arctan2(s, c)) % 360.0)


def _circular_dispersion(hues_deg: list[float], weights: list[float] | None = None) -> float:
    """Circular dispersion R̄ in [0, 1]. 1.0 = all hues identical, 0.0 = uniform.

    Low R̄ means hues disagree (no clear direction). 1 - R̄ is the usual
    circular variance; we return R̄ directly so higher = more concentrated.
    """
    import numpy as np
    if not hues_deg:
        return 0.0
    rad = np.deg2rad(np.asarray(hues_deg, dtype=np.float32))
    if weights is None:
        s = float(np.sin(rad).mean())
        c = float(np.cos(rad).mean())
    else:
        w = np.asarray(weights, dtype=np.float32)
        w = w / max(w.sum(), 1e-9)
        s = float((np.sin(rad) * w).sum())
        c = float((np.cos(rad) * w).sum())
    return float(np.sqrt(s * s + c * c))


def _detect_bimodal(hues_deg: list[float], weights: list[float]) -> tuple[float, float, float] | None:
    """Detect a bimodal hue distribution. Returns (primary_hue, secondary_hue, primary_weight_share) or None.

    Builds a 12-bin circular histogram (30° per bin). If the top 2 bins
    together hold >=70% of total weight AND are NOT adjacent (i.e. genuinely
    distinct modes), returns the weighted circular mean of each peak.
    """
    import numpy as np
    if not hues_deg:
        return None
    h = np.asarray(hues_deg, dtype=np.float32) % 360.0
    w = np.asarray(weights, dtype=np.float32)
    total_w = float(w.sum())
    if total_w <= 0:
        return None
    # 12 bins of 30°, circular layout
    bins = np.zeros(12, dtype=np.float32)
    for hi, wi in zip(h, w, strict=False):
        bin_idx = int(hi // 30) % 12
        bins[bin_idx] += wi
    # Find top 2 bins
    order = np.argsort(bins)[::-1]
    top1, top2 = int(order[0]), int(order[1])
    share = (bins[top1] + bins[top2]) / total_w
    # Adjacent (circular) bins = same mode, not bimodal
    adjacent = (abs(top1 - top2) % 12) in (1, 11)
    # Second peak must hold a non-trivial share — otherwise it's noise on a flat tail
    secondary_share = bins[top2] / total_w
    if share < 0.70 or adjacent or secondary_share < 0.20:
        return None
    # Compute primary hue: circular mean of pixels in top1 +/- 15°
    # Wrap-around handling: shift hues so top1's center is at 0
    center1 = (top1 * 30 + 15) % 360
    center2 = (top2 * 30 + 15) % 360
    # Pixels assigned to each peak: nearest of the two centers
    d1 = np.minimum(np.abs(h - center1), 360 - np.abs(h - center1))
    d2 = np.minimum(np.abs(h - center2), 360 - np.abs(h - center2))
    mask1 = d1 <= d2
    primary = _circular_mean(h[mask1].tolist(), w[mask1].tolist()) if mask1.any() else center1
    secondary = _circular_mean(h[~mask1].tolist(), w[~mask1].tolist()) if (~mask1).any() else center2
    primary_share = float(w[mask1].sum() / total_w)
    return (primary, secondary, primary_share)


def analyze_reference_hues(reference_paths: list[Path]) -> dict:
    """Extract dominant hue and saturation per tonal range (shadows/midtones/highlights)
    from a list of reference images, using **circular** statistics and **bimodal**
    detection so references with two distinct color grades (e.g. teal shadows +
    warm highlights) are not collapsed into a meaningless average.

    Per zone, returns one of:
      - hue_mode = "neutral": no clear color grade (low saturation or low
        sample count). hue = None, chroma = 0. The prompt applies NEUTRAL,
        respecting the target photo's colors.
      - hue_mode = "mono": a single dominant hue. hue is the weighted circular
        mean. chroma is the mean saturation in the zone.
      - hue_mode = "bi": two distinct color grades detected. The primary
        hue (higher saturation-weight) is returned as the main `*_hue`. A
        new `*_hue_secondary` field carries the secondary. The prompt /
        validator can decide how to apply (typically: use primary as the
        zone's hue, keep chroma modest to avoid over-tinting).

    Across references, hues are combined with weighted circular mean (not
    arithmetic). Circular dispersion R̄ is used to **lower** confidence when
    references disagree: if dispersion < 0.4 (saturated pixels disagree on
    direction), confidence is forced to 0 — neutral wins. This prevents
    the system from inventing a tint when handed a mixed reference set.

    Args:
        reference_paths: List of paths to reference JPEG/PNG images.

    Returns:
        Dict with keys:
          shadows_hue, midtones_hue, highlights_hue (or None),
          shadows_hue_secondary, midtones_hue_secondary, highlights_hue_secondary (or None),
          shadows_sat, midtones_sat, highlights_sat,
          shadows_hue_confidence, midtones_hue_confidence, highlights_hue_confidence,
          shadows_hue_mode, midtones_hue_mode, highlights_hue_mode
    """
    import numpy as np
    from PIL import Image

    # Configuration — tighter than before to demand real evidence of a grade.
    MIN_SATURATION_FOR_HUE = 0.15      # Min saturation to compute meaningful hue
    MIN_VALID_PIXELS = 200             # Min pixels with valid color in tonal range
    SATURATION_WEIGHT_POWER = 2.0      # Power for saturation weighting
    DISPERSION_MIN = 0.7               # R̄ below this = refs disagree → neutral

    ref_data = []

    for ref_path in reference_paths:
        try:
            img = Image.open(ref_path).convert('RGB')
            arr = np.asarray(img, dtype=np.float32) / 255.0

            # Luminance (BT.709 weighting matches the dependency on tonal masks)
            lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
            # Tonal masks
            shadows_mask = lum < 0.25
            midtones_mask = (lum >= 0.25) & (lum < 0.75)
            highlights_mask = lum >= 0.75

            def analyze_tonal_range(mask, arr=arr):
                """Returns (hue_list, sat_weights, mean_sat, valid_count, confidence, hue_mode)."""
                if not np.any(mask):
                    return [], [], 0.0, 0, 0.0, "neutral"

                # Per-pixel max/min/delta (RGB)
                px_max = np.max(arr, axis=2)
                px_min = np.min(arr, axis=2)
                delta = px_max - px_min
                sat_in_range = delta[mask]
                mean_sat = float(np.mean(sat_in_range))

                if mean_sat < MIN_SATURATION_FOR_HUE:
                    return [], [], mean_sat, 0, 0.0, "neutral"

                valid_mask = mask & (delta > MIN_SATURATION_FOR_HUE * 0.5)
                valid_count = int(np.sum(valid_mask))
                if valid_count < MIN_VALID_PIXELS:
                    return [], [], mean_sat, valid_count, 0.0, "neutral"

                r = arr[valid_mask, 0]
                g = arr[valid_mask, 1]
                b = arr[valid_mask, 2]
                max_c = np.maximum(np.maximum(r, g), b)
                min_c = np.minimum(np.minimum(r, g), b)
                delta_c = max_c - min_c

                # Per-pixel hue (0-360)
                hue = np.zeros_like(r)
                idx = delta_c > 0.01
                r_idx = (max_c == r) & idx
                g_idx = (max_c == g) & idx
                b_idx = (max_c == b) & idx
                hue[r_idx] = (60 * ((g[r_idx] - b[r_idx]) / delta_c[r_idx]) + 360) % 360
                hue[g_idx] = (60 * ((b[g_idx] - r[g_idx]) / delta_c[g_idx]) + 120) % 360
                hue[b_idx] = (60 * ((r[b_idx] - g[b_idx]) / delta_c[b_idx]) + 240) % 360

                weights = delta_c[idx] ** SATURATION_WEIGHT_POWER
                hues_list = hue[idx].tolist()
                w_list = weights.tolist()

                # Confidence: combined valid-pixel count + saturation level
                conf = min(1.0, valid_count / (MIN_VALID_PIXELS * 10)) * min(1.0, mean_sat / 0.3)
                return hues_list, w_list, mean_sat, valid_count, conf, "unknown"

            sh = analyze_tonal_range(shadows_mask)
            mt = analyze_tonal_range(midtones_mask)
            hi = analyze_tonal_range(highlights_mask)

            def _pack(z):
                # Detect bimodality *within this single reference* — distinguishes
                # an intentional two-color grade (e.g. teal shadows + warm
                # highlights in one Blade Runner frame) from "two references that
                # happen to disagree" (e.g. one warm photo + one cool photo). Only
                # the former should propagate as `bi`; the latter must collapse to
                # neutral so we don't invent a tint.
                bi = _detect_bimodal(z[0], z[1]) if z[0] else None
                return {
                    "hues": z[0], "weights": z[1], "sat": z[2],
                    "count": z[3], "conf": z[4],
                    "is_bi": bi is not None,
                    "bi_primary": bi[0] if bi else None,
                    "bi_secondary": bi[1] if bi else None,
                }

            ref_data.append({
                "shadows": _pack(sh), "midtones": _pack(mt), "highlights": _pack(hi),
            })

        except Exception as e:
            print(f"Warning: failed to analyze reference {ref_path}: {e}")
            continue

    if not ref_data:
        return {
            "shadows_hue": None, "midtones_hue": None, "highlights_hue": None,
            "shadows_hue_secondary": None, "midtones_hue_secondary": None, "highlights_hue_secondary": None,
            "shadows_sat": 0.0, "midtones_sat": 0.0, "highlights_sat": 0.0,
            "shadows_hue_confidence": 0.0, "midtones_hue_confidence": 0.0, "highlights_hue_confidence": 0.0,
            "shadows_hue_mode": "neutral", "midtones_hue_mode": "neutral", "highlights_hue_mode": "neutral",
        }

    def _zone_combine(zone_key: str) -> dict:
        """Combine one zone across all references with circular stats + bimodal detection.

        Decision rule:
          1. If ANY reference is internally bimodal in this zone (e.g. one photo
             with two distinct color grades), aggregate its peaks + the
             monomodal hues of the rest into a `bi` result. This is the
             intentional-orange-and-teal case.
          2. Otherwise (all refs individually monomodal), if the AGGREGATE hue
             dispersion is low (R̄ >= 0.4) → `mono` with the circular mean.
             High dispersion (R̄ < 0.4) means refs disagree on hue → `neutral`,
             no tint is forced.
        """
        all_hues = []
        all_weights = []
        sats = []
        confs = []
        any_internal_bi = False
        bi_primary = None
        bi_secondary = None
        for d in ref_data:
            z = d[zone_key]
            if z.get("is_bi"):
                any_internal_bi = True
                bi_primary = z["bi_primary"]
                bi_secondary = z["bi_secondary"]
            if z["hues"]:
                all_hues.extend(z["hues"])
                all_weights.extend(z["weights"])
            sats.append(z["sat"])
            confs.append(z["conf"])

        mean_sat = float(np.mean(sats)) if sats else 0.0
        mean_conf = float(np.mean(confs)) if confs else 0.0

        if not all_hues:
            return {
                "hue": None, "hue_secondary": None, "sat": mean_sat,
                "conf": 0.0, "mode": "neutral",
            }

        # Case 1: at least one reference was internally bimodal → emit `bi`.
        # Prefer an internally-bimodal ref's primary as the zone hue; the
        # aggregate circular mean becomes the secondary if no internal one exists.
        if any_internal_bi:
            # Fall back to aggregate circular mean if needed
            if bi_primary is None:
                bi_primary = _circular_mean(all_hues, all_weights)
            return {
                "hue": bi_primary, "hue_secondary": bi_secondary,
                "sat": mean_sat,
                "conf": max(mean_conf, 0.55), "mode": "bi",
            }

        # Case 2: all refs monomodal → use dispersion to decide mono vs neutral
        disp = _circular_dispersion(all_hues, all_weights)
        primary = _circular_mean(all_hues, all_weights)
        if disp < DISPERSION_MIN:
            return {
                "hue": None, "hue_secondary": None, "sat": mean_sat,
                "conf": 0.0, "mode": "neutral",
            }
        conf = mean_conf * float(disp)
        return {
            "hue": primary, "hue_secondary": None, "sat": mean_sat,
            "conf": conf, "mode": "mono",
        }

    shc = _zone_combine("shadows")
    mtc = _zone_combine("midtones")
    hic = _zone_combine("highlights")

    return {
        "shadows_hue": shc["hue"],
        "midtones_hue": mtc["hue"],
        "highlights_hue": hic["hue"],
        "shadows_hue_secondary": shc["hue_secondary"],
        "midtones_hue_secondary": mtc["hue_secondary"],
        "highlights_hue_secondary": hic["hue_secondary"],
        "shadows_sat": shc["sat"],
        "midtones_sat": mtc["sat"],
        "highlights_sat": hic["sat"],
        "shadows_hue_confidence": shc["conf"],
        "midtones_hue_confidence": mtc["conf"],
        "highlights_hue_confidence": hic["conf"],
        "shadows_hue_mode": shc["mode"],
        "midtones_hue_mode": mtc["mode"],
        "highlights_hue_mode": hic["mode"],
    }
