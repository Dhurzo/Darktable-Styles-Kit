"""Interface for VLM (Vision Language Model) clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VLMClient(ABC):
    """Port for calling Vision Language Models."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 2000,
        num_ctx: int = 8192,
        think: bool | str = False,
        json_mode: bool = False,
    ) -> str:
        """Generate a response from the VLM.

        Args:
            messages: List of message dictionaries in Ollama format.
            model: Model name override.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum output tokens.
            num_ctx: Context window size in tokens.
            think: Whether to enable thinking mode.
            json_mode: Whether to force JSON output.

        Returns:
            Raw response text from the VLM.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the VLM service is available.

        Returns:
            True if the service is reachable and has models loaded.
        """
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models.

        Returns:
            List of model names.
        """
        ...
