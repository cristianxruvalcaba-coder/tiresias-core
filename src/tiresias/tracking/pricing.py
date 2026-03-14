from __future__ import annotations

# Pricing in USD per 1M tokens (input/output separate)
# Updated: 2026-03-13
PRICING_TABLE: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4-turbo-preview": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-3.5-turbo-0125": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    # Gemini
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-1.0-pro": {"input": 0.50, "output": 1.50},
    # Groq (LPU inference)
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
    "gemma2-9b-it": {"input": 0.20, "output": 0.20},
}

MODEL_PREFIX_FALLBACK: list[tuple[str, str]] = [
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("gpt-4o", "gpt-4o"),
    ("gpt-4-turbo", "gpt-4-turbo"),
    ("gpt-4", "gpt-4"),
    ("gpt-3.5-turbo", "gpt-3.5-turbo"),
    ("o3-mini", "o3-mini"),
    ("o1-mini", "o1-mini"),
    ("o1", "o1"),
    ("claude-3-5-sonnet", "claude-3-5-sonnet-20241022"),
    ("claude-3-5-haiku", "claude-3-5-haiku-20241022"),
    ("claude-3-opus", "claude-3-opus-20240229"),
    ("claude-3-sonnet", "claude-3-sonnet-20240229"),
    ("claude-3-haiku", "claude-3-haiku-20240307"),
    ("claude-sonnet-4", "claude-sonnet-4-5"),
    ("claude-opus-4", "claude-opus-4-5"),
    ("gemini-2.0-flash-lite", "gemini-2.0-flash-lite"),
    ("gemini-2.0-flash", "gemini-2.0-flash"),
    ("gemini-1.5-pro", "gemini-1.5-pro"),
    ("gemini-1.5-flash", "gemini-1.5-flash"),
    ("gemini-1.0-pro", "gemini-1.0-pro"),
    ("llama-3.3-70b", "llama-3.3-70b-versatile"),
    ("llama-3.1-70b", "llama-3.1-70b-versatile"),
    ("llama-3.1-8b", "llama-3.1-8b-instant"),
    ("mixtral-8x7b", "mixtral-8x7b-32768"),
]


def _resolve_model(model: str):
    if model in PRICING_TABLE:
        return model
    for prefix, resolved in MODEL_PREFIX_FALLBACK:
        if model.startswith(prefix):
            return resolved
    return None


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    resolved = _resolve_model(model)
    if resolved is None:
        return 0.0
    pricing = PRICING_TABLE[resolved]
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 8)


def get_pricing(model: str):
    resolved = _resolve_model(model)
    if resolved is None:
        return None
    return PRICING_TABLE[resolved]
