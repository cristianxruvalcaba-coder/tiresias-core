import pytest
from tiresias.tracking.pricing import calculate_cost, get_pricing, PRICING_TABLE


def test_calculate_cost_gpt4o():
    cost = calculate_cost("gpt-4o", 1000, 500)
    assert cost > 0
    assert isinstance(cost, float)


def test_calculate_cost_unknown_model():
    cost = calculate_cost("unknown-model-xyz", 1000, 500)
    assert cost == 0.0


def test_calculate_cost_zero_tokens():
    cost = calculate_cost("gpt-4o", 0, 0)
    assert cost == 0.0


def test_calculate_cost_anthropic():
    cost = calculate_cost("claude-3-5-sonnet-20241022", 1000, 500)
    assert cost > 0


def test_calculate_cost_groq():
    cost = calculate_cost("llama-3.3-70b-versatile", 1000, 500)
    assert cost > 0


def test_calculate_cost_gemini():
    cost = calculate_cost("gemini-1.5-pro", 1000, 500)
    assert cost > 0


def test_prefix_fallback():
    # gpt-4o-mini-2024-07-18 should resolve via prefix to gpt-4o-mini
    cost = calculate_cost("gpt-4o-mini-2024-07-18", 1000, 500)
    assert cost > 0


def test_get_pricing_known():
    pricing = get_pricing("gpt-4o")
    assert pricing is not None
    assert "input" in pricing
    assert "output" in pricing


def test_get_pricing_unknown():
    pricing = get_pricing("unknown-xyz")
    assert pricing is None


def test_cost_math_correctness():
    # 1M prompt tokens for gpt-4o-mini = /usr/bin/bash.15 input (no completion)
    cost = calculate_cost("gpt-4o-mini", 1_000_000, 0)
    assert abs(cost - 0.15) < 0.000001


def test_cost_math_output_only():
    # 1M completion tokens for gpt-4o-mini = /usr/bin/bash.60 output
    cost = calculate_cost("gpt-4o-mini", 0, 1_000_000)
    assert abs(cost - 0.60) < 0.000001


def test_all_table_entries_have_input_output():
    for model, pricing in PRICING_TABLE.items():
        assert "input" in pricing, f"{model} missing input"
        assert "output" in pricing, f"{model} missing output"
        assert pricing["input"] >= 0
        assert pricing["output"] >= 0
