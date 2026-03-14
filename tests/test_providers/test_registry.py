import pytest
from tiresias.providers import build_provider, PROVIDER_MAP


def test_build_provider_openai():
    env = {"OPENAI_API_KEY": "sk-test"}
    prov = build_provider("openai", env)
    assert prov.name == "openai"


def test_build_provider_anthropic():
    env = {"ANTHROPIC_API_KEY": "ant-key"}
    prov = build_provider("anthropic", env)
    assert prov.name == "anthropic"


def test_build_provider_gemini():
    env = {"GOOGLE_API_KEY": "goog-key"}
    prov = build_provider("gemini", env)
    assert prov.name == "gemini"


def test_build_provider_groq():
    env = {"GROQ_API_KEY": "gsk-key"}
    prov = build_provider("groq", env)
    assert prov.name == "groq"


def test_build_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider("fakeprovider", {})


def test_build_provider_case_insensitive():
    env = {"OPENAI_API_KEY": "sk-test"}
    prov = build_provider("OpenAI", env)
    assert prov.name == "openai"


def test_provider_map_contains_all_four():
    assert "openai" in PROVIDER_MAP
    assert "anthropic" in PROVIDER_MAP
    assert "gemini" in PROVIDER_MAP
    assert "groq" in PROVIDER_MAP
