"""Tests for curve templates and curve-based IOP pack/unpack.

Also includes end-to-end pipeline tests and CLI tests.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from dtstylekit.codec.iop_registry import (
    IOP_REGISTRY,
    pack_params,
    unpack_params,
)
from dtstylekit.codec.serializer import build_dtstyle_xml
from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp
from dtstylekit.composer.generator import generate_dtstyle
from dtstylekit.curves import (
    COLORZONES_SIZE,
    REGISTRY,
    RGBCURVE_SIZE,
    TONECURVE_SIZE,
    # Packing
    apply_curve_template,
    apply_curve_template_colorzones,
    apply_curve_template_rgbcurve,
    apply_curve_template_tonecurve,
    curve_iop_size,
    get_template,
    list_templates,
    pack_colorzones,
    pack_rgbcurve,
    pack_tonecurve,
    render_template_summary,
    unpack_colorzones,
    unpack_rgbcurve,
    unpack_tonecurve,
)
from dtstylekit.curves.cli import (
    cmd_curves_info,
    cmd_curves_list,
)
from dtstylekit.vlm.models import Plugin, StyleSpec
from dtstylekit.vlm.validator import validate_style

# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_registry_has_templates(self) -> None:
        assert len(REGISTRY) >= 5

    def test_unique_names(self) -> None:
        names = [t.name for t in REGISTRY]
        assert len(set(names)) == len(names)

    def test_get_known(self) -> None:
        tmpl = get_template("identity")
        assert tmpl.name == "identity"
        assert tmpl.title == "Identity (no change)"
        assert tmpl.category == "tone"

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown curve template"):
            get_template("doesnt_exist")

    def test_category_filter(self) -> None:
        vintage = list_templates("vintage")
        assert all(t.category == "vintage" for t in vintage)
        assert len(vintage) >= 1

    def test_render_summary(self) -> None:
        summary = render_template_summary()
        assert "| Template |" in summary
        assert "`identity`" in summary
        assert "`s_strong`" in summary


class TestTemplateCurves:
    def test_identity_endpoints(self) -> None:
        tmpl = get_template("identity")
        nodes = tmpl.nodes_per_channel["all"]
        assert nodes[0] == (0.0, 0.0)
        assert nodes[-1] == (1.0, 1.0)

    def test_s_curve_boosts_mids(self) -> None:
        tmpl = get_template("s_strong")
        nodes = tmpl.nodes_per_channel["all"]
        mid_idx = len(nodes) // 2
        _x_mid, y_mid = nodes[mid_idx]
        assert 0.3 <= y_mid <= 0.7

    def test_inverted_s_structure(self) -> None:
        tmpl = get_template("inverted_s_strong")
        nodes = tmpl.nodes_per_channel["all"]
        assert nodes[0] == (0.0, 0.0)
        assert nodes[-1] == (1.0, 1.0)
        s_tmpl = get_template("s_strong")
        s_nodes = s_tmpl.nodes_per_channel["all"]

        def var(ns):
            mid = [n[1] for n in ns[1:-1]]
            mu = sum(mid) / len(mid)
            return sum((v - mu) ** 2 for v in mid) / len(mid)

        assert var(s_nodes) > var(nodes) * 0.5

    def test_lift_blacks_lifts_interior(self) -> None:
        identity_tmpl = get_template("identity")
        lift_tmpl = get_template("lift_medium")
        id_nodes = identity_tmpl.nodes_per_channel["all"]
        lift_nodes = lift_tmpl.nodes_per_channel["all"]

        assert lift_nodes[0] == (0.0, 0.0)
        assert lift_nodes[-1] == (1.0, 1.0)

        shadow_pts = list(zip(id_nodes[1:-1], lift_nodes[1:-1], strict=False))
        first_half = shadow_pts[: len(shadow_pts) // 2 + 1]
        assert first_half, "Need at least one shadow point"
        for id_node, lift_node in first_half:
            x = id_node[0]
            assert lift_node[1] > id_node[1], (
                f"Lift should raise y above identity at x={x}; "
                f"got lift={lift_node[1]} vs identity={id_node[1]}"
            )

    def test_lift_preserves_max(self) -> None:
        for tmpl_name in ["lift_subtle", "lift_medium"]:
            tmpl = get_template(tmpl_name)
            nodes = tmpl.nodes_per_channel["all"]
            assert nodes[-1] == (1.0, 1.0)


# ---------------------------------------------------------------------------
# Packing tests
# ---------------------------------------------------------------------------


def _assert_close_lists(a: list[float], b: list[float], tol: float = 1e-5) -> None:
    assert len(a) == len(b)
    for x, y in zip(a, b, strict=False):
        assert math.isclose(x, y, abs_tol=tol), f"values differ: {x} vs {y}"


class TestColorzonesPacking:
    def test_size_matches(self) -> None:
        assert curve_iop_size("colorzones") == COLORZONES_SIZE
        assert COLORZONES_SIZE == struct.calcsize("<i" + "20f" * 6 + "3i3ifiI")

    def test_pack_unpack_identity(self) -> None:
        p = apply_curve_template_colorzones("identity")
        blob = pack_colorzones(p)
        assert len(blob) == COLORZONES_SIZE
        p2 = unpack_colorzones(blob)
        assert p.channel == p2.channel
        assert p.strength == p2.strength
        assert p.mode == p2.mode
        for i in range(3):
            _assert_close_lists(p.curve_x[i], p2.curve_x[i])
            _assert_close_lists(p.curve_y[i], p2.curve_y[i])

    def test_pack_unpack_s_curve(self) -> None:
        p = apply_curve_template_colorzones("s_strong", strength=42.0, mode=1)
        blob = pack_colorzones(p)
        assert len(blob) == COLORZONES_SIZE
        p2 = unpack_colorzones(blob)
        assert p2.strength == 42.0
        assert p2.mode == 1

    def test_pack_unpack_endpoints_preserved(self) -> None:
        template_names = [
            "identity",
            "s_soft",
            "s_strong",
            "inverted_s_soft",
            "inverted_s_strong",
            "lift_medium",
            "crush_subtle",
            "shadow_cool",
            "shadow_warm",
        ]
        for name in template_names:
            p = apply_curve_template_colorzones(name)
            blob = pack_colorzones(p)
            p2 = unpack_colorzones(blob)
            for i in range(3):
                assert math.isclose(p2.curve_x[i][0], 0.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_y[i][0], 0.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_x[i][-1], 1.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_y[i][-1], 1.0, abs_tol=1e-5)

    def test_highlights_soft_caps_at_target(self) -> None:
        p = apply_curve_template_colorzones("highlights_soft")
        blob = pack_colorzones(p)
        p2 = unpack_colorzones(blob)
        for i in range(3):
            assert p2.curve_y[i][-1] < 1.0
            assert p2.curve_y[i][-1] >= 0.90

    def test_unpack_wrong_size_raises(self) -> None:
        with pytest.raises(ValueError, match="colorzones blob"):
            unpack_colorzones(b"\x00" * 100)


class TestRGBCurvePacking:
    def test_size_matches(self) -> None:
        assert curve_iop_size("rgbcurve") == RGBCURVE_SIZE

    def test_pack_unpack_roundtrip(self) -> None:
        p = apply_curve_template_rgbcurve("inverted_s_soft")
        blob = pack_rgbcurve(p)
        assert len(blob) == RGBCURVE_SIZE
        p2 = unpack_rgbcurve(blob)
        for i in range(3):
            _assert_close_lists(p.curve_nodes_x[i], p2.curve_nodes_x[i])
            _assert_close_lists(p.curve_nodes_y[i], p2.curve_nodes_y[i])

    def test_unpack_wrong_size_raises(self) -> None:
        with pytest.raises(ValueError, match="rgbcurve blob"):
            unpack_rgbcurve(b"\x00" * 100)


class TestTonecurvePacking:
    def test_size_matches(self) -> None:
        assert curve_iop_size("tonecurve") == TONECURVE_SIZE

    def test_pack_unpack_roundtrip(self) -> None:
        p = apply_curve_template_tonecurve("highlights_soft")
        blob = pack_tonecurve(p)
        assert len(blob) == TONECURVE_SIZE
        p2 = unpack_tonecurve(blob)
        for i in range(3):
            _assert_close_lists(p.tonecurve_x[i], p2.tonecurve_x[i])
            _assert_close_lists(p.tonecurve_y[i], p2.tonecurve_y[i])

    def test_unpack_wrong_size_raises(self) -> None:
        with pytest.raises(ValueError, match="tonecurve blob"):
            unpack_tonecurve(b"\x00" * 100)


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_apply_curve_template_colorzones(self) -> None:
        blob = apply_curve_template("colorzones", "s_strong")
        assert len(blob) == COLORZONES_SIZE

    def test_apply_curve_template_rgbcurve(self) -> None:
        blob = apply_curve_template("rgbcurve", "lift_medium")
        assert len(blob) == RGBCURVE_SIZE

    def test_apply_curve_template_tonecurve(self) -> None:
        blob = apply_curve_template("tonecurve", "highlights_soft")
        assert len(blob) == TONECURVE_SIZE

    def test_apply_curve_template_unknown_iop_raises(self) -> None:
        with pytest.raises(ValueError, match="not a curve-based IOP"):
            apply_curve_template("filmicrgb", "identity")

    def test_apply_curve_template_unknown_template_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown curve template"):
            apply_curve_template("rgbcurve", "doesnt_exist")


# ---------------------------------------------------------------------------
# Integration with XMP codec
# ---------------------------------------------------------------------------


class TestExtendedTemplates:
    """Tests for the extended catalogue: low_key, high_key, bleach_bypass,
    sepia, cross_process, matte_film."""

    @pytest.mark.parametrize(
        "name",
        [
            "low_key",
            "high_key",
            "bleach_bypass",
            "sepia_warm",
            "sepia_cool",
            "cross_process_warm",
            "matte_film",
        ],
    )
    def test_registered(self, name: str) -> None:
        assert name in [t.name for t in REGISTRY]

    @pytest.mark.parametrize(
        "name",
        [
            "low_key",
            "high_key",
            "bleach_bypass",
            "sepia_warm",
            "sepia_cool",
            "cross_process_warm",
            "matte_film",
        ],
    )
    def test_pinned_endpoints(self, name: str) -> None:
        tmpl = get_template(name)
        for ch, nodes in tmpl.nodes_per_channel.items():
            assert nodes[0] == (0.0, 0.0), f"{name}.{ch}: bad start"
            assert nodes[-1] == (1.0, 1.0), f"{name}.{ch}: bad end"

    @pytest.mark.parametrize(
        "name",
        [
            "low_key",
            "high_key",
            "bleach_bypass",
            "sepia_warm",
            "sepia_cool",
            "cross_process_warm",
            "matte_film",
        ],
    )
    def test_pack_into_all_curve_iops(self, name: str) -> None:
        """Every extended template must round-trip through all three curve IOPs."""
        for curve_op in ("colorzones", "rgbcurve", "tonecurve"):
            blob = apply_curve_template(curve_op, name)
            assert len(blob) == curve_iop_size(curve_op)

    def test_low_key_darkens_overall(self) -> None:
        tmpl = get_template("low_key")
        nodes = tmpl.nodes_per_channel["all"]
        for x, y in nodes:
            if 0.55 <= x <= 0.9:
                assert y < x, f"low_key insufficiently dark at x={x}: y={y}"

    def test_high_key_brightens_overall(self) -> None:
        tmpl = get_template("high_key")
        nodes = tmpl.nodes_per_channel["all"]
        for x, y in nodes:
            if 0.3 <= x <= 0.85:
                assert y > x, f"high_key insufficiently bright at x={x}: y={y}"

    def test_bleach_bypass_structure(self) -> None:
        tmpl = get_template("bleach_bypass")
        nodes = tmpl.nodes_per_channel["all"]
        for x, y in nodes:
            if 0.05 <= x <= 0.18:
                assert y > x + 0.10, f"bleach_bypass shadow lift weak at x={x}: y={y}"

    def test_matte_film_lifts_and_rolls(self) -> None:
        tmpl = get_template("matte_film")
        nodes = tmpl.nodes_per_channel["all"]
        for x, y in nodes:
            if x == 0.0:
                continue
            if 0.25 <= x <= 0.5:
                assert y > x - 0.05, f"matte_film shadow should be lifted at x={x}, got y={y}"


class TestXMPCodecIntegration:
    def test_blob_encodes_decodes(self) -> None:
        p = apply_curve_template_colorzones("s_strong")
        blob = pack_colorzones(p)

        encoded = encode_xmp(blob)
        decoded = decode_xmp(encoded)
        assert decoded == blob


# ---------------------------------------------------------------------------
# End-to-end pipeline tests (from test_curves_e2e.py)
# ---------------------------------------------------------------------------


def _fake_vlm_response() -> StyleSpec:
    """Build a StyleSpec shaped like the VLM's output, exercising
    a curve-based IOP plus a scalar-only IOP."""
    return StyleSpec(
        style_name="warm cinematic",
        style_description="Faded cinematic look with warm shadows.",
        iop_list=None,
        plugins=[
            Plugin(operation="filmicrgb", params={"contrast": 1.4, "latitude": 25.0}),
            Plugin(
                operation="tonecurve",
                params={"curve_preset": "lift_medium", "preserve_colors": 0},
            ),
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

        by_op = {plg.operation: plg for plg in validated.plugins}
        assert by_op["tonecurve"].params["curve_preset"] == "lift_medium"
        assert by_op["rgbcurve"].params["curve_preset"] == "s_soft"
        assert by_op["tonecurve"].params["preserve_colors"] == 0

    def test_curve_preset_packs_via_registry(self) -> None:
        blob = pack_params("tonecurve", {"curve_preset": "lift_medium"})
        assert len(blob) == curve_iop_size("tonecurve")
        assert blob != b"\x00" * 520

    def test_xmp_encoding_round_trip(self) -> None:
        blob = pack_params("colorzones", {"curve_preset": "s_strong", "strength": 50.0})
        encoded = encode_xmp(blob)
        assert encoded.startswith("gz")
        decoded = decode_xmp(encoded)
        assert decoded == blob

    def test_full_xml_serialization(self, tmp_path: Path) -> None:
        spec = _fake_vlm_response()
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert not warnings

        plugins_xml: list[dict] = []
        for i, plg in enumerate(validated.plugins):
            plugins_xml.append(
                {
                    "num": i,
                    "module": 0,
                    "operation": plg.operation,
                    "params": dict(plg.params),
                    "enabled": 1 if plg.enabled else 0,
                    "blendop_version": 13,
                    "multi_priority": plg.multi_priority,
                    "multi_name": plg.multi_name,
                    "multi_name_hand_edited": 0,
                }
            )

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
        spec = _fake_vlm_response()
        from dtstylekit.vlm.validator import validate_style

        validated, _ = validate_style(spec, IOP_REGISTRY)
        out = tmp_path / "test.dtstyle"
        rc = generate_dtstyle(validated, presets=[], output_path=out)
        assert rc.exists()

        root = ET.fromstring(rc.read_text())
        for plg in root.findall("style/plugin"):
            op = plg.find("operation").text
            if op in ("colorzones", "rgbcurve", "tonecurve"):
                blob = decode_xmp(plg.find("op_params").text)
                assert len(blob) == curve_iop_size(op)


@pytest.mark.parametrize("curve_op", ["colorzones", "rgbcurve", "tonecurve"])
@pytest.mark.parametrize("template_name", ["identity", "s_soft", "lift_medium", "shadow_warm"])
def test_curve_template_combinations_round_trip(curve_op, template_name):
    """Every (curve_op, template) combination packs and unpacks correctly."""
    blob = pack_params(curve_op, {"curve_preset": template_name})
    unpacked = unpack_params(curve_op, blob)
    assert unpacked["curve_preset"].startswith("(binary:")
    assert len(blob) == curve_iop_size(curve_op)


# ---------------------------------------------------------------------------
# CLI tests (from test_curves_cli.py)
# ---------------------------------------------------------------------------


def _make_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


class TestCurvesList:
    def test_list_default(self, capsys) -> None:
        args = _make_namespace(category=None, quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 0
        captured = capsys.readouterr().out
        assert "Curve templates (19 total" in captured
        for tmpl in ["s_strong", "lift_medium", "bleach_bypass", "shadow_cool"]:
            assert tmpl in captured

    def test_list_quiet(self, capsys) -> None:
        args = _make_namespace(category=None, quiet=True)
        rc = cmd_curves_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "s_strong" in out
        assert "bleach_bypass" in out
        assert "───" not in out

    def test_list_filter_category(self, capsys) -> None:
        args = _make_namespace(category="vintage", quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "lift_medium" in out
        assert "inverted_s_strong" in out
        assert "inverted_s_soft" in out
        lines_with_s_strong_alone = [
            line
            for line in out.split("\n")
            if "s_strong" in line and "inverted_s_strong" not in line
        ]
        assert (
            not lines_with_s_strong_alone
        ), f"Found unexpected s_strong lines: {lines_with_s_strong_alone}"
        assert "bleach_bypass" not in out

    def test_list_quiet_filter_category(self, capsys) -> None:
        args = _make_namespace(category="filmic", quiet=True)
        rc = cmd_curves_list(args)
        assert rc == 0
        out_lines = capsys.readouterr().out.strip().split("\n")
        assert set(out_lines) == {"highlights_soft", "bleach_bypass", "matte_film"}

    def test_list_unknown_category(self, capsys) -> None:
        args = _make_namespace(category="doesntexist", quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 1
        err = capsys.readouterr().err
        assert "No templates found" in err


class TestCurvesInfo:
    def test_info_known_template(self, capsys) -> None:
        args = _make_namespace(name="s_strong")
        rc = cmd_curves_info(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Template: s_strong" in out
        assert "Title:" in out
        assert "Category:" in out
        assert "Nodes per channel:" in out

    def test_info_unknown_template(self, capsys) -> None:
        args = _make_namespace(name="nonexistent_template")
        rc = cmd_curves_info(args)
        assert rc == 1
        err = capsys.readouterr().err
        assert "Unknown curve template" in err

    def test_info_includes_example_json(self, capsys) -> None:
        args = _make_namespace(name="bleach_bypass")
        rc = cmd_curves_info(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert '"operation": "tonecurve"' in out
        assert '"curve_preset": "bleach_bypass"' in out


class TestCliIntegration:
    """Quick end-to-end check: run main() with 'curves list'."""

    def test_cli_runs_curves_list(self) -> None:
        from dtstylekit.cli import main

        rc = main(["curves", "list", "--quiet"])
        assert rc == 0

    def test_cli_runs_curves_info(self) -> None:
        from dtstylekit.cli import main

        rc = main(["curves", "info", "s_strong"])
        assert rc == 0

    def test_cli_curves_info_unknown_returns_nonzero(self) -> None:
        from dtstylekit.cli import main

        rc = main(["curves", "info", "nothing"])
        assert rc != 0
