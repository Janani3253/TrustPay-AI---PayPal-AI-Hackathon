import re
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.verification import (
    BackendVerification,
    BackendVerificationCheck,
    CheckStatus,
    OverallDecision,
    VerificationTotals,
)
from app.services.cart_service import cart_service

logger = logging.getLogger(__name__)


def parse_numeric_with_unit(text: str) -> Optional[float]:
    """Parse numeric value with units like GB, TB, inch, etc."""
    if not text:
        return None
    cleaned = text.strip().upper()
    # Check TB
    tb_match = re.search(r"(\d+(?:\.\d+)?)\s*TB", cleaned)
    if tb_match:
        return float(tb_match.group(1)) * 1024
    # Check GB
    gb_match = re.search(r"(\d+(?:\.\d+)?)\s*GB", cleaned)
    if gb_match:
        return float(gb_match.group(1))
    # Plain number
    num_match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if num_match:
        return float(num_match.group(1))
    return None


class IntentLockEngine:
    """
    Deterministic purchase verification engine for TrustPay AI.
    Verifies that shopping cart contents strictly adhere to the customer's original
    purchase intent, specifications, budget boundaries, exclusions, and security policy.
    """

    @staticmethod
    def verify_budget(
        totals: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> BackendVerificationCheck:
        """Verify that total payable amount does not exceed customer budget."""
        max_budget = intent.get("maximumBudget")
        if max_budget is None:
            # Fallback to structured_intent
            structured = intent.get("structured_intent") or {}
            budget_spec = structured.get("budget") or {}
            max_budget = budget_spec.get("amount")

        if max_budget is None:
            return BackendVerificationCheck(
                name="Budget Limit Verification",
                status="Passed",
                reason="No maximum budget specified in customer intent.",
                critical=False,
            )

        max_budget_dec = Decimal(str(max_budget))
        total_dec = Decimal(str(totals.get("total", "0.00")))

        # Check currency
        intent_curr = intent.get("currency", "USD")
        cart_curr = totals.get("currency", "USD")
        if intent_curr != cart_curr:
            return BackendVerificationCheck(
                name="Currency Alignment",
                status="Failed",
                reason=f"Currency mismatch: Intent specified {intent_curr} but cart currency is {cart_curr}.",
                critical=True,
            )

        if total_dec > max_budget_dec:
            return BackendVerificationCheck(
                name="Budget Limit Verification",
                status="Failed",
                reason=(
                    f"Total ${float(total_dec):.2f} exceeds customer maximum budget of ${float(max_budget_dec):.2f}."
                ),
                critical=True,
            )

        return BackendVerificationCheck(
            name="Budget Limit Verification",
            status="Passed",
            reason=f"Total payable ${float(total_dec):.2f} is within budget of ${float(max_budget_dec):.2f}.",
            critical=True,
        )

    @staticmethod
    def verify_security(items: List[Dict[str, Any]]) -> List[BackendVerificationCheck]:
        """Verify that all products in cart passed prompt injection security analysis."""
        checks = []
        for item in items:
            product = item.get("product", {})
            title = product.get("title", f"Product {product.get('id')}")
            risk = item.get("security_risk") or product.get("security_risk_level") or "SAFE"

            if risk == "MALICIOUS":
                checks.append(
                    BackendVerificationCheck(
                        name=f"Security Policy: {title}",
                        status="Failed",
                        reason=f"Product '{title}' contains malicious prompt injection or adversarial directives.",
                        critical=True,
                    )
                )
            elif risk == "SUSPICIOUS":
                checks.append(
                    BackendVerificationCheck(
                        name=f"Security Policy: {title}",
                        status="Needs Review",
                        reason=f"Product '{title}' contains suspicious patterns requiring customer confirmation.",
                        critical=True,
                    )
                )
            else:
                checks.append(
                    BackendVerificationCheck(
                        name=f"Security Policy: {title}",
                        status="Passed",
                        reason=f"Product '{title}' verified clean without security threats detected.",
                        critical=True,
                    )
                )
        return checks

    @staticmethod
    def verify_exclusions(
        items: List[Dict[str, Any]],
        intent: Dict[str, Any],
    ) -> List[BackendVerificationCheck]:
        """Verify that no explicitly excluded conditions or items are present."""
        checks = []
        exclude_accessories = intent.get("excludeAccessories", False)

        structured = intent.get("structured_intent") or {}
        excluded_conditions = structured.get("excluded_conditions") or []

        # Check excludeAccessories
        if exclude_accessories:
            has_accessories = any(
                it.get("product", {}).get("category", "").lower() in ["accessories", "mobile-accessories"]
                for it in items
            )
            if has_accessories:
                checks.append(
                    BackendVerificationCheck(
                        name="Exclusions: No Accessories",
                        status="Failed",
                        reason="Customer explicitly excluded accessories, but an accessory product was found in cart.",
                        critical=True,
                    )
                )
            else:
                checks.append(
                    BackendVerificationCheck(
                        name="Exclusions: No Accessories",
                        status="Passed",
                        reason="No excluded accessories present in order.",
                        critical=True,
                    )
                )

        # Check structured excluded conditions (e.g. refurbished, used)
        for excl in excluded_conditions:
            cond_name = excl.get("condition", "") if isinstance(excl, dict) else str(excl)
            cond_lower = cond_name.lower()
            violation_found = False

            for it in items:
                prod = it.get("product", {})
                search_text = f"{prod.get('title', '')} {prod.get('description', '')}".lower()
                if cond_lower in search_text:
                    checks.append(
                        BackendVerificationCheck(
                            name=f"Exclusions: No {cond_name}",
                            status="Failed",
                            reason=f"Product '{prod.get('title')}' matches customer exclusion '{cond_name}'.",
                            critical=True,
                        )
                    )
                    violation_found = True
                    break

            if not violation_found and cond_name:
                checks.append(
                    BackendVerificationCheck(
                        name=f"Exclusions: No {cond_name}",
                        status="Passed",
                        reason=f"No products matching exclusion '{cond_name}' detected.",
                        critical=True,
                    )
                )

        return checks

    @staticmethod
    def verify_mandatory_specifications(
        items: List[Dict[str, Any]],
        intent: Dict[str, Any],
    ) -> List[BackendVerificationCheck]:
        """Verify that products satisfy mandatory requirements."""
        checks = []
        structured = intent.get("structured_intent") or {}
        specs = structured.get("mandatory_specifications") or []

        # If frontend sent requirements array directly
        frontend_reqs = intent.get("requirements") or []
        for req in frontend_reqs:
            r_name = req.get("name", "")
            r_val = req.get("value", "")
            # Convert to spec dict if not already in specs
            if not any(s.get("name", "").lower() == r_name.lower() for s in specs if isinstance(s, dict)):
                specs.append({"name": r_name, "value": r_val, "operator": "GTE"})

        for spec in specs:
            if not isinstance(spec, dict):
                continue
            name = spec.get("name", "").strip()
            operator = spec.get("operator", "GTE").upper()
            target_val = str(spec.get("value", "")).strip()
            name_lower = name.lower()

            matched = False
            explanation = ""

            for it in items:
                prod = it.get("product", {})
                title = prod.get("title", "")
                desc = prod.get("description", "")
                brand = prod.get("brand", "")
                full_text = f"{title} {desc}".lower()

                # 1. Brand match
                if name_lower in ["brand", "preferred_brand"]:
                    if target_val.lower() in brand.lower() or target_val.lower() in title.lower():
                        matched = True
                        explanation = f"Brand matched '{target_val}' on product '{title}'."
                    else:
                        explanation = f"Expected brand '{target_val}', found '{brand}'."

                # 2. RAM match
                elif "ram" in name_lower or "memory" in name_lower:
                    req_num = parse_numeric_with_unit(target_val)
                    ram_match = re.search(r"(\d+)\s*(?:gb)?\s*(?:ram|ddr|memory)", full_text)
                    if not ram_match:
                        ram_match = re.search(r"(?:ram|memory)\s*:?\s*(\d+)", full_text)
                    prod_num = float(ram_match.group(1)) if ram_match else parse_numeric_with_unit(full_text)
                    if req_num is not None and prod_num is not None:
                        if operator in ["GTE", ">="] and prod_num >= req_num:
                            matched = True
                            explanation = f"RAM {prod_num}GB meets requirement (>= {req_num}GB)."
                        elif operator in ["EQ", "=="] and prod_num == req_num:
                            matched = True
                            explanation = f"RAM {prod_num}GB matches exact requirement."
                        else:
                            explanation = f"RAM {prod_num}GB does not satisfy requirement ({operator} {req_num}GB)."
                    elif target_val.lower() in full_text:
                        matched = True
                        explanation = f"RAM specification '{target_val}' found in product details."
                    else:
                        explanation = f"RAM specification '{target_val}' could not be verified in product description."

                # 3. Storage / SSD match
                elif "storage" in name_lower or "ssd" in name_lower or "hdd" in name_lower:
                    req_num = parse_numeric_with_unit(target_val)
                    storage_tb = re.search(r"(\d+(?:\.\d+)?)\s*tb\s*(?:ssd|hdd|storage|drive)?", full_text)
                    storage_gb = re.search(r"(\d+)\s*(?:gb)?\s*(?:ssd|hdd|storage|drive|rom)", full_text)
                    if storage_tb:
                        prod_num = float(storage_tb.group(1)) * 1024
                    elif storage_gb:
                        prod_num = float(storage_gb.group(1))
                    else:
                        prod_num = None

                    if req_num is not None and prod_num is not None:
                        if operator in ["GTE", ">="] and prod_num >= req_num:
                            matched = True
                            explanation = f"Storage {prod_num}GB meets requirement (>= {req_num}GB)."
                        elif operator in ["EQ", "=="] and prod_num == req_num:
                            matched = True
                            explanation = f"Storage {prod_num}GB matches exact requirement."
                        else:
                            explanation = f"Storage {prod_num}GB does not satisfy requirement ({operator} {req_num}GB)."
                    elif target_val.lower() in full_text:
                        matched = True
                        explanation = f"Storage requirement '{target_val}' found in product details."
                    else:
                        explanation = f"Storage requirement '{target_val}' not found in description."

                # 4. Generic specification
                else:
                    if target_val.lower() in full_text:
                        matched = True
                        explanation = f"Specification '{name}: {target_val}' verified in product text."
                    else:
                        explanation = f"Specification '{name}: {target_val}' was not substantiated by product metadata."

                if matched:
                    break

            if matched:
                checks.append(
                    BackendVerificationCheck(
                        name=f"Specification: {name}",
                        status="Passed",
                        reason=explanation,
                        critical=True,
                    )
                )
            else:
                checks.append(
                    BackendVerificationCheck(
                        name=f"Specification: {name}",
                        status="Failed",
                        reason=explanation or f"Mandatory requirement '{name}' not satisfied.",
                        critical=True,
                    )
                )

        return checks

    @classmethod
    def verify_order_against_intent(
        cls,
        order_id: str,
        order_version: int,
        cart_items: List[Dict[str, Any]],
        intent: Dict[str, Any],
        cart_version: Optional[int] = None,
    ) -> BackendVerification:
        """
        Execute comprehensive deterministic IntentLock verification suite.
        Returns BackendVerification model matching frontend contract.
        """
        checks: List[BackendVerificationCheck] = []

        # 1. Cart Integrity & Version Check
        if not cart_items:
            checks.append(
                BackendVerificationCheck(
                    name="Cart Content Verification",
                    status="Failed",
                    reason="Shopping cart is empty. Cannot verify an empty order.",
                    critical=True,
                )
            )
        elif cart_version is not None and cart_version != order_version:
            checks.append(
                BackendVerificationCheck(
                    name="Order Version Consistency",
                    status="Failed",
                    reason="The cart changed after order creation. Re-verify the updated cart.",
                    critical=True,
                )
            )
        else:
            checks.append(
                BackendVerificationCheck(
                    name="Order Version Consistency",
                    status="Passed",
                    reason=f"Order version {order_version} matches current cart state.",
                    critical=True,
                )
            )

        # 2. Financial Totals Calculation
        totals = cart_service.calculate_totals(cart_items)

        # 3. Budget Verification
        budget_check = cls.verify_budget(totals, intent)
        checks.append(budget_check)

        # 4. Security Policy Check
        security_checks = cls.verify_security(cart_items)
        checks.extend(security_checks)

        # 5. Exclusions Check
        exclusion_checks = cls.verify_exclusions(cart_items, intent)
        checks.extend(exclusion_checks)

        # 6. Mandatory Specifications Check
        spec_checks = cls.verify_mandatory_specifications(cart_items, intent)
        checks.extend(spec_checks)

        # 7. Determine Overall Decision
        critical_failed = any(c.status == "Failed" and c.critical for c in checks)
        needs_review = any(c.status == "Needs Review" for c in checks)

        if critical_failed:
            overall_status = "Failed"
            decision = OverallDecision.BLOCKED
        elif needs_review:
            overall_status = "Failed"
            decision = OverallDecision.NEEDS_REVIEW
        else:
            overall_status = "Passed"
            decision = OverallDecision.READY_FOR_APPROVAL

        return BackendVerification(
            order_id=order_id,
            order_version=order_version,
            status=overall_status,
            checks=checks,
            totals=VerificationTotals(**totals),
            decision=decision,
        )


intentlock_engine = IntentLockEngine()
