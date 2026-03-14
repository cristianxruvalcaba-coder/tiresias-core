import pytest
from tiresias.tracking.tokens import (
    count_tokens_from_messages,
    count_tokens_from_string,
    extract_usage_from_response,
)


def test_count_tokens_from_string_basic():
    count = count_tokens_from_string("Hello world")
    assert count > 0
    assert isinstance(count, int)


def test_count_tokens_from_string_gpt4o():
    count = count_tokens_from_string("Hello world", model="gpt-4o")
    assert count > 0


def test_count_tokens_from_messages_single():
    messages = [{"role": "user", "content": "Hello, how are you?"}]
    count = count_tokens_from_messages(messages)
    assert count > 5


def test_count_tokens_from_messages_multi():
    single = count_tokens_from_messages([{"role": "user", "content": "Hello"}])
    multi = count_tokens_from_messages([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ])
    assert multi > single


def test_extract_usage_happy_path():
    response = {
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }
    }
    usage = extract_usage_from_response(response)
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 30


def test_extract_usage_missing_usage():
    usage = extract_usage_from_response({})
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0


def test_extract_usage_null_usage():
    usage = extract_usage_from_response({"usage": None})
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0


def test_unknown_model_falls_back():
    # Should not raise, should fall back to cl100k_base
    count = count_tokens_from_string("test text", model="unknown-model-xyz")
    assert count > 0


def test_extract_usage_partial():
    # Only prompt_tokens provided; total derived
    response = {"usage": {"prompt_tokens": 5, "completion_tokens": 15}}
    usage = extract_usage_from_response(response)
    assert usage["prompt_tokens"] == 5
    assert usage["completion_tokens"] == 15
    assert usage["total_tokens"] == 20
