"""Interface for image analysis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dtstylekit.analyzer.models import ImageAnalysis


class ImageAnalyzer(ABC):
    """Port for analyzing images and extracting metadata."""

    @abstractmethod
    def analyze(self, image_path: str | Path) -> ImageAnalysis:
        """Analyze an image and return structured metadata.

        Args:
            image_path: Path to the image file.

        Returns:
            ImageAnalysis with histogram, luminance, EXIF, noise, scene tags.
        """
        ...

    @abstractmethod
    def analyze_reference_hues(self, reference_paths: list[Path]) -> dict:
        """Analyze reference images for per-zone hue statistics.

        Args:
            reference_paths: List of paths to reference images.

        Returns:
            Dictionary with per-zone hue analysis (shadows, midtones, highlights).
        """
        ...
