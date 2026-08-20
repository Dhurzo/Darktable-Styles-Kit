"""Serializer for Darktable style plugins and XML generation.

Converts plugin parameter dictionaries to XML-ready format and builds
complete .dtstyle XML documents.
"""

import xml.etree.ElementTree as ET

from .blendop import DEFAULT_BLENDOP_DISPLAY, DEFAULT_BLENDOP_LAB, DEFAULT_BLENDOP_SCENE
from .iop_registry import get_registry, pack_params
from .xmp_codec import encode_xmp


def encode_plugin(plugin_dict: dict) -> dict:
    """Encode a plugin dictionary for XML output.

    Takes a plugin dict with keys:
        - operation (required): IOP name (e.g., "filmicrgb")
        - enabled (optional, default 1): 0 or 1
        - multi_name (optional, default ""): Instance name for multi-instance
        - multi_priority (optional, default 0): Priority for multi-instance
        - params (required unless ``op_params_override`` is provided):
            Parameter values dict.  May include the synthetic
            ``curve_preset`` field for curve-based IOPs.
        - op_params_override (optional): Already-encoded ``op_params``
            (hex or gz+base64 string).  Bypasses re-packing — useful
            when the *caller* has already run ``pack_params`` (e.g. the
            composer module which handles curve-based IOPs separately).
        - blendop_override (optional): Custom blendop encoded string
        - blendop_version (optional, default 13): Blendop version
        - module (optional, default 0): Module version field

    Returns:
        Dictionary with XML-ready fields including op_params_encoded and blendop_encoded
    """
    operation = plugin_dict["operation"]
    params = plugin_dict.get("params", {})
    enabled = plugin_dict.get("enabled", 1)
    multi_name = plugin_dict.get("multi_name", "")
    multi_priority = plugin_dict.get("multi_priority", 0)
    module = plugin_dict.get("module", 0)
    blendop_version = plugin_dict.get("blendop_version", 13)

    # Get registry to determine blendop_cst
    reg = get_registry(operation)
    blendop_cst = reg.blendop_cst if reg else 4

    # Pack op_params — caller may have already encoded them.
    op_params_override = plugin_dict.get("op_params_override")
    if op_params_override is not None:
        op_params_encoded = op_params_override
    elif reg:
        op_params_bytes = pack_params(operation, params)
        op_params_encoded = encode_xmp(op_params_bytes)
    else:
        # Unknown operation — only acceptable when the caller also
        # passes op_params_override, otherwise we error out.
        raise ValueError(f"Unknown operation: {operation}")

    # Handle blendop
    blendop_override = plugin_dict.get("blendop_override")
    if blendop_override:
        blendop_encoded = blendop_override
    else:
        # Use appropriate default based on blendop_cst (per blend.h of
        # this master: 2 = LAB, 3 = RGB_DISPLAY, 4 = RGB_SCENE).
        if blendop_cst == 4:
            blendop_encoded = DEFAULT_BLENDOP_SCENE
        elif blendop_cst == 2:
            blendop_encoded = DEFAULT_BLENDOP_LAB
        else:
            blendop_encoded = DEFAULT_BLENDOP_DISPLAY

    return {
        "num": plugin_dict.get("num", 0),
        "module": module,
        "operation": operation,
        "op_params_encoded": op_params_encoded,
        "enabled": enabled,
        "blendop_encoded": blendop_encoded,
        "blendop_version": blendop_version,
        "multi_priority": multi_priority,
        "multi_name": multi_name,
        "multi_name_hand_edited": plugin_dict.get("multi_name_hand_edited", 0),
    }


def build_dtstyle_xml(
    name: str, description: str, plugins: list[dict], iop_list: str | None = None
) -> str:
    """Build a complete .dtstyle XML document.

    Args:
        name: Style name (e.g., "My Style" or "_l10n_darktable|_l10n_colors|Sepia")
        description: Style description (can be empty string)
        plugins: List of plugin dicts (will be passed through encode_plugin)
        iop_list: Optional CSV string of "operation,priority" pairs

    Returns:
        Complete XML string with <?xml ...?> declaration

    Per format_analysis.md §2 and §10.
    """
    root = ET.Element("darktable_style", version="1.0")

    # Info section
    info = ET.SubElement(root, "info")
    ET.SubElement(info, "name").text = name
    ET.SubElement(info, "description").text = description
    if iop_list:
        ET.SubElement(info, "iop_list").text = iop_list

    # Style section
    style = ET.SubElement(root, "style")

    for _i, plugin_dict in enumerate(plugins):
        # Encode plugin to get XML-ready fields
        encoded = encode_plugin(plugin_dict)

        plugin = ET.SubElement(style, "plugin")
        ET.SubElement(plugin, "num").text = str(encoded["num"])
        ET.SubElement(plugin, "module").text = str(encoded["module"])
        ET.SubElement(plugin, "operation").text = encoded["operation"]
        ET.SubElement(plugin, "op_params").text = encoded["op_params_encoded"]
        ET.SubElement(plugin, "enabled").text = str(encoded["enabled"])
        ET.SubElement(plugin, "blendop_params").text = encoded["blendop_encoded"]
        ET.SubElement(plugin, "blendop_version").text = str(encoded["blendop_version"])
        ET.SubElement(plugin, "multi_priority").text = str(encoded["multi_priority"])
        ET.SubElement(plugin, "multi_name").text = encoded["multi_name"]
        ET.SubElement(plugin, "multi_name_hand_edited").text = str(
            encoded["multi_name_hand_edited"]
        )

    # Convert to string with XML declaration
    xml_str = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def write_dtstyle_file(
    filepath: str, name: str, description: str, plugins: list[dict], iop_list: str | None = None
) -> None:
    """Write a .dtstyle file to disk.

    Convenience wrapper around build_dtstyle_xml.
    """
    xml = build_dtstyle_xml(name, description, plugins, iop_list)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(xml)


__all__ = [
    "encode_plugin",
    "build_dtstyle_xml",
    "write_dtstyle_file",
]
