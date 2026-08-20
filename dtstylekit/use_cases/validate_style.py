"""Use case for validating styles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.interfaces import StyleValidator
    from dtstylekit.vlm.models import StyleSpec


@dataclass
class ValidateStyleRequest:
    """Input for style validation."""

    style_spec: StyleSpec
    dtstyle_path: Path | None = None
    reference_analysis: dict | None = None
    target_analysis: ImageAnalysis | None = None


@dataclass
class ValidateStyleResponse:
    """Output from style validation."""

    is_valid: bool
    validated_spec: StyleSpec
    warnings: list[str]
    errors: list[str]


class ValidateStyleUseCase:
    """Use case for validating style specifications."""

    def __init__(self, style_validator: StyleValidator):
        self._validator = style_validator

    def execute(self, request: ValidateStyleRequest, registry: dict) -> ValidateStyleResponse:
        """Execute the style validation use case.

        Args:
            request: Validation parameters.
            registry: IOP registry for parameter validation.

        Returns:
            Validation result with warnings and errors.
        """
        # Validate style spec against registry
        validated_spec, warnings = self._validator.validate(
            request.style_spec,
            registry,
            reference_analysis=request.reference_analysis,
            target_analysis=request.target_analysis,
        )

        errors = []
        if request.dtstyle_path:
            # Structural validation
            xml_errors = self._validator.validate_xml_structure(request.dtstyle_path)
            errors.extend(xml_errors)

            # Blob size validation
            blob_errors = self._validator.validate_blobs(request.dtstyle_path)
            errors.extend(blob_errors)

        return ValidateStyleResponse(
            is_valid=len(errors) == 0,
            validated_spec=validated_spec,
            warnings=warnings,
            errors=errors,
        )
