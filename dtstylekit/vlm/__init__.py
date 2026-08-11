"""VLM module: prompt building, Ollama client, response parsing, validation."""

from .client import VLMClient
from .models import (
    Plugin,
    ReportSection,
    StyleSpec,
    VLMRequest,
    VLMResponse,
    encode_image_b64,
)
from .orchestrator import generate_style_spec
from .parser import parse_response
from .prompt_builder import build_prompt
from .schema_renderer import render_iop_schema
from .validator import validate_style

__all__ = [
    "VLMClient",
    "VLMRequest",
    "VLMResponse",
    "StyleSpec",
    "Plugin",
    "ReportSection",
    "encode_image_b64",
    "build_prompt",
    "generate_style_spec",
    "parse_response",
    "render_iop_schema",
    "validate_style",
]
