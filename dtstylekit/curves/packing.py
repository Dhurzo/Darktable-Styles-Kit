"""Pack/unpack helpers for curve-based IOPs.

This module isolates the binary layout of the three curve-based IOPs:
``colorzones``, ``rgbcurve`` and ``tonecurve``.  Each shares the same
fundamental layout — *N channels × M nodes* with separate ``x`` and
``y`` arrays — but they differ in their accompanying scalar fields
(channel selectors, modes, autoscale flags, etc.).

We treat each curve-IOP as a small typed struct whose **curve** field
is a list of channels, each carrying a list of ``(x, y)`` nodes. The
helpers here translate between that Python-native representation and
the exact byte layout Darktable imports.

The byte layouts are derived from:

* ``glm5Generated/iop_modules_catalog.md`` § 14 (colorzones)
* ``glm5Generated/iop_modules_catalog.md`` § 22 (rgbcurve)
* ``glm5Generated/iop_modules_catalog.md`` § 23 (tonecurve)
* ``src/iop/colorzones.c``, ``src/iop/rgbcurve.c``, ``src/iop/tonecurve.c``
  in the Darktable source tree

Because the exact padding of these structs depends on the C compiler,
we **do not** round-trip against an unknown blob size — we always emit
explicit sized records.  Round-trip can therefore be checked by
``pack -> unpack`` symmetry, not against an example blob from
``data/styles/``.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field

# Local curve templates import (no circular dependency)
from .templates import CurveTemplate, get_template

# ---------------------------------------------------------------------------
# Curve node layout constants (from iop_modules_catalog.md)
# ---------------------------------------------------------------------------

MAX_CURVE_NODES = 20  # DT_IOP_RGBCURVE_MAXNODES / DT_IOP_COLORZONES_MAXNODES / TONE
MAX_CURVE_CHANNELS = 3  # R, G, B (or H, S, L depending on IOP)

# Curve interpolation types (from iop_modules_catalog.md colorzones)
CUBIC_SPLINE = 0
CATMULL_ROM = 1
MONOTONE_HERMITE = 2

# colorzones modes
ZONES_SMOOTH = 0
ZONES_STRONG = 1


# ---------------------------------------------------------------------------
# Python representations
# ---------------------------------------------------------------------------


@dataclass
class ColorzonesParams:
    """Python representation of ``dt_iop_colorzones_params_t``."""

    channel: int = 0  # 0=h, 1=C, 2=h (legacy — kept as-is)
    curve_x: list[list[float]] = field(default_factory=list)  # 3 × ≤20 floats
    curve_y: list[list[float]] = field(default_factory=list)  # 3 × ≤20 floats
    curve_num_nodes: list[int] = field(default_factory=list)  # length 3
    curve_type: list[int] = field(default_factory=lambda: [MONOTONE_HERMITE] * 3)
    strength: float = 0.0
    mode: int = ZONES_SMOOTH
    splines_version: int = 1

    def validate(self) -> None:
        assert len(self.curve_x) == 3, "curve_x must have 3 channels"
        assert len(self.curve_y) == 3, "curve_y must have 3 channels"
        for ch_x, ch_y in zip(self.curve_x, self.curve_y, strict=False):
            assert len(ch_x) == len(ch_y), "x/y per channel length mismatch"
            assert 2 <= len(ch_x) <= MAX_CURVE_NODES, "node count out of range"
            assert all(0.0 <= x <= 1.0 for x in ch_x), "x out of [0,1]"
            assert all(0.0 <= y <= 1.0 for y in ch_y), "y out of [0,1]"
        assert len(self.curve_num_nodes) == 3
        assert len(self.curve_type) == 3


@dataclass
class RGBCurveParams:
    """Python representation of ``dt_iop_rgbcurve_params_t``."""

    curve_nodes_x: list[list[float]] = field(default_factory=list)
    curve_nodes_y: list[list[float]] = field(default_factory=list)
    curve_num_nodes: list[int] = field(default_factory=list)
    curve_type: list[int] = field(default_factory=lambda: [MONOTONE_HERMITE] * 3)
    curve_autoscale: int = 1  # 0=manual, 1=automatic
    compensate_middle_grey: int = 0
    preserve_colors: int = 0

    def validate(self) -> None:
        assert len(self.curve_nodes_x) == 3
        assert len(self.curve_nodes_y) == 3
        for ch_x, ch_y in zip(self.curve_nodes_x, self.curve_nodes_y, strict=False):
            n = len(ch_x)
            assert n == len(ch_y), "x/y per channel length mismatch"
            assert 2 <= n <= MAX_CURVE_NODES
            assert all(0.0 <= x <= 1.0 for x in ch_x), "x out of [0,1]"
            assert all(0.0 <= y <= 1.0 for y in ch_y), "y out of [0,1]"


@dataclass
class TonecurveParams:
    """Python representation of ``dt_iop_tonecurve_params_t``."""

    tonecurve_x: list[list[float]] = field(default_factory=list)
    tonecurve_y: list[list[float]] = field(default_factory=list)
    tonecurve_nodes: list[int] = field(default_factory=list)
    tonecurve_type: list[int] = field(default_factory=lambda: [MONOTONE_HERMITE] * 3)
    tonecurve_autoscale_ab: int = 1
    tonecurve_preset: int = 0
    tonecurve_unbound_ab: int = 1
    preserve_colors: int = 0  # 0=AVERAGE, 1=LUMINANCE, ...

    def validate(self) -> None:
        assert len(self.tonecurve_x) == 3
        assert len(self.tonecurve_y) == 3
        for ch_x, ch_y in zip(self.tonecurve_x, self.tonecurve_y, strict=False):
            n = len(ch_x)
            assert n == len(ch_y), "x/y per channel length mismatch"
            assert 2 <= n <= MAX_CURVE_NODES
            assert all(0.0 <= x <= 1.0 for x in ch_x), "x out of [0,1]"
            assert all(0.0 <= y <= 1.0 for y in ch_y), "y out of [0,1]"


# ---------------------------------------------------------------------------
# Internal pack format strings (little-endian, padded to MAX_CURVE_NODES)
# ---------------------------------------------------------------------------

# colorzones (v5) — see iop_modules_catalog.md §14:
# int channel; float curve_x[3][20]; float curve_y[3][20];
# int curve_num_nodes[3]; int curve_type[3]; float strength;
# int mode; int splines_version;
# → 4 + 120×4 + 120×4 + 3×4 + 3×4 + 4 + 4 + 4 = 1024 bytes (no padding)
COLORZONES_FMT = (
    "<"  # little-endian
    "i"  # channel
    + "20f" * 3  # curve_x[3][20]
    + "20f" * 3  # curve_y[3][20]
    + "3i"
    + "3i"  # curve_num_nodes, curve_type
    + "f"  # strength
    + "2i"  # mode, splines_version
)
COLORZONES_SIZE = struct.calcsize(COLORZONES_FMT)  # should be 1024

# rgbcurve (v1):
# float curve_nodes_x[3][20]; float curve_nodes_y[3][20];
# int curve_num_nodes[3]; int curve_type[3]; int curve_autoscale;
# int compensate_middle_grey (gboolean as 4-byte int);
# int preserve_colors
RGBCURVE_FMT = (
    "<"
    + "20f" * 3
    + "20f" * 3
    + "3i"
    + "3i"
    + "i"  # curve_autoscale
    + "i"  # compensate_middle_grey
    + "i"  # preserve_colors
)
RGBCURVE_SIZE = struct.calcsize(RGBCURVE_FMT)

# tonecurve (v5):
# float tonecurve_x[3][20]; float tonecurve_y[3][20];
# int tonecurve_nodes[3]; int tonecurve_type[3]; int tonecurve_autoscale_ab;
# int tonecurve_preset; int tonecurve_unbound_ab; int preserve_colors
TONECURVE_FMT = "<" + "20f" * 3 + "20f" * 3 + "3i" + "3i" + "i" + "i" + "i" + "i"
TONECURVE_SIZE = struct.calcsize(TONECURVE_FMT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pad_nodes(
    nodes: Sequence[tuple[float, float]], max_n: int = MAX_CURVE_NODES
) -> tuple[list[float], list[float]]:
    """Pad an ``(x, y)`` list to exactly ``max_n`` entries by repeating
    the last point.  Padded entries must extend the curve monotonically
    so Darktable's spline solver does not stall."""
    if len(nodes) < 2:
        raise ValueError("Curve must have at least 2 nodes")
    if len(nodes) > max_n:
        nodes = nodes[:max_n]
    xs = [n[0] for n in nodes]
    ys = [n[1] for n in nodes]
    last_x, last_y = xs[-1], ys[-1]
    while len(xs) < max_n:
        xs.append(last_x)
        ys.append(last_y)
    return xs, ys


