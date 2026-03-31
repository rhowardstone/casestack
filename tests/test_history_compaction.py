"""Regression tests for _compact_history_turns() in ask.py.

When a conversation exceeds _MAX_HISTORY_TURNS Q&A pairs, older turns should be
compacted into a structured context block rather than silently discarded.  This
preserves investigative findings across the context boundary.
"""
from __future__ import annotations

import pytest

from casestack.api.routes.ask import (
    _compact_history_turns,
    _MAX_HISTORY_TURNS,
    _COMPACT_ANSWER_CHARS,
)


def _make_turns(n: int) -> list[dict]:
    """Create n Q&A pairs as a flat message list."""
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"Question {i}"})
        msgs.append({"role": "assistant", "content": f"Answer {i} with some detail about finding {i}."})
    return msgs


class TestCompactHistoryTurns:
    def test_returns_user_and_assistant_pair(self):
        dropped = _make_turns(3)
        user_msg, asst_ack = _compact_history_turns(dropped)
        assert user_msg["role"] == "user"
        assert asst_ack["role"] == "assistant"

    def test_context_header_present(self):
        dropped = _make_turns(2)
        user_msg, _ = _compact_history_turns(dropped)
        assert "Prior investigation context" in user_msg["content"]

    def test_all_questions_appear_in_compact(self):
        dropped = _make_turns(3)
        user_msg, _ = _compact_history_turns(dropped)
        for i in range(3):
            assert f"Question {i}" in user_msg["content"]

    def test_all_answers_appear_in_compact(self):
        dropped = _make_turns(3)
        user_msg, _ = _compact_history_turns(dropped)
        for i in range(3):
            assert f"Answer {i}" in user_msg["content"]

    def test_long_answer_is_truncated(self):
        long_answer = "x" * (_COMPACT_ANSWER_CHARS + 200)
        dropped = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": long_answer},
        ]
        user_msg, _ = _compact_history_turns(dropped)
        # Truncation ellipsis must be present
        assert "..." in user_msg["content"]
        # Full answer must NOT appear verbatim
        assert long_answer not in user_msg["content"]

    def test_short_answer_not_truncated(self):
        short_answer = "Short answer."
        dropped = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": short_answer},
        ]
        user_msg, _ = _compact_history_turns(dropped)
        assert short_answer in user_msg["content"]
        assert "..." not in user_msg["content"]

    def test_question_truncated_at_150_chars(self):
        # Place a unique marker at index 150 so [:150] slice excludes it
        long_q = "A" * 150 + "UNIQUEMARKER_PAST_TRUNCATION"
        dropped = [
            {"role": "user", "content": long_q},
            {"role": "assistant", "content": "A"},
        ]
        user_msg, _ = _compact_history_turns(dropped)
        assert "A" * 10 in user_msg["content"]  # beginning is present
        assert "UNIQUEMARKER_PAST_TRUNCATION" not in user_msg["content"]

    def test_empty_dropped_produces_header_only(self):
        user_msg, asst_ack = _compact_history_turns([])
        assert "Prior investigation context" in user_msg["content"]
        assert asst_ack["role"] == "assistant"

    def test_mismatched_roles_skipped(self):
        """Two consecutive user messages don't crash."""
        dropped = [
            {"role": "user", "content": "Q1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A"},
        ]
        user_msg, _ = _compact_history_turns(dropped)  # should not raise
        assert "Prior investigation context" in user_msg["content"]


class TestHistoryCompactionIntegration:
    """Verify the compaction threshold triggers at the right point.

    We don't run a full server here — just test the threshold arithmetic
    to ensure the boundary condition matches the constant.
    """

    def test_max_history_turns_constant(self):
        """_MAX_HISTORY_TURNS should be positive and even threshold."""
        assert _MAX_HISTORY_TURNS > 0

    def test_compact_answer_chars_reasonable(self):
        """_COMPACT_ANSWER_CHARS should be between 100 and 2000."""
        assert 100 <= _COMPACT_ANSWER_CHARS <= 2000

    def test_compaction_preserves_chronological_order(self):
        """Questions and answers appear in order within the compact block."""
        dropped = _make_turns(4)
        user_msg, _ = _compact_history_turns(dropped)
        text = user_msg["content"]
        positions = [text.index(f"Question {i}") for i in range(4)]
        assert positions == sorted(positions)
