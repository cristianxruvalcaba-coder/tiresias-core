from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from tiresias.config import TiresiasSettings

logger = logging.getLogger(__name__)

_HARD_DELETE_GRACE_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_retention_purge(
    engine: AsyncEngine,
    retention_days: int,
    usage_retention_days: int,
) -> dict[str, int]:
    """Run two-phase retention purge for a single tenant engine.

    Phase 1: Soft-delete audit_log rows older than retention_days (null encrypted columns).
    Phase 2: Hard-delete rows that were soft-deleted more than 7 days ago.
    Phase 3: Hard-delete usage_buckets older than usage_retention_days.

    Returns counts of affected rows in each phase.
    """
    now = _utcnow()
    soft_cutoff = now - timedelta(days=retention_days)
    hard_cutoff = now - timedelta(days=_HARD_DELETE_GRACE_DAYS)
    usage_cutoff = now - timedelta(days=usage_retention_days)

    soft_deleted = 0
    hard_deleted = 0
    usage_purged = 0

    async with engine.begin() as conn:
        # Phase 1: Soft delete — null encrypted columns, set deleted_at
        soft_result = await conn.execute(
            text(
                """
                UPDATE tiresias_audit_log
                SET encrypted_prompt = NULL,
                    encrypted_completion = NULL,
                    deleted_at = :now
                WHERE created_at < :soft_cutoff
                  AND deleted_at IS NULL
                """
            ),
            {"now": now, "soft_cutoff": soft_cutoff},
        )
        soft_deleted = soft_result.rowcount

        # Phase 2: Hard delete — remove rows soft-deleted more than 7 days ago
        hard_result = await conn.execute(
            text(
                """
                DELETE FROM tiresias_audit_log
                WHERE deleted_at IS NOT NULL
                  AND deleted_at < :hard_cutoff
                """
            ),
            {"hard_cutoff": hard_cutoff},
        )
        hard_deleted = hard_result.rowcount

        # Phase 3: Usage bucket purge — aggregate rows don't need soft delete
        usage_result = await conn.execute(
            text(
                """
                DELETE FROM tiresias_usage_buckets
                WHERE bucket_hour < :usage_cutoff
                """
            ),
            {"usage_cutoff": usage_cutoff},
        )
        usage_purged = usage_result.rowcount

    counts = {
        "soft_deleted": soft_deleted,
        "hard_deleted": hard_deleted,
        "usage_purged": usage_purged,
    }
    logger.info(
        "Retention purge complete: %s",
        counts,
    )
    return counts


def schedule_retention_purge(
    engine: AsyncEngine,
    settings: "TiresiasSettings",
):
    """Set up APScheduler AsyncIOScheduler to run retention purge on interval.

    Adds:
    - A startup job that runs immediately on scheduler start (catch-up).
    - An interval job that repeats every settings.purge_interval_hours hours.

    Returns the scheduler instance (caller must call scheduler.start()).
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import]

    scheduler = AsyncIOScheduler()

    job_kwargs = dict(
        engine=engine,
        retention_days=settings.retention_days,
        usage_retention_days=settings.usage_retention_days,
    )

    # Catch-up: run immediately on scheduler start
    scheduler.add_job(
        run_retention_purge,
        "date",
        run_date=datetime.now(timezone.utc),
        kwargs=job_kwargs,
        id="retention_purge_startup",
    )

    # Recurring interval job
    scheduler.add_job(
        run_retention_purge,
        "interval",
        hours=settings.purge_interval_hours,
        kwargs=job_kwargs,
        id="retention_purge_interval",
    )

    return scheduler