def _apply_template_to_channels(
    template: CurveTemplate,
) -> tuple[list[list[float]], list[list[float]]]:
    """Expand a template's nodes into 3 channel-specific x/y lists.

    If the template's ``channels`` include ``"all"`` or all 3 of R/G/B,
    every channel gets the same curve.  Otherwise the named channels
    get their curve, the others default to identity.
    """
    # Build all-channel default (identity)
    identity = [(0.0, 0.0), (1.0, 1.0)]
    _ = _pad_nodes(identity)

    if "all" in template.channels:
        src_x, src_y = _pad_nodes(template.nodes_per_channel["all"])
        curve_x: list[list[float]] = [src_x[:] for _ in range(3)]
        curve_y: list[list[float]] = [src_y[:] for _ in range(3)]
    else:
        curve_x = []
        curve_y = []
        for ch in ["r", "g", "b"]:
            if ch in template.nodes_per_channel:
                xs, ys = _pad_nodes(template.nodes_per_channel[ch])
                curve_x.append(xs)
                curve_y.append(ys)
            else:
                ix, iy = _pad_nodes(identity)
                curve_x.append(ix)
                curve_y.append(iy)
    return curve_x, curve_y


# ---------------------------------------------------------------------------
# Public API — colorzones
# ---------------------------------------------------------------------------


