"""Validate and clamp StyleSpec against the IOP registry.

Rejects unknown IOPs, clamps out-of-range parameters, merges defaults.
Recognises the synthetic ``curve_preset`` field for curve-based IOPs
and cross-checks the named template against the curve-template registry.

For curve-based IOPs, also validates that any additional scalar
parameters (e.g. ``strength`` for colorzones, ``preserve_colors``
for rgbcurve) are within their declared ranges.
"""

from __future__ import annotations

import logging

from .models import Plugin, StyleSpec

logger = logging.getLogger(__name__)


def _circular_mean(hues_deg: list[float]) -> float:
    """Circular mean of hue angles in degrees (handles wraparound).

    Unweighted; used by the Hito 6D dominance exception to compare the
    VLM's uniform hue against the reference's coherent grade.
    """
    import numpy as np

    if not hues_deg:
        return 0.0
    rad = np.deg2rad(np.asarray(hues_deg, dtype=np.float32))
    s = float(np.sin(rad).sum())
    c = float(np.cos(rad).sum())
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return 0.0
    return float(np.rad2deg(np.arctan2(s, c)) % 360.0)


# String-valued virtual fields that must be handled separately from
# numeric ranges.  Their "range" in the registry is a tuple of valid
# string choices, NOT a numeric (lo, hi) pair.
_STRING_VIRTUAL_FIELDS = {"curve_preset"}


