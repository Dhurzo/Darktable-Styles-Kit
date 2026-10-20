"""IOP Registry for Darktable styles.

Maps operation names to their parameter struct layouts, default values,
ranges, and verified sizes. Supports pack/unpack of binary blobs.
"""

import struct

from dtstylekit.codec.curve_iops import _CURVE_IOPS
from dtstylekit.codec.refinement_iops import _REFINEMENT_IOPS
from dtstylekit.codec.registry_types import IOPRegistry
from dtstylekit.codec.simple_iops import _SIMPLE_IOPS
from dtstylekit.codec.verified_iops import _VERIFIED_IOPS

# Combined registry
IOP_REGISTRY: dict[str, IOPRegistry] = {}
IOP_REGISTRY.update(_VERIFIED_IOPS)
IOP_REGISTRY.update(_SIMPLE_IOPS)
IOP_REGISTRY.update(_REFINEMENT_IOPS)
IOP_REGISTRY.update(_CURVE_IOPS)


def get_registry(op: str) -> IOPRegistry | None:
    """Get registry entry for an operation name."""
    return IOP_REGISTRY.get(op)


def pack_params(op: str, params: dict) -> bytes:
    """Pack parameters into binary blob for an IOP.

    Merges with defaults, validates ranges, then struct.pack.

    For curve-based IOPs (``colorzones``, ``rgbcurve``, ``tonecurve``)
    this function recognises a virtual ``curve_preset`` field.  When
    present it overrides the binary spline data via the
    :mod:`dtstylekit.curves` subsystem; remaining scalars are still
    validated against the registry ranges and merged with defaults.

    Args:
        op: Operation name (e.g., "filmicrgb")
        params: Dictionary of parameter values.  May include the virtual
            ``curve_preset`` key for curve IOPs.

    Returns:
        Packed binary blob ready for encode_xmp()

    Raises:
        ValueError: If operation not in registry or parameter out of range
    """
    reg = get_registry(op)
    if reg is None:
        raise ValueError(f"Unknown operation: {op}")

    # Curve-based IOPs: delegate to the curve-template system.
    if reg.is_curve_iop:
        return _pack_curve_iop(reg, params)

    # basecurve: cannot be packed from scratch (camera-specific curve data).
    if reg.pack_format == "<basecurve>":
        raise ValueError(
            "basecurve cannot be packed from scratch — it always comes "
            "from existing presets via op_params_override. "
            "To include basecurve, reference a preset blob."
        )

    # Merge defaults with provided params
    merged = {**reg.defaults, **params}

    # Validate ranges.  Float bounds get a small float32-scale tolerance:
    # values decoded from real preset blobs land a hair outside their
    # declared minimum/maximum (e.g. filmicrgb latitude default 0.01 →
    # 0.009999999776482582) and must survive a re-pack.  Integer bounds
    # stay strict.
    for field, (min_val, max_val) in reg.ranges.items():
        val = merged.get(field)
        if val is None:
            continue
        if isinstance(min_val, int | float) and not isinstance(min_val, bool):
            tol = 1e-6 * max(1.0, abs(float(min_val)), abs(float(max_val)))
            lo, hi = float(min_val) - tol, float(max_val) + tol
        else:
            lo, hi = float(min_val), float(max_val)  # type: ignore[assignment]
        if not (lo <= val <= hi):
            raise ValueError(f"{op}.{field}={val} out of range [{min_val}, {max_val}]")

    # Build values in field order
    values = [merged[field] for field in reg.fields]

    # Pack
    return struct.pack(reg.pack_format, *values)


def _pack_curve_iop(reg: "IOPRegistry", params: dict) -> bytes:
    """Pack a curve-based IOP via the curves templates subsystem.

    Args:
        reg: The IOP's registry entry.
        params: May include ``curve_preset`` plus scalar overrides
            (e.g. ``strength`` for colorzones, ``preserve_colors``
            for tonecurve, etc.).

    Returns:
        Packed bytes, exactly ``curve_pack_size_override`` (or the IOP
        size from ``dtstylekit.curves``).
    """
    # Lazy import to avoid a hard dependency cycle
    from dtstylekit.curves import REGISTRY as CURVE_REG
    from dtstylekit.curves import apply_curve_template, curve_iop_size

    if "curve_preset" not in params:
        raise ValueError(
            f"{reg.operation} is a curve-based IOP and requires a "
            f"'curve_preset' parameter in {sorted(t.name for t in CURVE_REG)}"
        )
    template = params.pop("curve_preset")
    if not isinstance(template, str):
        raise ValueError(f"curve_preset must be a string, got {type(template).__name__}")

    # Forward remaining scalars (e.g. colorzones.strength) as overrides
    kwargs = {
        k: v for k, v in params.items() if k in _CURVE_FORWARD_PARAMS.get(reg.operation, set())
    }
    blob = apply_curve_template(reg.operation, template, **kwargs)
    expected = reg.curve_pack_size_override or curve_iop_size(reg.operation)
    assert (
        len(blob) == expected
    ), f"{reg.operation} curve_preset pack produced {len(blob)} bytes, expected {expected}"
    return blob


# Scalar parameters that are forwarded from ``curve_preset`` kwargs in
# addition to the curve nodes themselves.
_CURVE_FORWARD_PARAMS: dict[str, set[str]] = {
    "colorzones": {"strength", "mode", "channel"},
    "rgbcurve": {"curve_autoscale", "compensate_middle_grey", "preserve_colors"},
    "tonecurve": {
        "tonecurve_autoscale_ab",
        "tonecurve_preset",
        "tonecurve_unbound_ab",
        "preserve_colors",
    },
}


