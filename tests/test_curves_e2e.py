"""End-to-end integration test: curve template selection flows
through validation, packing, and serialization all the way to a
valid .dtstyle file."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from dtstylekit.codec.iop_registry import (
    IOP_REGISTRY,
    pack_params,
    unpack_params,
)
from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp
from dtstylekit.codec.serializer import build_dtstyle_xml
from dtstylekit.codec.blendop import DEFAULT_BLENDOP_DISPLAY
from dtstylekit.curves import REGISTRY as CURVE_TEMPLATES
from dtstylekit.curves import curve_iop_size
from dtstylekit.vlm.models import Plugin, StyleSpec
from dtstylekit.vlm.validator import validate_style
from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.generator import generate_dtstyle


# ---------------------------------------------------------------------------
# Full pipeline: JSON -> validator -> pack -> serialize -> XML
# ---------------------------------------------------------------------------


def _fake_vlm_response() -> StyleSpec:
    """Build a StyleSpec shaped like the VLM's output, exercising
    a curve-based IOP plus a scalar-only IOP."""
    return StyleSpec(
        style_name="warm cinematic",
        style_description="Faded cinematic look with warm shadows.",
        iop_list=None,
        plugins=[
            # Scalar-only IOP (typical adjustment)
            Plugin(operation="filmicrgb", params={"contrast": 1.4, "latitude": 25.0}),
            # Curve-based IOP using a named template
            Plugin(
                operation="tonecurve",
                params={"curve_preset": "lift_medium", "preserve_colors": 0},
            ),
            # Another curve-based IOP
            Plugin(
                operation="rgbcurve",
                params={"curve_preset": "s_soft"},
            ),
        ],
    )


class TestEndToEndPipeline:
    def test_validator_curve_preset_propagates(self) -> None:
        spec = _fake_vlm_response()
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(warnings) == 0, f"unexpected warnings: {warnings}"
        assert len(validated.plugins) == 3

        # Find the curve-based plugins after validation
        by_op = {plg.operation: plg for plg in validated.plugins}
        assert by_op["tonecurve"].params["curve_preset"] == "lift_medium"
        assert by_op["rgbcurve"].params["curve_preset"] == "s_soft"
        # Scalar field also preserved
        assert by_op["tonecurve"].params["preserve_colors"] == 0

    def test_curve_preset_packs_via_registry(self) -> None:
        """pack_params('tonecurve', {'curve_preset': 'lift_medium'}) works."""
        blob = pack_params("tonecurve", {"curve_preset": "lift_medium"})
        assert len(blob) == curve_iop_size("tonecurve")  # 520
        assert blob != b"\x00" * 520  # not zeros — actual curve data

    def test_xmp_encoding_round_trip(self) -> None:
        """Encoded blob survives xmp codec round-trip."""
        blob = pack_params("colorzones", {"curve_preset": "s_strong", "strength": 50.0})
        encoded = encode_xmp(blob)
        assert encoded.startswith("gz")  # >100 bytes so gzip path
        decoded = decode_xmp(encoded)
        assert decoded == blob

    def test_full_xml_serialization(self, tmp_path: Path) -> None:
        """Full pipeline: StyleSpec → validate → build XML plugin dicts
        → ``build_dtstyle_xml`` (which calls ``encode_plugin`` with the
        params dict, including ``curve_preset``)."""
        spec = _fake_vlm_response()
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert not warnings

        plugins_xml: list[dict] = []
        for i, plg in enumerate(validated.plugins):
            plugins_xml.append({
                "num": i,
                "module": 0,
                "operation": plg.operation,
                "params": dict(plg.params),   # ← pass params so encode_plugin can re-pack
                "enabled": 1 if plg.enabled else 0,
                "blendop_version": 13,
                "multi_priority": plg.multi_priority,
                "multi_name": plg.multi_name,
                "multi_name_hand_edited": 0,
            })

        xml_str = build_dtstyle_xml(
            name=validated.style_name,
            description=validated.style_description,
            plugins=plugins_xml,
            iop_list=validated.iop_list,
        )

        out = tmp_path / "warm_cinematic.dtstyle"
        out.write_text(xml_str, encoding="utf-8")

        root = ET.fromstring(out.read_text())
        assert root.tag == "darktable_style"
        assert root.get("version") == "1.0"

        style_elems = root.findall("style/plugin")
        assert len(style_elems) == 3
        ops = [pe.find("operation").text for pe in style_elems]
        assert "filmicrgb" in ops
        assert "tonecurve" in ops
        assert "rgbcurve" in ops

        for pe in style_elems:
            op_name = pe.find("operation").text
            op_params_hex = pe.find("op_params").text
            assert len(op_params_hex) > 0
            blob = decode_xmp(op_params_hex)
            if op_name in ("colorzones", "rgbcurve", "tonecurve"):
                assert len(blob) == curve_iop_size(op_name)


class TestEndToEndWithComposer:
    def test_generate_dtstyle_uses_curve_template(self, tmp_path: Path) -> None:
        """The composer module's interface also accepts curve_preset.

        The merger calls ``pack_params`` which dispatches to the curve
        templates subsystem when ``is_curve_iop==True``.
        """
        spec = _fake_vlm_response()
        # Force the validator to run by hand (the composer doesn't do it)
        # — pre-validate so curve_preset is preserved
        from dtstylekit.vlm.validator import validate_style
        validated, _ = validate_style(spec, IOP_REGISTRY)
        # Caller now uses the validated spec
        out = tmp_path / "test.dtstyle"
        rc = generate_dtstyle(validated, presets=[], output_path=out)
        assert rc.exists()

        # Verify the curve plugin has correct blob size
        root = ET.fromstring(rc.read_text())
        for plg in root.findall("style/plugin"):
            op = plg.find("operation").text
            if op in ("colorzones", "rgbcurve", "tonecurve"):
                blob = decode_xmp(plg.find("op_params").text)
                assert len(blob) == curve_iop_size(op)


# ---------------------------------------------------------------------------
# Real-preset-driven test (skip if presets DB not built)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_presets_dir():
    p = Path(__file__).parent.parent / "dtstylekit" / "data" / "presets"
    if not p.exists():
        pytest.skip("Real preset dir not available")
    return p


@pytest.mark.parametrize("curve_op", ["colorzones", "rgbcurve", "tonecurve"])
@pytest.mark.parametrize("template_name", ["identity", "s_soft", "lift_medium", "shadow_warm"])
def test_curve_template_combinations_round_trip(curve_op, template_name):
    """Every (curve_op, template) combination packs and unpacks correctly."""
    blob = pack_params(curve_op, {"curve_preset": template_name})
    unpacked = unpack_params(curve_op, blob)
    assert unpacked["curve_preset"].startswith("(binary:")
    # Curve blob size matches the spec
    assert len(blob) == curve_iop_size(curve_op)
