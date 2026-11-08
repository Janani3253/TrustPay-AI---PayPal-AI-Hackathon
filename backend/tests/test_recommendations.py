import asyncio
import httpx
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database, main
from app.schemas import IntentRequest


class RecommendationCurrencyTests(unittest.TestCase):
    exchange_rate = 80.0
    rate_date = "2026-11-07"

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
        self.headers = {"Authorization": f"Bearer {main.create_token(1)}"}

    def cleanup(self) -> None:
        self.client.__exit__(None, None, None)
        database.DATABASE_PATH = self.original_database_path
        self.temporary_directory.cleanup()

    @staticmethod
    def products() -> list[dict[str, object]]:
        return [
            {
                "id": 1,
                "title": "iPhone 5s",
                "description": "Smartphone",
                "category": "smartphones",
                "brand": "Apple",
                "price": 199.99,
                "tags": ["phone"],
            },
            {
                "id": 2,
                "title": "iPhone 6",
                "description": "Smartphone",
                "category": "smartphones",
                "brand": "Apple",
                "price": 299.99,
                "tags": ["phone"],
            },
            {
                "id": 3,
                "title": "iPhone 13 Pro",
                "description": "Smartphone",
                "category": "smartphones",
                "brand": "Apple",
                "price": 1099.99,
                "tags": ["phone"],
            },
            {
                "id": 4,
                "title": "Galaxy S Series",
                "description": "Android smartphone",
                "category": "smartphones",
                "brand": "Samsung",
                "price": 399.99,
                "tags": ["phone"],
            },
        ]

    @staticmethod
    def request(budget: float, currency: str) -> dict[str, object]:
        symbol = "₹" if currency == "INR" else "$"
        return {
            "intent": {
                "request": f"Find an iPhone under {symbol}{budget:,.0f}",
                "category": "smartphones",
                "requirements": [],
                "maximumBudget": budget,
                "currency": currency,
                "trustedSellersOnly": False,
                "excludeAccessories": False,
            },
        }

    async def lookup_rate(self, base: str, quote: str) -> dict[str, object] | None:
        rate = 1.0 if base == quote else self.exchange_rate
        return {"rate": rate, "date": self.rate_date}

    def search(self, budget: float, currency: str, products: list[dict[str, object]] | None = None):
        with (
            patch.object(
                main,
                "dummyjson_get",
                new=AsyncMock(return_value={"products": products or self.products()}),
            ),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            return self.client.post(
                "/api/recommendations/search",
                json=self.request(budget, currency),
                headers=self.headers,
            )

    def search_text(self, text: str, budget: float, currency: str, products: list[dict[str, object]]):
        intent = main.parse_intent(IntentRequest(
            request=text,
            maximumBudget=budget,
            currency=currency,
            trustedSellersOnly=False,
        ))
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            return self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

    def test_inr_budget_converts_catalogue_prices_and_includes_estimated_fees(self) -> None:
        response = self.search(80_000, "INR")

        self.assertEqual(response.status_code, 200)
        recommendations = {
            item["product"]["title"]: item["analysis"]
            for item in response.json()["recommendations"]
        }
        affordable = recommendations["iPhone 5s"]

        self.assertEqual(affordable["catalogueCurrency"], "USD")
        self.assertEqual(affordable["cataloguePrice"], 199.99)
        self.assertEqual(affordable["convertedPrice"], 15_999.2)
        self.assertEqual(affordable["comparisonCurrency"], "INR")
        self.assertEqual(affordable["comparableTotal"], 17_598.4)
        self.assertTrue(affordable["budgetMatched"])
        self.assertEqual(affordable["status"], "Matches Requirements")
        self.assertEqual(affordable["exchangeRate"], self.exchange_rate)
        self.assertEqual(affordable["exchangeRateDate"], self.rate_date)
        self.assertEqual(affordable["matchType"], "Exact Match")
        self.assertEqual(set(recommendations), {"iPhone 5s", "iPhone 6"})
        self.assertNotIn("Galaxy S Series", recommendations)
        self.assertNotIn("iPhone 13 Pro", recommendations)
        self.assertEqual(
            response.json()["recommendations"][0]["product"]["title"],
            "iPhone 5s",
        )

    def test_usd_budget_compares_directly_in_usd(self) -> None:
        response = self.search(500, "USD")

        self.assertEqual(response.status_code, 200)
        recommendations = {
            item["product"]["title"]: item["analysis"]
            for item in response.json()["recommendations"]
        }
        self.assertEqual(recommendations["iPhone 5s"]["comparableTotal"], 219.98)
        self.assertEqual(recommendations["iPhone 5s"]["exchangeRate"], 1.0)
        self.assertTrue(recommendations["iPhone 5s"]["budgetMatched"])
        self.assertEqual(set(recommendations), {"iPhone 5s", "iPhone 6"})

    def test_request_parser_detects_budget_currency_and_category(self) -> None:
        inr_intent = main.parse_intent(IntentRequest(
            request="Find an iPhone under ₹80,000",
            maximumBudget=1,
            currency="USD",
            trustedSellersOnly=False,
        ))
        usd_intent = main.parse_intent(IntentRequest(
            request="Find an iPhone under $500",
            maximumBudget=1,
            currency="INR",
            trustedSellersOnly=False,
        ))

        self.assertEqual(inr_intent["maximumBudget"], 80_000)
        self.assertEqual(inr_intent["currency"], "INR")
        self.assertEqual(inr_intent["category"], "smartphones")
        self.assertEqual(usd_intent["maximumBudget"], 500)
        self.assertEqual(usd_intent["currency"], "USD")

    def test_request_parser_detects_laptop_and_ram_for_original_request(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find a Samsung laptop with 16GB RAM under ₹60,000",
            maximumBudget=1,
            currency="USD",
            trustedSellersOnly=False,
        ))

        self.assertEqual(intent["category"], "laptops")
        self.assertEqual(intent["requirements"], [{"name": "RAM", "value": "16GB"}])
        self.assertEqual(intent["maximumBudget"], 60_000)
        self.assertEqual(intent["currency"], "INR")

    def test_mobile_category_words_are_not_repeated_as_literal_name_requirements(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find a Samsung mobile phones under ₹60,000",
            maximumBudget=1,
            currency="USD",
            trustedSellersOnly=False,
        ))

        self.assertEqual(intent["category"], "smartphones")
        self.assertEqual(intent["mandatoryTerms"], ["samsung"])

    def test_request_parser_extracts_general_attributes_and_budget_ranges(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find 2 black cotton T-shirts in size L between $10 and $50",
            maximumBudget=1,
            currency="INR",
            trustedSellersOnly=False,
        ))

        self.assertEqual(intent["minimumBudget"], 10)
        self.assertEqual(intent["maximumBudget"], 50)
        self.assertEqual(intent["currency"], "USD")
        self.assertEqual(intent["quantity"], 2)
        self.assertEqual(
            {(item["name"], item["value"]) for item in intent["requirements"]},
            {("Size", "L"), ("Color", "black"), ("Material", "cotton")},
        )
        self.assertNotIn("10", intent["mandatoryTerms"])
        self.assertNotIn("50", intent["mandatoryTerms"])

    def test_optional_preferences_are_not_strict_filters(self) -> None:
        request = "Find a laptop, preferably Samsung"
        intent = main.parse_intent(IntentRequest(
            request=request,
            maximumBudget=1000,
            currency="USD",
            trustedSellersOnly=False,
        ))
        laptop = {
            "id": 20,
            "title": "Acer Travel Laptop",
            "description": "Portable computer",
            "category": "laptops",
            "brand": "Acer",
            "price": 300,
            "tags": [],
        }

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": [laptop]})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["brand"] for item in response.json()["recommendations"]], ["Acer"])

    def test_unseen_category_and_material_are_checked_from_catalogue_fields(self) -> None:
        request = "Find a wooden study table under ₹8,000"
        intent = main.parse_intent(IntentRequest(
            request=request,
            maximumBudget=80_000,
            currency="INR",
            trustedSellersOnly=False,
        ))
        table = {
            "id": 21,
            "title": "Study Table",
            "description": "Study table",
            "category": "furniture",
            "price": 50,
            "currency": "USD",
            "tags": [],
            "specifications": {"Material": "Wood"},
        }
        unrelated_category = {**table, "id": 22, "category": "home-decoration"}

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={
                "products": [table, unrelated_category],
            })),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [21])

    def test_unseen_feature_category_requires_each_structured_feature(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find wireless headphones with noise cancellation under $200",
            maximumBudget=200,
            currency="USD",
            trustedSellersOnly=False,
        ))
        headphones = {
            "id": 23,
            "title": "Wireless Headphones",
            "description": "Headphones",
            "category": "audio",
            "price": 100,
            "currency": "USD",
            "tags": ["headphones"],
            "specifications": {"Features": ["Wireless", "Noise cancellation"]},
        }
        missing_feature = {
            **headphones,
            "id": 24,
            "title": "Wireless Headphones Basic",
            "specifications": {"Features": ["Wireless"]},
        }
        unrelated = {
            **headphones,
            "id": 25,
            "title": "Wireless Speaker",
            "tags": ["speaker"],
        }

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={
                "products": [headphones, missing_feature, unrelated],
            })),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [23])

    def test_minimum_capacity_uses_structured_measurements(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find a refrigerator with at least 300 litres capacity",
            maximumBudget=80_000,
            currency="INR",
            trustedSellersOnly=False,
        ))
        products = [
            {
                "id": 41,
                "title": "Refrigerator 350L",
                "category": "appliances",
                "price": 400,
                "currency": "USD",
                "tags": [],
                "specifications": {"Capacity": "350 L"},
            },
            {
                "id": 42,
                "title": "Refrigerator 250L",
                "category": "appliances",
                "price": 400,
                "currency": "USD",
                "tags": [],
                "specifications": {"Capacity": "250 L"},
            },
            {
                "id": 43,
                "title": "Refrigerator",
                "category": "appliances",
                "price": 400,
                "currency": "USD",
                "tags": [],
            },
        ]

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [41])

    def test_model_brand_and_verified_storage_are_all_mandatory(self) -> None:
        request = "Find an iPhone 15 with 256GB storage under $1,000"
        intent = main.parse_intent(IntentRequest(
            request=request,
            maximumBudget=1000,
            currency="USD",
            trustedSellersOnly=False,
        ))
        matching = {
            "id": 26,
            "title": "iPhone 15",
            "description": "Phone",
            "category": "smartphones",
            "brand": "Apple",
            "price": 800,
            "currency": "USD",
            "tags": [],
            "specifications": {"Storage": "256GB"},
        }
        wrong_brand = {**matching, "id": 27, "brand": "Samsung"}
        wrong_storage = {
            **matching,
            "id": 28,
            "specifications": {"Storage": "128GB"},
        }
        missing_storage = {**matching, "id": 29, "specifications": {}}

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={
                "products": [matching, wrong_brand, wrong_storage, missing_storage],
            })),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [26])

    def test_budget_boundary_is_inclusive_and_above_boundary_is_rejected(self) -> None:
        product = {
            "id": 30,
            "title": "iPhone 5s",
            "description": "Phone",
            "category": "smartphones",
            "brand": "Apple",
            "price": 90,
            "currency": "USD",
            "tags": [],
        }

        boundary_response = self.search_text(
            "Find an iPhone under $104.49", 104.49, "USD", [product],
        )
        over_boundary_response = self.search_text(
            "Find an iPhone under $104.48", 104.48, "USD", [product],
        )

        self.assertEqual(len(boundary_response.json()["recommendations"]), 1)
        self.assertEqual(over_boundary_response.json()["recommendations"], [])

    def test_minimum_and_maximum_price_range_are_both_enforced(self) -> None:
        products = [
            {
                "id": 31,
                "title": "iPhone 5s",
                "category": "smartphones",
                "brand": "Apple",
                "price": 90,
                "currency": "USD",
                "tags": [],
            },
            {
                "id": 32,
                "title": "iPhone 6",
                "category": "smartphones",
                "brand": "Apple",
                "price": 200,
                "currency": "USD",
                "tags": [],
            },
            {
                "id": 33,
                "title": "iPhone 13 Pro",
                "category": "smartphones",
                "brand": "Apple",
                "price": 600,
                "currency": "USD",
                "tags": [],
            },
        ]
        response = self.search_text(
            "Find 2 iPhones from $100 to $500", 1000, "USD", products,
        )

        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual([item["product"]["id"] for item in recommendations], [32])
        self.assertEqual(recommendations[0]["analysis"]["comparableTotal"], 429.99)

    def test_size_color_and_material_are_mandatory_across_categories(self) -> None:
        intent = main.parse_intent(IntentRequest(
            request="Find a black cotton T-shirt in size L",
            maximumBudget=500,
            currency="USD",
            trustedSellersOnly=False,
        ))
        products = [
            {
                "id": 38,
                "title": "Black Cotton T-Shirt",
                "category": "mens-shirts",
                "price": 20,
                "currency": "USD",
                "tags": [],
                "specifications": {"Color": "Black", "Material": "Cotton", "Size": "L"},
            },
            {
                "id": 39,
                "title": "Black Cotton T-Shirt",
                "category": "mens-shirts",
                "price": 20,
                "currency": "USD",
                "tags": [],
                "specifications": {"Color": "Black", "Material": "Cotton", "Size": "M"},
            },
            {
                "id": 40,
                "title": "Black Cotton T-Shirt",
                "category": "womens-dresses",
                "price": 20,
                "currency": "USD",
                "tags": [],
                "specifications": {"Color": "Black", "Material": "Cotton", "Size": "L"},
            },
        ]

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [38])

    def test_explicit_exclusion_requires_structured_attribute_evidence(self) -> None:
        request = "Find a chair without leather"
        intent = main.parse_intent(IntentRequest(
            request=request,
            maximumBudget=500,
            currency="USD",
            trustedSellersOnly=False,
        ))
        products = [
            {
                "id": 34,
                "title": "Wooden Chair",
                "category": "furniture",
                "price": 100,
                "currency": "USD",
                "tags": [],
                "specifications": {"Material": "Wood"},
            },
            {
                "id": 35,
                "title": "Leather Chair",
                "category": "furniture",
                "price": 100,
                "currency": "USD",
                "tags": [],
                "specifications": {"Material": "Leather"},
            },
            {
                "id": 36,
                "title": "Unspecified Chair",
                "category": "furniture",
                "price": 100,
                "currency": "USD",
                "tags": [],
            },
        ]

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [34])

    def test_unknown_catalogue_currency_is_not_budget_compliant(self) -> None:
        product = {
            "id": 37,
            "title": "iPhone 5s",
            "category": "smartphones",
            "brand": "Apple",
            "price": 100,
            "currency": "EUR",
            "tags": [],
        }
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": [product]})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(return_value=None)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json=self.request(500, "USD"),
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        self.assertIn("currency conversion", response.json()["message"])

    def test_category_only_requests_do_not_get_misleading_high_scores(self) -> None:
        product = self.products()[0]
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": [product]})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={
                    "intent": {
                        "request": "Find a smartphone under ₹80,000",
                        "category": "smartphones",
                        "requirements": [],
                        "maximumBudget": 80_000,
                        "currency": "INR",
                        "trustedSellersOnly": False,
                        "excludeAccessories": False,
                    },
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertLess(response.json()["recommendations"][0]["analysis"]["percentage"], 60)

    def test_category_mismatch_is_excluded(self) -> None:
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": [self.products()[0]]})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={
                    "intent": {
                        **self.request(500, "USD")["intent"],
                        "category": "laptops",
                    },
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        self.assertEqual(response.json()["total"], 0)
        self.assertIn("category", response.json()["message"])

    def test_recommendations_only_include_products_in_requested_category(self) -> None:
        laptop = {
            "id": 5,
            "title": "Samsung Galaxy Book",
            "description": "Laptop computer",
            "category": "laptops",
            "brand": "Samsung",
            "price": 500,
            "tags": ["laptop"],
            "specifications": {"RAM": "16GB"},
        }
        unrelated_products = [
            *self.products(),
            laptop,
            {
                **laptop,
                "id": 8,
                "title": "Other Brand Laptop",
                "brand": "Acer",
            },
            {
                **laptop,
                "id": 9,
                "title": "Samsung Laptop with 8GB RAM",
                "specifications": {"RAM": "8GB"},
            },
            {
                **laptop,
                "id": 10,
                "title": "Samsung Expensive Laptop",
                "price": 1000,
            },
            {
                "id": 6,
                "title": "Samsung Smart Watch",
                "description": "Smartwatch",
                "category": "mens-watches",
                "brand": "Samsung",
                "price": 100,
                "tags": ["watch"],
            },
            {
                "id": 7,
                "title": "Mirror",
                "description": "Decorative mirror",
                "category": "home-decoration",
                "price": 20,
                "tags": [],
            },
        ]
        intent = main.parse_intent(IntentRequest(
            request="Find a Samsung laptop with 16GB RAM under ₹60,000",
            maximumBudget=1,
            currency="USD",
            trustedSellersOnly=False,
        ))

        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": unrelated_products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual([item["product"]["category"] for item in recommendations], ["laptops"])
        self.assertEqual(recommendations[0]["product"]["title"], "Samsung Galaxy Book")

    def test_samsung_mobile_request_returns_live_catalogue_matches_within_inr_budget(self) -> None:
        products = [
            {
                "id": 131,
                "title": "Samsung Galaxy S7",
                "description": "A Samsung smartphone",
                "category": "smartphones",
                "brand": "Samsung",
                "price": 299.99,
                "tags": ["smartphones", "samsung galaxy"],
            },
            {
                "id": 132,
                "title": "Samsung Galaxy S8",
                "description": "A Samsung smartphone",
                "category": "smartphones",
                "brand": "Samsung",
                "price": 499.99,
                "tags": ["smartphones", "samsung galaxy"],
            },
            {
                "id": 133,
                "title": "Samsung Galaxy S10",
                "description": "A Samsung smartphone",
                "category": "smartphones",
                "brand": "Samsung",
                "price": 750,
                "tags": ["smartphones", "samsung galaxy"],
            },
            {
                "id": 134,
                "title": "Samsung Smart Watch",
                "category": "mens-watches",
                "brand": "Samsung",
                "price": 100,
                "tags": ["smartwatch"],
            },
            {
                "id": 135,
                "title": "Apple iPhone",
                "category": "smartphones",
                "brand": "Apple",
                "price": 200,
                "tags": ["smartphones"],
            },
        ]

        response = self.search_text(
            "Find a Samsung mobile phones under ₹60,000",
            60_000,
            "INR",
            products,
        )

        self.assertEqual(response.status_code, 200)
        recommendations = response.json()["recommendations"]
        self.assertEqual(
            [item["product"]["id"] for item in recommendations],
            [131, 132],
        )
        self.assertTrue(all(item["analysis"]["budgetMatched"] for item in recommendations))
        self.assertTrue(all(item["analysis"]["brandMatched"] for item in recommendations))

    def test_category_synonyms_use_product_category_and_title_without_crossing_types(self) -> None:
        self.assertTrue(main._category_matches_product(
            "smartphones", "smartphones", ["phone"], True, "Samsung Galaxy S8"
        ))
        self.assertFalse(main._category_matches_product(
            "mens-watches", "smartphones", ["phone"], True, "Samsung Galaxy Watch"
        ))
        self.assertTrue(main._category_matches_product(
            "audio", "headphones", ["headphone"], True, "Wireless Headphones"
        ))
        self.assertTrue(main._category_matches_product(
            "furniture", "furniture", ["table"], True, "Wooden Study Table"
        ))
        self.assertFalse(main._category_matches_product(
            "furniture", "furniture", ["table"], True, "Office Chair"
        ))

    def test_catalogue_retrieval_reads_all_pages_and_deduplicates_products(self) -> None:
        catalogue = AsyncMock(side_effect=[
            {
                "total": 4,
                "products": [{"id": 1}, {"id": 2}],
            },
            {
                "total": 4,
                "products": [{"id": 2}, {"id": 3}],
            },
        ])
        with patch.object(main, "dummyjson_get", new=catalogue):
            products = asyncio.run(main._fetch_catalogue_products())

        self.assertEqual([product["id"] for product in products], [1, 2, 3])
        self.assertEqual(catalogue.await_args_list[0].args, ("/products", {"limit": 100, "skip": 0}))
        self.assertEqual(catalogue.await_args_list[1].args, ("/products", {"limit": 100, "skip": 2}))

    def test_incomplete_catalogue_page_is_an_api_error(self) -> None:
        catalogue = AsyncMock(side_effect=[
            {"total": 2, "products": [{"id": 1}]},
            {"total": 2, "products": []},
        ])
        with patch.object(main, "dummyjson_get", new=catalogue):
            with self.assertRaises(main.HTTPException) as error:
                asyncio.run(main._fetch_catalogue_products())

        self.assertEqual(error.exception.status_code, 502)

    def test_brand_can_come_from_title_but_not_conflicting_brand_or_description(self) -> None:
        products = [
            {
                "id": 141,
                "title": "Samsung Galaxy S8",
                "category": "smartphones",
                "price": 400,
                "tags": ["smartphones"],
            },
            {
                "id": 142,
                "title": "Samsung Galaxy S8",
                "category": "smartphones",
                "brand": "Acer",
                "price": 200,
                "tags": ["smartphones"],
            },
            {
                "id": 143,
                "title": "Acer Galaxy S8",
                "description": "Compatible with Samsung phones",
                "category": "smartphones",
                "price": 200,
                "tags": ["smartphones"],
            },
        ]

        response = self.search_text(
            "Find a Samsung smartphone under $1,000",
            1_000,
            "USD",
            products,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["product"]["id"] for item in response.json()["recommendations"]],
            [141],
        )

    def test_backend_reextracts_requirements_from_original_request(self) -> None:
        intent = {
            "request": "Find a Samsung laptop with 16GB RAM under $800",
            "category": "",
            "requirements": [],
            "maximumBudget": 800,
            "currency": "USD",
            "trustedSellersOnly": False,
            "excludeAccessories": False,
        }
        products = [
            {
                "id": 44,
                "title": "Samsung Galaxy Book",
                "category": "laptops",
                "brand": "Samsung",
                "price": 500,
                "currency": "USD",
                "tags": [],
                "specifications": {"RAM": "16GB"},
            },
            {
                "id": 45,
                "title": "Samsung Galaxy Book",
                "category": "laptops",
                "brand": "Samsung",
                "price": 400,
                "currency": "USD",
                "tags": [],
                "specifications": {"RAM": "8GB"},
            },
            {
                "id": 46,
                "title": "Samsung Galaxy Phone",
                "category": "smartphones",
                "brand": "Samsung",
                "price": 200,
                "currency": "USD",
                "tags": [],
                "specifications": {"RAM": "16GB"},
            },
        ]
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": products})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json={"intent": intent},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["product"]["id"] for item in response.json()["recommendations"]], [44])

    def test_exchange_rate_failure_is_never_budget_compliant(self) -> None:
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": self.products()})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(return_value=None)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json=self.request(80_000, "INR"),
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        self.assertIn("No products matched", response.json()["message"])

    def test_stale_exchange_rate_is_rejected(self) -> None:
        stale_date = "2026-10-30"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"date": stale_date, "rate": self.exchange_rate},
            )
        )
        real_async_client = httpx.AsyncClient
        with patch.object(
            main.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: real_async_client(transport=transport, **kwargs),
        ):
            rate = asyncio.run(main.get_exchange_rate("USD", "INR"))

        self.assertIsNone(rate)

    def test_missing_laptop_specifications_are_not_marked_as_matches(self) -> None:
        laptop = {
            "id": 4,
            "title": "Laptop Pro",
            "description": "16GB RAM and 512GB SSD",
            "category": "laptops",
            "price": 700,
            "tags": [],
        }
        intent = {
            "intent": {
                "request": "Find a laptop with 16GB RAM and 512GB SSD under $800",
                "category": "laptops",
                "requirements": [
                    {"name": "RAM", "value": "16GB"},
                    {"name": "Storage", "value": "512GB SSD"},
                ],
                "maximumBudget": 800,
                "currency": "USD",
                "trustedSellersOnly": False,
                "excludeAccessories": False,
            },
        }
        with (
            patch.object(main, "dummyjson_get", new=AsyncMock(return_value={"products": [laptop]})),
            patch.object(main, "get_exchange_rate", new=AsyncMock(side_effect=self.lookup_rate)),
        ):
            response = self.client.post(
                "/api/recommendations/search",
                json=intent,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
        self.assertIn("No products matched", response.json()["message"])

    def create_and_verify_order(self, item: dict[str, object], budget: float = 20_000, rate_available: bool = True):
        items = [{"product": item, "quantity": 1}]
        intent = self.request(budget, "INR")["intent"]
        with patch.object(main, "current_cart", new=AsyncMock(return_value=items)):
            created = self.client.post(
                "/api/orders",
                json={"intent": intent},
                headers=self.headers,
            )
        self.assertEqual(created.status_code, 201)

        rate_result = (
            AsyncMock(side_effect=self.lookup_rate)
            if rate_available
            else AsyncMock(return_value=None)
        )
        with (
            patch.object(main, "current_cart", new=AsyncMock(return_value=items)),
            patch.object(main, "get_exchange_rate", new=rate_result),
        ):
            verified = self.client.post(
                "/api/verification/order",
                json={"order_id": created.json()["id"]},
                headers=self.headers,
            )
        return created.json(), verified

    def test_over_budget_order_and_exchange_failure_cannot_be_approved(self) -> None:
        item = {
            "id": 2,
            "title": "iPhone 6",
            "category": "smartphones",
            "price": 299.99,
        }
        created, verified = self.create_and_verify_order(item)

        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.json()["status"], "Failed")
        self.assertEqual(
            next(check for check in verified.json()["checks"] if check["name"] == "Final price")["status"],
            "Failed",
        )
        self.assertEqual(verified.json()["budgetComparison"]["amount"], 25_998.4)
        with patch.object(main, "current_cart", new=AsyncMock(return_value=[{"product": item, "quantity": 1}])):
            approval = self.client.post(
                f"/api/approvals/{created['id']}/approve",
                json={"order_version": 1},
                headers=self.headers,
            )
        self.assertEqual(approval.status_code, 409)
        payment = self.client.post(
            "/api/payments/create-order",
            json={"order_id": created["id"]},
            headers=self.headers,
        )
        self.assertEqual(payment.status_code, 409)

        created, verified = self.create_and_verify_order(item, rate_available=False)
        self.assertEqual(verified.json()["status"], "Failed")
        self.assertIsNone(verified.json()["budgetComparison"]["amount"])
        with patch.object(main, "current_cart", new=AsyncMock(return_value=[{"product": item, "quantity": 1}])):
            approval = self.client.post(
                f"/api/approvals/{created['id']}/approve",
                json={"order_version": 1},
                headers=self.headers,
            )
        self.assertEqual(approval.status_code, 409)

    def test_in_budget_order_can_be_verified_and_explicitly_approved(self) -> None:
        item = {
            "id": 1,
            "title": "iPhone 5s",
            "category": "smartphones",
            "price": 199.99,
        }
        created, verified = self.create_and_verify_order(item, budget=80_000)

        self.assertEqual(verified.json()["status"], "Passed")
        self.assertEqual(verified.json()["budgetComparison"]["amount"], 17_598.4)
        with patch.object(main, "current_cart", new=AsyncMock(return_value=[{"product": item, "quantity": 1}])):
            approval = self.client.post(
                f"/api/approvals/{created['id']}/approve",
                json={"order_version": 1},
                headers=self.headers,
            )
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.json()["status"], "approved")

    def test_cart_change_invalidates_the_created_order(self) -> None:
        original_item = {
            "id": 1,
            "title": "iPhone 5s",
            "category": "smartphones",
            "price": 199.99,
        }
        changed_item = {**original_item, "price": 299.99}
        with patch.object(main, "current_cart", new=AsyncMock(return_value=[{"product": original_item, "quantity": 1}])):
            created = self.client.post(
                "/api/orders",
                json={"intent": self.request(80_000, "INR")["intent"]},
                headers=self.headers,
            )
        with patch.object(main, "current_cart", new=AsyncMock(return_value=[{"product": changed_item, "quantity": 1}])):
            verified = self.client.post(
                "/api/verification/order",
                json={"order_id": created.json()["id"]},
                headers=self.headers,
            )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(verified.json()["status"], "Failed")
        self.assertEqual(verified.json()["checks"][0]["name"], "Order version")


if __name__ == "__main__":
    unittest.main()
