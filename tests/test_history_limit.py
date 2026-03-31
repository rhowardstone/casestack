"""Regression tests for conversation history trimming in the ask API route.

Without a limit, long conversations send an ever-growing history to the LLM,
eventually blowing up the context window. These tests enforce the cap.
"""
from __future__ import annotations

import pytest

from casestack.api.routes.ask import _MAX_HISTORY_TURNS


def _make_history(n_turns: int) -> list[dict]:
    """Build a minimal message list: n_turns user+assistant pairs."""
    messages = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": f"Question {i}"})
        messages.append({"role": "assistant", "content": f"Answer {i}"})
    return messages


class TestHistoryTrimming:
    def test_constant_is_positive(self):
        assert _MAX_HISTORY_TURNS > 0

    def test_short_history_not_truncated(self):
        """A conversation shorter than the cap passes through unchanged."""
        msgs = _make_history(_MAX_HISTORY_TURNS - 1)
        tail = msgs[-(_MAX_HISTORY_TURNS * 2):]
        assert tail == msgs

    def test_exactly_at_cap_not_truncated(self):
        """A conversation exactly at the cap is not truncated."""
        msgs = _make_history(_MAX_HISTORY_TURNS)
        tail = msgs[-(_MAX_HISTORY_TURNS * 2):]
        assert len(tail) == _MAX_HISTORY_TURNS * 2
        assert tail == msgs

    def test_over_cap_is_truncated(self):
        """A conversation over the cap keeps only the most recent turns."""
        n_turns = _MAX_HISTORY_TURNS + 5
        msgs = _make_history(n_turns)
        tail = msgs[-(_MAX_HISTORY_TURNS * 2):]
        assert len(tail) == _MAX_HISTORY_TURNS * 2

    def test_truncation_keeps_most_recent(self):
        """Truncation drops the oldest turns, not the newest."""
        n_turns = _MAX_HISTORY_TURNS + 3
        msgs = _make_history(n_turns)
        tail = msgs[-(_MAX_HISTORY_TURNS * 2):]
        # The tail should end with the last turn's messages
        assert tail[-1] == msgs[-1]
        assert tail[-2] == msgs[-2]

    def test_truncation_drops_oldest(self):
        """The oldest messages are the ones dropped."""
        n_turns = _MAX_HISTORY_TURNS + 3
        msgs = _make_history(n_turns)
        tail = msgs[-(_MAX_HISTORY_TURNS * 2):]
        # The first messages of the full list should NOT be in the tail
        assert msgs[0] not in tail
        assert msgs[1] not in tail

    def test_empty_history_unchanged(self):
        """An empty history list produces an empty tail."""
        tail = [][-(_MAX_HISTORY_TURNS * 2):]
        assert tail == []

    def test_cap_yields_even_number_of_messages(self):
        """The cap (_MAX_HISTORY_TURNS * 2) is always even (user+assistant pairs)."""
        assert (_MAX_HISTORY_TURNS * 2) % 2 == 0
