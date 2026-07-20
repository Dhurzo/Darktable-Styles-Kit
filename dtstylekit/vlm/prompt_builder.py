"""Build VLM prompts combining image analysis + preset candidates.

Constructs Ollama-format messages with system prompt, image analysis,
preset suggestions, and user style direction. Targets ≤6000 tokens total.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.models import Preset


SYSTEM_PROMPT = """You are a Darktable colorist. Emit ONLY a JSON object — no chain-of-thought, no preamble, no commentary. Think briefly (1-2 sentences max) then output the JSON.

Output: a single ```json``` fenced block exactly matching this schema:
```json
{
  "style_name": "short name",
  "style_description": "one-line",
  "selected_presets": ["preset_filename1.dtstyle"],
  "adjustments": {"filmicrgb": {"contrast": 1.4}},
  "rationale": "one short sentence"
}
```

Rules:
- `selected_presets`: pick 1-2 filenames, COPIED EXACTLY from [CANDIDATE PRESETS]. Never invent names.
- `adjustments`: only keys from [AVAILABLE IOPs]; values are {param: scalar} within declared ranges.
- Minimal changes on top of the selected presets.
- Irrelevant candidates: still pick the closest 2 and explain in `rationale`.
- Be concise. Do NOT reason step-by-step — output JSON immediately."""


def build_prompt(
    analysis: "ImageAnalysis",
    presets: list["Preset"],
    direction: str,
    iop_schema: str,
    image_b64: str | None = None,
) -> list[dict]:
    """Build Ollama messages list.

    Args:
        analysis: ImageAnalysis from analyzer pipeline.
        presets: List of relevant Preset objects from search.
        direction: User style direction (e.g., "cinematic warm portrait").
        iop_schema: Compact markdown schema of available IOPs.
        image_b64: Optional base64-encoded image for VLM.

    Returns:
        List of message dicts compatible with ollama.chat().
    """
    analysis_dict = analysis.to_prompt_dict()
    # Compact preset list (top 5)
    from dtstylekit.presets.models import clean_description, derive_display_name

    preset_summaries = []
    for p in presets[:5]:
        ops = [plg.operation for plg in p.plugins if plg.enabled]
        # The .dtstyle filename (e.g. "examples_colors_sepia.dtstyle").
        try:
            filename = p.file_path.name if p.file_path else (getattr(p, "name", "") or "")
        except AttributeError:
            filename = getattr(p, "name", "") or ""
        # Use the cleaned display name ("sepia", "faded") when available.
        display_name = derive_display_name(getattr(p, "name", "") or "") or filename
        description = clean_description(getattr(p, "description", "") or "") or "(no description)"
        preset_summaries.append({
            "filename": filename,
            "name": display_name,
            "description": description[:200],
            "operations": list(dict.fromkeys(ops))[:10],
        })

    user_content = f"""[STYLE DIRECTION]
{direction}

[IMAGE ANALYSIS]
```json
{json.dumps(analysis_dict, indent=2)}
```

[CANDIDATE PRESETS]
```json
{json.dumps(preset_summaries, indent=2)}
```

[AVAILABLE IOPs]
{iop_schema}

Now generate the style specification."""

    user_msg: dict = {"role": "user", "content": user_content}
    if image_b64:
        user_msg["images"] = [image_b64]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        user_msg,
    ]
