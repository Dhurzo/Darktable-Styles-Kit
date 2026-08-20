"""Interface for image encoding."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ImageEncoder(ABC):
    """Port for encoding images as base64 JPEG."""

    @abstractmethod
    def encode(
        self,
        image_path: str | Path,
        max_dim: int = 768,
        quality: int = 88,
    ) -> str | None:
        """Encode image as base64 JPEG, downscaled to max_dim.

        Args:
            image_path: Path to image file.
            max_dim: Maximum dimension (width or height).
            quality: JPEG quality (1-100).

        Returns:
            Base64-encoded JPEG string, or None on failure.
        """
        ...

    @abstractmethod
    def encode_batch(
        self,
        image_paths: list[str | Path],
        max_dim: int = 768,
        quality: int = 88,
    ) -> list[str]:
        """Encode multiple images as base64 JPEG.

        Args:
            image_paths: List of image paths.
            max_dim: Maximum dimension.
            quality: JPEG quality.

        Returns:
            List of base64 strings (skips failed encodings).
        """
        ...
