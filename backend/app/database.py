import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DATABASE_PATH = Path(os.getenv("TRUSTPAY_DATABASE_PATH", Path(__file__).resolve().parents[1] / "trustpay.db"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                PRIMARY KEY (user_id, product_id)
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                intent_json TEXT NOT NULL,
                cart_json TEXT NOT NULL,
                total REAL NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                checks_json TEXT,
                paypal_order_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                approved_version INTEGER NOT NULL,
                approved_snapshot_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                approved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                order_id TEXT NOT NULL REFERENCES orders(id),
                product TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                date TEXT NOT NULL,
                method TEXT NOT NULL,
                status TEXT NOT NULL,
                verification TEXT NOT NULL,
                paypal_reference TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                description TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            );
            """
        )

        order_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(orders)")
        }
        for column in (
            "paypal_create_request_id",
            "paypal_capture_request_id",
            "paypal_capture_id",
            "paypal_approval_url",
        ):
            if column not in order_columns:
                connection.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")

        unique_keys = (
            ("orders", "paypal_order_id"),
            ("orders", "paypal_create_request_id"),
            ("orders", "paypal_capture_request_id"),
            ("orders", "paypal_capture_id"),
            ("transactions", "order_id"),
            ("transactions", "paypal_reference"),
        )
        for table, column in unique_keys:
            duplicate = connection.execute(
                f"""
                SELECT 1
                FROM {table}
                WHERE {column} IS NOT NULL
                GROUP BY {column}
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            ).fetchone()
            if duplicate:
                raise RuntimeError(
                    f"Cannot enforce payment idempotency: duplicate existing values "
                    f"were found in {table}.{column}. Review the existing records "
                    "before restarting the backend."
                )

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_paypal_order_id
            ON orders(paypal_order_id)
            WHERE paypal_order_id IS NOT NULL
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_paypal_create_request_id
            ON orders(paypal_create_request_id)
            WHERE paypal_create_request_id IS NOT NULL
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_paypal_capture_request_id
            ON orders(paypal_capture_request_id)
            WHERE paypal_capture_request_id IS NOT NULL
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_paypal_capture_id
            ON orders(paypal_capture_id)
            WHERE paypal_capture_id IS NOT NULL
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_order_id
            ON transactions(order_id)
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_paypal_reference
            ON transactions(paypal_reference)
            WHERE paypal_reference IS NOT NULL
        """)
