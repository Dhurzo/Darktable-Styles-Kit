"""Registry dataclass for darktable IOP binary blobs."""

from dataclasses import dataclass

_BLEND_MODES = {1, 2, 3, 4}


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

    def __post_init__(self) -> None:
        """Validate the invariants expected by codec/composer code paths."""
        if not self.operation:
            raise ValueError("IOPRegistry.operation must be a non-empty string")
        if self.version < 0:
            raise ValueError(f"IOPRegistry.version must be non-negative, got {self.version}")
        if not self.fields:
            raise ValueError(f"IOPRegistry.fields must be non-empty for {self.operation!r}")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError(f"IOPRegistry.fields must be unique for {self.operation!r}")

        field_names = set(self.fields)
        if not set(self.defaults) <= field_names:
            raise ValueError(
                f"IOPRegistry.defaults for {self.operation!r} contains unknown fields: "
                f"{sorted(set(self.defaults) - field_names)!r}"
            )
        if not set(self.ranges) <= field_names:
            raise ValueError(
                f"IOPRegistry.ranges for {self.operation!r} contains unknown fields: "
                f"{sorted(set(self.ranges) - field_names)!r}"
            )
        for name, bounds in self.ranges.items():
            if len(bounds) != 2:
                raise ValueError(
                    f"IOPRegistry.ranges[{name!r}] for {self.operation!r} must have two bounds"
                )

        if self.size_bytes is not None and self.size_bytes <= 0:
            raise ValueError(
                f"IOPRegistry.size_bytes for {self.operation!r} must be positive or None"
            )
        for legacy_size in self.legacy_size_bytes:
            if legacy_size <= 0:
                raise ValueError(
                    f"IOPRegistry.legacy_size_bytes for {self.operation!r} must be positive"
                )
        if self.legacy_pack_format is not None and not self.legacy_fields:
            raise ValueError(
                f"IOPRegistry.legacy_pack_format for {self.operation!r} requires legacy_fields"
            )
        if self.blendop_cst not in _BLEND_MODES:
            raise ValueError(
                f"IOPRegistry.blendop_cst for {self.operation!r} must be 2, 3, or 4, got {self.blendop_cst}"
            )
        if self.is_curve_iop and not self.curve_pack_size_override:
            raise ValueError(
                f"IOPRegistry.curve_pack_size_override required for curve IOP {self.operation!r}"
            )
