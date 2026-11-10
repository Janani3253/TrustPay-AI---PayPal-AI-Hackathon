from datetime import datetime, timezone
from typing import List, TYPE_CHECKING
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .auth_session import AuthSession


def utc_now() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)


class User(Base):
    """User account model for customers and administrators."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    email: Mapped[str] = mapped_column(
        sa.String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        sa.String(30),
        nullable=False,
        default="customer",
        server_default="customer",
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=sa.func.now(),
    )

    # Relationships
    sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @classmethod
    def normalize_email(cls, email: str) -> str:
        """Normalize email address to lowercase and strip whitespace."""
        return email.strip().lower()

    def __getitem__(self, key: str):
        """Provide dictionary-style access for backwards compatibility with legacy routes."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r} is_active={self.is_active}>"
