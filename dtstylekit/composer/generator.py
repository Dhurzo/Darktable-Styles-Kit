"""Generate final .dtstyle files."""

from __future__ import annotations

import logging
from pathlib import Path

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.codec.serializer import build_dtstyle_xml
from dtstylekit.presets.models import Preset
from dtstylekit.vlm.models import StyleSpec

from .merger import merge_presets

logger = logging.getLogger(__name__)


def generate_dtstyle(
    spec: StyleSpec,
    presets: list[Preset],
    output_path: Path,
    analysis: ImageAnalysis | None = None,
) -> Path:
    """Generate a `.dtstyle` file from a validated StyleSpec.

    Args:
        spec: Validated StyleSpec containing plugin adjustments.
        presets: Selected preset objects (used as base).
        output_path: Destination path (will be created).
        analysis: Optional ImageAnalysis for context reporting.

    Returns:
        Absolute path to the written .dtstyle file.
    """
    adjustments = {plg.operation: dict(plg.params) for plg in spec.plugins}
    # Dark display-referred images (mean luminance < 0.3) must not get a
    # fresh filmicrgb instance — see merger.merge_presets(dark_image=...).
    dark_image = False
    if analysis is not None:
        mean_lum = getattr(getattr(analysis, "luminance", None), "mean", None)
        if isinstance(mean_lum, int | float) and not isinstance(mean_lum, bool):
            dark_image = mean_lum < 0.3
    plugins = merge_presets(presets, adjustments, dark_image=dark_image)

    # Build XML-ready plugin dicts for the serializer.  We pass already-
    # packed ``op_params_override`` so the serializer doesn't re-pack
    # — this keeps curve-based IOPs (which the merger packs via the
    # curve templates subsystem) working even though they cannot be
    # re-packed by ``pack_params`` without a ``curve_preset``.
    xml_plugins: list[dict] = []
    for i, plg in enumerate(plugins):
        xml_plugins.append(
            {
                "num": i,
                "module": plg.module,
                "operation": plg.operation,
                "op_params_override": plg.op_params,
                "params": {},  # not used when override is supplied
                "enabled": 1 if plg.enabled else 0,
                "blendop_override": plg.blendop_params or None,
                "blendop_version": plg.blendop_version,
                "multi_priority": plg.multi_priority,
                "multi_name": plg.multi_name,
                "multi_name_hand_edited": plg.multi_name_hand_edited,
            }
        )

    # Filter out None overrides so the serializer picks defaults
    xml_plugins = [{k: v for k, v in p.items() if v is not None} for p in xml_plugins]

    xml_str = build_dtstyle_xml(
        name=spec.style_name,
        description=spec.style_description,
        plugins=xml_plugins,
        iop_list=spec.iop_list,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logger.info("Wrote %s", output_path)
    return output_path
