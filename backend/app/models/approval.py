from datetime import datetime, timezone
from typing import TYPE_CHECKING
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .order import Order


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Approval(Base):
    """PostgreSQL Customer Approval model recording explicit user purchase confirmation."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    approved_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    approved_snapshot_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), default="approved", nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )

    order: Mapped["Order"] = relationship("Order", back_populates="approvals")

