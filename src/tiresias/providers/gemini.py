from __future__ import annotations

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    """Google Gemini API provider adapter."""

    def __init__(self, api_key: str, api_base: str = "https://generativelanguage.googleapis.com") -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def api_base(self) -> str:
        return self._api_base

    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        model = body.get("model", "gemini-1.5-flash")
        url = f"{self._api_base}/v1beta/models/{model}:generateContent?key={self._api_key}"
        headers: dict = {}

        messages = list(body.get("messages", []))
        # Gemini role mapping: user->user, assistant->model, system->prepend to first user
        system_parts = []
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": content})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        # Prepend system content to the first user message
        if system_parts and contents:
            first = contents[0]
            if first["role"] == "user":
                first["parts"] = system_parts + first["parts"]
        elif system_parts:
            contents.insert(0, {"role": "user", "parts": system_parts})

        provider_body: dict = {"contents": contents}
        if "temperature" in body:
            provider_body["generationConfig"] = {"temperature": body["temperature"]}
        if body.get("max_tokens"):
            gc = provider_body.setdefault("generationConfig", {})
            gc["maxOutputTokens"] = body["max_tokens"]

        return url, headers, provider_body

    def parse_response(self, response_json: dict) -> dict:
        candidates = response_json.get("candidates", [])
        content_text = ""
        finish_reason = "stop"
        if candidates:
            first = candidates[0]
            parts = first.get("content", {}).get("parts", [])
            if parts:
                content_text = parts[0].get("text", "")
            finish_reason = first.get("finishReason", "stop").lower()

        usage_meta = response_json.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)

        return {
            "id": response_json.get("responseId", "gemini-response"),
            "object": "chat.completion",
            "model": response_json.get("modelVersion", ""),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content_text},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

