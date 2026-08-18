"""Interface for style validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.vlm.models import StyleSpec


class StyleValidator(ABC):
    """Port for validating and sanitizing style specifications."""

    @abstractmethod
    def validate(
        self,
        spec: StyleSpec,
        registry: dict,
        reference_analysis: dict | None = None,
        target_analysis: ImageAnalysis | None = None,
    ) -> tuple[StyleSpec, list[str]]:
        """Validate a style specification against registry and reference analysis.

        Args:
            spec: StyleSpec to validate.
            registry: IOP registry for parameter validation.
            reference_analysis: Optional reference hue analysis.
            target_analysis: Optional target image analysis.

        Returns:
            Tuple of (validated_spec, warnings).
        """
        ...

    @abstractmethod
    def validate_xml_structure(self, dtstyle_path: str | Path) -> list[str]:
        """Validate .dtstyle XML structure.

        Args:
            dtstyle_path: Path to .dtstyle file.

        Returns:
            List of validation errors (empty = valid).
        """
        ...

    @abstractmethod
    def validate_blobs(self, dtstyle_path: str | Path) -> list[str]:
        """Validate plugin blob sizes.

        Args:
            dtstyle_path: Path to .dtstyle file.

        Returns:
            List of validation errors (empty = valid).
        """
        ...