def validate_style(
    spec: StyleSpec,
    registry: dict,
    reference_analysis: dict | None = None,
    target_analysis: object | None = None,
) -> tuple[StyleSpec, list[str]]:
    """Validate the StyleSpec.

    Args:
        spec: Parsed StyleSpec from VLM.
        registry: Dict mapping operation name -> IOPRegistry-like dataclass.
        reference_analysis: Optional pre-computed hue/saturation analysis
            of reference images (from ``analyze_reference_hues``). Contains
            per-zone ``*_hue``, ``*_hue_mode`` (``neutral``|``mono``|``bi``),
            and ``*_hue_confidence``. Used by the *monochrome dominance*
            guard to decide whether a single-hue-across-all-zones pattern is
            an intentional grade (refs are ``mono`` with the same hue in
            every zone) or an accidental global tint (refs do NOT call for
            it → chroma is halved).
        target_analysis: Optional ``ImageAnalysis`` of the *photo the style
            will be applied to*. Used by the *midtones protection* guard to
            pull skin-tone hints from the histogram (mean green dominance)
            and keep midtones chroma low on likely-portrait targets.

    Returns:
        (validated_spec, warnings) tuple.
    """
    warnings: list[str] = []
    validated_plugins: list[Plugin] = []

    # Lazy-import the curve templates so this module stays usable
    # without the curve subsystem.
    curve_template_names: set[str] | None = None

    for plg in spec.plugins:
        if plg.operation not in registry:
            warnings.append(f"Unknown IOP '{plg.operation}' — skipped")
            continue
        reg = registry[plg.operation]
        is_curve = getattr(reg, "is_curve_iop", False)

        # Merge with defaults
        merged_params = dict(reg.defaults)
        merged_params.update(plg.params)

        # Clamp to ranges (or special-case string virtual fields)
        clamped_params: dict = {}
        for fld, val in merged_params.items():
            # ---- Unknown field check ----------------------------------------
            if fld not in reg.ranges and fld not in _STRING_VIRTUAL_FIELDS:
                # Only warn for fields the LLM explicitly specified
                if fld in plg.params:
                    warnings.append(f"{plg.operation}.{fld}: unknown field — ignored")
                continue

            in_range = fld in reg.ranges
            range_val = reg.ranges.get(fld)

            # ---- String virtual fields (curve_preset) -----------------------
            if fld in _STRING_VIRTUAL_FIELDS:
                if is_curve:
                    result, warn_msg = _validate_curve_preset(
                        plg.operation, val, curve_template_names
                    )
                    if warn_msg:
                        warnings.append(warn_msg)
                    # Update the cached set after first load
                    if curve_template_names is None and result is None:
                        try:
                            from dtstylekit.curves import REGISTRY as CURVE_REG

                            curve_template_names = {t.name for t in CURVE_REG}
                        except ImportError:
                            curve_template_names = set()
                        # Retry with populated set
                        result, warn_msg = _validate_curve_preset(
                            plg.operation, val, curve_template_names
                        )
                        if warn_msg:
                            warnings.append(warn_msg)
                    if result is not None:
                        clamped_params[fld] = result
                # Non-curve IOP setting curve_preset — silently skip
                continue

            # ---- String-valued range (enum-like) ---------------------------
            if in_range and range_val is not None:
                lo_r, _ = range_val
                if isinstance(lo_r, str):
                    # Range is a tuple of valid string choices
                    if val not in range_val:
                        if fld in plg.params:
                            warnings.append(
                                f"{plg.operation}.{fld}: '{val}' not in "
                                f"allowed values {range_val} — ignored"
                            )
                        continue
                    clamped_params[fld] = val
                    continue

            # ---- Numeric clamp -----------------------------------------------
            try:
                num_val = float(val)
            except (TypeError, ValueError):
                if fld in plg.params:
                    warnings.append(f"{plg.operation}.{fld}: not numeric — ignored")
                continue

            if in_range and range_val is not None:
                lo, hi = range_val
                if not (lo <= num_val <= hi):
                    clamped = max(lo, min(hi, num_val))
                    warnings.append(
                        f"{plg.operation}.{fld}: {num_val} out of range "
                        f"[{lo}, {hi}] → clamped to {clamped}"
                    )
                    num_val = clamped
                # Cast back to int if needed
                if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool):
                    num_val = int(num_val)

            clamped_params[fld] = num_val

        # ---- Semantic guard: colorbalancergb color tints ----------------
        # The "global" tab is an ADDITIVE RGB offset (commit_params in
        # src/iop/colorbalancergb.c): RGB += offset.  With global_C>0 and
        # global_H=0 (hue 0° = red) the whole image is tinted red — a
        # classic VLM mistake.  Neutralize the chroma when the hue is
        # missing/neutral instead of rendering a red-tinted image.
        #
        # We also guard shadows/midtones/highlights: when H≈0 the grading
        # tint is RED-ish (Yrg 0° = conventional -30°, a red/orange).  If
        # the VLM set H=0 (neutral intent) but left C>0, the result is an
        # unintended warm/red tint.  Force C to 0 in that case so the
        # target photo's original colors are respected.
        if plg.operation == "colorbalancergb":

            def _neutral_hue(h: float | None) -> bool:
                return abs(float(h or 0.0)) < 1e-3 or float(h or 0.0) > 359.999

            # Global additive offset (most dangerous - tints EVERY pixel).
            gc = float(clamped_params.get("global_C") or 0.0)
            gh = float(clamped_params.get("global_H") or 0.0)
            if gc > 0.0 and _neutral_hue(gh):
                if "global_C" in plg.params:
                    warnings.append(
                        "colorbalancergb.global_C>0 with global_H≈0 tints the "
                        "whole image RED (additive offset, hue 0°=red) — "
                        "global_C forced to 0.0"
                    )
                clamped_params["global_C"] = 0.0
            # Shadows / midtones / highlights: neutral hue + chroma = tint.
            for zone in ("shadows", "midtones", "highlights"):
                c_key = f"{zone}_C"
                h_key = f"{zone}_H"
                cz = float(clamped_params.get(c_key) or 0.0)
                hz = float(clamped_params.get(h_key) or 0.0)
                # Treat hue ≈ 0 or ≈ 360 as "neutral intent" (no grading).
                # Also catch tiny non-zero hues (VLM noise around 0).
                if cz > 0.0 and _neutral_hue(hz):
                    if c_key in plg.params:
                        warnings.append(
                            f"colorbalancergb.{c_key}>0 with {h_key}≈0 tints "
                            f"{zone} red/warm (Yrg hue 0° = conventional -30°). "
                            f"For neutral grading (respect target colors) "
                            f"{c_key} forced to 0.0"
                        )
                    clamped_params[c_key] = 0.0

            # ---- Hito 2.1: dynamic chroma ceiling per confidence ------------
            # Default chroma caps are conservative (0.10/0.08/0.05). They only
            # relax to the historical 0.15/0.15/0.10 when the Python hue
            # analysis for that zone reports HIGH confidence (>=0.85). This
            # stops the VLM from emitting a strong chroma on a wishy-washy
            # reference whose hue was borderline detectable.
            _zone_caps_default = {"shadows": 0.10, "midtones": 0.08, "highlights": 0.05}
            _zone_caps_highconf = {"shadows": 0.15, "midtones": 0.15, "highlights": 0.10}
            # Hito 6F: a *global* uniform grade (one coherent tint across all
            # three zones — hue_mode='global') tints EVERYTHING. The zone caps
            # above are tuned for split-tone grading and over-tint when applied
            # to a uniform grade (r4s renders came out +56..+138 R-B vs +9..+29
            # in the references; even the first 6F caps 0.05/0.04/0.03 still
            # doubled the reference warmth: +39 vs ~+19). Cap global grades at
            # a SUBTLE level and never exceed a quarter of the measured zone
            # saturation — a tint must stay WELL below the reference's own
            # colorfulness.
            _zone_caps_global = {"shadows": 0.02, "midtones": 0.015, "highlights": 0.012}
            _is_global_grade = reference_analysis is not None and all(
                (reference_analysis.get(f"{z}_hue_mode") or "") == "global"
                for z in _zone_caps_default
            )
            for zone, default_cap in _zone_caps_default.items():
                c_key = f"{zone}_C"
                conf_key = f"{zone}_hue_confidence"
                if c_key not in clamped_params:
                    continue
                cz = float(clamped_params[c_key] or 0.0)
                if cz <= 0.0:
                    continue
                conf = float((reference_analysis or {}).get(conf_key) or 0.0)
                if _is_global_grade:
                    # Uniform-grade cap: subtle ceiling, scaled by a QUARTER
                    # of the measured saturation of the zone (0 when absent).
                    sat = float((reference_analysis or {}).get(f"{zone}_sat") or 0.0)
                    cap = _zone_caps_global[zone]
                    if sat > 0.0:
                        cap = min(cap, sat * 0.25)
                    if cz > cap:
                        if c_key in plg.params:
                            warnings.append(
                                f"colorbalancergb.{c_key}={cz:.3f} exceeds "
                                f"GLOBAL-GRADE cap {cap:.2f} (uniform tint must "
                                f"stay subtle; reference {zone}_sat={sat:.3f}) — clamped"
                            )
                        clamped_params[c_key] = cap
                    continue
                cap = _zone_caps_highconf[zone] if conf >= 0.85 else default_cap
                if cz > cap:
                    if c_key in plg.params:
                        warnings.append(
                            f"colorbalancergb.{c_key}={cz:.3f} exceeds dynamic "
                            f"cap {cap:.2f} (reference {conf_key}={conf:.2f}, "
                            f"threshold 0.85 for relaxed cap) — clamped"
                        )
                    clamped_params[c_key] = cap

            # ---- Hito 2.2: midtones protection on likely-portrait targets ----
            # The midtones tab carries skin tones. Heavy midtones_C on a photo
            # whose histogram suggests a portrait (mean green dominant, the
            # classic warm-skin signature) thrusts a fake cinematic tint into
            # faces. Cap midtones_C hard at 0.05 in that case.
            mt_c = float(clamped_params.get("midtones_C") or 0.0)
            if mt_c > 0.05 and target_analysis is not None:
                hist = getattr(target_analysis, "histogram", None)
                if hist is not None:
                    rg = float(getattr(hist, "mean_red", 0.0) or 0.0)
                    gg = float(getattr(hist, "mean_green", 0.0) or 0.0)
                    bg = float(getattr(hist, "mean_blue", 0.0) or 0.0)
                    # Green dominance (R close to G, both clearly above B)
                    # = the warm-skin signature. R/G in [0.85, 1.15] AND
                    # B < min(R,G)*0.85.
                    if 0.0 < gg and abs(rg - gg) / max(gg, 1e-6) < 0.15 and bg < min(rg, gg) * 0.85:
                        if "midtones_C" in plg.params:
                            warnings.append(
                                f"colorbalancergb.midtones_C={mt_c:.3f} on a "
                                f"likely-portrait target (R≈G>B in histogram) "
                                f"would tint skin — clamped to 0.05"
                            )
                        clamped_params["midtones_C"] = 0.05

            # ---- Hito 2.3: monochrome-dominance check ------------------------
            # If the VLM puts the SAME hue in shadows+midtones+highlights with
            # non-trivial chroma in all three, the result is a hidden global
            # tint — the very failure mode this Hito targets. Halve each chroma
            # (warn). Exception: when the reference analysis itself declares
            # ``hue_mode='mono'`` in all three zones with the same hue, the
            # reference IS intentionally monochrome and we respect it.
            _zones = ("shadows", "midtones", "highlights")
            hues = [float(clamped_params.get(f"{z}_H") or 0.0) for z in _zones]
            chroms = [float(clamped_params.get(f"{z}_C") or 0.0) for z in _zones]
            # Circular pairwise distance

            def _circular_diff(a: float, b: float) -> float:
                d = abs(a - b) % 360.0
                return min(d, 360.0 - d)

            same_hue = (
                _circular_diff(hues[0], hues[1]) < 15.0
                and _circular_diff(hues[1], hues[2]) < 15.0
                and _circular_diff(hues[0], hues[2]) < 15.0
            )
            all_chroma = all(c > 0.05 for c in chroms)
            if same_hue and all_chroma:
                # Exception: reference_analysis declares an intentional
                # uniform grade — either `mono` (Hito 2.3) or `global`
                # (Hito 6D: one coherent tint across the tonal range,
                # e.g. warm 15°/38°/33°).  The reference's zone hues may
                # spread up to ±45° (a warm grade is not pixel-identical
                # across zones), and the VLM's uniform hue must actually
                # agree with the reference's mean hue — a teal spec on a
                # warm-global reference is NOT intentional.
                allow = False
                if reference_analysis:
                    modes = [reference_analysis.get(f"{z}_hue_mode") for z in _zones]
                    ref_hues = [reference_analysis.get(f"{z}_hue") for z in _zones]
                    if all(m in ("mono", "global") for m in modes) and all(
                        h is not None for h in ref_hues
                    ):

                        def _wrap(h: float) -> float:
                            return h % 360.0

                        ref_same = (
                            _circular_diff(_wrap(ref_hues[0] or 0), _wrap(ref_hues[1] or 0)) < 45.0
                            and _circular_diff(_wrap(ref_hues[1] or 0), _wrap(ref_hues[2] or 0))
                            < 45.0
                        )
                        # The spec's uniform hue must match the reference's
                        # coherent grade (±45° between their circular means).
                        spec_mean = float(
                            _circular_mean(
                                [_wrap(h) for h in hues],
                            )
                        )
                        ref_mean = float(
                            _circular_mean(
                                [_wrap(float(h or 0.0)) for h in ref_hues],
                            )
                        )
                        if ref_same and _circular_diff(spec_mean, ref_mean) <= 45.0:
                            allow = True
                if not allow:
                    for zone in _zones:
                        c_key = f"{zone}_C"
                        if c_key in plg.params:
                            old = float(clamped_params[c_key] or 0.0)
                            warnings.append(
                                f"colorbalancergb monochrome-dominance: "
                                f"{c_key}={old:.3f} at hue {hues[_zones.index(zone)]:.1f}° "
                                f"matches the other zones' hue — collapsing "
                                f"to a global tint. Halved to {old / 2:.3f}. "
                                f"(Reference analysis does not declare this an "
                                f"intentional monochrome grade.)"
                            )
                        clamped_params[c_key] = float(clamped_params[c_key] or 0.0) / 2.0

        # ---- Hito 2.4: colorful-references desaturation guard ----
        # The prompt tells the VLM to keep saturation when references
        # are COLORFUL (global HSV >= 0.25), but the VLM has repeatedly
        # ignored it (Alen Palander: chose filmicrgb.saturation=-25 "to
        # match reference color intensity" while the references measure
        # 0.30 HSV — the per-zone delta metrics misled it).  Enforce the
        # rule here: a negative saturation contradicts the reference
        # look, clamp to 0.0 (neutral).  Keeps the style portable for
        # references that are genuinely desaturated (< 0.15 → allowed).
        if plg.operation == "filmicrgb":
            gsat = (reference_analysis or {}).get("global_saturation")
            sat = float(clamped_params.get("saturation") or 0.0)
            if (
                isinstance(gsat, int | float)
                and not isinstance(gsat, bool)
                and gsat >= 0.25
                and sat < 0.0
                and "saturation" in plg.params
            ):
                warnings.append(
                    f"filmicrgb.saturation={sat:.1f} contradicts colorful "
                    f"references (global HSV {gsat:.3f} >= 0.25) — "
                    f"clamped to 0.0"
                )
                clamped_params["saturation"] = 0.0

        # ---- Hito 2.5: temperature white-balance guard ----
        # The temperature module REPLACES the camera's white balance:
        # neutral coefficients (1,1,1,1) mean "no WB correction" and
        # produce wrong colors on RAW (red channel collapses — verified
        # E2E on a Sony ARW).  Only allow the module when the VLM chose
        # an intentional WB (coeffs clearly off neutral or a preset like
        # D65).  Otherwise drop it: omitting temperature keeps the
        # camera's as-shot WB, which is always the safe default.
        if plg.operation == "temperature":
            red = float(clamped_params.get("red") or 0.0)
            green = float(clamped_params.get("green") or 0.0)
            blue = float(clamped_params.get("blue") or 0.0)
            various = float(clamped_params.get("various") or 0.0)
            preset = int(clamped_params.get("preset") or 0)
            coeffs_neutral = (
                abs(red - 1.0) < 0.05
                and abs(green - 1.0) < 0.05
                and abs(blue - 1.0) < 0.05
                and abs(various - 1.0) < 0.05
            )
            # Coeffs off-neutral (e.g. warm red 1.8/blue 1.2) are a
            # deliberate WB choice -> keep.  Neutral coeffs with any
            # preset except D65 (which darktable late-corrects) are the
            # "identity" trap -> drop the whole plugin.
            if coeffs_neutral and preset != 3:
                warnings.append(
                    "temperature: neutral coefficients (1,1,1,1) would "
                    "REPLACE the camera white balance with identity "
                    "(wrong colors on RAW) — dropping the module; "
                    "camera as-shot WB is kept"
                )
                continue  # skip this plugin entirely
            if coeffs_neutral and preset == 3:
                warnings.append(
                    "temperature: neutral coefficients with D65 preset "
                    "kept (darktable applies late D65 correction)"
                )

        validated_plugins.append(
            Plugin(
                operation=plg.operation,
                enabled=plg.enabled,
                multi_name=plg.multi_name,
                multi_priority=plg.multi_priority,
                params=clamped_params,
            )
        )

    validated = StyleSpec(
        style_name=spec.style_name,
        style_description=spec.style_description,
        rationale=spec.rationale,
        iop_list=spec.iop_list,
        plugins=validated_plugins,
        selected_preset_names=list(spec.selected_preset_names),
    )
    return validated, warnings


def _validate_curve_preset(
    operation: str,
    val: object,
    template_names: set[str] | None,
) -> tuple[str | None, str | None]:
    """Validate a curve_preset value.

    Returns:
        (result_string_or_None, warning_message_or_None) tuple.
        result is the validated string if valid, None if invalid.
        warning_message is a human-readable string if invalid, None if valid.
    """
    if not isinstance(val, str):
        msg = f"{operation}.curve_preset: must be a string template name"
        logger.warning(msg)
        return None, msg

    if template_names is None:
        try:
            from dtstylekit.curves import REGISTRY as CURVE_REG

            template_names = {t.name for t in CURVE_REG}
        except ImportError:
            template_names = set()

    if val not in template_names:
        msg = (
            f"{operation}.curve_preset: '{val}' is not a known curve template "
            f"(available: {', '.join(sorted(template_names)) if template_names else '(none loaded)'})"
        )
        logger.warning(msg)
        return None, msg

    return val, None
