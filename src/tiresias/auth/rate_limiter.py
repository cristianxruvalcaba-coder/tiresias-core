"""Sliding window rate limiter for the Tiresias LLM Proxy PDP."""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Mapping from rate limit period names to seconds.
_PERIOD_SECONDS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}

_RATE_LIMIT_RE = re.compile(r"^(\d+)/(second|minute|hour|day)$")


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of a rate limit check."""

    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_at: float  # epoch timestamp when the oldest entry in the window expires
    window_seconds: int


def parse_rate_limit(spec: str) -> tuple[int, int] | None:
    """Parse a rate limit string like ``'100/hour'`` into *(limit, window_seconds)*.

    Returns ``None`` if *spec* is not a recognised format.
    """
    match = _RATE_LIMIT_RE.match(spec)
    if match is None:
        return None
    count = int(match.group(1))
    period = match.group(2)
    return count, _PERIOD_SECONDS[period]


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter for the LLM Proxy PDP.

    Tracks request timestamps per *key* (typically ``identity:scope``) inside a
    configurable window.  Thread-safe via :class:`threading.Lock`.
    """

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check whether *key* is within its rate limit **without** recording a new request.

        Returns a :class:`RateLimitResult` with ``allowed=True`` if the current
        count is strictly below *limit*.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return RateLimitResult(
                    allowed=True,
                    current_count=0,
                    limit=limit,
                    remaining=limit,
                    reset_at=now + window_seconds,
                    window_seconds=window_seconds,
                )

            # Evict stale entries from the left of the deque.
            self._evict(window, cutoff)

            count = len(window)
            allowed = count < limit
            remaining = max(limit - count, 0)
            reset_at = window[0] + window_seconds if window else now + window_seconds

        return RateLimitResult(
            allowed=allowed,
            current_count=count,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            window_seconds=window_seconds,
        )

    def record(self, key: str) -> None:
        """Record a request for *key*.  Call **after** a successful dispatch."""
        now = time.monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                window = deque()
                self._windows[key] = window
            window.append(now)

    def get_count(self, key: str, window_seconds: int) -> int:
        """Return the current request count for *key* within *window_seconds*."""
        cutoff = time.monotonic() - window_seconds
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return 0
            self._evict(window, cutoff)
            return len(window)

    def cleanup(self, max_window_seconds: int = 86400) -> int:
        """Remove entries older than *max_window_seconds* across all keys.

        Returns the number of keys that were fully purged (empty after eviction).
        Call periodically from a background timer.
        """
        cutoff = time.monotonic() - max_window_seconds
        purged = 0
        with self._lock:
            empty_keys: list[str] = []
            for key, window in self._windows.items():
                self._evict(window, cutoff)
                if not window:
                    empty_keys.append(key)
            for key in empty_keys:
                del self._windows[key]
                purged += 1
        if purged:
            logger.debug("rate_limiter_cleanup", purged_keys=purged)
        return purged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _evict(window: deque[float], cutoff: float) -> None:
        """Remove timestamps from the left that are older than *cutoff*."""
        while window and window[0] <= cutoff:
            window.popleft()
