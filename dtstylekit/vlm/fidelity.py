"""Signature fidelity: auto-fit the style spec to the reference signature.

The VLM proposes a style from the prompt, but nothing forced it to actually
match the *objective* signature of the reference photos (saturation level,
tonal placement, warmth).  This module closes that gap deterministically —
no extra VLM calls — by comparing measured reference stats against the
target photo's analysis and adjusting the spec:

1. SATURATION — if the references are notably less (more) saturated than
   the target photo, set ``filmicrgb.saturation`` (``colorbalancergb.
   vibrance``) to close the gap.
2. TONE — match exposure placement: ``EV = log2(ref_lum / scene_lum)``.
3. WARMTH — if a reference zone hue is confident but the spec carries no
   visible chroma in that zone, set the hue with a subtle chroma
   (respecting the global-grade caps from the anti-tint work).

Runs after ``validate_style`` whenever ``reference_analysis`` is available;
without references it is a no-op.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# Global-grade chroma caps (must mirror validator._zone_caps_global):
# a uniform tint above these over-tints the whole image.
_GLOBAL_CAPS = {"shadows": 0.02, "midtones": 0.015, "highlights": 0.012}
# Chroma floor below which a zone tint is considered imperceptible.
_CHROMA_VISIBLE = 0.03
# Subtle-but-visible chroma used when a confident reference hue has no
# matching chroma in the spec (bidirectional zone grading).
_CHROMA_SUBTLE = 0.05

_SATURATION_RATIO_LOW = 0.65  # refs notably less saturated than the scene
_SATURATION_RATIO_HIGH = 1.5  # refs notably more saturated
# colorequal desaturation calibration (real darktable render): sat_* = 0.35
# on all 8 channels → render saturation = 0.53 × scene saturation.
# factor ≈ 1 - (1 - sat_equal) / 1.44
_CE_DESAT_SCALE = 1.44
_CE_CHANNELS = ("red", "orange", "yellow", "green", "cyan", "blue", "lavender", "magenta")
_EV_TOLERANCE = 0.3  # don't touch exposure if within ±0.3 EV of target
# A style is one exposure recipe for MANY photos: never demand a huge EV
# jump from a single (possibly atypical) preview — the user fine-tunes
# exposure per shot.  Clamp the fitted EV correction.
_EV_CLAMP = 0.8
_HUE_CONF_MIN = (
    0.5  # lowered to capture moderate-confidence reference hues (e.g., Nishimura/Moumarion shadows)
)


def compute_reference_luminance(reference_paths) -> float | None:
    """Mean luminance (0-1) across the reference images."""
    lums: list[float] = []
    for ref in reference_paths:
        try:
            from dtstylekit.analyzer.pipeline import analyze_image as _analyze

            a = _analyze(ref)
            m = getattr(getattr(a, "luminance", None), "mean", None)
            if isinstance(m, int | float) and not isinstance(m, bool):
                lums.append(float(m))
        except Exception:
            continue
    if not lums:
        return None
    return sum(lums) / len(lums)


def auto_fit_signature(spec, reference_analysis: dict | None, analysis) -> tuple[object, list[str]]:
    """Deterministically fit ``spec`` to the reference signature.

    Returns ``(spec, warnings)``.  The spec is modified in place (plugins
    merged/added); without ``reference_analysis`` it is a no-op.
    """
    warnings: list[str] = []
    if not reference_analysis:
        return spec, warnings

    lum = getattr(getattr(analysis, "luminance", None), "mean", None)
    scene_sat = getattr(getattr(analysis, "luminance", None), "saturation_mean", None)

    def _plugin(op: str):
        for plg in spec.plugins:
            if plg.operation == op:
                return plg
        return None

    def _ensure(op: str):
        plg = _plugin(op)
        if plg is None:
            from dtstylekit.vlm.models import Plugin

            plg = Plugin(operation=op, enabled=True, multi_name="", params={})
            spec.plugins.append(plg)
        return plg

    # ---- 1. SATURATION -----------------------------------------------------
    ref_sat = reference_analysis.get("global_saturation")
    if (
        isinstance(ref_sat, int | float)
        and isinstance(scene_sat, int | float)
        and not isinstance(ref_sat, bool)
        and scene_sat > 0.02
    ):
        ratio = float(ref_sat) / float(scene_sat)
        if ratio < 0.15 or float(ref_sat) < 0.03:
            # Essentially monochrome references → real B/W via the
            # monochrome IOP (a=b=0 is the luminance mix).  filmicrgb
            # saturation is NOT a desaturator (measured: -100 still leaves
            # ≈half the scene saturation — it shapes the tone mapper).
            mono = _ensure("monochrome")
            mono.params.setdefault("a", 0.0)
            mono.params.setdefault("b", 0.0)
            ce = _ensure("colorequal")
            for c in _CE_CHANNELS:
                ce.params.setdefault(f"sat_{c}", 0.15)
            warnings.append(
                f"FIDELITY monochrome: refs saturation {float(ref_sat):.2f} "
                f"→ monochrome IOP added (colorequal sat 0.15 assists)"
            )
        elif ratio < _SATURATION_RATIO_LOW:
            # Partial desaturation via colorequal (measured render
            # calibration: sat_* 0.35 → render factor 0.53 of scene sat).
            target = 1.0 - (1.0 - ratio) / _CE_DESAT_SCALE
            target = max(0.05, min(1.0, round(target, 3)))
            ce = _ensure("colorequal")
            changed = []
            for c in _CE_CHANNELS:
                k = f"sat_{c}"
                cur = float(ce.params.get(k, 1.0) or 1.0)
                if cur > target:
                    ce.params[k] = target
                    changed.append(c)
            if changed:
                warnings.append(
                    f"FIDELITY saturation: refs {ref_sat:.2f} vs scene {scene_sat:.2f} "
                    f"(ratio {ratio:.2f}) → colorequal sat_* → {target:.2f}"
                )
        elif ratio > _SATURATION_RATIO_HIGH:
            cb = _ensure("colorbalancergb")
            cur = float(cb.params.get("vibrance", 0.0) or 0.0)
            target = min(0.4, max(cur, round(min(0.4, (ratio - 1.0) * 0.3), 2)))
            if target > cur:
                cb.params["vibrance"] = target
                warnings.append(
                    f"FIDELITY saturation: refs {ref_sat:.2f} vs scene {scene_sat:.2f} "
                    f"(ratio {ratio:.2f}) → colorbalancergb.vibrance {cur:.2f}→{target:.2f}"
                )

    # ---- 2. TONE ------------------------------------------------------------
    ref_lum = reference_analysis.get("global_luminance")
    if (
        isinstance(ref_lum, int | float)
        and isinstance(lum, int | float)
        and not isinstance(ref_lum, bool)
        and lum > 0.02
    ):
        ev = math.log2(max(float(ref_lum), 1e-3) / max(float(lum), 1e-3))
        ev = max(-_EV_CLAMP, min(_EV_CLAMP, ev))
        exposure_plg = _ensure("exposure")
        cur = float(exposure_plg.params.get("exposure", 0.0) or 0.0)
        if abs(cur - ev) > _EV_TOLERANCE:
            new = round(ev * 20) / 20  # snap to 0.05
            exposure_plg.params["exposure"] = new
            warnings.append(
                f"FIDELITY tone: refs lum {ref_lum:.2f} vs scene {lum:.2f} "
                f"(target {ev:+.2f} EV) → exposure.exposure {cur:+.2f}→{new:+.2f}"
            )

    # ---- 3. WARMTH ------------------------------------------------------------
    for zone in ("shadows", "midtones", "highlights"):
        hue = reference_analysis.get(f"{zone}_hue")
        conf = reference_analysis.get(f"{zone}_hue_confidence", 0) or 0
        mode = reference_analysis.get(f"{zone}_hue_mode")
        cb = _ensure("colorbalancergb")
        c_key = f"{zone}_C"
        h_key = f"{zone}_H"
        cur_c = float(cb.params.get(c_key, 0.0) or 0.0)

        # 3a. Chroma calibration cap: the reference zone hue describes the
        # color of ALREADY-SATURATED areas, not an order to tint the whole
        # zone. Cap the spec chroma at ref_zone_sat × 0.15 (measured render
        # calibration: C=0.15 in two zones shifts global R-B by ≈ -0.42 —
        # a full-image tint; C=0.06 ≈ neutral). The ref zone_sat measures
        # the reference's CONTENT (neons, saturated skies) — the grade
        # transferred to a different scene must be a fraction of it.
        # Applies to every hue mode.
        zone_sat = reference_analysis.get(f"{zone}_sat")
        if (
            isinstance(zone_sat, int | float)
            and not isinstance(zone_sat, bool)
            and float(zone_sat) > 0.01
            and cur_c > float(zone_sat) * 0.15
        ):
            cap = round(min(0.08, float(zone_sat) * 0.15), 3)
            cb.params[c_key] = cap
            warnings.append(
                f"FIDELITY warmth cap: refs {zone}_sat {float(zone_sat):.2f} → "
                f"{c_key} {cur_c:.3f}→{cap} (hue describes already-saturated "
                f"areas, not a whole-zone tint)"
            )
            cur_c = cap

        if hue is None or conf < _HUE_CONF_MIN or mode not in ("bi", "global"):
            continue

        # 3b. Missing chroma: confident reference hue with no visible spec
        # chroma → set hue + subtle chroma (global mode respects caps).
        if cur_c >= _CHROMA_VISIBLE * 0.66:  # already carries a tint
            continue
        if mode == "global":
            cap = _GLOBAL_CAPS[zone]
            new_c = min(_CHROMA_SUBTLE, cap)
            if new_c <= cur_c:
                continue
        else:
            new_c = _CHROMA_SUBTLE
        cb.params[h_key] = float(hue)
        cb.params[c_key] = new_c
        warnings.append(
            f"FIDELITY warmth: ref {zone} hue {float(hue):.1f}° (conf {conf:.2f}, "
            f"mode {mode}) but spec {c_key}={cur_c:.3f} → {h_key}={float(hue):.1f}, "
            f"{c_key}={new_c:.3f}"
        )

    for w in warnings:
        logger.info(w)
    return spec, warnings