def apply_curve_template_colorzones(template_name: str, **kwargs: float | int) -> ColorzonesParams:
    """Build a :class:`ColorzonesParams` from a named template."""
    template = get_template(template_name)
    cx, cy = _apply_template_to_channels(template)
    n = len(template.nodes_per_channel.get(template.channels[0], []))
    n_nodes = [n, n, n]
    return ColorzonesParams(
        channel=int(kwargs.get("channel", 0)),
        curve_x=cx,
        curve_y=cy,
        curve_num_nodes=n_nodes,
        curve_type=[MONOTONE_HERMITE] * 3,
        strength=kwargs.get("strength", 0.0),
        mode=int(kwargs.get("mode", ZONES_SMOOTH)),
        splines_version=int(kwargs.get("splines_version", 1)),
    )


def pack_colorzones(params: ColorzonesParams) -> bytes:
    """Serialize :class:`ColorzonesParams` to its raw bytes."""
    params.validate()
    return struct.pack(
        COLORZONES_FMT,
        params.channel,
        *params.curve_x[0],
        *params.curve_x[1],
        *params.curve_x[2],
        *params.curve_y[0],
        *params.curve_y[1],
        *params.curve_y[2],
        *params.curve_num_nodes,
        *params.curve_type,
        params.strength,
        params.mode,
        params.splines_version,
    )


