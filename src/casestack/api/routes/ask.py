"""AI Research Assistant route with SSE streaming.

POST /api/cases/{slug}/ask — streams a RAG-based answer as Server-Sent Events.

SSE event types:
  - status:  progress messages (searching, generating, etc.)
  - token:   individual text tokens from the LLM
  - done:    final event with source citations
  - error:   error messages
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from casestack.api.deps import get_case_db

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


# ---------------------------------------------------------------------------
# Prompts (reused from ask.py with minor tweaks)
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

ANSWER_SYSTEM = """You are a research assistant analyzing a document corpus. Answer the user's question using ONLY the evidence provided. Cite every factual claim with the document ID and page number in brackets, like [DOC-ID, page N].

If the evidence doesn't contain enough information to answer, say so explicitly. Do not make claims without citations."""

ANSWER_USER = """## Evidence

{evidence}

## Question

{question}

## Answer (with citations)"""


# ---------------------------------------------------------------------------
# Search helper (reused from ask.py)
# ---------------------------------------------------------------------------


def _search_pages(db_path: Path, queries: list[str], max_per_query: int = 10) -> list[dict]:
    """Run FTS5 queries and return deduplicated page results."""
    conn = sqlite3.connect(str(db_path))
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()

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
                (query, max_per_query),
            ).fetchall()
            for row in rows:
                key = (row[0], row[2])
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "doc_id": row[0],
                        "title": row[1],
                        "page_number": row[2],
                        "text": row[3][:2000],
                        "snippet": row[4],
                    })
        except Exception as exc:
            logger.debug("FTS5 query failed: %r -- %s", query, exc)
            continue

    conn.close()
    return results[:50]


def _sanitize_fts5(query: str) -> str:
    """Strip characters that cause FTS5 syntax errors."""
    # Remove FTS5 operators and punctuation that breaks queries
    cleaned = re.sub(r'[?!;:@#$%^&*()\[\]{}<>~/\\|`]', ' ', query)
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Remove common stop words to improve relevance
    stop_words = {'who', 'what', 'where', 'when', 'why', 'how', 'is', 'are',
                  'was', 'were', 'the', 'a', 'an', 'in', 'on', 'at', 'to',
                  'for', 'of', 'with', 'by', 'from', 'do', 'does', 'did',
                  'can', 'could', 'would', 'should', 'this', 'that', 'it'}
    words = [w for w in cleaned.split() if w.lower() not in stop_words]
    return ' '.join(words) if words else cleaned


def _parse_queries(text: str) -> list[str]:
    """Extract a JSON array of query strings from the planner LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [_sanitize_fts5(str(q)) for q in parsed if q]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> str:
    """Format a single SSE event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# LLM provider detection
# ---------------------------------------------------------------------------


def _get_llm_config() -> dict | None:
    """Detect available LLM configuration.

    Checks (in order):
      1. ANTHROPIC_API_KEY -> Anthropic Messages API (streaming)
      2. OPENROUTER_API_KEY -> OpenRouter (OpenAI-compatible, streaming)

    Returns dict with keys: provider, api_key, base_url, model
    or None if no key is available.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        return {
            "provider": "anthropic",
            "api_key": anthropic_key,
            "base_url": "https://api.anthropic.com/v1/messages",
            "model": "claude-sonnet-4-20250514",
        }

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key:
        return {
            "provider": "openrouter",
            "api_key": openrouter_key,
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "model": "google/gemini-2.5-flash-preview",
        }

    return None


# ---------------------------------------------------------------------------
# Streaming LLM calls
# ---------------------------------------------------------------------------


async def _stream_anthropic(config: dict, system: str, user_msg: str):
    """Stream tokens from Anthropic Messages API."""
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            config["base_url"],
            headers={
                "x-api-key": config["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": config["model"],
                "max_tokens": 4096,
                "stream": True,
                "system": system,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = data.get("type", "")
                if event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        yield text


async def _stream_openrouter(config: dict, system: str, user_msg: str):
    """Stream tokens from OpenRouter (OpenAI-compatible)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_msg})

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            config["base_url"],
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["model"],
                "messages": messages,
                "max_tokens": 4096,
                "stream": True,
            },
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text


