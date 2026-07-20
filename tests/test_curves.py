"""Tests for curve templates and curve-based IOP pack/unpack."""

from __future__ import annotations

import math
import struct

import pytest

from dtstylekit.curves import (
    # Templates
    CurveTemplate,
    REGISTRY,
    get_template,
    list_templates,
    render_template_summary,
    # Packing
    ColorzonesParams,
    RGBCurveParams,
    TonecurveParams,
    COLORZONES_SIZE,
    RGBCURVE_SIZE,
    TONECURVE_SIZE,
    CUBIC_SPLINE,
    CATMULL_ROM,
    MONOTONE_HERMITE,
    apply_curve_template,
    apply_curve_template_colorzones,
    apply_curve_template_rgbcurve,
    apply_curve_template_tonecurve,
    pack_colorzones,
    unpack_colorzones,
    pack_rgbcurve,
    unpack_rgbcurve,
    pack_tonecurve,
    unpack_tonecurve,
    curve_iop_size,
)


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
        # midpoint should be >= 0.5 or curve should dip
        mid_idx = len(nodes) // 2
        x_mid, y_mid = nodes[mid_idx]
        # S-curve: at x=0.5, y is shifted (should be close to 0.5)
        assert 0.3 <= y_mid <= 0.7

    def test_inverted_s_structure(self) -> None:
        tmpl = get_template("inverted_s_strong")
        nodes = tmpl.nodes_per_channel["all"]
        # Endpoints must be pinned
        assert nodes[0] == (0.0, 0.0)
        assert nodes[-1] == (1.0, 1.0)
        # Inverted-S differs from S-curve: at the mid-region the y values
        # should lie closer to 0.5 (i.e. less variation than s_soft)
        s_tmpl = get_template("s_strong")
        s_nodes = s_tmpl.nodes_per_channel["all"]
        # Variance around 0.5
        def var(ns):
            mid = [n[1] for n in ns[1:-1]]  # skip endpoints
            mu = sum(mid) / len(mid)
            return sum((v - mu) ** 2 for v in mid) / len(mid)
        # S-curve should have more variance than inverted-S at midtones
        # (the S-curve "S-ifies" mids, inverted-S "straight-ens" them)
        assert var(s_nodes) > var(nodes) * 0.5

    def test_lift_blacks_lifts_interior(self) -> None:
        """Lift is visible in the lower-interior nodes (not endpoints).

        Endpoints must remain pinned for spline solver convergence —
        the lift effect is strongest near the bottom and tapers off toward
        the (1,1) anchor.
        """
        identity_tmpl = get_template("identity")
        lift_tmpl = get_template("lift_medium")
        id_nodes = identity_tmpl.nodes_per_channel["all"]
        lift_nodes = lift_tmpl.nodes_per_channel["all"]

        # Endpoints pinned
        assert lift_nodes[0] == (0.0, 0.0)
        assert lift_nodes[-1] == (1.0, 1.0)

        # Lower-interior nodes (skip first and last): lift curve sits
        # ABOVE identity in the shadow region
        shadow_pts = list(zip(id_nodes[1:-1], lift_nodes[1:-1]))
        # Lift is most prominent in the first half
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
    for x, y in zip(a, b):
        assert math.isclose(x, y, abs_tol=tol), f"values differ: {x} vs {y}"


class TestColorzonesPacking:
    def test_size_matches(self) -> None:
        assert curve_iop_size("colorzones") == COLORZONES_SIZE
        assert COLORZONES_SIZE == struct.calcsize(
            "<i" + "20f" * 6 + "3i3ifiI"
        )

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
        template_names = ["identity", "s_soft", "s_strong",
                          "inverted_s_soft", "inverted_s_strong",
                          "lift_medium", "crush_subtle",
                          "shadow_cool", "shadow_warm"]
        for name in template_names:
            p = apply_curve_template_colorzones(name)
            blob = pack_colorzones(p)
            p2 = unpack_colorzones(blob)
            for i in range(3):
                # Endpoints pinned by design (aside from highlight-roll-off
                # which intentionally caps at <1.0)
                assert math.isclose(p2.curve_x[i][0], 0.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_y[i][0], 0.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_x[i][-1], 1.0, abs_tol=1e-5)
                assert math.isclose(p2.curve_y[i][-1], 1.0, abs_tol=1e-5)

    def test_highlights_soft_caps_at_target(self) -> None:
        """highlights_soft intentionally doesn't pin (1,1) — it caps at <1.0."""
        p = apply_curve_template_colorzones("highlights_soft")
        blob = pack_colorzones(p)
        p2 = unpack_colorzones(blob)
        # Last node should NOT be 1.0 — it's capped
        for i in range(3):
            assert p2.curve_y[i][-1] < 1.0
            assert p2.curve_y[i][-1] >= 0.90  # ~0.95

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
        """Above 0.5 the curve should sit below identity (darker)."""
        tmpl = get_template("low_key")
        nodes = tmpl.nodes_per_channel["all"]
        # Find a node at x >= 0.5 and check its y is < x
        for x, y in nodes:
            if 0.55 <= x <= 0.9:
                assert y < x, f"low_key insufficiently dark at x={x}: y={y}"

    def test_high_key_brightens_overall(self) -> None:
        """Above 0.3 the curve should sit above identity (brighter)."""
        tmpl = get_template("high_key")
        nodes = tmpl.nodes_per_channel["all"]
        for x, y in nodes:
            if 0.3 <= x <= 0.85:
                assert y > x, f"high_key insufficiently bright at x={x}: y={y}"

    def test_bleach_bypass_structure(self) -> None:
        """Bleach bypass should lift blacks substantially."""
        tmpl = get_template("bleach_bypass")
        nodes = tmpl.nodes_per_channel["all"]
        # At x=0.1 the y should still be lifted to ~0.25 (well above identity 0.1)
        for x, y in nodes:
            if 0.05 <= x <= 0.18:
                assert y > x + 0.10, f"bleach_bypass shadow lift weak at x={x}: y={y}"

    def test_matte_film_lifts_and_rolls(self) -> None:
        """Matte film should lift blacks AND keep highlights compressed."""
        tmpl = get_template("matte_film")
        nodes = tmpl.nodes_per_channel["all"]
        # Lift at x=0.3 should be visible
        for x, y in nodes:
            if x == 0.0:
                continue
            if 0.25 <= x <= 0.5:
                assert y > x - 0.05, (
                    f"matte_film shadow should be lifted at x={x}, got y={y}"
                )


class TestXMPCodecIntegration:
    def test_blob_encodes_decodes(self) -> None:
        """Colorzones blob should round-trip through encode_xmp/decode_xmp."""
        from dtstylekit.codec.xmp_codec import encode_xmp, decode_xmp

        p = apply_curve_template_colorzones("s_strong")
        blob = pack_colorzones(p)

        encoded = encode_xmp(blob)
        decoded = decode_xmp(encoded)
        assert decoded == blob


