import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database, main


class PayPalCaptureTests(unittest.TestCase):
    order_id = "trustpay-order-test"
    paypal_order_id = "PAYPAL-ORDER-TEST"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temporary_directory.name) / "trustpay-test.db"
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.cleanup)

        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (id, name, email, password_hash, created_at)
                VALUES (1, 'Test Buyer', 'buyer@example.test', 'unused', ?)
                """,
                (main.utc_now(),),
            )
            connection.execute(
                """
                INSERT INTO users (id, name, email, password_hash, created_at)
                VALUES (2, 'Other Buyer', 'other@example.test', 'unused', ?)
                """,
                (main.utc_now(),),
            )
            connection.execute(
                """
                INSERT INTO orders
                (id, user_id, version, intent_json, cart_json, total, currency,
                 status, checks_json, paypal_order_id, created_at, updated_at)
                VALUES (?, 1, 1, '{}', ?, 10.0, 'USD', 'paypal_pending',
                        '{"status":"Passed"}', ?, ?, ?)
                """,
                (
                    self.order_id,
                    json.dumps([{
                        "product": {"id": 1, "title": "Test item"},
                        "quantity": 1,
                    }]),
                    self.paypal_order_id,
                    main.utc_now(),
                    main.utc_now(),
                ),
            )
            connection.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (1, 1, 1)"
            )

        self.headers = {"Authorization": f"Bearer {main.create_token(1)}"}
        self.other_buyer_headers = {"Authorization": f"Bearer {main.create_token(2)}"}

    def cleanup(self) -> None:
        self.client.__exit__(None, None, None)
        database.DATABASE_PATH = self.original_database_path
        self.temporary_directory.cleanup()

    def approved_paypal_order(self) -> dict[str, object]:
        return {
            "id": self.paypal_order_id,
            "status": "APPROVED",
            "purchase_units": [{
                "reference_id": self.order_id,
                "amount": {"currency_code": "USD", "value": "10.00"},
            }],
        }

    def completed_paypal_order(
        self,
        amount: str = "10.00",
        currency: str = "USD",
    ) -> dict[str, object]:
        return {
            "id": self.paypal_order_id,
            "status": "COMPLETED",
            "purchase_units": [{
                "reference_id": self.order_id,
                "amount": {"currency_code": "USD", "value": "10.00"},
                "payments": {
                    "captures": [{
                        "id": "PAYPAL-CAPTURE-TEST",
                        "status": "COMPLETED",
                        "final_capture": True,
                        "amount": {"currency_code": currency, "value": amount},
                    }],
                },
            }],
        }

    def created_paypal_order(self) -> dict[str, object]:
        return {
            "id": self.paypal_order_id,
            "status": "CREATED",
            "purchase_units": [{
                "reference_id": self.order_id,
                "amount": {"currency_code": "USD", "value": "10.00"},
            }],
            "links": [{
                "rel": "approve",
                "href": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-TEST",
            }],
        }

    def test_approval_url_rejects_external_hosts_and_nonstandard_ports(self) -> None:
        for href in (
            "https://example.com/checkout",
            "https://www.sandbox.paypal.com:8443/checkout",
            "https://www.sandbox.paypal.com.evil.example/checkout",
        ):
            with self.subTest(href=href), self.assertRaises(main.HTTPException):
                main.paypal_approval_url({
                    "links": [{"rel": "approve", "href": href}],
                })

    def capture(self) -> object:
        return self.client.post(
            "/api/payments/capture-order",
            json={"paypal_order_id": self.paypal_order_id},
            headers=self.headers,
        )

    def test_completed_capture_is_recorded_once_and_clears_matching_cart(self) -> None:
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    (201, self.completed_paypal_order()),
                ]),
            ) as paypal_request,
        ):
            response = self.capture()
            duplicate = self.capture()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertTrue(response.json()["cart_cleared"])
        self.assertEqual(response.json()["product"], "Test item")
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["cart_cleared"])
        self.assertEqual(paypal_request.await_count, 2)

        with database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "completed",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM cart_items WHERE user_id = 1"
                ).fetchone()[0],
                0,
            )

    def test_capture_preserves_a_cart_changed_during_paypal_checkout(self) -> None:
        with database.connect() as connection:
            connection.execute("DELETE FROM cart_items WHERE user_id = 1")
            connection.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (1, 2, 3)"
            )

        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    (201, self.completed_paypal_order()),
                ]),
            ),
        ):
            response = self.capture()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertFalse(response.json()["cart_cleared"])
        with database.connect() as connection:
            cart = connection.execute(
                "SELECT product_id, quantity FROM cart_items WHERE user_id = 1"
            ).fetchone()
            self.assertEqual((cart["product_id"], cart["quantity"]), (2, 3))

    def test_capture_amount_mismatch_is_not_recorded(self) -> None:
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    (201, self.completed_paypal_order("9.00")),
                ]),
            ),
        ):
            response = self.capture()

        self.assertEqual(response.status_code, 409)
        with database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "reconciliation_required",
            )

    def test_capture_currency_mismatch_is_not_recorded(self) -> None:
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    (201, self.completed_paypal_order(currency="INR")),
                ]),
            ),
        ):
            response = self.capture()

        self.assertEqual(response.status_code, 409)
        with database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "reconciliation_required",
            )

    def test_failed_capture_is_not_recorded(self) -> None:
        failed_order = self.approved_paypal_order()
        failed_order["status"] = "DENIED"
        failed_order["purchase_units"][0]["payments"] = {
            "captures": [{
                "id": "PAYPAL-CAPTURE-FAILED",
                "status": "DECLINED",
                "final_capture": True,
                "amount": {"currency_code": "USD", "value": "10.00"},
            }],
        }
        capture_response = {"id": self.paypal_order_id, "status": "DENIED"}
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    (201, capture_response),
                    (200, failed_order),
                ]),
            ),
        ):
            response = self.capture()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "FAILED")
        with database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "failed",
            )

    def test_capture_cannot_be_requested_by_another_user(self) -> None:
        response = self.client.post(
            "/api/payments/capture-order",
            json={"paypal_order_id": self.paypal_order_id},
            headers=self.other_buyer_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_create_order_reuses_sandbox_order_and_request_id(self) -> None:
        with database.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = 'approved' WHERE id = ?",
                (self.order_id,),
            )

        current_cart = [{
            "product": {"id": 1, "title": "Test item"},
            "quantity": 1,
        }]
        created_paypal_order = self.created_paypal_order()
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=current_cart)),
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(return_value=(201, created_paypal_order)),
            ) as paypal_request,
        ):
            response = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )
            retry = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(response.json()["paypal_order_id"], self.paypal_order_id)
        self.assertEqual(retry.json()["approval_url"], response.json()["approval_url"])
        self.assertEqual(paypal_request.await_count, 1)
        self.assertEqual(paypal_request.await_args.kwargs["request_id"], main.payment_request_id("create", self.order_id))
        with database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "paypal_pending",
            )

    def test_create_order_refreshes_incomplete_post_response(self) -> None:
        with database.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = 'approved' WHERE id = ?",
                (self.order_id,),
            )

        current_cart = [{
            "product": {"id": 1, "title": "Test item"},
            "quantity": 1,
        }]
        incomplete_response = {"id": self.paypal_order_id, "status": "CREATED"}
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=current_cart)),
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (201, incomplete_response),
                    (200, self.created_paypal_order()),
                ]),
            ) as paypal_request,
        ):
            response = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["paypal_order_id"], self.paypal_order_id)
        self.assertEqual(paypal_request.await_count, 2)
        self.assertEqual(paypal_request.await_args_list[1].args[:2], (
            "GET",
            f"/v2/checkout/orders/{self.paypal_order_id}",
        ))
        with database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "paypal_pending",
            )

    def test_create_order_rejects_unexpected_refreshed_response(self) -> None:
        with database.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = 'approved' WHERE id = ?",
                (self.order_id,),
            )

        current_cart = [{
            "product": {"id": 1, "title": "Test item"},
            "quantity": 1,
        }]
        incomplete_response = {"id": self.paypal_order_id, "status": "CREATED"}
        invalid_refreshed_order = {
            **self.created_paypal_order(),
            "purchase_units": [],
        }
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=current_cart)),
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (201, incomplete_response),
                    (200, invalid_refreshed_order),
                ]),
            ) as paypal_request,
        ):
            response = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(paypal_request.await_count, 2)
        with database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "reconciliation_required",
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )

    def test_create_order_rejects_a_different_id_in_refreshed_response(self) -> None:
        with database.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = 'approved' WHERE id = ?",
                (self.order_id,),
            )

        current_cart = [{
            "product": {"id": 1, "title": "Test item"},
            "quantity": 1,
        }]
        incomplete_response = {"id": self.paypal_order_id, "status": "CREATED"}
        mismatched_order = {
            **self.created_paypal_order(),
            "id": "DIFFERENT-PAYPAL-ORDER",
        }
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=current_cart)),
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (201, incomplete_response),
                    (200, mismatched_order),
                ]),
            ),
        ):
            response = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409)
        with database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "reconciliation_required",
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )

    def test_create_order_reconciles_existing_paypal_order_without_creating_another(self) -> None:
        with database.connect() as connection:
            connection.execute(
                "UPDATE orders SET status = 'reconciliation_required' WHERE id = ?",
                (self.order_id,),
            )

        current_cart = [{
            "product": {"id": 1, "title": "Test item"},
            "quantity": 1,
        }]
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=current_cart)),
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(return_value=(200, self.created_paypal_order())),
            ) as paypal_request,
        ):
            response = self.client.post(
                "/api/payments/create-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["paypal_order_id"], self.paypal_order_id)
        self.assertEqual(paypal_request.await_count, 1)
        self.assertEqual(paypal_request.await_args.args[:2], (
            "GET",
            f"/v2/checkout/orders/{self.paypal_order_id}",
        ))
        with database.connect() as connection:
            order = connection.execute(
                "SELECT status, paypal_order_id FROM orders WHERE id = ?",
                (self.order_id,),
            ).fetchone()
            self.assertEqual(order["status"], "paypal_pending")
            self.assertEqual(order["paypal_order_id"], self.paypal_order_id)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )

    def test_cancelled_paypal_order_is_not_recorded(self) -> None:
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(return_value=(200, self.created_paypal_order())),
            ),
        ):
            response = self.client.post(
                "/api/payments/cancel-order",
                json={"order_id": self.order_id},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "CANCELLED")
        with database.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM orders WHERE id = ?", (self.order_id,)
                ).fetchone()["status"],
                "cancelled",
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                0,
            )

    def test_capture_timeout_reconciles_provider_status(self) -> None:
        with (
            patch.object(main, "paypal_access_token", new=AsyncMock(return_value="test-token")),
            patch.object(
                main,
                "paypal_api_request",
                new=AsyncMock(side_effect=[
                    (200, self.approved_paypal_order()),
                    main.PayPalTransportError("capture response timed out"),
                    (200, self.completed_paypal_order()),
                ]),
            ) as paypal_request,
        ):
            response = self.capture()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertEqual(paypal_request.await_count, 3)
        with database.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
