"""End-to-end VLM style spec generation.

Orchestrates: image analysis → preset search → prompt build → VLM call
→ response parse → validation → iterative refinement (optional).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from dtstylekit.analyzer.pipeline import analyze_reference_hues

from .client import VLMClient
from .iterative_refiner import iterative_refine
from .parser import parse_response
from .prompt_builder import build_prompt
from .schema_renderer import render_iop_schema

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.models import StyleSpec
from .validator import validate_style

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.models import Preset

    from .models import StyleSpec

logger = logging.getLogger(__name__)


def _encode_resized(image_path: str | Path, max_dim: int = 768, quality: int = 88) -> str:
    """Encode image as base64 JPEG, downscaled to max_dim."""
    import io

    from PIL import Image

    img = Image.open(image_path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")  # type: ignore[assignment]
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def generate_style_spec(
    image_path: str | Path,
    direction: str,
    searcher: PresetSearcher,
    analyzer: Callable[[str | Path], ImageAnalysis],
    registry: dict,
    model: str | None = None,
    temperature: float = 0.4,
    references: list[str | Path] | None = None,
    refine_iterations: int = 0,  # 0 = no iterative refinement
    refine_raw_path: str | Path | None = None,  # RAW file for test renders
) -> tuple[StyleSpec, str, list[str], ImageAnalysis]:
    """Generate a validated StyleSpec for a given image.

    Args:
        image_path: Path to JPEG/TIFF image (for analysis + VLM vision).
        direction: User style direction string.
        searcher: PresetSearcher instance.
        analyzer: Callable taking image_path -> ImageAnalysis.
        registry: IOP_REGISTRY dict.
        model: VLM model override.
        temperature: Sampling temperature.
        references: Optional list of reference-look images (JPEG/TIFF) the
            VLM should derive the target aesthetic from.  The analysis
            still runs on ``image_path``; the references are attached to
            the prompt as vision context.
        refine_iterations: If >0, run iterative generate→render→eval loop
            using ``refine_raw_path`` as test RAW. Each iteration re-prompts
            the VLM with visual feedback from the previous render.
        refine_raw_path: RAW file path for test renders during refinement.
            Required if ``refine_iterations > 0``.

    Returns:
        (validated_spec, vlm_report, warnings, image_analysis) tuple.
    """
    # 1. Analyze image
    logger.info("Analyzing %s", image_path)
    analysis = analyzer(image_path)

    # 2. Search presets.  When no explicit direction is given (the CLI
    #    default is "auto"), build a query from the image's own scene
    #    tags so the semantic search has something meaningful to match —
    #    a literal "auto" query returns nothing useful and (because the
    #    preset library is dominated by camera baseline profiles, which
    #    are category-filtered out) can yield zero candidates.
    if direction and direction.strip().lower() not in ("", "auto"):
        query = direction
    else:
        tags = getattr(analysis, "scene_tags", None) or []
        query = " ".join(tags) if tags else "neutral balanced photography"
    logger.info("Searching presets for query: %s", query)
    search_results = searcher.hybrid_search(query, limit=5)

    # 2b. Resolve each SearchResult (lightweight PresetIndexEntry) back to a
    # full Preset (with plugins / op_params / blendops / filename) by
    # re-parsing the .dtstyle file from disk. The indexer persists the
    # absolute file_path for exactly this case.
    presets: list[Preset] = []
    for r in search_results:
        file_path = getattr(r.preset, "file_path", None)
        if not file_path:
            logger.warning(
                "SearchResult for %r has no file_path — cannot resolve full Preset",
                getattr(r.preset, "display_name", None) or r.preset.name,
            )
            continue
        from pathlib import Path

        from dtstylekit.presets.parser import parse_preset

        full = parse_preset(Path(file_path))
        if full is not None:
            presets.append(full)
        else:
            logger.warning("Could not re-parse preset file: %s", file_path)

    # 2c. Luminance-suitability filter.  The semantic search matches
    # keywords, not exposure: a query built from scene tags like "night
    # low-key" happily returns "day for twilight" (net exposure -1 EV),
    # and gemma3:12b picked it for an already-dark
    # image — crushing the output to near black.  Drop candidates whose
    # net exposure pushes a dark image darker (or a bright image
    # brighter), but always keep at least two candidates so the VLM
    # still has a choice.
    mean_lum = getattr(getattr(analysis, "luminance", None), "mean", None)
    if not isinstance(mean_lum, int | float) or isinstance(mean_lum, bool):
        mean_lum = None
    if mean_lum is not None:
        fitted = [p for p in presets if _preset_ev_fits(p, mean_lum)]
        if len(fitted) >= 2:
            dropped = len(presets) - len(fitted)
            if dropped:
                logger.info(
                    "Dropped %d candidate preset(s) with unsuitable net "
                    "exposure for a %.2f-luminance image",
                    dropped,
                    mean_lum,
                )
            presets = fitted
        elif len(presets) > len(fitted) > 0:
            logger.info(
                "Kept all %d candidates: filter would leave fewer than 2",
                len(presets),
            )

    # 3. Build schema
    schema = render_iop_schema(registry)

    # 4. Optionally encode image for VLM vision
    try:
        image_b64 = _encode_resized(image_path)
    except Exception as e:
        logger.warning("Could not encode image: %s", e)
        image_b64 = None

    # 4b. Optionally encode reference-look images (they define the target
    # aesthetic; e.g. samples of a photographer's style).
    reference_b64s: list[str] = []
    reference_paths: list[Path] = []
    for ref in references or []:
        try:
            reference_b64s.append(_encode_resized(ref))
            reference_paths.append(Path(ref))
            logger.info("Attaching reference image: %s", ref)
        except Exception as e:
            logger.warning("Could not encode reference image %s: %s", ref, e)

    # 4c. Analyze reference hues with Python (avoids VLM visual confusion)
    reference_analysis: dict | None = None
    if reference_paths:
        logger.info("Analyzing reference hues with Python...")
        reference_analysis = analyze_reference_hues(reference_paths)
        logger.info(
            "Reference hues: shadows_H=%.1f (conf=%.2f), midtones_H=%.1f (conf=%.2f), highlights_H=%.1f (conf=%.2f), "
            "shadows_S=%.3f, midtones_S=%.3f, highlights_S=%.3f",
            reference_analysis.get("shadows_hue", 0) or 0,
            reference_analysis.get("shadows_hue_confidence", 0),
            reference_analysis.get("midtones_hue", 0) or 0,
            reference_analysis.get("midtones_hue_confidence", 0),
            reference_analysis.get("highlights_hue", 0) or 0,
            reference_analysis.get("highlights_hue_confidence", 0),
            reference_analysis.get("shadows_sat", 0),
            reference_analysis.get("midtones_sat", 0),
            reference_analysis.get("highlights_sat", 0),
        )

        # 4c-bis. Global HSV saturation of the references (mean of
        # luminance.saturation_mean per reference).  The per-zone *_sat
        # values from analyze_reference_hues use ABSOLUTE RGB deltas
        # averaged over ALL pixels of the zone — on low-key references
        # (most pixels in shadows) they systematically under-report how
        # colorful the photos actually are (Alen Palander: zones
        # 0.04–0.08 vs HSV mean ~0.30).  The VLM used the depressed
        # number to justify filmicrgb.saturation=-20 and skipped
        # vibrance entirely, producing muted outputs.  Feed the true
        # global HSV saturation into the prompt so saturation decisions
        # are based on real data.
        try:
            from dtstylekit.analyzer.pipeline import analyze_image as _analyze_ref

            _sats: list[float] = []
            for ref in reference_paths:
                try:
                    _a = _analyze_ref(ref)
                    _s = getattr(getattr(_a, "luminance", None), "saturation_mean", None)
                    if isinstance(_s, int | float) and not isinstance(_s, bool):
                        _sats.append(float(_s))
                except Exception:
                    continue
            if _sats:
                reference_analysis["global_saturation"] = sum(_sats) / len(_sats)
                logger.info(
                    "Reference global HSV saturation: %.3f (%d refs)",
                    reference_analysis["global_saturation"],
                    len(_sats),
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not compute reference global saturation: %s", exc)

    # 5. Build prompt
    messages = build_prompt(
        analysis,
        presets,
        direction,
        schema,
        image_b64,
        reference_b64s=reference_b64s or None,
        reference_analysis=reference_analysis,
    )

    # 6. Call VLM.  gemma3:12b left ``content`` empty under ``think="low"``
    #    on some runs (everything routed to the ``thinking`` field), which
    #    produced an empty style.  ``think=False`` reliably populates
    #    ``content`` with the final JSON, and the client still falls back to
    #    ``thinking`` if ``content`` is ever empty.  ``max_tokens`` bounds
    #    the call so it cannot run unbounded on CPU.
    logger.info("Calling VLM...")
    # Long timeout: on CPU-only machines a gemma3:12b generation takes
    # 10-30 minutes.  The client's default is 1 hour; pass it explicitly
    # so a slow machine never trips the 5-minute default from older code.
    client = VLMClient(timeout=3600.0, max_retries=1)

    def _call(temperature: float) -> tuple[StyleSpec, str, list[str]]:
        response_text = client.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=3000,
            # 16384: with several attached reference images a single
            # request routinely exceeds 8192 (5 refs + target image
            # ≈ 7-9k tokens on top of the analysis/preset/schema text).
            num_ctx=16384,
            think=False,
            json_mode=False,
        )
        spec, report = parse_response(response_text)
        validated, warns = validate_style(
            spec,
            registry,
            reference_analysis=reference_analysis,
            target_analysis=analysis,
        )
        return validated, report, warns

    validated_spec, report, warnings = _call(temperature)

    # 6b. Empty spec guard.  A VLM response that yields neither presets nor
    # adjustments produces a useless "untitled" style with no plugins.
    # Retry once at higher temperature (cheap, often recovers empty specs
    # from "thinking" models), then fail with a clear error instead of
    # silently writing a broken style.
    if not validated_spec.plugins and not validated_spec.selected_preset_names:
        logger.warning("VLM returned an empty style spec — retrying once at higher temperature")
        try:
            validated_spec, report, retry_warnings = _call(0.8)
            warnings = list(retry_warnings)
        except Exception as exc:
            logger.warning("VLM retry failed: %s", exc)
        if not validated_spec.plugins and not validated_spec.selected_preset_names:
            raise ValueError(
                "VLM returned an empty style spec (no presets, no adjustments) "
                "even after a retry — cannot generate a style. "
                "Check the model and the analysis output."
            )

    # 7. Report + warnings for the CLI
    logger.info("VLM report: %s", (report or "(empty)")[:500])
    for w in warnings:
        logger.warning(w)

    # 8. Optional iterative refinement (generate → render → evaluate → adjust)
    if refine_iterations > 0 and refine_raw_path:
        logger.info("Starting iterative refinement (%d iterations)...", refine_iterations)

        # Build a generate function that the refiner can call
        def _generate_for_refiner(refine_direction: str, ref_b64s: list[str]) -> StyleSpec:
            build_prompt(
                analysis,
                presets,
                refine_direction,
                schema,
                image_b64,
                reference_b64s=ref_b64s or None,
            )
            refine_spec, _, refine_warns = _call(temperature)
            # Merge warnings
            warnings.extend(refine_warns)
            return refine_spec

        # Encode references for refiner
        ref_b64s = reference_b64s if reference_b64s else []
        for ref in references or []:
            if ref not in list(references or []):  # avoid double-encoding
                try:
                    ref_b64s.append(_encode_resized(ref))
                except Exception:
                    pass

        # Run iterative refinement
        try:
            refine_result = iterative_refine(
                raw_path=Path(refine_raw_path),
                reference_paths=[Path(r) for r in (references or [])],
                direction=direction,
                target_analysis=analysis,
                generate_func=_generate_for_refiner,
                max_iterations=refine_iterations,
            )
            validated_spec = refine_result.spec
            if refine_result.passed:
                logger.info(
                    "Iterative refinement passed on iteration %d",
                    refine_result.iterations_completed,
                )
            else:
                logger.info(
                    "Iterative refinement completed %d iteration(s) without passing; "
                    "returning best attempt",
                    refine_result.iterations_completed,
                )
        except Exception as e:
            logger.warning("Iterative refinement failed: %s, using original spec", e)

    return validated_spec, report, warnings, analysis


def _preset_net_ev(preset: Preset) -> float:
    """Net exposure EV contributed by a preset's *enabled* exposure IOPs.

    Decodes the exposure blobs (v6 or v7 layout) and sums their
    ``exposure`` field.  A preset like "day for twilight" contributes
    -1.0 EV; a plain color preset contributes 0.0.
    """
    from dtstylekit.codec.iop_registry import unpack_params
    from dtstylekit.codec.xmp_codec import decode_xmp

    ev = 0.0
    for plg in preset.plugins:
        if plg.operation != "exposure" or not plg.enabled or not plg.op_params:
            continue
        try:
            params = unpack_params("exposure", decode_xmp(plg.op_params))
            ev += float(params.get("exposure", 0.0))
        except Exception:
            continue
    return ev


def _preset_ev_fits(preset: Preset, mean_lum: float) -> bool:
    """Whether a preset's net exposure suits the image's brightness.

    Dark images (mean luminance < 0.3) are crushed by darkening presets
    (net EV < -0.3); bright images (> 0.7) are blown out by brightening
    presets (net EV > +0.3).  Everything else is acceptable.

    In addition, for dark images we drop dehaze/defog presets by name:
    hazeremoval is not in the IOP registry (its blob cannot be decoded
    for a net-EV estimate), but dehaze removes atmospheric brightness,
    which empirically crushes dark images (gemma3:12b picked "dehaze
    strong luminance only" for a night photo and pushed 61% of pixels
    below 10/255).
    """
    ev = _preset_net_ev(preset)
    if mean_lum < 0.3 and ev < -0.3:
        return False
    if mean_lum > 0.7 and ev > 0.3:
        return False
    if mean_lum < 0.3:
        name = " ".join(
            part.lower() for part in (preset.name, getattr(preset, "description", "") or "") if part
        )
        if any(kw in name for kw in ("dehaze", "defog", "fog", "mist")):
            return False
    return True
