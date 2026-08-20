"""Interface for preset repository."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.presets.models import Preset


class PresetRepository(ABC):
    """Port for loading and resolving presets."""

    @abstractmethod
    def load_preset(self, path: Path) -> Preset | None:
        """Load a preset from a .dtstyle file.

        Args:
            path: Path to .dtstyle file.

        Returns:
            Preset object or None on failure.
        """
        ...

    @abstractmethod
    def resolve_preset(self, name: str) -> Preset | None:
        """Resolve a preset name to a full Preset object.

        Searches by filename, display_name, or index lookup.

        Args:
            name: Preset name, filename, or display name.

        Returns:
            Preset object or None if not found.
        """
        ...

    @abstractmethod
    def load_selected_presets(self, preset_names: list[str], warnings: list[str]) -> list[Preset]:
        """Load multiple presets by name.

        Args:
            preset_names: List of preset names/filenames.
            warnings: List to accumulate warnings.

        Returns:
            List of loaded Preset objects.
        """
        ...

    @abstractmethod
    def index_presets(self, preset_dir: Path) -> int:
        """Build/rebuild the preset search index.

        Args:
            preset_dir: Directory containing .dtstyle files.

        Returns:
            Number of presets indexed.
        """
        ...
