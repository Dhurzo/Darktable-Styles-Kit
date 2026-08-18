"""Ollama VLM client with retries and timeout handling."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

try:
    import ollama  # type: ignore
except ImportError:
    ollama = None  # type: ignore

logger = logging.getLogger(__name__)


class VLMClient:
    """Wrapper around Ollama VLM inference.

    Args:
        host: Ollama API endpoint (default: localhost:11434).
        default_model: Default VLM model (e.g., 'gemma3:12b', 'llava:7b').
        timeout: Request timeout in seconds.
        max_retries: Number of retries on transient errors.
    """

    _client: ollama.Client | None

    def __init__(
        self,
        host: str | None = None,
        default_model: str = "gemma3:27b",
        timeout: float = 3600.0,
        max_retries: int = 1,
    ) -> None:
        # Allow overriding the Ollama endpoint via OLLAMA_HOST (e.g. to
        # point at a user-run server on a non-default port).  An explicit
        # host argument always wins.
        #
        # ``timeout`` defaults to 1 hour: on CPU-only machines a single
        # gemma3:12b generation routinely takes 10-30 minutes, and the
        # old 300 s default made the client time out mid-generation,
        # retry from scratch, and never make progress.
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        if ollama is not None:
            try:
                self._client = ollama.Client(host=self.host, timeout=self.timeout)
            except Exception as e:
                logger.warning("Ollama client init failed: %s", e)
                self._client = None
        else:
            self._client = None

    def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 2000,
        num_ctx: int = 8192,
        think: bool | str = True,
        json_mode: bool = False,
    ) -> str:
        """Generate a response from the VLM.

        Args:
            messages: Ollama-format messages list.
            model: Model name (overrides default).
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum output tokens (Ollama ``num_predict``).
            num_ctx: Context window size in tokens.  Ollama defaults to
                4096 for ``gemma3:12b`` which is too small for our
                prompt (image analysis + candidate presets + IOP schema
                easily exceeds 4k tokens).  8192 leaves headroom.
            think: Whether to use the model's thinking mode.  ``True``
                (default for gemma3:12b) lets the model do its
                chain-of-thought into ``message.thinking`` and write
                the FINAL answer into ``message.content``.  Empirically
                ``think=False`` makes gemma3 put everything into the
                ``thinking`` field and leave ``content`` empty (the
                model is hard-wired to think first).  Pass ``False`` for
                non-thinking models, or one of
                ``"low"/"medium"/"high"`` for budgeted thinking.
            json_mode: When True, ask Ollama to enforce JSON output via
                ``format='json'``.  NOTE: this strips the markdown
                ``---REPORT---`` section the prompt asks for — the model
                can only emit a single JSON object.  Default ``False``
                so we get both JSON + report; the robust parser
                recovers JSON even from prose-wrapped responses.

        Returns:
            Generated text from the VLM.
        """
        model_name = model or self.default_model
        if self._client is None and ollama is not None:
            try:
                self._client = ollama.Client(host=self.host, timeout=self.timeout)
            except Exception as e:
                raise RuntimeError(f"Ollama client unavailable: {e}") from e

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if ollama is not None and self._client is not None:
                    kwargs: dict[str, Any] = {
                        "model": model_name,
                        "messages": messages,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                            "num_ctx": num_ctx,
                        },
                        "think": think,
                    }
                    if json_mode:
                        kwargs["format"] = "json"
                    resp = self._client.chat(**kwargs)
                    msg = resp.get("message", {}) or {}
                    content = msg.get("content") or ""
                    # gemma3:12b sometimes routes the entire answer into
                    # ``thinking`` and leaves ``content`` empty even with
                    # ``think=True``.  When that happens fall back to the
                    # thinking field so the downstream parser still sees a
                    # payload instead of silently returning "".
                    if not content.strip():
                        thinking = msg.get("thinking") or ""
                        if thinking.strip():
                            logger.info(
                                "VLM content empty; falling back to thinking field (%d chars)",
                                len(thinking),
                            )
                            return thinking
                    return content
                # Fallback if ollama not installed: raise
                raise RuntimeError("ollama package not installed")
            except Exception as e:
                last_err = e
                if attempt < self.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "VLM call failed (attempt %d): %s; retrying in %ds",
                        attempt + 1,
                        e,
                        wait,
                    )
                    time.sleep(wait)
        raise RuntimeError(f"VLM call failed after {self.max_retries + 1} attempts: {last_err}")
