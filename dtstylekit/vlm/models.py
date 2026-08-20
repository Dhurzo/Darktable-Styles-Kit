"""Data models for the VLM (Vision Language Model) integration layer.

These dataclasses are the *contract* between three parties:

* The :mod:`prompt_builder` – which constructs the outgoing Ollama request.
* The :mod:`client` – which performs the actual HTTP call to Ollama.
* The :mod:`parser` and :mod:`validator` – which consume the raw text
  response, transform it into a strongly-typed :class:`StyleSpec`, and
  clamp parameters against :data:`dtstylekit.codec.iop_registry.IOP_REGISTRY`.

The design follows ``glm5Generated/ai_integration_notes.md`` §2.2 / §5:

* The LLM emits **only** a JSON object plus an optional ``---REPORT---``
  markdown explanation.
* The JSON shape is *partial*: each plugin only includes the params it
  wants to override. Defaults come from the registry and are merged by
  :func:`dtstylekit.vlm.validator.validate_style`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Request / response containers
# ---------------------------------------------------------------------------


@dataclass
class VLMRequest:
    """A request ready to be sent to the Ollama client.

    The ``messages`` field follows the Ollama chat API format — see
    https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion
    — i.e. a list of ``{"role": ..., "content": ..., "images": [...]}``
    dicts.

    Attributes
    ----------
    messages:
        Ollama-formatted chat messages (system + user).  Images are
        inlined as base64 strings inside the ``images`` list.
    model:
        Target Ollama model tag, e.g. ``"gemma3:4b"`` or ``"llava:7b"``.
    temperature:
        Sampling temperature in ``[0.0, 1.0]``.  ``ai_integration_notes.md``
        §6 recommends ``0.3-0.5`` for consistent style generation.
    options:
        Additional Ollama ``options`` dict (e.g. ``top_p``, ``top_k``,
        ``repeat_penalty``).
    image_path:
        Optional path to the source image — kept on the request so
        callers don't need to thread it through separately.
    direction:
        The user-supplied style direction.  ``"auto"`` means the
        orchestrator should derive the direction from the image analysis.
    """

    messages: list[dict[str, Any]]
    model: str = "gemma3:27b"
    temperature: float = 0.4
    options: dict[str, Any] = field(default_factory=dict)
    image_path: Path | None = None
    direction: str = "auto"

    def __post_init__(self) -> None:
        """Light validation of construction input.

        Keeps us robust with very small / very-chilled VLMs — we never
        let a malformed request reach the network layer.
        """
        if not self.messages:
            raise ValueError("VLMRequest.messages must contain at least one entry")
        if not (0.0 <= self.temperature <= 1.0):
            raise ValueError(f"temperature must be in [0.0, 1.0], got {self.temperature}")
        if not self.model.strip():
            raise ValueError("VLMRequest.model must be a non-empty string")


@dataclass
class VLMResponse:
    """The response produced by :class:`VLMClient`.

    Holds both the *raw* text returned by the model and a small amount
    of metadata that downstream code (the orchestrator in particular)
    uses for logging and report generation.
    """

    text: str
    model: str = ""
    elapsed_seconds: float = 0.0
    prompt_eval_count: int = 0
    eval_count: int = 0
    ok: bool = True
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        """``True`` when the model returned nothing usable."""
        return not self.text or not self.text.strip()


# ---------------------------------------------------------------------------
# Parsed style — the schema we extract from the raw response
# ---------------------------------------------------------------------------


@dataclass
class Plugin:
    """One darktable plugin entry inside a :class:`StyleSpec`.

    Attributes
    ----------
    operation:
        IOP operation name (e.g. ``"colorbalancergb"``).  Must be a key
        of ``IOP_REGISTRY`` — the validator enforces this.
    enabled:
        Equivalent to darktable's "instance enabled" flag.
    multi_name:
        Optional instance label (multi-instance).  Empty string for
        the default instance.
    multi_priority:
        Priority for multi-instance ordering; positive integers only.
    params:
        *Partial* parameter dict.  Only fields that differ from the
        registry default.  All other fields are filled in by the
        validator.
    """

    operation: str
    enabled: bool = True
    multi_name: str = ""
    multi_priority: int = 0
    params: dict[str, float | int] = field(default_factory=dict)


@dataclass
class StyleSpec:
    """A parsed and validated darktable style spec.

    Built progressively: :func:`dtstylekit.vlm.parser.parse_response`
    produces a *raw* instance straight from the LLM JSON.  The
    validator (:func:`dtstylekit.vlm.validator.validate_style`) then
    clamps parameters, merges defaults, and emits warnings.
    """

    style_name: str = ""
    style_description: str = ""
    iop_list: str | None = None
    plugins: list[Plugin] = field(default_factory=list)
    # Filenames (e.g. "examples_colors_sepia.dtstyle") that the VLM chose
    # as base presets.  The composer loads + merges these before applying
    # ``plugins`` scalar adjustments.  Populated from the ``selected_presets``
    # JSON field the prompt asks the VLM to emit.
    selected_preset_names: list[str] = field(default_factory=list)
    # Free-form rationale the VLM emits in its JSON.  Surfaced in the
    # markdown report when the separate ``---REPORT---`` section is not
    # produced (the minimalist SYSTEM_PROMPT doesn't request that section).
    rationale: str = ""

    @property
    def operations(self) -> list[str]:
        """List of operations in pipeline order."""
        return [p.operation for p in self.plugins]

    @property
    def enabled_operations(self) -> list[str]:
        """Only enabled operations."""
        return [p.operation for p in self.plugins if p.enabled]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict representation (matches the LLM schema)."""
        return {
            "style_name": self.style_name,
            "style_description": self.style_description,
            "rationale": self.rationale,
            "iop_list": self.iop_list,
            "selected_presets": list(self.selected_preset_names),
            "plugins": [
                {
                    "operation": p.operation,
                    "enabled": p.enabled,
                    "multi_name": p.multi_name,
                    "multi_priority": p.multi_priority,
                    "params": dict(p.params),
                }
                for p in self.plugins
            ],
        }


@dataclass
class ReportSection:
    """Free-form ``---REPORT---`` markdown that follows the JSON.

    The LLM produces a single markdown blob — we keep it as-is.  If the
    blob is missing, the orchestrator synthesises one from the spec.
    """

    text: str = ""
    auto_generated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()


# ---------------------------------------------------------------------------
# Image embedding helpers
# ---------------------------------------------------------------------------


def encode_image_b64(image_path: str | Path) -> str:
    """Encode an image file to a base64 string suitable for Ollama.

    Returns the bare string (no ``data:image/...`` URI prefix) because
    Ollama accepts the raw base64 blob.

    Raises
    ------
    FileNotFoundError:
        If ``image_path`` does not exist.
    OSError:
        If the file exists but cannot be read.
    """
    return base64.b64encode(Path(image_path).read_bytes()).decode("ascii")


__all__ = [
    "VLMRequest",
    "VLMResponse",
    "Plugin",
    "StyleSpec",
    "ReportSection",
    "encode_image_b64",
]
