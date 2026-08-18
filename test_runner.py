#!/usr/bin/env python3
"""Automated test runner for dtstylekit style generation.

Runs the full pipeline on a set of test images with different style directions.
Results are written to dtstylekit/test_outputs/ (gitignored).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

TEST_CASES: list[dict[str, Any]] = [
    {
        "image": "thumb_A14I7406.jpg",
        "direction": "dark moody cinematic architectural",
        "expected_modules": ["sigmoid", "exposure", "colorbalancergb"],
    },
    {
        "image": "thumb_AE7A8477.jpg",
        "direction": "high contrast night photography cool tones moody",
        "expected_modules": ["sigmoid", "exposure", "colorbalancergb"],
    },
    {
        "image": "thumb_UPBUNDLE.jpg",
        "direction": "landscape photography vibrant natural colors",
        "expected_modules": ["sigmoid", "colorbalancergb"],
    },
    {
        "image": "thumb_AE7A8490-2.jpg",
        "direction": "portrait warm golden hour skin tones",
        "expected_modules": ["sigmoid", "colorbalancergb"],
    },
    {
        "image": "thumb_Oct1042.jpg",
        "direction": "vintage film look faded muted colors",
        "expected_modules": ["sigmoid", "colorbalancergb", "tonecurve"],
    },
    {
        "image": "thumb_Photo202012.jpg",
        "direction": "black and white high contrast fine art",
        "expected_modules": ["sigmoid", "exposure", "colorbalancergb"],
    },
]


def run_generation(image: str, direction: str, output_dir: Path) -> tuple[bool, str, Path | None]:
    """Run dtstylekit generate on a single image."""
    cmd = [
        sys.executable,
        "-m",
        "dtstylekit.cli",
        "generate",
        str(Path("test_data") / image),
        "--direction",
        direction,
        "--model",
        "gemma3:12b",
        "--output",
        str(output_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            # Find the generated .dtstyle file
            dtstyle_files = list(output_dir.glob("*.dtstyle"))
            if dtstyle_files:
                return True, result.stdout, dtstyle_files[0]
            return False, "No .dtstyle file generated", None
        return False, result.stderr, None
    except subprocess.TimeoutExpired:
        return False, "Timeout after 300s", None
    except Exception as e:
        return False, str(e), None


def check_style(dtstyle_path: Path, expected_modules: list[str]) -> tuple[bool, list[str]]:
    """Verify the generated style has expected modules."""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(dtstyle_path)
        root = tree.getroot()
        operations = []
        for plugin in root.findall(".//plugin"):
            op = plugin.find("operation")
            if op is not None:
                operations.append(op.text)

        missing = [m for m in expected_modules if m not in operations]
        extra = [o for o in operations if o not in expected_modules]

        return len(missing) == 0, missing + [f"unexpected: {e}" for e in extra]
    except Exception as e:
        return False, [f"Parse error: {e}"]


def main() -> int:
    test_dir = Path(__file__).parent / "test_data"
    output_base = Path(__file__).parent / "test_outputs"

    if not test_dir.exists():
        print(f"ERROR: Test data directory not found: {test_dir}")
        return 1

    output_base.mkdir(parents=True, exist_ok=True)

    results = []
    for i, case in enumerate(TEST_CASES):
        print(f"\n{'=' * 60}")
        print(f"Test {i + 1}/{len(TEST_CASES)}: {case['image']} -> {case['direction']}")
        print(f"{'=' * 60}")

        output_dir = output_base / f"test_{i + 1}_{Path(case['image']).stem}"
        output_dir.mkdir(parents=True, exist_ok=True)

        success, output, dtstyle_path = run_generation(case["image"], case["direction"], output_dir)

        if success and dtstyle_path:
            print(f"✓ Generation succeeded: {dtstyle_path.name}")
            modules_ok, issues = check_style(dtstyle_path, case["expected_modules"])
            if modules_ok:
                print(f"✓ All expected modules present: {case['expected_modules']}")
            else:
                print(f"⚠ Module issues: {issues}")

            # Also check the report
            report_path = dtstyle_path.with_suffix(".md")
            if report_path.exists():
                print(f"✓ Report generated: {report_path.name}")

            results.append(
                {
                    "test": i + 1,
                    "image": case["image"],
                    "direction": case["direction"],
                    "success": True,
                    "modules_ok": modules_ok,
                    "issues": issues,
                    "dtstyle": str(dtstyle_path),
                }
            )
        else:
            print(f"✗ Generation failed: {output}")
            results.append(
                {
                    "test": i + 1,
                    "image": case["image"],
                    "direction": case["direction"],
                    "success": False,
                    "error": output,
                }
            )

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    passed = sum(1 for r in results if r.get("success", False))
    total = len(results)
    print(f"Passed: {passed}/{total}")

    for r in results:
        status = "✓" if r.get("success", False) else "✗"
        print(f"  {status} Test {r['test']}: {r['image']}")

    # Save results JSON
    results_path = output_base / "test_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {results_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
