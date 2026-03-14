from __future__ import annotations

from .base import BaseProvider


class GroqProvider(BaseProvider):
    """Groq LPU provider adapter (OpenAI-compatible wire format)."""

    def __init__(self, api_key: str, api_base: str = "https://api.groq.com") -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def name(self) -> str:
        return "groq"

    @property
    def api_base(self) -> str:
        return self._api_base

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        # Groq uses OpenAI-compatible API at /openai/v1/chat/completions
        url = f"{self._api_base}/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        return url, headers, dict(body)

    def parse_response(self, response_json: dict) -> dict:
        # Groq returns OpenAI-format responses.
        return response_json
