"""Exposure suitability checks for preset candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Preset


def preset_net_ev(preset: Preset) -> float:
    """Net exposure EV contributed by a preset's enabled exposure IOPs.

    Decodes the exposure blobs (v6 or v7 layout) and sums their
    ``exposure`` field. A preset like "day for twilight" contributes
    -1.0 EV; a plain color preset contributes 0.0.
    """
    from dtstylekit.codec.iop_registry import unpack_params
    from dtstylekit.codec.xmp_codec import decode_xmp

    ev = 0.0
    for plg in preset.plugins:
        if plg.operation != "exposure" or not plg.enabled or not plg.op_params:
            continue
        try:
            params = unpack_params("exposure", decode_xmp(plg.op_params))
            ev += float(params.get("exposure", 0.0))
        except Exception:
            continue
    return ev


def preset_ev_fits(preset: Preset, mean_lum: float) -> bool:
    """Whether a preset's net exposure suits the image's brightness.

    Dark images (mean luminance < 0.3) are crushed by darkening presets
    (net EV < -0.3); bright images (> 0.7) are blown out by brightening
    presets (net EV > +0.3). Everything else is acceptable.

    In addition, for dark images we drop dehaze/defog presets by name:
    hazeremoval is not in the IOP registry (its blob cannot be decoded
    for a net-EV estimate), but dehaze removes atmospheric brightness,
    which empirically crushes dark images.
    """
    ev = preset_net_ev(preset)
    if mean_lum < 0.3 and ev < -0.3:
        return False
    if mean_lum > 0.7 and ev > 0.3:
        return False
    if mean_lum < 0.3:
        name = " ".join(
            part.lower() for part in (preset.name, getattr(preset, "description", "") or "") if part
        )
        if any(kw in name for kw in ("dehaze", "defog", "fog", "mist")):
            return False
    return True
