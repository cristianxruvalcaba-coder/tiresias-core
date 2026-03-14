from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasAuditLog

logger = logging.getLogger(__name__)


def new_session_id() -> str:
    from uuid import uuid4
    return str(uuid4())


def parse_session_id(header_value) -> "str | None":
    if not header_value:
        return None
    cleaned = header_value.strip()
    if not cleaned:
        return None
    return cleaned[:128]


async def tag_session(session_id: str, metadata: dict, db_session: AsyncSession) -> int:
    stmt = select(TiresiasAuditLog).where(TiresiasAuditLog.session_id == session_id)
    result = await db_session.execute(stmt)
    rows = result.scalars().all()
    updated = 0
    for row in rows:
        existing = {}
        if row.metadata_json:
            try:
                existing = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                existing = {}
        existing.update(metadata)
        row.metadata_json = json.dumps(existing)
        updated += 1
    if updated > 0:
        await db_session.commit()
    return updated


async def get_session_records(session_id: str, db_session: AsyncSession):
    stmt = (
        select(TiresiasAuditLog)
        .where(
            TiresiasAuditLog.session_id == session_id,
            TiresiasAuditLog.deleted_at.is_(None),
        )
        .order_by(TiresiasAuditLog.created_at.asc())
    )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


async def get_session_stats(session_id: str, db_session: AsyncSession) -> dict:
    records = await get_session_records(session_id, db_session)
    total_tokens = sum(r.token_count or 0 for r in records)
    total_cost = sum(r.cost_usd or 0.0 for r in records)
    return {
        "session_id": session_id,
        "request_count": len(records),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 8),
        "first_request_at": records[0].created_at.isoformat() if records else None,
        "last_request_at": records[-1].created_at.isoformat() if records else None,
    }
