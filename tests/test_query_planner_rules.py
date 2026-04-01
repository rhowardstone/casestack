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

    def test_rule_no_not_operator(self):
        """Rule 4 extension: FTS5 NOT operator must not be used (almost always wrong)."""
        assert "NOT operator" in QUERY_PLANNER_PROMPT or "NEVER use the FTS5 NOT" in QUERY_PLANNER_PROMPT

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

    def test_rule_compliance_failure_vocabulary(self):
        """Rule 13: compliance failures are described as 'missing' in govt docs, not 'unsigned/failed'."""
        # Corpus says "16 of 16 instances were missing" — not "failed to sign" or "unsigned"
        assert "missing" in QUERY_PLANNER_PROMPT
        assert "signatures missing" in QUERY_PLANNER_PROMPT or "missing sign" in QUERY_PLANNER_PROMPT

    def test_rule_no_clock_times_in_queries(self):
        """Rule 14: clock times (6:45pm, 10:30pm) must never appear in FTS5 queries."""
        # FTS5 tokenizes ':' as separator — "6:45pm" → tokens "6","45pm", matches nothing
        assert "NEVER include clock times" in QUERY_PLANNER_PROMPT or "clock time" in QUERY_PLANNER_PROMPT.lower()
        assert "6:45" in QUERY_PLANNER_PROMPT  # example of what NOT to include

    def test_rule_bop_vocabulary(self):
        """Rule 15: use BOP institutional vocabulary — 'legal visit*' not 'attorney visits'."""
        assert "legal visit" in QUERY_PLANNER_PROMPT
        assert "psychological observation" in QUERY_PLANNER_PROMPT


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
        """Must not make claims without citations or speculate beyond the evidence."""
        assert (
            "without citations" in ANSWER_SYSTEM
            or "no citation" in ANSWER_SYSTEM.lower()
            or "do not speculate" in ANSWER_SYSTEM.lower()
            or "speculate" in ANSWER_SYSTEM.lower()
        )


class TestAnswerSystemSourceHierarchy:
    """Verify ANSWER_SYSTEM encodes the evidentiary source hierarchy."""

    def test_primary_records_ranked_highest(self):
        """Primary event records (logs, count sheets) must outrank narrative summaries."""
        assert "Primary event records" in ANSWER_SYSTEM or "primary event" in ANSWER_SYSTEM.lower()

    def test_fd302_ranked_above_summaries(self):
        """FD-302 interview transcripts must be explicitly ranked above investigative summaries."""
        assert "FD-302" in ANSWER_SYSTEM or "interview transcript" in ANSWER_SYSTEM.lower()

    def test_narrative_summaries_ranked_lowest(self):
        """Narrative summaries must be identified as lowest-authority source type."""
        assert "Narrative summar" in ANSWER_SYSTEM or "narrative summar" in ANSWER_SYSTEM.lower()

    def test_primary_record_overrides_summary(self):
        """Must instruct LLM to prefer primary records when they conflict with summaries."""
        assert "authoritative" in ANSWER_SYSTEM.lower()

    def test_multi_source_confirmation(self):
        """When multiple sources confirm the same fact, cite all of them."""
        assert "multiple source" in ANSWER_SYSTEM.lower() or "confirm the same" in ANSWER_SYSTEM.lower()


class TestAnswerSystemHonestyFraming:
    """Verify ANSWER_SYSTEM enforces three-tier honesty framing (documented / implied / absent)."""

    def test_documented_fact_tier(self):
        """Must distinguish explicit document statements from inferences."""
        assert "documents state" in ANSWER_SYSTEM.lower() or "direct quote" in ANSWER_SYSTEM.lower()

    def test_inference_tier(self):
        """Must distinguish inferences from documented facts."""
        assert "documents imply" in ANSWER_SYSTEM.lower() or "reasonable inference" in ANSWER_SYSTEM.lower()

    def test_absence_of_evidence_tier(self):
        """Must distinguish 'not in evidence' from 'proof of absence'."""
        assert "do not address" in ANSWER_SYSTEM.lower() or "absence of evidence" in ANSWER_SYSTEM.lower()


class TestAnswerSystemFollowUpQuestions:
    """Verify ANSWER_SYSTEM instructs the LLM to surface follow-up questions."""

    def test_follow_up_questions_required(self):
        """Every answer must end with follow-up threads worth investigating."""
        # The prompt must instruct the LLM to suggest follow-up questions
        assert "follow-up" in ANSWER_SYSTEM.lower() or "threads worth" in ANSWER_SYSTEM.lower()

    def test_follow_up_count(self):
        """Must specify how many follow-up questions to generate (2-3)."""
        assert "2" in ANSWER_SYSTEM and "3" in ANSWER_SYSTEM  # "2–3" or "2-3"

    def test_follow_up_focus_on_gaps(self):
        """Follow-up questions should surface gaps and contradictions, not generic queries."""
        assert "gap" in ANSWER_SYSTEM.lower() or "contradiction" in ANSWER_SYSTEM.lower() or "unresolved" in ANSWER_SYSTEM.lower()
