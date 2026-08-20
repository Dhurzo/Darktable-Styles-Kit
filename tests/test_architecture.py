"""Tests for the Clean Architecture layers (ports, DI container, use cases).

Regression coverage for the architecture introduced in the
"Clean Architecture & SOLID improvements" refactor: the ports package,
the DI container and the use cases must be importable and functional at
runtime (they previously raised NameError and had no tests at all).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.di.container import DIContainer
from dtstylekit.di.services import configure_services
from dtstylekit.interfaces import (
    ImageAnalyzer,
    ImageEncoder,
    PresetRepository,
    ReferenceAnalyzer,
    StyleGenerator,
    StyleValidator,
    VLMClient,
)
from dtstylekit.interfaces import (
    PresetSearcher as IPresetSearcher,
)
from dtstylekit.presets.models import PresetIndexEntry
from dtstylekit.presets.search import PresetSearcher, SearchResult
from dtstylekit.use_cases import (
    GenerateStyleUseCase,
    IndexPresetsUseCase,
    RefineStyleUseCase,
    SearchPresetsUseCase,
    ValidateStyleUseCase,
)
from dtstylekit.vlm.iterative_refiner import (
    RefinementResult,
    iterative_refine,
)
from dtstylekit.vlm.models import StyleSpec


class TestArchitectureImports:
    """The refactor must be importable at runtime (regression for NameError)."""

    def test_interfaces_package_imports(self) -> None:
        import dtstylekit.interfaces  # noqa: F401

    def test_di_services_imports_without_side_effect(self) -> None:
        import dtstylekit.di.services  # noqa: F401

    def test_cli_new_imports(self) -> None:
        import dtstylekit.cli_new  # noqa: F401

    def test_use_cases_imports(self) -> None:
        import dtstylekit.use_cases  # noqa: F401


class TestDIContainer:
    def test_fresh_container_is_empty(self) -> None:
        c = DIContainer()
        assert not c.is_registered(dict)
        with pytest.raises(KeyError):
            c.resolve(dict)

    def test_singleton_registration(self) -> None:
        c = DIContainer()

        class Impl:
            pass

        c.register_singleton(Impl, Impl)
        assert c.resolve(Impl) is c.resolve(Impl)

    def test_transient_registration(self) -> None:
        c = DIContainer()

        class Impl:
            pass

        c.register_transient(Impl, Impl)
        assert c.resolve(Impl) is not c.resolve(Impl)

    def test_factory_registration(self) -> None:
        from dataclasses import dataclass

        c = DIContainer()

        @dataclass
        class Impl:
            value: int

        c.register_factory(Impl, lambda _c: Impl(42))
        assert c.resolve(Impl).value == 42

    def test_instance_registration(self) -> None:
        c = DIContainer()
        instance = object()
        c.register_instance(type(instance), instance)
        assert c.resolve(type(instance)) is instance

    def test_abstract_interface_resolution(self) -> None:
        class FakeEncoder(ImageEncoder):
            def encode(self, _image_path, _max_dim=768, _quality=88):
                return None

            def encode_batch(self, _image_paths, _max_dim=768, _quality=88):
                return []

        c = DIContainer()
        c.register_singleton(ImageEncoder, FakeEncoder)
        assert isinstance(c.resolve(ImageEncoder), FakeEncoder)

    def test_unknown_resolution_raises_key_error(self) -> None:
        c = DIContainer()
        with pytest.raises(KeyError):
            c.resolve(StyleGenerator)

    def test_try_resolve_returns_none(self) -> None:
        c = DIContainer()
        assert c.try_resolve(StyleGenerator) is None

    def test_clear(self) -> None:
        c = DIContainer()

        class Impl:
            pass

        c.register_singleton(Impl, Impl)
        c.clear()
        assert not c.is_registered(Impl)

    def test_child_container_copies_registrations(self) -> None:
        c = DIContainer()

        class Impl:
            pass

        c.register_singleton(Impl, Impl)
        child = c.create_child_container()
        assert child.is_registered(Impl)
        child.register_singleton(Impl, Impl)
        # Parent is unaffected by child registrations
        assert c.resolve(Impl) is not child.resolve(Impl)


class TestConfigureServices:
    def test_configures_all_ports_and_use_cases(self) -> None:
        c = DIContainer()
        configure_services(c)

        for port in (
            ImageAnalyzer,
            ImageEncoder,
            PresetRepository,
            IPresetSearcher,
            ReferenceAnalyzer,
            StyleGenerator,
            StyleValidator,
            VLMClient,
        ):
            assert c.is_registered(port), port

        for use_case in (
            GenerateStyleUseCase,
            IndexPresetsUseCase,
            RefineStyleUseCase,
            SearchPresetsUseCase,
            ValidateStyleUseCase,
        ):
            assert c.resolve(use_case) is not None, use_case

    def test_no_auto_configuration_on_global_container(self) -> None:
        """Importing di.services must not mutate the global container."""
        import subprocess
        import sys

        code = (
            "from dtstylekit.di.container import get_container;"
            "from dtstylekit.di import services;"
            "from dtstylekit.use_cases import GenerateStyleUseCase;"
            "c = get_container();"
            "assert not c.is_registered(GenerateStyleUseCase), 'import side effect'"
        )
        subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parent.parent)

    def test_plain_dict_is_not_a_service_key(self) -> None:
        c = DIContainer()
        configure_services(c)
        with pytest.raises(KeyError):
            c.resolve(dict)


class TestUseCases:
    def test_refine_style_use_case_reports_real_outcome(self, tmp_path, monkeypatch) -> None:
        generated = StyleSpec(style_name="refined")
        ref_file = tmp_path / "ref.jpg"
        ref_file.write_bytes(b"jpeg")

        class StubGenerator(StyleGenerator):
            def generate(
                self,
                image_path,  # noqa: ARG002
                direction,  # noqa: ARG002
                references=None,  # noqa: ARG002
                refine_iterations=0,  # noqa: ARG002
                refine_raw_path=None,  # noqa: ARG002
            ):
                return generated, "report", [], ImageAnalysis()

            def generate_spec_only(self, image_path, direction, references=None):  # noqa: ARG002
                return generated

        class FakeMetrics:
            mean_luminance = 0.4
            std_luminance = 0.1
            mean_saturation = 0.2
            r_mean = 0.5
            g_mean = 0.5
            b_mean = 0.4
            r_over_g = 1.0
            shadows_pct = 0.1
            highlights_pct = 0.1
            has_red_cast = False
            is_crushed = False
            is_blown = False

        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.render_with_style",
            lambda *_a, **_k: Path("rendered.jpg"),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.compute_render_metrics",
            lambda _p: FakeMetrics(),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.evaluate_metrics",
            lambda _m, _t: (True, []),
        )

        use_case = RefineStyleUseCase(StubGenerator())
        response = use_case.execute(
            type(
                "Request",
                (),
                {
                    "raw_path": tmp_path / "fake.raw",
                    "reference_paths": [ref_file],
                    "direction": "warm",
                    "target_analysis": ImageAnalysis(),
                    "max_iterations": 3,
                    "work_dir": tmp_path / "work",
                },
            )()
        )

        assert response.passed is True
        assert response.iterations_completed == 1
        assert response.refined_spec is generated

    def test_refine_use_case_exhausts_iterations_when_never_passing(
        self, tmp_path, monkeypatch
    ) -> None:
        generated = StyleSpec(style_name="refined")
        ref_file = tmp_path / "ref.jpg"
        ref_file.write_bytes(b"jpeg")

        class StubGenerator(StyleGenerator):
            def generate(
                self,
                image_path,  # noqa: ARG002
                direction,  # noqa: ARG002
                references=None,  # noqa: ARG002
                refine_iterations=0,  # noqa: ARG002
                refine_raw_path=None,  # noqa: ARG002
            ):
                return generated, "report", [], ImageAnalysis()

            def generate_spec_only(self, image_path, direction, references=None):  # noqa: ARG002
                return generated

        class FakeMetrics:
            mean_luminance = 0.1
            std_luminance = 0.1
            mean_saturation = 0.02
            r_mean = 0.6
            g_mean = 0.3
            b_mean = 0.3
            r_over_g = 2.0
            shadows_pct = 0.6
            highlights_pct = 0.02
            has_red_cast = True
            is_crushed = True
            is_blown = False

        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.render_with_style",
            lambda *_a, **_k: Path("rendered.jpg"),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.compute_render_metrics",
            lambda _p: FakeMetrics(),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.evaluate_metrics",
            lambda _m, _t: (False, ["too dark"]),
        )

        use_case = RefineStyleUseCase(StubGenerator())
        response = use_case.execute(
            type(
                "Request",
                (),
                {
                    "raw_path": tmp_path / "fake.raw",
                    "reference_paths": [ref_file],
                    "direction": "warm",
                    "target_analysis": ImageAnalysis(),
                    "max_iterations": 2,
                    "work_dir": tmp_path / "work",
                },
            )()
        )

        assert response.passed is False
        assert response.iterations_completed == 2
        assert response.refined_spec is generated


class TestIterativeRefine:
    def test_zero_iterations_generates_once_without_render(self, tmp_path: Path) -> None:
        calls = []

        def generate_func(direction: str, _ref_b64s: list[str]) -> StyleSpec:
            calls.append(direction)
            return StyleSpec(style_name="spec")

        ref = tmp_path / "ref.jpg"
        ref.write_bytes(b"jpeg")

        result = iterative_refine(
            raw_path=tmp_path / "raw.raw",
            reference_paths=[ref],
            direction="warm",
            target_analysis=ImageAnalysis(),
            generate_func=generate_func,
            max_iterations=0,
            work_dir=tmp_path / "work",
        )

        assert isinstance(result, RefinementResult)
        assert len(calls) == 1
        assert result.iterations_completed == 0
        assert result.passed is False
        assert result.spec.style_name == "spec"

    def test_pass_returns_iteration_count(self, tmp_path: Path, monkeypatch) -> None:
        def generate_func(_direction: str, _ref_b64s: list[str]) -> StyleSpec:
            return StyleSpec(style_name="spec")

        class FakeMetrics:
            mean_luminance = 0.4
            std_luminance = 0.1
            mean_saturation = 0.2
            r_mean = 0.5
            g_mean = 0.5
            b_mean = 0.4
            r_over_g = 1.0
            shadows_pct = 0.1
            highlights_pct = 0.1
            has_red_cast = False
            is_crushed = False
            is_blown = False

        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.render_with_style",
            lambda *_a, **_k: Path("rendered.jpg"),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.compute_render_metrics",
            lambda _p: FakeMetrics(),
        )
        monkeypatch.setattr(
            "dtstylekit.vlm.iterative_refiner.evaluate_metrics",
            lambda _m, _t: (True, []),
        )

        ref = tmp_path / "ref.jpg"
        ref.write_bytes(b"jpeg")

        result = iterative_refine(
            raw_path=tmp_path / "raw.raw",
            reference_paths=[ref],
            direction="warm",
            target_analysis=ImageAnalysis(),
            generate_func=generate_func,
            max_iterations=3,
            work_dir=tmp_path / "work",
        )

        assert result.passed is True
        assert result.iterations_completed == 1


class TestPresetSearcherDelegation:
    def test_get_preset_by_id_and_list_presets_delegate(self, tmp_path: Path) -> None:
        from dtstylekit.presets.indexer import PresetIndexer

        db_path = tmp_path / "index.db"
        with PresetIndexer(db_path) as idx:
            idx.connect()

        searcher = PresetSearcher(db_path)
        assert searcher.get_preset_by_id(0) is None
        assert searcher.list_presets() == []
        searcher.close()

    def test_search_result_roundtrip(self) -> None:
        entry = PresetIndexEntry(
            id=1,
            name="sepia",
            description="",
            iop_list="",
            plugin_count=0,
            xml_hash="",
            display_name="Sepia",
            category="examples",
        )
        result = SearchResult(preset=entry, score=0.9, search_type="hybrid")
        assert result.preset.id == 1
        assert result.score == 0.9
