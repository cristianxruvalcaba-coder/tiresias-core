"""Tests for the ProviderHealth tracker."""
import time
import pytest
from unittest.mock import patch
from tiresias.providers.health import HealthTracker, _ERROR_THRESHOLD, _RECOVERY_SECONDS


def test_health_tracker_initial_all_healthy():
    ht = HealthTracker(["openai", "anthropic", "gemini"])
    assert ht.is_healthy("openai") is True
    assert ht.is_healthy("anthropic") is True
    assert ht.is_healthy("gemini") is True


def test_health_tracker_single_error_does_not_mark_unhealthy():
    ht = HealthTracker(["openai"])
    ht.record_error("openai")
    assert ht.is_healthy("openai") is True


def test_health_tracker_record_error_marks_unhealthy_after_threshold():
    ht = HealthTracker(["openai"])
    for _ in range(_ERROR_THRESHOLD):
        ht.record_error("openai")
    assert ht.is_healthy("openai") is False


def test_health_tracker_record_success_resets_errors():
    ht = HealthTracker(["openai"])
    for _ in range(_ERROR_THRESHOLD):
        ht.record_error("openai")
    assert ht.is_healthy("openai") is False
    ht.record_success("openai")
    assert ht.is_healthy("openai") is True


def test_health_tracker_auto_recover_after_timeout():
    ht = HealthTracker(["openai"])
    for _ in range(_ERROR_THRESHOLD):
        ht.record_error("openai")
    assert ht.is_healthy("openai") is False

    # Simulate time passing beyond recovery window
    past_time = time.monotonic() - (_RECOVERY_SECONDS + 1)
    ht._state["openai"].last_error_at = past_time
    assert ht.is_healthy("openai") is True


def test_get_ordered_providers_healthy_first():
    ht = HealthTracker(["openai", "anthropic", "gemini"])
    # Mark openai unhealthy
    for _ in range(_ERROR_THRESHOLD):
        ht.record_error("openai")
    ordered = ht.get_ordered_providers()
    # Unhealthy openai should be at the end
    assert ordered.index("openai") > ordered.index("anthropic")
    assert ordered.index("openai") > ordered.index("gemini")


def test_get_ordered_providers_all_healthy_preserves_order():
    ht = HealthTracker(["openai", "anthropic", "gemini"])
    ordered = ht.get_ordered_providers()
    assert ordered == ["openai", "anthropic", "gemini"]


def test_reset_clears_all_state():
    ht = HealthTracker(["openai", "anthropic"])
    for _ in range(_ERROR_THRESHOLD):
        ht.record_error("openai")
    assert ht.is_healthy("openai") is False
    ht.reset()
    assert ht.is_healthy("openai") is True


def test_status_returns_list():
    ht = HealthTracker(["openai", "anthropic"])
    status = ht.status()
    assert len(status) == 2
    names = [s["name"] for s in status]
    assert "openai" in names
    assert "anthropic" in names
    for s in status:
        assert "is_healthy" in s
        assert "consecutive_errors" in s


def test_unknown_provider_auto_created():
    ht = HealthTracker(["openai"])
    # Accessing a provider not in the initial list should work gracefully
    assert ht.is_healthy("groq") is True
    ht.record_error("groq")
    assert ht.is_healthy("groq") is True  # one error, not yet threshold
