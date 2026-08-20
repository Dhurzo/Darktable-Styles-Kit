"""Parse VLM responses into StyleSpec and report.

Handles JSON extraction from ```json``` fences or raw JSON, plus
extraction of the ---REPORT--- markdown section.

gemma3:12b (and other "thinking" models) prefix the actual answer
with a chain-of-thought blob that often contains braces, which makes
naive ``\\{.*\\}`` greedy matching grab the wrong span.  This module
extracts JSON defensively:

* First try every ``` json fenced block (last one wins — the final
  fenced block is the model's answer, earlier ones tend to echo
  candidate input).
* Then iterate over candidate ``{...}`` spans from the END of the
  text backwards, attempting ``json.loads`` on each until one parses.
"""

from __future__ import annotations

import json
import re

from dtstylekit.codec.iop_registry import IOP_REGISTRY

from .models import Plugin, StyleSpec


def parse_response(text: str) -> tuple[StyleSpec, str]:
    """Parse VLM response.

    Args:
        text: Raw VLM response string.

    Returns:
        (StyleSpec, report_text) tuple.
    """
    data = _extract_json(text)
    if data is None:
        raise ValueError(f"No JSON found in VLM response: {text[:200]}...")

    # Extract ---REPORT--- section
    report_match = re.search(r"---REPORT---(.*)", text, re.DOTALL)
    report = report_match.group(1).strip() if report_match else ""

    spec = _build_style_spec(data)
    return spec, report


def _extract_json(text: str) -> dict | None:
    """Robustly extract a JSON object from a VLM response.

    Tries fenced ```` ```json ```` blocks first (last one wins), then
    falls back to scanning ``{...}`` spans from the end of the text
    backwards.  Returns ``None`` if no valid JSON object can be parsed.
    """
    # 1. Fenced ```json blocks.  findall gives us every match; the
    #    last fence is typically the model's final answer.
    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    for candidate in reversed(fenced):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # A fenced block may contain prose that quotes JSON; try to
            # find the first ``{...}`` span inside it.
            inner = _first_valid_object_span(candidate)
            if inner is not None:
                return inner

    # 2. Scan `{...}` spans from the end backwards.  ``re.finditer``
    #    with a non-greedy pattern gives us balanced-from-left spans
    #    (which is good enough — JSON allows nested objects, and the
    #    closest balanced span from the right is the most likely to be
    #    the actual answer after a thinking blob).
    return _first_valid_object_span(text)


_STYLE_SPEC_KEYS = (
    "style_name",
    "adjustments",
    "selected_presets",
    "rationale",
    "style_description",
)


def _first_valid_object_span(text: str) -> dict | None:
    """Find the most likely StyleSpec JSON object in ``text``.

    "Thinking" models (gemma3) put their chain-of-thought — including
    the image-analysis JSON and candidate-preset JSON we fed them — into
    the ``thinking`` field, and emit the *actual* answer object at the
    very end.  A naive "first balanced ``{...}``" scan therefore matches
    the embedded analysis JSON (which lacks style keys) and yields an
    empty spec.

    So we collect every balanced top-level dict, then prefer the LAST one
    whose keys look like a StyleSpec answer; only if none match do we fall
    back to the last dict overall.
    """
    open_positions = [m.start() for m in re.finditer(r"\{", text)]
    candidates: list[dict] = []
    for start in open_positions:
        end = _find_matching_brace(text, start)
        if end is None:
            continue
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    if not candidates:
        return None
    for parsed in reversed(candidates):
        if any(k in parsed for k in _STYLE_SPEC_KEYS):
            return parsed
    return candidates[-1]


def _find_matching_brace(text: str, start: int) -> int | None:
    """Return the index of the ``}`` that closes the ``{`` at ``start``.

    Handles nested braces and string literals (single/double quotes,
    with backslash escapes).  Returns ``None`` if unbalanced.
    """
    depth = 0
    in_string = False
    quote_char = ""
    i = start
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2  # skip escaped char
                continue
            if ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            quote_char = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


# Map generic photography terms the model tends to emit to the
# verified Darktable IOP / parameter names.  Without this, the validator
# drops unknown ops/params and the generated style ends up empty.
_GENERIC_PARAM_MAP: dict[str, tuple[str, str]] = {
    "exposure": ("exposure", "exposure"),
    "contrast": ("filmicrgb", "contrast"),
    "saturation": ("filmicrgb", "saturation"),
    "shadows": ("shadhi", "shadows"),
    "highlights": ("shadhi", "highlights"),
    "white_balance": ("colorbalancergb", "global_Y"),
    "temperature": ("colorbalancergb", "global_H"),
    "tint": ("colorbalancergb", "global_C"),
    "hue": ("colorbalancergb", "hue_angle"),
    "vibrance": ("colorbalancergb", "vibrance"),
    "clarity": ("sharpen", "amount"),
    "sharpness": ("sharpen", "amount"),
    "noise": ("filmicrgb", "noise_level"),
    "denoise": ("filmicrgb", "noise_level"),
    "latitude": ("filmicrgb", "latitude"),
    "grain": ("grain", "strength"),
    "vignette": ("vignette", "scale"),
    "bloom": ("bloom", "strength"),
    "soften": ("soften", "amount"),
    "brightness": ("exposure", "exposure"),
}

