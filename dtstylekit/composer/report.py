"""Generate markdown reports explaining the generated style."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.vlm.models import StyleSpec


def generate_report(
    spec: StyleSpec,
    presets: list,
    analysis: ImageAnalysis | None,
    vlm_report: str,
    output_path: Path,
) -> Path:
    """Generate a markdown report.

    Args:
        spec: Validated StyleSpec.
        presets: Selected presets.
        analysis: ImageAnalysis from analyzer pipeline.
        vlm_report: Free-form markdown from VLM "---REPORT---" section.
        output_path: Destination path.

    Returns:
        Path to written report.
    """
    lines: list[str] = []
    lines.append(f"# Style Report: {spec.style_name}")
    lines.append("")
    lines.append(f"*Generated: {datetime.now().isoformat()}*")
    lines.append("")

    if spec.style_description:
        lines.append(f"**Description**: {spec.style_description}")
        lines.append("")

    # Image Analysis Summary
    if analysis is not None:
        lines.append("## Image Analysis")
        lines.append("")
        prompt_dict = analysis.to_prompt_dict()
        dims = prompt_dict.get("dimensions", {})
        lines.append(
            f"- **Dimensions**: {dims.get('w', '?')} × {dims.get('h', '?')} ({dims.get('format', '?')})"
        )
        lum = prompt_dict.get("luminance", {})
        lines.append(f"- **Mean luminance**: {lum.get('mean', 0):.2f}")
        lines.append(f"- **Std luminance**: {lum.get('std', 0):.2f}")
        lines.append(f"- **Saturation**: {lum.get('saturation', 0):.2f}")
        tonal = lum.get("tonal", [0, 0, 0])
        lines.append(
            f"- **Tonal distribution**: shadows={tonal[0]:.2%}, midtones={tonal[1]:.2%}, highlights={tonal[2]:.2%}"
        )
        tags = prompt_dict.get("scene_tags") or []
        if tags:
            lines.append(f"- **Scene tags**: {', '.join(tags)}")
        noise = prompt_dict.get("noise", 0)
        lines.append(f"- **Noise estimate**: {noise}")
        lines.append("")

    # Presets used
    lines.append("## Base Presets")
    lines.append("")
    # Lazy import keeps report.py independent of parser if a caller
    # passes a bare Preset with only file_path set.
    from dtstylekit.presets.models import clean_description, derive_display_name

    if presets:
        for p in presets:
            ops = sorted({plg.operation for plg in p.plugins if plg.enabled})
            file_label = ""
            try:
                file_label = p.file_path.name if p.file_path else ""
            except AttributeError:
                file_label = ""
            display = derive_display_name(getattr(p, "name", "") or "") or file_label or "(unnamed)"
            lines.append(f"- **{file_label or display}** — {display}")
            if ops:
                lines.append(f"  - IOPs: {', '.join(ops)}")
            desc = clean_description(getattr(p, "description", "") or "")
            if desc:
                lines.append(f"  - {desc[:120]}")
        lines.append("")
    else:
        lines.append("- (no base presets — pure from-scratch)")
        lines.append("")

    # Adjustments
    lines.append("## Adjustments Applied")
    lines.append("")
    if spec.plugins:
        for plg in spec.plugins:
            lines.append(f"### `{plg.operation}`")
            if plg.multi_name:
                lines.append(f"*Instance: `{plg.multi_name}`*")
            lines.append("")
            if plg.params:
                lines.append("| Field | Value |")
                lines.append("|-------|-------|")
                for fld, val in plg.params.items():
                    lines.append(f"| {fld} | {val} |")
                lines.append("")
    else:
        lines.append("(no scalar adjustments)")
        lines.append("")

    # VLM Rationale
    lines.append("## VLM Rationale")
    lines.append("")
    if vlm_report:
        lines.append(vlm_report)
        lines.append("")
    elif getattr(spec, "rationale", ""):
        lines.append(spec.rationale)
        lines.append("")
    else:
        lines.append("(no VLM rationale provided)")
        lines.append("")

    # How to import
    lines.append("## How to Import")
    lines.append("")
    lines.append("1. Open Darktable")
    lines.append("2. Go to **Modules → Styles → Import**")
    lines.append("3. Select the generated `.dtstyle` file")
    lines.append("4. Apply from the styles sidebar")
    lines.append("")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
