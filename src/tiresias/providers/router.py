from __future__ import annotations

import logging
from typing import Callable

import httpx

from .base import BaseProvider
from .health import HealthTracker

logger = logging.getLogger(__name__)

_PROVIDER_TIMEOUT = 2.0   # seconds per provider attempt


class ProviderCascadeExhausted(Exception):
    """Raised when all providers in the cascade have failed."""


class ProviderRouter:
    """Routes requests through a cascade of providers with automatic failover."""

    def __init__(
        self,
        cascade: list[str],
        health: HealthTracker,
        builder: Callable[[str], BaseProvider],
        http_client: httpx.AsyncClient,
    ) -> None:
        self._cascade = cascade
        self._health = health
        self._builder = builder
        self._http_client = http_client

    async def execute(
        self,
        request_body: dict,
        extra_headers: dict,
    ) -> tuple[dict, str]:
        """Try providers in cascade order. Returns (normalized_response, provider_name).

        Raises:
            ProviderCascadeExhausted: if every provider in the cascade returns 5xx / times out.
        """
        ordered = self._health.get_ordered_providers()
        last_exc: Exception | None = None

        for provider_name in ordered:
            provider = self._builder(provider_name)
            try:
                url, provider_headers, provider_body = provider.format_request(request_body)
                merged_headers = {**extra_headers, **provider_headers}
                # Remove host header -- it will be wrong for the new upstream
                merged_headers.pop("host", None)
                merged_headers.pop("Host", None)

                resp = await self._http_client.post(
                    url,
                    headers=merged_headers,
                    json=provider_body,
                    timeout=_PROVIDER_TIMEOUT,
                )
            except httpx.TimeoutException as exc:
                logger.warning("Provider %s timed out: %s", provider_name, exc)
                self._health.record_error(provider_name)
                last_exc = exc
                continue
            except httpx.RequestError as exc:
                logger.warning("Provider %s request error: %s", provider_name, exc)
                self._health.record_error(provider_name)
                last_exc = exc
                continue

            if provider.is_error(resp.status_code):
                logger.warning(
                    "Provider %s returned %s, trying next", provider_name, resp.status_code
                )
                self._health.record_error(provider_name)
                last_exc = RuntimeError(
                    f"Provider {provider_name} returned HTTP {resp.status_code}"
                )
                continue

            # Success
            self._health.record_success(provider_name)
            try:
                response_json = resp.json()
            except Exception:
                response_json = {}
            normalized = provider.parse_response(response_json)
            return normalized, provider_name

        raise ProviderCascadeExhausted(
            f"All providers exhausted. Last error: {last_exc}"
        )
