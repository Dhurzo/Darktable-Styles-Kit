"""Style composer: merge selected presets + scalar adjustments.

Produces a unified plugin list from multiple base presets and optional
scalar adjustments.  Policies:

* **Duplicates**: for each operation only the *first* preset that
  contains it contributes its instances — later presets' instances of
  the same operation are dropped (stacking two filmic tone-maps or two
  color grades produces dark/broken looks).  Intentional multi-instances
  *within* a single preset (named instances, e.g. a camera style with
  "highlights"/"shadows" color balance) are preserved.
* **Adjustments**: a scalar adjustment is merged onto the preset's
  *actual* parameter values (decoded from the blob of the enabled
  instance — never onto darktable's disabled "scene-referred default"
  placeholder) and re-packed.  When the blob cannot be decoded
  (unverified IOP, legacy layout, curve blob) the preset parameters are
  kept untouched and the adjustment is skipped with a warning — never
  re-packed from registry defaults, which would silently discard the
  preset's look.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    multi_name_hand_edited: int = 0
    # Darktable reads the style_items `module` column and treats it as the
    # IOP's *module_version*: it compares it against `module->version()`.
    # For the style to apply, `module` must equal the IOP's version.
    # Verbatim presets already carry this value; freshly-packed IOPs get it
    # from IOP_REGISTRY[op].version below.
    module: int = 0


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

    # Fast path: known operation (accepts current and legacy blob sizes)
    if operation:
        reg = get_registry(operation)
        if reg is not None and reg.size_bytes is not None:
            if len(blob) == reg.size_bytes or len(blob) in reg.legacy_size_bytes:
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
    merged: OrderedDict[tuple[str, str], ComposerPlugin],
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
    presets: list[Preset],
    adjustments: dict[str, dict[str, float]] | None = None,
    dark_image: bool = False,
) -> list[ComposerPlugin]:
    """Merge multiple presets + optional adjustments into a unified plugin list.

    Args:
        presets: List of preset objects (each containing parsed plugins).
        adjustments: Optional dict of {operation: params} for additional
            adjustments.  When the operation already exists in the merged
            list the adjustment is applied on top (merged-then-packed).
            When it does not exist, a new plugin entry is appended.
        dark_image: When True (image mean luminance < 0.3, display-referred),
            a *fresh* filmicrgb instance is never created from scratch: the
            scene tone-mapper re-maps display-referred data and crushes
            shadows to black (measured: <10/255 pixels go 19% -> 40% on a
            dark PNG).  Adjustments may still merge onto a filmicrgb that a
            base preset already contributes.

    Returns:
        List of ComposerPlugin instances, deduplicated, in pipeline order.
        Multi-instance conflicts are resolved by auto-incrementing
        ``multi_priority``.
    """
    adjustments = adjustments or {}
    merged: OrderedDict[tuple[str, str], ComposerPlugin] = OrderedDict()

    # Operations already contributed by an earlier preset.  Only the
    # first preset that contains an operation contributes its instances;
    # later presets' instances of that operation are dropped — stacking
    # them (e.g. two filmic tone-maps, two color grades) produces
    # dark/broken looks.  Official styles carry *named* default
    # instances (filmicrgb "scene-referred default", artistic instances
    # like "sepia"), so exact (operation, multi_name) dedup alone cannot
    # tell "same look from two presets" apart from "intentional
    # multi-instance within one preset".
    seen_ops: set[str] = set()

    for preset in presets:
        preset_ops: set[str] = set()
        for plg in preset.plugins:
            # Cross-preset dedup: this operation was already contributed
            # by an earlier preset → drop this instance.
            if plg.operation in seen_ops and plg.operation not in preset_ops:
                logger.info(
                    "Skipping %s from preset %r — operation already "
                    "contributed by an earlier preset",
                    plg.operation,
                    preset.name,
                )
                continue

            key = (plg.operation, plg.multi_name or "")

            if key in merged:
                # Same operation + same multi_name twice within this
                # preset: explicitly-named instances are kept (priority
                # auto-incremented); unnamed duplicates are dropped.
                if plg.multi_name:
                    new_priority = _next_multi_priority(merged, plg.operation)
                    mname = plg.multi_name
                    new_key = (plg.operation, mname)
                    while new_key in merged:
                        new_priority += 1
                        mname = f"{plg.multi_name}_{new_priority}"
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
                        module=getattr(plg, "module", 0),
                        multi_name_hand_edited=getattr(plg, "multi_name_hand_edited", 0),
                    )
                    logger.info(
                        "Multi-instance conflict: %s — created instance %r",
                        plg.operation,
                        mname,
                    )
                else:
                    logger.info(
                        "Skipping duplicate %s from preset %r — "
                        "first occurrence wins (no multi-instance)",
                        plg.operation,
                        preset.name,
                    )
                continue

            preset_ops.add(plg.operation)
            seen_ops.add(plg.operation)
            merged[key] = ComposerPlugin(
                operation=plg.operation,
                enabled=bool(plg.enabled),
                multi_name=plg.multi_name or "",
                multi_priority=plg.multi_priority,
                params={},
                op_params=plg.op_params or "",
                blendop_params=plg.blendop_params or "",
                blendop_version=plg.blendop_version or 13,
                module=getattr(plg, "module", 0),
                multi_name_hand_edited=getattr(plg, "multi_name_hand_edited", 0),
            )

    # Apply adjustments: for each operation, override or add
    for op, new_params in adjustments.items():
        candidates = [plg for plg in merged.values() if plg.operation == op]
        # Pick the instance the adjustment should merge onto: prefer an
        # enabled unnamed instance, then the first *enabled* instance
        # (keeping its multi_name), then — importantly — the first
        # instance even if disabled.  Presets embed darktable's disabled
        # "scene-referred default" placeholder (e.g. filmicrgb) which
        # carries the preset's *custom* parameter values (black/white
        # points etc.), NOT the registry defaults.  Merging onto it and
        # enabling it preserves the preset look instead of replacing it
        # with a defaults-packed instance.
        pick = (
            next((p for p in candidates if not p.multi_name and p.enabled), None)
            or next((p for p in candidates if p.enabled), None)
            or next(iter(candidates), None)
        )
        if pick is None:
            # Fresh instance path.  Never create a fresh filmicrgb on a
            # dark display-referred image: measured 19% -> 40% pixels
            # below 10/255 (scene tone-mapper over display data).
            if dark_image and op == "filmicrgb":
                logger.warning(
                    "Adjustment for filmicrgb skipped: image is dark and "
                    "no preset provides filmicrgb — a fresh instance would "
                    "crush shadows (scene tone-mapper over display data)"
                )
                continue
            try:
                blob = pack_params(op, new_params)
                op_params_encoded = encode_xmp(blob)
            except Exception as exc:
                # Never fall back to a blendop blob as op_params: darktable
                # would read the 420 blendop bytes as the IOP's parameters
                # and render garbage (corrupted/black image).  Skip the
                # adjustment and keep the style free of this module.
                logger.warning("Pack %s failed: %s — omitting adjustment from style", op, exc)
                continue
            merged[(op, "")] = ComposerPlugin(
                operation=op,
                enabled=True,
                multi_name="",
                multi_priority=_next_multi_priority(merged, op),
                params=dict(new_params),
                op_params=op_params_encoded,
                blendop_params="",
                blendop_version=13,
                module=IOP_REGISTRY[op].version if op in IOP_REGISTRY else 0,
            )
            continue

        # Reconstruct the preset's *actual* parameter values from its
        # blob so the adjustment is applied on top of the preset's
        # look — packing from registry defaults would silently
        # discard everything the preset contributed to this module.
        base = _decode_params_from_blob(pick.op_params, pick.operation)
        if base is None or any(isinstance(v, str) for v in base.values()):
            # Opaque blob (unverified IOP, legacy layout, or a curve
            # blob that cannot be re-packed without a template name):
            # leave the preset parameters untouched.
            logger.warning(
                "Adjustment for %s skipped: preset blob cannot be "
                "re-packed — keeping preset parameters as-is",
                op,
            )
            continue
        existing_params = dict(base)
        existing_params.update(new_params)
        try:
            blob = pack_params(op, existing_params)
            pick.op_params = encode_xmp(blob)
            pick.params = existing_params
        except Exception as exc:
            logger.warning("Re-pack %s failed: %s", op, exc)

        # If we merged onto a disabled placeholder instance (e.g. the
        # preset's "scene-referred default" filmicrgb), enable it so the
        # adjustment actually has a visible effect.
        if not pick.enabled:
            pick.enabled = True
            logger.info(
                "Enabled %s instance %r to apply adjustment",
                op,
                pick.multi_name,
            )

    return list(merged.values())
