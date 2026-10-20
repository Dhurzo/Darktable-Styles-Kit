"""End-to-end evaluation harness: VLM output -> preset -> rendered look.

Runs the full pipeline for an :class:`EvalCase`, renders the resulting
``.dtstyle`` with darktable, and scores it on two axes:

* **Intent loss** — how much of the VLM's intended ``adjustments`` survives
  parsing + validation + clamping (structural fidelity).
* **Look fidelity** — how closely the *rendered* output matches the reference
  look (visual fidelity, via :mod:`dtstylekit.eval.metrics`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.eval.dataset import EvalCase
    from dtstylekit.eval.metrics import LookFidelity, LookProfile
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.models import StyleSpec

logger = logging.getLogger(__name__)


@dataclass
class IntentLoss:
    """How much of the VLM's intended adjustments were lost."""

    total_params: int = 0
    dropped_ops: int = 0
    dropped_params: int = 0
    clamped_params: int = 0
    pct_preserved: float = 1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_params": self.total_params,
            "dropped_ops": self.dropped_ops,
            "dropped_params": self.dropped_params,
            "clamped_params": self.clamped_params,
            "pct_preserved": round(self.pct_preserved, 3),
            "notes": self.notes,
        }


@dataclass
class EvalResult:
    """Outcome of evaluating one :class:`EvalCase`."""

    case: EvalCase
    valid: bool = False
    fidelity: LookFidelity | None = None
    intent_loss: IntentLoss | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    style_path: Path | None = None
    rendered_path: Path | None = None
    reference_profile: LookProfile | None = None
    achieved_profile: LookProfile | None = None

    def to_dict(self) -> dict:
        return {
            "case": self.case.to_dict(),
            "valid": self.valid,
            "fidelity": self.fidelity.to_dict() if self.fidelity else None,
            "intent_loss": self.intent_loss.to_dict() if self.intent_loss else None,
            "warnings": self.warnings,
            "notes": self.notes,
        }


def measure_intent_loss(
    raw_text: str,
    registry: dict,
    reference_analysis: dict | None = None,
    target_analysis: ImageAnalysis | None = None,
) -> IntentLoss:
    """Compare the VLM's intended adjustments to the validated spec.

    Counts operations/parameters the parser+validator dropped or clamped.
    ``reference_analysis`` is accepted so chroma-cap style guards (which depend
    on it) are exercised — pass it for an accurate measurement.
    """
    from dtstylekit.vlm.parser import (
        _extract_json,
        intended_adjustments,
        parse_response,
    )
    from dtstylekit.vlm.validator import validate_style

    # Raw adjustments (pre-normalisation) — used to count *unknown* ops/params
    # the VLM emitted but that the normaliser silently dropped (also intent loss).
    data = _extract_json(raw_text) or {}
    raw_adj = data.get("adjustments") or {}

    intended = intended_adjustments(raw_text)
    if not intended and not raw_adj:
        return IntentLoss(
            total_params=0, pct_preserved=1.0, notes=["no intended adjustments parsed"]
        )

    spec, _ = parse_response(raw_text)
    try:
        validated, _ = validate_style(
            spec,
            registry,
            reference_analysis=reference_analysis,
            target_analysis=target_analysis,
        )
        valid_map = {p.operation: dict(p.params) for p in validated.plugins}
    except Exception as exc:
        # Validator needs the full IOP_REGISTRY; when only a stub is supplied
        # (e.g. unit tests) fall back to the parsed spec so parse-level drops
        # are still measured. Clamp detection is skipped in that case.
        logger.debug("validate_style unavailable for intent-loss: %s", exc)
        valid_map = {p.operation: dict(p.params) for p in spec.plugins}

    total = 0
    dropped_ops = 0
    dropped_params = 0
    clamped = 0
    for op, val in raw_adj.items():
        n_params = len(val) if isinstance(val, dict) else 1
        total += n_params
        if op not in intended:
            # Unknown op/term the normaliser discarded entirely.
            dropped_ops += 1
            dropped_params += n_params
            continue
        int_params = intended[op]
        valid_params = valid_map.get(op, {})
        for pk, _pv in (val.items() if isinstance(val, dict) else []):
            if pk not in int_params:
                dropped_params += 1
                continue
            ipv = int_params[pk]
            if pk not in valid_params:
                dropped_params += 1
            elif abs(valid_params[pk] - ipv) > 1e-3:
                clamped += 1

    preserved = (total - dropped_params - clamped) / total if total else 1.0
    notes: list[str] = []
    if dropped_ops:
        notes.append(f"{dropped_ops} op(s) fully dropped")
    if dropped_params:
        notes.append(f"{dropped_params} param(s) dropped")
    if clamped:
        notes.append(f"{clamped} param(s) clamped")
    return IntentLoss(total, dropped_ops, dropped_params, clamped, preserved, notes)


