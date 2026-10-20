"""Unit tests for render path and style-name sanitization helpers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from dtstylekit.render import _safe_style_name, compute_render_metrics


def test_safe_style_name_rejects_paths() -> None:
    assert _safe_style_name("../../evil/name") == "evil_name"
    assert _safe_style_name("Post-Montgomery Rainy Day") == "Post-Montgomery_Rainy_Day"
    assert _safe_style_name("   ") == "style"


def test_compute_render_metrics_black(tmp_path: Path) -> None:
    image = Image.new("RGB", (2, 2), (0, 0, 0))
    path = tmp_path / "black.png"
    image.save(path)

    metrics = compute_render_metrics(path)
    assert metrics.mean_luminance == 0.0
    assert metrics.std_luminance == 0.0
    assert metrics.clipped_pct == 0.0
