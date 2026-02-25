"""PII detection and redaction for document corpora.

Detects personally identifiable information in the pages table and can redact it.
Replaces PII with empty strings (not [REDACTED] tags) to prevent reverse-searchability.

Detection tiers:
  - Tier 1: High-confidence regex (phone, email, SSN)
  - Tier 2: Context-dependent patterns (DOB, address)

False positive filters prevent flagging document IDs, Bates stamps, URLs, and
invalid SSN/phone patterns.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PIIMatch:
    """A single PII detection in a document page."""

    doc_id: str
    page_number: int
    match_text: str
    pattern_type: str  # "phone", "email", "ssn", "dob", "address"
    confidence: float  # 0.0-1.0
    start: int  # character offset in text
    end: int


@dataclass
class PIIScanResult:
    """Results of scanning a database for PII."""

    total_pages_scanned: int
    matches: list[PIIMatch] = field(default_factory=list)

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def affected_pages(self) -> int:
        return len({(m.doc_id, m.page_number) for m in self.matches})

    @property
    def by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self.matches:
            counts[m.pattern_type] = counts.get(m.pattern_type, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Tier 1 patterns -- high-confidence regex
# ---------------------------------------------------------------------------

# US phone numbers: (xxx) xxx-xxxx, xxx-xxx-xxxx, xxx.xxx.xxxx
PHONE_RE = re.compile(
    r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)

# Email addresses
EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
)

# US Social Security Numbers: xxx-xx-xxxx
SSN_RE = re.compile(
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
)

TIER1_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("phone", PHONE_RE, 0.9),
    ("email", EMAIL_RE, 0.95),
    ("ssn", SSN_RE, 0.85),
]


# ---------------------------------------------------------------------------
# Tier 2 patterns -- context-dependent
# ---------------------------------------------------------------------------

# Date of birth: look for dates near context keywords
DOB_KEYWORDS = {"born", "birth", "dob", "d.o.b", "age", "birthday"}
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+ \d{1,2},? \d{4})\b"
)

# Street addresses: number + street name + type
ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Ln|Lane|Rd|Road|Ct|Court|Way|Pl|Place)\b",
    re.IGNORECASE,
)

# Context window size (characters before/after a match) for Tier 2 checks
_CONTEXT_WINDOW = 200


# ---------------------------------------------------------------------------
# False positive filters
# ---------------------------------------------------------------------------


def _is_false_positive_ssn(match_text: str, full_text: str, start: int) -> bool:
    """Filter SSN false positives."""
    digits = re.sub(r"\D", "", match_text)

    # All same digit (e.g. 000-00-0000, 111-11-1111)
    if len(set(digits)) == 1:
        return True

    # Invalid SSN prefixes: 000, 666, or 9xx
    if digits[:3] in ("000", "666") or digits[0] == "9":
        return True

    # Middle group all zeros or last group all zeros (invalid per SSA rules)
    if digits[3:5] == "00" or digits[5:9] == "0000":
        return True

    # Check if inside a URL or near a document ID pattern
    ctx_start = max(0, start - 50)
    ctx_end = start + len(match_text) + 50
    context = full_text[ctx_start:ctx_end]
    if re.search(r"https?://", context) or re.search(r"[A-Z]{2,}\d{5,}", context):
        return True

    return False


def _is_false_positive_phone(match_text: str, full_text: str, start: int) -> bool:
    """Filter phone number false positives."""
    digits = re.sub(r"\D", "", match_text)

    # All same digit
    if len(set(digits)) == 1:
        return True

    # Sequential digits (1234567890 or subset)
    if digits in "12345678901234567890":
        return True

    # Check if inside a URL
    ctx_start = max(0, start - 30)
    ctx_end = start + len(match_text) + 30
    context = full_text[ctx_start:ctx_end]
    if re.search(r"https?://", context):
        return True

    # Check if near Bates stamp patterns (e.g. EFTA00012345)
    if re.search(r"[A-Z]{2,}\d{5,}", context):
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 2 scanning
# ---------------------------------------------------------------------------


def _scan_tier2(
    text: str,
    doc_id: str,
    page_number: int,
    result: PIIScanResult,
) -> None:
    """Scan for context-dependent PII patterns (Tier 2)."""
    text_lower = text.lower()

    # Date of birth: find dates near DOB keywords
    for match in DATE_RE.finditer(text):
        ctx_start = max(0, match.start() - _CONTEXT_WINDOW)
        ctx_end = min(len(text), match.end() + _CONTEXT_WINDOW)
        context = text_lower[ctx_start:ctx_end]
        if any(kw in context for kw in DOB_KEYWORDS):
            result.matches.append(
                PIIMatch(
                    doc_id=doc_id,
                    page_number=page_number,
                    match_text=match.group(),
                    pattern_type="dob",
                    confidence=0.75,
                    start=match.start(),
                    end=match.end(),
                )
            )

    # Street addresses
    for match in ADDRESS_RE.finditer(text):
        result.matches.append(
            PIIMatch(
                doc_id=doc_id,
                page_number=page_number,
                match_text=match.group(),
                pattern_type="address",
                confidence=0.7,
                start=match.start(),
                end=match.end(),
            )
        )


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------


def scan_database(db_path: Path) -> PIIScanResult:
    """Scan all pages in the database for PII.

    Parameters
    ----------
    db_path:
        Path to the SQLite database with a ``pages`` table.

    Returns
    -------
    PIIScanResult
        Aggregated scan results with all detected PII matches.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        pages = conn.execute(
            "SELECT doc_id, page_number, text_content FROM pages"
        ).fetchall()
    finally:
        conn.close()

    result = PIIScanResult(total_pages_scanned=len(pages))

    for doc_id, page_number, text in pages:
        if not text:
            continue

        # Tier 1: high-confidence regex
        for pattern_type, regex, confidence in TIER1_PATTERNS:
            for match in regex.finditer(text):
                # Apply false positive filters
                if pattern_type == "ssn" and _is_false_positive_ssn(
                    match.group(), text, match.start()
                ):
                    continue
                if pattern_type == "phone" and _is_false_positive_phone(
                    match.group(), text, match.start()
                ):
                    continue
                result.matches.append(
                    PIIMatch(
                        doc_id=doc_id,
                        page_number=page_number,
                        match_text=match.group(),
                        pattern_type=pattern_type,
                        confidence=confidence,
                        start=match.start(),
                        end=match.end(),
                    )
                )

        # Tier 2: context-dependent
        _scan_tier2(text, doc_id, page_number, result)

    logger.info(
        "PII scan complete: %d pages scanned, %d matches found",
        result.total_pages_scanned,
        result.match_count,
    )
    return result


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def redact_database(db_path: Path, matches: list[PIIMatch]) -> int:
    """Redact PII matches from the database pages.

    Replaces matched text with empty strings (not ``[REDACTED]`` tags) to
    prevent reverse-searchability. Updates ``char_count`` and rebuilds the
    FTS5 index after all changes.

    Parameters
    ----------
    db_path:
        Path to the SQLite database.
    matches:
        List of PIIMatch objects to redact.

    Returns
    -------
    int
        Number of individual PII items redacted.
    """
    if not matches:
        return 0

    conn = sqlite3.connect(str(db_path))

    # Group by (doc_id, page_number)
    groups: dict[tuple[str, int], list[PIIMatch]] = {}
    for m in matches:
        key = (m.doc_id, m.page_number)
        groups.setdefault(key, []).append(m)

    redacted = 0
    for (doc_id, page_num), page_matches in groups.items():
        # Get current text
        row = conn.execute(
            "SELECT text_content FROM pages WHERE doc_id = ? AND page_number = ?",
            (doc_id, page_num),
        ).fetchone()
        if not row:
            continue

        text = row[0]
        # Sort matches by start position descending (so offsets don't shift)
        for m in sorted(page_matches, key=lambda x: x.start, reverse=True):
            text = text[: m.start] + text[m.end :]
            redacted += 1

        # Update the page
        conn.execute(
            "UPDATE pages SET text_content = ?, char_count = ? "
            "WHERE doc_id = ? AND page_number = ?",
            (text, len(text), doc_id, page_num),
        )

    # Rebuild FTS index after redaction
    try:
        conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
    except Exception:
        logger.warning("FTS rebuild failed; index may be stale")

    conn.commit()
    conn.close()

    logger.info("Redacted %d PII items across %d pages", redacted, len(groups))
    return redacted
