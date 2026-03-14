"""Tests for OpenAI provider adapter."""
import pytest
from tiresias.providers.openai import OpenAIProvider


def _make_body():
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
        "temperature": 0.7,
    }


def test_openai_name():
    p = OpenAIProvider(api_key="test-key")
    assert p.name == "openai"


def test_openai_api_base_default():
    p = OpenAIProvider(api_key="test-key")
    assert p.api_base == "https://api.openai.com"


def test_openai_api_base_override():
    p = OpenAIProvider(api_key="test-key", api_base="http://mock-openai")
    assert p.api_base == "http://mock-openai"


def test_openai_format_request_url():
    p = OpenAIProvider(api_key="sk-abc", api_base="https://api.openai.com")
    url, headers, body = p.format_request(_make_body())
    assert url == "https://api.openai.com/v1/chat/completions"


def test_openai_format_request_auth_header():
    p = OpenAIProvider(api_key="sk-abc")
    url, headers, body = p.format_request(_make_body())
    assert headers["Authorization"] == "Bearer sk-abc"


def test_openai_format_request_body_passthrough():
    p = OpenAIProvider(api_key="sk-abc")
    original = _make_body()
    url, headers, body = p.format_request(original)
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"] == original["messages"]


def test_openai_format_request_does_not_mutate_original():
    p = OpenAIProvider(api_key="sk-abc")
    original = _make_body()
    url, headers, body = p.format_request(original)
    body["injected"] = True
    assert "injected" not in original


def test_openai_parse_response_passthrough():
    p = OpenAIProvider(api_key="sk-abc")
    resp = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop", "index": 0}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    result = p.parse_response(resp)
    assert result is resp  # or equal -- passthrough
    assert result["choices"][0]["message"]["content"] == "Hi"
