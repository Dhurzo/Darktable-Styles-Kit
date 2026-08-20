"""Round-trip test suite: verify generated .dtstyle files are valid Darktable styles.

This module provides comprehensive validation that goes beyond simple
darktable-cli import. It checks:
    1. darktable-cli imports the file successfully
    2. XML structure is valid
    3. Every plugin has a valid operation name (known in IOP_REGISTRY)
    4. Every plugin has the correct blob size for its operation
    5. blendop_params decodes to the expected 420 bytes
    6. iop_list is consistent with the plugins in <style>

Based on format_analysis.md §2 and §10, and blob_size_calibration.md §1.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from dtstylekit.codec.iop_registry import IOP_REGISTRY, verify_size
from dtstylekit.codec.xmp_codec import decode_xmp

logger = logging.getLogger(__name__)


class DtstyleValidationError(Exception):
    """Raised when a .dtstyle file fails validation."""

    def __init__(self, msg: str, *, errors: list[str] | None = None) -> None:
        self.errors = errors or []
        super().__init__(msg)


def find_darktable_cli() -> str | None:
    """Locate darktable-cli executable."""
    return shutil.which("darktable-cli")


def validate_xml_structure(dtstyle_path: Path) -> list[str]:
    """Parse .dtstyle XML and return a list of errors.

    Checks:
        - Root element is <darktable_style version="1.0">
        - <info> section exists with <name>
        - <style> section exists with at least one <plugin>
        - Each <plugin> has required child elements
    """
    errors: list[str] = []
    try:
        tree = ET.parse(dtstyle_path)
        root = tree.getroot()
    except ET.ParseError as e:
        return [f"XML parse error: {e}"]

    if root.tag != "darktable_style":
        errors.append(f"Root element is <{root.tag}>, expected <darktable_style>")
    elif root.get("version") != "1.0":
        errors.append(f"Version mismatch: {root.get('version')} != 1.0")

    info = root.find("info")
    if info is None:
        errors.append("Missing <info> section")
    else:
        name_elem = info.find("name")
        if name_elem is None or not name_elem.text:
            errors.append("<info> missing <name>")

    style = root.find("style")
    if style is None:
        errors.append("Missing <style> section")
    else:
        plugins = style.findall("plugin")
        if not plugins:
            errors.append("<style> has no <plugin> elements")
        for p in plugins:
            for required in ("operation", "op_params", "enabled"):
                if p.find(required) is None:
                    errors.append(f"Plugin missing <{required}>")

    return errors


def validate_plugin_blobs(dtstyle_path: Path) -> list[str]:
    """Validate that every plugin's op_params matches the expected blob size.

    Returns a list of error strings (empty list = all OK).
    """
    errors: list[str] = []
    tree = ET.parse(dtstyle_path)
    root = tree.getroot()
    style = root.find("style")
    if style is None:
        return errors  # already caught by validate_xml_structure

    for plugin in style.findall("plugin"):
        operation = plugin.findtext("operation", "").strip()
        op_params_enc = plugin.findtext("op_params", "").strip()
        blendop_enc = plugin.findtext("blendop_params", "").strip()

        if not operation:
            errors.append("Plugin missing <operation>")
            continue

        # Unknown operation is OK if it comes from a real preset --
        # we only warn about it.
        if operation not in IOP_REGISTRY:
            errors.append(f"Unknown operation '{operation}' (not in IOP_REGISTRY)")
            continue

        # op_params blob size check
        if op_params_enc:
            try:
                blob = decode_xmp(op_params_enc)
            except Exception as exc:
                errors.append(f"{operation}: cannot decode op_params: {exc}")
                continue

            reg = IOP_REGISTRY.get(operation)
            if reg and reg.size_bytes is not None:
                if not verify_size(operation, blob):
                    errors.append(
                        f"{operation}: blob size {len(blob)} != expected {reg.size_bytes}"
                    )
        else:
            # Some presets may have empty op_params (should be rare)
            pass

        # blendop blob size check (should be 420 bytes for standard blendops)
        if blendop_enc:
            try:
                blendop_blob = decode_xmp(blendop_enc)
            except Exception as exc:
                errors.append(f"{operation}: cannot decode blendop_params: {exc}")
                continue
            if len(blendop_blob) != 420:
                errors.append(f"{operation}: blendop blob size {len(blendop_blob)} != 420")

    return errors


def validate_iop_list_consistency(dtstyle_path: Path) -> list[str]:
    """Ensure <iop_list> (if present) contains all plugins in <style>."""
    errors: list[str] = []
    tree = ET.parse(dtstyle_path)
    root = tree.getroot()
    info = root.find("info")
    if info is None:
        return errors

    iop_list_text = info.findtext("iop_list", "")
    if not iop_list_text:
        return errors

    # Parse iop_list: "operation,priority,operation,priority,..."
    try:
        parts = iop_list_text.split(",")
        iop_ops = {parts[i] for i in range(0, len(parts), 2)}
    except Exception as exc:
        errors.append(f"Cannot parse <iop_list>: {exc}")
        return errors

    style = root.find("style")
    if style is None:
        return errors

    style_ops = set()
    for plugin in style.findall("plugin"):
        op = plugin.findtext("operation", "").strip()
        if op:
            style_ops.add(op)

    missing = style_ops - iop_ops
    if missing:
        errors.append(f"Operations in <style> but not in <iop_list>: {missing}")

    return errors


def test_roundtrip(dtstyle_path: Path, darktable_cli: str | None = None) -> bool:
    """Full round-trip validation of a generated .dtstyle file.

    Steps:
        1. Structural and blob-level validation (no darktable required)
        2. darktable-cli --import-style (if available)

    Args:
        dtstyle_path: Path to generated .dtstyle.
        darktable_cli: Override path or None to auto-detect.

    Returns:
        True if all validation passed, False otherwise.
    """
    logger.info("Starting round-trip validation for %s", dtstyle_path)

    all_errors: list[str] = []

    # --- Structural validation ---
    xml_errors = validate_xml_structure(dtstyle_path)
    all_errors.extend(xml_errors)

    # --- Blob validation ---
    blob_errors = validate_plugin_blobs(dtstyle_path)
    all_errors.extend(blob_errors)

    # --- iop_list consistency ---
    iop_errors = validate_iop_list_consistency(dtstyle_path)
    all_errors.extend(iop_errors)

    if all_errors:
        for err in all_errors:
            logger.error("VALIDATION: %s", err)
        logger.warning("Round-trip FAILED (validation errors)")
        return False

    # --- darktable-cli import ---
    cli = darktable_cli or find_darktable_cli()
    if cli is None:
        logger.warning("darktable-cli not found; skipping import test")
        return True  # validation OK, just no CLI

    try:
        result = subprocess.run(
            [cli, "--import-style", str(dtstyle_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(
                "darktable-cli failed (rc=%d): stdout=%s stderr=%s",
                result.returncode,
                result.stdout[:500],
                result.stderr[:500],
            )
            return False
        logger.info("Round-trip OK for %s", dtstyle_path)
        return True
    except subprocess.TimeoutExpired:
        logger.error("darktable-cli timeout for %s", dtstyle_path)
        return False
    except Exception as exc:
        logger.error("darktable-cli error: %s", exc)
        return False


def batch_roundtrip(style_dir: Path, darktable_cli: str | None = None) -> dict[str, bool]:
    """Validate all .dtstyle files in a directory.

    Returns a dict mapping filename -> success.
    """
    results: dict[str, bool] = {}
    for path in style_dir.glob("*.dtstyle"):
        results[path.name] = test_roundtrip(path, darktable_cli)
    return results
