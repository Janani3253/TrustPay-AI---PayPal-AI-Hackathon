"""Create carts and cart_items tables

Revision ID: 0003_create_carts_and_cart_items
Revises: 0002_create_users_and_auth_sessions
Create Date: 2026-11-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_create_carts_and_cart_items"
down_revision: Union[str, None] = "0002_create_users_and_auth_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create carts table
    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_carts_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_carts"),
    )
    op.create_index("ix_carts_user_id", "carts", ["user_id"], unique=True)

    # 2. Create cart_items table
    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cart_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), server_default="DEMO", nullable=False),
        sa.Column("external_product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("product_snapshot", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("security_risk_level", sa.String(length=20), server_default="SAFE", nullable=False),
        sa.Column("security_analysis_status", sa.String(length=30), server_default="COMPLETE", nullable=False),
        sa.Column("security_findings", sa.JSON(), nullable=False),
        sa.Column("price_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], name="fk_cart_items_cart_id_carts", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_cart_items"),
        sa.UniqueConstraint("cart_id", "provider", "external_product_id", name="uq_cart_items_cart_product"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_external_product_id", "cart_items", ["external_product_id"])


def downgrade() -> None:
    op.drop_index("ix_cart_items_external_product_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_carts_user_id", table_name="carts")
    op.drop_table("carts")

