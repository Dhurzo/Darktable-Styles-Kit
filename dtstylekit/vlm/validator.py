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
from collections.abc import Mapping
from typing import Any

from dtstylekit.color import circular_diff as _circular_diff
from dtstylekit.color import circular_mean as _circular_mean

from .models import Plugin, StyleSpec

logger = logging.getLogger(__name__)


# String-valued virtual fields that must be handled separately from
# numeric ranges.  Their "range" in the registry is a tuple of valid
# string choices, NOT a numeric (lo, hi) pair.
_STRING_VIRTUAL_FIELDS = {"curve_preset"}


def validate_style(
    spec: StyleSpec,
    registry: dict,
    reference_analysis: Mapping[str, Any] | None = None,
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

    # Curve template names are not preset filenames.  The VLM occasionally
    # puts one in selected_presets (e.g. "s_strong"); drop it here instead of
    # failing the preset lookup later.
    try:
        from dtstylekit.curves.templates import list_templates

        curve_template_names = {t.name for t in list_templates()}
    except Exception:  # pragma: no cover - curve subsystem unavailable
        pass
    selected_presets = _filter_curve_template_presets(
        list(spec.selected_preset_names), curve_template_names, warnings
    )

    for plg in spec.plugins:
        if plg.operation not in registry:
            warnings.append(f"Unknown IOP '{plg.operation}' — skipped")
            continue
        reg = registry[plg.operation]
        clamped_params, curve_template_names = _clamp_plugin_params(
            plg, reg, curve_template_names, warnings
        )

        if plg.operation == "colorbalancergb":
            _apply_colorbalancergb_guards(
                plg, clamped_params, warnings, reference_analysis, target_analysis
            )

        if plg.operation == "filmicrgb":
            _apply_filmicrgb_guard(plg, clamped_params, warnings, reference_analysis)

        if plg.operation == "temperature":
            if not _apply_temperature_guard(clamped_params, warnings):
                continue

        if plg.operation == "exposure":
            _apply_exposure_guard(clamped_params, warnings)

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
        plugins=tuple(validated_plugins),
        selected_preset_names=tuple(selected_presets),
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


def _filter_curve_template_presets(
    selected_presets: list[str],
    curve_template_names: set[str] | None,
    warnings: list[str],
) -> list[str]:
    """Drop curve-template names accidentally placed in ``selected_presets``."""
    if not curve_template_names:
        return selected_presets
    kept: list[str] = []
    for name in selected_presets:
        bare = name.rsplit(".", 1)[0] if name.endswith(".dtstyle") else name
        if bare in curve_template_names:
            warnings.append(
                f"selected_presets: '{name}' is a curve template, not a preset "
                f"file — ignored (use adjustments.*.curve_preset instead)"
            )
        else:
            kept.append(name)
    return kept


def _clamp_plugin_params(
    plg: Plugin,
    reg: object,
    curve_template_names: set[str] | None,
    warnings: list[str],
) -> tuple[dict, set[str] | None]:
    """Merge defaults and clamp a plugin's params against the IOP registry."""
    is_curve = getattr(reg, "is_curve_iop", False)
    ranges = getattr(reg, "ranges", {})
    defaults = getattr(reg, "defaults", {})

    merged_params = dict(defaults)
    merged_params.update(plg.params)

    clamped_params: dict = {}
    for fld, val in merged_params.items():
        if fld not in ranges and fld not in _STRING_VIRTUAL_FIELDS:
            if fld in plg.params:
                warnings.append(f"{plg.operation}.{fld}: unknown field — ignored")
            continue

        in_range = fld in ranges
        range_val = ranges.get(fld)

        if fld in _STRING_VIRTUAL_FIELDS:
            if is_curve:
                result, warn_msg = _validate_curve_preset(
                    plg.operation, val, curve_template_names
                )
                if warn_msg:
                    warnings.append(warn_msg)
                if curve_template_names is None and result is None:
                    try:
                        from dtstylekit.curves import REGISTRY as CURVE_REG

                        curve_template_names = {t.name for t in CURVE_REG}
                    except ImportError:
                        curve_template_names = set()
                    result, warn_msg = _validate_curve_preset(
                        plg.operation, val, curve_template_names
                    )
                    if warn_msg:
                        warnings.append(warn_msg)
                if result is not None:
                    clamped_params[fld] = result
            continue

        if in_range and range_val is not None:
            lo_r, _ = range_val
            if isinstance(lo_r, str):
                if val not in range_val:
                    if fld in plg.params:
                        warnings.append(
                            f"{plg.operation}.{fld}: '{val}' not in "
                            f"allowed values {range_val} — ignored"
                        )
                    continue
                clamped_params[fld] = val
                continue

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
            if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool):
                num_val = int(num_val)

        clamped_params[fld] = num_val

    return clamped_params, curve_template_names


