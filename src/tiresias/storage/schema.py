from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TiresiasAuditLog(Base):
    __tablename__ = "tiresias_audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    encrypted_prompt: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_completion: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TiresiasLicense(Base):
    __tablename__ = "tiresias_licenses"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    feature_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    kek_provider: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jwt_signature: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TiresiasUsageBucket(Base):
    __tablename__ = "tiresias_usage_buckets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    bucket_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "bucket_hour"),)


class TiresiasApiLog(Base):
    __tablename__ = "tiresias_api_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    api_service: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    path_pattern: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    request_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class TiresiasApiEndpointBucket(Base):
    __tablename__ = "tiresias_api_endpoint_buckets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    api_service: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path_pattern: Mapped[str] = mapped_column(String(1024), nullable=False)
    bucket_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_sum_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_min_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_max_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "api_service", "method", "path_pattern", "bucket_hour"),
    )
