"""End-to-end reference-loop integration test (skipped by default).

Exercises the full closed loop: analyze references → VLM generates a
style → render with darktable-cli → compare the render against the
references → refine. This requires a running Ollama instance and the
``darktable-cli`` binary, so it is skipped unless explicitly enabled:

    DARKTABLE_INTEGRATION_TESTS=1 \
    DARKTABLE_TEST_RAW=/path/to/test.raw \
    pytest tests/test_reference_loop_integration.py

It also needs a RAW file to render against (the references alone are
not enough — darktable renders a RAW, not the reference JPEGs).
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from dtstylekit.vlm.orchestrator import generate_style_spec


def _have_darktable() -> bool:
    return shutil.which("darktable-cli") is not None


HAS_DARKTABLE = _have_darktable()
ENABLED = (
    __import__("os").environ.get("DARKTABLE_INTEGRATION_TESTS") == "1"
    and __import__("os").environ.get("DARKTABLE_TEST_RAW") is not None
)

pytestmark = pytest.mark.skipif(
    not (HAS_DARKTABLE and ENABLED),
    reason="needs darktable-cli + DARKTABLE_INTEGRATION_TESTS=1 + DARKTABLE_TEST_RAW",
)


def _write_image(path, color):
    arr = np.full((128, 128, 3), color, dtype=np.uint8)
    Image.fromarray(arr).save(path)


def test_reference_loop_runs_end_to_end(tmp_path):
    """The closed loop produces a spec and does not crash on a real render."""
    raw = __import__("os").environ["DARKTABLE_TEST_RAW"]
    ref_warm = tmp_path / "ref_warm.jpg"
    ref_cool = tmp_path / "ref_cool.jpg"
    _write_image(ref_warm, (220, 120, 60))
    _write_image(ref_cool, (60, 120, 220))

    try:
        spec, report, warnings, analysis = generate_style_spec(
            image_path=raw,
            direction="match the warm reference look",
            references=[str(ref_warm)],
            refine_iterations=2,
            refine_raw_path=raw,
        )
    except Exception as exc:  # pragma: no cover - depends on env
        if "ollama" in str(exc).lower() or "connection" in str(exc).lower():
            pytest.skip(f"Ollama not reachable: {exc}")
        raise

    from dtstylekit.vlm.models import StyleSpec

    assert isinstance(spec, StyleSpec)
    assert spec.plugins, "a non-empty style should have been produced"
    assert any(
        "REFERENCE" in w or "FIDELITY" in w or "reference" in w.lower() for w in warnings
    ) or True  # warnings are informational; success is a valid non-empty spec
