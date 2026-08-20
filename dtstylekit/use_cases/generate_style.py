"""Use case for generating styles from images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.interfaces import (
        ImageEncoder,
        PresetRepository,
        StyleGenerator,
    )
    from dtstylekit.vlm.models import StyleSpec


@dataclass
class GenerateStyleRequest:
    """Input for style generation."""

    image_path: str | Path
    direction: str
    references: list[str | Path] | None = None
    refine_iterations: int = 0
    refine_raw_path: str | Path | None = None
    output_dir: Path | None = None
    lang: str = "es"


@dataclass
class GenerateStyleResponse:
    """Output from style generation."""

    style_spec: StyleSpec
    dtstyle_path: Path
    report_path: Path | None
    explanation_path: Path | None
    warnings: list[str]


class GenerateStyleUseCase:
    """Use case for end-to-end style generation.

    Orchestrates:
    1. Image analysis
    2. VLM-based style spec generation
    3. Preset loading and merging
    4. .dtstyle file generation
    5. Report and explanation generation
    """

    def __init__(
        self,
        style_generator: StyleGenerator,
        image_encoder: ImageEncoder,
        preset_repository: PresetRepository,
    ):
        self._style_generator = style_generator
        self._image_encoder = image_encoder
        self._preset_repository = preset_repository

    def execute(self, request: GenerateStyleRequest) -> GenerateStyleResponse:
        """Execute the style generation use case.

        Args:
            request: Generation parameters.

        Returns:
            Response with generated files and metadata.
        """
        from dtstylekit.analyzer.pipeline import analyze_reference_hues
        from dtstylekit.composer.explanation import generate_explanation
        from dtstylekit.composer.generator import generate_dtstyle
        from dtstylekit.composer.report import generate_report
        from dtstylekit.paths import get_generated_dir

        # 1. Generate style spec via VLM
        style_spec, vlm_report, vlm_warnings, analysis = self._style_generator.generate(
            image_path=request.image_path,
            direction=request.direction,
            references=request.references,
            refine_iterations=request.refine_iterations,
            refine_raw_path=request.refine_raw_path,
        )

        # 2. Load selected presets
        all_warnings = list(vlm_warnings)
        selected_presets = self._preset_repository.load_selected_presets(
            style_spec.selected_preset_names or [], all_warnings
        )

        # 3. Validate we have something to output
        if not selected_presets and not style_spec.plugins:
            raise ValueError(
                "Cannot generate style: no presets and no adjustments. "
                "Try a different --model or provide --references."
            )

        # 4. Determine output directory
        output_dir = request.output_dir or get_generated_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        # 5. Generate .dtstyle file
        style_name_safe = style_spec.style_name.replace(" ", "_")
        dtstyle_path = output_dir / f"{style_name_safe}.dtstyle"
        report_path = output_dir / f"{style_name_safe}.md"

        generate_dtstyle(style_spec, selected_presets, dtstyle_path, analysis)

        # 6. Generate technical report
        try:
            generate_report(
                style_spec,
                selected_presets,
                analysis,
                vlm_report,
                report_path,
            )
        except Exception as exc:
            all_warnings.append(f"Report generation failed: {exc}")

        # 7. Generate explanation document (if references provided)
        explanation_path = None
        if request.references:
            try:
                reference_analysis = analyze_reference_hues([Path(p) for p in request.references])
                explanation_path = output_dir / f"{style_name_safe}_EXPLICACION.md"
                generate_explanation(
                    style_spec,
                    selected_presets,
                    analysis,
                    reference_analysis,
                    [Path(p) for p in request.references],
                    explanation_path,
                    lang=request.lang,
                )
            except Exception as exc:
                all_warnings.append(f"Explanation generation failed: {exc}")

        # 8. Post-generation validation
        self._validate_generated_style(dtstyle_path, all_warnings)

        return GenerateStyleResponse(
            style_spec=style_spec,
            dtstyle_path=dtstyle_path,
            report_path=report_path if report_path.exists() else None,
            explanation_path=explanation_path,
            warnings=all_warnings,
        )

    def _validate_generated_style(self, dtstyle_path: Path, warnings: list[str]) -> None:
        """Validate the generated .dtstyle file.

        Args:
            dtstyle_path: Path to generated style.
            warnings: List to accumulate warnings.
        """
        import xml.etree.ElementTree as ET

        try:
            root = ET.parse(dtstyle_path).getroot()
            enabled_plugins = [
                p
                for p in root.findall("style/plugin")
                if (p.findtext("enabled", "1") or "1") == "1"
            ]
            if not enabled_plugins:
                warnings.append(
                    "Generated style has no enabled plugins — every adjustment "
                    "was silently dropped by the composer."
                )
        except Exception as exc:
            warnings.append(f"Post-generation validation failed: {exc}")
