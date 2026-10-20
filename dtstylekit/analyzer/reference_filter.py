"""Consistency filter for reference-look images.

Reference sets are often assembled by hand and end up mixing different
edits: one warm cinematic frame, one neutral snapshot, one grainy vintage
photo.  The VLM then tries to satisfy contradictory looks, and the numeric
targets (luminance, saturation, hues) are averaged across incomparable
images.

This module builds a small, interpretable **edit fingerprint** per
reference and keeps the largest mutually-consistent group.  It does not try
to recover the actual editing history (a JPEG has none); tone curve shape,
colour grade, processing texture and lighting are used as proxies.  If
``.xmp`` sidecars ever become available, they can be added as an exact
signal without changing this API.

The filter is pure Python + numpy/Pillow, deterministic, and safe to call
before any VLM or darktable work.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Literal, cast

import numpy as np
from PIL import Image

from .noise import estimate_noise
from .pipeline import analyze_reference_hues

logger = logging.getLogger(__name__)

FilterMode = Literal["off", "warn", "auto", "strict"]
MatchMode = Literal["edit", "light", "both"]

_ZONES = ("shadows", "midtones", "highlights")
_QUANTILES = (0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.98)

# Fixed scales are used instead of per-set standard deviations.  With three
# references a single outlier would inflate a MAD/STD and protect itself;
# these defaults come from normalising typical JPEG reference exports.
_EDIT_SCALES = {
    "contrast": 0.12,
    "dynamic_range": 0.20,
    "quantile_shape": 0.80,
    "shadows_pct": 0.15,
    "highlights_pct": 0.10,
    "highlight_clip_pct": 0.03,
    "saturation": 0.12,
    "saturation_p90": 0.18,
    "warmth_rb": 0.06,
    "zone_sat": 0.15,
    "noise": 0.50,
    "gradient": 0.030,
    "high_freq": 0.15,
    "vignette": 0.20,
}
_LIGHT_SCALES = {
    "luminance": 0.10,
    "contrast": 0.12,
    "wb_rb": 0.25,
    "warmth_rb": 0.08,
    "shadows_pct": 0.15,
    "highlights_pct": 0.10,
}


@dataclass
class ReferenceFilterConfig:
    """Policy for :func:`filter_references`.

    ``mode`` controls what happens to the selected group:

    * ``off``   – do nothing (legacy behaviour).
    * ``warn``  – analyse and report, but keep every readable reference.
    * ``auto``  – drop clear outliers; fall back to the closest pair when no
      group reaches ``min_refs``.
    * ``strict`` – like auto, but return an error instead of falling back.

    ``match`` selects the signal used for grouping: ``edit`` (tone, colour,
    processing), ``light`` (scene key and white balance), or ``both``.
    """

    mode: FilterMode = "auto"
    match: MatchMode = "edit"
    min_refs: int = 2
    max_exact_refs: int = 12
    edit_threshold: float = 0.90
    light_threshold: float = 0.75
    tone_threshold: float = 1.05

    def __post_init__(self) -> None:
        if self.min_refs < 2:
            raise ValueError("min_refs must be >= 2")
        if self.max_exact_refs < 2:
            raise ValueError("max_exact_refs must be >= 2")
        if self.edit_threshold <= 0 or self.light_threshold <= 0 or self.tone_threshold <= 0:
            raise ValueError("reference filter thresholds must be > 0")


@dataclass(frozen=True)
class ReferenceFeatures:
    """Per-reference visual fingerprint used by the consistency filter."""

    path: Path
    luminance: float
    contrast: float
    dynamic_range: float
    saturation: float
    saturation_p90: float
    warmth_rb: float
    wb_rb: float
    quantiles: tuple[float, ...]
    shadows_pct: float
    highlights_pct: float
    highlight_clip_pct: float
    noise: float
    gradient: float
    high_freq: float
    vignette: float
    zone_hues: dict[str, float | None] = field(default_factory=dict)
    zone_modes: dict[str, str] = field(default_factory=dict)
    zone_confidences: dict[str, float] = field(default_factory=dict)
    zone_saturations: dict[str, float] = field(default_factory=dict)

    @property
    def is_monochrome(self) -> bool:
        return self.saturation < 0.03

    @property
    def quantile_shape(self) -> np.ndarray:
        """Quantiles normalised for exposure and overall contrast.

        The median is removed (exposure offset) and the inter-quartile
        range divides the result (contrast).  What remains is the *shape*
        of the tone distribution: flat/high-key, S-curve, lifted shadows,
        compressed highlights, etc.
        """
        q: np.ndarray = np.asarray(self.quantiles, dtype=np.float64)
        iqr = max(float(q[5] - q[3]), 1e-6)
        return cast("np.ndarray", (q - q[4]) / iqr)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "luminance": round(self.luminance, 4),
            "contrast": round(self.contrast, 4),
            "dynamic_range": round(self.dynamic_range, 4),
            "saturation": round(self.saturation, 4),
            "saturation_p90": round(self.saturation_p90, 4),
            "warmth_rb": round(self.warmth_rb, 4),
            "wb_rb": round(self.wb_rb, 4),
            "shadows_pct": round(self.shadows_pct, 4),
            "highlights_pct": round(self.highlights_pct, 4),
            "highlight_clip_pct": round(self.highlight_clip_pct, 4),
            "noise": round(self.noise, 6),
            "gradient": round(self.gradient, 5),
            "high_freq": round(self.high_freq, 4),
            "vignette": round(self.vignette, 4),
            "monochrome": self.is_monochrome,
            "zones": {
                zone: {
                    "hue": self.zone_hues.get(zone),
                    "mode": self.zone_modes.get(zone, "neutral"),
                    "confidence": round(self.zone_confidences.get(zone, 0.0), 3),
                    "saturation": round(self.zone_saturations.get(zone, 0.0), 4),
                }
                for zone in _ZONES
            },
        }


@dataclass
class ReferenceFilterResult:
    """Outcome of :func:`filter_references`."""

    mode: FilterMode
    match: MatchMode
    kept: list[Path]
    dropped: list[Path]
    outliers: list[Path]
    features: dict[Path, ReferenceFeatures]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    edit_distances: dict[Path, float] = field(default_factory=dict)
    tone_distances: dict[Path, float] = field(default_factory=dict)
    light_distances: dict[Path, float] = field(default_factory=dict)
    medoid: Path | None = None
    error: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.dropped)

    @property
    def summary(self) -> str:
        total = len(self.kept) + len(self.dropped)
        if self.mode == "off" or total == 0:
            return ""
        if self.mode == "warn":
            if not self.outliers:
                return f"Reference filter ({self.match}): all {total} reference(s) consistent"
            names = ", ".join(p.name for p in self.outliers)
            return (
                f"Reference filter ({self.match}): would drop {len(self.outliers)}/{total} "
                f"inconsistent reference(s): {names}"
            )
        if self.dropped:
            names = ", ".join(p.name for p in self.dropped)
            return (
                f"Reference filter ({self.match}): kept {len(self.kept)}/{total} "
                f"reference(s); dropped: {names}"
            )
        return f"Reference filter ({self.match}): all {total} reference(s) consistent"


def extract_reference_features(path: str | Path) -> ReferenceFeatures:
    """Build a :class:`ReferenceFeatures` fingerprint for one image.

    Raises the underlying Pillow exception for unreadable files; callers
    that batch multiple references should use :func:`filter_references`,
    which records them as dropped instead of aborting the whole set.
    """
    p = Path(path)
    image = Image.open(p).convert("RGB")
    image.load()
    arr = np.asarray(image, dtype=np.float32) / 255.0
    if arr.size == 0:
        raise ValueError(f"empty image: {p}")

    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    mean_lum = float(lum.mean())
    contrast = float(lum.std())
    quantiles = tuple(float(v) for v in np.percentile(lum, [q * 100.0 for q in _QUANTILES]))

    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    delta = mx - mn
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-9), 0.0)
    saturation = float(sat.mean())
    saturation_p90 = float(np.percentile(sat, 90))
    warmth = float((arr[..., 0] - arr[..., 2]).mean())
    mean_r = float(arr[..., 0].mean())
    mean_b = float(arr[..., 2].mean())
    wb_rb = float(min(max(mean_r / (mean_b + 1e-9), 0.1), 10.0))

    shadows_pct = float(np.mean(lum < 0.18))
    highlights_pct = float(np.mean(lum >= 0.75))
    highlight_clip_pct = float(np.mean(lum >= 0.98))

    # Texture/processing proxies on a fixed-size thumbnail so runtime and
    # grain estimates are resolution-independent.
    small = image.copy()
    small.thumbnail((512, 512), Image.Resampling.BILINEAR)
    small_arr = np.asarray(small, dtype=np.float32) / 255.0
    small_lum = 0.2126 * small_arr[..., 0] + 0.7152 * small_arr[..., 1] + 0.0722 * small_arr[..., 2]
    gradient = 0.0
    if small_lum.shape[1] > 1:
        gradient += float(np.abs(np.diff(small_lum, axis=1)).mean())
    if small_lum.shape[0] > 1:
        gradient += float(np.abs(np.diff(small_lum, axis=0)).mean())
    high_freq = gradient / (float(small_lum.std()) + 1e-6)
    vignette = _vignette_strength(small_lum)

    zone_hues: dict[str, float | None] = {}
    zone_modes: dict[str, str] = {}
    zone_confidences: dict[str, float] = {}
    zone_saturations: dict[str, float] = {}
    try:
        zones = analyze_reference_hues([p])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Reference hue analysis failed for %s: %s", p, exc)
        zones = {}
    for zone in _ZONES:
        hue = zones.get(f"{zone}_hue")
        zone_hues[zone] = float(hue) if isinstance(hue, int | float) else None
        zone_modes[zone] = str(zones.get(f"{zone}_hue_mode", "neutral") or "neutral")
        zone_confidences[zone] = float(zones.get(f"{zone}_hue_confidence", 0.0) or 0.0)
        zone_saturations[zone] = float(zones.get(f"{zone}_sat", 0.0) or 0.0)

    return ReferenceFeatures(
        path=p,
        luminance=mean_lum,
        contrast=contrast,
        dynamic_range=float(quantiles[7] - quantiles[1]),
        saturation=saturation,
        saturation_p90=saturation_p90,
        warmth_rb=warmth,
        wb_rb=wb_rb,
        quantiles=quantiles,
        shadows_pct=shadows_pct,
        highlights_pct=highlights_pct,
        highlight_clip_pct=highlight_clip_pct,
        noise=estimate_noise(image),
        gradient=gradient,
        high_freq=high_freq,
        vignette=vignette,
        zone_hues=zone_hues,
        zone_modes=zone_modes,
        zone_confidences=zone_confidences,
        zone_saturations=zone_saturations,
    )


def filter_references(
    paths: Sequence[str | Path],
    config: ReferenceFilterConfig | None = None,
) -> ReferenceFilterResult:
    """Select the largest mutually-consistent group of references.

    The input order is normalised so the result is deterministic.  With
    fewer than three readable references there is not enough evidence to
    call anything an outlier, so all readable paths are kept (with a note).
    """
    cfg = config or ReferenceFilterConfig()
    unique = sorted({Path(p) for p in paths}, key=lambda p: str(p))

    if cfg.mode == "off":
        return ReferenceFilterResult(
            mode=cfg.mode,
            match=cfg.match,
            kept=unique,
            dropped=[],
            outliers=[],
            features={},
        )

    if not unique:
        return ReferenceFilterResult(
            mode=cfg.mode,
            match=cfg.match,
            kept=[],
            dropped=[],
            outliers=[],
            features={},
            warnings=["Reference filter: no reference images supplied"],
        )

    features: dict[Path, ReferenceFeatures] = {}
    invalid: list[Path] = []
    for path in unique:
        try:
            features[path] = extract_reference_features(path)
        except Exception as exc:
            logger.warning("Reference filter: cannot read %s: %s", path, exc)
            invalid.append(path)

    valid = list(features)
    result = ReferenceFilterResult(
        mode=cfg.mode,
        match=cfg.match,
        kept=list(valid),
        dropped=list(invalid),
        outliers=[],
        features=features,
    )
    if invalid:
        result.warnings.append(
            "Reference filter: skipped unreadable reference(s): "
            + ", ".join(p.name for p in invalid)
        )

    if len(valid) < 3:
        result.notes.append(
            "Reference filter: fewer than 3 readable references; "
            "consistency filtering needs at least 3 to detect outliers."
        )
        return result

    min_refs = min(cfg.min_refs, len(valid))
    matrix = _distance_matrix(valid, features, cfg)
    group = _select_group(valid, matrix, cfg, min_refs)

    if group is None:
        if cfg.mode == "strict":
            result.error = (
                "No consistent reference group found; refusing to generate a style. "
                "Use --reference-filter warn/auto or provide references with the same edit."
            )
            result.warnings.append(result.error)
            result.kept = list(valid)
            return result
        group = _fallback_group(valid, matrix, min_refs)
        result.warnings.append(
            "Reference filter: no group passed the consistency threshold; "
            "keeping the closest references and continuing."
        )

    proposed = [p for p in valid if p not in group]
    result.outliers = proposed
    medoid = _medoid(group, matrix, valid)
    result.medoid = medoid
    for path in valid:
        result.tone_distances[path] = _tone_distance(features[path], features[medoid])
        result.edit_distances[path] = _edit_distance(features[path], features[medoid])
        result.light_distances[path] = _light_distance(features[path], features[medoid])

    if cfg.mode == "warn":
        result.warnings.extend(_outlier_warnings(features, medoid, proposed, "would drop"))
        return result

    if cfg.mode == "strict" and len(group) < min_refs:
        result.error = result.error or (
            f"Reference filter: only {len(group)} consistent reference(s) found; "
            f"at least {min_refs} are required."
        )
        result.warnings.append(result.error)
        result.kept = list(valid)
        return result

    result.kept = group
    result.dropped.extend(proposed)
    result.warnings.extend(_outlier_warnings(features, medoid, proposed, "dropped"))
    return result


def format_reference_filter_report(result: ReferenceFilterResult) -> list[str]:
    """Markdown lines describing the filter decision (for the style report)."""
    if result.mode == "off" or not result.features:
        return []
    total = len(result.kept) + len(result.dropped)
    lines = [
        "## Reference Consistency",
        "",
        f"- **Mode**: `{result.mode}` / `{result.match}`",
        f"- **Kept**: {len(result.kept)} of {total}",
    ]
    if result.outliers and result.mode == "warn":
        lines.append("- **Would drop**: " + ", ".join(f"`{p.name}`" for p in result.outliers))
    elif result.dropped:
        lines.append("- **Dropped**: " + ", ".join(f"`{p.name}`" for p in result.dropped))
    else:
        lines.append("- **Dropped**: none")
    if result.error:
        lines.append(f"- **Error**: {result.error}")
    lines.append("")
    lines.append("| Reference | Status | Edit distance | Tone distance | Light distance | Reason |")
    lines.append("|-----------|--------|---------------|---------------|----------------|--------|")
    kept_set = set(result.kept)
    for path, feature in sorted(result.features.items(), key=lambda item: item[0].name):
        status = "kept" if path in kept_set else "dropped"
        edit_d = result.edit_distances.get(path)
        tone_d = result.tone_distances.get(path)
        light_d = result.light_distances.get(path)
        reason = ""
        if status == "dropped" and result.medoid in result.features:
            reason = _explain_outlier(feature, result.features[result.medoid])
        lines.append(
            f"| `{path.name}` | {status} | {_fmt(edit_d)} | "
            f"{_fmt(tone_d)} | {_fmt(light_d)} | {reason} |"
        )
    lines.append("")
    return lines


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _distance_matrix(
    paths: list[Path],
    features: dict[Path, ReferenceFeatures],
    cfg: ReferenceFilterConfig,
) -> list[list[float]]:
    n = len(paths)
    matrix = [[0.0] * n for _ in range(n)]
    for i, j in combinations(range(n), 2):
        d = _selection_distance(features[paths[i]], features[paths[j]], cfg)
        matrix[i][j] = d
        matrix[j][i] = d
    return matrix


def _selection_distance(
    a: ReferenceFeatures, b: ReferenceFeatures, cfg: ReferenceFilterConfig
) -> float:
    if cfg.match == "light":
        return _light_distance(a, b) / cfg.light_threshold
    edit_score = _edit_distance(a, b) / cfg.edit_threshold
    tone_score = _tone_distance(a, b) / cfg.tone_threshold
    if cfg.match == "edit":
        return max(edit_score, tone_score)
    return max(
        edit_score,
        tone_score,
        _light_distance(a, b) / cfg.light_threshold,
    )


def _select_group(
    paths: list[Path],
    matrix: list[list[float]],
    cfg: ReferenceFilterConfig,
    min_refs: int,
) -> list[Path] | None:
    n = len(paths)
    if n <= cfg.max_exact_refs:
        best: tuple[int, float, float, list[int]] | None = None
        for size in range(n, min_refs - 1, -1):
            for members in combinations(range(n), size):
                distances = [matrix[i][j] for i, j in combinations(members, 2)]
                max_d = max(distances, default=0.0)
                if max_d > 1.0:
                    continue
                sum_d = float(sum(distances))
                candidate = (size, -max_d, -sum_d, list(members))
                if best is None or candidate[:3] > best[:3]:
                    best = candidate
            if best is not None and best[0] == size:
                break
        if best is None:
            return None
        return [paths[i] for i in best[3]]

    # Large sets: medoid + nearest neighbours under the threshold.
    seed = _medoid(paths, matrix, paths)
    seed_i = paths.index(seed)
    order = sorted((i for i in range(n) if i != seed_i), key=lambda i: matrix[seed_i][i])
    group = [seed_i]
    for i in order:
        if all(matrix[i][j] <= 1.0 for j in group):
            group.append(i)
    if len(group) < min_refs:
        group = [seed_i] + order[: min_refs - 1]
    return [paths[i] for i in group]


def _fallback_group(paths: list[Path], matrix: list[list[float]], min_refs: int) -> list[Path]:
    seed = _medoid(paths, matrix, paths)
    seed_i = paths.index(seed)
    order = sorted((i for i in range(len(paths)) if i != seed_i), key=lambda i: matrix[seed_i][i])
    return [seed] + [paths[i] for i in order[: max(0, min_refs - 1)]]


def _medoid(paths: list[Path], matrix: list[list[float]], universe: list[Path]) -> Path:
    indexes = {p: i for i, p in enumerate(universe)}
    return min(
        paths,
        key=lambda p: sum(matrix[indexes[p]][indexes[q]] for q in paths if q != p),
    )


def _outlier_warnings(
    features: dict[Path, ReferenceFeatures],
    medoid: Path,
    outliers: list[Path],
    verb: str,
) -> list[str]:
    warnings: list[str] = []
    for path in outliers:
        reason = _explain_outlier(features[path], features[medoid])
        warnings.append(f"Reference filter: {verb} {path.name} ({reason})")
    return warnings


def _top_differences(
    feature: ReferenceFeatures,
    reference: ReferenceFeatures,
    limit: int = 2,
) -> list[tuple[str, float, float, float]]:
    """Return (label, value, reference value, normalised difference)."""
    values: list[tuple[str, float, float, float]] = [
        (
            "luminance",
            feature.luminance,
            reference.luminance,
            abs(feature.luminance - reference.luminance) / _LIGHT_SCALES["luminance"],
        ),
        (
            "contrast",
            feature.contrast,
            reference.contrast,
            abs(feature.contrast - reference.contrast) / _EDIT_SCALES["contrast"],
        ),
        (
            "saturation",
            feature.saturation,
            reference.saturation,
            abs(feature.saturation - reference.saturation) / _EDIT_SCALES["saturation"],
        ),
        (
            "warmth",
            feature.warmth_rb,
            reference.warmth_rb,
            abs(feature.warmth_rb - reference.warmth_rb) / _EDIT_SCALES["warmth_rb"],
        ),
        (
            "shadows%",
            feature.shadows_pct,
            reference.shadows_pct,
            abs(feature.shadows_pct - reference.shadows_pct) / _EDIT_SCALES["shadows_pct"],
        ),
        (
            "highlights%",
            feature.highlights_pct,
            reference.highlights_pct,
            abs(feature.highlights_pct - reference.highlights_pct) / _EDIT_SCALES["highlights_pct"],
        ),
        (
            "texture",
            feature.high_freq,
            reference.high_freq,
            abs(feature.high_freq - reference.high_freq) / _EDIT_SCALES["high_freq"],
        ),
        (
            "vignette",
            feature.vignette,
            reference.vignette,
            abs(feature.vignette - reference.vignette) / _EDIT_SCALES["vignette"],
        ),
    ]
    return sorted(values, key=lambda item: item[3], reverse=True)[:limit]


def _explain_outlier(feature: ReferenceFeatures, reference: ReferenceFeatures) -> str:
    parts = []
    for label, value, ref_value, _ in _top_differences(feature, reference):
        if label in ("shadows%", "highlights%"):
            parts.append(f"{label} {value:.0%} vs {ref_value:.0%}")
        else:
            parts.append(f"{label} {value:.3f} vs {ref_value:.3f}")
    return "; ".join(parts)


def _tone_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    """Tone-only distance (contrast, dynamic range, curve shape, clipping)."""
    return _rms(
        [
            abs(a.contrast - b.contrast) / _EDIT_SCALES["contrast"],
            abs(a.dynamic_range - b.dynamic_range) / _EDIT_SCALES["dynamic_range"],
            _quantile_distance(a, b),
            abs(a.shadows_pct - b.shadows_pct) / _EDIT_SCALES["shadows_pct"],
            abs(a.highlights_pct - b.highlights_pct) / _EDIT_SCALES["highlights_pct"],
            abs(a.highlight_clip_pct - b.highlight_clip_pct) / _EDIT_SCALES["highlight_clip_pct"],
        ]
    )


def _edit_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    tone = _tone_distance(a, b)
    color = _rms(
        [
            abs(a.saturation - b.saturation) / _EDIT_SCALES["saturation"],
            abs(a.saturation_p90 - b.saturation_p90) / _EDIT_SCALES["saturation_p90"],
            abs(a.warmth_rb - b.warmth_rb) / _EDIT_SCALES["warmth_rb"],
            _zone_hue_distance(a, b),
            0.5 * _zone_saturation_distance(a, b),
        ]
    )
    if a.is_monochrome != b.is_monochrome:
        color = max(color, 0.75)
    processing = _rms(
        [
            abs(math.log1p(a.noise) - math.log1p(b.noise)) / _EDIT_SCALES["noise"],
            abs(a.gradient - b.gradient) / _EDIT_SCALES["gradient"],
            abs(a.high_freq - b.high_freq) / _EDIT_SCALES["high_freq"],
            abs(a.vignette - b.vignette) / _EDIT_SCALES["vignette"],
        ]
    )
    return 0.40 * tone + 0.40 * color + 0.20 * processing


def _light_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    return _rms(
        [
            abs(a.luminance - b.luminance) / _LIGHT_SCALES["luminance"],
            abs(a.contrast - b.contrast) / _LIGHT_SCALES["contrast"],
            abs(a.wb_rb - b.wb_rb) / _LIGHT_SCALES["wb_rb"],
            abs(a.warmth_rb - b.warmth_rb) / _LIGHT_SCALES["warmth_rb"],
            abs(a.shadows_pct - b.shadows_pct) / _LIGHT_SCALES["shadows_pct"],
            abs(a.highlights_pct - b.highlights_pct) / _LIGHT_SCALES["highlights_pct"],
        ]
    )


def _quantile_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    delta = (a.quantile_shape - b.quantile_shape) / _EDIT_SCALES["quantile_shape"]
    return _rms(delta.tolist())


def _zone_hue_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    values: list[float] = []
    for zone in _ZONES:
        ha = a.zone_hues.get(zone)
        hb = b.zone_hues.get(zone)
        ca = a.zone_confidences.get(zone, 0.0)
        cb = b.zone_confidences.get(zone, 0.0)
        if ha is not None and hb is not None and ca >= 0.5 and cb >= 0.5:
            weight = min(
                1.0,
                (a.zone_saturations.get(zone, 0.0) + b.zone_saturations.get(zone, 0.0)) / 0.20,
            )
            values.append((_circular_difference(ha, hb) / 180.0) * weight)
        elif (ha is None) != (hb is None):
            graded_sat = (
                a.zone_saturations.get(zone, 0.0)
                if ha is not None
                else b.zone_saturations.get(zone, 0.0)
            )
            values.append(0.35 * min(1.0, graded_sat / 0.15))
        else:
            values.append(0.0)
    return _rms(values)


def _zone_saturation_distance(a: ReferenceFeatures, b: ReferenceFeatures) -> float:
    return _rms(
        [
            abs(a.zone_saturations.get(zone, 0.0) - b.zone_saturations.get(zone, 0.0))
            / _EDIT_SCALES["zone_sat"]
            for zone in _ZONES
        ]
    )


def _circular_difference(a: float, b: float) -> float:
    d = abs(float(a) - float(b)) % 360.0
    return min(d, 360.0 - d)


def _rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    arr: np.ndarray = np.asarray(values, dtype=np.float64)
    return float(np.sqrt(np.mean(np.square(arr))))


def _vignette_strength(lum: np.ndarray) -> float:
    """Mean centre minus mean border luminance (positive = darker border)."""
    h, w = lum.shape
    if h < 4 or w < 4:
        return 0.0
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    centre = float(lum[y0:y1, x0:x1].mean())
    band_y = max(1, h // 10)
    band_x = max(1, w // 10)
    border = np.concatenate(
        [
            lum[:band_y, :].ravel(),
            lum[-band_y:, :].ravel(),
            lum[:, :band_x].ravel(),
            lum[:, -band_x:].ravel(),
        ]
    )
    return centre - float(border.mean())