def unpack_colorzones(blob: bytes) -> ColorzonesParams:
    """Inverse of :func:`pack_colorzones`.  Exact round-trip only."""
    if len(blob) != COLORZONES_SIZE:
        raise ValueError(
            f"colorzones blob must be exactly {COLORZONES_SIZE} bytes, got {len(blob)}"
        )
    parts = struct.unpack(COLORZONES_FMT, blob)
    cx0 = list(parts[1:21])
    cx1 = list(parts[21:41])
    cx2 = list(parts[41:61])
    cy0 = list(parts[61:81])
    cy1 = list(parts[81:101])
    cy2 = list(parts[101:121])
    n_nodes = list(parts[121:124])
    types = list(parts[124:127])
    strength = parts[127]
    mode = parts[128]
    splines_version = parts[129]
    return ColorzonesParams(
        channel=parts[0],
        curve_x=[cx0, cx1, cx2],
        curve_y=[cy0, cy1, cy2],
        curve_num_nodes=n_nodes,
        curve_type=types,
        strength=strength,
        mode=mode,
        splines_version=splines_version,
    )


# ---------------------------------------------------------------------------
# Public API — rgbcurve
# ---------------------------------------------------------------------------


def apply_curve_template_rgbcurve(template_name: str, **kwargs: float | int) -> RGBCurveParams:
    template = get_template(template_name)
    cx, cy = _apply_template_to_channels(template)
    curve_num_nodes = kwargs.get("curve_num_nodes", [5, 5, 5])
    if not isinstance(curve_num_nodes, list):
        curve_num_nodes = [5, 5, 5]
    return RGBCurveParams(
        curve_nodes_x=cx,
        curve_nodes_y=cy,
        curve_num_nodes=curve_num_nodes,
        curve_type=[MONOTONE_HERMITE] * 3,
        curve_autoscale=int(kwargs.get("curve_autoscale", 1)),
        compensate_middle_grey=int(kwargs.get("compensate_middle_grey", 0)),
        preserve_colors=int(kwargs.get("preserve_colors", 0)),
    )


def pack_rgbcurve(params: RGBCurveParams) -> bytes:
    params.validate()
    return struct.pack(
        RGBCURVE_FMT,
        *params.curve_nodes_x[0],
        *params.curve_nodes_x[1],
        *params.curve_nodes_x[2],
        *params.curve_nodes_y[0],
        *params.curve_nodes_y[1],
        *params.curve_nodes_y[2],
        *params.curve_num_nodes,
        *params.curve_type,
        params.curve_autoscale,
        params.compensate_middle_grey,
        params.preserve_colors,
    )


def unpack_rgbcurve(blob: bytes) -> RGBCurveParams:
    if len(blob) != RGBCURVE_SIZE:
        raise ValueError(f"rgbcurve blob must be exactly {RGBCURVE_SIZE} bytes, got {len(blob)}")
    parts = struct.unpack(RGBCURVE_FMT, blob)
    return RGBCurveParams(
        curve_nodes_x=[list(parts[0:20]), list(parts[20:40]), list(parts[40:60])],
        curve_nodes_y=[list(parts[60:80]), list(parts[80:100]), list(parts[100:120])],
        curve_num_nodes=list(parts[120:123]),
        curve_type=list(parts[123:126]),
        curve_autoscale=parts[126],
        compensate_middle_grey=parts[127],
        preserve_colors=parts[128],
    )


# ---------------------------------------------------------------------------
# Public API — tonecurve
# ---------------------------------------------------------------------------


def apply_curve_template_tonecurve(template_name: str, **kwargs: float | int) -> TonecurveParams:
    template = get_template(template_name)
    cx, cy = _apply_template_to_channels(template)
    n = len(template.nodes_per_channel.get(template.channels[0], []))
    return TonecurveParams(
        tonecurve_x=cx,
        tonecurve_y=cy,
        tonecurve_nodes=[n, n, n],
        tonecurve_type=[MONOTONE_HERMITE] * 3,
        tonecurve_autoscale_ab=int(kwargs.get("tonecurve_autoscale_ab", 1)),
        tonecurve_preset=int(kwargs.get("tonecurve_preset", 0)),
        tonecurve_unbound_ab=int(kwargs.get("tonecurve_unbound_ab", 1)),
        preserve_colors=int(kwargs.get("preserve_colors", 0)),
    )


