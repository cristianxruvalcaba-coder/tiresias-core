from __future__ import annotations

from .base import BaseProvider
from .openai import OpenAIProvider
from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .groq import GroqProvider

PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
}

_ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
}

_DEFAULT_BASE_MAP = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com",
}


def build_provider(name: str, env: dict, api_base: str | None = None) -> BaseProvider:
    """Instantiate a provider by name, reading API key from env dict.

    Args:
        name:     Provider name (openai, anthropic, gemini, groq)
        env:      Environment variables dict (typically os.environ or a test dict)
        api_base: Optional base URL override. If None, uses the provider default.

    Raises:
        ValueError: If name is not a known provider.
    """
    name = name.lower().strip()
    if name not in PROVIDER_MAP:
        known = list(PROVIDER_MAP)
        raise ValueError(f"Unknown provider: {name!r}. Known providers: {known}")
    cls = PROVIDER_MAP[name]
    key_var = _ENV_KEY_MAP[name]
    api_key = env.get(key_var, "")
    base = api_base or _DEFAULT_BASE_MAP[name]
    return cls(api_key=api_key, api_base=base)


__all__ = [
    "BaseProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "GroqProvider",
    "PROVIDER_MAP",
    "build_provider",
]
