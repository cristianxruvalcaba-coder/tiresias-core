from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.encryption.envelope import EnvelopeEncryption
from tiresias.storage.schema import TiresiasAuditLog, TiresiasUsageBucket
from tiresias.tracking.pricing import calculate_cost
from tiresias.tracking.tokens import extract_usage_from_response

logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _bucket_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


async def record_turn(
    tenant_id: str,
    model: str,
    provider: str,
    request_body: dict,
    response_body: dict,
    session_id,
    metadata,
    envelope: EnvelopeEncryption,
    db_session: AsyncSession,
) -> dict:
    messages = request_body.get("messages", [])
    prompt_text = json.dumps(messages)
    completion_text = _extract_completion_text(response_body)

    usage = extract_usage_from_response(response_body)
    prompt_tokens = usage["prompt_tokens"]
    completion_tokens = usage["completion_tokens"]
    total_tokens = usage["total_tokens"]

    cost_usd = calculate_cost(model, prompt_tokens, completion_tokens)

    request_hash = _sha256(json.dumps(request_body, sort_keys=True))
    response_hash = _sha256(json.dumps(response_body, sort_keys=True))

    dek = await envelope.get_or_create_dek(tenant_id, db_session)
    encrypted_prompt = await envelope.encrypt(prompt_text, dek)
    encrypted_completion = await envelope.encrypt(completion_text, dek)

    now = datetime.now(timezone.utc)
    row_id = str(uuid4())
    row = TiresiasAuditLog(
        id=row_id,
        tenant_id=tenant_id,
        encrypted_prompt=encrypted_prompt,
        encrypted_completion=encrypted_completion,
        model=model,
        provider=provider,
        token_count=total_tokens,
        cost_usd=cost_usd,
        session_id=session_id,
        metadata_json=json.dumps(metadata) if metadata else None,
        request_hash=request_hash,
        response_hash=response_hash,
        created_at=now,
    )
    db_session.add(row)

    await _upsert_usage_bucket(
        tenant_id=tenant_id,
        bucket_dt=_bucket_hour(now),
        token_count=total_tokens,
        cost_usd=cost_usd,
        is_error=False,
        db_session=db_session,
    )

    snapshot = {
        "id": row_id,
        "tenant_id": tenant_id,
        "model": model,
        "provider": provider,
        "token_count": total_tokens,
        "cost_usd": cost_usd,
        "session_id": session_id,
        "request_hash": request_hash,
        "response_hash": response_hash,
        "created_at": now,
    }
    await db_session.commit()
    return snapshot


async def record_error_turn(tenant_id: str, model, db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await _upsert_usage_bucket(
        tenant_id=tenant_id,
        bucket_dt=_bucket_hour(now),
        token_count=0,
        cost_usd=0.0,
        is_error=True,
        db_session=db_session,
    )
    await db_session.commit()


async def _upsert_usage_bucket(
    tenant_id: str,
    bucket_dt: datetime,
    token_count: int,
    cost_usd: float,
    is_error: bool,
    db_session: AsyncSession,
) -> None:
    stmt = (
        select(TiresiasUsageBucket)
        .where(
            TiresiasUsageBucket.tenant_id == tenant_id,
            TiresiasUsageBucket.bucket_hour == bucket_dt,
        )
    )
    result = await db_session.execute(stmt)
    bucket = result.scalar_one_or_none()

    if bucket is None:
        bucket = TiresiasUsageBucket(
            id=str(uuid4()),
            tenant_id=tenant_id,
            bucket_hour=bucket_dt,
            token_count=0,
            request_count=0,
            cost_usd=0.0,
            error_count=0,
        )
        db_session.add(bucket)

    bucket.token_count += token_count
    bucket.cost_usd += cost_usd
    if is_error:
        bucket.error_count += 1
    else:
        bucket.request_count += 1


def _extract_completion_text(response_body: dict) -> str:
    choices = response_body.get("choices", [])
    if not choices:
        return ""
    first = choices[0]
    msg = first.get("message", {})
    content = msg.get("content")
    if content is not None:
        return str(content)
    delta = first.get("delta", {})
    return str(delta.get("content", ""))
