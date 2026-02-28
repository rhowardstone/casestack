"""Deduplication of documents using title similarity, Bates range overlap, and content hashing."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import defaultdict
from typing import NamedTuple

from pydantic import BaseModel
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class DedupRecord(NamedTuple):
    """Lightweight record carrying only the fields needed for dedup.

    Using this instead of full ``Document`` objects avoids loading large
    ``ocrText`` bodies into memory (~3 GB for 531K docs → ~200 MB).
    """

    id: str
    title: str
    bates_range: str | None
    content_hash: str | None


class DuplicatePair(BaseModel):
    """A pair of documents identified as probable duplicates."""

    doc_id_1: str
    doc_id_2: str
    score: float  # 0.0 - 1.0, where 1.0 is identical
    reason: str  # Human-readable explanation (e.g. "title similarity: 0.95")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_BATES_PATTERN = re.compile(r"([A-Z]+)(\d+)")

# Titles that are just identifiers (e.g. "EFTA00039025", "DOJ-001234") produce
# false-positive fuzzy matches because they differ by only 1-2 digits.  Skip them.
_IDENTIFIER_TITLE = re.compile(r"^[A-Za-z]{1,10}[\-_]?\d{3,}$")


def _parse_bates_range(bates: str) -> tuple[str, int, int] | None:
    """Parse a Bates range like 'PREFIX00039025-PREFIX00039030'.

    Returns (prefix, start_num, end_num) or None if unparseable.
    """
    parts = bates.split("-")
    if len(parts) < 2:
        # Single Bates number -- treat as a one-page range.
        m = _BATES_PATTERN.match(parts[0].strip())
        if m:
            prefix, num_str = m.group(1), m.group(2)
            num = int(num_str)
            return (prefix, num, num)
        return None

    m1 = _BATES_PATTERN.match(parts[0].strip())
    m2 = _BATES_PATTERN.match(parts[-1].strip())
    if not m1 or not m2:
        return None

    prefix1, num1 = m1.group(1), int(m1.group(2))
    prefix2, num2 = m2.group(1), int(m2.group(2))

    # Bates ranges should share a prefix.
    if prefix1 != prefix2:
        return None

    return (prefix1, min(num1, num2), max(num1, num2))


def _content_hash(text: str) -> str:
    """SHA-256 of normalised text (lowered, whitespace-collapsed)."""
    normalised = " ".join(text.lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class Deduplicator:
    """Find duplicate document pairs using multiple signals.

    Signals checked (in order):
    1. **Content hash** -- if both records have a ``content_hash`` and they
       match, they are exact duplicates (score 1.0).  O(n).
    2. **Bates range overlap** -- sorted-sweep algorithm.  O(n log n).
    3. **Title similarity** -- blocked comparison (first 6 chars + length
       bucket) so only similar titles are compared.  ~O(n × k) where k is
       the average block size (typically < 100).
    """

    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    # Max forward comparisons per item in the Bates sweep.  Prevents
    # quadratic blowup when many documents share a single wide range.
    BATES_MAX_FANOUT = 200

    # Max block size for title comparison.  Blocks larger than this are
    # sub-divided by a finer key to keep pairwise cost bounded.
    TITLE_BLOCK_CAP = 500

    def find_duplicates(self, records: list[DedupRecord]) -> list[DuplicatePair]:
        """Scan records and return those that look like duplicates.

        The returned list is sorted by descending score so the most confident
        matches appear first.
        """
        t_total = time.monotonic()
        pairs: list[DuplicatePair] = []
        seen: set[tuple[str, str]] = set()

        # --- Signal 1: Content hash (O(n)) ---
        t0 = time.monotonic()
        hash_groups: dict[str, list[str]] = defaultdict(list)
        for rec in records:
            if rec.content_hash:
                hash_groups[rec.content_hash].append(rec.id)

        for group in hash_groups.values():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = (min(group[i], group[j]), max(group[i], group[j]))
                    if pair_key not in seen:
                        seen.add(pair_key)
                        pairs.append(
                            DuplicatePair(
                                doc_id_1=pair_key[0],
                                doc_id_2=pair_key[1],
                                score=1.0,
                                reason="exact content hash match",
                            )
                        )
        logger.info(
            "Signal 1 (content hash): %.1fs, %d pairs from %d groups",
            time.monotonic() - t0, len(pairs), sum(1 for g in hash_groups.values() if len(g) >= 2),
        )

        # --- Signal 2: Bates overlap — sorted sweep (O(n log n)) ---
        t0 = time.monotonic()
        pairs_before = len(pairs)
        bates_docs: list[tuple[DedupRecord, tuple[str, int, int]]] = []
        for rec in records:
            if rec.bates_range:
                parsed = _parse_bates_range(rec.bates_range)
                if parsed:
                    bates_docs.append((rec, parsed))

        # Sort by (prefix, start_num) so overlapping ranges are adjacent.
        bates_docs.sort(key=lambda x: (x[1][0], x[1][1]))
        logger.info("Bates sweep: %d docs with parseable ranges", len(bates_docs))

        for i, (a, ra) in enumerate(bates_docs):
            fan = 0
            for j in range(i + 1, len(bates_docs)):
                b, rb = bates_docs[j]
                if ra[0] != rb[0] or rb[1] > ra[2]:
                    break
                fan += 1
                if fan > self.BATES_MAX_FANOUT:
                    break
                pair_key = (min(a.id, b.id), max(a.id, b.id))
                if pair_key not in seen:
                    seen.add(pair_key)
                    pairs.append(
                        DuplicatePair(
                            doc_id_1=pair_key[0],
                            doc_id_2=pair_key[1],
                            score=0.95,
                            reason=f"Bates range overlap: {a.bates_range} / {b.bates_range}",
                        )
                    )
        logger.info(
            "Signal 2 (Bates overlap): %.1fs, %d new pairs",
            time.monotonic() - t0, len(pairs) - pairs_before,
        )

        # --- Signal 3: Title similarity — blocked comparison (~O(n × k)) ---
        t0 = time.monotonic()
        pairs_before = len(pairs)

        # Block key: first 6 chars of lowered title + length bucket (//5).
        # Skip titles that are just identifiers (e.g. "EFTA00039025") — they
        # produce false-positive matches because they differ by only 1-2 digits.
        skipped_ids = 0
        blocks: dict[str, list[DedupRecord]] = defaultdict(list)
        for rec in records:
            if rec.title:
                stripped = rec.title.strip()
                if _IDENTIFIER_TITLE.match(stripped):
                    skipped_ids += 1
                    continue
                norm = stripped.lower()
                key = f"{norm[:6]}_{len(norm) // 5}"
                blocks[key].append(rec)
        if skipped_ids:
            logger.info("Title blocking: skipped %d identifier-only titles", skipped_ids)

        big_blocks = sum(1 for b in blocks.values() if len(b) > self.TITLE_BLOCK_CAP)
        if big_blocks:
            logger.info(
                "Title blocking: %d blocks, %d over cap (%d) — sub-dividing",
                len(blocks), big_blocks, self.TITLE_BLOCK_CAP,
            )
            # Re-block oversized blocks with a finer key (first 10 chars + length//3).
            refined: dict[str, list[DedupRecord]] = {}
            for key, block in blocks.items():
                if len(block) <= self.TITLE_BLOCK_CAP:
                    refined[key] = block
                else:
                    for rec in block:
                        norm = rec.title.lower().strip()
                        fine_key = f"{norm[:10]}_{len(norm) // 3}"
                        refined.setdefault(fine_key, []).append(rec)
            blocks = refined
            still_big = sum(1 for b in blocks.values() if len(b) > self.TITLE_BLOCK_CAP)
            if still_big:
                logger.warning(
                    "%d blocks still over cap after refinement — largest: %d",
                    still_big, max(len(b) for b in blocks.values()),
                )

        logger.info("Title comparison: %d blocks, max size %d",
                     len(blocks), max((len(b) for b in blocks.values()), default=0))

        for block in blocks.values():
            blen = len(block)
            if blen < 2:
                continue
            # For very large blocks that survived refinement, cap pairwise.
            cap = min(blen, self.TITLE_BLOCK_CAP)
            for i in range(cap):
                for j in range(i + 1, cap):
                    a, b = block[i], block[j]
                    pair_key = (min(a.id, b.id), max(a.id, b.id))
                    if pair_key in seen:
                        continue
                    ratio = fuzz.ratio(a.title.lower(), b.title.lower()) / 100.0
                    if ratio >= self.threshold:
                        seen.add(pair_key)
                        pairs.append(
                            DuplicatePair(
                                doc_id_1=pair_key[0],
                                doc_id_2=pair_key[1],
                                score=round(ratio, 4),
                                reason=f"title similarity: {ratio:.2%}",
                            )
                        )
        logger.info(
            "Signal 3 (title similarity): %.1fs, %d new pairs",
            time.monotonic() - t0, len(pairs) - pairs_before,
        )

        pairs.sort(key=lambda p: p.score, reverse=True)
        logger.info("Dedup complete: %.1fs total, %d pairs", time.monotonic() - t_total, len(pairs))
        return pairs
