import base64
import html
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.core.config import settings

# Characters commonly used for visual evasion or invisible payload smuggling
ZERO_WIDTH_CHARS = {
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\ufeff",  # zero-width no-break space / BOM
    "\u2060",  # word joiner
    "\u00ad",  # soft hyphen
    "\u200e",  # left-to-right mark
    "\u200f",  # right-to-left mark
    "\u202a",  # LRE
    "\u202b",  # RLE
    "\u202c",  # PDF
    "\u202d",  # LRO
    "\u202e",  # RLO
}

ZERO_WIDTH_REGEX = re.compile("[" + "".join(ZERO_WIDTH_CHARS) + "]")

# Regex to detect HTML comments: <!-- comment -->
HTML_COMMENT_REGEX = re.compile(r"<!--(.*?)-->", re.DOTALL)

# Regex to detect hidden HTML elements
HTML_HIDDEN_ELEMENT_REGEX = re.compile(
    r"""<([a-zA-Z0-9]+)[^>]*?(?:style\s*=\s*['"][^'"]*?(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0|font-size\s*:\s*0)[^'"]*?['"]|aria-hidden\s*=\s*['"]true['"]|\bhidden\b)[^>]*?>(.*?)</\1>""",
    re.IGNORECASE | re.DOTALL,
)

# Base64 candidate regex: blocks of at least 16 valid characters aligned to 4 bytes
BASE64_REGEX = re.compile(
    r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{4}){3,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![A-Za-z0-9+/=])"
)

# Keywords indicating active prompt injection or policy bypass in decoded content
SUSPICIOUS_DECODED_KEYWORDS = {
    "ignore",
    "override",
    "bypass",
    "system",
    "prompt",
    "budget",
    "cart",
    "paypal",
    "wallet",
    "admin",
    "payment",
    "token",
    "transfer",
    "disregard",
    "exfiltrate",
    "secret",
}


@dataclass
class DecodedPayload:
    encoding_type: str
    original: str
    decoded: str
    is_suspicious: bool
    suspicious_keywords: List[str] = field(default_factory=list)


@dataclass
class NormalizedField:
    field_name: str
    raw_text: str
    normalized_text: str
    zero_width_chars_removed: int
    html_comments: List[str] = field(default_factory=list)
    hidden_elements: List[str] = field(default_factory=list)
    decoded_payloads: List[DecodedPayload] = field(default_factory=list)
    was_truncated: bool = False


