"""Use case for searching presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.interfaces import PresetSearcher
    from dtstylekit.presets.models import PresetIndexEntry


@dataclass
class SearchPresetsRequest:
    """Input for preset search."""

    query: str
    limit: int = 5
    category: str | None = None


@dataclass
class SearchPresetsResponse:
    """Output from preset search."""

    results: list[PresetIndexEntry]
    total_found: int


class SearchPresetsUseCase:
    """Use case for searching presets by semantic query."""

    def __init__(self, preset_searcher: PresetSearcher):
        self._searcher = preset_searcher

    def execute(self, request: SearchPresetsRequest) -> SearchPresetsResponse:
        """Execute the preset search use case.

        Args:
            request: Search parameters.

        Returns:
            Search results with scores.
        """
        if request.category:
            entries = self._searcher.list_presets(category=request.category)
            # Filter by query if provided
            if request.query:
                search_results = self._searcher.search(request.query, limit=request.limit)
                # Filter entries by search results
                search_ids = {r.preset.id for r in search_results}
                entries = [e for e in entries if e.id in search_ids]
        else:
            search_results = self._searcher.search(request.query, limit=request.limit)
            entries = [r.preset for r in search_results]

        total_found = len(entries)
        return SearchPresetsResponse(
            results=entries[: request.limit],
            total_found=total_found,
        )