def unpack_params(op: str, blob: bytes) -> dict:
    """Unpack binary blob into parameter dictionary.

    Args:
        op: Operation name
        blob: Binary blob from decode_xmp()

    Returns:
        Dictionary mapping field names to values

    Raises:
        ValueError: If operation not in registry or blob size mismatch
    """
    reg = get_registry(op)
    if reg is None:
        raise ValueError(f"Unknown operation: {op}")

    # Curve IOPs: route to dedicated unpacker
    if reg.is_curve_iop:
        return _unpack_curve_iop(reg, blob)

    # basecurve: extract only the scalar portion at offset 480.
    if reg.pack_format == "<basecurve>":
        if len(blob) != 520:
            raise ValueError(f"basecurve blob must be 520 bytes, got {len(blob)}")
        # Layout at offset 480: 3i (nodes) + 3i (type) + i (fusion) + f (stops) + f (bias) + i (preserve)
        # Veryfied: <3i3iiffi = 40 bytes, yields (6,0,0, 2,0,0, 0, 1.0, 1.0, 1)
        nodes0, nodes1, nodes2, type0, type1, type2, fusion, stops, bias, preserve = struct.unpack(
            "<3i3iiffi", blob[480 : 480 + struct.calcsize("<3i3iiffi")]
        )
        return {
            "basecurve_nodes_0": nodes0,
            "basecurve_nodes_1": nodes1,
            "basecurve_nodes_2": nodes2,
            "basecurve_type_0": type0,
            "basecurve_type_1": type1,
            "basecurve_type_2": type2,
            "exposure_fusion": fusion,
            "exposure_stops": stops,
            "exposure_bias": bias,
            "preserve_colors": preserve,
        }

    if reg.size_bytes is not None and len(blob) not in {reg.size_bytes, *reg.legacy_size_bytes}:
        raise ValueError(f"Blob size mismatch for {op}: expected {reg.size_bytes}, got {len(blob)}")

    # Legacy blob (older module version shipped in official styles):
    # unpack with the legacy format when one is registered.
    if reg.legacy_pack_format is not None and len(blob) in reg.legacy_size_bytes:
        values = struct.unpack(reg.legacy_pack_format, blob)
        return dict(zip(reg.legacy_fields, values, strict=True))

    values = struct.unpack(reg.pack_format, blob)
    return dict(zip(reg.fields, values, strict=True))


def _unpack_curve_iop(reg: "IOPRegistry", blob: bytes) -> dict:
    """Unpack a curve-based IOP blob back to a dict.

    The curve I/O modules in :mod:`dtstylekit.curves` do the heavy
    lifting.  We return a *partial* dict: scalars are reconstructed
    from defaults, but the spline data is reported under the synthetic
    ``curve_preset`` key as ``"(binary: <size> bytes)"`` because we don't
    know which template was used to produce the blob.
    """
    from dtstylekit.curves import (
        unpack_colorzones,
        unpack_rgbcurve,
        unpack_tonecurve,
    )
    from dtstylekit.curves.packing import ColorzonesParams, RGBCurveParams, TonecurveParams

    if reg.operation == "colorzones":
        cz_params: ColorzonesParams = unpack_colorzones(blob)
        return {
            "channel": cz_params.channel,
            "strength": cz_params.strength,
            "mode": cz_params.mode,
            "splines_version": cz_params.splines_version,
            "curve_preset": "(binary: 520 bytes)",
        }
    if reg.operation == "rgbcurve":
        rgb_params: RGBCurveParams = unpack_rgbcurve(blob)
        return {
            "curve_autoscale": rgb_params.curve_autoscale,
            "compensate_middle_grey": rgb_params.compensate_middle_grey,
            "preserve_colors": rgb_params.preserve_colors,
            "curve_preset": "(binary: 516 bytes)",
        }
    if reg.operation == "tonecurve":
        tc_params: TonecurveParams = unpack_tonecurve(blob)
        return {
            "tonecurve_autoscale_ab": tc_params.tonecurve_autoscale_ab,
            "tonecurve_preset": tc_params.tonecurve_preset,
            "tonecurve_unbound_ab": tc_params.tonecurve_unbound_ab,
            "preserve_colors": tc_params.preserve_colors,
            "curve_preset": "(binary: 520 bytes)",
        }
    raise ValueError(f"_unpack_curve_iop: unknown operation {reg.operation}")


def verify_size(op: str, blob: bytes) -> bool:
    """Verify blob size matches expected size for operation.

    Args:
        op: Operation name
        blob: Binary blob

    Returns:
        True if size matches (or size not verified), False otherwise
    """
    reg = get_registry(op)
    if reg is None:
        return False
    if reg.size_bytes is None:
        return True  # Can't verify, assume OK
    return len(blob) == reg.size_bytes or len(blob) in reg.legacy_size_bytes


def list_registered() -> list[str]:
    """Return sorted list of all registered operation names."""
    return sorted(IOP_REGISTRY.keys())


def list_verified() -> list[str]:
    """Return sorted list of operations with verified blob sizes."""
    return sorted(op for op, reg in IOP_REGISTRY.items() if reg.size_bytes is not None)


def list_unverified() -> list[str]:
    """Return sorted list of operations without verified blob sizes."""
    return sorted(op for op, reg in IOP_REGISTRY.items() if reg.size_bytes is None)


__all__ = [
    "IOPRegistry",
    "IOP_REGISTRY",
    "get_registry",
    "pack_params",
    "unpack_params",
    "verify_size",
    "list_registered",
    "list_verified",
    "list_unverified",
]
