from datetime import datetime, timezone
from typing import TYPE_CHECKING
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthSession(Base):
    """Authentication session tracking active JWT token identifiers (JTIs)."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jti: Mapped[str] = mapped_column(
        sa.String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=sa.func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")

    @property
    def is_active(self) -> bool:
        """Return True if session has not been revoked and has not expired."""
        now = utc_now()
        return self.revoked_at is None and self.expires_at > now

    def revoke(self) -> None:
        """Mark this session as revoked."""
        self.revoked_at = utc_now()

    def __repr__(self) -> str:
        return f"<AuthSession id={self.id} user_id={self.user_id} jti={self.jti[:8]}... active={self.is_active}>"

