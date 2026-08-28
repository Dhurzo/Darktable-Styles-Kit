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
    from pathlib import Path  # local import: a later block also imports Path

    reference_paths: list[Path] = []
    reference_b64s: list[str] = []
    if references:
        for ref in references:
            try:
                reference_b64s.append(_encode_resized(ref))
                reference_paths.append(Path(ref))
            except Exception as e:
                logger.warning("Could not encode reference image %s: %s", ref, e)
        if reference_paths:
            logger.info("Analyzing reference hues with Python (early)...")
            try:
                reference_analysis = analyze_reference_hues(reference_paths)
            except Exception as exc:
                logger.warning("Reference hue analysis failed: %s", exc)
            try:
                from dtstylekit.analyzer.pipeline import analyze_image as _analyze_ref

                _sats, _lums = [], []
                for ref in reference_paths:
                    try:
                        _a = _analyze_ref(ref)
                        _s = getattr(getattr(_a, "luminance", None), "saturation_mean", None)
                        if isinstance(_s, int | float) and not isinstance(_s, bool):
                            _sats.append(float(_s))
                        _m = getattr(getattr(_a, "luminance", None), "mean", None)
                        if isinstance(_m, int | float) and not isinstance(_m, bool):
                            _lums.append(float(_m))
                    except Exception:
                        continue
                if _sats:
                    reference_analysis["global_saturation"] = sum(_sats) / len(_sats)
                if _lums:
                    reference_analysis["global_luminance"] = sum(_lums) / len(_lums)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Could not compute reference global saturation: %s", exc)
            try:
                from dtstylekit.vlm.fidelity import compute_reference_profile

                reference_analysis.update(compute_reference_profile(reference_paths))
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Could not compute reference profile: %s", exc)

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

    # 4c. Analyze reference hues with Python (avoids VLM visual confusion).
    # Skipped when the early reference analysis (step 1b) already succeeded.
    if reference_paths and reference_analysis is None:
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
            _lums: list[float] = []
            for ref in reference_paths:
                try:
                    _a = _analyze_ref(ref)
                    _s = getattr(getattr(_a, "luminance", None), "saturation_mean", None)
                    if isinstance(_s, int | float) and not isinstance(_s, bool):
                        _sats.append(float(_s))
                    _m = getattr(getattr(_a, "luminance", None), "mean", None)
                    if isinstance(_m, int | float) and not isinstance(_m, bool):
                        _lums.append(float(_m))
                except Exception:
                    continue
            if _sats:
                reference_analysis["global_saturation"] = sum(_sats) / len(_sats)
                logger.info(
                    "Reference global HSV saturation: %.3f (%d refs)",
                    reference_analysis["global_saturation"],
                    len(_sats),
                )
            if _lums:
                reference_analysis["global_luminance"] = sum(_lums) / len(_lums)
                logger.info(
                    "Reference global luminance: %.3f (%d refs)",
                    reference_analysis["global_luminance"],
                    len(_lums),
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not compute reference global saturation: %s", exc)

        # 4c-ter. Extended reference profile (contrast, dynamic range,
        # saturation peaks, warmth) — feeds the adaptive fidelity ranges.
        try:
            from dtstylekit.vlm.fidelity import compute_reference_profile

            reference_analysis.update(compute_reference_profile(reference_paths))
            logger.info(
                "Reference profile: contrast=%.3f DR=%.3f sat_p90=%.3f warmth=%+.3f",
                reference_analysis.get("global_contrast", 0),
                reference_analysis.get("global_dynamic_range", 0),
                reference_analysis.get("global_saturation_p90", 0),
                reference_analysis.get("global_warmth_rb", 0),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not compute reference profile: %s", exc)

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
    # render it on the target; if the result is crushed / under-exposed (or
    # far below the reference brightness), nudge exposure until it is safe.
    # This guarantees reference transfer onto dark photos does not collapse to
    # near-black — the single biggest source of uneven results — without
    # re-prompting the VLM.  Runs after validation + auto-fit so the baked
    # exposure is what gets serialized.
    if presets is not None:
        try:
            import tempfile

            _bake_dir = Path(tempfile.mkdtemp(prefix="dtstylekit_bake_"))
            validated_spec = _safety_bake(
                validated_spec,
                presets,
                image_path,
                reference_analysis,
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

    if capture_raw:
        return validated_spec, report, warnings, analysis, (  # type: ignore[return-value]
            raw_capture[-1] if raw_capture else ""
        )
    return validated_spec, report, warnings, analysis


def _safety_bake(
    spec: StyleSpec,
    presets: list,
    target_path: str | Path,
    reference_analysis: dict | None,
    work_dir: str | Path,
) -> StyleSpec:
    """Deterministically ensure the assembled style is not crushed.

    Renders the style on the *target* image and, while the result is crushed
    (or well below the reference brightness), lifts exposure (re-packing the
    ``exposure`` IOP) and re-renders.  Purely numerical — no VLM call.
    """
    import math

    from dtstylekit.codec.iop_registry import pack_params
    from dtstylekit.codec.xmp_codec import encode_xmp
    from dtstylekit.composer.generator import generate_dtstyle
    from dtstylekit.composer.merger import ComposerPlugin
    from dtstylekit.vlm.iterative_refiner import compute_render_metrics, render_with_style

    # Selected baseline presets (those the spec references).
    selected = [
        p
        for p in presets
        if getattr(getattr(p, "file_path", None), "name", "") in (spec.selected_preset_names or [])
    ]

    ref_lum = reference_analysis.get("global_luminance") if reference_analysis else None
    if isinstance(ref_lum, int | float) and not isinstance(ref_lum, bool) and float(ref_lum) > 0.05:
        target_safe = max(0.18, min(0.5, float(ref_lum) * 0.9))
    else:
        target_safe = 0.20

    tmp = Path(work_dir) / "_bake.dtstyle"
    for attempt in range(6):
        generate_dtstyle(spec, selected, tmp, None)
        ach = render_with_style(target_path, tmp, "bake", work_dir)
        if ach is None:
            break
        m = compute_render_metrics(ach)
        lum = m.mean_luminance
        crushed = lum < 0.12
        too_dark = bool(ref_lum) and lum < float(ref_lum) * 0.6
        if not crushed and not too_dark:
            if attempt:
                logger.info("Safety bake: style safe after %d nudge(s) (lum=%.3f)", attempt, lum)
            break
        needed = max(target_safe, float(ref_lum) * 0.9 if ref_lum else 0.20)
        delta = max(-1.5, min(1.5, math.log2(needed / max(lum, 1e-3))))
        exp = next((p for p in spec.plugins if p.operation == "exposure"), None)
        if exp is None:
            blob = pack_params("exposure", {"exposure": 0.0})
            exp = ComposerPlugin(
                operation="exposure",
                enabled=True,
                multi_name="",
                multi_priority=0,
                params={"exposure": 0.0},
                op_params=encode_xmp(blob),
                blendop_params="",
                blendop_version=13,
                module=0,
            )
            spec.plugins.append(exp)
        cur = float(exp.params.get("exposure") or 0.0)
        new = max(-4.0, min(4.0, cur + delta))
        if abs(new - cur) < 0.02:
            # Exposure already maxed; try softening the sigmoid contrast instead.
            sig = next((p for p in spec.plugins if p.operation == "sigmoid"), None)
            if sig is not None:
                c = float(sig.params.get("middle_grey_contrast", 2.0))
                sig.params["middle_grey_contrast"] = max(0.8, c - 0.3)
                try:
                    sig.op_params = encode_xmp(
                        pack_params("sigmoid", {"middle_grey_contrast": sig.params["middle_grey_contrast"], "contrast_skewness": 0.0})
                    )
                except Exception:
                    pass
                logger.info("Safety bake: softened sigmoid contrast to %.2f", sig.params["middle_grey_contrast"])
                continue
            break
        blob = pack_params("exposure", {"exposure": new})
        exp.params["exposure"] = new
        exp.op_params = encode_xmp(blob)
        logger.info("Safety bake: exposure %+.2f -> %+.2f EV (lum=%.3f)", cur, new, lum)
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
