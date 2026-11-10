"""SQLAlchemy 2.x model for tamper-evident audit log entries."""

from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    """Append-only, SHA-256 hashed audit log record."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_audit_events_user_id_users"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    timestamp: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    previous_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )

    user = relationship("User", backref="audit_events")

    def __repr__(self) -> str:
        return f"<AuditEvent id={self.id} type={self.type} hash={self.hash[:12]}...>"

