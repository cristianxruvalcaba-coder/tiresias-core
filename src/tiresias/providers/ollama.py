from __future__ import annotations

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    """Ollama provider adapter (OpenAI-compatible wire format, no auth required)."""

    def __init__(self, api_key: str, api_base: str = "http://localhost:11434") -> None:
        # api_key is accepted for interface compatibility but Ollama does not need auth.
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def api_base(self) -> str:
        return self._api_base

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        url = f"{self._api_base}/v1/chat/completions"
        # Ollama does not require auth; skip Authorization header entirely.
        headers: dict[str, str] = {}
        if self._api_key and self._api_key.lower() != "ollama":
            headers["Authorization"] = f"Bearer {self._api_key}"
        return url, headers, dict(body)

    def parse_response(self, response_json: dict) -> dict:
        # Ollama uses OpenAI-compatible response format.
        return response_json
