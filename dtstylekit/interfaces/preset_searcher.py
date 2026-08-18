"""Interface for preset searching."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.presets.models import PresetIndexEntry
    from dtstylekit.presets.search import SearchResult as ConcreteSearchResult

    # Use the concrete SearchResult from the implementation.
    # Only needed for static analysis: all annotations are strings
    # (PEP 563 via ``from __future__ import annotations``), so importing
    # the concrete type at runtime would drag in heavyweight dependencies
    # (sentence-transformers, numpy) and create a runtime NameError.
    SearchResult = ConcreteSearchResult


class PresetSearcher(ABC):
    """Port for searching and retrieving presets."""

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search presets by semantic query (hybrid search).

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of search results with scores.
        """
        ...

    @abstractmethod
    def keyword_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search presets using FTS5 keyword search.

        Args:
            query: Search query (supports FTS5 syntax).
            limit: Maximum number of results.

        Returns:
            List of SearchResult objects sorted by relevance (BM25 score).
        """
        ...

    @abstractmethod
    def semantic_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search presets using semantic vector similarity.

        Args:
            query: Natural language query (e.g., "warm cinematic portrait").
            limit: Maximum number of results.

        Returns:
            List of SearchResult objects sorted by cosine similarity (highest first).
        """
        ...

    @abstractmethod
    def hybrid_search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search presets using hybrid keyword + semantic search.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of SearchResult objects with combined scores.
        """
        ...

    @abstractmethod
    def get_preset_by_id(self, preset_id: int) -> PresetIndexEntry | None:
        """Get a full preset by its ID.

        Args:
            preset_id: Preset ID.

        Returns:
            PresetIndexEntry or None if not found.
        """
        ...

    @abstractmethod
    def list_presets(self, category: str | None = None) -> list[PresetIndexEntry]:
        """List all presets, optionally filtered by category.

        Args:
            category: Optional category filter.

        Returns:
            List of preset entries.
        """
        ...
