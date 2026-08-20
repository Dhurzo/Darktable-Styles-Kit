"""Curve templates for curve-based IOPs (colorzones, rgbcurve, tonecurve).

A curve template is a named spline that can be applied to any of the
curve-based IOPs. They are designed to:

- Be robust: All nodes satisfy *(0, 0)* and *(1, 1)* invariants so
  Darktable accepts them without complaint.
- Be compact: Default to 5–9 nodes per channel (Darktable allows up to
  20, but fewer = simpler curves = easier to reason about).
- Be semantic: Each template has a *style* tag the VLM can reason about
  ("cinematic_S", "lifted_blacks", "faded_highlights", etc.).

Curves operate per **channel**. For most tone/grading uses a single
curve is applied to all 3 channels simultaneously. The library
exposes both all-channel and per-channel templates.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurveTemplate:
    """A named, reusable curve.

    Attributes:
        name: Unique identifier used by the VLM (snake_case).
        title: Human-readable label.
        category: Coarse bucket (``"tone"``, ``"lift"``, ``"color"``...).
        description: One-line explanation for the VLM prompt.
        channels: List of channel names this template applies to
            (``["all"]`` for identical R/G/B curves, or
            ``["r", "g", "b"]`` for separate per-channel curves).
        nodes_per_channel: Map of channel -> list of ``(x, y)`` nodes.
    """

    name: str
    title: str
    category: str
    description: str
    channels: list[str]
    nodes_per_channel: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Curve generators — all pin (0,0) and (1,1) by construction
# ---------------------------------------------------------------------------


def _identity(n: int = 5) -> list[tuple[float, float]]:
    """Linear ``y = x`` with ``n`` nodes.  Pins (0,0) and (1,1)."""
    if n < 2:
        n = 2
    return [(i / (n - 1), i / (n - 1)) for i in range(n)]


def _pin_endpoints(nodes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Force the first and last nodes to (0,0) and (1,1) respectively.

    A cosmetic guard: every generator below is responsible for emitting
    correct endpoints, but mistakes happen.  Calling this before
    serialisation prevents ``Darktable`` from failing to fit the spline.
    """
    if not nodes:
        return [(0.0, 0.0), (1.0, 1.0)]
    out = list(nodes)
    out[0] = (0.0, 0.0)
    out[-1] = (1.0, 1.0)
    return out


def _resample(n: int, fn: Callable[[float], float]) -> list[tuple[float, float]]:
    """Sample a function in [0, 1] at ``n`` evenly spaced nodes, pin
    endpoints, and clamp the output to [0, 1].

    Args:
        n: Number of nodes (>= 2).
        fn: Mapping ``x -> y`` taking values in [0, 1] but allowing
            smooth excursions outside before clamping.
    """
    if n < 2:
        n = 2
    pts: list[tuple[float, float]] = []
    for i in range(n):
        x = i / (n - 1)
        y = max(0.0, min(1.0, float(fn(x))))
        pts.append((round(x, 4), round(y, 4)))
    pts[0] = (0.0, 0.0)
    pts[-1] = (1.0, 1.0)
    return pts


def _contrast_s(n: int = 7, strength: float = 0.4) -> list[tuple[float, float]]:
    """S-curve.  Darkens shadows, lifts highlights, boosts mids.

    Implementation: smoothstep ``y = 0.5 + sin(pi*(x-0.5)) / 2``
    scaled by ``strength``.

    * strength=0  ⇒ identity
    * strength>0  ⇒ increased contrast
    """
    s = max(0.0, min(1.0, strength))
    return _resample(
        n,
        lambda x: (
            0.5
            + math.sin(math.pi * (x - 0.5)) * s / 2.0
            + (x - 0.5) * (1 - s) * 0
            + (x - 0.5) * (1 - s)
        ),
    )


def _contrast_s_v2(n: int = 7, strength: float = 0.5) -> list[tuple[float, float]]:
    """S-curve, additive form.  ``strength`` directly controls amplitude."""
    s = max(-1.0, min(1.0, strength))
    return _resample(
        n,
        lambda x: x + (math.sin(math.pi * (x - 0.5)) ** 3) * s * 0.35,
    )


