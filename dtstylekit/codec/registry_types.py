"""Registry dataclass for darktable IOP binary blobs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IOPRegistry:
    """Registry entry for a single IOP module."""

    operation: str
    version: int
    pack_format: str
    fields: tuple[str, ...]
    defaults: dict[str, float | int | str]
    ranges: dict[str, tuple[float | int | str, float | int | str]]
    size_bytes: int | None  # None = not verified against real .dtstyle
    blendop_cst: int  # 2 = LAB, 3 = RGB_DISPLAY, 4 = RGB_SCENE (per blend.h of this master)
    legacy_size_bytes: tuple[int, ...] = ()  # older versions still shipped in official styles
    legacy_pack_format: str | None = None  # struct format for legacy blobs
    legacy_fields: tuple[str, ...] = ()  # field names for legacy blobs
    # Sentinel for curve-based IOPs (colorzones/rgbcurve/tonecurve):
    # when True, ``pack_params`` redirects to the curve-template system
    # rather than the standard struct.pack path.  ``curve_pack_size_override``
    # carries the exact byte count for the curve IOP when set.
    is_curve_iop: bool = False
    curve_pack_size_override: int | None = None
