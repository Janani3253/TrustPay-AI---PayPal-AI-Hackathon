import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.recommendation import (
    MatchTier,
    ProductRecommendationItem,
    RecommendationResponse,
    RecommendationScoreBreakdown,
    RequirementMatchItem,
)
from app.services.currency_service import currency_service
from app.services.product_service import product_service

logger = logging.getLogger(__name__)


# Standard Product Taxonomy Rules & Exclusions
CATEGORY_RULES: Dict[str, Dict[str, Any]] = {
    "headphones": {
        "aliases": [
            "headphone", "headphones", "earphone", "earphones", "earbud",
            "earbuds", "headset", "headsets", "in-ear", "airpods", "ear pods"
        ],
        "excluded_keywords": [
            "phone case", "silicone case", "protective case", "charger",
            "wireless charger", "fast charger", "cable", "lightning cable",
            "car mount", "holder", "stand", "screen protector", "selfie stick",
            "speaker", "smart speaker", "soundbar", "adapter"
        ],
        "dummyjson_categories": ["mobile-accessories"],
        "search_queries": ["headphones", "earbuds", "earphones", "headset", "airpods"],
    },
    "smartphones": {
        "aliases": ["smartphone", "smartphones", "phone", "phones", "mobile phone", "cellphone"],
        "excluded_keywords": [
            "case", "cover", "charger", "cable", "screen protector",
            "tempered glass", "mount", "stand", "holder", "selfie stick", "battery pack"
        ],
        "dummyjson_categories": ["smartphones"],
        "search_queries": ["smartphone", "phone", "galaxy", "iphone"],
    },
    "laptops": {
        "aliases": ["laptop", "laptops", "notebook", "notebooks", "macbook", "computer"],
        "excluded_keywords": ["laptop bag", "sleeve", "backpack", "keyboard cover", "cooling pad"],
        "dummyjson_categories": ["laptops"],
        "search_queries": ["laptop", "macbook", "thinkpad"],
    },
    "shoes": {
        "aliases": [
            "shoe", "shoes", "sneaker", "sneakers", "sports shoes", "running shoes",
            "footwear", "boots", "sandals", "loafers"
        ],
        "excluded_keywords": ["socks", "shirt", "t-shirt", "pants", "bag", "jacket", "dress"],
        "dummyjson_categories": ["mens-shoes", "womens-shoes"],
        "search_queries": ["shoes", "sneakers", "running shoes"],
    },
}

KNOWN_COLORS = {
    "black", "white", "red", "blue", "green", "silver", "gold", "gray", "grey",
    "yellow", "purple", "orange", "pink", "brown", "navy", "midnight", "space black",
    "matte black", "jet black", "rose gold"
}

KNOWN_CONNECTIVITIES = {
    "wireless", "bluetooth", "wired", "usb-c", "lightning", "aux", "3.5mm", "tws"
}