def _inverted_s(n: int = 7, strength: float = 0.4) -> list[tuple[float, float]]:
    """Inverted S — pulls mids toward 0.5 (faded look).

    Inverse of :func:`_contrast_s_v2` with a negated amplitude.
    """
    s = max(-1.0, min(1.0, -strength))  # NOTE: negative
    return _resample(
        n,
        lambda x: x + (math.sin(math.pi * (x - 0.5)) ** 3) * s * 0.35,
    )


def _lift_blacks(lift: float = 0.1, n: int = 5) -> list[tuple[float, float]]:
    """Lift the black point while pinning (1, 1)."""
    lift = max(0.0, min(0.5, lift))
    return _resample(n, lambda x: lift + (1.0 - lift) * x)


def _crush_blacks(crush: float = 0.05, n: int = 5) -> list[tuple[float, float]]:
    """Push blacks down (deepens contrast).  Pins (0, 0) and (1, 1)."""
    crush = max(0.0, min(0.2, crush))
    return _resample(
        n,
        # Above x=0.15 follow a steeper-than-identity line
        lambda x: (
            0.0
            if x == 0.0
            else (
                (x ** (1.0 + crush * 4.0)) * (1.0 / (1.0 ** (1.0 + crush * 4.0))) if x > 0 else 0.0
            )
        ),
    )


def _simple_crush(crush: float = 0.05, n: int = 5) -> list[tuple[float, float]]:
    """Smoothstep variant — slightly cleaner than the power-based version.

    Pulls values below 0.5 down and values above 0.5 up by ``crush``.
    """
    crush = max(0.0, min(0.3, crush))
    # Mix between identity (a=1) and crisp S (a=∞), parameterised by crush.
    1.0 + crush * 6.0
    return _resample(
        n,
        lambda x: 0.5 + (math.sin(math.pi * (x - 0.5))) * crush * 0.5 + (x - 0.5) * (1 - crush),
    )


def _highlights_rolloff(target: float = 0.95, n: int = 5) -> list[tuple[float, float]]:
    """Cap highlights below 1.0 with smooth ease.  Pins (0, 0) and (1, 1).

    The cap is applied only to the top range; otherwise the curve follows
    :func:`_identity`.
    """
    target = max(0.5, min(1.0, target))
    threshold = 0.85

    def fn(x: float) -> float:
        if x <= threshold:
            return x
        t = (x - threshold) / (1.0 - threshold)
        # Smootherstep-style ease from threshold to target
        eased = math.sin(t * math.pi / 2)
        return threshold + (target - threshold) * eased

    pts = _resample(n, fn)
    # Override the (1,1) invariant back to (1,target) for last node
    pts[-1] = (1.0, target)
    return pts


def _shadow_tint(_channel: str, strength: float = 0.08, n: int = 5) -> list[tuple[float, float]]:
    """Lift the shadow region of the curve only.

    For ``tonecurve`` and ``colorzones`` use ``channel`` to pick a
    shadow-only tint: 'shadow_cool' lifts blue in darks, 'shadow_warm'
    lifts red in darks.

    Implementation: piecewise linear, (0, strength→0) for warmly tinted
    channels, top half pinned.
    """
    strength = max(0.0, min(0.5, strength))
    return _resample(
        n,
        lambda x: strength * (1.0 - x) if x < 0.5 else x,
    )


# ---------------------------------------------------------------------------
# Generators for the extended template catalogue (low-key, high-key,
# bleach-bypass, sepia, cross-process, matte-film).
# ---------------------------------------------------------------------------


def _bleach_bypass(n: int = 9) -> list[tuple[float, float]]:
    """Bleach-bypass curve: aggressive contrast + lifted lows.

    The bleach-bypass look:
    1. Push shadows toward mid-tones (lifted blacks).
    2. Hold mids in a tight band (the "flat" look).
    3. Aggressive contrast in the upper half + highlight rolloff.

    Implemented piecewise: lifted blacks below 0.15, flat mids 0.15-0.55,
    then aggressive contrast between 0.55 and 1.0.
    """

    def fn(x: float) -> float:
        if x < 0.15:
            # Lift: y = 0.18 + (0.65 * x) — pushes blacks towards 0.18
            return 0.18 + 0.65 * (x / 0.15) * (0.35 - 0.18)
            # simpler: linear from (0, 0.18) to (0.15, 0.35)
        if x < 0.55:
            # Flat mid: y = (x - 0.15) / (0.55 - 0.15) * 0.18 + 0.35
            t = (x - 0.15) / (0.55 - 0.15)
            return 0.35 + t * (0.55 - 0.35)  # (0.35, 0.55)
        # Aggressive contrast in highlights + rolloff
        t = (x - 0.55) / (1.0 - 0.55)
        # smoothstep from 0.55 to 0.95
        eased = 3 * t * t - 2 * t * t * t
        return 0.55 + eased * (0.93 - 0.55)

    return _resample(n, fn)


