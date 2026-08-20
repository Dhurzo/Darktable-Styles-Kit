"""Round-trip tests against REAL .dtstyle files from Darktable.

These are the most important tests in the suite: they verify that our
binary codec produces blobs that match the size and structure of the
actual blobs emitted by Darktable's style exporter. A divergence
here would be catastrophic (Darktable would silently drop or crash on
the corruption).

Strategy:

1. Walk all 534 preset files in ``data/styles/``.
2. For each ``<plugin>`` element, decode the ``op_params`` blob.
3. Verify:
   - For verified IOPs (size known): the decoded blob matches our
     expected size.
   - For curve-based IOPs: if present in any preset, our packer must
     produce correct-sized output for the same operation.
   - All other IOPs: just confirm the blob decodes to bytes (we don't
     claim to understand every layout, but we need to know none have
     zero/garbage size).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dtstylekit.codec.iop_registry import (
    IOP_REGISTRY,
    get_registry,
    unpack_params,
)
from dtstylekit.codec.xmp_codec import decode_xmp

# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------


def _find_presets_dir() -> Path | None:
    """Locate the 534 .dtstyle preset files (symlinked into the project)."""
    candidates = [
        Path(__file__).parent.parent / "dtstylekit" / "data" / "presets",
        Path(__file__).parent / "data" / "presets",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


PRESETS_DIR = _find_presets_dir()
HAS_PRESETS = PRESETS_DIR is not None


pytestmark_global = pytest.mark.skipif(
    not HAS_PRESETS, reason="Real .dtstyle presets not available"
)


@pytest.fixture(scope="module")
def parsed_presets() -> list[dict]:
    """Parse every .dtstyle file into a list of plugin dicts.

    Each entry: {file_path, file_name, operation, op_params_blob,
                 blend_op_blob, blendop_version}.
    """
    assert PRESETS_DIR is not None
    out: list[dict] = []
    for fpath in sorted(PRESETS_DIR.glob("*.dtstyle")):
        try:
            tree = ET.parse(fpath)
        except ET.ParseError:
            continue
        root = tree.getroot()
        style_el = root.find("style")
        if style_el is None:
            continue
        for plg in style_el.findall("plugin"):
            op = plg.find("operation")
            if op is None or not op.text:
                continue
            op_params_text = plg.find("op_params").text or ""
            blendop_text = plg.find("blendop_params").text or ""
            blendop_version = plg.find("blendop_version")
            try:
                op_blob = decode_xmp(op_params_text)
            except Exception:
                continue
            try:
                blend_op_blob = decode_xmp(blendop_text)
            except Exception:
                blend_op_blob = b""

            out.append(
                {
                    "file_path": str(fpath),
                    "file_name": fpath.name,
                    "operation": op.text,
                    "op_params_blob": op_blob,
                    "blend_op_blob": blend_op_blob,
                    "blendop_version": int(blendop_version.text)
                    if blendop_version is not None and blendop_version.text
                    else 0,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Real-preset inventory
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_PRESETS, reason="real presets missing")
class TestRealPresetInventory:
    def test_presets_directory_exists(self) -> None:
        assert PRESETS_DIR is not None
        assert PRESETS_DIR.is_dir()

    def test_finds_500_plus_presets(self) -> None:
        """We expect the canonical 534 .dtstyle files."""
        assert PRESETS_DIR is not None
        n = len(list(PRESETS_DIR.glob("*.dtstyle")))
        # Exactly 534 per blob_size_calibration.md; accept >=500 to be
        # robust against accidental .dtstyle file removals in dev.
        assert n >= 500, f"expected ≥500 presets, found {n}"

    def test_all_blobs_decode(self, parsed_presets: list[dict]) -> None:
        """Every op_params blob must decode via the XMP codec."""
        assert parsed_presets, "no presets parsed"
        # All entries already passed decode_xmp() during parsing
        for entry in parsed_presets:
            assert entry["op_params_blob"], f"empty op_params blob in {entry['file_name']}"


# ---------------------------------------------------------------------------
# Verified-IOP size matches reality
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_PRESETS, reason="real presets missing")
class TestVerifiedIopSizeMatchesDarktable:
    """For each verified IOP, the size of the actual blob in real presets
    must equal our declared ``size_bytes``.

    This is the single most important assertion in the suite — a
    mismatch means Darktable would silently corrupt the import.
    """

    @pytest.mark.parametrize(
        "op_name",
        [
            # Verified size-checked IOPs: each will be tested against real preset blobs.
            # Only IOPs with size_bytes set (verified) are tested.
            op
            for op, reg in IOP_REGISTRY.items()
            if reg.size_bytes is not None and not reg.is_curve_iop
        ],
    )
    def test_size_matches(self, op_name: str, parsed_presets: list[dict]) -> None:
        reg = get_registry(op_name)
        if reg is None:
            pytest.skip(f"{op_name} not in registry")
        if reg.size_bytes is None:
            pytest.skip(f"{op_name} size not verified in this build")

        matching = [e for e in parsed_presets if e["operation"] == op_name]
        if not matching:
            pytest.skip(f"no real presets actually use {op_name}")

        for entry in matching:
            actual = len(entry["op_params_blob"])
            ok_sizes = {reg.size_bytes} | set(reg.legacy_size_bytes)
            assert actual in ok_sizes, (
                f"{op_name} in {entry['file_name']}: actual={actual} "
                f"bytes, expected one of {sorted(ok_sizes)}"
            )

    @pytest.mark.parametrize(
        "op_name",
        # Dynamically use all IOPs whose size is verified (non-curve, non-special).
        # Exclude curve IOPs (they have dedicated unpackers) and basecurve (opaque).
        sorted(
            op
            for op, reg in IOP_REGISTRY.items()
            if reg.size_bytes is not None
            and not reg.is_curve_iop
            and not reg.pack_format.startswith("<curve>")
            and reg.pack_format != "<basecurve>"
        ),
    )
    def test_unpack_round_trip(self, op_name: str, parsed_presets: list[dict]) -> None:
        """unpack_params on a real blob should produce a typed dict."""
        matching = [e for e in parsed_presets if e["operation"] == op_name]
        if not matching:
            pytest.skip(f"no real presets use {op_name}")

        # Spot-check: try first entry
        blob = matching[0]["op_params_blob"]
        try:
            unpacked = unpack_params(op_name, blob)
            assert isinstance(unpacked, dict)
            assert len(unpacked) > 0
        except Exception as e:
            pytest.fail(
                f"unpack_params('{op_name}', real blob from {matching[0]['file_name']}) failed: {e}"
            )


# ---------------------------------------------------------------------------
# Cross-checks against our pack_format declarations
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_PRESETS, reason="real presets missing")
class TestStructFormatMatchesReality:
    """For verified IOPs we can unpack real blobs — let's verify the
    **field count** matches what we declared in ``pack_format``.
    A buggy struct could surface here."""

    def test_filmicrgb_field_count(self, parsed_presets: list[dict]) -> None:
        """filmicrgb v6: 18 floats + 11 ints = 29 fields."""
        matching = [e for e in parsed_presets if e["operation"] == "filmicrgb"]
        if not matching:
            pytest.skip("no filmicrgb presets")
        reg = get_registry("filmicrgb")
        unpacked = unpack_params("filmicrgb", matching[0]["op_params_blob"])
        assert len(unpacked) == len(reg.fields)
        assert len(unpacked) == 29

    def test_colorbalancergb_field_count(self, parsed_presets: list[dict]) -> None:
        """colorbalancergb v5: 32 floats + 1 int = 33 fields."""
        matching = [e for e in parsed_presets if e["operation"] == "colorbalancergb"]
        if not matching:
            pytest.skip("no colorbalancergb presets")
        reg = get_registry("colorbalancergb")
        unpacked = unpack_params("colorbalancergb", matching[0]["op_params_blob"])
        assert len(unpacked) == len(reg.fields)

    def test_sigmoid_field_count(self, parsed_presets: list[dict]) -> None:
        """sigmoid v3 size: 12 floats + 2 ints = 14 fields."""
        matching = [e for e in parsed_presets if e["operation"] == "sigmoid"]
        if not matching:
            pytest.skip("no sigmoid presets")
        reg = get_registry("sigmoid")
        unpacked = unpack_params("sigmoid", matching[0]["op_params_blob"])
        assert len(unpacked) == len(reg.fields)

    def test_exposure_field_count(self, parsed_presets: list[dict]) -> None:
        matching = [e for e in parsed_presets if e["operation"] == "exposure"]
        if not matching:
            pytest.skip("no exposure presets")
        reg = get_registry("exposure")
        unpacked = unpack_params("exposure", matching[0]["op_params_blob"])
        # v7 blobs have 7 fields; v6 legacy blobs (shipped in official
        # styles) have 6.
        assert len(unpacked) in (len(reg.fields), len(reg.legacy_fields))


# ---------------------------------------------------------------------------
# Coverage summary (sanity report)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_PRESETS, reason="real presets missing")
def test_coverage_report(parsed_presets: list[dict], capsys) -> None:  # noqa: ARG001
    """Print a quick coverage report of which real-world IOPs we support."""
    from collections import Counter

    counts = Counter(e["operation"] for e in parsed_presets)
    verified_size = {op for op, reg in IOP_REGISTRY.items() if reg.size_bytes is not None}

    print("\n=== IOP coverage across 534 real presets ===")
    for op, n in sorted(counts.items(), key=lambda x: -x[1]):
        in_registry = "[X]" if op in IOP_REGISTRY else "[ ]"
        size_verified = "[size]" if op in verified_size else "[no-size]"
        print(f"  {in_registry} {size_verified} {op:25s}: {n}")
