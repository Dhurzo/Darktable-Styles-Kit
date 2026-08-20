"""Render compact IOP schema for VLM prompts.

Produces a markdown-formatted table of the most-used IOPs with their
key parameters and ranges, optimized for token efficiency.  Curve-based
IOPs get a separate template catalogue so the VLM can pick by name
instead of trying to write spline coordinates by hand.
"""

from __future__ import annotations

_CURVE_OPERATIONS = ("colorzones", "rgbcurve", "tonecurve")


def render_iop_schema(registry: dict, max_iops: int = 16) -> str:
    """Render a compact IOP schema as markdown.

    Args:
        registry: Dict mapping operation name -> IOPRegistry dataclass.
        max_iops: Maximum number of IOPs to include (keeps prompt small).

    Returns:
        Markdown-formatted string describing key IOPs *and* the curve
        template catalogue.
    """
    lines = ["## Available IOPs", ""]

    # Prioritize verified (scene-referred) IOPs first
    verified = ["filmicrgb", "colorbalancergb", "sigmoid", "exposure", "atrous"]
    # Curve-based IOPs come AFTER the simple scalar ones — they're less
    # commonly used but extremely powerful.
    curve_ops = list(_CURVE_OPERATIONS)
    other_simple = [
        "vibrance",
        "velvia",
        "grain",
        "bloom",
        "soften",
        "highpass",
        "sharpen",
        "splittoning",
        "colorcontrast",
        "colisa",
        "monochrome",
        "vignette",
        "colorize",
        "colorbalance",
        "shadhi",
    ]
    # Refinement IOPs — fine tonal/color shaping on top of the
    # core pipeline.  temperature sits BEFORE exposure in the pipeline
    # (raw WB), toneequal after exposure, colorequal after filmicrgb,
    # colorharmonizer in RGB.  (relight is deprecated in darktable and
    # deliberately not registered.)
    refinement = [
        "temperature",
        "basicadj",
        "toneequal",
        "colorequal",
        "colorharmonizer",
    ]

    included: list[str] = []
    for op in verified:
        if op in registry and len(included) < max_iops:
            included.append(op)
    for op in refinement:
        if op in registry and len(included) < max_iops:
            included.append(op)
    for op in other_simple:
        if op in registry and len(included) < max_iops:
            included.append(op)
    # Reserve two slots for curve IOPs (always include if available)
    for op in curve_ops:
        if op in registry and op not in included:
            included.append(op)

    for op in included:
        reg = registry[op]
        lines.append(f"### {op} (v{reg.version})")
        if getattr(reg, "is_curve_iop", False):
            lines.append(
                "**Curve-based IOP** — apply named templates via the "
                "`curve_preset` field (see template catalogue below)."
            )
            # Show scalar fields (skip the synthetic `curve_preset`)
            scalar_fields = [f for f in reg.fields if f != "curve_preset"]
            range_summary = ", ".join(f"{f}: {reg.ranges[f]}" for f in scalar_fields)
            lines.append(f"Scalars: {range_summary}")
        else:
            fields = list(reg.ranges.keys())[:8]
            range_summary = ", ".join(f"{f}: {reg.ranges[f]}" for f in fields)
            lines.append(f"Fields: {range_summary}")
        lines.append("")

    # Append the curve template catalogue (only if any curve IOPs exist
    # in the registry or the templates module is importable).
    try:
        from dtstylekit.curves import render_template_summary

        lines.append("---")
        lines.append("")
        lines.append("## Curve Templates")
        lines.append("")
        lines.append(
            "Pick a named template via the `curve_preset` field. Do NOT "
            "specify spline nodes directly."
        )
        lines.append("")
        lines.append(render_template_summary())
    except Exception:
        pass

    return "\n".join(lines)
