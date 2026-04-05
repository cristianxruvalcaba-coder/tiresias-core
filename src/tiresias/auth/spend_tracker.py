"""Spend tracking for the Tiresias LLM Proxy PDP."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Outcome of a budget check."""

    allowed: bool
    current_spend_usd: float
    max_spend_usd: float
    remaining_usd: float


class SpendTracker:
    """Tracks cumulative spend per *(identity, scope)* key for ``max_spend_usd`` enforcement.

    All amounts are in USD.  Thread-safe via :class:`threading.Lock`.
    """

    def __init__(self) -> None:
        self._spend: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_budget(self, key: str, max_spend_usd: float) -> BudgetResult:
        """Check whether *key* is within its budget.

        Returns a :class:`BudgetResult` with ``allowed=True`` when the cumulative
        spend is strictly below *max_spend_usd*.
        """
        with self._lock:
            current = self._spend.get(key, 0.0)

        remaining = max(max_spend_usd - current, 0.0)
        allowed = current < max_spend_usd

        return BudgetResult(
            allowed=allowed,
            current_spend_usd=current,
            max_spend_usd=max_spend_usd,
            remaining_usd=remaining,
        )

    def record_spend(self, key: str, amount_usd: float) -> None:
        """Record *amount_usd* of spend for *key*.  Call after a completed request."""
        if amount_usd <= 0:
            return
        with self._lock:
            self._spend[key] = self._spend.get(key, 0.0) + amount_usd
        logger.debug("spend_recorded", key=key, amount_usd=amount_usd, total_usd=self._spend[key])

    def get_spend(self, key: str) -> float:
        """Return cumulative spend for *key*."""
        with self._lock:
            return self._spend.get(key, 0.0)

    def reset(self, key: str) -> None:
        """Reset spend counter for *key* (e.g. on monthly rollover)."""
        with self._lock:
            self._spend.pop(key, None)
        logger.info("spend_reset", key=key)
