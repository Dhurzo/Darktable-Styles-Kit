"""Blendop handling for Darktable styles.

Default blendop templates and patching functions.
See blob_size_calibration.md §3 for verified structure.
"""

import struct

from .xmp_codec import decode_xmp, encode_xmp


def _patch_field(encoded: str, offset: int, value: int | float, fmt: str) -> str:
    """Internal helper: decode, patch field at offset, re-encode."""
    blob = bytearray(decode_xmp(encoded))
    struct.pack_into(fmt, blob, offset, value)
    return encode_xmp(bytes(blob))


# Base 420-byte blendop: blend_cst=4 (RGB_SCENE), blend_mode=24 (NORMAL2),
# opacity=100.0.  Verified against the blendops stored in the official
# darktable styles of this master (data/styles).
_BASE_BLENDOP = "gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"

# Default blendop encoded strings (verified 420 bytes each).
# Color spaces per src/develop/blend.h of this darktable master:
#   2 = DEVELOP_BLEND_CS_LAB, 3 = DEVELOP_BLEND_CS_RGB_DISPLAY,
#   4 = DEVELOP_BLEND_CS_RGB_SCENE
DEFAULT_BLENDOP_SCENE = _BASE_BLENDOP  # blend_cst=4
DEFAULT_BLENDOP_DISPLAY = _patch_field(_BASE_BLENDOP, 4, 3, "<i")  # blend_cst=3
DEFAULT_BLENDOP_LAB = _patch_field(_BASE_BLENDOP, 4, 2, "<i")  # blend_cst=2


def patch_opacity(encoded: str, opacity_pct: float) -> str:
    """Patch opacity field at offset 16 (float32, percentage 0-100).

    Darktable stores opacity as 0-100 percentage, not 0.0-1.0.
    """
    return _patch_field(encoded, 16, opacity_pct, "<f")


def patch_blend_mode(encoded: str, mode: int) -> str:
    """Patch blend_mode field at offset 8 (uint32).

    Common modes:
    - 0: DEVELOP_BLEND_NORMAL (legacy)
    - 24: DEVELOP_BLEND_NORMAL2 (current default)
    """
    return _patch_field(encoded, 8, mode, "<I")


def patch_blend_cst(encoded: str, cst: int) -> str:
    """Patch blend_cst field at offset 4 (int32).

    Color space for blending (per src/develop/blend.h of this master):
    - 2: DEVELOP_BLEND_CS_LAB
    - 3: DEVELOP_BLEND_CS_RGB_DISPLAY (display-referred)
    - 4: DEVELOP_BLEND_CS_RGB_SCENE (scene-referred)
    """
    return _patch_field(encoded, 4, cst, "<i")


def create_blendop(opacity: float = 100.0, mode: int = 24, cst: int = 3) -> str:
    """Create a blendop from the display template with custom values.

    Args:
        opacity: Opacity percentage (0-100)
        mode: Blend mode (default 24 = NORMAL2)
        cst: Color space (default 3 = RGB_DISPLAY)

    Returns:
        Encoded blendop string
    """
    result = DEFAULT_BLENDOP_DISPLAY
    if cst != 3:
        result = patch_blend_cst(result, cst)
    if mode != 24:
        result = patch_blend_mode(result, mode)
    if opacity != 100.0:
        result = patch_opacity(result, opacity)
    return result


def create_blendop_scene(opacity: float = 100.0, mode: int = 24) -> str:
    """Create a blendop from the scene template with custom values.

    Args:
        opacity: Opacity percentage (0-100)
        mode: Blend mode (default 24 = NORMAL2)

    Returns:
        Encoded blendop string with blend_cst=4 (RGB_SCENE)
    """
    result = DEFAULT_BLENDOP_SCENE
    if mode != 24:
        result = patch_blend_mode(result, mode)
    if opacity != 100.0:
        result = patch_opacity(result, opacity)
    return result


def get_opacity(encoded: str) -> float:
    """Extract opacity value from encoded blendop."""
    blob = decode_xmp(encoded)
    return float(struct.unpack_from("<f", blob, 16)[0])


def get_blend_mode(encoded: str) -> int:
    """Extract blend_mode value from encoded blendop."""
    blob = decode_xmp(encoded)
    return int(struct.unpack_from("<I", blob, 8)[0])


def get_blend_cst(encoded: str) -> int:
    """Extract blend_cst value from encoded blendop."""
    blob = decode_xmp(encoded)
    return int(struct.unpack_from("<i", blob, 4)[0])


def verify_blendop_size(encoded: str) -> bool:
    """Verify decoded blendop is 420 bytes (expected default size)."""
    return len(decode_xmp(encoded)) == 420


__all__ = [
    "DEFAULT_BLENDOP_DISPLAY",
    "DEFAULT_BLENDOP_SCENE",
    "DEFAULT_BLENDOP_LAB",
    "patch_opacity",
    "patch_blend_mode",
    "patch_blend_cst",
    "create_blendop",
    "create_blendop_scene",
    "get_opacity",
    "get_blend_mode",
    "get_blend_cst",
    "verify_blendop_size",
]