class ContentNormalizer:
    """
    Sanitizes, normalizes, and extracts hidden or obfuscated text
    from untrusted external product metadata.
    """

    def __init__(
        self,
        max_chars: Optional[int] = None,
        max_decode_depth: int = 2,
        max_decoded_len: int = 1024,
    ):
        self.max_chars = max_chars or settings.SECURITY_SCAN_MAX_CONTENT_CHARS
        self.max_decode_depth = max_decode_depth
        self.max_decoded_len = max_decoded_len

    def normalize_text(self, text: str) -> str:
        """
        Apply Unicode NFKC normalization and strip zero-width characters.
        """
        if not text:
            return ""
        # 1. NFKC normalization
        nfkc = unicodedata.normalize("NFKC", text)
        # 2. Strip zero-width characters
        return ZERO_WIDTH_REGEX.sub("", nfkc)

    def extract_html_comments(self, text: str) -> List[str]:
        """Extract all HTML comment contents."""
        if not text:
            return []
        matches = HTML_COMMENT_REGEX.findall(text)
        return [self.normalize_text(m).strip() for m in matches if m.strip()]

    def extract_hidden_elements(self, text: str) -> List[str]:
        """Extract contents of HTML tags that are visually hidden."""
        if not text:
            return []
        matches = HTML_HIDDEN_ELEMENT_REGEX.findall(text)
        # matches is a list of tuples: (tag_name, inner_content)
        return [self.normalize_text(m[1]).strip() for m in matches if m[1].strip()]

    def decode_base64_candidate(self, candidate: str, depth: int = 1) -> Optional[DecodedPayload]:
        """Safely attempt to decode a base64 candidate string up to max_decode_depth."""
        if depth > self.max_decode_depth:
            return None
        candidate = candidate.strip()
        if len(candidate) < 16 or len(candidate) > 4096:
            return None

        try:
            raw_bytes = base64.b64decode(candidate, validate=True)
            # Only consider valid UTF-8 strings
            decoded_text = raw_bytes.decode("utf-8", errors="strict")
            # Must be primarily printable characters
            printable_ratio = sum(c.isprintable() or c.isspace() for c in decoded_text) / max(1, len(decoded_text))
            if printable_ratio < 0.85:
                return None

            decoded_text = decoded_text[: self.max_decoded_len].strip()
            if not decoded_text:
                return None

            # Check if decoded payload contains another nested base64 layer
            nested_candidate = BASE64_REGEX.search(decoded_text)
            if nested_candidate and depth < self.max_decode_depth:
                nested_res = self.decode_base64_candidate(nested_candidate.group(0), depth + 1)
                if nested_res:
                    return nested_res

            # Check for suspicious keywords
            words = set(re.findall(r"\b[a-zA-Z]{3,}\b", decoded_text.lower()))
            found_keywords = list(words.intersection(SUSPICIOUS_DECODED_KEYWORDS))

            return DecodedPayload(
                encoding_type=f"BASE64_L{depth}",
                original=candidate,
                decoded=decoded_text,
                is_suspicious=len(found_keywords) > 0,
                suspicious_keywords=found_keywords,
            )
        except Exception:
            return None

    def scan_for_encoded_payloads(self, text: str) -> List[DecodedPayload]:
        """Find and decode base64 or percent-encoded sequences in text."""
        payloads: List[DecodedPayload] = []
        if not text:
            return payloads

        # 1. Base64 candidates
        for match in BASE64_REGEX.finditer(text):
            candidate = match.group(0)
            res = self.decode_base64_candidate(candidate)
            if res and res.is_suspicious:
                payloads.append(res)

        # 2. Percent-encoded check if URL contains %xx heavily
        if "%" in text:
            try:
                unquoted = urllib.parse.unquote(text)
                if unquoted != text:
                    words = set(re.findall(r"\b[a-zA-Z]{3,}\b", unquoted.lower()))
                    found_kw = list(words.intersection(SUSPICIOUS_DECODED_KEYWORDS))
                    if found_kw:
                        payloads.append(
                            DecodedPayload(
                                encoding_type="URL_PERCENT",
                                original=text[:100],
                                decoded=unquoted[: self.max_decoded_len],
                                is_suspicious=True,
                                suspicious_keywords=found_kw,
                            )
                        )
            except Exception:
                pass

        return payloads

    def process_field(self, field_name: str, raw_text: Optional[str]) -> NormalizedField:
        """
        Fully normalize and inspect a single text field from product data.
        """
        if not raw_text:
            return NormalizedField(
                field_name=field_name,
                raw_text="",
                normalized_text="",
                zero_width_chars_removed=0,
            )

        was_truncated = False
        text = str(raw_text)
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
            was_truncated = True

        # Unescape HTML entities first (e.g. &lt;!-- &gt;)
        unescaped_text = html.unescape(text)

        # Count zero-width chars
        zero_width_matches = ZERO_WIDTH_REGEX.findall(unescaped_text)
        zw_count = len(zero_width_matches)

        # Normalized main text
        normalized_text = self.normalize_text(unescaped_text)

        # Extract hidden structures
        html_comments = self.extract_html_comments(unescaped_text)
        hidden_elements = self.extract_hidden_elements(unescaped_text)

        # Scan for encoded instructions in text + comments
        text_to_scan = f"{normalized_text} {' '.join(html_comments)} {' '.join(hidden_elements)}"
        decoded_payloads = self.scan_for_encoded_payloads(text_to_scan)

        return NormalizedField(
            field_name=field_name,
            raw_text=raw_text,
            normalized_text=normalized_text,
            zero_width_chars_removed=zw_count,
            html_comments=html_comments,
            hidden_elements=hidden_elements,
            decoded_payloads=decoded_payloads,
            was_truncated=was_truncated,
        )

    def process_dict(self, data: Dict[str, any]) -> Dict[str, NormalizedField]:
        """Process multiple key-value fields from a product record."""
        results: Dict[str, NormalizedField] = {}
        for k, v in list(data.items())[: settings.SECURITY_SCAN_MAX_FIELDS]:
            if isinstance(v, (str, int, float, bool)):
                results[k] = self.process_field(k, str(v))
            elif isinstance(v, list):
                # Join string lists (like tags)
                joined = " ".join(str(item) for item in v if isinstance(item, (str, int, float)))
                results[k] = self.process_field(k, joined)
        return results


content_normalizer = ContentNormalizer()
