import pytest
from tiresias.providers.gemini import GeminiProvider


def test_gemini_name():
    prov = GeminiProvider(api_key="test-key")
    assert prov.name == "gemini"


def test_gemini_api_base_default():
    prov = GeminiProvider(api_key="test-key")
    assert prov.api_base == "https://generativelanguage.googleapis.com"


def test_gemini_format_request_url():
    prov = GeminiProvider(api_key="my-key", api_base="https://generativelanguage.googleapis.com")
    url, headers, body = prov.format_request({
        "model": "gemini-1.5-flash",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert "gemini-1.5-flash:generateContent" in url
    assert "key=my-key" in url


def test_gemini_format_request_no_auth_header():
    prov = GeminiProvider(api_key="my-key")
    url, headers, body = prov.format_request({
        "model": "gemini-1.5-flash",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert "Authorization" not in headers


def test_gemini_format_request_converts_messages():
    prov = GeminiProvider(api_key="key")
    url, headers, body = prov.format_request({
        "model": "gemini-1.5-flash",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "Tell me more"},
        ],
    })
    contents = body["contents"]
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[2]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "Hello"
    assert contents[1]["parts"][0]["text"] == "Hi there"


def test_gemini_format_request_system_prepended_to_first_user():
    prov = GeminiProvider(api_key="key")
    url, headers, body = prov.format_request({
        "model": "gemini-1.5-flash",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    })
    contents = body["contents"]
    first_parts = contents[0]["parts"]
    texts = [item["text"] for item in first_parts]
    assert "You are helpful." in texts
    assert "Hello" in texts


def test_gemini_parse_response_normalizes():
    prov = GeminiProvider(api_key="key")
    gemini_resp = {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": "Hello from Gemini!"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 6,
        },
    }
    normalized = prov.parse_response(gemini_resp)
    assert normalized["object"] == "chat.completion"
    assert normalized["choices"][0]["message"]["content"] == "Hello from Gemini!"
    assert normalized["usage"]["prompt_tokens"] == 10
    assert normalized["usage"]["completion_tokens"] == 6
    assert normalized["usage"]["total_tokens"] == 16


def test_gemini_parse_response_empty_candidates():
    prov = GeminiProvider(api_key="key")
    normalized = prov.parse_response({"candidates": [], "usageMetadata": {}})
    assert normalized["choices"][0]["message"]["content"] == ""
