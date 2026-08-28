"""Evaluation dataset construction and image categorisation.

Supports two corpus types required for full coverage:

* **Real / curated** images, auto-tagged into the categories the brief demands
  (RAW, display-referred, portrait, landscape, low-key, high-key, monochrome,
  colorful, no-reference).
* **Synthetic pairs**: a preset from the library is rendered onto a base image
  to *produce* a reference look; the harness then asks the VLM to recreate that
  look from the rendered image, giving an exact ground-truth target.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis

# The category vocabulary.  Multi-label: an image may carry several.
CATEGORIES = (
    "raw",
    "display_referred",
    "portrait",
    "landscape",
    "low_key",
    "high_key",
    "monochrome",
    "colorful",
    "no_reference",
)

_RAW_EXTS = {
    ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf",
    ".rw2", ".pef", ".sr2", ".srw", ".x3f", ".iiq", ".3fr",
}

# Style-direction matrix used to exercise different looks.  Each entry is a
# free-form direction string passed to the VLM.
STYLE_DIRECTIONS = (
    "cinematic warm portrait",
    "cool teal and orange film look",
    "high-key airy pastel",
    "low-key moody dramatic",
    "vintage faded sepia",
    "black and white fine-art",
    "vibrant travel landscape",
    "matte muted editorial",
    "cross-processed slide film",
    "neutral balanced documentary",
)


@dataclass
class EvalCase:
    """One evaluation instance.

    Attributes
    ----------
    name:
        Unique case id.
    base_image:
        The photo the style is generated *for* (analysis + VLM vision).
    reference_images:
        Look target(s).  Empty for the ``no_reference`` category (direction
        only).  For synthetic pairs this is the image produced by rendering the
        base with ``hidden_preset``.
    direction:
        Style direction string.
    tags:
        Multi-label category tags for the *base* image.
    ref_tags:
        Category tags describing the intended *look* (for synthetic pairs,
        derived from the preset; otherwise from the reference image).
    hidden_preset:
        Optional preset filename used to synthesise the reference look; kept so
        the harness can verify the preset is correctly rediscovered.
    """

    name: str
    base_image: Path
    direction: str
    reference_images: list[Path] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    ref_tags: set[str] = field(default_factory=set)
    hidden_preset: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_image": str(self.base_image),
            "direction": self.direction,
            "reference_images": [str(p) for p in self.reference_images],
            "tags": sorted(self.tags),
            "ref_tags": sorted(self.ref_tags),
            "hidden_preset": self.hidden_preset,
        }


def classify_image(
    image_path: str | Path,
    analysis: ImageAnalysis | None = None,
) -> set[str]:
    """Auto-tag an image into the evaluation categories.

    Relies on the file extension for RAW detection and on the precomputed
    :class:`ImageAnalysis` (luminance mean, saturation, scene tags) for the
    tonal / subject categories.  ``analysis`` is optional; without it only the
    RAW vs display-referred split is meaningful.
    """
    p = Path(image_path)
    tags: set[str] = set()

    if p.suffix.lower() in _RAW_EXTS:
        tags.add("raw")
    else:
        tags.add("display_referred")

    if analysis is not None:
        lum = getattr(getattr(analysis, "luminance", None), "mean", None)
        sat = getattr(getattr(analysis, "luminance", None), "saturation_mean", None)
        scene = getattr(analysis, "scene_tags", None) or []
        scene_l = {str(s).lower() for s in scene}

        if isinstance(lum, int | float) and not isinstance(lum, bool):
            if lum < 0.3:
                tags.add("low_key")
            elif lum > 0.7:
                tags.add("high_key")
        if isinstance(sat, int | float) and not isinstance(sat, bool):
            if sat < 0.05:
                tags.add("monochrome")
            elif sat > 0.25:
                tags.add("colorful")
        if "portrait" in scene_l:
            tags.add("portrait")
        if "landscape" in scene_l:
            tags.add("landscape")

    return tags


def build_synthetic_pairs(
    preset_paths: list[Path],
    base_images: list[Path],
    renderer: Callable,
    out_dir: Path,
    direction: str | None = None,
    limit: int | None = None,
) -> list[EvalCase]:
    """Build synthetic (base, reference-look) pairs from presets.

    For each preset, ``renderer(base, preset_path) -> reference_image`` renders
    the preset onto a base photo to create the *target look*.  The VLM is then
    asked to recreate that look from the reference image alone (the preset is
    hidden), giving an exact ground-truth target for :func:`compare_looks`.

    Args:
        preset_paths: Candidate ``.dtstyle`` presets.
        base_images: Neutral base photos to render presets onto.
        renderer: Callable(base: Path, preset: Path, out: Path) -> Path | None.
        out_dir: Where reference images are written.
        direction: Override direction; defaults to the preset's stem name.
        limit: Cap the number of pairs (for a quick smoke run).

    Returns:
        List of :class:`EvalCase` with ``reference_images`` populated and
        ``hidden_preset`` set.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[EvalCase] = []

    for preset in preset_paths:
        if limit is not None and len(cases) >= limit:
            break
        for base in base_images:
            ref_out = out_dir / f"{preset.stem}__on__{base.stem}.jpg"
            rendered = renderer(base, preset, ref_out)
            if rendered is None:
                continue
            cases.append(
                EvalCase(
                    name=f"{preset.stem}__on__{base.stem}",
                    base_image=base,
                    direction=direction or preset.stem.replace("_", " "),
                    reference_images=[rendered],
                    ref_tags={"synthetic", preset.stem},
                    hidden_preset=preset.name,
                )
            )
            break  # one base image per preset is enough for the matrix
    return cases


def build_no_reference_cases(
    base_images: list[Path],
    directions: tuple[str, ...] = STYLE_DIRECTIONS,
) -> list[EvalCase]:
    """Cases with *no* reference look — direction only.

    Exercises the "valid for every ... style" requirement when the VLM must
    invent the look from the direction string alone.  Look-fidelity cannot be
    computed (no target), so these cases are scored structurally only.
    """
    cases: list[EvalCase] = []
    for base in base_images:
        for d in directions:
            cases.append(
                EvalCase(
                    name=f"{base.stem}__dir__{d.replace(' ', '_')}",
                    base_image=base,
                    direction=d,
                    reference_images=[],
                    tags={"no_reference"},
                )
            )
    return cases
