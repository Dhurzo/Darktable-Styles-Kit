"""Interface for reference image analysis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ReferenceAnalyzer(ABC):
    """Port for analyzing reference images for style transfer."""

    @abstractmethod
    def analyze_hues(self, reference_paths: list[Path]) -> dict:
        """Analyze reference images for per-zone hue statistics.

        Args:
            reference_paths: List of reference image paths.

        Returns:
            Dictionary with keys:
            - shadows_hue, midtones_hue, highlights_hue: primary hue angles
            - shadows_hue_secondary, etc.: secondary hue for bimodal
            - shadows_hue_mode, etc.: "neutral" | "mono" | "bi" | "global"
            - shadows_hue_confidence, etc.: 0.0-1.0
            - shadows_sat, etc.: mean saturation per zone
            - global_saturation: optional global HSV saturation
        """
        ...

    @abstractmethod
    def compute_global_saturation(self, reference_paths: list[Path]) -> float:
        """Compute global HSV saturation from reference images.

        Args:
            reference_paths: List of reference image paths.

        Returns:
            Mean saturation across references.
        """
        ...
