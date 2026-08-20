"""Use case for iterative style refinement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.interfaces import StyleGenerator
    from dtstylekit.vlm.models import StyleSpec


@dataclass
class RefineStyleRequest:
    """Input for style refinement."""

    raw_path: Path
    reference_paths: list[Path]
    direction: str
    target_analysis: ImageAnalysis
    max_iterations: int = 3
    work_dir: Path | None = None


@dataclass
class RefineStyleResponse:
    """Output from style refinement."""

    refined_spec: StyleSpec
    iterations_completed: int
    passed: bool
    warnings: list[str]


class RefineStyleUseCase:
    """Use case for iterative style refinement.

    Runs generate → render → evaluate → adjust loop.
    """

    def __init__(self, style_generator: StyleGenerator):
        self._style_generator = style_generator

    def execute(self, request: RefineStyleRequest) -> RefineStyleResponse:
        """Execute the iterative refinement use case.

        Args:
            request: Refinement parameters.

        Returns:
            Refined style spec with real iteration metadata.
        """
        from dtstylekit.vlm.iterative_refiner import iterative_refine

        # Build a generate function that the refiner can call
        def generate_func(direction: str, _ref_b64s: list[str]) -> StyleSpec:
            spec, _, _, _ = self._style_generator.generate(
                image_path=request.target_analysis.image_path
                if hasattr(request.target_analysis, "image_path")
                else "",
                direction=direction,
                references=[],  # refs already encoded in ref_b64s
                refine_iterations=0,
            )
            return spec

        # Run iterative refinement
        result = iterative_refine(
            raw_path=request.raw_path,
            reference_paths=request.reference_paths,
            direction=request.direction,
            target_analysis=request.target_analysis,
            generate_func=generate_func,
            max_iterations=request.max_iterations,
            work_dir=request.work_dir,
        )

        return RefineStyleResponse(
            refined_spec=result.spec,
            iterations_completed=result.iterations_completed,
            passed=result.passed,
            warnings=[],
        )
