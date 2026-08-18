"""Service registration for dtstylekit DI container.

This module registers all concrete implementations with the DI container.
Importing it has no side effects: call :func:`configure_services` explicitly
at application startup (e.g. from the CLI entry point).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from dtstylekit.interfaces import (
    ImageAnalyzer,
    ImageEncoder,
    PresetRepository,
    ReferenceAnalyzer,
    StyleGenerator,
    StyleValidator,
)
from dtstylekit.interfaces import PresetSearcher as IPresetSearcher
from dtstylekit.interfaces import VLMClient as IVLMClient

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.di.container import DIContainer
    from dtstylekit.interfaces.preset_searcher import SearchResult
    from dtstylekit.presets.indexer import PresetIndexer
    from dtstylekit.presets.models import Preset, PresetIndexEntry
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.models import StyleSpec

from dtstylekit.di.container import get_container

logger = logging.getLogger(__name__)


def configure_services(container: DIContainer | None = None) -> None:
    """Register all services with the DI container.

    This function should be called once at application startup.

    Args:
        container: Container to configure (defaults to the global one).
    """
    container = container or get_container()

    # Import implementations here to avoid circular imports
    from dtstylekit.analyzer.pipeline import analyze_image as _analyze_image
    from dtstylekit.paths import get_outputs_dir
    from dtstylekit.presets.indexer import PresetIndexer
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.client import VLMClient

    # --- Singletons (stateless services) ---

    # Image Analyzer - stateless function
    container.register_factory(
        ImageAnalyzer,
        lambda _c: _ImageAnalyzerAdapter(_analyze_image),
    )

    # VLM Client - stateless, can be singleton
    container.register_singleton(IVLMClient, VLMClient)

    # --- Transients (stateful or config-dependent) ---

    # Concrete PresetSearcher - needs DB paths, created per resolve
    def _create_concrete_searcher() -> PresetSearcher:
        outputs_dir = get_outputs_dir()
        return PresetSearcher(outputs_dir / "presets.db", outputs_dir / "preset_embeddings.npy")

    container.register_factory(PresetSearcher, lambda _c: _create_concrete_searcher())

    # Preset Searcher adapter - wraps the concrete searcher
    container.register_factory(
        IPresetSearcher,
        lambda c: _PresetSearcherAdapter(c.resolve(PresetSearcher)),
    )

    # Style Generator - composed of multiple services
    container.register_factory(
        StyleGenerator,
        lambda c: _StyleGeneratorAdapter(c.resolve(PresetSearcher)),
    )

    # Style Validator - stateless
    container.register_singleton(StyleValidator, _StyleValidatorAdapter)

    # Image Encoder - stateless
    container.register_singleton(ImageEncoder, _ImageEncoderAdapter)

    # Preset Repository - needs index path
    def _create_preset_repository() -> _PresetRepositoryAdapter:
        outputs_dir = get_outputs_dir()
        index_path = outputs_dir / "presets.db"
        indexer = PresetIndexer(index_path) if index_path.exists() else None
        return _PresetRepositoryAdapter(indexer)

    container.register_factory(PresetRepository, lambda _c: _create_preset_repository())

    # Reference Analyzer - stateless
    container.register_singleton(ReferenceAnalyzer, _ReferenceAnalyzerAdapter)

    # --- Use Cases ---
    # Use cases are stateless - register as singletons
    from dtstylekit.use_cases import (
        GenerateStyleUseCase,
        IndexPresetsUseCase,
        RefineStyleUseCase,
        SearchPresetsUseCase,
        ValidateStyleUseCase,
    )

    container.register_factory(
        GenerateStyleUseCase,
        lambda c: GenerateStyleUseCase(
            style_generator=c.resolve(StyleGenerator),
            image_encoder=c.resolve(ImageEncoder),
            preset_repository=c.resolve(PresetRepository),
        ),
    )

    container.register_factory(
        SearchPresetsUseCase,
        lambda c: SearchPresetsUseCase(
            preset_searcher=c.resolve(IPresetSearcher),
        ),
    )

    container.register_factory(
        IndexPresetsUseCase,
        lambda c: IndexPresetsUseCase(
            preset_repository=c.resolve(PresetRepository),
        ),
    )

    container.register_factory(
        ValidateStyleUseCase,
        lambda c: ValidateStyleUseCase(
            style_validator=c.resolve(StyleValidator),
        ),
    )

    container.register_factory(
        RefineStyleUseCase,
        lambda c: RefineStyleUseCase(
            style_generator=c.resolve(StyleGenerator),
        ),
    )


# --- Adapter classes ---


class _ImageAnalyzerAdapter(ImageAnalyzer):
    """Adapter for the analyze_image function."""

    def __init__(self, analyze_func: Callable[[str | Path], ImageAnalysis]) -> None:
        self._analyze = analyze_func

    def analyze(self, image_path: str | Path) -> ImageAnalysis:
        return self._analyze(image_path)

    def analyze_reference_hues(self, reference_paths: list[Path]) -> dict:
        from dtstylekit.analyzer.pipeline import analyze_reference_hues

        return analyze_reference_hues(reference_paths)


class _StyleGeneratorAdapter(StyleGenerator):
    """Adapter for the generate_style_spec function."""

    def __init__(self, searcher: PresetSearcher) -> None:
        self._searcher = searcher

    def generate(
        self,
        image_path: str | Path,
        direction: str,
        references: list[str | Path] | None = None,
        refine_iterations: int = 0,
        refine_raw_path: str | Path | None = None,
    ) -> tuple[StyleSpec, str, list[str], ImageAnalysis]:
        from dtstylekit.analyzer.pipeline import analyze_image
        from dtstylekit.codec.iop_registry import IOP_REGISTRY
        from dtstylekit.vlm.orchestrator import generate_style_spec

        return generate_style_spec(
            image_path=image_path,
            direction=direction,
            searcher=self._searcher,
            analyzer=analyze_image,
            registry=IOP_REGISTRY,
            references=references,
            refine_iterations=refine_iterations,
            refine_raw_path=refine_raw_path,
        )

    def generate_spec_only(
        self,
        image_path: str | Path,
        direction: str,
        references: list[str | Path] | None = None,
    ) -> StyleSpec:
        # Same as generate but without refinement
        return self.generate(image_path, direction, references, 0, None)[0]


class _StyleValidatorAdapter(StyleValidator):
    """Adapter for the validate_style function."""

    def __init__(self) -> None:
        from dtstylekit.vlm.validator import validate_style

        self._validate = validate_style

    def validate(
        self,
        spec: StyleSpec,
        registry: dict,
        reference_analysis: dict | None = None,
        target_analysis: ImageAnalysis | None = None,
    ) -> tuple[StyleSpec, list[str]]:
        validated, warnings = self._validate(
            spec,
            registry,
            reference_analysis=reference_analysis,
            target_analysis=target_analysis,
        )
        return validated, warnings

    def validate_xml_structure(self, dtstyle_path: str | Path) -> list[str]:
        from dtstylekit.composer.roundtrip import validate_xml_structure

        return validate_xml_structure(Path(dtstyle_path))

    def validate_blobs(self, dtstyle_path: str | Path) -> list[str]:
        from dtstylekit.composer.roundtrip import validate_plugin_blobs

        return validate_plugin_blobs(Path(dtstyle_path))


class _ImageEncoderAdapter(ImageEncoder):
    """Adapter for image encoding."""

    def encode(self, image_path: str | Path, max_dim: int = 768, quality: int = 88) -> str | None:
        import base64
        import io

        from PIL import Image

        try:
            img = Image.open(image_path)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")  # type: ignore[assignment]
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as exc:
            logger.debug("Failed to encode image %s: %s", image_path, exc)
            return None

    def encode_batch(
        self, image_paths: list[str | Path], max_dim: int = 768, quality: int = 88
    ) -> list[str]:
        results: list[str] = []
        for p in image_paths:
            encoded = self.encode(p, max_dim, quality)
            if encoded is not None:
                results.append(encoded)
        return results


class _PresetRepositoryAdapter(PresetRepository):
    """Adapter for preset repository operations."""

    def __init__(self, indexer: PresetIndexer | None):
        self._indexer = indexer

    def load_preset(self, path: Path) -> Preset | None:
        from dtstylekit.presets.parser import parse_preset

        return parse_preset(path)

    def resolve_preset(self, name: str) -> Preset | None:
        from pathlib import Path

        from dtstylekit.paths import get_presets_dir

        # Try index first
        if self._indexer:
            conn = self._indexer.connect()
            target = Path(name).name
            row = conn.execute(
                "SELECT file_path FROM presets WHERE file_path = ? OR file_path LIKE ? LIMIT 1",
                (name, f"%{target}"),
            ).fetchone()
            if row and row["file_path"]:
                return self.load_preset(Path(row["file_path"]))

            row = conn.execute(
                "SELECT file_path FROM presets WHERE display_name = ? LIMIT 1", (name,)
            ).fetchone()
            if row and row["file_path"]:
                return self.load_preset(Path(row["file_path"]))

        # Fallback: search preset dirs
        for d in (get_presets_dir(), Path("data/presets"), Path("../../data/styles")):
            if not d.exists():
                continue
            direct = d / Path(name).name
            if direct.exists():
                return self.load_preset(direct)

        return None

    def load_selected_presets(self, preset_names: list[str], warnings: list[str]) -> list[Preset]:
        presets: list[Preset] = []
        for name in preset_names:
            if not name:
                continue
            p = self.resolve_preset(name)
            if p is None:
                warnings.append(f"Preset not found: {name}")
                continue
            presets.append(p)
        return presets

    def index_presets(self, preset_dir: Path) -> int:
        from dtstylekit.paths import get_outputs_dir
        from dtstylekit.presets.indexer import PresetIndexer

        index_path = get_outputs_dir() / "presets.db"
        indexer = PresetIndexer(index_path)
        indexer.connect()

        from dtstylekit.presets.parser import parse_all_presets

        presets = parse_all_presets(preset_dir)
        count = indexer.index_presets(presets)
        return count


class _ReferenceAnalyzerAdapter(ReferenceAnalyzer):
    """Adapter for reference analysis."""

    def analyze_hues(self, reference_paths: list[Path]) -> dict:
        from dtstylekit.analyzer.pipeline import analyze_reference_hues

        return analyze_reference_hues(reference_paths)

    def compute_global_saturation(self, reference_paths: list[Path]) -> float:
        from dtstylekit.analyzer.pipeline import analyze_image

        sats = []
        for ref in reference_paths:
            try:
                a = analyze_image(ref)
                s = getattr(getattr(a, "luminance", None), "saturation_mean", None)
                if s is not None:
                    sats.append(float(s))
            except Exception as exc:
                logger.warning("Failed to analyze reference image %s: %s", ref, exc)
                continue
        return sum(sats) / len(sats) if sats else 0.0


class _PresetSearcherAdapter(IPresetSearcher):
    """Adapter for the concrete PresetSearcher."""

    def __init__(self, searcher: PresetSearcher) -> None:
        self._searcher = searcher

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return self._searcher.hybrid_search(query, limit)

    def keyword_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._searcher.keyword_search(query, limit)

    def semantic_search(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._searcher.semantic_search(query, limit)

    def hybrid_search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return self._searcher.hybrid_search(query, limit)

    def get_preset_by_id(self, preset_id: int) -> PresetIndexEntry | None:
        return self._searcher.get_preset_by_id(preset_id)

    def list_presets(self, category: str | None = None) -> list[PresetIndexEntry]:
        return self._searcher.list_presets(category)
