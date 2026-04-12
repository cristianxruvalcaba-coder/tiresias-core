from __future__ import annotations

from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    """Anthropic API provider adapter (converts OpenAI format <-> Anthropic Messages API)."""

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: str, api_base: str = "https://api.anthropic.com") -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def api_base(self) -> str:
        return self._api_base

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        url = f"{self._api_base}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        messages = list(body.get("messages", []))
        # Extract system message (Anthropic uses top-level "system" field)
        system_text = None
        non_system = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                non_system.append({"role": msg["role"], "content": msg.get("content", "")})

        # Strip provider prefix (e.g. "anthropic/claude-sonnet-4-6" -> "claude-sonnet-4-6")
        model = body.get("model", "claude-3-5-sonnet-20241022")
        if model.startswith("anthropic/"):
            model = model[len("anthropic/"):]

        provider_body: dict = {
            "model": model,
            "messages": non_system,
            "max_tokens": body.get("max_tokens", 1024),
        }
        if system_text:
            provider_body["system"] = system_text
        if "temperature" in body:
            provider_body["temperature"] = body["temperature"]
        if "stream" in body:
            provider_body["stream"] = body["stream"]
        return url, headers, provider_body

    def parse_response(self, response_json: dict) -> dict:
        # Normalize Anthropic Messages response -> OpenAI chat completion format
        content_list = response_json.get("content", [])
        content_text = ""
        if content_list:
            first = content_list[0]
            content_text = first.get("text", "")

        usage = response_json.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)

        return {
            "id": response_json.get("id", ""),
            "object": "chat.completion",
            "model": response_json.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content_text},
                    "finish_reason": response_json.get("stop_reason", "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

