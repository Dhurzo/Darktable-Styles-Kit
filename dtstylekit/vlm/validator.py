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


# String-valued virtual fields that must be handled separately from
# numeric ranges.  Their "range" in the registry is a tuple of valid
# string choices, NOT a numeric (lo, hi) pair.
_STRING_VIRTUAL_FIELDS = {"curve_preset"}


def validate_style(
    spec: StyleSpec,
    registry: dict,
) -> tuple[StyleSpec, list[str]]:
    """Validate the StyleSpec.

    Args:
        spec: Parsed StyleSpec from VLM.
        registry: Dict mapping operation name -> IOPRegistry-like dataclass.

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
                lo_r, hi_r = range_val
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
