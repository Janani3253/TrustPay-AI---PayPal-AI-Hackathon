from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AttackCategory(str, Enum):
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    BUDGET_MANIPULATION = "BUDGET_MANIPULATION"
    CART_MANIPULATION = "CART_MANIPULATION"
    PURCHASE_BYPASS = "PURCHASE_BYPASS"
    PAYMENT_MANIPULATION = "PAYMENT_MANIPULATION"
    CHARGE_CONCEALMENT = "CHARGE_CONCEALMENT"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    SECRET_EXTRACTION = "SECRET_EXTRACTION"
    SYSTEM_PROMPT_EXTRACTION = "SYSTEM_PROMPT_EXTRACTION"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    HTML_HIDDEN_INSTRUCTIONS = "HTML_HIDDEN_INSTRUCTIONS"
    ENCODED_INSTRUCTIONS = "ENCODED_INSTRUCTIONS"
    ROLE_MANIPULATION = "ROLE_MANIPULATION"


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"
    UNKNOWN = "UNKNOWN"


class AnalysisStatus(str, Enum):
    COMPLETE = "COMPLETE"
    RULES_ONLY = "RULES_ONLY"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    FAILED = "FAILED"


class AnalysisMode(str, Enum):
    HYBRID = "HYBRID"
    RULE_BASED_ONLY = "RULE_BASED_ONLY"


class DetectionMethod(str, Enum):
    RULE_BASED = "RULE_BASED"
    GEMINI = "GEMINI"


class SecurityFinding(BaseModel):
    """Specific security threat detected in content."""
    rule_id: str = Field(description="Unique rule identifier or detector ID")
    category: AttackCategory = Field(description="Taxonomy classification of the attack")
    severity: SeverityLevel = Field(description="Severity impact of the finding")
    field: str = Field(description="Field name where finding occurred (e.g. title, description)")
    evidence: str = Field(description="Supporting quote or snippet from content")
    description: str = Field(description="Detailed description of the risk")
    detection_method: DetectionMethod = Field(
        default=DetectionMethod.RULE_BASED,
        description="Whether identified via deterministic rules or Gemini AI",
    )


class ProductSecurityScanRequest(BaseModel):
    """Request model for scanning product content for prompt injection."""
    product_id: int = Field(gt=0, description="Product ID to retrieve and scan")
    provider: str = Field(default="DEMO", description="Product catalog provider")
    analysis_mode: AnalysisMode = Field(
        default=AnalysisMode.HYBRID,
        description="HYBRID for Rules + Gemini, or RULE_BASED_ONLY",
    )


class ProductSecurityScanResponse(BaseModel):
    """Complete security assessment of product metadata."""
    product_id: int
    provider: str
    risk_level: RiskLevel
    analysis_status: AnalysisStatus
    detected: bool = Field(
        description="True if risk_level is SUSPICIOUS or MALICIOUS, or suspicious findings present",
    )
    analysis_methods: List[DetectionMethod] = Field(
        default_factory=list,
        description="Detection engines involved in this analysis",
    )
    findings: List[SecurityFinding] = Field(
        default_factory=list,
        description="List of detected security findings",
    )
    summary: str = Field(description="Executive explanation of findings")
    scanned_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of the scan",
    )
    content_hash: str = Field(
        description="Canonical SHA-256 hash of scanned product payload",
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Any operational limitations (e.g. AI unavailable, text truncated)",
    )


# Structured models for Gemini AI output
class GeminiSecurityFinding(BaseModel):
    category: AttackCategory
    severity: SeverityLevel
    field: str
    evidence: str
    description: str


class GeminiSecurityAnalysis(BaseModel):
    risk_level: RiskLevel
    findings: List[GeminiSecurityFinding] = Field(default_factory=list)
    summary: str


class ContentScanRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContentScanAction(str, Enum):
    ALLOW = "ALLOW"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    BLOCK_AND_REVIEW = "BLOCK_AND_REVIEW"


class ContentScanRequest(BaseModel):
    """Payload for POST /security/scan-content."""
    content: str = Field(..., min_length=1, max_length=50000, description="Untrusted text, website content, or product description to scan")
    product_id: Optional[int] = Field(default=None, description="Optional associated product ID")
    source: Optional[str] = Field(default="shopping_website", description="Origin of untrusted content")


class ContentScanResponse(BaseModel):
    """Response matching the exact task specification for POST /security/scan-content."""
    is_suspicious: bool = Field(description="True if malicious or suspicious instructions detected")
    risk_level: ContentScanRiskLevel = Field(description="Risk classification: LOW, MEDIUM, or HIGH")
    detected_patterns: List[str] = Field(default_factory=list, description="List of detected attack patterns")
    action: ContentScanAction = Field(description="Action to take: ALLOW, FLAG_FOR_REVIEW, or BLOCK_AND_REVIEW")
    explanation: str = Field(default="", description="Detailed human-readable explanation")
    findings: List[SecurityFinding] = Field(default_factory=list, description="Granular finding details")
    scanned_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str = Field(default="")

