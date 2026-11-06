from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base
import app.models  # ensure models are registered with Base.metadata

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def test_alembic_config_loads():
    """Verify alembic.ini exists and can be parsed with latest migration head."""
    assert ALEMBIC_INI.exists()
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0].startswith("000")


def test_alembic_revisions_chain():
    """Verify migration revision lineage."""
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    rev1 = script.get_revision("0001_initial_baseline")
    assert rev1 is not None
    assert rev1.down_revision is None

    rev2 = script.get_revision("0002_users_auth_sessions")
    assert rev2 is not None
    assert rev2.down_revision == "0001_initial_baseline"
    assert "Create users and auth_sessions tables" in rev2.doc

    rev3 = script.get_revision("0003_carts_cart_items")
    assert rev3 is not None
    assert rev3.down_revision == "0002_users_auth_sessions"

    rev4 = script.get_revision("0004_orders_approvals")
    assert rev4 is not None
    assert rev4.down_revision == "0003_carts_cart_items"

    rev5 = script.get_revision("0005_transactions_audit")
    assert rev5 is not None
    assert rev5.down_revision == "0004_orders_approvals"

    assert all(len(revision.revision) <= 32 for revision in (rev1, rev2, rev3, rev4, rev5))


def test_base_metadata_is_ready_for_migrations():
    """Verify Base.metadata contains required domain tables."""
    assert hasattr(Base, "metadata")
    table_names = {t.name for t in Base.metadata.tables.values()}
    assert "users" in table_names
    assert "auth_sessions" in table_names
    assert "carts" in table_names
    assert "cart_items" in table_names
    assert "orders" in table_names
    assert "approvals" in table_names
    assert "transactions" in table_names
    assert "audit_events" in table_names
