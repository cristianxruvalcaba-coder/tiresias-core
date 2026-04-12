from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Abstract base class for all LLM provider adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. openai, anthropic, gemini, groq)."""

    @property
    @abstractmethod
    def api_base(self) -> str:
        """Base URL for the provider API."""

    @abstractmethod
    def format_request(self, body: dict) -> tuple[str, dict, dict]:
        """Convert an OpenAI-format request body to the provider wire format.

        Returns:
            (url, headers, provider_body)
            url     -- full URL to POST to
            headers -- HTTP headers dict (Authorization, api-key, etc.)
            body    -- request body dict in provider-native format
        """

    @abstractmethod
    def parse_response(self, response_json: dict) -> dict:
        """Normalize a provider response to OpenAI chat completion format."""

    def is_error(self, status_code: int) -> bool:
        """Return True if the status code should trigger failover to next provider."""
        return status_code >= 500 or status_code == 429

    def is_client_error(self, status_code: int) -> bool:
        """Return True if this is a client error that should be returned to the caller
        rather than silently parsed as a successful response."""
        return 400 <= status_code < 500 and status_code != 429

