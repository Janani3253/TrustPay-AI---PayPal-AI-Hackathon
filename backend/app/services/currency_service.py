"""Authoritative Currency Conversion and Formatting Service for TrustPay AI."""

from typing import Any, Dict, Optional, Tuple


# Standard authoritative exchange rates (USD is baseline for DummyJSON catalogue)
USD_TO_INR_RATE = 83.0
INR_TO_USD_RATE = 1.0 / USD_TO_INR_RATE  # ≈ 0.012048


class CurrencyService:
    """Service providing explicit currency conversions, formatting, and rate lookups."""

    @staticmethod
    def get_supported_currencies() -> Tuple[str, ...]:
        return ("USD", "INR")

    @staticmethod
    def convert(amount: float, from_currency: str, to_currency: str) -> float:
        """Convert monetary amount between supported currencies."""
        from_curr = (from_currency or "USD").upper()
        to_curr = (to_currency or "USD").upper()

        if from_curr == to_curr:
            return round(amount, 2)

        if from_curr == "USD" and to_curr == "INR":
            return round(amount * USD_TO_INR_RATE, 2)

        if from_curr == "INR" and to_curr == "USD":
            return round(amount * INR_TO_USD_RATE, 2)

        # Fallback if unknown currency
        return round(amount, 2)

    @staticmethod
    def get_symbol(currency: str) -> str:
        """Return the correct currency symbol for the given code."""
        code = (currency or "USD").upper()
        if code == "INR":
            return "₹"
        return "$"

    @classmethod
    def format_money(cls, amount: float, currency: str) -> str:
        """Format an amount cleanly with its matching symbol and code."""
        code = (currency or "USD").upper()
        symbol = cls.get_symbol(code)
        return f"{symbol}{amount:,.2f} {code}"

    @classmethod
    def get_conversion_summary(
        cls, amount: float, from_currency: str, to_currency: str
    ) -> Dict[str, Any]:
        from_curr = (from_currency or "USD").upper()
        to_curr = (to_currency or "USD").upper()
        converted = cls.convert(amount, from_curr, to_curr)
        rate = USD_TO_INR_RATE if from_curr == "USD" else (INR_TO_USD_RATE if from_curr == "INR" else 1.0)
        return {
            "original_amount": amount,
            "original_currency": from_curr,
            "converted_amount": converted,
            "target_currency": to_curr,
            "rate": rate,
            "explanation": (
                f"{cls.format_money(amount, from_curr)} ≈ {cls.format_money(converted, to_curr)} "
                f"(exchange rate: 1 USD = {USD_TO_INR_RATE:.2f} INR)"
            ),
        }


currency_service = CurrencyService()
