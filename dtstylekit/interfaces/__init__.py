"""Interfaces (Ports) for dtstylekit.

This module defines the abstract contracts (Ports) that the application
core depends on. Concrete implementations (Adapters) live in their
respective modules and implement these interfaces.

Following Clean Architecture: the inner layers (use cases, domain)
depend on abstractions, not concrete implementations.
"""

from .analyzer import ImageAnalyzer
from .image_encoder import ImageEncoder
from .preset_repository import PresetRepository
from .preset_searcher import PresetSearcher
from .reference_analyzer import ReferenceAnalyzer
from .style_generator import StyleGenerator
from .style_validator import StyleValidator
from .vlm_client import VLMClient

__all__ = [
    "ImageAnalyzer",
    "PresetSearcher",
    "VLMClient",
    "StyleGenerator",
    "StyleValidator",
    "ImageEncoder",
    "PresetRepository",
    "ReferenceAnalyzer",
]
