"""SQLAlchemy 2.x model for completed or captured transactions."""

from datetime import datetime, timezone
from decimal import Decimal
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Transaction(Base):
    """Immutable record of finalized financial transactions."""

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_transactions_user_id_users"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("orders.id", ondelete="CASCADE", name="fk_transactions_order_id_orders"),
        nullable=False,
        index=True,
    )
    product: Mapped[str] = mapped_column(sa.Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), server_default="USD", nullable=False)
    date: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    method: Mapped[str] = mapped_column(sa.String(50), server_default="PayPal Sandbox", nullable=False)
    status: Mapped[str] = mapped_column(sa.String(30), server_default="Completed", nullable=False)
    verification: Mapped[str] = mapped_column(sa.String(50), server_default="Backend verified", nullable=False)
    paypal_reference: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        server_default=sa.func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User", backref="transactions")
    order = relationship("Order", backref="transaction")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} order_id={self.order_id} amount={self.amount} status={self.status}>"

