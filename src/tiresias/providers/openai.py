from __future__ import annotations

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    """OpenAI API provider adapter."""

    def __init__(self, api_key: str, api_base: str = "https://api.openai.com") -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def name(self) -> str:
        return "openai"

    @property
    def api_base(self) -> str:
        return self._api_base

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        url = f"{self._api_base}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        return url, headers, dict(body)

    def parse_response(self, response_json: dict) -> dict:
        # OpenAI format is already the canonical format.
        return response_json
