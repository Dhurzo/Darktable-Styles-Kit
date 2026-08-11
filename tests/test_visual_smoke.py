"""Visual smoke test: generated styles must render a sane image.

Skips automatically when ``darktable-cli`` is not available.  Builds a
style deterministically (no VLM): one real preset from the official
library + a filmicrgb contrast adjustment, then renders a synthetic test
image through darktable-cli with and without the style and checks the
luminance statistics (see tools/visual_check.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.roundtrip import find_darktable_cli
from dtstylekit.presets.parser import parse_preset
from tools.visual_check import check_style

pytestmark = pytest.mark.skipif(
    find_darktable_cli() is None,
    reason="darktable-cli not found (build darktable or adjust PATH)",
)


def _build_smoke_style(preset_dir: Path, out_path: Path) -> None:
    """Merge one real preset + a filmicrgb adjustment, write the .dtstyle."""
    from dtstylekit.codec.serializer import build_dtstyle_xml

    preset = None
    for f in sorted(preset_dir.glob("*.dtstyle")):
        p = parse_preset(f)
        if p is not None and p.plugins:
            preset = p
            break
    assert preset is not None, "no usable preset found in library"

    plugins = merge_presets([preset], {"filmicrgb": {"contrast": 1.4}})
    assert plugins, "merge produced no plugins"

    xml_plugins = [
        {
            "num": i,
            "module": plg.module,
            "operation": plg.operation,
            "op_params_override": plg.op_params,
            "params": {},
            "enabled": 1 if plg.enabled else 0,
            "blendop_override": plg.blendop_params or None,
            "blendop_version": plg.blendop_version,
            "multi_priority": plg.multi_priority,
            "multi_name": plg.multi_name,
            "multi_name_hand_edited": plg.multi_name_hand_edited,
        }
        for i, plg in enumerate(plugins)
    ]
    xml = build_dtstyle_xml(
        name="visual_smoke_test",
        description="",
        plugins=xml_plugins,
        iop_list=None,
    )
    out_path.write_text(xml, encoding="utf-8")


def test_generated_style_renders_sane(tmp_path: Path, preset_dir: Path) -> None:
    style = tmp_path / "smoke.dtstyle"
    _build_smoke_style(preset_dir, style)

    rc = check_style(style, outdir=tmp_path / "out", width=400)
    assert rc == 0, f"visual check failed with exit code {rc}"
