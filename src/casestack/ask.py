"""Ask-proxy RAG system for CaseStack.

Three-stage retrieval-augmented generation pipeline:
  1. Query Planning — LLM generates FTS5 search queries from natural language
  2. Parallel Search — Execute queries against the SQLite pages_fts index
  3. Answer Synthesis — LLM generates a cited answer from search results

The LLM does not need to "know" your documents. It just needs to read
search results and cite them.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

QUERY_PLANNER_PROMPT = """You are a search query planner for a document database that uses SQLite FTS5 full-text search.

Given a user question, generate 2-5 FTS5 search queries that would find relevant documents.

FTS5 syntax:
- Quoted phrases: "wire transfer"
- Boolean: term1 AND term2, term1 OR term2
- Prefix: bank*
- Negation: NOT term

Return ONLY a JSON array of search query strings. No explanation.

User question: {question}"""

ANSWER_PROMPT = """You are a research assistant analyzing a document corpus. Answer the user's question using ONLY the evidence provided below. Cite every factual claim with the document ID and page number in brackets, like [DOC-ID, page N].

If the evidence doesn't contain enough information to answer, say so explicitly. Do not make claims without citations.

## Evidence

{evidence}

## Question

{question}

## Answer (with citations)"""

# ---------------------------------------------------------------------------
# LLM integration
# ---------------------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS = [
    "google/gemini-2.5-flash-preview",
    "meta-llama/llama-3.3-70b-instruct:free",
]


async def call_llm(
    prompt: str,
    system: str = "",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """Call an LLM via OpenRouter or any OpenAI-compatible API.

    Parameters
    ----------
    prompt:
        The user message to send.
    system:
        Optional system prompt.
    api_key:
        API key. Falls back to OPENROUTER_API_KEY env var.
    base_url:
        Override the API base URL (for OpenAI-compatible APIs).
    model:
        Override the model name. If set, only this model is tried.

    Returns
    -------
    str
        The LLM response text.

    Raises
    ------
    ValueError
        If no API key is provided.
    RuntimeError
        If all LLM providers fail.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ValueError("No API key. Set OPENROUTER_API_KEY or pass --api-key")

    url = base_url or OPENROUTER_URL
    models = [model] if model else OPENROUTER_MODELS

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error: Exception | None = None
    for m in models:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": m,
                        "messages": messages,
                        "max_tokens": 2000,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("LLM call failed for model %s: %s", m, exc)
            last_error = exc
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


# ---------------------------------------------------------------------------
# Stage 2: Search
# ---------------------------------------------------------------------------


def search_pages(
    db_path: Path,
    queries: list[str],
    max_results_per_query: int = 10,
) -> list[dict]:
    """Run FTS5 queries and return deduplicated page results.

    Parameters
    ----------
    db_path:
        Path to the CaseStack SQLite database.
    queries:
        List of FTS5 query strings.
    max_results_per_query:
        Maximum results per individual query.

    Returns
    -------
    list[dict]
        Deduplicated page results with doc_id, title, page_number, text, snippet.
    """
    conn = sqlite3.connect(str(db_path))
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()  # (doc_id, page_number) for dedup

    for query in queries:
        if not query or not query.strip():
            continue
        try:
            rows = conn.execute(
                """
                SELECT d.doc_id, d.title, p.page_number, p.text_content,
                       snippet(pages_fts, 0, '**', '**', '...', 64) as snippet
                FROM pages_fts
                JOIN pages p ON p.id = pages_fts.rowid
                JOIN documents d ON d.id = p.document_id
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, max_results_per_query),
            ).fetchall()

            for row in rows:
                key = (row[0], row[2])  # (doc_id, page_number)
                if key not in seen:
                    seen.add(key)
                    results.append(
                        {
                            "doc_id": row[0],
                            "title": row[1],
                            "page_number": row[2],
                            "text": row[3][:2000],  # Cap context size
                            "snippet": row[4],
                        }
                    )
        except Exception as exc:
            logger.debug("FTS5 query failed: %r — %s", query, exc)
            continue  # Skip malformed queries

    conn.close()
    return results[:50]  # Cap total results


# ---------------------------------------------------------------------------
# Stage 1 + 3: Full RAG pipeline
# ---------------------------------------------------------------------------


def _parse_queries(planner_response: str) -> list[str]:
    """Extract a JSON array of query strings from the planner LLM response.

    Handles cases where the LLM wraps the JSON in markdown code fences.
    """
    text = planner_response.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (the fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(q) for q in parsed if q]
        return []
    except (json.JSONDecodeError, TypeError):
        logger.warning("Could not parse query planner response: %s", text[:200])
        return []


async def ask(
    question: str,
    db_path: Path,
    api_key: str | None = None,
) -> str:
    """Ask a question about the document corpus. Returns a cited answer.

    This is the main entry point for the RAG pipeline:
      1. An LLM generates FTS5 search queries from the question
      2. The queries are executed against the database
      3. Search results are injected into a prompt and the LLM synthesizes a cited answer

    Parameters
    ----------
    question:
        The natural language question to answer.
    db_path:
        Path to the CaseStack SQLite database.
    api_key:
        Optional API key for the LLM provider.

    Returns
    -------
    str
        The LLM-generated answer with citations, or an error message.
    """
    # Stage 1: Generate search queries
    planner_response = await call_llm(
        QUERY_PLANNER_PROMPT.format(question=question),
        api_key=api_key,
    )
    queries = _parse_queries(planner_response)

    if not queries:
        # Fallback: use the raw question as a simple FTS5 query
        logger.info("Query planner returned no queries, falling back to raw question")
        queries = [question]

    # Stage 2: Search
    results = search_pages(db_path, queries)
    if not results:
        return "No relevant documents found for this question."

    # Stage 3: Synthesize answer
    evidence = "\n\n".join(
        f"### {r['title']} [{r['doc_id']}, page {r['page_number']}]\n{r['text']}"
        for r in results
    )
    answer = await call_llm(
        ANSWER_PROMPT.format(evidence=evidence, question=question),
        api_key=api_key,
    )
    return answer
