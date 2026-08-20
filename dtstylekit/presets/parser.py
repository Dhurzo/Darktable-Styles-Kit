"""XML parser for Darktable .dtstyle preset files."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import PluginRef, Preset, compute_xml_hash

logger = logging.getLogger(__name__)


def parse_preset(file_path: Path) -> Preset | None:
    """
    Parse a .dtstyle file into a Preset dataclass.

    Args:
        file_path: Path to the .dtstyle file.

    Returns:
        Preset object if parsing succeeds, None if file is malformed.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read %s: %s", file_path, e)
        return None

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.warning("Failed to parse XML in %s: %s", file_path, e)
        return None

    # Validate root element
    if root.tag != "darktable_style":
        logger.warning("%s is not a darktable_style document", file_path)
        return None

    # Parse <info> section
    info = root.find("info")
    if info is None:
        logger.warning("%s missing <info> section", file_path)
        return None

    name = info.findtext("name", "")
    description = info.findtext("description", "")
    iop_list = info.findtext("iop_list", "")

    # Parse <style> section - plugins
    style = root.find("style")
    plugins: list[PluginRef] = []

    if style is not None:
        for plugin_elem in style.findall("plugin"):
            plugin = _parse_plugin(plugin_elem)
            if plugin is not None:
                plugins.append(plugin)

    xml_hash = compute_xml_hash(content)

    return Preset(
        name=name,
        description=description,
        iop_list=iop_list,
        plugins=plugins,
        file_path=file_path,
        xml_hash=xml_hash,
    )


def _parse_plugin(plugin_elem: ET.Element) -> PluginRef | None:
    """Parse a single <plugin> element into PluginRef."""
    try:
        return PluginRef(
            num=int(plugin_elem.findtext("num", "0")),
            module=int(plugin_elem.findtext("module", "0")),
            operation=plugin_elem.findtext("operation", ""),
            op_params=plugin_elem.findtext("op_params", ""),
            enabled=int(plugin_elem.findtext("enabled", "0")),
            blendop_params=plugin_elem.findtext("blendop_params", ""),
            blendop_version=int(plugin_elem.findtext("blendop_version", "0")),
            multi_priority=int(plugin_elem.findtext("multi_priority", "0")),
            multi_name=plugin_elem.findtext("multi_name", ""),
            multi_name_hand_edited=int(plugin_elem.findtext("multi_name_hand_edited", "0")),
        )
    except (ValueError, TypeError) as e:
        logger.warning("Failed to parse plugin element: %s", e)
        return None


def parse_all_presets(preset_dir: Path) -> list[Preset]:
    """
    Parse all .dtstyle files in a directory.

    Args:
        preset_dir: Directory containing .dtstyle files.

    Returns:
        List of successfully parsed Preset objects.
    """
    presets: list[Preset] = []
    dtstyle_files = list(preset_dir.glob("*.dtstyle"))

    for file_path in dtstyle_files:
        preset = parse_preset(file_path)
        if preset is not None:
            presets.append(preset)
        else:
            logger.warning("Skipping malformed preset: %s", file_path.name)

    return presets
