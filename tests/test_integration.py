"""End-to-end integration tests for dtstylekit.

These tests verify the complete pipeline:
  image → analyze → preset search → VLM → style spec →
  generate .dtstyle → report → round-trip validation

The VLM is mocked to avoid requiring Ollama.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dtstylekit.codec.iop_registry import pack_params
from dtstylekit.codec.xmp_codec import encode_xmp
from dtstylekit.composer.generator import generate_dtstyle
from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.roundtrip import (
    validate_iop_list_consistency,
    validate_plugin_blobs,
    validate_xml_structure,
)
from dtstylekit.presets.models import PluginRef, Preset
from dtstylekit.vlm.models import Plugin, StyleSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preset_with_real_blob(
    name: str = "test_preset",
    operation: str = "vibrance",
    params: dict | None = None,
) -> Preset:
    """Create a preset with a *real* encoded blob (not a placeholder)."""
    if params is None:
        params = {"amount": 50.0}

    blob = pack_params(operation, params)
    encoded = encode_xmp(blob)

    return Preset(
        name=name,
        description="Test preset for E2E",
        iop_list=f"{operation},0",
        plugins=[
            PluginRef(
                operation=operation,
                enabled=1,
                multi_name="",
                multi_priority=0,
                num=0,
                module=0,
                op_params=encoded,
                blendop_params="",
                blendop_version=13,
                multi_name_hand_edited=0,
            )
        ],
        file_path=Path("/tmp/test.dtstyle"),
        xml_hash="e2etest",
    )


def _make_multipreset(
    name: str = "multi_preset",
) -> Preset:
    """Create a preset with multiple real-blob plugins."""
    plugins = []
    ops = [
        ("exposure", {"exposure": 0.5, "black": 0.0, "mode": 0,
                      "deflicker_percentile": 50.0,
                      "deflicker_target_level": -4.0,
                      "compensate_exposure_bias": 0}),
        ("vibrance", {"amount": 30.0}),
    ]
    for i, (op, params) in enumerate(ops):
        blob = pack_params(op, params)
        encoded = encode_xmp(blob)
        plugins.append(
            PluginRef(
                operation=op,
                enabled=1,
                multi_name="",
                multi_priority=0,
                num=i,
                module=0,
                op_params=encoded,
                blendop_params="",
                blendop_version=13,
                multi_name_hand_edited=0,
            )
        )

    return Preset(
        name=name,
        description="Multi-plugin test preset",
        iop_list="exposure,0,vibrance,1",
        plugins=plugins,
        file_path=Path("/tmp/multi.dtstyle"),
        xml_hash="multi_e2e",
    )


# ---------------------------------------------------------------------------
# E2E: Analyze → VLM (mocked) → Generate → Validate
# ---------------------------------------------------------------------------


class TestE2EGenerateAndValidate:
    """Full pipeline from StyleSpec to .dtstyle + validation."""

    def test_single_plugin_dtstyle(self, tmp_path: Path) -> None:
        """Generate a .dtstyle with a single vibrance plugin and validate."""
        spec = StyleSpec(
            style_name="warm_vibrant",
            style_description="A warm vibrant look",
            iop_list="vibrance,0",
            plugins=[
                Plugin(operation="vibrance", params={"amount": 60.0}),
            ],
        )
        preset = _make_preset_with_real_blob()
        output = tmp_path / "warm_vibrant.dtstyle"

        generate_dtstyle(spec, [preset], output)

        assert output.exists(), ".dtstyle file was not written"

        # XML structure validation
        xml_errors = validate_xml_structure(output)
        assert xml_errors == [], f"XML structure errors: {xml_errors}"

        # Blob size validation
        blob_errors = validate_plugin_blobs(output)
        assert blob_errors == [], f"Blob validation errors: {blob_errors}"

    def test_multipreset_merge_and_validate(self, tmp_path: Path) -> None:
        """Merge a multi-plugin preset + adjustments → validate."""
        spec = StyleSpec(
            style_name="cinematic_look",
            style_description="Cinematic film look",
            iop_list="exposure,0,vibrance,1",
            plugins=[
                Plugin(operation="exposure", params={"exposure": 0.3}),
                Plugin(operation="vibrance", params={"amount": 40.0}),
            ],
        )
        preset = _make_multipreset()
        output = tmp_path / "cinematic.dtstyle"

        generate_dtstyle(spec, [preset], output)

        assert output.exists()
        xml_errors = validate_xml_structure(output)
        assert xml_errors == [], f"XML errors: {xml_errors}"

    def test_with_adjustments(self, tmp_path: Path) -> None:
        """Merge preset + scalar adjustments and validate."""
        preset = _make_preset_with_real_blob()
        merged = merge_presets(
            [preset],
            adjustments={"vibrance": {"amount": 80.0}},
        )
        assert len(merged) >= 1
        # Verify the adjustment was applied
        vib = next(p for p in merged if p.operation == "vibrance")
        assert vib.params == {"amount": 80.0}

    def test_iop_list_consistency_check(self, tmp_path: Path) -> None:
        """Validate detects iop_list / style mismatch."""
        spec = StyleSpec(
            style_name="mismatch_test",
            style_description="Test iop_list mismatch",
            iop_list="vibrance,0",
            plugins=[
                Plugin(operation="exposure", params={"exposure": 1.0}),
            ],
        )
        output = tmp_path / "mismatch.dtstyle"
        generate_dtstyle(spec, [], output)

        errors = validate_iop_list_consistency(output)
        # exposure is in <style> but not in <iop_list>
        assert any("exposure" in e for e in errors), (
            f"Expected iop_list mismatch error, got: {errors}"
        )

    def test_generated_xml_roundtrip(self, tmp_path: Path) -> None:
        """Generated XML parses cleanly with ElementTree."""
        spec = StyleSpec(
            style_name="roundtrip_test",
            style_description="XML round-trip",
            plugins=[
                Plugin(operation="exposure", params={
                    "exposure": 0.0, "black": 0.0, "mode": 0,
                    "deflicker_percentile": 50.0,
                    "deflicker_target_level": -4.0,
                    "compensate_exposure_bias": 0,
                }),
            ],
        )
        output = tmp_path / "roundtrip.dtstyle"
        generate_dtstyle(spec, [], output)

        import xml.etree.ElementTree as ET
        tree = ET.parse(output)
        root = tree.getroot()
        assert root.tag == "darktable_style"
        assert root.find("info") is not None
        assert root.find("style") is not None

        # Verify op_params can be decoded
        for plugin in root.find("style").findall("plugin"):
            op = plugin.findtext("operation")
            op_params_enc = plugin.findtext("op_params", "")
            if op_params_enc and op in ("exposure", "vibrance"):
                from dtstylekit.codec.xmp_codec import decode_xmp
                from dtstylekit.codec.iop_registry import unpack_params
                blob = decode_xmp(op_params_enc)
                params = unpack_params(op, blob)
                assert isinstance(params, dict)
                assert len(params) > 0


# ---------------------------------------------------------------------------
# E2E: Simulated full pipeline (mocked VLM)
# ---------------------------------------------------------------------------


class TestE2EFullPipelineMocked:
    """Simulate the full `dtstylekit generate` pipeline with a mocked VLM."""

    def test_pipeline_produces_valid_style(self, tmp_path: Path) -> None:
        """Analyze image → (mocked VLM) → .dtstyle → validate."""
        from dtstylekit.analyzer.models import ImageAnalysis, LuminanceStats, HistogramStats
        from dtstylekit.composer.report import generate_report

        # -- Analyze (synthetic) --
        analysis = ImageAnalysis(
            width=800, height=600, mode="RGB", format="JPEG",
            luminance=LuminanceStats(mean=0.45, std=0.18, saturation_mean=0.3),
            histogram=HistogramStats(bins=64),
            scene_tags=["outdoor", "daylight"],
        )

        # -- VLM output (mocked) --
        spec = StyleSpec(
            style_name="golden_hour",
            style_description="Golden hour warmth",
            iop_list="filmicrgb,0,colorbalancergb,1,exposure,2",
            plugins=[
                Plugin(operation="filmicrgb", params={
                    "contrast": 1.4, "latitude": 25.0,
                }),
                Plugin(operation="colorbalancergb", params={
                    "shadows_H": 25.0, "highlights_H": 35.0,
                }),
                Plugin(operation="exposure", params={
                    "exposure": 0.3,
                }),
            ],
        )

        # -- Generate .dtstyle --
        dtstyle_path = tmp_path / "golden_hour.dtstyle"
        generate_dtstyle(spec, [], dtstyle_path, analysis)
        assert dtstyle_path.exists()

        # -- Generate report --
        report_path = tmp_path / "golden_hour.md"
        generate_report(
            spec, [], analysis,
            "Golden hour look with warm shadows and highlighted hues",
            report_path,
        )
        assert report_path.exists()
        assert "golden_hour" in report_path.read_text()

        # -- Validate --
        xml_errors = validate_xml_structure(dtstyle_path)
        assert xml_errors == [], f"XML errors: {xml_errors}"

        blob_errors = validate_plugin_blobs(dtstyle_path)
        # Some blob errors are acceptable for unverified IOPs
        verified_errors = [
            e for e in blob_errors
            if "not in IOP_REGISTRY" not in e
        ]
        assert verified_errors == [], f"Verified blob errors: {verified_errors}"
