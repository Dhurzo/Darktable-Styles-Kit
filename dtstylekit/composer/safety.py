"""Clipping-only safety bake for generated styles.

A ``.dtstyle`` is a reusable look, not an exposure correction for one
photo.  The bake only lowers exposure when the freshly generated style
clips highlights on the target image; brightness normalisation belongs to
``dtstylekit apply`` and is intentionally not baked into the style.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path

from dtstylekit.presets.models import Preset
from dtstylekit.vlm.models import Plugin, StyleSpec

logger = logging.getLogger(__name__)


def _selected_presets(spec: StyleSpec, presets: list[Preset]) -> list[Preset]:
    """Filter candidate presets by the names the VLM selected.

    Names may be filenames (``examples_colors_sepia.dtstyle``), stems,
    i18n names, or derived display names (``sepia``).  Returning the
    caller-supplied objects keeps already-resolved presets intact.
    """
    from dtstylekit.presets.models import derive_display_name

    names = set(spec.selected_preset_names or [])
    if not names:
        return []
    selected: list[Preset] = []
    for preset in presets:
        path = Path(preset.file_path)
        identities = {
            path.name,
            path.stem,
            preset.name,
            derive_display_name(preset.name),
        }
        if identities & names:
            selected.append(preset)
    return selected


def safety_bake(
    spec: StyleSpec,
    presets: list[Preset],
    target_path: str | Path,
    work_dir: str | Path,
) -> StyleSpec:
    """Lower exposure until the style no longer clips highlights.

    ``presets`` should be the full presets selected by the spec (not the
    entire search candidate list).  The function is a no-op when none of
    the names can be matched, but still renders the scalar adjustments.
    """
    from dtstylekit.composer.generator import generate_dtstyle
    from dtstylekit.render import compute_render_metrics, render_with_style

    selected = _selected_presets(spec, presets)

    target = Path(target_path)
    work = Path(work_dir)
    tmp = work / "_bake.dtstyle"
    max_clip = 0.01
    for attempt in range(4):
        generate_dtstyle(spec, selected, tmp, None)
        ach = render_with_style(target, tmp, "bake", work)
        if ach is None:
            break
        metrics = compute_render_metrics(ach)
        if metrics.clipped_pct <= max_clip:
            if attempt:
                logger.info(
                    "Safety bake: highlights safe after %d nudge(s) (clipped=%.1f%%, lum=%.3f)",
                    attempt,
                    metrics.clipped_pct * 100.0,
                    metrics.mean_luminance,
                )
            break
        exp = next((p for p in spec.plugins if p.operation == "exposure"), None)
        if exp is None:
            exp = Plugin(operation="exposure", enabled=True, params={"exposure": 0.0})
            spec = replace(spec, plugins=(*spec.plugins, exp))
        current = float(exp.params.get("exposure") or 0.0)
        step = min(1.5, max(0.25, math.log2(max(metrics.clipped_pct / max_clip, 1.0001))))
        new = max(-6.0, min(6.0, current - step))
        logger.info(
            "Safety bake: clipped=%.1f%% -> exposure %+.2f -> %+.2f EV",
            metrics.clipped_pct * 100.0,
            current,
            new,
        )
        if abs(new - current) < 0.02:
            break
        exp.params["exposure"] = new
    else:
        logger.warning(
            "Safety bake: highlights still clipped after 4 attempts; "
            "the exporter will clamp exposure per image"
        )
    return spec
