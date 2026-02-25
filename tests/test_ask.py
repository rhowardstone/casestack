"""Tests for the ask-proxy RAG system.

Covers:
- search_pages() against a real SQLite database
- Query planner prompt formatting
- Answer prompt formatting with evidence injection
- _parse_queries() helper for LLM response parsing
- The full ask() function with mocked LLM calls
- CLI ask command with mocked ask function
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from casestack.ask import (
    ANSWER_PROMPT,
    QUERY_PLANNER_PROMPT,
    _parse_queries,
    ask,
    call_llm,
    search_pages,
)
from casestack.models.document import Document, Page


# ---------------------------------------------------------------------------
# Fixture: create a test database with documents + pages + FTS5
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db():
    """Create a temporary SQLite database with the CaseStack schema and test data."""
    from casestack.exporters.sqlite_export import SqliteExporter

    docs = [
        Document(
            id="doc-finance-001",
            title="Wire Transfer Records",
            source="financial",
            category="financial",
            summary="Bank wire transfer records from 2019",
            ocrText="Wire transfer of $500,000 from Account A to Account B on March 15, 2019",
            tags=["wire-transfer", "banking"],
        ),
        Document(
            id="doc-travel-001",
            title="Flight Manifest July 2019",
            source="travel",
            category="travel",
            summary="Private aircraft flight logs",
            ocrText="Passengers: John Smith, Jane Doe. Route: New York to Miami.",
            tags=["flight", "travel"],
        ),
        Document(
            id="doc-legal-001",
            title="Deposition Transcript",
            source="court-filing",
            category="legal",
            summary="Witness deposition transcript",
            ocrText="Q: Did you authorize the wire transfer? A: I have no recollection.",
            tags=["deposition", "legal"],
        ),
    ]
    pages = [
        # doc-finance-001: 2 pages
        Page(
            document_id="doc-finance-001",
            page_number=1,
            text_content=(
                "Wire transfer of $500,000 from Account A to Account B. "
                "Transaction date: March 15, 2019. Reference: WT-2019-0315."
            ),
            char_count=120,
        ),
        Page(
            document_id="doc-finance-001",
            page_number=2,
            text_content=(
                "Beneficiary bank: First National Bank of Miami. "
                "Originator: Offshore Holdings Ltd. SWIFT code: FNBMUS33."
            ),
            char_count=110,
        ),
        # doc-travel-001: 1 page
        Page(
            document_id="doc-travel-001",
            page_number=1,
            text_content=(
                "Flight manifest for July 12, 2019. Aircraft: Gulfstream G550. "
                "Passengers: John Smith, Jane Doe, Robert Johnson. "
                "Route: Teterboro (KTEB) to Miami-Opa Locka (KOPF)."
            ),
            char_count=160,
        ),
        # doc-legal-001: 3 pages
        Page(
            document_id="doc-legal-001",
            page_number=1,
            text_content=(
                "DEPOSITION OF JAMES WILSON "
                "Q: State your name for the record. A: James Wilson."
            ),
            char_count=80,
        ),
        Page(
            document_id="doc-legal-001",
            page_number=2,
            text_content=(
                "Q: Did you authorize the wire transfer of $500,000? "
                "A: I have no recollection of that transaction."
            ),
            char_count=100,
        ),
        Page(
            document_id="doc-legal-001",
            page_number=3,
            text_content=(
                "Q: Were you present on the flight to Miami on July 12? "
                "A: I may have been, I don't recall the specific date."
            ),
            char_count=105,
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ask.db"
        exporter = SqliteExporter()
        exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)
        yield db_path


# ---------------------------------------------------------------------------
# search_pages() tests
# ---------------------------------------------------------------------------


class TestSearchPages:
    def test_basic_single_query(self, test_db):
        """A single FTS5 query returns matching pages."""
        results = search_pages(test_db, ["wire transfer"])
        assert len(results) >= 1
        # Should find the wire transfer pages
        doc_ids = {r["doc_id"] for r in results}
        assert "doc-finance-001" in doc_ids

    def test_multiple_queries_dedup(self, test_db):
        """Multiple queries that match the same page are deduplicated."""
        results = search_pages(test_db, ["wire transfer", "wire AND transfer"])
        # The same pages should not appear twice
        keys = [(r["doc_id"], r["page_number"]) for r in results]
        assert len(keys) == len(set(keys)), "Results should be deduplicated"

    def test_no_results_for_nonexistent(self, test_db):
        """A query with no matches returns an empty list."""
        results = search_pages(test_db, ["xyznonexistent123"])
        assert results == []

    def test_malformed_query_skipped(self, test_db):
        """A malformed FTS5 query is skipped without crashing."""
        results = search_pages(test_db, ['invalid OR OR query ""'])
        # Should not raise, just skip
        assert isinstance(results, list)

    def test_empty_query_skipped(self, test_db):
        """Empty or whitespace-only queries are skipped."""
        results = search_pages(test_db, ["", "  ", "Miami"])
        # "Miami" should still return results
        assert any(r["doc_id"] == "doc-travel-001" for r in results)

    def test_result_structure(self, test_db):
        """Each result has the expected keys."""
        results = search_pages(test_db, ["deposition"])
        assert len(results) >= 1
        r = results[0]
        assert "doc_id" in r
        assert "title" in r
        assert "page_number" in r
        assert "text" in r
        assert "snippet" in r

    def test_result_joins_document_title(self, test_db):
        """Results include the document title from the documents table."""
        results = search_pages(test_db, ["Gulfstream"])
        assert len(results) == 1
        assert results[0]["title"] == "Flight Manifest July 2019"
        assert results[0]["doc_id"] == "doc-travel-001"
        assert results[0]["page_number"] == 1

    def test_max_results_per_query(self, test_db):
        """max_results_per_query limits results per individual query."""
        results = search_pages(test_db, ["wire OR transfer OR Miami"], max_results_per_query=2)
        # With limit of 2, we should get at most 2 results from this query
        assert len(results) <= 2

    def test_text_truncated_at_2000(self, test_db):
        """Result text is capped at 2000 characters."""
        results = search_pages(test_db, ["wire"])
        for r in results:
            assert len(r["text"]) <= 2000

    def test_cross_document_search(self, test_db):
        """A query matching multiple documents returns results from all of them."""
        # "wire transfer" appears in both finance and legal documents
        results = search_pages(test_db, ['"wire transfer"'])
        doc_ids = {r["doc_id"] for r in results}
        assert "doc-finance-001" in doc_ids
        assert "doc-legal-001" in doc_ids

    def test_page_number_accuracy(self, test_db):
        """Returned page numbers match the actual page where content appears."""
        results = search_pages(test_db, ["SWIFT code"])
        assert len(results) == 1
        assert results[0]["page_number"] == 2  # SWIFT code is on page 2

    def test_fts5_phrase_query(self, test_db):
        """FTS5 phrase queries (quoted) work correctly."""
        results = search_pages(test_db, ['"no recollection"'])
        assert len(results) >= 1
        assert any("recollection" in r["text"] for r in results)

    def test_fts5_boolean_and(self, test_db):
        """FTS5 AND queries work correctly."""
        results = search_pages(test_db, ["deposition AND Wilson"])
        assert len(results) >= 1
        assert all("doc-legal-001" == r["doc_id"] for r in results)

    def test_empty_queries_list(self, test_db):
        """An empty queries list returns no results."""
        results = search_pages(test_db, [])
        assert results == []


# ---------------------------------------------------------------------------
# _parse_queries() tests
# ---------------------------------------------------------------------------


class TestParseQueries:
    def test_valid_json_array(self):
        """Parses a clean JSON array of strings."""
        response = '["wire transfer", "bank account", "Miami"]'
        assert _parse_queries(response) == ["wire transfer", "bank account", "Miami"]

    def test_json_in_code_fences(self):
        """Parses JSON wrapped in markdown code fences."""
        response = '```json\n["wire transfer", "bank account"]\n```'
        assert _parse_queries(response) == ["wire transfer", "bank account"]

    def test_json_in_plain_code_fences(self):
        """Parses JSON wrapped in plain code fences (no language tag)."""
        response = '```\n["query one", "query two"]\n```'
        assert _parse_queries(response) == ["query one", "query two"]

    def test_empty_array(self):
        """Returns empty list for an empty JSON array."""
        assert _parse_queries("[]") == []

    def test_invalid_json(self):
        """Returns empty list for unparseable responses."""
        assert _parse_queries("This is not JSON at all") == []

    def test_non_array_json(self):
        """Returns empty list if JSON is not an array."""
        assert _parse_queries('{"query": "test"}') == []

    def test_filters_empty_strings(self):
        """Filters out empty strings from the result."""
        response = '["valid query", "", "another query"]'
        result = _parse_queries(response)
        assert "" not in result
        assert len(result) == 2

    def test_whitespace_around_json(self):
        """Handles whitespace around the JSON."""
        response = '  \n  ["query"]  \n  '
        assert _parse_queries(response) == ["query"]


# ---------------------------------------------------------------------------
# Prompt formatting tests
# ---------------------------------------------------------------------------


class TestPromptFormatting:
    def test_query_planner_prompt_substitution(self):
        """QUERY_PLANNER_PROMPT correctly substitutes the question."""
        question = "What wire transfers exceeded $100,000?"
        prompt = QUERY_PLANNER_PROMPT.format(question=question)
        assert question in prompt
        assert "FTS5" in prompt
        assert "JSON array" in prompt

    def test_answer_prompt_substitution(self):
        """ANSWER_PROMPT correctly substitutes evidence and question."""
        evidence = "### Doc Title [DOC-001, page 1]\nSome evidence text."
        question = "What happened?"
        prompt = ANSWER_PROMPT.format(evidence=evidence, question=question)
        assert evidence in prompt
        assert question in prompt
        assert "[DOC-ID, page N]" in prompt

    def test_answer_prompt_multi_evidence(self):
        """ANSWER_PROMPT handles multiple evidence blocks."""
        blocks = [
            "### Doc A [DOC-A, page 1]\nFirst evidence.",
            "### Doc B [DOC-B, page 3]\nSecond evidence.",
        ]
        evidence = "\n\n".join(blocks)
        prompt = ANSWER_PROMPT.format(evidence=evidence, question="test?")
        assert "DOC-A" in prompt
        assert "DOC-B" in prompt
        assert "page 3" in prompt


# ---------------------------------------------------------------------------
# call_llm() tests
# ---------------------------------------------------------------------------


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self):
        """call_llm raises ValueError when no API key is provided."""
        # Ensure env var is not set
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No API key"):
                await call_llm("test prompt")

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """call_llm returns the LLM response content."""
        mock_response = {
            "choices": [{"message": {"content": "Test answer"}}]
        }

        # httpx Response methods (raise_for_status, json) are synchronous,
        # so use MagicMock for the response object.
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("casestack.ask.httpx.AsyncClient", return_value=mock_client):
            result = await call_llm("test prompt", api_key="test-key")
            assert result == "Test answer"

    @pytest.mark.asyncio
    async def test_falls_back_to_next_model(self):
        """call_llm tries the next model when the first fails."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First model failed")
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "Fallback answer"}}]
            }
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post

        with patch("casestack.ask.httpx.AsyncClient", return_value=mock_client):
            result = await call_llm("test prompt", api_key="test-key")
            assert result == "Fallback answer"
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_models_fail_raises(self):
        """call_llm raises RuntimeError when all models fail."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("API error"))

        with patch("casestack.ask.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="All LLM providers failed"):
                await call_llm("test prompt", api_key="test-key")


# ---------------------------------------------------------------------------
# Full ask() pipeline tests (mocked LLM)
# ---------------------------------------------------------------------------


class TestAskPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, test_db):
        """Full ask pipeline: planner -> search -> synthesize."""
        call_count = 0

        async def mock_llm(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Query planner response
                return '["wire transfer", "$500,000"]'
            else:
                # Answer synthesis response
                return (
                    "A wire transfer of $500,000 was sent from Account A to Account B "
                    "[doc-finance-001, page 1]. The beneficiary bank was First National "
                    "Bank of Miami [doc-finance-001, page 2]."
                )

        with patch("casestack.ask.call_llm", side_effect=mock_llm):
            answer = await ask("What wire transfers were made?", test_db, api_key="test")
            assert "wire transfer" in answer.lower() or "$500,000" in answer
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_results_returns_message(self, test_db):
        """ask returns a helpful message when no documents match."""

        async def mock_llm(prompt, **kwargs):
            return '["xyznonexistent123"]'

        with patch("casestack.ask.call_llm", side_effect=mock_llm):
            answer = await ask("Tell me about xyznonexistent123", test_db, api_key="test")
            assert "No relevant documents found" in answer

    @pytest.mark.asyncio
    async def test_planner_returns_garbage_falls_back(self, test_db):
        """When the planner returns unparseable JSON, falls back to raw question."""
        call_count = 0

        async def mock_llm(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return garbage for planner
                return "I cannot generate queries right now."
            else:
                # Answer synthesis
                return "Based on the evidence, Miami is mentioned in the flight manifest."

        with patch("casestack.ask.call_llm", side_effect=mock_llm):
            answer = await ask("Miami", test_db, api_key="test")
            # Should still get an answer because fallback to raw question works
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_evidence_formatting(self, test_db):
        """Verify that search results are correctly formatted as evidence blocks."""
        captured_prompts = []

        async def mock_llm(prompt, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return '["Gulfstream"]'
            else:
                return "The aircraft was a Gulfstream G550 [doc-travel-001, page 1]."

        with patch("casestack.ask.call_llm", side_effect=mock_llm):
            await ask("What aircraft was used?", test_db, api_key="test")
            # The second prompt (answer synthesis) should contain formatted evidence
            answer_prompt = captured_prompts[1]
            assert "Flight Manifest July 2019" in answer_prompt
            assert "doc-travel-001" in answer_prompt
            assert "page 1" in answer_prompt
            assert "Gulfstream G550" in answer_prompt


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestAskCLI:
    def test_ask_command_exists(self):
        """The 'ask' command is registered in the CLI group."""
        from casestack.cli import cli

        commands = cli.commands if hasattr(cli, "commands") else {}
        assert "ask" in commands, "The 'ask' command should be registered"

    def test_ask_command_params(self):
        """The 'ask' command has the expected parameters."""
        from casestack.cli import cli

        cmd = cli.commands["ask"]
        param_names = [p.name for p in cmd.params]
        assert "question" in param_names
        assert "case_path" in param_names
        assert "api_key" in param_names

    def test_ask_command_help(self):
        """The 'ask' command has help text."""
        from casestack.cli import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["ask", "--help"])
        assert result.exit_code == 0
        assert "Ask a question" in result.output
