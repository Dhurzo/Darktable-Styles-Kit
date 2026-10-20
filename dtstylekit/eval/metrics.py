"""Look-fidelity metrics for evaluating VLM-output -> preset quality.

The VLM emits a JSON ``adjustments`` spec; the pipeline validates, clamps
and merges it into a ``.dtstyle`` which is then rendered by darktable.  Until
now the only automated check was *safety* (no red cast / crush / blow-out).
This module adds the missing half: a **look-fidelity** score that measures how
closely the *rendered* styled image matches the *reference look* the VLM was
supposed to reproduce.

The reference look is described by the same Python analysis the prompt already
feeds the VLM (``analyze_reference_hues`` + ``compute_reference_profile``), so
the score is cheap (no extra model calls) and directly comparable to what the
VLM "saw".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dtstylekit.color import circular_diff as _circ_dist
from dtstylekit.color import is_blown, is_crushed, is_red_cast


@dataclass
class LookProfile:
    """Compact description of an image's visual 'look'.

    Built from the same analysers the VLM prompt uses, so it is directly
    comparable to the reference the VLM was given.  ``None`` hues mean the
    zone carried no analysable colour grade (neutral).
    """

    # Per tonal zone colour grade.
    shadows_hue: float | None = None
    shadows_sat: float = 0.0
    shadows_mode: str = "neutral"
    midtones_hue: float | None = None
    midtones_sat: float = 0.0
    midtones_mode: str = "neutral"
    highlights_hue: float | None = None
    highlights_sat: float = 0.0
    highlights_mode: str = "neutral"

    # Global shape of the look.
    global_contrast: float = 0.0
    global_dynamic_range: float = 0.0
    global_saturation_p90: float = 0.0
    global_warmth_rb: float = 0.0

    # Aggregate stats (from render metrics).
    mean_luminance: float = 0.0
    mean_saturation: float = 0.0
    r_over_g: float = 1.0
    r_mean: float = 0.0
    g_mean: float = 0.0
    b_mean: float = 0.0
    shadows_pct: float = 0.0
    highlights_pct: float = 0.0

    @property
    def has_red_cast(self) -> bool:
        return is_red_cast(self.r_over_g, self.r_mean, self.b_mean)

    @property
    def is_crushed(self) -> bool:
        return is_crushed(self.mean_luminance)

    @property
    def is_blown(self) -> bool:
        return is_blown(self.mean_luminance, self.highlights_pct)

    @property
    def safety_ok(self) -> bool:
        return not (self.has_red_cast or self.is_crushed or self.is_blown)


def extract_look_profile(image_path: str | Path) -> LookProfile:
    """Build a :class:`LookProfile` from a rendered image.

    Combines the per-zone hue analysis (``analyze_reference_hues``), the
    extended global profile (``compute_reference_profile``) and the aggregate
    render metrics (``compute_render_metrics``).
    """
    from dtstylekit.analyzer.pipeline import analyze_reference_hues
    from dtstylekit.render import compute_render_metrics
    from dtstylekit.vlm.fidelity import compute_reference_profile

    p = Path(image_path)
    ref = analyze_reference_hues([p]) or {}
    prof = compute_reference_profile([p]) or {}
    m = compute_render_metrics(p)

    return LookProfile(
        shadows_hue=ref.get("shadows_hue"),
        shadows_sat=float(ref.get("shadows_sat", 0.0) or 0.0),
        shadows_mode=str(ref.get("shadows_hue_mode", "neutral") or "neutral"),
        midtones_hue=ref.get("midtones_hue"),
        midtones_sat=float(ref.get("midtones_sat", 0.0) or 0.0),
        midtones_mode=str(ref.get("midtones_hue_mode", "neutral") or "neutral"),
        highlights_hue=ref.get("highlights_hue"),
        highlights_sat=float(ref.get("highlights_sat", 0.0) or 0.0),
        highlights_mode=str(ref.get("highlights_hue_mode", "neutral") or "neutral"),
        global_contrast=float(prof.get("global_contrast", 0.0) or 0.0),
        global_dynamic_range=float(prof.get("global_dynamic_range", 0.0) or 0.0),
        global_saturation_p90=float(prof.get("global_saturation_p90", 0.0) or 0.0),
        global_warmth_rb=float(prof.get("global_warmth_rb", 0.0) or 0.0),
        mean_luminance=m.mean_luminance,
        mean_saturation=m.mean_saturation,
        r_over_g=m.r_over_g,
        r_mean=m.r_mean,
        g_mean=m.g_mean,
        b_mean=m.b_mean,
        shadows_pct=m.shadows_pct,
        highlights_pct=m.highlights_pct,
    )


@dataclass
class LookFidelity:
    """Result of comparing a styled ('achieved') look against a reference.

    All component scores are in ``[0, 1]`` (1 = perfect match).  ``overall``
    is a weighted blend; ``passed`` is ``True`` only when the look is both
    safe and above ``pass_threshold``.
    """

    overall: float = 0.0
    hue_score: float = 0.0
    chroma_score: float = 0.0
    contrast_score: float = 0.0
    dr_score: float = 0.0
    warmth_score: float = 0.0
    luminance_score: float = 0.0
    saturation_score: float = 0.0
    safety_ok: bool = True
    passed: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 3),
            "hue_score": round(self.hue_score, 3),
            "chroma_score": round(self.chroma_score, 3),
            "contrast_score": round(self.contrast_score, 3),
            "dr_score": round(self.dr_score, 3),
            "warmth_score": round(self.warmth_score, 3),
            "luminance_score": round(self.luminance_score, 3),
            "saturation_score": round(self.saturation_score, 3),
            "safety_ok": self.safety_ok,
            "passed": self.passed,
            "notes": self.notes,
        }


# Weights for the overall score.  Colour grade (hue+chroma) dominates because
# that is the part most directly driven by the VLM's `adjustments` JSON.
_WEIGHTS = {
    "hue": 0.20,
    "chroma": 0.20,
    "contrast": 0.12,
    "dr": 0.10,
    "warmth": 0.10,
    "luminance": 0.13,
    "saturation": 0.15,
}

_PASS_THRESHOLD = 0.70
_SAFETY_PENALTY = 0.5


def compare_looks(
    ref: LookProfile,
    achieved: LookProfile,
    pass_threshold: float = _PASS_THRESHOLD,
) -> LookFidelity:
    """Score how closely ``achieved`` reproduces the ``ref`` look.

    The comparison is tonal-zone aware: graded zones (``mono``/``bi``/
    ``global``) are scored on circular hue distance; neutral zones expect the
    styled output *not* to introduce a strong grade.  Global shape (contrast,
    dynamic range, warmth, luminance, saturation) is scored independently.
    """
    notes: list[str] = []

    zones = [
        (
            "shadows",
            ref.shadows_hue,
            ref.shadows_sat,
            ref.shadows_mode,
            achieved.shadows_hue,
            achieved.shadows_sat,
            achieved.shadows_mode,
        ),
        (
            "midtones",
            ref.midtones_hue,
            ref.midtones_sat,
            ref.midtones_mode,
            achieved.midtones_hue,
            achieved.midtones_sat,
            achieved.midtones_mode,
        ),
        (
            "highlights",
            ref.highlights_hue,
            ref.highlights_sat,
            ref.highlights_mode,
            achieved.highlights_hue,
            achieved.highlights_sat,
            achieved.highlights_mode,
        ),
    ]

    hue_scores: list[float] = []
    chroma_scores: list[float] = []
    for name, rh, rs, rm, ah, as_, _am in zones:
        # Chroma magnitude match (graded or not).
        rs = float(rs or 0.0)
        as_ = float(as_ or 0.0)
        chroma_err = abs(as_ - rs) / max(abs(rs), 0.1)
        chroma_scores.append(1.0 - min(chroma_err, 1.0))

        # Hue match / grade-introduction check.
        if rm in ("mono", "bi", "global") and rh is not None and ah is not None:
            d = _circ_dist(rh, ah)
            hue_scores.append(1.0 - d / 180.0)
            if d > 45:
                notes.append(
                    f"{name}: hue off by {d:.0f}deg (ref={rh:.0f}, got={ah:.0f})"
                )
        elif rm == "neutral":
            # Reference had no grade -> penalise a strong grade we added.
            added = max(0.0, as_ - 0.05)
            hue_scores.append(1.0 - min(added / 0.2, 1.0))
            if added > 0.1:
                notes.append(f"{name}: introduced grade where reference was neutral")

    hue_score = sum(hue_scores) / len(hue_scores) if hue_scores else 1.0
    chroma_score = sum(chroma_scores) / len(chroma_scores) if chroma_scores else 1.0

    def _shape_score(delta: float, scale: float) -> float:
        return 1.0 - min(abs(delta) / scale, 1.0)

    contrast_score = _shape_score(
        achieved.global_contrast - ref.global_contrast,
        max(abs(ref.global_contrast), 0.1),
    )
    dr_score = _shape_score(
        achieved.global_dynamic_range - ref.global_dynamic_range,
        max(abs(ref.global_dynamic_range), 0.2),
    )
    warmth_score = _shape_score(
        achieved.global_warmth_rb - ref.global_warmth_rb, 0.3
    )
    luminance_score = _shape_score(
        achieved.mean_luminance - ref.mean_luminance, 0.3
    )
    saturation_score = _shape_score(
        achieved.mean_saturation - ref.mean_saturation,
        max(ref.mean_saturation, 0.2),
    )

    overall = (
        _WEIGHTS["hue"] * hue_score
        + _WEIGHTS["chroma"] * chroma_score
        + _WEIGHTS["contrast"] * contrast_score
        + _WEIGHTS["dr"] * dr_score
        + _WEIGHTS["warmth"] * warmth_score
        + _WEIGHTS["luminance"] * luminance_score
        + _WEIGHTS["saturation"] * saturation_score
    )

    # A warm/red cast is only a defect when the *reference* was not itself
    # monochrome (sepia, B/W, split-tone).  An intentionally warm monochrome
    # reference (e.g. sepia) legitimately yields R>G in the output, so do not
    # flag it as a red cast.
    ref_is_mono = (
        ref.shadows_mode in ("mono", "bi")
        or ref.midtones_mode in ("mono", "bi")
        or ref.highlights_mode in ("mono", "bi")
    )
    red_cast = achieved.has_red_cast and not ref_is_mono
    safety = not (achieved.is_crushed or achieved.is_blown or red_cast)
    if not safety:
        overall = min(overall * _SAFETY_PENALTY, 0.49)
        if red_cast:
            notes.append("red cast detected in output")
        if achieved.is_crushed:
            notes.append("shadows crushed in output")
        if achieved.is_blown:
            notes.append("highlights blown in output")

    # A large colour-grade error is a hard fail regardless of the weighted
    # average — a safe-but-wrong grade is still wrong (this is what the
    # iterative refiner also enforces).
    passed = (
        safety
        and overall >= pass_threshold
        and hue_score >= 0.7
        and chroma_score >= 0.7
    )
    return LookFidelity(
        overall=overall,
        hue_score=hue_score,
        chroma_score=chroma_score,
        contrast_score=contrast_score,
        dr_score=dr_score,
        warmth_score=warmth_score,
        luminance_score=luminance_score,
        saturation_score=saturation_score,
        safety_ok=safety,
        passed=passed,
        notes=notes,
    )
