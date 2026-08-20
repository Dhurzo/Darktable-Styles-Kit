"""Data models for Darktable preset library."""

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PluginRef:
    """Reference to a plugin (IOP module) within a preset."""

    operation: str
    enabled: int
    multi_name: str
    multi_priority: int
    num: int
    module: int
    op_params: str
    blendop_params: str
    blendop_version: int
    multi_name_hand_edited: int


@dataclass
class Preset:
    """Parsed Darktable .dtstyle preset."""

    name: str
    description: str
    iop_list: str
    plugins: list[PluginRef]
    file_path: Path
    xml_hash: str

    @property
    def plugin_count(self) -> int:
        return len(self.plugins)

    @property
    def operations(self) -> list[str]:
        """List of unique IOP operations used in this preset."""
        return list({p.operation for p in self.plugins if p.enabled == 1})

    @property
    def enabled_operations(self) -> list[str]:
        """List of enabled IOP operations in pipeline order."""
        return [p.operation for p in self.plugins if p.enabled == 1]


@dataclass
class PresetIndexEntry:
    """Row in the presets SQLite table."""

    id: int | None
    name: str
    description: str
    iop_list: str
    plugin_count: int
    xml_hash: str
    display_name: str = ""  # Human-readable label ("sepia", "faded"...)
    category: str = ""  # "camera" | "examples" | "other"
    search_text: str = ""  # Clean text used for FTS + embeddings
    file_path: str = ""  # Absolute path to the .dtstyle on disk


def _strip_l10n(segment: str) -> str:
    """Remove a single leading ``_l10n_`` marker from one pipe-segment."""
    return segment[len("_l10n_") :] if segment.startswith("_l10n_") else segment


def derive_display_name(i18n_name: str) -> str:
    """Derive a human-readable label from an i18n dotted name.

    Darktable stores names like ``_l10n_darktable|_l10n_examples|_l10n_colors|_l10n_sepia``.
    The last pipe-segment (with its ``_l10n_`` prefix stripped) is the
    actual style label — e.g. "sepia", "faded", "day for night".

    For camera profiles the final segment is already clean, e.g.
    ``_l10n_darktable|_l10n_camera styles|Canon|EOS...|EOS 5D Mark II``
    → "EOS 5D Mark II".
    """
    if not i18n_name:
        return ""
    last = i18n_name.rsplit("|", 1)[-1]
    return _strip_l10n(last).strip()


def derive_category(i18n_name: str) -> str:
    """Categorize a preset by its i18n name.

    Returns ``"camera"`` for camera baseline profiles, ``"examples"`` for
    artistic example presets, or ``"other"`` for anything else.
    """
    if not i18n_name:
        return "other"
    if "_l10n_camera styles" in i18n_name:
        return "camera"
    if "_l10n_examples" in i18n_name:
        return "examples"
    return "other"


def clean_description(description: str) -> str:
    """Strip a leading ``_l10n_`` marker from a preset description."""
    if not description:
        return ""
    return _strip_l10n(description).strip()


@dataclass
class PresetPluginEntry:
    """Row in the preset_plugins SQLite table."""

    preset_id: int
    operation: str
    enabled: int
    multi_name: str
    multi_priority: int
    num: int
    module: int
    op_params: str
    blendop_params: str
    blendop_version: int
    multi_name_hand_edited: int


def compute_xml_hash(content: str) -> str:
    """Compute SHA256 hash of XML content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
