"""Style composer: merge selected presets + scalar adjustments.

Produces a unified plugin list from multiple base presets and optional
scalar adjustments. Deduplicates by (operation, multi_name) and
preserves pipeline order.  Properly handles multi-instance IOPs by
auto-incrementing ``multi_priority`` when the same (operation, multi_name)
pair appears more than once.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dtstylekit.codec.blendop import DEFAULT_BLENDOP_DISPLAY
from dtstylekit.codec.iop_registry import IOP_REGISTRY, pack_params
from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp

if TYPE_CHECKING:
    from dtstylekit.presets.models import Preset

logger = logging.getLogger(__name__)


@dataclass
class ComposerPlugin:
    """Minimal plugin spec passed to the serializer."""

    operation: str
    enabled: bool = True
    multi_name: str = ""
    multi_priority: int = 0
    params: dict[str, float | int] | None = None
    op_params: str = ""  # hex or gz+base64 encoded blob
    blendop_params: str = ""
    blendop_version: int = 13


# ---------------------------------------------------------------------------
# Blob helpers
# ---------------------------------------------------------------------------


def _decode_params_from_blob(op_params_encoded: str, operation: str = "") -> dict | None:
    """Decode a hex/gz+base64 encoded op_params back to a params dict.

    If ``operation`` is known (its registry entry has ``size_bytes``),
    use it directly.  Otherwise fall back to a best-effort size-probe.
    """
    if not op_params_encoded:
        return None

    from dtstylekit.codec.iop_registry import get_registry, unpack_params

    try:
        blob = decode_xmp(op_params_encoded)
    except Exception:
        return None

    # Fast path: known operation
    if operation:
        reg = get_registry(operation)
        if reg is not None and reg.size_bytes is not None:
            if len(blob) == reg.size_bytes:
                try:
                    return unpack_params(operation, blob)
                except Exception:
                    return None

    # Fallback: probe all registry entries by size
    for op_name, reg in IOP_REGISTRY.items():
        if reg.size_bytes is not None and len(blob) == reg.size_bytes:
            try:
                return unpack_params(op_name, blob)
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Multi-instance helpers
# ---------------------------------------------------------------------------


def _next_multi_priority(
    merged: "OrderedDict[tuple[str, str], ComposerPlugin]",
    operation: str,
) -> int:
    """Return the next available ``multi_priority`` for *operation*.

    Scans existing entries for the same operation and returns
    ``max(existing) + 1``, or 0 if none exist yet.
    """
    used: list[int] = []
    for (op, _mname), plg in merged.items():
        if op == operation:
            used.append(plg.multi_priority)
    return max(used, default=-1) + 1


# ---------------------------------------------------------------------------
# Core merge
# ---------------------------------------------------------------------------


def merge_presets(
    presets: list["Preset"],
    adjustments: dict[str, dict[str, float]] | None = None,
) -> list[ComposerPlugin]:
    """Merge multiple presets + optional adjustments into a unified plugin list.

    Args:
        presets: List of preset objects (each containing parsed plugins).
        adjustments: Optional dict of {operation: params} for additional
            adjustments.  When the operation already exists in the merged
            list the adjustment is applied on top (merged-then-packed).
            When it does not exist, a new plugin entry is appended.

    Returns:
        List of ComposerPlugin instances, deduplicated, in pipeline order.
        Multi-instance conflicts are resolved by auto-incrementing
        ``multi_priority``.
    """
    adjustments = adjustments or {}
    merged: "OrderedDict[tuple[str, str], ComposerPlugin]" = OrderedDict()

    for preset in presets:
        for plg in preset.plugins:
            key = (plg.operation, plg.multi_name or "")

            if key in merged:
                # Same operation + same multi_name — resolve by
                # incrementing priority and appending a new instance.
                new_priority = _next_multi_priority(merged, plg.operation)
                # Use the display multi_name (or generate one)
                mname = plg.multi_name or ""
                if not mname:
                    # Give synthetic instances a name so they're
                    # distinguishable in the pipeline.
                    mname = f"instance_{new_priority}"
                new_key = (plg.operation, mname)
                # Still a collision? Keep incrementing.
                while new_key in merged:
                    new_priority += 1
                    mname = f"instance_{new_priority}"
                    new_key = (plg.operation, mname)

                merged[new_key] = ComposerPlugin(
                    operation=plg.operation,
                    enabled=bool(plg.enabled),
                    multi_name=mname,
                    multi_priority=new_priority,
                    params={},
                    op_params=plg.op_params or "",
                    blendop_params=plg.blendop_params or "",
                    blendop_version=plg.blendop_version or 13,
                )
                logger.info(
                    "Multi-instance conflict: %s — created instance_%d",
                    plg.operation, new_priority,
                )
                continue

            merged[key] = ComposerPlugin(
                operation=plg.operation,
                enabled=bool(plg.enabled),
                multi_name=plg.multi_name or "",
                multi_priority=plg.multi_priority,
                params={},
                op_params=plg.op_params or "",
                blendop_params=plg.blendop_params or "",
                blendop_version=plg.blendop_version or 13,
            )

    # Apply adjustments: for each operation, override or add
    for op, new_params in adjustments.items():
        # Try to find existing plugin without multi_name
        key = (op, "")
        if key in merged:
            existing = merged[key]
            existing_params = dict(existing.params or {})
            existing_params.update(new_params)
            try:
                blob = pack_params(op, existing_params)
                existing.op_params = encode_xmp(blob)
                existing.params = existing_params
            except Exception as exc:
                logger.warning("Re-pack %s failed: %s", op, exc)
        else:
            try:
                blob = pack_params(op, new_params)
                op_params_encoded = encode_xmp(blob)
            except Exception as exc:
                logger.warning("Pack %s failed: %s", op, exc)
                op_params_encoded = ""
            merged[key] = ComposerPlugin(
                operation=op,
                enabled=True,
                multi_name="",
                multi_priority=_next_multi_priority(merged, op),
                params=dict(new_params),
                op_params=op_params_encoded or DEFAULT_BLENDOP_DISPLAY,
                blendop_params="",
                blendop_version=13,
            )

    return list(merged.values())
