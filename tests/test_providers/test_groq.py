import pytest
from tiresias.providers.groq import GroqProvider


def test_groq_name():
    prov = GroqProvider(api_key="test-key")
    assert prov.name == "groq"


def test_groq_api_base_default():
    prov = GroqProvider(api_key="test-key")
    assert prov.api_base == "https://api.groq.com"


def test_groq_format_request_url():
    prov = GroqProvider(api_key="gsk-key", api_base="https://api.groq.com")
    url, headers, body = prov.format_request({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert url == "https://api.groq.com/openai/v1/chat/completions"


def test_groq_format_request_uses_openai_path():
    prov = GroqProvider(api_key="gsk-key")
    url, headers, body = prov.format_request({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert "/openai/v1/" in url


def test_groq_format_request_auth_header():
    prov = GroqProvider(api_key="gsk-secret")
    url, headers, body = prov.format_request({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Hi"}],
    })
    assert headers["Authorization"] == "Bearer gsk-secret"


def test_groq_parse_response_passthrough():
    prov = GroqProvider(api_key="key")
    resp = {
        "id": "chatcmpl-groq-123",
        "object": "chat.completion",
        "choices": [{"message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop", "index": 0}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    result = prov.parse_response(resp)
    assert result["choices"][0]["message"]["content"] == "Hi!"
