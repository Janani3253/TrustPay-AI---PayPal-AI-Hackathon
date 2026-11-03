from typing import List, Optional, Tuple

from app.schemas.security import (
    AnalysisMode,
    AnalysisStatus,
    DetectionMethod,
    GeminiSecurityAnalysis,
    RiskLevel,
    SecurityFinding,
    SeverityLevel,
)


class RiskClassifier:
    """
    Enforces risk aggregation invariants across deterministic and AI analysis layers.
    Fundamental Invariant:
    Gemini can identify additional suspicious patterns or upgrade risk,
    but it must NEVER suppress, downgrade, or veto a deterministic security finding.
    """

    @staticmethod
    def aggregate(
        rule_findings: List[SecurityFinding],
        rule_risk: RiskLevel,
        gemini_analysis: Optional[GeminiSecurityAnalysis],
        mode: AnalysisMode,
        ai_error: Optional[str] = None,
    ) -> Tuple[RiskLevel, AnalysisStatus, List[DetectionMethod], List[SecurityFinding], str]:
        """
        Aggregate deterministic and Gemini findings into the final verdict.
        Returns: (final_risk, analysis_status, detection_methods, all_findings, summary)
        """
        all_findings = list(rule_findings)
        methods: List[DetectionMethod] = [DetectionMethod.RULE_BASED]

        # 1. Determine Analysis Status
        if mode == AnalysisMode.RULE_BASED_ONLY:
            status = AnalysisStatus.RULES_ONLY
        elif gemini_analysis is not None:
            status = AnalysisStatus.COMPLETE
            methods.append(DetectionMethod.GEMINI)
        elif ai_error is not None:
            status = AnalysisStatus.AI_UNAVAILABLE
        else:
            status = AnalysisStatus.COMPLETE

        # 2. Convert Gemini findings to SecurityFinding models
        gemini_risk: Optional[RiskLevel] = None
        if gemini_analysis is not None:
            gemini_risk = gemini_analysis.risk_level
            for idx, gf in enumerate(gemini_analysis.findings):
                all_findings.append(
                    SecurityFinding(
                        rule_id=f"GEMINI_AI_{idx+1}",
                        category=gf.category,
                        severity=gf.severity,
                        field=gf.field,
                        evidence=gf.evidence,
                        description=gf.description,
                        detection_method=DetectionMethod.GEMINI,
                    )
                )

        # 3. Enforce the Core Invariant for Final Risk Level
        final_risk = RiskLevel.SAFE

        if rule_risk == RiskLevel.MALICIOUS:
            # Deterministic MALICIOUS is final and uncompromisable
            final_risk = RiskLevel.MALICIOUS
        elif rule_risk == RiskLevel.SUSPICIOUS:
            # Deterministic SUSPICIOUS can be upgraded to MALICIOUS by Gemini, but never downgraded to SAFE
            if gemini_risk == RiskLevel.MALICIOUS:
                final_risk = RiskLevel.MALICIOUS
            else:
                final_risk = RiskLevel.SUSPICIOUS
        else:
            # Deterministic was SAFE
            if gemini_risk == RiskLevel.MALICIOUS:
                final_risk = RiskLevel.MALICIOUS
            elif gemini_risk == RiskLevel.SUSPICIOUS:
                final_risk = RiskLevel.SUSPICIOUS
            else:
                final_risk = RiskLevel.SAFE

        # 4. Synthesize Executive Summary
        summary = RiskClassifier._build_summary(
            final_risk=final_risk,
            rule_risk=rule_risk,
            gemini_risk=gemini_risk,
            status=status,
            finding_count=len(all_findings),
            gemini_summary=gemini_analysis.summary if gemini_analysis else None,
        )

        return final_risk, status, methods, all_findings, summary

    @staticmethod
    def _build_summary(
        final_risk: RiskLevel,
        rule_risk: RiskLevel,
        gemini_risk: Optional[RiskLevel],
        status: AnalysisStatus,
        finding_count: int,
        gemini_summary: Optional[str] = None,
    ) -> str:
        if final_risk == RiskLevel.MALICIOUS:
            reasons = []
            if rule_risk == RiskLevel.MALICIOUS:
                reasons.append("deterministic pattern detection")
            if gemini_risk == RiskLevel.MALICIOUS:
                reasons.append("AI semantic security analysis")
            src = " and ".join(reasons) or "security scan"
            base = f"MALICIOUS content detected via {src} ({finding_count} total findings)."
            if gemini_summary:
                base += f" AI Assessment: {gemini_summary}"
            return base

        if final_risk == RiskLevel.SUSPICIOUS:
            base = f"SUSPICIOUS content patterns identified ({finding_count} findings)."
            if gemini_summary:
                base += f" AI Assessment: {gemini_summary}"
            return base

        # SAFE
        if status == AnalysisStatus.AI_UNAVAILABLE:
            return "Content assessed as SAFE via deterministic rules (AI analysis was unavailable)."
        if status == AnalysisStatus.RULES_ONLY:
            return "Content assessed as SAFE via deterministic rules (Rule-based mode)."
        return "Content passed all prompt injection security evaluations without threats detected."


risk_classifier = RiskClassifier()

