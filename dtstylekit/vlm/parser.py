"""Parse VLM responses into StyleSpec and report.

Handles JSON extraction from ```json``` fences or raw JSON, plus
extraction of the ---REPORT--- markdown section.

qwen3-vl:8b (and other "thinking" models) prefix the actual answer
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


def _first_valid_object_span(text: str) -> dict | None:
    """Find the FIRST balanced ``{...}`` span (topmost scope) that parses.

    Iterates ``{`` positions from the LEFT so we prefer the outermost
    JSON object over inner sub-objects.  This matters when the model
    emits a fenced or bare dict whose values themselves contain nested
    dicts — e.g.::

        {"adjustments": {"exposure": {"exposure": 5.0}}}

    The outermost ``{`` is the whole spec; the innermost ``{`` is just
    ``{"exposure": 5.0}``.  We want the spec.

    Each candidate's closing brace is located by scanning forward with
    string-literal awareness (so braces inside strings don't confuse
    the matcher).  Returns the parsed dict or ``None``.
    """
    open_positions = [m.start() for m in re.finditer(r"\{", text)]
    for start in open_positions:
        end = _find_matching_brace(text, start)
        if end is None:
            continue
        candidate = text[start:end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


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


def _build_style_spec(data: dict) -> StyleSpec:
    """Build a StyleSpec from parsed JSON."""
    plugins: list[Plugin] = []

    # New format: {"adjustments": {op: params}}
    adjustments = data.get("adjustments") or {}
    for op, params in adjustments.items():
        if not isinstance(params, dict):
            continue
        plugins.append(
            Plugin(
                operation=op,
                enabled=True,
                multi_name="",
                multi_priority=0,
                params={k: float(v) for k, v in params.items() if isinstance(v, (int, float))},
            )
        )

    # Old format: {"plugins": [{operation, enabled, multi_name, params: {...}}]}
    for p in data.get("plugins") or []:
        if not isinstance(p, dict):
            continue
        op = p.get("operation")
        if not op:
            continue
        params = p.get("params") or {}
        plugins.append(
            Plugin(
                operation=op,
                enabled=bool(p.get("enabled", True)),
                multi_name=str(p.get("multi_name", "")),
                multi_priority=int(p.get("multi_priority", 0)),
                params={k: float(v) for k, v in params.items() if isinstance(v, (int, float))},
            )
        )

    return StyleSpec(
        style_name=str(data.get("style_name", "untitled")),
        style_description=str(data.get("style_description", "")),
        rationale=str(data.get("rationale", "")),
        iop_list=data.get("iop_list"),
        plugins=plugins,
        selected_preset_names=[
            str(name) for name in (data.get("selected_presets") or []) if name
        ],
    )