def pack_tonecurve(params: TonecurveParams) -> bytes:
    params.validate()
    return struct.pack(
        TONECURVE_FMT,
        *params.tonecurve_x[0],
        *params.tonecurve_x[1],
        *params.tonecurve_x[2],
        *params.tonecurve_y[0],
        *params.tonecurve_y[1],
        *params.tonecurve_y[2],
        *params.tonecurve_nodes,
        *params.tonecurve_type,
        params.tonecurve_autoscale_ab,
        params.tonecurve_preset,
        params.tonecurve_unbound_ab,
        params.preserve_colors,
    )


def unpack_tonecurve(blob: bytes) -> TonecurveParams:
    if len(blob) != TONECURVE_SIZE:
        raise ValueError(f"tonecurve blob must be exactly {TONECURVE_SIZE} bytes, got {len(blob)}")
    parts = struct.unpack(TONECURVE_FMT, blob)
    return TonecurveParams(
        tonecurve_x=[list(parts[0:20]), list(parts[20:40]), list(parts[40:60])],
        tonecurve_y=[list(parts[60:80]), list(parts[80:100]), list(parts[100:120])],
        tonecurve_nodes=list(parts[120:123]),
        tonecurve_type=list(parts[123:126]),
        tonecurve_autoscale_ab=parts[126],
        tonecurve_preset=parts[127],
        tonecurve_unbound_ab=parts[128],
        preserve_colors=parts[129],
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


_CURVE_IOPS = {
    "colorzones": (
        pack_colorzones,
        unpack_colorzones,
        apply_curve_template_colorzones,
        COLORZONES_SIZE,
    ),
    "rgbcurve": (pack_rgbcurve, unpack_rgbcurve, apply_curve_template_rgbcurve, RGBCURVE_SIZE),
    "tonecurve": (pack_tonecurve, unpack_tonecurve, apply_curve_template_tonecurve, TONECURVE_SIZE),
}


def apply_curve_template(op: str, template_name: str, **kwargs: float | int) -> bytes:
    """High-level convenience: apply a named template to a curve-IOP.

    Args:
        op: Curve-based IOP name — ``"colorzones"``, ``"rgbcurve"``
            or ``"tonecurve"``.
        template_name: Curve template identifier (see
            :mod:`dtstylekit.curves.templates`).
        **kwargs: Forwarded scalar overrides (strength, mode, etc.).

    Returns:
        Encoded ``op_params`` blob ready to be embedded in a .dtstyle.
    """
    if op not in _CURVE_IOPS:
        raise ValueError(f"{op!r} is not a curve-based IOP")
    pack, _, apply, _ = _CURVE_IOPS[op]
    return pack(apply(template_name, **kwargs))  # type: ignore[no-any-return, operator]


def curve_iop_size(op: str) -> int:
    """Return the exact blob size for a curve-based IOP."""
    if op not in _CURVE_IOPS:
        raise ValueError(f"{op!r} is not a curve-based IOP")
    return _CURVE_IOPS[op][3]


__all__ = [
    "MAX_CURVE_NODES",
    "MAX_CURVE_CHANNELS",
    "CUBIC_SPLINE",
    "CATMULL_ROM",
    "MONOTONE_HERMITE",
    "ZONES_SMOOTH",
    "ZONES_STRONG",
    "ColorzonesParams",
    "RGBCurveParams",
    "TonecurveParams",
    "COLORZONES_SIZE",
    "RGBCURVE_SIZE",
    "TONECURVE_SIZE",
    "apply_curve_template",
    "apply_curve_template_colorzones",
    "apply_curve_template_rgbcurve",
    "apply_curve_template_tonecurve",
    "pack_colorzones",
    "pack_rgbcurve",
    "pack_tonecurve",
    "unpack_colorzones",
    "unpack_rgbcurve",
    "unpack_tonecurve",
    "curve_iop_size",
]
