"""Use case for indexing presets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.interfaces import PresetRepository


@dataclass
class IndexPresetsRequest:
    """Input for preset indexing."""

    preset_dir: Path
    force: bool = False


@dataclass
class IndexPresetsResponse:
    """Output from preset indexing."""

    indexed_count: int
    message: str


class IndexPresetsUseCase:
    """Use case for building the preset search index."""

    def __init__(self, preset_repository: PresetRepository):
        self._repository = preset_repository

    def execute(self, request: IndexPresetsRequest) -> IndexPresetsResponse:
        """Execute the preset indexing use case.

        Args:
            request: Indexing parameters.

        Returns:
            Result with count of indexed presets.
        """
        if not request.preset_dir.exists():
            raise ValueError(f"Preset directory does not exist: {request.preset_dir}")

        count = self._repository.index_presets(request.preset_dir)

        return IndexPresetsResponse(
            indexed_count=count,
            message=f"Successfully indexed {count} presets from {request.preset_dir}",
        )
