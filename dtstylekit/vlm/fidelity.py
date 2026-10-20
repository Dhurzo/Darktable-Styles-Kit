"""Safety guards plus bounded reference nudges.

The VLM sees the reference images and chooses all creative parameters.
This module clamps impossible/unsafe values that would crash darktable or
produce visibly broken output, and applies a *gentle* nudge only when the
spec contradicts the reference on a gross scale (for example a strongly
negative filmic saturation on vividly colorful references).  There is no
blanket tone or saturation fit: a single preview frame is not a reliable
target for exposure/contrast.

Runs after ``validate_style`` whenever ``reference_analysis`` is available;
without references it is a no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dtstylekit.vlm.models import Plugin, StyleSpec

logger = logging.getLogger(__name__)


def auto_fit_signature(
    spec: StyleSpec,
    reference_analysis: dict | None,
    _analysis: object,
) -> tuple[StyleSpec, list[str]]:
    """Clamp unsafe values and gently nudge gross reference contradictions.

    The VLM sees the reference images and chooses all creative parameters.
    This function clamps impossible/unsafe values that would crash darktable
    or produce visibly broken output.  Gross contradictions (a spec that is
    the opposite of the measured reference) are moved halfway toward a
    reference-derived target; subtle differences are left untouched so
    creative intent is preserved.

    Runs after ``validate_style`` whenever ``reference_analysis`` is available;
    without references it is a no-op.
    """
    warnings: list[str] = []
    if not reference_analysis:
        return spec, warnings

    def _plugin(op: str) -> Plugin | None:
        for plg in spec.plugins:
            if plg.operation == op:
                return plg
        return None

    def _ensure(op: str) -> Plugin:
        plg = _plugin(op)
        if plg is None:
            plg = Plugin(operation=op, enabled=True, multi_name="", params={})
            spec.plugins.append(plg)
        return plg

    # 1. MONOCHROME REFERENCES → real B/W via monochrome IOP
    ref_sat = reference_analysis.get("global_saturation")
    if isinstance(ref_sat, int | float) and not isinstance(ref_sat, bool) and float(ref_sat) < 0.03:
        mono = _ensure("monochrome")
        mono.params.setdefault("a", 0.0)
        mono.params.setdefault("b", 0.0)
        warnings.append(
            f"FIDELITY monochrome: refs saturation {float(ref_sat):.2f} "
            "→ monochrome IOP added (true B/W)"
        )

    # 2. ABSOLUTE SAFETY GUARDS ONLY (no aesthetic adjustments)
    # filmicrgb: clamp saturation to valid range [-100, 100]
    filmic = _plugin("filmicrgb")
    filmic_sat_clamped = False
    if filmic:
        sat = filmic.params.get("saturation")
        if isinstance(sat, int | float) and not isinstance(sat, bool):
            if sat < -100:
                filmic.params["saturation"] = -100.0
                filmic_sat_clamped = True
                warnings.append("FIDELITY safety: filmicrgb.saturation clamped to -100")
            elif sat > 100:
                filmic.params["saturation"] = 100.0
                filmic_sat_clamped = True
                warnings.append("FIDELITY safety: filmicrgb.saturation clamped to 100")

    # colorbalancergb: clamp chroma to [0, 1] and hue to [0, 360)
    cb = _plugin("colorbalancergb")
    if cb:
        for zone in ("shadows", "midtones", "highlights"):
            c_key = f"{zone}_C"
            c_val = cb.params.get(c_key)
            if isinstance(c_val, int | float) and not isinstance(c_val, bool):
                if c_val < 0:
                    cb.params[c_key] = 0.0
                    warnings.append(f"FIDELITY safety: {c_key} clamped to 0")
                elif c_val > 1:
                    cb.params[c_key] = 1.0
                    warnings.append(f"FIDELITY safety: {c_key} clamped to 1")
            h_key = f"{zone}_H"
            h_val = cb.params.get(h_key)
            if isinstance(h_val, int | float) and not isinstance(h_val, bool):
                if h_val < 0:
                    cb.params[h_key] = 0.0
                    warnings.append(f"FIDELITY safety: {h_key} clamped to 0")
                elif h_val >= 360:
                    cb.params[h_key] = float(h_val % 360)
                    warnings.append(f"FIDELITY safety: {h_key} wrapped to [0, 360)")

    # 2b. DARK-TARGET SAFETY.  A dark / display-referred target (mean
    #     luminance < 0.3) must not be crushed by the preset's or the VLM's
    #     shadow-darkening.  Clamp colour-balance lift (zone Y) and negative
    #     exposure to >= 0 so shadows are never pushed below the base; the
    #     colour *grade* (hue/chroma) is preserved.  This is what keeps
    #     reference transfer onto dark photos from collapsing to near-black.
    _tgt_lum = getattr(getattr(_analysis, "luminance", None), "mean", None)
    if (
        isinstance(_tgt_lum, int | float)
        and not isinstance(_tgt_lum, bool)
        and float(_tgt_lum) < 0.3
    ):
        if cb is None:
            cb = _plugin("colorbalancergb")
        if cb is not None:
            for zone in ("shadows", "midtones", "highlights", "global"):
                y_key = f"{zone}_Y"
                y_val = cb.params.get(y_key)
                if isinstance(y_val, int | float) and not isinstance(y_val, bool) and y_val < 0:
                    cb.params[y_key] = 0.0
                    warnings.append(
                        f"FIDELITY safety: colorbalancergb.{y_key} clamped to 0 (dark target)"
                    )
        _exp = _plugin("exposure") or _ensure("exposure")
        _ev = _exp.params.get("exposure")
        if isinstance(_ev, int | float) and not isinstance(_ev, bool) and _ev < 0:
            _exp.params["exposure"] = 0.0
            warnings.append("FIDELITY safety: exposure floored at 0 EV (dark target)")

    # exposure: clamp to reasonable EV range
    exposure_plg = _plugin("exposure")
    if exposure_plg:
        exp = exposure_plg.params.get("exposure")
        if isinstance(exp, int | float) and not isinstance(exp, bool):
            if exp < -4:
                exposure_plg.params["exposure"] = -4.0
                warnings.append("FIDELITY safety: exposure clamped to -4 EV")
            elif exp > 4:
                exposure_plg.params["exposure"] = 4.0
                warnings.append("FIDELITY safety: exposure clamped to 4 EV")

    # filmicrgb: basic sanity ranges
    filmic = _plugin("filmicrgb")
    if filmic:
        for param, (lo, hi) in {
            "contrast": (0.1, 5.0),
            "latitude": (0.1, 10.0),
            "balance": (-10.0, 10.0),
        }.items():
            val = filmic.params.get(param)
            if isinstance(val, int | float) and not isinstance(val, bool):
                if val < lo:
                    filmic.params[param] = lo
                    warnings.append(f"FIDELITY safety: filmicrgb.{param} clamped to {lo}")
                elif val > hi:
                    filmic.params[param] = hi
                    warnings.append(f"FIDELITY safety: filmicrgb.{param} clamped to {hi}")

    # 3. GENTLE TARGET NUDGES.  Only gross contradictions are corrected, and
    #    only halfway toward the reference target: the VLM keeps creative
    #    control, while obvious mismatches (e.g. saturation -60 on vivid
    #    references) converge in one pass without another VLM call.
    gsat = reference_analysis.get("global_saturation")
    if (
        isinstance(gsat, int | float)
        and not isinstance(gsat, bool)
        and filmic is not None
        and not filmic_sat_clamped
        and isinstance(filmic.params.get("saturation"), int | float)
        and not isinstance(filmic.params.get("saturation"), bool)
    ):
        current = float(filmic.params["saturation"])
        target = max(-20.0, min(15.0, (float(gsat) - 0.20) * 100.0))
        # Nudge only when the sign contradicts the reference and the gap is
        # large; a mild same-side deviation is intentional.
        if current * target < 0 and abs(current - target) > 30.0:
            new_sat = current + (target - current) * 0.5
            filmic.params["saturation"] = new_sat
            warnings.append(
                f"FIDELITY nudge: filmicrgb.saturation {current:+.1f}->"
                f"{new_sat:+.1f} toward reference level (global HSV {float(gsat):.2f}, "
                f"target {target:+.1f})"
            )

    # Add gentle zone chroma only where the reference zone is clearly
    # colorful and the spec left that zone at zero.
    zone_caps = {"shadows": 0.10, "midtones": 0.08, "highlights": 0.05}
    nudged_cb: Plugin | None = None
    for zone, cap in zone_caps.items():
        ref_zone_sat = reference_analysis.get(f"{zone}_sat")
        if not isinstance(ref_zone_sat, int | float) or isinstance(ref_zone_sat, bool):
            continue
        if float(ref_zone_sat) < 0.15:
            continue
        # Only zones the analyzer declared as an intentional grade may be
        # nudged.  A "neutral" midtones zone (confidence 0) with a leftover
        # saturation estimate was re-tinting everything at hue 0 after the
        # validator had already forced midtones_C to 0.
        if reference_analysis.get(f"{zone}_hue_mode") not in ("mono", "bi", "global"):
            continue
        cb = _plugin("colorbalancergb")
        current_c = cb.params.get(f"{zone}_C") if cb is not None else None
        if isinstance(current_c, int | float) and not isinstance(current_c, bool) and current_c != 0:
            continue
        if cb is None:
            cb = _ensure("colorbalancergb")
        target_c = min(cap, float(ref_zone_sat) * 0.3)
        new_c = target_c * 0.5
        cb.params[f"{zone}_C"] = new_c
        nudged_cb = cb
        warnings.append(
            f"FIDELITY nudge: {zone}_C 0.000->{new_c:.3f} (reference {zone}_sat="
            f"{float(ref_zone_sat):.3f}, gentle half-step)"
        )

    # Warm/cool contradiction: a strongly warm reference with a cool zone hue
    # (or vice versa) is rotated halfway toward the reference's hue band.
    warmth = reference_analysis.get("global_warmth_rb")
    if isinstance(warmth, int | float) and not isinstance(warmth, bool):
        cb = nudged_cb or _plugin("colorbalancergb")
        if cb is not None and abs(float(warmth)) >= 0.05:
            target_hue = 45.0 if float(warmth) > 0 else 220.0
            label = "warm" if float(warmth) > 0 else "cool"

            def _circ_diff(a: float, b: float) -> float:
                d = abs(a - b) % 360.0
                return min(d, 360.0 - d)

            for zone in ("shadows", "midtones", "highlights"):
                h_val = cb.params.get(f"{zone}_H")
                c_val = cb.params.get(f"{zone}_C")
                if not isinstance(h_val, int | float) or isinstance(h_val, bool):
                    continue
                if not isinstance(c_val, int | float) or isinstance(c_val, bool) or c_val <= 0:
                    continue
                delta = ((target_hue - float(h_val) + 180.0) % 360.0) - 180.0
                if abs(delta) <= 90.0:
                    continue
                new_h = (float(h_val) + delta * 0.5) % 360.0
                cb.params[f"{zone}_H"] = new_h
                warnings.append(
                    f"FIDELITY nudge: {label} reference (R-B {float(warmth):+.2f}) "
                    f"rotated {zone}_H {float(h_val):.1f}->{new_h:.1f}"
                )

    for w in warnings:
        logger.info(w)
    return spec, warnings


def compute_reference_profile(reference_paths: list) -> dict:
    """Extended reference profile: contrast, dynamic range, saturation
    peaks and warmth — the *shape* of the look, not just its averages.

    Delegates to the analyzer's single-pass global stats so the prompt,
    evaluator and refiner all share one implementation.  These values are
    purely informational (for logging/debugging) and do NOT drive
    automatic fits; the VLM makes all creative decisions.
    """
    from dtstylekit.analyzer.pipeline import compute_reference_globals

    globals_ = compute_reference_globals([Path(p) for p in reference_paths])
    return {
        key: globals_[key]
        for key in (
            "global_contrast",
            "global_dynamic_range",
            "global_saturation_p90",
            "global_warmth_rb",
        )
    }
