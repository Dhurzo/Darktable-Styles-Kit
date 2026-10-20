"""Application service for end-to-end style generation.

Owns the orchestration that used to live in :mod:`dtstylekit.cli`: preset
search setup, reference filtering, VLM generation, selected-preset
resolution, style assembly and companion reports.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from dtstylekit.paths import get_generated_dir

from .analyzer.pipeline import analyze_image, compute_reference_signature
from .analyzer.reference_filter import ReferenceFilterConfig, filter_references
from .codec.iop_registry import IOP_REGISTRY
from .presets.resolver import PresetResolver
from .vlm.orchestrator import generate_style_spec

if TYPE_CHECKING:
    from .analyzer.models import ImageAnalysis
    from .analyzer.reference_filter import ReferenceFilterResult
    from .presets.models import Preset
    from .presets.search import PresetSearcher
    from .vlm.models import StyleSpec

logger = logging.getLogger(__name__)


@dataclass
class GenerationRequest:
    """Inputs for one generation run."""

    image_path: str | Path
    direction: str = "auto"
    references: Sequence[str | Path] | None = None
    reference_filter: ReferenceFilterConfig | None = None
    reference_filter_result: ReferenceFilterResult | None = None
    model: str | None = None
    temperature: float = 0.4
    refine_iterations: int = 0
    refine_raw_path: str | Path | None = None
    bake_path: str | Path | None = None
    reference_preset: str | None = None
    capture_raw: bool = False


@dataclass
class GenerationResult:
    """Outputs of one generation run, ready for assembly."""

    spec: StyleSpec
    report: str
    warnings: list[str]
    analysis: ImageAnalysis
    presets: list[Preset] = field(default_factory=list)
    references: list[Path] = field(default_factory=list)
    filter_result: ReferenceFilterResult | None = None
    reference_analysis: dict | None = None
    raw_response: str | None = None


@dataclass
class GenerationOutput:
    """Paths written by :meth:`GenerationService.write`."""

    dtstyle_path: Path
    report_path: Path
    explanation_path: Path | None = None


class GenerationService:
    """Run the full analyze → search → VLM → resolve → assemble pipeline."""

    def __init__(
        self,
        searcher: PresetSearcher,
        analyzer: Callable[[str | Path], ImageAnalysis] = analyze_image,
        registry: dict | None = None,
        resolver: PresetResolver | None = None,
    ) -> None:
        self.searcher = searcher
        self.analyzer = analyzer
        self.registry = registry if registry is not None else IOP_REGISTRY
        self._resolver = resolver

    def generate(self, request: GenerationRequest) -> GenerationResult:
        references, filter_result = self._filter_references(request)

        reference_analysis: dict | None = None
        if references:
            try:
                reference_analysis = compute_reference_signature(references)
            except Exception as exc:
                logger.warning("Reference signature analysis failed: %s", exc)

        result = generate_style_spec(
            image_path=request.image_path,
            direction=request.direction,
            searcher=self.searcher,
            analyzer=self.analyzer,
            registry=self.registry,
            model=request.model,
            temperature=request.temperature,
            references=[str(path) for path in references] or None,
            reference_filter=request.reference_filter,
            reference_filter_result=filter_result,
            reference_analysis=reference_analysis,
            refine_iterations=request.refine_iterations,
            refine_raw_path=request.refine_raw_path,
            bake_path=request.bake_path,
            capture_raw=request.capture_raw,
            reference_preset=request.reference_preset,
        )
        if request.capture_raw:
            spec, report, warnings, analysis, raw_response = cast(
                "tuple[StyleSpec, str, list[str], ImageAnalysis, str]", result
            )
        else:
            spec, report, warnings, analysis = cast(
                "tuple[StyleSpec, str, list[str], ImageAnalysis]", result
            )
            raw_response = None

        resolved = self._resolve_presets(spec, warnings)
        if not resolved and not spec.plugins:
            raise ValueError(
                "Cannot generate a style: the VLM returned no selected presets "
                "and no scalar adjustments. Re-run with a different --model or "
                "provide --references that define the target aesthetic."
            )
        return GenerationResult(
            spec=spec,
            report=report,
            warnings=warnings,
            analysis=analysis,
            presets=resolved,
            references=references,
            filter_result=filter_result,
            reference_analysis=reference_analysis,
            raw_response=raw_response,
        )

    def write(
        self,
        result: GenerationResult,
        output: str | Path | None = None,
        *,
        lang: str = "es",
    ) -> GenerationOutput:
        """Assemble the style and companion report/explanation files."""
        from dtstylekit.analyzer.pipeline import analyze_reference_hues
        from dtstylekit.analyzer.reference_filter import format_reference_filter_report
        from dtstylekit.composer.explanation import generate_explanation
        from dtstylekit.composer.generator import generate_dtstyle
        from dtstylekit.composer.report import generate_report

        if output and str(output).endswith(".dtstyle"):
            dtstyle_path = Path(output).expanduser()
            output_dir = dtstyle_path.parent
            stem = dtstyle_path.stem
        else:
            output_dir = Path(output).expanduser() if output else get_generated_dir()
            stem = result.spec.style_name.replace(" ", "_")
            dtstyle_path = output_dir / f"{stem}.dtstyle"
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{stem}.md"

        generate_dtstyle(result.spec, result.presets, dtstyle_path, result.analysis)
        self._check_written_style(dtstyle_path)

        filter_report = (
            format_reference_filter_report(result.filter_result) if result.filter_result else None
        )
        try:
            generate_report(
                result.spec,
                result.presets,
                result.analysis,
                result.report,
                report_path,
                reference_filter_report=filter_report,
            )
        except Exception as exc:
            result.warnings.append(f"Report generation failed: {exc}")
            logger.warning("Report generation failed: %s", exc)

        explanation_path: Path | None = None
        if result.references:
            explanation_path = output_dir / f"{stem}_EXPLICACION.md"
            try:
                reference_analysis = result.reference_analysis
                if reference_analysis is None:
                    reference_analysis = analyze_reference_hues(result.references)
                generate_explanation(
                    result.spec,
                    result.presets,
                    result.analysis,
                    reference_analysis=reference_analysis,
                    reference_paths=result.references,
                    output_path=explanation_path,
                    lang=lang,
                    reference_filter_report=filter_report,
                )
            except Exception as exc:
                result.warnings.append(f"Explanation generation failed: {exc}")
                logger.warning("Explanation generation failed: %s", exc)
                explanation_path = None

        return GenerationOutput(
            dtstyle_path=dtstyle_path,
            report_path=report_path,
            explanation_path=explanation_path,
        )

    def _filter_references(
        self, request: GenerationRequest
    ) -> tuple[list[Path], ReferenceFilterResult | None]:
        references = [Path(path).expanduser() for path in request.references or []]
        if not references and request.reference_filter_result is None:
            return [], None
        filter_result = request.reference_filter_result or filter_references(
            references,
            request.reference_filter or ReferenceFilterConfig(),
        )
        if filter_result.error:
            raise ValueError(filter_result.error)
        if not filter_result.kept:
            raise ValueError("all reference images were rejected by the filter.")
        return list(filter_result.kept), filter_result

    def _resolve_presets(self, spec: StyleSpec, warnings: list[str]) -> list[Preset]:
        names = list(spec.selected_preset_names or [])
        if not names:
            warnings.append(
                "VLM returned no `selected_presets`; the composer will emit a "
                "style that contains only the scalar adjustments (no baseline)."
            )
            return []
        resolver = self._resolver or PresetResolver()
        if self._resolver is not None:
            return resolver.load_many(names, warnings)
        with resolver as owned:
            return owned.load_many(names, warnings)

    @staticmethod
    def _check_written_style(dtstyle_path: Path) -> None:
        root = ET.parse(dtstyle_path).getroot()
        enabled = [
            plugin
            for plugin in root.findall("style/plugin")
            if (plugin.findtext("enabled", "1") or "1") == "1"
        ]
        if enabled:
            return
        dtstyle_path.unlink(missing_ok=True)
        raise ValueError(
            "Generated style has no enabled plugins — every adjustment was "
            "silently dropped by the composer (preset blobs could not be "
            "re-packed). Refusing to ship a no-op style."
        )
