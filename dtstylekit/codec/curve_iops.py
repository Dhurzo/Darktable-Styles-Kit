"""Curve-based IOP definitions."""

from dtstylekit.codec.registry_types import IOPRegistry

# ---------------------------------------------------------------------------
# Curve-based IOPs.
# These IOPs store 3 × 20-node splines in addition to (small) scalar
# fields.  Because the binary layout is multiple hundred floats long and
# *cannot* be hand-built by an LLM, we register them with a virtual
# ``curve_preset`` field and redirect packing to the dedicated
# :mod:`dtstylekit.curves` subsystem.  ``pack_format`` is the size in
# bytes (which is the same value checked by :func:`curve_iop_size`).
# ---------------------------------------------------------------------------
_CURVE_IOPS = {
    "colorzones": IOPRegistry(
        operation="colorzones",
        version=5,
        pack_format="<curve>",  # placeholder — never actually struct-packed
        fields=(
            # Curve data is fully managed by ``curve_preset``; scalars
            # below are forwarded as kwargs to the curves.pack helpers.
            "channel",
            "strength",
            "mode",
            "splines_version",
            # Synthetic marker — not a real field on the struct but
            # recognised by ``pack_params`` and routed to the curve
            # templates subsystem before struct.pack ever sees it.
            "curve_preset",
        ),
        defaults={
            "channel": 0,
            "strength": 0.0,
            "mode": 0,  # ZONES_SMOOTH
            "splines_version": 1,
            "curve_preset": "identity",
        },
        ranges={
            "channel": (0, 2),
            "strength": (-200.0, 200.0),
            "mode": (0, 1),
            "splines_version": (0, 10),
            # ``curve_preset`` accepts *string* keys — range is informal,
            # the validator cross-checks against the curves registry.
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=520,
        blendop_cst=2,  # LAB (colorzones/tonecurve work in Lab)
        is_curve_iop=True,
        curve_pack_size_override=520,
    ),
    "rgbcurve": IOPRegistry(
        operation="rgbcurve",
        version=1,
        pack_format="<curve>",
        fields=(
            "curve_autoscale",
            "compensate_middle_grey",
            "preserve_colors",
            "curve_preset",
        ),
        defaults={
            "curve_autoscale": 1,
            "compensate_middle_grey": 0,
            "preserve_colors": 0,
            "curve_preset": "identity",
        },
        ranges={
            "curve_autoscale": (0, 1),
            "compensate_middle_grey": (0, 1),
            "preserve_colors": (0, 2),
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=516,
        blendop_cst=4,  # RGB_SCENE (rgbcurve is scene-referred)
        is_curve_iop=True,
        curve_pack_size_override=516,
    ),
    "tonecurve": IOPRegistry(
        operation="tonecurve",
        version=5,
        pack_format="<curve>",
        fields=(
            "tonecurve_autoscale_ab",
            "tonecurve_preset",
            "tonecurve_unbound_ab",
            "preserve_colors",
            "curve_preset",
        ),
        defaults={
            "tonecurve_autoscale_ab": 1,
            "tonecurve_preset": 0,
            "tonecurve_unbound_ab": 1,
            "preserve_colors": 0,
            "curve_preset": "identity",
        },
        ranges={
            "tonecurve_autoscale_ab": (0, 1),
            "tonecurve_preset": (0, 10),
            "tonecurve_unbound_ab": (0, 1),
            "preserve_colors": (0, 2),
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=520,
        blendop_cst=2,  # LAB (colorzones/tonecurve work in Lab)
        is_curve_iop=True,
        curve_pack_size_override=520,
    ),
}
