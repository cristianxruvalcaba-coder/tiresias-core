from __future__ import annotations

from .openai import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    """Ollama provider -- speaks OpenAI-compatible API with model-name normalization.

    Strips the ``ollama/`` prefix that litellm-style clients prepend, since
    Ollama's own ``/v1/chat/completions`` endpoint expects bare model names
    (e.g. ``llama3.1:8b`` not ``ollama/llama3.1:8b``).
    """

    def __init__(
        self, api_key: str = "", api_base: str = "http://localhost:11434"
    ) -> None:
        super().__init__(api_key=api_key or "ollama", api_base=api_base)

    @property
    def name(self) -> str:
        return "ollama"

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        url, headers, payload = super().format_request(body)
        # Strip ollama/ prefix so Ollama sees the bare model name
        model = payload.get("model", "")
        if model.startswith("ollama/"):
            payload["model"] = model[len("ollama/"):]
        return url, headers, payload

    def is_error(self, status_code: int) -> bool:
        """Ollama returns 4xx for unknown models -- treat as failover-worthy."""
        return status_code >= 400

