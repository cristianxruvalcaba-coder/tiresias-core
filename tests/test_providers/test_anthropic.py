"""Tests for Anthropic provider adapter."""
import pytest
from tiresias.providers.anthropic import AnthropicProvider


def test_anthropic_name():
    p = AnthropicProvider(api_key="test-key")
    assert p.name == "anthropic"


def test_anthropic_api_base_default():
    p = AnthropicProvider(api_key="test-key")
    assert p.api_base == "https://api.anthropic.com"


def test_anthropic_format_request_url():
    p = AnthropicProvider(api_key="key", api_base="https://api.anthropic.com")
    url, headers, body = p.format_request({
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert url == "https://api.anthropic.com/v1/messages"


def test_anthropic_format_request_headers():
    p = AnthropicProvider(api_key="my-anthropic-key")
    url, headers, body = p.format_request({
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert headers["x-api-key"] == "my-anthropic-key"
    assert headers["anthropic-version"] == "2023-06-01"


def test_anthropic_format_request_extracts_system():
    p = AnthropicProvider(api_key="key")
    url, headers, body = p.format_request({
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    })
    assert body["system"] == "You are helpful."
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_anthropic_format_request_no_system():
    p = AnthropicProvider(api_key="key")
    url, headers, body = p.format_request({
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
    })
    assert "system" not in body


def test_anthropic_format_request_max_tokens_default():
    p = AnthropicProvider(api_key="key")
    url, headers, body = p.format_request({
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
    })
    assert body["max_tokens"] == 1024


def test_anthropic_format_request_max_tokens_passthrough():
    p = AnthropicProvider(api_key="key")
    url, headers, body = p.format_request({
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 512,
    })
    assert body["max_tokens"] == 512


def test_anthropic_parse_response_normalizes():
    p = AnthropicProvider(api_key="key")
    anthropic_resp = {
        "id": "msg_abc",
        "model": "claude-3-5-sonnet-20241022",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello there!"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }
    normalized = p.parse_response(anthropic_resp)
    assert normalized["object"] == "chat.completion"
    assert normalized["choices"][0]["message"]["content"] == "Hello there!"
    assert normalized["choices"][0]["message"]["role"] == "assistant"
    assert normalized["usage"]["prompt_tokens"] == 12
    assert normalized["usage"]["completion_tokens"] == 7
    assert normalized["usage"]["total_tokens"] == 19


def test_anthropic_parse_response_empty_content():
    p = AnthropicProvider(api_key="key")
    normalized = p.parse_response({"content": [], "usage": {}, "stop_reason": "stop"})
    assert normalized["choices"][0]["message"]["content"] == ""
