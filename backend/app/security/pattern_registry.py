import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.schemas.security import AttackCategory, SeverityLevel


@dataclass
class SecurityRule:
    rule_id: str
    category: AttackCategory
    severity: SeverityLevel
    pattern: re.Pattern
    description: str
    exclusion_patterns: List[re.Pattern] = field(default_factory=list)


def compile_pattern(pattern_str: str) -> re.Pattern:
    return re.compile(pattern_str, re.IGNORECASE)


# Precompiled rule set for prompt injection and untrusted content analysis
SECURITY_RULES: List[SecurityRule] = [
    # 1. INSTRUCTION_OVERRIDE (CRITICAL)
    SecurityRule(
        rule_id="RULE_INST_001",
        category=AttackCategory.INSTRUCTION_OVERRIDE,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:ignore|disregard|forget|override|bypass|cancel)\s+(?:all\s+)?(?:(?:previous|prior|above|system|initial|preceding|customer(?:'s)?)\s+)?(?:instructions|prompts|rules|directives|constraints|commands|requirements)\b"
        ),
        description="Attempt to override prior system instructions or customer requirements.",
        exclusion_patterns=[
            compile_pattern(r"(?:noise|distraction|distractions|background|ambient)\s+(?:cancellation|chatter)?"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_INST_002",
        category=AttackCategory.INSTRUCTION_OVERRIDE,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:system\s+(?:prompt\s+)?override|new\s+system\s+instruction|from\s+now\s+on\s+you\s+(?:must|will)|override\s+customer\s+requirements)\b"
        ),
        description="Direct instruction injection to redefine system operational mode.",
    ),
    SecurityRule(
        rule_id="RULE_INST_003",
        category=AttackCategory.INSTRUCTION_OVERRIDE,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:reset\s+all\s+rules|clear\s+your\s+memory|start\s+fresh\s+and\s+ignore)\b"
        ),
        description="Instruction to reset model context and discard constraints.",
    ),

    # 2. BUDGET_MANIPULATION (CRITICAL / HIGH)
    SecurityRule(
        rule_id="RULE_BUDGET_001",
        category=AttackCategory.BUDGET_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:ignore|override|disregard|bypass|remove|delete|reset)\s+(?:the\s+)?(?:customer['’]s?\s+)?(?:budget|maximum\s+budget|price\s+limit|spending\s+limit)\b"
        ),
        description="Attempt to eliminate or bypass customer budget limits.",
        exclusion_patterns=[
            compile_pattern(r"\bbudget[- ]friendly\b"),
            compile_pattern(r"\bwithin\s+budget\b"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_BUDGET_002",
        category=AttackCategory.BUDGET_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:set\s+(?:the\s+)?budget\s+to\s+(?:unlimited|infinite|\$?\s*999999|\$?\s*0))\b"
        ),
        description="Directive to assign arbitrary or infinite customer budget.",
    ),
    SecurityRule(
        rule_id="RULE_BUDGET_003",
        category=AttackCategory.BUDGET_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:price\s+is\s+actually\s+(?:zero|free|\$0|0\.00)|no\s+budget\s+restriction)\b"
        ),
        description="Attempt to falsify product price to bypass budget checks.",
    ),

    # 3. CART_MANIPULATION (HIGH)
    SecurityRule(
        rule_id="RULE_CART_001",
        category=AttackCategory.CART_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:automatically|silently|forcefully|force)\s+(?:add|inject|insert)\s+(?:this|extra|additional|another|hidden)\s+(?:item|product|to\s+cart)\b"
        ),
        description="Directive to forcibly insert unapproved items into customer shopping cart.",
        exclusion_patterns=[
            compile_pattern(r"\badds\s+(?:convenience|comfort|style|bass|clarity|efficiency|value|flair|elegance)\b"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_CART_002",
        category=AttackCategory.CART_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:add\s+(?:this|item)\s+to\s+cart\s+without\s+(?:asking|customer\s+permission|confirmation|approval|consent))\b"
        ),
        description="Directive to add items without customer consent.",
    ),
    SecurityRule(
        rule_id="RULE_CART_003",
        category=AttackCategory.CART_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:force\s+add\s+to\s+cart|inject\s+into\s+(?:the\s+)?cart)\b"
        ),
        description="Cart injection directive targeting shopping agent state.",
    ),
    SecurityRule(
        rule_id="RULE_CART_004",
        category=AttackCategory.CART_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:add|insert|inject)\s+(?:an?\s+)?(?:(?:expensive|premium|extra|hidden|unauthorized|additional)\s+)+(?:product|item|products|items)\b"
        ),
        description="Directive to insert unauthorized or expensive premium items into cart.",
    ),
    SecurityRule(
        rule_id="RULE_CART_005",
        category=AttackCategory.CART_MANIPULATION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:change|substitute|replace|swap)\s+(?:the\s+)?(?:selected|chosen|target)\s+(?:product|item)\b"
        ),
        description="Directive to replace or substitute the customer's selected product.",
    ),

    # 4. PURCHASE_BYPASS (CRITICAL)
    SecurityRule(
        rule_id="RULE_BYPASS_001",
        category=AttackCategory.PURCHASE_BYPASS,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:bypass|skip|ignore|circumvent|disable)\s+(?:intentlock|purchase\s+verification|order\s+verification|confirmation\s+check|approval\s+step)\b"
        ),
        description="Attempt to circumvent IntentLock verification or purchase confirmation.",
    ),
    SecurityRule(
        rule_id="RULE_BYPASS_002",
        category=AttackCategory.PURCHASE_BYPASS,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:auto-?approve\s+(?:this\s+)?(?:purchase|transaction|order|payment)|execute\s+without\s+(?:user\s+)?confirmation|proceed\s+with\s+payment\s+automatically|perform\s+payment\s+without\s+(?:customer\s+)?approval|pay\s+automatically)\b"
        ),
        description="Directive to auto-approve purchase or perform payment without customer approval.",
    ),
    SecurityRule(
        rule_id="RULE_BYPASS_003",
        category=AttackCategory.PURCHASE_BYPASS,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:mark\s+as\s+verified\s+immediately|assume\s+customer\s+already\s+approved)\b"
        ),
        description="Attempt to fabricate pre-verified order state.",
    ),

    # 5. PAYMENT_MANIPULATION (CRITICAL)
    SecurityRule(
        rule_id="RULE_PAY_001",
        category=AttackCategory.PAYMENT_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:redirect|transfer|route|send)\s+(?:payment|funds|money|paypal)\s+to\s+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
        ),
        description="Payment redirection to an unauthorized recipient email or wallet.",
    ),
    SecurityRule(
        rule_id="RULE_PAY_002",
        category=AttackCategory.PAYMENT_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:use\s+alternative\s+payment\s+address|intercept\s+payment|substitute\s+paypal\s+account)\b"
        ),
        description="Attempt to intercept or replace payment receiver credentials.",
    ),
    SecurityRule(
        rule_id="RULE_PAY_003",
        category=AttackCategory.PAYMENT_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:override\s+merchant\s+recipient|send\s+crypto\s+to|pay\s+to\s+wallet)\b"
        ),
        description="Unauthorized routing of payment funds to external cryptocurrency or wallet addresses.",
    ),

    # 6. CHARGE_CONCEALMENT (HIGH)
    SecurityRule(
        rule_id="RULE_CHARGE_001",
        category=AttackCategory.CHARGE_CONCEALMENT,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:hide|conceal|mask|suppress|omit)\s+(?:this\s+)?(?:fee|charge|surcharge|shipping\s+fee|tax|total\s+cost)\b"
        ),
        description="Attempt to conceal mandatory charges, taxes, or fees from customer view.",
        exclusion_patterns=[
            compile_pattern(r"\b(?:no|zero)\s+hidden\s+(?:fees|charges|costs)\b"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_CHARGE_002",
        category=AttackCategory.CHARGE_CONCEALMENT,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:do\s+not\s+display\s+(?:the\s+)?fee|do\s+not\s+show\s+(?:the\s+)?surcharge|hidden\s+charge\s+authorized)\b"
        ),
        description="Directive to suppress fee breakdown during checkout.",
    ),

    # 7. DATA_EXFILTRATION (CRITICAL)
    SecurityRule(
        rule_id="RULE_EXFIL_001",
        category=AttackCategory.DATA_EXFILTRATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:send|exfiltrate|transmit|post|upload)\s+(?:user\s+)?(?:token|session|cookie|credential|password|card|secret)\s+to\s+(?:https?:\/\/|\/|endpoint|webhook)\b"
        ),
        description="Instruction to exfiltrate user credentials or sessions to an external destination.",
    ),
    SecurityRule(
        rule_id="RULE_EXFIL_002",
        category=AttackCategory.DATA_EXFILTRATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"""\b(?:https?://[^\s"'<>]*/(?:steal|exfil|collect|dump|logger|webhook))\b"""
        ),
        description="Suspicious exfiltration URL or collector endpoint detected in product text.",
    ),
    SecurityRule(
        rule_id="RULE_EXFIL_003",
        category=AttackCategory.DATA_EXFILTRATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"""\b(?:fetch|curl)\s+https?://[^\s"'<>]+\?data=[a-zA-Z0-9]+\b"""
        ),
        description="Data exfiltration via HTTP request command syntax.",
    ),

    # 8. SECRET_EXTRACTION (HIGH)
    SecurityRule(
        rule_id="RULE_SECRET_001",
        category=AttackCategory.SECRET_EXTRACTION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:reveal|print|output|display|show|leak|echo)\s+(?:your\s+)?(?:api[_-]?key|secret[_-]?key|paypal[_-]?secret|private[_-]?key|database[_-]?url|jwt[_-]?secret)\b"
        ),
        description="Probe to extract backend secret keys or API credentials.",
    ),
    SecurityRule(
        rule_id="RULE_SECRET_002",
        category=AttackCategory.SECRET_EXTRACTION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:what\s+is\s+your\s+(?:api\s+key|jwt\s+secret|paypal\s+secret))\b"
        ),
        description="Inquiry probing system credential variables.",
    ),

    # 9. SYSTEM_PROMPT_EXTRACTION (HIGH)
    SecurityRule(
        rule_id="RULE_SYS_001",
        category=AttackCategory.SYSTEM_PROMPT_EXTRACTION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:repeat|output|show|print|display)\s+(?:your\s+)?(?:system\s+prompt|developer\s+instructions|initial\s+prompt|system\s+instructions)\b"
        ),
        description="Attempt to extract system prompts or developer instructions.",
    ),
    SecurityRule(
        rule_id="RULE_SYS_002",
        category=AttackCategory.SYSTEM_PROMPT_EXTRACTION,
        severity=SeverityLevel.HIGH,
        pattern=compile_pattern(
            r"\b(?:what\s+(?:is|was)\s+your\s+(?:original\s+)?system\s+prompt|dump\s+system\s+prompt)\b"
        ),
        description="Direct inquiry requesting full dump of agent system prompt.",
    ),

    # 10. TOOL_EXECUTION (CRITICAL)
    SecurityRule(
        rule_id="RULE_TOOL_001",
        category=AttackCategory.TOOL_EXECUTION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:call\s+tool|execute\s+tool|invoke\s+tool|run\s+tool)\s*:\s*[a-zA-Z0-9_]+\b"
        ),
        description="Malicious tool execution or agent RPC command.",
        exclusion_patterns=[
            compile_pattern(r"\btool[- ]free\s+assembly\b"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_TOOL_002",
        category=AttackCategory.TOOL_EXECUTION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:tool_call|function_call)\s*:\s*\{?[a-zA-Z0-9_]+\b"
        ),
        description="Fabricated function call or tool invocation payload.",
    ),
    SecurityRule(
        rule_id="RULE_TOOL_003",
        category=AttackCategory.TOOL_EXECUTION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:execute_payment|capture_payment|transfer_funds|paypal_execute)\s*\("
        ),
        description="Direct programmatic attempt to execute backend financial operations.",
    ),

    # 11. ROLE_MANIPULATION (CRITICAL)
    SecurityRule(
        rule_id="RULE_ROLE_001",
        category=AttackCategory.ROLE_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:you\s+are\s+now\s+(?:in\s+)?(?:developer\s+mode|dan\s+mode|unrestricted|god\s+mode)|act\s+as\s+dan)\b"
        ),
        description="Attempt to induce jailbreak or unrestricted persona.",
        exclusion_patterns=[
            compile_pattern(r"\bdeveloper\s+edition\b"),
        ],
    ),
    SecurityRule(
        rule_id="RULE_ROLE_002",
        category=AttackCategory.ROLE_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:jailbreak\s+active|bypass\s+all\s+safety\s+filters|ignore\s+your\s+ethical\s+guidelines)\b"
        ),
        description="Adversarial prompt designed to disable safety guards.",
    ),
    SecurityRule(
        rule_id="RULE_ROLE_003",
        category=AttackCategory.ROLE_MANIPULATION,
        severity=SeverityLevel.CRITICAL,
        pattern=compile_pattern(
            r"\b(?:act\s+as\s+(?:a\s+)?payment\s+administrator\s+with\s+full\s+privileges)\b"
        ),
        description="Privilege escalation via administrative persona injection.",
    ),
]


class PatternRegistry:
    """Registry managing precompiled rules with false-positive resilience."""

    def __init__(self, rules: Optional[List[SecurityRule]] = None):
        self.rules: List[SecurityRule] = rules or SECURITY_RULES

    def get_rules_for_category(self, category: AttackCategory) -> List[SecurityRule]:
        return [r for r in self.rules if r.category == category]


pattern_registry = PatternRegistry()
