"""End-to-end VLM style spec generation.

Orchestrates: image analysis → preset search → prompt build → VLM call
→ response parse → validation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .client import VLMClient
from .models import encode_image_b64
from .parser import parse_response
from .prompt_builder import build_prompt
from .schema_renderer import render_iop_schema
from .validator import validate_style

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.models import Preset
    from .models import StyleSpec

logger = logging.getLogger(__name__)


def generate_style_spec(
    image_path: str | Path,
    direction: str,
    searcher,  # PresetSearcher
    analyzer,  # callable path -> ImageAnalysis
    registry: dict,
    model: str | None = None,
    temperature: float = 0.4,
) -> tuple["StyleSpec", str, list[str], "ImageAnalysis"]:
    """Generate a validated StyleSpec for a given image.

    Args:
        image_path: Path to JPEG/TIFF image.
        direction: User style direction string.
        searcher: PresetSearcher instance.
        analyzer: Callable taking image_path -> ImageAnalysis.
        registry: IOP_REGISTRY dict.
        model: VLM model override.
        temperature: Sampling temperature.

    Returns:
        (validated_spec, vlm_report, warnings, image_analysis) tuple.
    """
    # 1. Analyze image
    logger.info("Analyzing %s", image_path)
    analysis = analyzer(image_path)

    # 2. Search presets
    logger.info("Searching presets for direction: %s", direction)
    search_results = searcher.hybrid_search(direction, limit=5)

    # 2b. Resolve each SearchResult (lightweight PresetIndexEntry) back to a
    # full Preset (with plugins / op_params / blendops / filename) by
    # re-parsing the .dtstyle file from disk. The indexer persists the
    # absolute file_path for exactly this case.
    presets: list["Preset"] = []
    for r in search_results:
        file_path = getattr(r.preset, "file_path", None)
        if not file_path:
            logger.warning(
                "SearchResult for %r has no file_path — cannot resolve full Preset",
                getattr(r.preset, "display_name", None) or r.preset.name,
            )
            continue
        from dtstylekit.presets.parser import parse_preset
        from pathlib import Path

        full = parse_preset(Path(file_path))
        if full is not None:
            presets.append(full)
        else:
            logger.warning("Could not re-parse preset file: %s", file_path)

    # 3. Build schema
    schema = render_iop_schema(registry)

    # 4. Optionally encode image for VLM vision
    try:
        image_b64 = encode_image_b64(image_path)
    except Exception as e:
        logger.warning("Could not encode image: %s", e)
        image_b64 = None

    # 5. Build prompt
    messages = build_prompt(analysis, presets, direction, schema, image_b64)

    # 6. Call VLM.  qwen3-vl:8b at ~2.5 tok/s on CPU; num_predict=8000
    #    leaves headroom for thinking-mode budget (which counts against
    #    num_predict) plus the final JSON.  think=True lets the model
    #    reason in `message.thinking` and emit the clean JSON in
    #    `message.content`.  The client falls back to `thinking` when
    #    `content` is empty (qwen3-vl sometimes does this).
    logger.info("Calling VLM...")
    client = VLMClient()
    response_text = client.generate(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=8000,
        num_ctx=8192,
        think=True,
        json_mode=False,
    )

    # 7. Parse response
    spec, report = parse_response(response_text)

    # 8. Validate
    validated_spec, warnings = validate_style(spec, registry)
    for w in warnings:
        logger.warning(w)

    return validated_spec, report, warnings, analysis
