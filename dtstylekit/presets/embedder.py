"""Embedding generator for Darktable preset semantic search."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class PresetEmbedder:
    """Generates and manages semantic embeddings for presets."""

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Path | None = None):
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers is required for embeddings. "
                "Install with: pip install sentence-transformers"
            )
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load the sentence transformer model."""
        if self._model is None:
            self._model = SentenceTransformer(
                self.model_name, cache_folder=str(self.cache_dir) if self.cache_dir else None
            )
        return self._model

    def _build_preset_text(self, preset: object) -> str:
        """
        Build the text representation for embedding.

        Prefers the cleaned ``search_text`` field populated by the
        indexer (display name + cleaned description + enabled ops) when
        available.  Falls back to constructing it from the raw preset for
        backwards compatibility — using the human-readable ``display_name``
        rather than the i18n keychain so semantic search actually finds
        "sepia", "faded", "day for night" etc.
        """
        # New path: PresetIndexEntry exposes a populated search_text.
        search_text = getattr(preset, "search_text", None)
        if search_text:
            return search_text  # type: ignore[no-any-return]

        # Fallback path: build from the parsed Preset using cleaned labels.
        from .models import clean_description, derive_category, derive_display_name

        parts = []
        display_name = derive_display_name(getattr(preset, "name", ""))
        if display_name:
            parts.append(display_name)

        cleaned_desc = clean_description(getattr(preset, "description", ""))
        if cleaned_desc:
            parts.append(cleaned_desc)

        # Add enabled operations as semantic context (skip camera profiles'
        # generic baseline ops so artistic presets cluster apart from them).
        category = derive_category(getattr(preset, "name", ""))
        if category != "camera":
            enabled_ops = [
                p.operation for p in getattr(preset, "plugins", []) if getattr(p, "enabled", 0) == 1
            ]
            if enabled_ops:
                parts.append(" ".join(enabled_ops))

        return " ".join(parts)

    def generate_embeddings(self, presets: Sequence[object]) -> np.ndarray:
        """
        Generate embeddings for a list of presets.

        Args:
            presets: List of Preset objects.

        Returns:
            numpy array of shape (n_presets, embedding_dim) with float32 embeddings.
        """
        texts = [self._build_preset_text(p) for p in presets]

        # Generate embeddings in batches for efficiency
        embeddings = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,  # L2 normalize for cosine similarity
        )

        return embeddings.astype(np.float32)  # type: ignore[no-any-return]

    def save_embeddings(self, embeddings: np.ndarray, output_path: Path) -> None:
        """
        Save embeddings to .npy file.

        Args:
            embeddings: Embeddings array of shape (n, 384).
            output_path: Path to save the .npy file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_path, embeddings)

    def load_embeddings(self, input_path: Path) -> np.ndarray:
        """
        Load embeddings from .npy file.

        Args:
            input_path: Path to the .npy file.

        Returns:
            Embeddings array.
        """
        return np.load(input_path)  # type: ignore[no-any-return]

    def generate_and_save(self, presets: Sequence[object], output_path: Path) -> np.ndarray:
        """
        Generate embeddings for presets and save to file.

        Args:
            presets: List of Preset objects.
            output_path: Path to save the .npy file.

        Returns:
            Generated embeddings array.
        """
        embeddings = self.generate_embeddings(presets)
        self.save_embeddings(embeddings, output_path)
        return embeddings


def build_embeddings(
    preset_dir: Path, output_path: Path, model_name: str = DEFAULT_MODEL
) -> np.ndarray:
    """
    Convenience function to build embeddings from a preset directory.

    Args:
        preset_dir: Directory containing .dtstyle files.
        output_path: Path to save the .npy embeddings file.
        model_name: Sentence transformer model to use.

    Returns:
        Generated embeddings array.
    """
    from .parser import parse_all_presets

    presets = parse_all_presets(preset_dir)
    embedder = PresetEmbedder(model_name)
    return embedder.generate_and_save(presets, output_path)
