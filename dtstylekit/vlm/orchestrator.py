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

from dtstylekit.analyzer.pipeline import (
    analyze_reference_hues,
    compute_reference_signature,
)

from .client import VLMClient
from .iterative_refiner import iterative_refine
from .parser import parse_response
from .prompt_builder import build_prompt
from .schema_renderer import render_iop_schema
from .validator import validate_style

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.models import Preset
    from dtstylekit.presets.search import PresetSearcher

    from .models import StyleSpec

logger = logging.getLogger(__name__)


def _as_float(value: object, default: float | None = None) -> float | None:
    """Narrow an arbitrary analysis value to float without bool leakage."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


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
    bake_path: str | Path | None = None,  # image used for safety-bake renders
    capture_raw: bool = False,  # if True, also return the raw VLM text (5-tuple)
    reference_preset: str | None = None,  # ground-truth baseline preset filename
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
        bake_path: Image used for safety-bake renders. Defaults to
            ``image_path``; pass the RAW when ``image_path`` is a preview.

    Returns:
        (validated_spec, vlm_report, warnings, image_analysis) tuple.
    """
    # 1. Analyze image
    logger.info("Analyzing %s", image_path)
    analysis = analyzer(image_path)

    # 1b. Early reference analysis.  When reference images are supplied they
    #     define the TARGET LOOK, so we analyse them up-front and (a) drive the
    #     semantic preset search from the reference aesthetic (not the literal
    #     direction string) and (b) feed the prompt.  Computed once here and
    #     reused below (no double analysis).
    reference_analysis: dict | None = None
    reference_paths: list[Path] = []
    reference_b64s: list[str] = []
    if references:
        for ref in references:
            try:
                reference_b64s.append(_encode_resized(ref))
                reference_paths.append(Path(ref))
                logger.info("Attaching reference image: %s", ref)
            except Exception as e:
                logger.warning("Could not encode reference image %s: %s", ref, e)
        if reference_paths:
            logger.info("Analyzing reference signature with Python...")
            try:
                reference_analysis = compute_reference_signature(reference_paths)
            except Exception as exc:
                logger.warning(
                    "Reference signature analysis failed (%s); falling back to hues", exc
                )
                try:
                    reference_analysis = analyze_reference_hues(reference_paths)
                except Exception as hue_exc:
                    logger.warning("Reference hue analysis failed: %s", hue_exc)
            if reference_analysis:
                logger.info(
                    "Reference signature: luminance=%.3f saturation=%.3f "
                    "warmth=%+.3f contrast=%.3f DR=%.3f",
                    reference_analysis.get("global_luminance", 0.0),
                    reference_analysis.get("global_saturation", 0.0),
                    reference_analysis.get("global_warmth_rb", 0.0),
                    reference_analysis.get("global_contrast", 0.0),
                    reference_analysis.get("global_dynamic_range", 0.0),
                )

    # 2. Search presets.  When references are supplied, build the query from
    #    the *reference* look (so search returns the creative presets that
    #    actually match the target aesthetic — sepia, autumn, vivid — instead
    #    of treating the literal direction as a search term).  Otherwise fall
    #    back to the direction, or to the image's scene tags when direction is
    #    empty/auto.
    if references and reference_analysis:
        query = _reference_query(reference_analysis)
    elif direction and direction.strip().lower() not in ("", "auto"):
        query = direction
    else:
        tags = getattr(analysis, "scene_tags", None) or []
        query = " ".join(tags) if tags else "neutral balanced photography"
    logger.info("Searching presets for query: %s", query)
    # Reference-driven generation needs a wider candidate pool so the VLM can
    # pick the preset that actually matches the reference look.
    search_limit = 10 if references else 5
    search_results = searcher.hybrid_search(query, limit=search_limit)

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

    def _call(
        temperature: float, msgs: list[dict] | None = None
    ) -> tuple[StyleSpec, str, list[str]]:
        response_text = client.generate(
            msgs or messages,
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
        if capture_raw:
            raw_capture.append(response_text)
        spec, report = parse_response(response_text)
        validated, warns = validate_style(
            spec,
            registry,
            reference_analysis=reference_analysis,
            target_analysis=analysis,
        )
        return validated, report, warns

    raw_capture: list[str] = []
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

    # 6c. Signature fidelity: deterministically fit the spec to the
    # reference signature (saturation level, tonal placement, warmth).
    # No-op without references.  Runs after validation so the fitted
    # values are the ones serialized.
    if reference_analysis:
        # 6c-bis. Reference-driven baseline.  gemma3 often returns
        # selected_presets:[] even when instructed to compose from a preset,
        # which leaves the style with no tone map / grade baseline (the root
        # cause of crushed shadows and weak fidelity on reference generation).
        # When references are present and the VLM picked nothing, deterministically
        # select the most relevant *creative* candidate as the baseline so the
        # style inherits a real tone map + grade; the VLM's adjustments still
        # refine it on top.
        if not validated_spec.selected_preset_names:
            _fn: str | None = None
            if reference_preset:
                # Ground-truth baseline (e.g. the source preset of the
                # reference look) supplied by the caller — always preferred.
                _fn = reference_preset
            elif presets:
                # gemma3 often returns selected_presets:[] even when instructed
                # to compose from a preset; deterministically pick the most
                # relevant *creative* candidate so the style inherits a real
                # tone map + grade.  The VLM's adjustments still refine on top.
                _best = None
                for _p in presets:
                    _fn_cand = getattr(
                        getattr(_p, "file_path", None), "name", ""
                    ) or getattr(_p, "name", "")
                    if _fn_cand.startswith("examples_"):
                        _best = _p
                        break
                if _best is None:
                    _best = presets[0]
                _fn = getattr(
                    getattr(_best, "file_path", None), "name", ""
                ) or getattr(_best, "name", "")
            if _fn:
                validated_spec.selected_preset_names = [_fn]
                logger.info("Reference generation: auto-selected baseline preset %s", _fn)

        from dtstylekit.vlm.fidelity import auto_fit_signature

        validated_spec, fit_warnings = auto_fit_signature(
            validated_spec, reference_analysis, analysis
        )
        warnings.extend(fit_warnings)

    # 6d. SAFETY BAKE (deterministic, no VLM).  Assemble the final style and
    # render it on the target; if it clips highlights, lower exposure.  It
    # deliberately does NOT lift dark renders to the reference brightness:
    # that would serialize a target-specific exposure into the style and blow
    # brighter photos.  ``dtstylekit apply`` normalizes brightness per image.
    # Runs after validation + auto-fit so the saved style is clipping-safe.
    if presets is not None:
        try:
            import tempfile

            _bake_dir = Path(tempfile.mkdtemp(prefix="dtstylekit_bake_"))
            validated_spec = _safety_bake(
                validated_spec,
                presets,
                bake_path or image_path,
                _bake_dir,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Safety bake failed (kept un-baked spec): %s", exc)

    # 7. Report + warnings for the CLI
    logger.info("VLM report: %s", (report or "(empty)")[:500])
    for w in warnings:
        logger.warning(w)

    # 8. Optional iterative refinement (generate → render → evaluate → adjust)
    if refine_iterations > 0 and refine_raw_path:
        logger.info("Starting iterative refinement (%d iterations)...", refine_iterations)

        # Build a generate function that the refiner can call.  The refined
        # direction must actually reach the VLM, so rebuild the messages for
        # every iteration instead of reusing the original prompt.
        def _generate_for_refiner(refine_direction: str, ref_b64s: list[str]) -> StyleSpec:
            refine_messages = build_prompt(
                analysis,
                presets,
                refine_direction,
                schema,
                image_b64,
                reference_b64s=ref_b64s or None,
                reference_analysis=reference_analysis,
            )
            refine_spec, _, refine_warns = _call(temperature, refine_messages)
            # Merge warnings
            warnings.extend(refine_warns)
            # Check clipping before returning: the refiner renders this spec
            # directly, so keep its highlights safe.  It never lifts exposure
            # to a reference target (that is apply's job).
            if presets is not None:
                try:
                    import tempfile

                    refine_spec = _safety_bake(
                        refine_spec,
                        presets,
                        bake_path or image_path,
                        Path(tempfile.mkdtemp(prefix="dtstylekit_bake_")),
                    )
                except Exception as exc:  # pragma: no cover — defensive
                    logger.warning("Refinement safety bake failed: %s", exc)
            return refine_spec

        # Run iterative refinement
        try:
            refine_result = iterative_refine(
                raw_path=Path(refine_raw_path),
                reference_paths=[Path(r) for r in (references or [])],
                direction=direction,
                target_analysis=analysis,
                generate_func=_generate_for_refiner,
                max_iterations=refine_iterations,
                reference_analysis=reference_analysis,
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

    if capture_raw:
        return validated_spec, report, warnings, analysis, (  # type: ignore[return-value]
            raw_capture[-1] if raw_capture else ""
        )
    return validated_spec, report, warnings, analysis


def _safety_bake(
    spec: StyleSpec,
    presets: list,
    target_path: str | Path,
    work_dir: str | Path,
) -> StyleSpec:
    """Prevent clipped highlights without baking target brightness.

    A ``.dtstyle`` is a reusable look, not an exposure correction for one
    photo.  Earlier versions forced the target's mean luminance toward the
    reference and serialized the resulting +EV (e.g. +2.54 EV for a dark
    frame); applying that style to a brighter photo blew its highlights.
    Reference brightness is now normalized per image by ``dtstylekit apply``.

    This check only lowers exposure when the freshly generated style clips
    highlights on the bake target.  It never lifts exposure to match a
    reference, so the saved style stays exposure-neutral.
    """
    import math

    from dtstylekit.composer.generator import generate_dtstyle
    from dtstylekit.vlm.iterative_refiner import compute_render_metrics, render_with_style
    from dtstylekit.vlm.models import Plugin

    selected = [
        p
        for p in presets
        if getattr(getattr(p, "file_path", None), "name", "") in (spec.selected_preset_names or [])
    ]

    target = Path(target_path)
    work = Path(work_dir)
    tmp = work / "_bake.dtstyle"
    max_clip = 0.01
    for attempt in range(4):
        generate_dtstyle(spec, selected, tmp, None)
        ach = render_with_style(target, tmp, "bake", work)
        if ach is None:
            break
        m = compute_render_metrics(ach)
        if m.clipped_pct <= max_clip:
            if attempt:
                logger.info(
                    "Safety bake: highlights safe after %d nudge(s) "
                    "(clipped=%.1f%%, lum=%.3f)",
                    attempt,
                    m.clipped_pct * 100.0,
                    m.mean_luminance,
                )
            break
        exp = next((p for p in spec.plugins if p.operation == "exposure"), None)
        if exp is None:
            exp = Plugin(operation="exposure", enabled=True, params={"exposure": 0.0})
            spec.plugins.append(exp)
        cur = float(exp.params.get("exposure") or 0.0)
        # Clipping is a highlight problem: reduce exposure.  Do not lift a
        # dark render here; that is the exporter's job (and target-specific).
        step = min(1.5, max(0.25, math.log2(max(m.clipped_pct / max_clip, 1.0001))))
        new = max(-6.0, min(6.0, cur - step))
        logger.info(
            "Safety bake: clipped=%.1f%% -> exposure %+.2f -> %+.2f EV",
            m.clipped_pct * 100.0,
            cur,
            new,
        )
        if abs(new - cur) < 0.02:
            break
        exp.params["exposure"] = new
    else:
        logger.warning(
            "Safety bake: highlights still clipped after 4 attempts; "
            "the exporter will clamp exposure per image"
        )
    return spec


def _reference_query(reference_analysis: dict) -> str:
    """Build a semantic-search query from the *reference* look.

    When reference images define the target aesthetic we must search the
    preset library for the creative looks that actually match it (sepia,
    autumn, vivid, ...) rather than treating the literal direction string as
    a search term (which returns nothing useful, e.g. "Reproduce the
    reference look...").  Used by :func:`generate_style_spec` step 2.
    """
    hues = [reference_analysis.get(f"{z}_hue") for z in ("shadows", "midtones", "highlights")]
    warm_hues = [h for h in hues if isinstance(h, (int, float))]

    parts: list[str] = []
    if warm_hues:
        mean_h = sum(warm_hues) / len(warm_hues)
        if mean_h <= 90 or mean_h >= 315:
            parts.append("warm")
        else:
            parts.append("cool")

    # Always include the creative-look vocabulary so hybrid search surfaces the
    # real example presets (autumn, sepia, extreme saturation, faded, twilight,
    # ...) regardless of how a dark base image measures.  The VLM then picks the
    # closest match by *looking* at the reference images.
    parts += [
        "autumn",
        "sepia",
        "extreme saturation",
        "faded",
        "vintage",
        "pastel",
        "twilight",
        "color grade",
        "film look",
    ]
    return " ".join(parts)


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