async def _call_llm_non_streaming(config: dict, prompt: str) -> str:
    """Non-streaming LLM call for query planning."""
    if config["provider"] == "anthropic":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                config["base_url"],
                headers={
                    "x-api-key": config["api_key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config["model"],
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
    else:
        # OpenRouter / OpenAI-compatible
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                config["base_url"],
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------


@router.post("/cases/{slug}/ask")
async def ask_endpoint(slug: str, body: AskRequest):
    """Stream a RAG-based answer as Server-Sent Events."""
    db_path = get_case_db(slug)
    question = body.question.strip()

    if not question:
        async def error_stream():
            yield _sse("error", {"message": "Question cannot be empty."})

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    llm_config = _get_llm_config()

    async def generate():
        try:
            # ---- Stage 1: Generate search queries ----
            yield _sse("status", {"message": "Planning search queries..."})

            if llm_config:
                try:
                    planner_response = await _call_llm_non_streaming(
                        llm_config,
                        QUERY_PLANNER_PROMPT.format(question=question),
                    )
                    queries = _parse_queries(planner_response)
                except Exception as exc:
                    logger.warning("Query planner failed: %s", exc)
                    queries = []
            else:
                queries = []

            if not queries:
                # Fallback: use sanitized question words
                queries = [_sanitize_fts5(question)]

            # ---- Stage 2: Search documents ----
            yield _sse("status", {"message": "Searching documents..."})

            results = _search_pages(db_path, queries)

            if not results:
                yield _sse("token", {"text": "No relevant documents found for this question. Try rephrasing your query or using different keywords."})
                yield _sse("done", {"sources": []})
                return

            yield _sse("status", {"message": f"Found {len(results)} relevant passages. Generating answer..."})

            # ---- Stage 3: Synthesize answer ----
            if not llm_config:
                # No API key: return search results as plain text
                yield _sse("token", {"text": "**Note:** No LLM API key configured. Showing raw search results instead.\n\n"})
                yield _sse("token", {"text": "Set `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` environment variable to enable AI-powered answers.\n\n---\n\n"})
                for r in results[:10]:
                    yield _sse("token", {"text": f"### {r['title']} [{r['doc_id']}, page {r['page_number']}]\n"})
                    yield _sse("token", {"text": f"{r['snippet']}\n\n"})
                sources = [
                    {"doc_id": r["doc_id"], "title": r["title"], "page": r["page_number"]}
                    for r in results[:10]
                ]
                yield _sse("done", {"sources": sources})
                return

            # Build evidence context
            evidence = "\n\n".join(
                f"### {r['title']} [{r['doc_id']}, page {r['page_number']}]\n{r['text']}"
                for r in results
            )

            user_msg = ANSWER_USER.format(evidence=evidence, question=question)

            # Stream the answer
            streamer = (
                _stream_anthropic if llm_config["provider"] == "anthropic"
                else _stream_openrouter
            )

            async for token in streamer(llm_config, ANSWER_SYSTEM, user_msg):
                yield _sse("token", {"text": token})

            # Send sources
            sources = [
                {"doc_id": r["doc_id"], "title": r["title"], "page": r["page_number"]}
                for r in results
            ]
            yield _sse("done", {"sources": sources})

        except httpx.HTTPStatusError as exc:
            logger.error("LLM API error: %s", exc)
            yield _sse("error", {"message": f"LLM API error: {exc.response.status_code}"})
        except Exception as exc:
            logger.error("Ask error: %s", exc, exc_info=True)
            yield _sse("error", {"message": f"An error occurred: {str(exc)}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
