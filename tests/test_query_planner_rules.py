"""Regression tests for QUERY_PLANNER_PROMPT rule coverage.

These tests verify the prompt text contains the critical rules that prevent
known query-planning failures found during dogfooding.
"""
from __future__ import annotations

from casestack.api.routes.ask import QUERY_PLANNER_PROMPT, ANSWER_SYSTEM


class TestQueryPlannerRules:
    """Verify rule text is present in the query planner prompt."""

    def test_rule_noun_verb_inflection(self):
        """Rule 9: planner must be told to search verbal forms for payment/transfer."""
        assert "paid" in QUERY_PLANNER_PROMPT
        assert "wire" in QUERY_PLANNER_PROMPT

    def test_rule_max_terms(self):
        """Rule 6: max 2-3 key terms per query."""
        assert "2 to 3" in QUERY_PLANNER_PROMPT or "2-3" in QUERY_PLANNER_PROMPT

    def test_rule_prefix_wildcards(self):
        """Rule 7: use prefix wildcards for inflected forms."""
        assert "recommend*" in QUERY_PLANNER_PROMPT

    def test_rule_no_citation_artifacts(self):
        """Rule 4: no page numbers or document IDs in queries."""
        assert "EFTA" in QUERY_PLANNER_PROMPT  # example of what NOT to include

    def test_rule_minimum_vocabulary_query(self):
        """Rule 8: always include a single-root minimum vocab query."""
        assert "minimum vocabulary" in QUERY_PLANNER_PROMPT or "minimum" in QUERY_PLANNER_PROMPT

    def test_rule_proper_nouns(self):
        """Rule 1: preserve proper nouns exactly."""
        assert "proper noun" in QUERY_PLANNER_PROMPT.lower() or "last name" in QUERY_PLANNER_PROMPT.lower()

    def test_rule_multiple_queries_instead_of_long(self):
        """Rule 6: spaces are AND operators — multiple short queries beat one long query."""
        assert "AND" in QUERY_PLANNER_PROMPT  # explanation of AND semantics

    def test_rule_comma_numeric_amounts(self):
        """Rule 10: FTS5 splits on commas — search '250' not '250,000'."""
        # Must warn about comma-splitting and give guidance on numeric queries
        assert "250" in QUERY_PLANNER_PROMPT or "comma" in QUERY_PLANNER_PROMPT.lower()
        assert "FAIL" in QUERY_PLANNER_PROMPT or "splits" in QUERY_PLANNER_PROMPT.lower()

    def test_rule_action_verb_queries(self):
        """Rule 11: for 'what did X do' questions, also search action verbs like gather*, locat*."""
        assert "gather" in QUERY_PLANNER_PROMPT
        assert "locat" in QUERY_PLANNER_PROMPT

    def test_rule_legal_vocabulary(self):
        """Rule 12: use legal document vocabulary for charges/prosecution questions."""
        assert "nolle prosequi" in QUERY_PLANNER_PROMPT
        assert "deferred prosecution" in QUERY_PLANNER_PROMPT
        assert "indictment" in QUERY_PLANNER_PROMPT

    def test_rule_no_invented_dates(self):
        """Rule 3 extension: must not invent dates/years not in the question."""
        assert "NEVER invent" in QUERY_PLANNER_PROMPT or "not appear verbatim" in QUERY_PLANNER_PROMPT


class TestAnswerSystemNumericalReasoning:
    """Verify ANSWER_SYSTEM instructs LLM to compute from timestamps."""

    def test_timestamp_arithmetic_instruction(self):
        """Must tell LLM to compute elapsed time from timestamps, not accept summaries."""
        assert "timestamp" in ANSWER_SYSTEM.lower() or "elapsed" in ANSWER_SYSTEM.lower()

    def test_conflict_reporting(self):
        """When computed duration conflicts with stated summary, report discrepancy."""
        assert "conflict" in ANSWER_SYSTEM.lower() or "discrepancy" in ANSWER_SYSTEM.lower()

    def test_cite_every_claim(self):
        """Core instruction: cite every factual claim."""
        assert "Cite every" in ANSWER_SYSTEM or "cite every" in ANSWER_SYSTEM.lower()

    def test_no_hallucination_instruction(self):
        """Must not make claims without citations."""
        assert "without citations" in ANSWER_SYSTEM or "no citation" in ANSWER_SYSTEM.lower()