def _apply_colorbalancergb_guards(
    plg: Plugin,
    clamped_params: dict,
    warnings: list[str],
    reference_analysis: Mapping[str, Any] | None,
    target_analysis: object | None,
) -> None:
    """Apply colorbalancergb semantic guards in their historical order."""

    def _neutral_hue(h: float | None) -> bool:
        return abs(float(h or 0.0)) < 1e-3 or float(h or 0.0) > 359.999

    gc = float(clamped_params.get("global_C") or 0.0)
    gh = float(clamped_params.get("global_H") or 0.0)
    if gc > 0.0:
        if reference_analysis is not None:
            if "global_C" in plg.params:
                warnings.append(
                    "colorbalancergb.global_C>0 tints EVERY pixel "
                    "(additive offset) — forced to 0.0; reference "
                    "grades belong in the tonal zones"
                )
            clamped_params["global_C"] = 0.0
        elif _neutral_hue(gh):
            if "global_C" in plg.params:
                warnings.append(
                    "colorbalancergb.global_C>0 with global_H≈0 tints the "
                    "whole image RED (additive offset, hue 0°=red) — "
                    "global_C forced to 0.0"
                )
            clamped_params["global_C"] = 0.0

    for zone in ("shadows", "midtones", "highlights"):
        c_key = f"{zone}_C"
        h_key = f"{zone}_H"
        cz = float(clamped_params.get(c_key) or 0.0)
        hz = float(clamped_params.get(h_key) or 0.0)
        if cz > 0.0 and _neutral_hue(hz):
            if c_key in plg.params:
                warnings.append(
                    f"colorbalancergb.{c_key}>0 with {h_key}≈0 tints "
                    f"{zone} red/warm (Yrg hue 0° = conventional -30°). "
                    f"For neutral grading (respect target colors) "
                    f"{c_key} forced to 0.0"
                )
            clamped_params[c_key] = 0.0

    _NEUTRAL_CONF = 0.70
    for _zone in ("shadows", "midtones", "highlights"):
        _c_key = f"{_zone}_C"
        if _c_key not in clamped_params:
            continue
        _cz = float(clamped_params.get(_c_key) or 0.0)
        if _cz <= 0.0:
            continue
        _conf = float((reference_analysis or {}).get(f"{_zone}_hue_confidence") or 0.0)
        _mode = (reference_analysis or {}).get(f"{_zone}_hue_mode")
        if _mode in ("mono", "bi", "global"):
            continue
        if reference_analysis is not None and _conf < _NEUTRAL_CONF:
            if _c_key in plg.params:
                warnings.append(
                    f"colorbalancergb.{_c_key}={_cz:.3f} on a low-confidence "
                    f"reference (conf={_conf:.2f} < {_NEUTRAL_CONF}): would tint "
                    f"a non-graded look — forced to 0.0 (respect target colors)"
                )
            clamped_params[_c_key] = 0.0

    _zone_caps_default = {"shadows": 0.10, "midtones": 0.08, "highlights": 0.05}
    _zone_caps_highconf = {"shadows": 0.15, "midtones": 0.15, "highlights": 0.10}
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
        sat = float((reference_analysis or {}).get(f"{zone}_sat") or 0.0)
        if sat > 0.0:
            cap = min(cap, sat)
        if cz > cap:
            if c_key in plg.params:
                warnings.append(
                    f"colorbalancergb.{c_key}={cz:.3f} exceeds dynamic "
                    f"cap {cap:.2f} (reference {conf_key}={conf:.2f}, "
                    f"threshold 0.85 for relaxed cap) — clamped"
                )
            clamped_params[c_key] = cap

    mt_c = float(clamped_params.get("midtones_C") or 0.0)
    if mt_c > 0.05 and target_analysis is not None:
        hist = getattr(target_analysis, "histogram", None)
        if hist is not None:
            rg = float(getattr(hist, "mean_red", 0.0) or 0.0)
            gg = float(getattr(hist, "mean_green", 0.0) or 0.0)
            bg = float(getattr(hist, "mean_blue", 0.0) or 0.0)
            if 0.0 < gg and abs(rg - gg) / max(gg, 1e-6) < 0.15 and bg < min(rg, gg) * 0.85:
                if "midtones_C" in plg.params:
                    warnings.append(
                        f"colorbalancergb.midtones_C={mt_c:.3f} on a "
                        f"likely-portrait target (R≈G>B in histogram) "
                        f"would tint skin — clamped to 0.05"
                    )
                clamped_params["midtones_C"] = 0.05

    _zones = ("shadows", "midtones", "highlights")
    hues = [float(clamped_params.get(f"{z}_H") or 0.0) for z in _zones]
    chroms = [float(clamped_params.get(f"{z}_C") or 0.0) for z in _zones]
    same_hue = (
        _circular_diff(hues[0], hues[1]) < 15.0
        and _circular_diff(hues[1], hues[2]) < 15.0
        and _circular_diff(hues[0], hues[2]) < 15.0
    )
    all_chroma = all(c > 0.05 for c in chroms)
    if same_hue and all_chroma:
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
                    and _circular_diff(_wrap(ref_hues[1] or 0), _wrap(ref_hues[2] or 0)) < 45.0
                )
                spec_mean = float(_circular_mean([_wrap(h) for h in hues]))
                ref_mean = float(
                    _circular_mean([_wrap(float(h or 0.0)) for h in ref_hues])
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


def _apply_filmicrgb_guard(
    plg: Plugin,
    clamped_params: dict,
    warnings: list[str],
    reference_analysis: Mapping[str, Any] | None,
) -> None:
    """Reject filmicrgb saturation that contradicts colorful references."""
    gsat = (reference_analysis or {}).get("global_saturation")
    sat = float(clamped_params.get("saturation") or 0.0)
    if (
        isinstance(gsat, int | float)
        and not isinstance(gsat, bool)
        and gsat >= 0.15
        and sat < 0.0
        and "saturation" in plg.params
    ):
        warnings.append(
            f"filmicrgb.saturation={sat:.1f} contradicts colorful "
            f"references (global HSV {gsat:.3f} >= 0.15) — "
            f"clamped to 0.0"
        )
        clamped_params["saturation"] = 0.0


def _apply_temperature_guard(
    clamped_params: dict,
    warnings: list[str],
) -> bool:
    """Drop temperature with neutral coefficients unless it is an explicit D65."""
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
    if coeffs_neutral and preset != 3:
        warnings.append(
            "temperature: neutral coefficients (1,1,1,1) would "
            "REPLACE the camera white balance with identity "
            "(wrong colors on RAW) — dropping the module; "
            "camera as-shot WB is kept"
        )
        return False
    if coeffs_neutral and preset == 3:
        warnings.append(
            "temperature: neutral coefficients with D65 preset "
            "kept (darktable applies late D65 correction)"
        )
    return True


def _apply_exposure_guard(
    clamped_params: dict,
    warnings: list[str],
) -> None:
    """Clamp exposure.black to a subtle scene-linear level."""
    black = float(clamped_params.get("black") or 0.0)
    _BLACK_LIMIT = 0.005
    if black > _BLACK_LIMIT:
        clamped_params["black"] = _BLACK_LIMIT
        warnings.append(
            f"exposure.black={black:+.3f} is a scene-linear black level "
            f"(not a display point); clamped to +{_BLACK_LIMIT:.3f} to "
            f"avoid crushing shadows"
        )
    elif black < -_BLACK_LIMIT:
        clamped_params["black"] = -_BLACK_LIMIT
        warnings.append(
            f"exposure.black={black:+.3f} lifts scene-linear blacks too "
            f"strongly; clamped to -{_BLACK_LIMIT:.3f}"
        )
