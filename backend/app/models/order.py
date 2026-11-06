from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    """PostgreSQL Order model storing immutable purchase snapshot and verification state."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    cart_id: Mapped[Optional[int]] = mapped_column(
        sa.Integer,
        sa.ForeignKey("carts.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(30),
        default="pending_verification",
        index=True,
        nullable=False,
    )
    intent_json: Mapped[Dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    items_json: Mapped[List[Dict[str, Any]]] = mapped_column(sa.JSON, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    shipping: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    tax: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), default="USD", nullable=False)
    checks_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(sa.JSON, nullable=True)
    snapshot_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    paypal_order_id: Mapped[Optional[str]] = mapped_column(sa.String(128), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )

    approvals: Mapped[List["Approval"]] = relationship(
        "Approval",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