class RecommendationService:
    """
    Intelligent recommendation engine for customer shopping intent.
    Enforces strict product filtering before scoring:
    - Strict Category / Product-Type Matching (prevents accessory pollution)
    - Strict Budget & Cross-Currency Matching (using authoritative rate 1 USD = 83 INR)
    - Strict Brand Matching (prioritizes or enforces customer requested brand)
    - Strict Feature & Specification Verification (unverified attributes marked NOT VERIFIED)
    - Product Availability (excludes out-of-stock items)

    Weighted Recommendation Ranking:
    Recommendation Score = 30% Category + 25% Feature + 20% Price + 15% Brand + 10% Rating.
    Normalized between 0 and 100 (and 0.0 - 1.0).
    Enforces invariant: A high score NEVER compensates for a mandatory criteria violation.
    Only products satisfying all requirements and verified features receive FULL MATCH.
    """

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text).lower().split())

    def _identify_canonical_category(self, category_input: str, request_text: str) -> Optional[str]:
        """Map user category or request string to a canonical product category key."""
        combined = self._normalize_text(f"{category_input} {request_text}")
        for canon, conf in CATEGORY_RULES.items():
            for alias in conf["aliases"]:
                if re.search(r"\b" + re.escape(alias) + r"\b", combined):
                    return canon
        return None

    def _validate_product_category(
        self,
        product: Dict[str, Any],
        canonical_cat: Optional[str],
        requested_category_str: str,
    ) -> Tuple[bool, str]:
        """
        Check if product truly belongs to the requested category and is not an excluded accessory.
        """
        title = self._normalize_text(product.get("title", ""))
        desc = self._normalize_text(product.get("description", ""))
        tags = [self._normalize_text(t) for t in product.get("tags", [])]
        prod_cat = self._normalize_text(product.get("category", ""))

        if not canonical_cat:
            # Generic category comparison if not in pre-defined canonical list
            req_norm = self._normalize_text(requested_category_str)
            if not req_norm or req_norm in ("all", "general", "any", "not specified"):
                return True, "No specific category restrictions."
            if req_norm in prod_cat or req_norm in title:
                return True, f"Product matches category '{requested_category_str}'."
            return False, f"Product category '{prod_cat}' does not match requested '{requested_category_str}'."

        conf = CATEGORY_RULES[canonical_cat]

        # 1. Check for negative / exclusion keywords in product title
        for exc in conf["excluded_keywords"]:
            if re.search(r"\b" + re.escape(exc) + r"\b", title):
                return False, f"Excluded accessory: Product title contains '{exc}', not target category '{canonical_cat}'."

        # 2. Check if product title or tags positively indicate target category
        has_positive_alias = False
        for alias in conf["aliases"]:
            if re.search(r"\b" + re.escape(alias) + r"\b", title) or any(alias in t for t in tags):
                has_positive_alias = True
                break

        # For categories like smartphones or laptops, also accept exact DummyJSON category
        if prod_cat in conf["dummyjson_categories"]:
            if canonical_cat in ("smartphones", "laptops", "shoes"):
                has_positive_alias = True

        if has_positive_alias:
            return True, f"Verified product type matches requested '{canonical_cat}'."

        # Check in description as secondary fallback, but with strict penalty if title is unrelated
        for alias in conf["aliases"]:
            if re.search(r"\b" + re.escape(alias) + r"\b", desc):
                return True, f"Description mentions '{alias}' for category '{canonical_cat}'."

        return False, f"Product does not match target category '{canonical_cat}' (found: {prod_cat})."

    def _verify_single_feature(
        self,
        feature_text: str,
        product: Dict[str, Any],
    ) -> Tuple[str, bool, str]:
        """
        Verify if a specific customer feature is present in API product data.
        Returns: (status: "Matched" | "Not matched" | "Not verified", is_verified: bool, explanation: str)
        """
        feat_clean = feature_text.split(":")[-1].strip() if ":" in feature_text else feature_text.strip()
        feat_norm = self._normalize_text(feat_clean)

        title = self._normalize_text(product.get("title", ""))
        desc = self._normalize_text(product.get("description", ""))
        tags = " ".join([self._normalize_text(t) for t in product.get("tags", [])])
        warranty = self._normalize_text(product.get("warrantyInformation", ""))
        shipping = self._normalize_text(product.get("shippingInformation", ""))
        searchable_text = f"{title} {tags} {desc} {warranty} {shipping}"

        # 1. Color feature check
        is_color_req = False
        target_color = ""
        for c in KNOWN_COLORS:
            if c in feat_norm:
                is_color_req = True
                target_color = c
                break

        if is_color_req:
            # Look for color in title, description, or tags
            pattern = r"\b" + re.escape(target_color) + r"\b"
            if re.search(pattern, title) or re.search(pattern, tags):
                return "Matched", True, f"Verified {target_color.title()} color in product details."
            elif re.search(pattern, desc):
                return "Matched", True, f"Description specifies {target_color} color."
            else:
                # Color is NOT provided in the API response. Do not invent!
                return "Not verified", False, f"Color ({target_color.title()}) is not provided in product API data."

        # 2. Connectivity feature check (e.g. Wireless, Bluetooth)
        is_conn_req = False
        target_conn = ""
        for conn in KNOWN_CONNECTIVITIES:
            if conn in feat_norm:
                is_conn_req = True
                target_conn = conn
                break

        if is_conn_req:
            pattern = r"\b" + re.escape(target_conn) + r"\b"
            if re.search(pattern, searchable_text):
                return "Matched", True, f"Verified {target_conn.title()} connectivity in product details."
            else:
                # Check if it explicitly says wired when wireless was requested
                if "wireless" in target_conn or "bluetooth" in target_conn:
                    if "wired" in searchable_text:
                        return "Not matched", True, "Product specifies wired connection, not wireless."
                return "Not verified", False, f"Connectivity ({target_conn.title()}) not confirmed in API data."

        # 3. General specification or keyword
        words = [w for w in feat_norm.split() if len(w) > 2]
        if words:
            matched_words = [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", searchable_text)]
            if len(matched_words) == len(words):
                return "Matched", True, f"Specification '{feat_clean}' verified in product details."
            elif matched_words:
                return "Not verified", False, f"Partially mentioned in API data ({', '.join(matched_words)})."
            else:
                return "Not verified", False, f"Feature '{feat_clean}' is not documented in product API data."

        return "Not verified", False, f"Feature '{feat_clean}' could not be verified."

    async def get_recommendations(
        self,
        intent_data: Dict[str, Any],
        limit: int = 50,
    ) -> RecommendationResponse:
        """
        Evaluate catalogue products against customer intent with strict multi-layer filtering:
        1. Retrieve candidates from supported provider.
        2. Filter out products that violate mandatory constraints (wrong category, over budget, brand conflict).
        3. Verify all requested features without fabricating missing attributes.
        4. Compute normalized recommendation score:
           Score = 30% Category + 25% Feature + 20% Price + 15% Brand + 10% Rating.
        5. Group into MatchTier: FULL MATCH, PARTIAL MATCH, NOT VERIFIED, EXCLUDED.
        6. Return ranked recommendations.
        """
        # 1. Parse intent parameters
        category_raw = intent_data.get("category", "").strip()
        brands = intent_data.get("brand", [])
        if isinstance(brands, str):
            brands = [brands] if brands.strip() else []

        max_budget = intent_data.get("max_budget")
        if max_budget is None:
            max_budget = intent_data.get("maximumBudget")
        if max_budget is not None:
            try:
                max_budget = float(max_budget)
            except (ValueError, TypeError):
                max_budget = None

        currency = intent_data.get("currency", "USD").upper()
        features = intent_data.get("features", [])
        if isinstance(features, str):
            features = [features] if features.strip() else []

        requirements = intent_data.get("requirements", [])
        for req in requirements:
            if isinstance(req, dict):
                r_name = req.get("name", "").strip()
                r_val = req.get("value", "").strip()
                if r_name.lower() in ("brand", "preferred_brand") and r_val not in brands:
                    brands.append(r_val)
                elif r_name and r_val and f"{r_name}: {r_val}" not in features:
                    features.append(f"{r_name}: {r_val}")

        query = intent_data.get("request", "") or intent_data.get("query", "") or intent_data.get("original_request", "")
        canonical_category = self._identify_canonical_category(category_raw, query)

        # 2. Fetch candidate products from product_service
        raw_candidates: List[Dict[str, Any]] = []
        try:
            if canonical_category and canonical_category in CATEGORY_RULES:
                conf = CATEGORY_RULES[canonical_category]
                seen_ids: Set[int] = set()

                # Fetch from category endpoints
                for cat_slug in conf["dummyjson_categories"]:
                    try:
                        res = await product_service.list_products(category=cat_slug, limit=50)
                        for p in res.products:
                            p_dict = p.model_dump(by_alias=True)
                            p_id = p_dict.get("id")
                            if p_id not in seen_ids:
                                seen_ids.add(p_id)
                                raw_candidates.append(p_dict)
                    except Exception:
                        pass

                # For categories without a 1:1 DummyJSON category (like headphones in mobile-accessories)
                # or if category listing yielded no products, fetch by targeted search queries:
                if not raw_candidates or canonical_category == "headphones":
                    for q_term in conf["search_queries"][:2]:
                        try:
                            res = await product_service.search_products(query=q_term, limit=50)
                            for p in res.products:
                                p_dict = p.model_dump(by_alias=True)
                                p_id = p_dict.get("id")
                                if p_id not in seen_ids:
                                    seen_ids.add(p_id)
                                    raw_candidates.append(p_dict)
                        except Exception:
                            pass

            elif category_raw and category_raw.lower() not in ("all", "general"):
                cat_slug = category_raw.lower().replace(" ", "-")
                res = await product_service.list_products(category=cat_slug, limit=50)
                raw_candidates = [p.model_dump(by_alias=True) for p in res.products]

            elif query:
                words = [w for w in query.split() if len(w) > 2][:3]
                q_str = " ".join(words)
                res = await product_service.search_products(query=q_str, limit=50)
                raw_candidates = [p.model_dump(by_alias=True) for p in res.products]

            if not raw_candidates:
                fallback_res = await product_service.list_products(limit=50)
                raw_candidates = [p.model_dump(by_alias=True) for p in fallback_res.products]

        except Exception as exc:
            logger.error("Failed to query catalogue for recommendations: %s", exc)
            raw_candidates = []

        # 3. Evaluate each product against intent criteria
        evaluated_items: List[ProductRecommendationItem] = []

        for prod in raw_candidates:
            prod_title = prod.get("title", "")
            prod_brand = prod.get("brand", "") or ""
            prod_category = prod.get("category", "")
            prod_price = float(prod.get("price", 0.0))
            prod_rating = float(prod.get("rating", 0.0))
            stock_raw = prod.get("stock")
            prod_stock = int(stock_raw) if stock_raw is not None else 1
            prod_avail = prod.get("availabilityStatus", "In Stock")

            mismatch_reasons: List[str] = []
            unverified_features: List[str] = []
            matches_list: List[RequirementMatchItem] = []

            # --- A. Strict Category Match (30 pts) ---
            cat_matched, cat_reason = self._validate_product_category(
                prod, canonical_category, category_raw
            )
            category_score = 30.0 if cat_matched else 0.0
            if not cat_matched:
                mismatch_reasons.append(cat_reason)
            matches_list.append(RequirementMatchItem(
                name="Category",
                requested=category_raw or canonical_category or "Any",
                status="Matched" if cat_matched else "Not matched",
                explanation=cat_reason,
                verified=cat_matched,
            ))

            # --- B. Strict Budget & Cross-Currency Match (20 pts) ---
            # DummyJSON prices are in USD. Standard fees: 5% tax + $9.99 shipping.
            estimated_total_usd = round(prod_price * 1.05 + 9.99, 2)
            budget_matched: Optional[bool] = True
            price_score = 0.0
            price_explanation = ""

            if max_budget is not None and max_budget > 0:
                if currency == "INR":
                    # Convert USD total to INR using authoritative currency_service
                    effective_inr = currency_service.convert(estimated_total_usd, "USD", "INR")
                    if effective_inr <= max_budget:
                        budget_matched = True
                        price_score = 20.0
                        price_explanation = (
                            f"Total with estimated fees (~{currency_service.format_money(effective_inr, 'INR')}) "
                            f"is within budget limit of {currency_service.format_money(max_budget, 'INR')}."
                        )
                    else:
                        budget_matched = False
                        price_score = 0.0
                        reason = (
                            f"Price exceeds budget: Estimated total {currency_service.format_money(effective_inr, 'INR')} "
                            f"(product ${prod_price:.2f} USD + fees) exceeds maximum budget of {currency_service.format_money(max_budget, 'INR')}."
                        )
                        price_explanation = reason
                        mismatch_reasons.append(reason)
                else:
                    # USD budget
                    if estimated_total_usd <= max_budget:
                        budget_matched = True
                        price_score = 20.0
                        price_explanation = (
                            f"Total with estimated fees (${estimated_total_usd:.2f} USD) is within budget limit (${max_budget:.2f} USD)."
                        )
                    else:
                        budget_matched = False
                        price_score = 0.0
                        reason = (
                            f"Price exceeds budget: Estimated total ${estimated_total_usd:.2f} USD "
                            f"exceeds maximum budget of ${max_budget:.2f} USD."
                        )
                        price_explanation = reason
                        mismatch_reasons.append(reason)
            else:
                budget_matched = True
                price_score = 20.0
                price_explanation = "No maximum budget specified."

            matches_list.append(RequirementMatchItem(
                name="Budget Limit",
                requested=currency_service.format_money(max_budget, currency) if max_budget else "None",
                status="Matched" if budget_matched else "Not matched",
                explanation=price_explanation,
                verified=True,
            ))

            # --- C. Strict Brand Match (15 pts) ---
            brand_score = 0.0
            brand_matched = True
            brand_explanation = ""

            if brands:
                matched_b = False
                for b in brands:
                    b_norm = self._normalize_text(b)
                    if (
                        re.search(r"\b" + re.escape(b_norm) + r"\b", self._normalize_text(prod_brand))
                        or re.search(r"\b" + re.escape(b_norm) + r"\b", self._normalize_text(prod_title))
                    ):
                        matched_b = True
                        break

                if matched_b:
                    brand_score = 15.0
                    brand_matched = True
                    brand_explanation = f"Brand matches requested '{', '.join(brands)}'."
                else:
                    brand_score = 0.0
                    brand_matched = False
                    reason = f"Brand '{prod_brand or 'Generic'}' does not match requested brand(s): {', '.join(brands)}."
                    brand_explanation = reason
                    mismatch_reasons.append(reason)
            else:
                brand_score = 15.0
                brand_matched = True
                brand_explanation = "No specific brand requirement; all brands accepted."

            matches_list.append(RequirementMatchItem(
                name="Brand",
                requested=", ".join(brands) if brands else "Any Brand",
                status="Matched" if brand_matched else "Not matched",
                explanation=brand_explanation,
                verified=True,
            ))

            # --- D. Feature & Specification Verification (25 pts) ---
            feature_score = 0.0
            verified_matches_count = 0
            has_unverified_feature = False
            has_mismatched_feature = False

            if features:
                for feat in features:
                    status, is_verified, expl = self._verify_single_feature(feat, prod)
                    if status == "Matched":
                        verified_matches_count += 1
                        matches_list.append(RequirementMatchItem(
                            name="Feature",
                            requested=feat,
                            status="Matched",
                            explanation=expl,
                            verified=True,
                        ))
                    elif status == "Not verified":
                        has_unverified_feature = True
                        unverified_features.append(feat)
                        matches_list.append(RequirementMatchItem(
                            name="Feature",
                            requested=feat,
                            status="Not verified",
                            explanation=expl,
                            verified=False,
                        ))
                    else:
                        has_mismatched_feature = True
                        mismatch_reasons.append(expl)
                        matches_list.append(RequirementMatchItem(
                            name="Feature",
                            requested=feat,
                            status="Not matched",
                            explanation=expl,
                            verified=True,
                        ))

                ratio = verified_matches_count / max(len(features), 1)
                feature_score = round(ratio * 25.0, 2)
            else:
                feature_score = 25.0

            # --- E. Rating Score (10 pts) ---
            rating_score = 0.0
            if prod_rating > 0:
                rating_ratio = min(max(prod_rating / 5.0, 0.0), 1.0)
                rating_score = round(rating_ratio * 10.0, 2)
            else:
                rating_score = 0.0

            # --- F. Total Normalized Score ---
            raw_total = category_score + feature_score + price_score + brand_score + rating_score
            total_score = round(min(max(raw_total, 0.0), 100.0), 1)
            normalized_score = round(total_score / 100.0, 3)

            breakdown = RecommendationScoreBreakdown(
                category_match_score=category_score,
                feature_match_score=feature_score,
                price_suitability_score=price_score,
                brand_match_score=brand_score,
                rating_score=rating_score,
                total_score=total_score,
                normalized_score=normalized_score,
            )

            # --- G. Mandatory Compliance & Match Tier Determination ---
            # Rule: High recommendation score must never compensate for a mandatory requirement violation.
            is_out_of_stock = prod_stock <= 0 or prod_avail == "Out of Stock"
            if is_out_of_stock:
                mismatch_reasons.append("Product is currently out of stock.")

            if not cat_matched:
                tier = MatchTier.EXCLUDED
                rec_reason = f"Excluded: Product does not match requested category '{category_raw or canonical_category}'."
            elif not budget_matched:
                tier = MatchTier.EXCLUDED
                rec_reason = f"Excluded: {price_explanation}"
            elif not brand_matched:
                tier = MatchTier.EXCLUDED
                rec_reason = f"Excluded: {brand_explanation}"
            elif is_out_of_stock:
                tier = MatchTier.EXCLUDED
                rec_reason = "Excluded: Product is out of stock in catalogue."
            elif has_mismatched_feature:
                tier = MatchTier.EXCLUDED
                rec_reason = f"Excluded: Mandatory feature requirement contradicted in product details ({', '.join(mismatch_reasons)})."
            elif has_unverified_feature:
                tier = MatchTier.NOT_VERIFIED
                rec_reason = (
                    f"Category and budget match ({total_score}%), but required feature(s) "
                    f"({', '.join(unverified_features)}) could not be verified in API product catalogue."
                )
            else:
                tier = MatchTier.FULL_MATCH
                cat_name = canonical_category.title() if canonical_category else category_raw
                rec_reason = (
                    f"Recommended ({total_score}%): Verified match for {cat_name} category, "
                    f"satisfies budget ({price_explanation.split('.')[0]}), and all requested features verified."
                )

            is_fully_matching = (tier == MatchTier.FULL_MATCH)

            analysis = {
                "percentage": int(total_score),
                "normalized_score": normalized_score,
                "match_tier": tier.value,
                "categoryMatched": cat_matched,
                "budgetMatched": budget_matched,
                "brandMatched": brand_matched,
                "matches": [m.model_dump() for m in matches_list],
                "status": "Matches Requirements" if is_fully_matching else tier.value,
                "breakdown": breakdown.model_dump(),
                "recommendation_reason": rec_reason,
                "is_fully_matching": is_fully_matching,
                "unverified_features": unverified_features,
            }

            evaluated_items.append(
                ProductRecommendationItem(
                    product=prod,
                    score=total_score,
                    normalized_score=normalized_score,
                    match_tier=tier,
                    is_fully_matching=is_fully_matching,
                    breakdown=breakdown,
                    recommendation_reason=rec_reason,
                    mismatch_reasons=mismatch_reasons,
                    unverified_features=unverified_features,
                    analysis=analysis,
                )
            )

        # 4. Rank products strictly:
        # Tier priority: FULL_MATCH (0) > NOT_VERIFIED (1) > PARTIAL_MATCH (2) > EXCLUDED (3)
        tier_order = {
            MatchTier.FULL_MATCH: 0,
            MatchTier.NOT_VERIFIED: 1,
            MatchTier.PARTIAL_MATCH: 2,
            MatchTier.EXCLUDED: 3,
        }

        evaluated_items.sort(
            key=lambda item: (tier_order.get(item.match_tier, 99), -item.score)
        )

        full_matches = [i for i in evaluated_items if i.match_tier == MatchTier.FULL_MATCH]

        has_category_restriction = bool(
            canonical_category
            or (category_raw and category_raw.lower() not in ("all", "general", "any", "not specified"))
        )
        if has_category_restriction:
            filtered_results = [
                item for item in evaluated_items
                if item.breakdown.category_match_score > 0
            ]
            final_items = filtered_results[:limit]
        else:
            final_items = evaluated_items[:limit]

        return RecommendationResponse(
            total=len(final_items),
            full_matches_count=len(full_matches),
            recommendations=final_items,
        )


recommendation_service = RecommendationService()
