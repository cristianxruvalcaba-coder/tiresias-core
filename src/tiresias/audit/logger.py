"""Audit event logger for Tiresias SOP compliance."""
from __future__ import annotations

import uuid
import structlog
from datetime import datetime, timezone
from typing import Any

logger = structlog.get_logger(__name__)

VALID_SOP_EVENT_TYPES = {"sop_check", "sop_grant", "sop_deny", "sop_violation"}


class AuditLogger:
    """Logs SOP compliance events for audit trail."""

    def __init__(self, store=None):
        self.store = store  # Optional persistence backend
        self.log = logger

    def log_event(self, event_type: str, payload: dict[str, Any]) -> str:
        """Log an audit event. Returns event UUID."""
        if event_type not in VALID_SOP_EVENT_TYPES:
            raise ValueError(f"Invalid SOP event type: {event_type}")
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self.log.info("sop_audit_event", **event)
        if self.store:
            self.store.write(event)
        return event_id
