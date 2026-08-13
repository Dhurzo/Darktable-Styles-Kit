"""dtstylekit.codec - XMP codec, blendop handling, and IOP registry."""

from .blendop import (
    DEFAULT_BLENDOP_DISPLAY,
    DEFAULT_BLENDOP_LAB,
    DEFAULT_BLENDOP_SCENE,
    create_blendop,
    create_blendop_scene,
    get_blend_cst,
    get_blend_mode,
    get_opacity,
    patch_blend_cst,
    patch_blend_mode,
    patch_opacity,
    verify_blendop_size,
)
from .iop_registry import (
    IOP_REGISTRY,
    IOPRegistry,
    get_registry,
    list_registered,
    list_unverified,
    list_verified,
    pack_params,
    unpack_params,
    verify_size,
)
from .serializer import (
    build_dtstyle_xml,
    encode_plugin,
    write_dtstyle_file,
)
from .xmp_codec import (
    decode_xmp,
    encode_xmp,
    verify_roundtrip,
)

__all__ = [
    # xmp_codec
    "encode_xmp",
    "decode_xmp",
    "verify_roundtrip",
    # blendop
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
    # iop_registry
    "IOPRegistry",
    "IOP_REGISTRY",
    "get_registry",
    "pack_params",
    "unpack_params",
    "verify_size",
    "list_registered",
    "list_verified",
    "list_unverified",
    # serializer
    "encode_plugin",
    "build_dtstyle_xml",
    "write_dtstyle_file",
]
