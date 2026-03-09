"""A2A transport helpers.

This module centralises how we emit Agent-to-Agent (A2A) messages.
Messages are persisted to the shared database for dashboards and audit,
and can optionally be forwarded to external webhooks for real-time
integrations. By funnelling all message emission through the helpers
below we keep the business logic in negotiator/verifier tools isolated
from transport concerns.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Iterable, List

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from shared.database import SessionLocal
from shared.database.models import A2AEvent
from .a2a import A2AMessage

logger = logging.getLogger(__name__)


def publish_message(
    message: A2AMessage,
    *,
    tags: Iterable[str] | None = None,
    session: Session | None = None,
) -> None:
    """Publish an A2A message.

    Args:
        message: Fully constructed A2A envelope to emit.
        tags: Optional iterable of hint strings that transport/broker
            implementations can use for routing or filtering.

    The implementation persists the message to the local database and,
    when the ``A2A_EVENT_WEBHOOK_URL`` environment variable is set,
    forwards the envelope as JSON to the configured webhook(s). Multiple
    URLs can be provided by comma-separating the value.
    """

    tag_list = list(tags) if tags else []
    tag_suffix = f" tags={tag_list}" if tag_list else ""
    logger.info(
        "A2A publish %s->%s type=%s%s body=%s",
        message.from_agent,
        message.to_agent,
        message.type,
        tag_suffix,
        message.body,
    )

    _persist_event(message, tag_list, session=session)
    _dispatch_webhooks(message, tag_list)


def _persist_event(
    message: A2AMessage,
    tags: List[str],
    *,
    session: Session | None = None,
) -> None:
    """Persist the message into the shared database."""

    owns_session = session is None
    session = session or SessionLocal()
    try:
        existing = (
            session.query(A2AEvent)
            .filter(A2AEvent.message_id == message.id)
            .one_or_none()
        )

        payload = message.to_dict()
        timestamp = _coerce_timestamp(message.timestamp)

        if existing:
            existing.protocol = message.protocol
            existing.message_type = message.type
            existing.from_agent = message.from_agent
            existing.to_agent = message.to_agent
            existing.thread_id = message.thid
            existing.timestamp = timestamp
            existing.tags = tags or None
            existing.body = payload
        else:
            session.add(
                A2AEvent(
                    message_id=message.id,
                    protocol=message.protocol,
                    message_type=message.type,
                    from_agent=message.from_agent,
                    to_agent=message.to_agent,
                    thread_id=message.thid,
                    timestamp=timestamp,
                    tags=tags or None,
                    body=payload,
                )
            )

        if owns_session:
            session.commit()
        else:
            session.flush()
    except SQLAlchemyError:
        if owns_session:
            session.rollback()
        logger.exception("Failed to persist A2A message %s", message.id)
        if not owns_session:
            raise
    finally:
        if owns_session:
            session.close()


def _dispatch_webhooks(message: A2AMessage, tags: List[str]) -> None:
    """Send the message payload to configured webhook endpoints."""

    raw_urls = os.getenv("A2A_EVENT_WEBHOOK_URL", "")
    if not raw_urls:
        return

    urls = [url.strip() for url in raw_urls.split(",") if url.strip()]
    if not urls:
        return

    payload = {
        "message": message.to_dict(),
        "tags": tags,
    }

    for url in urls:
        try:
            response = httpx.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to dispatch A2A webhook to %s: %s", url, exc)


def _coerce_timestamp(value: str | None) -> datetime:
    """Convert message timestamp into a timezone-aware datetime object."""

    if not value:
        return datetime.utcnow()

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.utcnow()

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


__all__ = ["publish_message"]
