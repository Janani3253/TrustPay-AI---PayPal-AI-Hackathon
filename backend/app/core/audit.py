import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from app.database import connect

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def add_audit(user_id: int, event_type: str, description: str) -> None:
    """Record an audit event to the append-only SHA-256 hash chain in SQLite."""
    event_id = str(uuid.uuid4())
    timestamp = utc_now()
    try:
        with connect() as connection:
            previous = connection.execute(
                "SELECT hash FROM audit_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            previous_hash = previous["hash"] if previous else "GENESIS"
            payload = {"id": event_id, "type": event_type, "timestamp": timestamp, "description": description}
            digest = hashlib.sha256(f"{previous_hash}:{json_dump(payload)}".encode()).hexdigest()
            connection.execute(
                """INSERT INTO audit_events
                   (id, user_id, type, timestamp, description, previous_hash, hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_id, user_id, event_type, timestamp, description, previous_hash, digest),
            )
    except Exception as exc:
        logger.debug("Audit write skipped or failed: %s", str(exc))