# When a known IOP is given a bare scalar (not a {param: value} dict),
# use this param name for it.
_PRIMARY_PARAM: dict[str, str] = {
    "exposure": "exposure",
    "sigmoid": "middle_grey_contrast",
    "atrous": "mix",
    "colorbalancergb": "contrast",
    "filmicrgb": "contrast",
    "vibrance": "amount",
    "sharpen": "amount",
    "velvia": "strength",
    "colisa": "contrast",
    "bloom": "strength",
    "grain": "strength",
    "vignette": "scale",
    "colorcontrast": "a_steepness",
    "levels": "black",
    "monochrome": "a",
    "colorize": "hue",
    "soften": "amount",
}


def _normalize_adjustments(adjustments: dict) -> dict[str, dict]:
    """Translate model ``adjustments`` into verified Darktable IOP params.

    Handles three input shapes:
      * ``{iop: {param: scalar, ...}}`` — valid op keys pass through.
      * ``{iop: scalar}`` — a known op with a bare value uses its primary
        param (e.g. ``exposure: 0.2`` → ``exposure.exposure``).
      * ``{generic_term: value}`` (or ``{generic_term: {sub: value}}``) —
        mapped via :data:`_GENERIC_PARAM_MAP` to the right IOP/param
        (e.g. ``shadows: 35`` → ``shadhi.shadows``;
        ``white_balance: {temperature: 3500}`` → ``colorbalancergb.global_H``).
    Unknown keys are dropped so the validator never sees a stray op.
    """
    result: dict[str, dict] = {}
    for key, val in adjustments.items():
        k = str(key).strip().lower()
        if k in IOP_REGISTRY:
            if isinstance(val, dict):
                for pk, pv in val.items():
                    if isinstance(pv, int | float):
                        result.setdefault(k, {})[pk] = float(pv)
            elif isinstance(val, int | float):
                param = _PRIMARY_PARAM.get(k)
                if param:
                    result.setdefault(k, {})[param] = float(val)
            continue
        if k in _GENERIC_PARAM_MAP:
            op, param = _GENERIC_PARAM_MAP[k]
            if isinstance(val, dict):
                for sub_k, sub_v in val.items():
                    if not isinstance(sub_v, int | float):
                        continue
                    sk = str(sub_k).strip().lower()
                    if sk in _GENERIC_PARAM_MAP:
                        sub_op, sub_param = _GENERIC_PARAM_MAP[sk]
                        result.setdefault(sub_op, {})[sub_param] = float(sub_v)
                    elif sk in IOP_REGISTRY[op].ranges:
                        result.setdefault(op, {})[sk] = float(sub_v)
            elif isinstance(val, int | float):
                result.setdefault(op, {})[param] = float(val)
            continue
        # Unknown key — skip silently (validator would drop it anyway).
    return result


def _build_style_spec(data: dict) -> StyleSpec:
    """Build a StyleSpec from parsed JSON."""
    plugins: list[Plugin] = []

    # New format: {"adjustments": {op: params}} — normalize generic
    # photography terms (e.g. "contrast", "shadows", "white_balance")
    # to the verified Darktable IOP/param names so the validator keeps
    # them instead of dropping unknown keys.
    adjustments = _normalize_adjustments(data.get("adjustments") or {})
    for op, params in adjustments.items():
        plugins.append(
            Plugin(
                operation=op,
                enabled=True,
                multi_name="",
                multi_priority=0,
                params={k: float(v) for k, v in params.items()},
            )
        )

    # Old format: {"plugins": [{operation, enabled, multi_name, params: {...}}]}
    for p in data.get("plugins") or []:
        if not isinstance(p, dict):
            continue
        op_name: str = str(p.get("operation", ""))
        if not op_name:
            continue
        params = p.get("params") or {}
        plugins.append(
            Plugin(
                operation=op_name,
                enabled=bool(p.get("enabled", True)),
                multi_name=str(p.get("multi_name", "")),
                multi_priority=int(p.get("multi_priority", 0)),
                params={k: float(v) for k, v in params.items() if isinstance(v, int | float)},
            )
        )

    return StyleSpec(
        style_name=str(data.get("style_name", "untitled")),
        style_description=str(data.get("style_description", "")),
        rationale=str(data.get("rationale", "")),
        iop_list=data.get("iop_list"),
        plugins=plugins,
        selected_preset_names=[str(name) for name in (data.get("selected_presets") or []) if name],
    )
