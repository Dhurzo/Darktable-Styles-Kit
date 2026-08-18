"""Version-drift guard: registry IOP versions vs the darktable checkout.

dtstylekit lives *inside* a darktable checkout (``../..`` from the project
root).  The single most dangerous failure mode of the whole tool is a
silent drift between the IOP struct versions/params declared in
``IOP_REGISTRY`` and the C source of the darktable version being targeted:
darktable then skips the module on import (version mismatch) or, worse,
reads garbage from a re-packed blob.

This test parses ``DT_MODULE_INTROSPECTION(N, ...)`` from every
``src/iop/*.c`` and fails loudly if the registry disagrees with the
checkout.  It is skipped automatically when the C sources are absent
(e.g. dtstylekit vendored standalone).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dtstylekit.codec.iop_registry import IOP_REGISTRY

# dtstylekit/tests/test_version_drift.py -> dtstylekit -> <darktable checkout>
_DTSTYLEKIT_ROOT = Path(__file__).resolve().parents[1]
_DARKTABLE_SRC = _DTSTYLEKIT_ROOT.parent / "src" / "iop"

_INTROSPECTION_RE = re.compile(r"DT_MODULE_INTROSPECTION\s*\(\s*(\d+)\s*,\s*[A-Za-z0-9_]+\s*\)")

pytestmark = pytest.mark.skipif(
    not _DARKTABLE_SRC.is_dir(),
    reason="darktable C sources not available (../../src/iop)",
)


def _read_versions() -> dict[str, int]:
    """Map operation name -> version from the darktable C sources."""
    versions: dict[str, int] = {}
    for path in sorted(_DARKTABLE_SRC.glob("*.c")):
        match = _INTROSPECTION_RE.search(path.read_text(encoding="utf-8"))
        if match:
            versions[path.stem] = int(match.group(1))
    return versions


def test_every_registered_iop_has_a_source_file() -> None:
    """Each registered operation must map to a ``src/iop/<op>.c`` file."""
    missing = [op for op in IOP_REGISTRY if not (_DARKTABLE_SRC / f"{op}.c").exists()]
    assert (
        not missing
    ), f"registry operations without a C source file (renamed/removed in darktable?): {missing}"


def test_iop_versions_match_master() -> None:
    """``IOP_REGISTRY[op].version`` must equal ``DT_MODULE_INTROSPECTION``."""
    c_versions = _read_versions()
    mismatches = [
        (op, reg.version, c_versions.get(op))
        for op, reg in IOP_REGISTRY.items()
        if c_versions.get(op) != reg.version
    ]
    assert not mismatches, (
        "version drift between IOP_REGISTRY and darktable sources "
        "(op, registry, C source): "
        + ", ".join(f"{op}: registry={r} c={c}" for op, r, c in mismatches)
    )


def test_exposure_legacy_v6_still_declared() -> None:
    """exposure is the only IOP with a legacy (pre-7) layout registered;
    if darktable bumps it again this test forces a registry update."""
    reg = IOP_REGISTRY["exposure"]
    assert reg.version == 7
    assert 24 in reg.legacy_size_bytes  # v6 layout
