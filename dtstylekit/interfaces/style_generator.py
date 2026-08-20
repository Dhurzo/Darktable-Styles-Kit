"""Interface for style specification generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.vlm.models import StyleSpec


class StyleGenerator(ABC):
    """Port for generating style specifications from images."""

    @abstractmethod
    def generate(
        self,
        image_path: str | Path,
        direction: str,
        references: list[str | Path] | None = None,
        refine_iterations: int = 0,
        refine_raw_path: str | Path | None = None,
    ) -> tuple[StyleSpec, str, list[str], ImageAnalysis]:
        """Generate a validated StyleSpec for a given image.

        Args:
            image_path: Path to input image.
            direction: Style direction string.
            references: Optional reference images for target aesthetic.
            refine_iterations: Number of iterative refinement loops.
            refine_raw_path: RAW file for test renders during refinement.

        Returns:
            Tuple of (validated_spec, vlm_report, warnings, image_analysis).
        """
        ...

    @abstractmethod
    def generate_spec_only(
        self,
        image_path: str | Path,
        direction: str,
        references: list[str | Path] | None = None,
    ) -> StyleSpec:
        """Generate a StyleSpec without full assembly (for VLM subcommand).

        Args:
            image_path: Path to input image.
            direction: Style direction string.
            references: Optional reference images.

        Returns:
            Validated StyleSpec.
        """
        ...
