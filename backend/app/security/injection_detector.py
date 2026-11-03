import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.security import (
    AttackCategory,
    DetectionMethod,
    RiskLevel,
    SecurityFinding,
    SeverityLevel,
)
from app.security.content_normalizer import (
    ContentNormalizer,
    NormalizedField,
    content_normalizer,
)
from app.security.pattern_registry import PatternRegistry, SecurityRule, pattern_registry

logger = logging.getLogger(__name__)

# Keywords that in hidden elements or comments constitute an active directive
HIDDEN_DIRECTIVE_KEYWORDS = {
    "ignore",
    "override",
    "bypass",
    "system",
    "prompt",
    "budget",
    "cart",
    "paypal",
    "wallet",
    "payment",
    "admin",
    "disregard",
    "execute",
    "approve",
}


class InjectionDetector:
    """
    Deterministic rule-based security engine that analyzes untrusted
    content for prompt injection attacks and covert instruction payloads.
    """

    def __init__(
        self,
        registry: Optional[PatternRegistry] = None,
        normalizer: Optional[ContentNormalizer] = None,
    ):
        self.registry = registry or pattern_registry
        self.normalizer = normalizer or content_normalizer

    def _matches_exclusion(self, rule: SecurityRule, snippet: str, full_text: str) -> bool:
        """Check if any exclusion patterns for this rule are satisfied."""
        if not rule.exclusion_patterns:
            return False
        for ex in rule.exclusion_patterns:
            if ex.search(snippet) or ex.search(full_text):
                return True
        return False

    def scan_normalized_field(
        self,
        norm: NormalizedField,
    ) -> List[SecurityFinding]:
        """
        Scan a single pre-normalized field for all deterministic threat patterns.
        """
        findings: List[SecurityFinding] = []
        full_text = norm.normalized_text

        # 1. Evaluate Rule-based patterns on primary normalized text
        for rule in self.registry.rules:
            for match in rule.pattern.finditer(full_text):
                matched_snippet = match.group(0)

                # Check if false positive exclusion matches
                if self._matches_exclusion(rule, matched_snippet, full_text):
                    continue

                # Extract surrounding context for evidence (up to 80 chars)
                start = max(0, match.start() - 20)
                end = min(len(full_text), match.end() + 20)
                evidence = full_text[start:end].strip()

                findings.append(
                    SecurityFinding(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        severity=rule.severity,
                        field=norm.field_name,
                        evidence=evidence,
                        description=rule.description,
                        detection_method=DetectionMethod.RULE_BASED,
                    )
                )

        # 2. Check HTML Comments for Hidden Directives
        for idx, comment in enumerate(norm.html_comments):
            comment_lower = comment.lower()
            found_words = [kw for kw in HIDDEN_DIRECTIVE_KEYWORDS if re.search(rf"\b{kw}\b", comment_lower)]
            if found_words:
                findings.append(
                    SecurityFinding(
                        rule_id=f"RULE_HTML_COMMENT_{idx+1}",
                        category=AttackCategory.HTML_HIDDEN_INSTRUCTIONS,
                        severity=SeverityLevel.HIGH,
                        field=norm.field_name,
                        evidence=comment[:100],
                        description=f"Hidden HTML comment contains directive keywords: {', '.join(found_words)}",
                        detection_method=DetectionMethod.RULE_BASED,
                    )
                )

        # 3. Check Visually Hidden HTML Elements
        for idx, hidden_elem in enumerate(norm.hidden_elements):
            elem_lower = hidden_elem.lower()
            found_words = [kw for kw in HIDDEN_DIRECTIVE_KEYWORDS if re.search(rf"\b{kw}\b", elem_lower)]
            if found_words:
                findings.append(
                    SecurityFinding(
                        rule_id=f"RULE_HTML_HIDDEN_ELEM_{idx+1}",
                        category=AttackCategory.HTML_HIDDEN_INSTRUCTIONS,
                        severity=SeverityLevel.HIGH,
                        field=norm.field_name,
                        evidence=hidden_elem[:100],
                        description=f"Visually hidden HTML tag contains covert instructions: {', '.join(found_words)}",
                        detection_method=DetectionMethod.RULE_BASED,
                    )
                )

        # 4. Check Decoded Obfuscated Payloads (Base64 / URL)
        for idx, payload in enumerate(norm.decoded_payloads):
            if payload.is_suspicious:
                findings.append(
                    SecurityFinding(
                        rule_id=f"RULE_ENCODED_{payload.encoding_type}_{idx+1}",
                        category=AttackCategory.ENCODED_INSTRUCTIONS,
                        severity=SeverityLevel.HIGH,
                        field=norm.field_name,
                        evidence=f"{payload.encoding_type}: {payload.decoded[:100]}",
                        description=f"Obfuscated {payload.encoding_type} payload contains keywords: {', '.join(payload.suspicious_keywords)}",
                        detection_method=DetectionMethod.RULE_BASED,
                    )
                )

        # 5. Check Zero-width evasion attempt
        if norm.zero_width_chars_removed > 3 and findings:
            findings.append(
                SecurityFinding(
                    rule_id="RULE_OBFUSCATION_ZW",
                    category=AttackCategory.ENCODED_INSTRUCTIONS,
                    severity=SeverityLevel.MEDIUM,
                    field=norm.field_name,
                    evidence=f"{norm.zero_width_chars_removed} zero-width characters removed",
                    description="Zero-width unicode characters used to fragment text and evade security filters.",
                    detection_method=DetectionMethod.RULE_BASED,
                )
            )

        return findings

    def scan_product_dict(
        self,
        product_data: Dict[str, Any],
    ) -> Tuple[List[SecurityFinding], RiskLevel, List[str]]:
        """
        Normalize and scan all relevant fields of a product data dictionary.
        Returns: (findings, deterministic_risk_level, limitations)
        """
        all_findings: List[SecurityFinding] = []
        limitations: List[str] = []

        # Fields to prioritize
        scan_keys = ["title", "description", "category", "brand"]
        # Add additional string/list fields up to limit
        for k in product_data:
            if k not in scan_keys and len(scan_keys) < settings.SECURITY_SCAN_MAX_FIELDS:
                val = product_data[k]
                if isinstance(val, (str, list)):
                    scan_keys.append(k)

        for key in scan_keys:
            val = product_data.get(key)
            if val is None:
                continue
            norm = self.normalizer.process_field(key, str(val))
            if norm.was_truncated:
                limitations.append(f"Field '{key}' was truncated to {self.normalizer.max_chars} chars.")

            field_findings = self.scan_normalized_field(norm)
            all_findings.extend(field_findings)

        # Deduplicate findings by (rule_id, field, evidence)
        seen = set()
        deduped_findings: List[SecurityFinding] = []
        for f in all_findings:
            key_sig = (f.rule_id, f.field, f.evidence)
            if key_sig not in seen:
                seen.add(key_sig)
                deduped_findings.append(f)

        # Enforce max findings limit
        if len(deduped_findings) > settings.SECURITY_SCAN_MAX_FINDINGS:
            limitations.append(
                f"Findings truncated to maximum allowed limit ({settings.SECURITY_SCAN_MAX_FINDINGS})."
            )
            deduped_findings = deduped_findings[: settings.SECURITY_SCAN_MAX_FINDINGS]

        # Calculate deterministic risk level
        risk_level = self.calculate_risk_level(deduped_findings)

        return deduped_findings, risk_level, limitations

    @staticmethod
    def calculate_risk_level(findings: List[SecurityFinding]) -> RiskLevel:
        """
        Map detected findings to deterministic RiskLevel.
        CRITICAL / HIGH -> MALICIOUS
        MEDIUM -> SUSPICIOUS
        LOW / INFO -> SUSPICIOUS if any, else SAFE
        """
        if not findings:
            return RiskLevel.SAFE

        severities = {f.severity for f in findings}
        if SeverityLevel.CRITICAL in severities or SeverityLevel.HIGH in severities:
            return RiskLevel.MALICIOUS
        if SeverityLevel.MEDIUM in severities or SeverityLevel.LOW in severities:
            return RiskLevel.SUSPICIOUS

        return RiskLevel.SAFE


injection_detector = InjectionDetector()

