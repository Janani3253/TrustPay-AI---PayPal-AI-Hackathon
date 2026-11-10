from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def utc_now() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)


class Cart(Base):
    """PostgreSQL Cart model representing a customer's active shopping cart."""

    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), default="USD", nullable=False)
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

    items: Mapped[List["CartItem"]] = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CartItem.id",
    )


class CartItem(Base):
    """PostgreSQL CartItem model storing authoritative product snapshots and security metadata."""

    __tablename__ = "cart_items"

    __table_args__ = (
        sa.UniqueConstraint(
            "cart_id",
            "provider",
            "external_product_id",
            name="uq_cart_items_cart_product",
        ),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("carts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(sa.String(50), default="DEMO", nullable=False)
    external_product_id: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), default="USD", nullable=False)
    product_snapshot: Mapped[Dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    security_risk_level: Mapped[str] = mapped_column(sa.String(20), default="SAFE", nullable=False)
    security_analysis_status: Mapped[str] = mapped_column(sa.String(30), default="COMPLETE", nullable=False)
    security_findings: Mapped[List[Dict[str, Any]]] = mapped_column(sa.JSON, default=list, nullable=False)
    price_observed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )
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

    cart: Mapped["Cart"] = relationship("Cart", back_populates="items")