def _resolve_presets(spec: StyleSpec, warnings: list[str]) -> list:
    """Resolve the spec's selected presets to full Preset objects."""
    from dtstylekit.presets.resolver import PresetResolver

    names = list(spec.selected_preset_names or [])
    if not names:
        warnings.append(
            "VLM returned no `selected_presets`; the composer will emit a "
            "style that contains only the scalar adjustments (no baseline)."
        )
        return []
    with PresetResolver() as resolver:
        return resolver.load_many(names, warnings)


def _check_valid(style_path: Path) -> bool:
    """A generated ``.dtstyle`` is valid if it parses to >=1 plugin."""
    from dtstylekit.presets.parser import parse_preset

    try:
        preset = parse_preset(style_path)
    except Exception:
        return False
    if preset is None:
        return False
    return len(preset.plugins) > 0


def run_eval_case(
    case: EvalCase,
    searcher: PresetSearcher,
    analyzer: Callable,
    registry: dict,
    model: str | None,
    out_dir: Path,
    refine_iterations: int = 0,
    refine_raw_path: Path | None = None,
) -> EvalResult:
    """Run the full pipeline for one case and score the result."""
    from dtstylekit.analyzer.pipeline import analyze_reference_hues
    from dtstylekit.analyzer.reference_filter import (
        ReferenceFilterConfig,
        filter_references,
    )
    from dtstylekit.composer.generator import generate_dtstyle
    from dtstylekit.eval.metrics import compare_looks, extract_look_profile
    from dtstylekit.render import render_with_style
    from dtstylekit.vlm.orchestrator import generate_style_spec

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = EvalResult(case=case)

    reference_filter_result = None
    refs = cast("list[str | Path] | None", list(case.reference_images) or None)
    if case.reference_images:
        reference_filter_result = filter_references(
            case.reference_images, ReferenceFilterConfig()
        )
        if reference_filter_result.error:
            result.notes.append(reference_filter_result.error)
            return result
        refs = [str(p) for p in reference_filter_result.kept]
        if not refs:
            result.notes.append("all reference images rejected by the filter")
            return result
    try:
        gen = generate_style_spec(
            image_path=case.base_image,
            direction=case.direction,
            searcher=searcher,
            analyzer=analyzer,
            registry=registry,
            model=model,
            references=refs,
            reference_filter_result=reference_filter_result,
            refine_iterations=refine_iterations,
            refine_raw_path=refine_raw_path,
            capture_raw=True,
        )
    except Exception as exc:
        result.notes.append(f"generation failed: {exc}")
        return result

    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.vlm.models import StyleSpec

    _GenTuple = tuple[StyleSpec, str, list[str], ImageAnalysis, str]
    spec, report, warnings, analysis, raw_text = cast(_GenTuple, gen)
    result.warnings = list(warnings)

    presets = _resolve_presets(spec, result.warnings)
    style_path = out_dir / f"{case.name}.dtstyle"
    try:
        generate_dtstyle(spec, presets, style_path, analysis)
        result.style_path = style_path
        result.valid = _check_valid(style_path)
    except Exception as exc:
        result.notes.append(f"style assembly failed: {exc}")
        result.valid = False
        return result

    kept_refs = [Path(p) for p in (refs or [])]
    ref_analysis = (
        analyze_reference_hues(kept_refs)
        if kept_refs
        else None
    )
    result.intent_loss = measure_intent_loss(
        raw_text, registry, reference_analysis=ref_analysis, target_analysis=analysis
    )

    if case.reference_images:
        work = out_dir / "render"
        work.mkdir(exist_ok=True)
        rendered = render_with_style(
            case.base_image, style_path, spec.style_name or case.name, work
        )
        if rendered is None:
            result.notes.append("styled render failed (darktable-cli)")
        else:
            result.rendered_path = rendered
            result.achieved_profile = extract_look_profile(rendered)
            result.reference_profile = extract_look_profile(kept_refs[0])
            result.fidelity = compare_looks(
                result.reference_profile, result.achieved_profile
            )
            if not result.fidelity.passed:
                result.notes.append(
                    f"look fidelity {result.fidelity.overall:.2f} below pass threshold"
                )
    else:
        result.notes.append("no reference look — structural scoring only")

    return result
