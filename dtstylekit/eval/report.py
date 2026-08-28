"""Aggregate eval results into a human-readable report."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .harness import EvalResult


def build_report(results: list[EvalResult]) -> str:
    """Render a markdown report covering every category x style cell.

    Computes per-category mean look-fidelity and intent-preservation so gaps
    ("valid for every type of reference picture and style") are visible at a
    glance, then lists the worst offenders.
    """
    if not results:
        return "# Eval Report\n\nNo results.\n"

    # Per-category aggregates.
    cat_scores: dict[str, list[float]] = defaultdict(list)
    cat_intent: dict[str, list[float]] = defaultdict(list)
    valid_count = 0

    for r in results:
        if r.valid:
            valid_count += 1
        tags = set(r.case.tags) | set(r.case.ref_tags)
        # Drop non-category tags for the matrix.
        cat_tags = {t for t in tags if t in {
            "raw", "display_referred", "portrait", "landscape", "low_key",
            "high_key", "monochrome", "colorful", "no_reference", "synthetic",
        }}
        if not cat_tags:
            cat_tags = {"uncategorised"}
        for t in cat_tags:
            if r.fidelity is not None:
                cat_scores[t].append(r.fidelity.overall)
            if r.intent_loss is not None:
                cat_intent[t].append(r.intent_loss.pct_preserved)

    lines: list[str] = []
    lines.append("# dtstylekit — VLM→Preset Evaluation Report\n")
    lines.append(
        f"- Cases evaluated: **{len(results)}**  "
        f"Valid `.dtstyle`: **{valid_count}/{len(results)}** "
        f"({100 * valid_count / max(len(results), 1):.0f}%)  "
        f"With look-fidelity: **{sum(1 for r in results if r.fidelity)}**\n"
    )

    lines.append("## Per-category look fidelity (mean overall score, 0–1)\n")
    lines.append("| Category | Cases scored | Mean fidelity | Mean intent preserved |")
    lines.append("|---|---|---|---|")
    for cat in sorted(cat_scores):
        scores = cat_scores[cat]
        intents = cat_intent.get(cat, [])
        mean_f = sum(scores) / len(scores) if scores else float("nan")
        mean_i = sum(intents) / len(intents) if intents else float("nan")
        lines.append(
            f"| {cat} | {len(scores)} | "
            f"{mean_f:.2f} | {mean_i:.2f} |"
        )

    # Worst offenders.
    scored = [r for r in results if r.fidelity is not None]
    scored.sort(key=lambda r: r.fidelity.overall if r.fidelity is not None else 0.0)
    lines.append("\n## Worst look-fidelity cases\n")
    if scored:
        lines.append("| Case | Tags | Overall | Hue | Chroma | Intent kept |")
        lines.append("|---|---|---|---|---|---|")
        for r in scored[:15]:
            f = r.fidelity
            if f is None:
                continue
            tag_str = ",".join(sorted(r.case.tags | r.case.ref_tags))[:40]
            intent = (
                f"{r.intent_loss.pct_preserved:.2f}"
                if r.intent_loss
                else "n/a"
            )
            lines.append(
                f"| {r.case.name} | {tag_str} | {f.overall:.2f} | "
                f"{f.hue_score:.2f} | {f.chroma_score:.2f} | {intent} |"
            )
    else:
        lines.append("_No cases had a reference look to score._")

    # Validity failures.
    invalid = [r for r in results if not r.valid]
    if invalid:
        lines.append("\n## Invalid `.dtstyle` outputs\n")
        for r in invalid:
            lines.append(f"- {r.case.name}: {'; '.join(r.notes) or 'unknown'}")

    return "\n".join(lines) + "\n"


def save_report(results: list[EvalResult], out_dir: Path) -> tuple[Path, Path]:
    """Write both a markdown and a JSON report; return (md_path, json_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = build_report(results)
    md_path = out_dir / "eval_report.md"
    md_path.write_text(md, encoding="utf-8")
    json_path = out_dir / "eval_results.json"
    json_path.write_text(
        json.dumps([r.to_dict() for r in results], indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path
