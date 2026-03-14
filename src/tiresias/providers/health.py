from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


_ERROR_THRESHOLD = 3          # consecutive errors before marking unhealthy
_RECOVERY_SECONDS = 60        # seconds after last error before auto-recovery


@dataclass
class ProviderHealth:
    name: str
    is_healthy: bool = True
    consecutive_errors: int = 0
    last_error_at: Optional[float] = None   # time.monotonic() timestamp


class HealthTracker:
    """In-memory, per-container provider health state."""

    def __init__(self, providers: list[str]) -> None:
        self._cascade = list(providers)
        self._state: dict[str, ProviderHealth] = {
            name: ProviderHealth(name=name) for name in providers
        }

    def record_success(self, name: str) -> None:
        state = self._get_or_create(name)
        state.consecutive_errors = 0
        state.is_healthy = True
        state.last_error_at = None

    def record_error(self, name: str) -> None:
        state = self._get_or_create(name)
        state.consecutive_errors += 1
        state.last_error_at = time.monotonic()
        if state.consecutive_errors >= _ERROR_THRESHOLD:
            state.is_healthy = False

    def is_healthy(self, name: str) -> bool:
        state = self._get_or_create(name)
        # Auto-recover if enough time has passed since the last error
        if not state.is_healthy and state.last_error_at is not None:
            elapsed = time.monotonic() - state.last_error_at
            if elapsed >= _RECOVERY_SECONDS:
                state.is_healthy = True
                state.consecutive_errors = 0
        return state.is_healthy

    def get_ordered_providers(self) -> list[str]:
        """Return cascade in config order, with healthy providers first."""
        healthy = [n for n in self._cascade if self.is_healthy(n)]
        unhealthy = [n for n in self._cascade if not self.is_healthy(n)]
        return healthy + unhealthy

    def reset(self) -> None:
        """Reset all health state (test helper)."""
        for name in self._state:
            self._state[name] = ProviderHealth(name=name)

    def status(self) -> list[dict]:
        """Return a serializable snapshot of all provider health states."""
        return [
            {
                "name": name,
                "is_healthy": self.is_healthy(name),
                "consecutive_errors": self._state[name].consecutive_errors,
            }
            for name in self._cascade
        ]

    def _get_or_create(self, name: str) -> ProviderHealth:
        if name not in self._state:
            self._state[name] = ProviderHealth(name=name)
        return self._state[name]
