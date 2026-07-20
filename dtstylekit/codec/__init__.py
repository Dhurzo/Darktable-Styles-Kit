"""dtstylekit.codec - XMP codec, blendop handling, and IOP registry."""

from .xmp_codec import (
    encode_xmp,
    decode_xmp,
    verify_roundtrip,
)
from .blendop import (
    DEFAULT_BLENDOP_DISPLAY,
    DEFAULT_BLENDOP_SCENE,
    patch_opacity,
    patch_blend_mode,
    patch_blend_cst,
    create_blendop,
    create_blendop_scene,
    get_opacity,
    get_blend_mode,
    get_blend_cst,
    verify_blendop_size,
)
from .iop_registry import (
    IOPRegistry,
    IOP_REGISTRY,
    get_registry,
    pack_params,
    unpack_params,
    verify_size,
    list_registered,
    list_verified,
    list_unverified,
)
from .serializer import (
    encode_plugin,
    build_dtstyle_xml,
    write_dtstyle_file,
)

__all__ = [
    # xmp_codec
    "encode_xmp",
    "decode_xmp",
    "verify_roundtrip",
    # blendop
    "DEFAULT_BLENDOP_DISPLAY",
    "DEFAULT_BLENDOP_SCENE",
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