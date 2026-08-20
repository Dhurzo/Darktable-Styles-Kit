"""Preset search functionality: keyword (FTS5), semantic (embeddings), and hybrid search."""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embedder import EMBEDDING_DIM, PresetEmbedder
from .indexer import PresetIndexEntry, PresetIndexer


@dataclass
class SearchResult:
    """A search result with preset entry and relevance score."""

    preset: PresetIndexEntry
    score: float
    search_type: str  # "keyword", "semantic", or "hybrid"


class PresetSearcher:
    """
    Unified search interface for Darktable presets.

    Supports three search modes:
    - keyword_search: FTS5 full-text search on name, description, IOPs
    - semantic_search: Vector similarity search using sentence embeddings
    - hybrid_search: Weighted combination of keyword and semantic scores
    """

    def __init__(
        self,
        db_path: Path,
        embeddings_path: Path | None = None,
        embedder_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        exclude_categories: tuple[str, ...] | None = ("camera",),
    ):
        """
        Args:
            db_path: Path to the SQLite index database.
            embeddings_path: Path to the .npy embeddings file (optional
                when only keyword search is used).
            embedder_model: Sentence transformer model identifier.
            exclude_categories: Preset categories to exclude from all
                searches (default: excludes ``"camera"`` baseline
                profiles so the VLM only sees artistic presets).
                Pass ``()`` or ``None`` to disable filtering.
        """
        self.db_path = Path(db_path)
        self.embeddings_path = Path(embeddings_path) if embeddings_path is not None else None
        self.indexer = PresetIndexer(self.db_path)
        self._embeddings: np.ndarray | None = None
        self._embedder: PresetEmbedder | None = None
        self._embedder_model = embedder_model
        self.exclude_categories: tuple[str, ...] = (
            tuple(exclude_categories) if exclude_categories else ()
        )

    def _load_embeddings(self) -> np.ndarray:
        """Load embeddings from file (cached)."""
        if self._embeddings is not None:
            return self._embeddings

        if self.embeddings_path is None or not self.embeddings_path.exists():
            raise ValueError(
                f"Embeddings file not found: {self.embeddings_path}. "
                "Run 'dtstylekit preset index' to generate embeddings."
            )

        self._embeddings = np.load(self.embeddings_path)

        # Validate shape
        n_presets = self.indexer.get_preset_count()
        if self._embeddings.shape[0] != n_presets:
            raise ValueError(
                f"Embedding count mismatch: {self._embeddings.shape[0]} embeddings "
                f"but {n_presets} presets in database. Re-index required."
            )
        if self._embeddings.shape[1] != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, "
                f"got {self._embeddings.shape[1]}"
            )

        return self._embeddings

    def _get_embedder(self) -> PresetEmbedder:
        """Get or create embedder instance."""
        if self._embedder is None:
            self._embedder = PresetEmbedder(self._embedder_model)
        return self._embedder

    def _should_keep(self, entry: PresetIndexEntry) -> bool:
        """Apply the category filter to a single result entry."""
        if not self.exclude_categories:
            return True
        return entry.category not in self.exclude_categories

    def _filter_results(self, results: list["SearchResult"]) -> list["SearchResult"]:
        """Drop results in excluded categories (e.g. camera baselines)."""
        if not self.exclude_categories:
            return results
        return [r for r in results if self._should_keep(r.preset)]

    def keyword_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search presets using FTS5 keyword search.

        Args:
            query: Search query (supports FTS5 syntax: "warm portrait", "sepia", "color*")
            limit: Maximum number of results.

        Returns:
            List of SearchResult objects sorted by relevance (BM25 score).
            Higher score = better match (we normalize BM25 distance to a similarity-like 0..1).
        """
        self.indexer.connect()  # Ensure connection
        # FTS5 has no tolerance for query syntax it can't parse: hyphens
        # ("low-key") are read as `column:term` minus-operators and raise
        # "no such column", commas and other punctuation raise "syntax
        # error".  Strip everything except word characters so descriptive
        # direction strings (which can contain commas, quotes, colons, …)
        # never crash the keyword search — the semantic branch still gets
        # the raw query.
        safe_query = re.sub(r"[^a-zA-Z0-9\s]", " ", query).strip()
        if not safe_query:
            return []
        # Over-fetch so we still hit `limit` after filtering camera profiles.
        ranked = self.indexer.search_presets_fts_ranked(safe_query, limit=max(limit * 3, limit))

        results = []
        for entry, rank in ranked:
            if not self._should_keep(entry):
                continue
            # BM25 in SQLite FTS5 is a distance (lower = better).
            # Convert to a similarity-like score in (0, 1] via 1 / (1 + rank).
            # rank can be negative in SQLite; clamp with max(0, ...) to stay safe.
            score = 1.0 / (1.0 + max(0.0, rank))
            results.append(SearchResult(preset=entry, score=score, search_type="keyword"))
            if len(results) >= limit:
                break

        return results

    def semantic_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search presets using semantic vector similarity.

        Args:
            query: Natural language query (e.g., "warm cinematic portrait")
            limit: Maximum number of results.

        Returns:
            List of SearchResult objects sorted by cosine similarity (highest first).
        """
        embeddings = self._load_embeddings()
        embedder = self._get_embedder()

        # Encode query
        query_embedding = embedder.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)

        # Compute cosine similarities (embeddings are L2 normalized)
        similarities = embeddings @ query_embedding.T  # Shape: (n_presets, 1)
        similarities = similarities.flatten()

        # Get top-k indices (in embedding array order, which matches DB row insertion order).
        # We oversample by a factor to compensate for category-filtering: if the
        # top-K are all excluded (e.g. 510/534 presets are camera profiles), the
        # filter would otherwise yield an empty result for small limits.
        k = min(max(limit * 5, limit), len(similarities))
        if k >= len(similarities):
            top_indices = np.argsort(similarities)[::-1]
        else:
            top_indices = np.argpartition(similarities, -k)[-k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        # The embeddings array's i-th row corresponds to the i-th row inserted
        # into the DB by `indexer.index_presets()`. Build a dense mapping
        # embedding-row -> preset-id by reading IDs in insertion order.
        ids_in_order = self.indexer.get_preset_ids_in_insertion_order()
        id_for_row = dict(enumerate(ids_in_order))

        # Build results
        results = []
        seen = 0
        for idx in top_indices:
            if seen >= limit:
                break
            entry_id = id_for_row.get(int(idx))
            if entry_id is None:
                continue
            entry = self.indexer.get_preset_by_id(entry_id)
            if entry is None or not self._should_keep(entry):
                continue
            results.append(
                SearchResult(preset=entry, score=float(similarities[idx]), search_type="semantic")
            )
            seen += 1

        return results

    def hybrid_search(self, query: str, limit: int = 10, alpha: float = 0.5) -> list[SearchResult]:
        """
        Hybrid search combining keyword and semantic search.

        Args:
            query: Search query.
            limit: Maximum number of results.
            alpha: Weight for semantic score (0=keyword only, 1=semantic only).
                   Default 0.5 gives equal weight.

        Returns:
            List of SearchResult objects sorted by combined score.
        """
        # Get more candidates from each to allow for better fusion
        k = limit * 3

        keyword_results = self.keyword_search(query, k)
        semantic_results = self.semantic_search(query, k)

        # Create score maps by preset ID
        keyword_scores = {r.preset.id: r.score for r in keyword_results}
        semantic_scores = {r.preset.id: r.score for r in semantic_results}

        # Combine scores
        all_ids = set(keyword_scores.keys()) | set(semantic_scores.keys())

        combined = []
        for pid in all_ids:
            if pid is None:
                continue
            entry = self.indexer.get_preset_by_id(pid)
            if entry is None or not self._should_keep(entry):
                continue

            kw_score = keyword_scores.get(pid, 0.0)
            sem_score = semantic_scores.get(pid, 0.0)

            # Normalize scores to 0-1 range (BM25 is inverted, semantic is cosine)
            # For BM25, we invert and normalize: lower rank -> higher score
            # For simplicity, we use the position-based score
            combined_score = alpha * sem_score + (1 - alpha) * kw_score

            combined.append(SearchResult(preset=entry, score=combined_score, search_type="hybrid"))

        # Sort by combined score (unfiltered) so we know the global ranking.
        combined.sort(key=lambda r: r.score, reverse=True)

        # Apply the category filter, but never return fewer than ``limit``
        # results: if filtering excludes everything (e.g. a generic query
        # whose nearest neighbours are all camera baseline profiles), top
        # up with the best unfiltered candidates so the VLM always has
        # something to choose from.
        filtered = [r for r in combined if self._should_keep(r.preset)]
        if len(filtered) < limit:
            seen_ids = {r.preset.id for r in filtered}
            for r in combined:
                if r.preset.id not in seen_ids:
                    filtered.append(r)
                    seen_ids.add(r.preset.id)
                    if len(filtered) >= limit:
                        break
        return filtered[:limit]

    def get_preset_by_id(self, preset_id: int) -> PresetIndexEntry | None:
        """Get a preset entry by its database ID."""
        self.indexer.connect()
        return self.indexer.get_preset_by_id(preset_id)

    def list_presets(self, category: str | None = None) -> list[PresetIndexEntry]:
        """List presets, optionally filtered by category."""
        self.indexer.connect()
        return self.indexer.list_presets(category)

    def close(self) -> None:
        """Close database connections."""
        self.indexer.close()
