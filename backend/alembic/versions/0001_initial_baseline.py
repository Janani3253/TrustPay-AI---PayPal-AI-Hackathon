"""Initial baseline migration (Alembic version tracking initialized)

Revision ID: 0001_initial_baseline
Revises: 
Create Date: 2026-11-03 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline migration: establishes Alembic revision tracking.
    # Domain models (users, carts, orders, transactions, audit) will be created in their respective phases.
    pass


def downgrade() -> None:
    pass

