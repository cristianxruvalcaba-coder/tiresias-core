"""Tests for ProviderRouter: cascade, failover, health tracking."""
import pytest
import httpx
import respx
from httpx import Response as HttpxResponse

from tiresias.providers.health import HealthTracker
from tiresias.providers.router import ProviderRouter, ProviderCascadeExhausted
from tiresias.providers.openai import OpenAIProvider
from tiresias.providers.anthropic import AnthropicProvider


def _openai_response(content: str = "Hello!") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop", "index": 0}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _anthropic_response(content: str = "Hi from Anthropic!") -> dict:
    return {
        "id": "msg_abc",
        "model": "claude-3-haiku-20240307",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _make_router(cascade, http_client, env=None):
    env = env or {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "ant-test"}
    health = HealthTracker(cascade)
    from tiresias.providers import build_provider

    def builder(name: str):
        return build_provider(name, env)

    return ProviderRouter(cascade=cascade, health=health, builder=builder, http_client=http_client), health


@pytest.mark.anyio
async def test_router_routes_to_first_healthy_provider():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai", "anthropic"], client)
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=HttpxResponse(200, json=_openai_response("Hi from OpenAI"))
            )
            resp, provider_name = await router.execute(
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                {},
            )
        assert provider_name == "openai"
        assert resp["choices"][0]["message"]["content"] == "Hi from OpenAI"


@pytest.mark.anyio
async def test_router_failover_on_500():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai", "anthropic"], client)
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=HttpxResponse(500, json={"error": "Internal server error"})
            )
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=HttpxResponse(200, json=_anthropic_response("Fallback response"))
            )
            resp, provider_name = await router.execute(
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                {},
            )
        assert provider_name == "anthropic"
        assert resp["choices"][0]["message"]["content"] == "Fallback response"


@pytest.mark.anyio
async def test_router_failover_on_timeout():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai", "anthropic"], client)
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                side_effect=httpx.TimeoutException("timeout")
            )
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=HttpxResponse(200, json=_anthropic_response("After timeout failover"))
            )
            resp, provider_name = await router.execute(
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                {},
            )
        assert provider_name == "anthropic"


@pytest.mark.anyio
async def test_router_raises_cascade_exhausted_when_all_fail():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai", "anthropic"], client)
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=HttpxResponse(500)
            )
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=HttpxResponse(503)
            )
            with pytest.raises(ProviderCascadeExhausted):
                await router.execute(
                    {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                    {},
                )


@pytest.mark.anyio
async def test_router_records_success_on_2xx():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai"], client)
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=HttpxResponse(200, json=_openai_response())
            )
            await router.execute(
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                {},
            )
        # After success, openai should still be healthy and consecutive_errors should be 0
        assert health.is_healthy("openai") is True
        assert health._state["openai"].consecutive_errors == 0


@pytest.mark.anyio
async def test_router_skips_unhealthy_but_tries_as_last_resort():
    async with httpx.AsyncClient() as client:
        router, health = _make_router(["openai", "anthropic"], client)
        # Mark openai as unhealthy
        from tiresias.providers.health import _ERROR_THRESHOLD
        for _ in range(_ERROR_THRESHOLD):
            health.record_error("openai")
        assert health.is_healthy("openai") is False

        with respx.mock:
            # Anthropic should be tried first (it's healthy)
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=HttpxResponse(200, json=_anthropic_response("From healthy provider"))
            )
            resp, provider_name = await router.execute(
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                {},
            )
        assert provider_name == "anthropic"