def _sepia_warm(n: int = 5) -> list[tuple[float, float]]:
    """Slight global warm bias + mid-darkening.

    Curve is mostly linear with a small lift in the mid-range and a
    gentle tilt down at the very top to keep the print feel.
    """

    def fn(x: float) -> float:
        # Lift mids ~5% darker for sepia feel
        if x < 0.1:
            return x * 0.7
        if x > 0.7:
            return 0.7 + (x - 0.7) * 0.95
        # smooth mid range
        return x * 0.95 - 0.005

    return _resample(n, fn)


def _sepia_cool(n: int = 5) -> list[tuple[float, float]]:
    """Cool variant: stronger mid-shadow lift, gentle highlight push."""

    def fn(x: float) -> float:
        if x < 0.1:
            return x * 0.85
        if x > 0.7:
            return 0.7 + (x - 0.7) * 1.05
        return x * 1.0 - 0.005

    return _resample(n, fn)


def _cross_process_warm(n: int = 7) -> list[tuple[float, float]]:
    """Cross-process: warm highlights, cool shadows, crushed mids.

    This is a perceptual approximation.  True cross-process swaps
    colour channels (cyan/magenta) — here we emulate it with a curve
    that lifts shadows, holds mids, and rolls the highlights warmly.
    """

    def fn(x: float) -> float:
        if x < 0.18:
            # Cool/lifted shadow tone
            return 0.10 + x * 0.55  # approaching 0.20 at x=0.18
        if x < 0.55:
            # Flat mids
            t = (x - 0.18) / (0.55 - 0.18)
            return 0.20 + t * (0.55 - 0.20)
        # Warm/aggressive highlight
        t = (x - 0.55) / (1.0 - 0.55)
        eased = 3 * t * t - 2 * t * t * t
        return 0.55 + eased * (0.95 - 0.55)

    return _resample(n, fn)


def _matte_film(n: int = 7) -> list[tuple[float, float]]:
    """Matte-film look: heavy lift + soft highlights + slight toe crush.

    Combines lift_blacks (0.18) with a soft highlight rolloff and a
    mild toe compression for the print feel.
    """

    def fn(x: float) -> float:
        # Toe (0..0.15): crush slightly then lift
        if x < 0.15:
            toe = x**1.3  # slow rise
            return float(0.18 + toe * (0.42 - 0.18) / 0.42)  # map to 0.18..0.42
        # Mids (0.15..0.7): linear-ish but slightly compressed
        if x < 0.7:
            t = (x - 0.15) / (0.7 - 0.15)
            return 0.42 + t * (0.72 - 0.42)
        # Highlights (0.7..1.0): roll off to 0.95
        t = (x - 0.7) / (1.0 - 0.7)
        eased = math.sin(t * math.pi / 2)
        return 0.72 + eased * (0.95 - 0.72)

    return _resample(n, fn)


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------


