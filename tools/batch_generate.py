#!/usr/bin/env python3
"""Batch style generation: one style per RAW, each optimized for its exposure.

Usage:
    python tools/batch_generate.py \
        --raws /tmp/palander/raws/*.ARW /tmp/palander/raws/*.NEF \
        --references /tmp/palander/references/*.jpeg \
        --direction "Palander editorial fashion look..." \
        --output /tmp/palander/outputs \
        --model gemma3:27b \
        --refine-iterations 3
"""

from __future__ import annotations

import argparse
import base64
import logging
import sys
import subprocess
import tempfile
from pathlib import Path

from dtstylekit.analyzer.pipeline import analyze_image
from dtstylekit.codec.iop_registry import IOP_REGISTRY
from dtstylekit.composer.generator import generate_dtstyle
from dtstylekit.composer.report import generate_report
from dtstylekit.paths import get_outputs_dir
from dtstylekit.presets.search import PresetSearcher
from dtstylekit.vlm.iterative_refiner import (
    iterative_refine, compute_render_metrics, evaluate_metrics,
    render_with_style, _import_style_into_library,
)
from dtstylekit.vlm.orchestrator import generate_style_spec
from dtstylekit.vlm.models import StyleSpec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def export_preview(raw_path: Path, out_dir: Path, width: int = 1600) -> Path | None:
    """Export a preview JPEG from RAW using darktable-cli."""
    out_tif = out_dir / f"{raw_path.stem}_preview.tif"
    out_jpg = out_dir / f"{raw_path.stem}_preview.jpg"

    # Clean any existing
    for p in (out_tif, out_jpg, out_dir / f"{out_tif.stem}_01.tif", out_dir / f"{out_jpg.stem}_01.jpg"):
        if p.exists():
            p.unlink()

    # Export TIFF
    result = subprocess.run(
        ["darktable-cli", str(raw_path), str(out_tif), "--width", str(width)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not out_tif.exists():
        # Check for _01 suffix
        actual = list(out_dir.glob(f"{raw_path.stem}_preview*.tif"))
        if not actual:
            logger.error("Failed to export preview for %s: %s", raw_path, result.stderr)
            return None
        out_tif = actual[0]

    # Convert to JPEG
    result = subprocess.run(
        ["convert", str(out_tif), str(out_jpg)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not out_jpg.exists():
        logger.error("Failed to convert preview for %s: %s", raw_path, result.stderr)
        return None

    logger.info("Exported preview: %s", out_jpg)
    return out_jpg


def generate_style_with_refiner(
    raw_path: Path,
    preview_path: Path,
    references: list[Path],
    direction: str,
    searcher: PresetSearcher,
    model: str | None,
    max_iterations: int,
    output_dir: Path,
) -> tuple[Path, Path] | tuple[None, None]:
    """Generate style for a single RAW using iterative refinement."""
    logger.info("=" * 60)
    logger.info("Processing: %s", raw_path.name)
    logger.info("Preview:  %s", preview_path.name)

    # Analyze the PREVIEW (for VLM input) - this is what the VLM sees
    preview_analysis = analyze_image(preview_path)

    # Analyze the REFERENCE aggregate (target look)
    # We'll use the first reference as representative
    ref_analysis = analyze_image(references[0]) if references else preview_analysis

    # Encode references for VLM
    ref_b64s = [base64.b64encode(p.read_bytes()).decode("ascii") for p in references]

    def generate_func(current_direction: str, ref_b64s_local: list[str]) -> StyleSpec:
        """Inner function to generate a style spec for the refiner."""
        spec, vlm_report, vlm_warnings, _ = generate_style_spec(
            image_path=preview_path,
            direction=current_direction,
            searcher=searcher,
            analyzer=analyze_image,
            registry=IOP_REGISTRY,
            model=model,
            references=references,
        )
        return spec

    # Run iterative refinement
    logger.info("Starting iterative refinement (%d iterations)...", max_iterations)
    with tempfile.TemporaryDirectory(prefix=f"dtstylekit_refine_{raw_path.stem}_") as tmp:
        work_dir = Path(tmp)
        refined_spec = iterative_refine(
            raw_path=raw_path,
            reference_paths=references,
            direction=direction,
            target_analysis=ref_analysis,
            generate_func=generate_func,
            max_iterations=max_iterations,
            work_dir=work_dir,
        )

    # Load selected presets (will be empty for adjustments-only)
    all_warnings: list[str] = []
    from dtstylekit.cli import _load_selected_presets
    selected_presets = _load_selected_presets(refined_spec, all_warnings)

    # Generate final .dtstyle + report
    dtstyle_path = output_dir / f"{refined_spec.style_name.replace(' ', '_')}_{raw_path.stem}.dtstyle"
    report_path = output_dir / f"{refined_spec.style_name.replace(' ', '_')}_{raw_path.stem}.md"

    try:
        generate_dtstyle(refined_spec, selected_presets, dtstyle_path, preview_analysis)
    except Exception as exc:
        logger.error("Style generation failed for %s: %s", raw_path, exc)
        return None, None

    try:
        generate_report(refined_spec, selected_presets, preview_analysis, "", report_path)
    except Exception as exc:
        all_warnings.append(f"Report generation failed: {exc}")
        logger.warning("Report generation failed for %s: %s", raw_path, exc)

    logger.info("Generated: %s", dtstyle_path)
    if all_warnings:
        for w in all_warnings:
            logger.warning("  %s", w)

    return dtstyle_path, report_path


def apply_style_to_raw(
    raw_path: Path,
    style_path: Path,
    style_name: str,
    output_dir: Path,
    width: int = 2400,
) -> Path | None:
    """Apply style to RAW using isolated darktable library."""
    import tempfile
    import shutil
    import xml.etree.ElementTree as ET
    from dtstylekit.codec.xmp_codec import decode_xmp

    out_path = output_dir / f"{raw_path.stem}_{style_name.replace(' ', '_')}.jpg"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        env = {
            "HOME": str(work),
            "XDG_CONFIG_HOME": str(work / "cfg"),
            "XDG_DATA_HOME": str(work / "data"),
        }

        # 1. Baseline export (creates library)
        baseline = work / "baseline.jpg"
        result = subprocess.run(
            ["darktable-cli", str(raw_path), str(baseline), "--width", str(width)],
            env=env,
            capture_output=True,
            timeout=180,
        )
        if result.returncode != 0:
            logger.error("Baseline export failed for %s: %s", raw_path, result.stderr.decode())
            return None

        # 2. Import style into library
        dbs = sorted((work / "cfg" / "darktable").glob("*.db"))
        if not dbs:
            logger.error("No darktable library database found")
            return None
        db_path = dbs[0]

        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()

            def _exists(name: str) -> bool:
                return cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
                ).fetchone() is not None

            styles_tbl = "data.styles" if _exists("data.styles") else "styles"
            items_tbl = "data.style_items" if _exists("data.style_items") else "style_items"

            style_id = cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {styles_tbl}").fetchone()[0]
            cur.execute(
                f"INSERT INTO {styles_tbl} (id, name, description, iop_list) VALUES (?, ?, '', NULL)",
                (style_id, style_name),
            )

            root = ET.parse(style_path).getroot()
            for plugin in root.findall("style/plugin"):
                op_enc = plugin.findtext("op_params", "") or ""
                bl_enc = plugin.findtext("blendop_params", "") or ""
                cur.execute(
                    f"INSERT INTO {items_tbl} "
                    " (styleid, num, module, operation, op_params, enabled,"
                    "  blendop_params, blendop_version, multi_priority,"
                    "  multi_name, multi_name_hand_edited)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        style_id,
                        int(plugin.findtext("num", "0") or 0),
                        int(plugin.findtext("module", "0") or 0),
                        plugin.findtext("operation", "") or "",
                        decode_xmp(op_enc) if op_enc else b"",
                        int(plugin.findtext("enabled", "1") or 1),
                        decode_xmp(bl_enc) if bl_enc else b"",
                        int(plugin.findtext("blendop_version", "13") or 13),
                        int(plugin.findtext("multi_priority", "0") or 0),
                        plugin.findtext("multi_name", "") or "",
                        int(plugin.findtext("multi_name_hand_edited", "0") or 0),
                    ),
                )
            conn.commit()
            logger.info("Style '%s' registered in isolated library", style_name)
        finally:
            conn.close()

        # 3. Export with style
        result = subprocess.run(
            ["darktable-cli", str(raw_path), str(out_path), "--width", str(width), "--style", style_name],
            env=env,
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error("Styled export failed for %s: %s", raw_path, result.stderr.decode())
            return None

        # darktable-cli doesn't overwrite - find actual output
        actual = list(output_dir.glob(f"{out_path.stem}*.jpg"))
        if not actual:
            logger.error("No output file found after styled export")
            return None

        final_path = max(actual, key=lambda p: p.stat().st_mtime)
        if final_path != out_path:
            final_path.rename(out_path)
            final_path = out_path

        logger.info("Styled export: %s", final_path)
        return final_path


def main():
    parser = argparse.ArgumentParser(description="Batch generate styles for multiple RAWs with iterative refinement")
    parser.add_argument("--raws", nargs="+", required=True, help="RAW files to process")
    parser.add_argument("--references", nargs="+", required=True, help="Reference images (Palander samples)")
    parser.add_argument("--direction", required=True, help="Style direction text")
    parser.add_argument("--model", default="gemma3:27b", help="VLM model")
    parser.add_argument("--output", default="/tmp/palander/outputs", help="Output directory")
    parser.add_argument("--width", type=int, default=2400, help="Export width for final renders")
    parser.add_argument("--refine-iterations", type=int, default=3, help="Max refinement iterations per RAW")
    parser.add_argument("--skip-apply", action="store_true", help="Only generate styles, don't apply to RAWs")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve paths
    raw_paths = [Path(p).expanduser() for p in args.raws]
    ref_paths = [Path(p).expanduser() for p in args.references]

    # Validate
    for p in raw_paths:
        if not p.exists():
            logger.error("RAW not found: %s", p)
            return 1
    for p in ref_paths:
        if not p.exists():
            logger.error("Reference not found: %s", p)
            return 1

    # Build preset searcher
    outputs_dir = get_outputs_dir()
    db_path = outputs_dir / "presets.db"
    emb_path = outputs_dir / "preset_embeddings.npy"
    if not db_path.exists() or not emb_path.exists():
        logger.error("Preset index not built. Run: dtstylekit preset index")
        return 1

    searcher = PresetSearcher(db_path, emb_path)

    # Process each RAW
    results = []
    for raw_path in raw_paths:
        # Export preview
        preview_path = export_preview(raw_path, output_dir)
        if not preview_path:
            logger.error("Skipping %s - failed to export preview", raw_path)
            results.append((raw_path, None, None, None))
            continue

        # Generate style for this RAW using iterative refinement
        dtstyle_path, report_path = generate_style_with_refiner(
            raw_path=raw_path,
            preview_path=preview_path,
            references=ref_paths,
            direction=args.direction,
            searcher=searcher,
            model=args.model,
            max_iterations=args.refine_iterations,
            output_dir=output_dir,
        )

        if not dtstyle_path:
            results.append((raw_path, None, None, None))
            continue

        # Apply style if not skipped
        if not args.skip_apply:
            # Extract style name from XML
            import xml.etree.ElementTree as ET
            root = ET.parse(dtstyle_path).getroot()
            style_name = root.findtext("info/name", "").strip() or dtstyle_path.stem

            styled_path = apply_style_to_raw(
                raw_path=raw_path,
                style_path=dtstyle_path,
                style_name=style_name,
                output_dir=output_dir,
                width=args.width,
            )
            results.append((raw_path, dtstyle_path, report_path, styled_path))
        else:
            results.append((raw_path, dtstyle_path, report_path, None))

    # Summary
    logger.info("=" * 60)
    logger.info("BATCH GENERATION COMPLETE")
    logger.info("=" * 60)
    for raw_path, dtstyle_path, report_path, styled_path in results:
        status = "✓" if dtstyle_path else "✗"
        logger.info("%s %s -> style: %s, render: %s",
                    status, raw_path.name,
                    dtstyle_path.name if dtstyle_path else "FAILED",
                    styled_path.name if styled_path else ("SKIPPED" if args.skip_apply else "FAILED"))

    return 0


if __name__ == "__main__":
    sys.exit(main())