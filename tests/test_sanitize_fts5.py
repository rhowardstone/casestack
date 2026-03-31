"""Regression tests for _sanitize_fts5() in the ask API route.

Previously the sanitizer stripped ALL asterisks, including valid FTS5 prefix
wildcards (e.g. "recommend*"). This caused the query planner's wildcard queries
to arrive at the FTS5 engine as plain terms, dramatically reducing recall for
inflected words (recommended/recommends/recommendation → no match for recommend*).
"""
from __future__ import annotations

import pytest

from casestack.api.routes.ask import _sanitize_fts5


class TestSanitizeFts5:
    def test_prefix_wildcard_preserved(self):
        """Bug regression: recommend* must not be stripped to 'recommend'."""
        assert _sanitize_fts5("recommend*") == "recommend*"

    def test_prefix_wildcard_mid_query(self):
        assert _sanitize_fts5("OIG recommend*") == "OIG recommend*"

    def test_prefix_wildcard_with_phrase(self):
        assert _sanitize_fts5('"wire transfer" AND bank*') == '"wire transfer" AND bank*'

    def test_multiple_wildcards_preserved(self):
        result = _sanitize_fts5("prosecut* disciplin*")
        assert "prosecut*" in result
        assert "disciplin*" in result

    def test_bare_star_stripped(self):
        """A bare * not attached to a word (e.g. glob-style) should be removed."""
        result = _sanitize_fts5("5 * 3")
        assert "*" not in result

    def test_leading_star_stripped(self):
        """FTS5 does not support leading wildcards — *word is not valid."""
        result = _sanitize_fts5("*word")
        assert result == "word"

    def test_special_chars_stripped(self):
        result = _sanitize_fts5("test (parens) [brackets] {braces}")
        assert "(" not in result
        assert ")" not in result
        assert "[" not in result
        assert "]" not in result

    def test_stop_words_removed(self):
        result = _sanitize_fts5("what is the answer")
        assert "what" not in result.lower()
        assert "is" not in result.lower()
        assert "the" not in result.lower()
        assert "answer" in result

    def test_empty_string(self):
        assert _sanitize_fts5("") == ""

    def test_only_stop_words(self):
        # All stop words: should return something (the cleaned version)
        result = _sanitize_fts5("what is the")
        # After stop word removal result may be empty; should not crash
        assert isinstance(result, str)

    def test_whitespace_collapsed(self):
        result = _sanitize_fts5("foo   bar    baz")
        assert "  " not in result