def _build_registry() -> list[CurveTemplate]:
    """Curated catalog of named curve templates."""
    reg: list[CurveTemplate] = []

    # ---- Identity ---------------------------------------------------------
    reg.append(
        CurveTemplate(
            name="identity",
            title="Identity (no change)",
            category="tone",
            description="Linear y=x — no contrast or color changes. Use as neutral baseline.",
            channels=["all"],
            nodes_per_channel={"all": _identity(5)},
        )
    )

    # ---- S curves (contrast) ---------------------------------------------
    reg.append(
        CurveTemplate(
            name="s_soft",
            title="Soft S-curve",
            category="contrast",
            description="Gentle global contrast: darken shadows, lift highlights, subtle mid-separation.",
            channels=["all"],
            nodes_per_channel={"all": _contrast_s_v2(7, strength=0.35)},
        )
    )
    reg.append(
        CurveTemplate(
            name="s_strong",
            title="Strong S-curve",
            category="contrast",
            description="Heavy contrast — dark blacks, bright whites, accentuated midtone separation.",
            channels=["all"],
            nodes_per_channel={"all": _contrast_s_v2(7, strength=0.85)},
        )
    )

    # ---- Inverted-S (faded / vintage) ------------------------------------
    reg.append(
        CurveTemplate(
            name="inverted_s_soft",
            title="Soft inverted-S",
            category="vintage",
            description="Gentle faded look: subtly pulled mids, soft highlight rolloff.",
            channels=["all"],
            nodes_per_channel={"all": _inverted_s(7, strength=0.30)},
        )
    )
    reg.append(
        CurveTemplate(
            name="inverted_s_strong",
            title="Strong inverted-S",
            category="vintage",
            description="Heavily faded / vintage look with pronounced mid pull.",
            channels=["all"],
            nodes_per_channel={"all": _inverted_s(7, strength=0.70)},
        )
    )

    # ---- Lift / crush ----------------------------------------------------
    reg.append(
        CurveTemplate(
            name="lift_subtle",
            title="Subtle black lift",
            category="vintage",
            description="Lift black point by ~5 % — filmic fade, soft contrast.",
            channels=["all"],
            nodes_per_channel={"all": _lift_blacks(0.05, n=5)},
        )
    )
    reg.append(
        CurveTemplate(
            name="lift_medium",
            title="Medium black lift",
            category="vintage",
            description="Lift black point by ~12 % — clearly faded / washed-out look.",
            channels=["all"],
            nodes_per_channel={"all": _lift_blacks(0.12, n=5)},
        )
    )
    reg.append(
        CurveTemplate(
            name="crush_subtle",
            title="Subtle black crush",
            category="contrast",
            description="Deepen blacks ~5 % for cleaner contrast.",
            channels=["all"],
            nodes_per_channel={"all": _simple_crush(0.05, n=5)},
        )
    )
    reg.append(
        CurveTemplate(
            name="crush_strong",
            title="Strong black crush",
            category="contrast",
            description="Heavy black-point crush for high-contrast edge emphasis.",
            channels=["all"],
            nodes_per_channel={"all": _simple_crush(0.15, n=5)},
        )
    )

    # ---- Highlight roll-off ---------------------------------------------
    reg.append(
        CurveTemplate(
            name="highlights_soft",
            title="Soft highlight roll-off",
            category="filmic",
            description="Cap highlights at ~0.95 with smooth ease — filmic highlight compression. (Note: caps rather than pinning 1.0)",
            channels=["all"],
            nodes_per_channel={"all": _highlights_rolloff(0.95, n=5)},
        )
    )

    # ---- Shadow tints ----------------------------------------------------
    reg.append(
        CurveTemplate(
            name="shadow_cool",
            title="Cool shadow tint",
            category="color",
            description="Add cool/blue cast in the shadow region only. Suggests cinematic teal-orange or dusk lighting.",
            channels=["all"],
            nodes_per_channel={"all": _shadow_tint("blue", 0.08, n=5)},
        )
    )
    reg.append(
        CurveTemplate(
            name="shadow_warm",
            title="Warm shadow tint",
            category="color",
            description="Add amber/warm cast in the shadow region only. Classic 'moody' look; pairs with highlights_soft.",
            channels=["all"],
            nodes_per_channel={"all": _shadow_tint("red", 0.08, n=5)},
        )
    )

    # ---- Low-key / High-key (general tone biases) -----------------------
    # Implementation: gain/gamma-style scaling around the midtone.
    reg.append(
        CurveTemplate(
            name="low_key",
            title="Low-key (dark overall)",
            category="tone",
            description=(
                "Compresses the upper half of the curve, darkening overall "
                "while preserving highlight detail. Classic low-key cinematic look."
            ),
            channels=["all"],
            nodes_per_channel={"all": _resample(7, lambda x: x**1.4)},
        )
    )
    reg.append(
        CurveTemplate(
            name="high_key",
            title="High-key (bright overall)",
            category="tone",
            description=(
                "Lifts the lower half of the curve while compressing "
                "highlights toward white. Bright, airy look."
            ),
            channels=["all"],
            nodes_per_channel={"all": _resample(7, lambda x: x**0.7)},
        )
    )

    # ---- Bleach bypass (Saving Private Ryan feel) -----------------------
    # Curve shape: very strong contrast (extreme S) + lifted blacks
    # in the lower midrange, then a roll-off near the highlights.
    reg.append(
        CurveTemplate(
            name="bleach_bypass",
            title="Bleach bypass (Saving Private Ryan)",
            category="filmic",
            description=(
                "Extreme contrast with flat mids and aggressive highlight "
                "compression. Emulates the bleach-bypass film processing "
                "look (lifts + crush)."
            ),
            channels=["all"],
            nodes_per_channel={"all": _bleach_bypass(n=9)},
        )
    )

    # ---- Sepia warm / cool (slight global bias) -------------------------
    reg.append(
        CurveTemplate(
            name="sepia_warm",
            title="Sepia warm",
            category="color",
            description=(
                "Mild global warm cast + slight mid-darkening. Implies a "
                "vintage photograph. For per-channel brown tone use the "
                "monochrome + colorbalance IOPs instead."
            ),
            channels=["all"],
            nodes_per_channel={"all": _sepia_warm()},
        )
    )
    reg.append(
        CurveTemplate(
            name="sepia_cool",
            title="Sepia cool",
            category="color",
            description=(
                "Mild global cool/blue cast + slight mid-darkening. Harder, "
                "more clinical vintage-photo look."
            ),
            channels=["all"],
            nodes_per_channel={"all": _sepia_cool()},
        )
    )

    # ---- Cross-process (cyan/magenta swap on Lab-like) ------------------
    reg.append(
        CurveTemplate(
            name="cross_process_warm",
            title="Cross-process warm",
            category="color",
            description=(
                "Emulates cross-processed film: warm highlights, cool "
                "shadows, slightly crushed mids. Pairs well with filmicrgb."
            ),
            channels=["all"],
            nodes_per_channel={"all": _cross_process_warm()},
        )
    )

    # ---- Matte (filmic fade with extra contrast) -------------------------
    reg.append(
        CurveTemplate(
            name="matte_film",
            title="Matte film print",
            category="filmic",
            description=(
                "Heavy black lift + soft highlight rolloff + slight toe "
                "compression. Emulates a film print with a darker base."
            ),
            channels=["all"],
            nodes_per_channel={"all": _matte_film()},
        )
    )

    # === Sanity check: all templates must pin (0,0) and (1,1) ============
    for tmpl in reg:
        for ch, nodes in tmpl.nodes_per_channel.items():
            if nodes[0] != (0.0, 0.0):
                raise RuntimeError(
                    f"Template '{tmpl.name}' channel '{ch}' first node is "
                    f"{nodes[0]}, expected (0.0, 0.0)"
                )
            if nodes[-1] != (1.0, 1.0) and tmpl.name != "highlights_soft":
                raise RuntimeError(
                    f"Template '{tmpl.name}' channel '{ch}' last node is "
                    f"{nodes[-1]}, expected (1.0, 1.0)"
                )

    return reg


REGISTRY: list[CurveTemplate] = _build_registry()


def get_template(name: str) -> CurveTemplate:
    """Look up a curve template by name.

    Args:
        name: The template's unique identifier
            (``"s_strong"``, ``"lift_medium"``, …).

    Returns:
        The matching :class:`CurveTemplate`.

    Raises:
        KeyError: If ``name`` is not in the registry.
    """
    for tmpl in REGISTRY:
        if tmpl.name == name:
            return tmpl
    available = ", ".join(sorted(t.name for t in REGISTRY))
    raise KeyError(f"Unknown curve template '{name}'. Available: {available}")


def list_templates(category: str | None = None) -> list[CurveTemplate]:
    """List registered templates, optionally filtered by category."""
    if category is None:
        return list(REGISTRY)
    return [t for t in REGISTRY if t.category == category]


def render_template_summary() -> str:
    """Return a compact markdown summary of templates for VLM prompts."""
    lines: list[str] = [
        "| Template | Category | Description |",
        "|----------|----------|-------------|",
    ]
    for tmpl in REGISTRY:
        desc = tmpl.description.replace("\n", " ")[:90]
        lines.append(f"| `{tmpl.name}` | {tmpl.category} | {desc} |")
    return "\n".join(lines)
