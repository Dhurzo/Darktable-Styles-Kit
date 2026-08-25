"""Minimal safety guards only — NO automatic aesthetic fits.

The VLM sees the reference images and chooses all creative parameters.
This function ONLY clamps impossible/unsafe values that would crash
darktable or produce visibly broken output. No automatic aesthetic
adjustments — the VLM sees the references and makes the creative calls.

Runs after ``validate_style`` whenever ``reference_analysis`` is available;
without references it is a no-op.
"""

from __future__ import annotations

import logging

from dtstylekit.vlm.models import StyleSpec

logger = logging.getLogger(__name__)


def auto_fit_signature(
    spec: StyleSpec,
    reference_analysis: dict | None,
    _analysis,
) -> tuple[StyleSpec, list[str]]:
    """Minimal safety guards only — NO automatic aesthetic fits.

    The VLM sees the reference images and chooses all creative parameters.
    This function ONLY clamps impossible/unsafe values that would crash
    darktable or produce visibly broken output. No automatic aesthetic
    adjustments — the VLM sees the references and makes the creative calls.

    Runs after ``validate_style`` whenever ``reference_analysis`` is available;
    without references it is a no-op.
    """
    warnings: list[str] = []
    if not reference_analysis:
        return spec, warnings

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
    if filmic:
        sat = filmic.params.get("saturation")
        if isinstance(sat, int | float) and not isinstance(sat, bool):
            if sat < -100:
                filmic.params["saturation"] = -100.0
                warnings.append("FIDELITY safety: filmicrgb.saturation clamped to -100")
            elif sat > 100:
                filmic.params["saturation"] = 100.0
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

    for w in warnings:
        logger.info(w)
    return spec, warnings


def compute_reference_profile(reference_paths) -> dict:
    """Extended reference profile: contrast, dynamic range, saturation
    peaks and warmth — the *shape* of the look, not just its averages.

    These are purely informational (for logging/debugging) and do NOT
    drive automatic fits. The VLM makes all creative decisions.
    """
    import numpy as np
    from PIL import Image

    stds: list[float] = []
    drs: list[float] = []
    sp90s: list[float] = []
    rbs: list[float] = []
    for ref in reference_paths:
        try:
            im = np.asarray(Image.open(ref).convert("RGB"), dtype=np.float32) / 255.0
            lum = 0.2126 * im[..., 0] + 0.7152 * im[..., 1] + 0.0722 * im[..., 2]
            stds.append(float(lum.std()))
            drs.append(float(np.percentile(lum, 95) - np.percentile(lum, 5)))
            mx, mn = im.max(-1), im.min(-1)
            sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0.0)
            sp90s.append(float(np.percentile(sat, 90)))
            rbs.append(float((im[..., 0] - im[..., 2]).mean()))
        except Exception:
            continue
    out: dict = {}
    if stds:
        out["global_contrast"] = sum(stds) / len(stds)
    if drs:
        out["global_dynamic_range"] = sum(drs) / len(drs)
    if sp90s:
        out["global_saturation_p90"] = sum(sp90s) / len(sp90s)
    if rbs:
        out["global_warmth_rb"] = sum(rbs) / len(rbs)
    return out
