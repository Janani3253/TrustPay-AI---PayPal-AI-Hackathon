import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.security import (
    AnalysisMode,
    AnalysisStatus,
    AttackCategory,
    ContentScanAction,
    ContentScanResponse,
    ContentScanRiskLevel,
    DetectionMethod,
    GeminiSecurityAnalysis,
    ProductSecurityScanResponse,
    RiskLevel,
    SecurityFinding,
    SeverityLevel,
)
from app.security.injection_detector import InjectionDetector, injection_detector
from app.security.risk_classifier import RiskClassifier, risk_classifier
from app.services.gemini_service import GeminiService, gemini_service
from app.services.product_service import product_service

logger = logging.getLogger(__name__)


class PromptInjectionService:
    """
    Orchestrates prompt injection defense and untrusted content analysis.
    Combines high-speed deterministic pattern detection with Gemini AI semantic scrutiny.
    Enforces risk aggregation invariants and bounded scan caching.
    """

    def __init__(
        self,
        detector: Optional[InjectionDetector] = None,
        classifier: Optional[RiskClassifier] = None,
        gemini: Optional[GeminiService] = None,
        cache_ttl: Optional[int] = None,
        max_cache_entries: Optional[int] = None,
    ):
        self.detector = detector or injection_detector
        self.classifier = classifier or risk_classifier
        self.gemini = gemini or gemini_service
        self.cache_ttl = cache_ttl or settings.SECURITY_SCAN_CACHE_TTL_SECONDS
        self.max_cache_entries = max_cache_entries or settings.SECURITY_SCAN_CACHE_MAX_ENTRIES
        self._cache: OrderedDict[str, Tuple[float, ProductSecurityScanResponse]] = OrderedDict()

    def clear_cache(self) -> None:
        """Clear cached security scans."""
        self._cache.clear()

    @staticmethod
    def compute_content_hash(product_data: Dict[str, Any]) -> str:
        """
        Generate a canonical SHA-256 hash for product content to detect changes.
        """
        key_fields = {
            "id": product_data.get("id"),
            "provider": product_data.get("provider", "DEMO"),
            "title": product_data.get("title", ""),
            "description": product_data.get("description", ""),
            "category": product_data.get("category", ""),
            "brand": product_data.get("brand", ""),
            "price": product_data.get("price"),
        }
        serialized = json.dumps(key_fields, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[ProductSecurityScanResponse]:
        """Retrieve unexpired scan result from cache."""
        if cache_key in self._cache:
            ts, response = self._cache[cache_key]
            if time.time() - ts < self.cache_ttl:
                self._cache.move_to_end(cache_key)
                return response
            del self._cache[cache_key]
        return None

    def _put_in_cache(self, cache_key: str, response: ProductSecurityScanResponse) -> None:
        """Store scan result in LRU cache with eviction."""
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
        self._cache[cache_key] = (time.time(), response)
        if len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)

    @staticmethod
    def _build_content_summary_for_ai(product_data: Dict[str, Any]) -> str:
        """Format product metadata into structured text for AI inspection."""
        lines = [
            f"PRODUCT ID: {product_data.get('id')}",
            f"TITLE: {product_data.get('title', '')}",
            f"BRAND: {product_data.get('brand', '')}",
            f"CATEGORY: {product_data.get('category', '')}",
            f"PRICE: {product_data.get('price', '')}",
            f"DESCRIPTION: {product_data.get('description', '')}",
        ]
        if "tags" in product_data and product_data["tags"]:
            lines.append(f"TAGS: {', '.join(str(t) for t in product_data['tags'])}")
        return "\n".join(lines)

    async def analyze_product(
        self,
        product: Dict[str, Any],
        analysis_mode: AnalysisMode = AnalysisMode.HYBRID,
    ) -> ProductSecurityScanResponse:
        """
        Analyze untrusted product dictionary with caching, rules, and optional AI layer.
        """
        prod_id = int(product.get("id", 0))
        provider = str(product.get("provider", "DEMO"))
        content_hash = self.compute_content_hash(product)

        cache_key = f"{provider}:{prod_id}:{content_hash}:{analysis_mode.value}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        # 1. Deterministic Rule-Based Scanning
        rule_findings, rule_risk, limitations = self.detector.scan_product_dict(product)

        # 2. AI Semantic Inspection (if requested and configured)
        gemini_analysis: Optional[GeminiSecurityAnalysis] = None
        ai_error: Optional[str] = None

        if analysis_mode == AnalysisMode.HYBRID:
            if settings.is_gemini_configured:
                try:
                    summary_text = self._build_content_summary_for_ai(product)
                    gemini_analysis = await self.gemini.analyze_product_security(summary_text)
                except Exception as exc:
                    logger.warning("Gemini security analysis failed, falling back to rules: %s", exc)
                    ai_error = str(exc)
                    limitations.append(f"AI security analysis unavailable: {exc}")
            else:
                ai_error = "Gemini AI not configured"
                limitations.append("Google Gemini is not configured; scan completed using deterministic rules.")

        # 3. Enforce Invariant Risk Aggregation
        (
            final_risk,
            analysis_status,
            analysis_methods,
            all_findings,
            summary,
        ) = self.classifier.aggregate(
            rule_findings=rule_findings,
            rule_risk=rule_risk,
            gemini_analysis=gemini_analysis,
            mode=analysis_mode,
            ai_error=ai_error,
        )

        detected = (
            final_risk in (RiskLevel.MALICIOUS, RiskLevel.SUSPICIOUS)
            or any(f.severity in (SeverityLevel.HIGH, SeverityLevel.CRITICAL) for f in all_findings)
        )

        response = ProductSecurityScanResponse(
            product_id=prod_id,
            provider=provider,
            risk_level=final_risk,
            analysis_status=analysis_status,
            detected=detected,
            analysis_methods=analysis_methods,
            findings=all_findings,
            summary=summary,
            scanned_at=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
            limitations=limitations,
        )

        # Store in cache
        self._put_in_cache(cache_key, response)
        return response

    async def analyze_product_by_id(
        self,
        product_id: int,
        provider: str = "DEMO",
        analysis_mode: AnalysisMode = AnalysisMode.HYBRID,
    ) -> ProductSecurityScanResponse:
        """
        Fetch authentic product from provider and perform security scan.
        Guarantees client cannot spoof product content.
        """
        product = await product_service.get_product_details(product_id=product_id, platform=provider)
        # Normalize product to dictionary
        if hasattr(product, "model_dump"):
            product_dict = product.model_dump()
        elif isinstance(product, dict):
            product_dict = product
        else:
            product_dict = dict(product)
        product_dict["provider"] = provider

        return await self.analyze_product(product_dict, analysis_mode=analysis_mode)

    async def scan_content(
        self,
        content: str,
        product_id: Optional[int] = None,
        source: str = "shopping_website",
    ) -> ContentScanResponse:
        """
        Scan arbitrary untrusted content, website text, or product description for prompt injections.
        Isolates untrusted content from execution flow.
        Classifies risk into LOW, MEDIUM, or HIGH and prescribes enforcement action.
        """
        clean_text = content.strip()
        content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

        # 1. Deterministic Rule-Based Analysis
        mock_product = {
            "id": product_id or 0,
            "provider": source,
            "title": clean_text[:120],
            "description": clean_text,
        }
        rule_findings, rule_risk, limitations = self.detector.scan_product_dict(mock_product)

        # 2. AI Semantic Inspection if Gemini is configured
        gemini_findings: List[SecurityFinding] = []
        if settings.is_gemini_configured:
            try:
                gemini_res = await self.gemini.analyze_product_security(clean_text)
                if gemini_res and gemini_res.findings:
                    for gf in gemini_res.findings:
                        gemini_findings.append(
                            SecurityFinding(
                                rule_id="GEMINI_AI_DETECT",
                                category=gf.category,
                                severity=gf.severity,
                                field="content",
                                evidence=gf.evidence,
                                description=gf.description,
                                detection_method=DetectionMethod.GEMINI,
                            )
                        )
            except Exception as exc:
                logger.warning("Gemini AI scan failed for untrusted content: %s", exc)

        all_findings = rule_findings + gemini_findings

        # 3. Categorize detected patterns into task-specified pattern names
        pattern_names = []
        has_instruction_override = False
        has_budget_manipulation = False
        has_payment_manipulation = False
        has_cart_manipulation = False
        has_secret_extraction = False

        for f in all_findings:
            if f.category == AttackCategory.INSTRUCTION_OVERRIDE:
                has_instruction_override = True
            elif f.category == AttackCategory.BUDGET_MANIPULATION:
                has_budget_manipulation = True
            elif f.category in (AttackCategory.PURCHASE_BYPASS, AttackCategory.PAYMENT_MANIPULATION):
                has_payment_manipulation = True
            elif f.category == AttackCategory.CART_MANIPULATION:
                has_cart_manipulation = True
            elif f.category in (AttackCategory.SECRET_EXTRACTION, AttackCategory.DATA_EXFILTRATION):
                has_secret_extraction = True

        if has_instruction_override or re.search(r"\b(?:ignore|override|disregard|bypass|forget)\b", clean_text, re.I):
            has_instruction_override = True
            pattern_names.append("Instruction override")
        if has_budget_manipulation:
            pattern_names.append("Budget manipulation")
        if has_cart_manipulation:
            pattern_names.append("Cart manipulation")
        if has_payment_manipulation:
            pattern_names.append("Unauthorized payment instruction")
        if has_secret_extraction:
            pattern_names.append("Confidential information extraction")

        # 4. Determine risk level and enforcement action
        is_suspicious = len(all_findings) > 0
        has_critical_or_high = any(
            f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH) for f in all_findings
        )
        has_medium = any(f.severity == SeverityLevel.MEDIUM for f in all_findings)

        if has_critical_or_high or has_instruction_override or has_budget_manipulation or has_payment_manipulation:
            risk_level = ContentScanRiskLevel.HIGH
            action = ContentScanAction.BLOCK_AND_REVIEW
            explanation = (
                f"High-risk adversarial directives detected ({', '.join(pattern_names)}). "
                "Untrusted content isolated. Directives will NOT be executed."
            )
        elif has_medium:
            risk_level = ContentScanRiskLevel.MEDIUM
            action = ContentScanAction.FLAG_FOR_REVIEW
            explanation = (
                f"Potentially suspicious patterns identified ({', '.join(pattern_names)}). "
                "Isolated from automated execution; customer review advised."
            )
        else:
            risk_level = ContentScanRiskLevel.LOW
            action = ContentScanAction.ALLOW
            is_suspicious = False
            explanation = "No adversarial prompt injection patterns detected in untrusted content."

        return ContentScanResponse(
            is_suspicious=is_suspicious,
            risk_level=risk_level,
            detected_patterns=pattern_names,
            action=action,
            explanation=explanation,
            findings=all_findings,
            scanned_at=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
        )


prompt_injection_service = PromptInjectionService()

