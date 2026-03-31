"""AI Research Assistant route with SSE streaming.

POST /api/cases/{slug}/ask — streams a RAG-based answer as Server-Sent Events.

SSE event types:
  - status:  progress messages (searching, generating, etc.)
  - token:   individual text tokens from the LLM
  - done:    final event with source citations and conversation_id
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

from casestack.api.deps import get_app_state, get_case_db

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None


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

CRITICAL RULES:
1. Always preserve proper nouns exactly as given (person names, organization names, place names, job titles).
   Include at least one query that searches for the person's last name or full name verbatim.
2. Include one broad keyword query and one narrow/specific query for best recall.
3. If the question mentions specific dates or numbers, include them in at least one query.
   NEVER invent or guess a date or year that does not appear verbatim in the user's question.
   For example, if the question asks "when did X happen?" with no year, do NOT add a year guess
   like "2019" or "2024" to the query — this restricts recall to one year and may miss results.
4. NEVER include page numbers (e.g. "page 110"), document IDs (e.g. "EFTA00039025"), or
   citation references in queries — the full-text index does not surface these as useful matches.
   Search for the CONTENT being sought, not the citation pointing to it.
5. If the question references prior conversation context ("as we discussed", "the prior answer cited",
   "you mentioned"), extract only the underlying factual question and search for that.
6. Keep each query SHORT — 2 to 3 key terms maximum. FTS5 treats spaces as AND operators,
   so a 5-word query requires all 5 words on the same page, which almost always returns nothing.
   Use multiple short queries instead of one long query.
7. Use prefix wildcards for words that have many forms: write recommend* instead of
   recommendation/recommend/recommended/recommends; prosecut* instead of prosecution/prosecuted;
   disciplin* instead of discipline/disciplinary/disciplined. This dramatically improves recall.
8. Always include at least one "minimum vocabulary" query: a single root word with a wildcard
   that captures the core concept. For example, for a question about "OIG recommendations",
   include "recommend*" alone or with one modifier. For "disciplinary actions", include
   "disciplin*". This ensures broad recall even when other queries are too specific.
9. When a question uses a noun derived from a verb, ALSO search the verbal form — these often
   have different roots and wildcards won't bridge them.  Key pairs to remember:
   - "payment" / "transfer" in the question → also search "paid" / "wire*"
   - "testimony" → also "testif*"
   - "arrival" / "departure" → also "arrived" / "left"
   - "recommendation" → already covered by "recommend*"
   Always generate at least one query that pairs the verbal form with another specific term.
10. For dollar amounts with commas (e.g., "$250,000"), FTS5 SPLITS on punctuation so "250,000"
    becomes tokens "250" and "000" — searching "250,000" or "250000" will FAIL. Instead search
    just the distinctive digits: "paid 250" or "250 Individual". Never include the comma in a
    numeric query.
11. For questions asking what someone DID (actions, activities performed by a person), ALSO
    generate SHORT standalone queries (WITHOUT the person's name/title) using concrete action
    verbs that appear in interview transcripts and FD-302 reports. FBI interview transcripts use
    pronouns ("he gathered", "she located") not job titles, so a query like "Captain gather*"
    will MISS those pages. Instead generate the verb phrase alone:
    - "What did the Captain do on the morning of August 10?" → also search "gathered records",
      "locate* file", "signed logbook"  (NO "Captain" in these queries)
    - "What evidence did investigators collect?" → also search "collected evidence", "seize*"
    Common action-verb fragments for investigative reports: gather*, collect*, seize*, locat*,
    retrieve*, inspect*, review*, signed logbook, gathered records.

12. For questions about legal outcomes, charges, or prosecutions, use the vocabulary of legal
    documents rather than plain English paraphrases:
    - "charged" / "indicted" / "indictment" — not "referred for criminal prosecution"
    - "nolle prosequi" — for dismissed cases
    - "deferred prosecution" — for DPA outcomes
    - "declined" — when prosecutors chose not to charge ("prosecution was declined")
    - "plea" / "pled guilty" — not "agreed to plead"
    Legal documents use precise terminology; plain-English paraphrases may not appear at all.

Return ONLY a JSON array of search query strings. No explanation.

User question: {question}"""

ANSWER_SYSTEM = """You are a research assistant analyzing a document corpus. Answer the user's question using ONLY the evidence provided. Cite every factual claim with the document ID and page number in brackets, like [DOC-ID, page N].

If the evidence doesn't contain enough information to answer, say so explicitly. Do not make claims without citations.

IMPORTANT — numerical reasoning: When the evidence provides specific timestamps or start/end times for an event (e.g., "placed at 1:40 a.m. July 23, removed at 8:45 a.m. July 24"), COMPUTE elapsed durations from those timestamps rather than accepting a rounded summary figure from another document. Timestamps from event records are more precise than narrative summaries. If a computed duration conflicts with a stated summary, report the computed value and note the discrepancy."""

ANSWER_USER = """## Evidence

{evidence}

## Question

{question}

## Answer (with citations)"""


# ---------------------------------------------------------------------------
# Search helper
# ---------------------------------------------------------------------------


def _add_adjacent_context(
    conn: sqlite3.Connection,
    results: list[dict],
    context_chars: int = 300,
) -> None:
    """Mutate each result to include tail/head text from adjacent pages.

    PDF page boundaries often split sentences mid-way.  For example, a page
    may start with "...notified by the Captain" where the first part of that
    sentence is on the previous page.  Without context, the LLM sees a
    garbled fragment.

    This fetches up to ``context_chars`` characters from the end of the
    previous page and the start of the next page for each result, prepending /
    appending them so the LLM has complete sentence context across boundaries.
    """
    for r in results:
        doc_id = r["doc_id"]
        page_num = r["page_number"]

        rows = conn.execute(
            """
            SELECT page_number, text_content FROM pages
            WHERE doc_id = ? AND page_number IN (?, ?)
            ORDER BY page_number
            """,
            (doc_id, page_num - 1, page_num + 1),
        ).fetchall()

        prev_tail = ""
        next_head = ""
        for row in rows:
            if row[0] == page_num - 1:
                prev_tail = row[1][-context_chars:].strip()
            elif row[0] == page_num + 1:
                next_head = row[1][:context_chars].strip()

        if prev_tail or next_head:
            parts = []
            if prev_tail:
                parts.append(f"[...]{prev_tail}")
            parts.append(r["text"])
            if next_head:
                parts.append(f"{next_head}[...]")
            r["text"] = "\n".join(parts)


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

    _add_adjacent_context(conn, results)
    conn.close()
    return results[:50]


def _fetch_doc_overview_pages(db_path: Path, question: str, seen: set[tuple[str, int]]) -> list[dict]:
    """When the question references a document by title/ID, fetch its first few pages.

    The FTS5 index covers page text, not document titles, so asking "what is in
    EFTA00039421?" can't retrieve that document by name alone.  This helper
    detects document-title patterns in the question (EFTA-style IDs) and
    injects the document's opening pages so the LLM has representative content.
    """
    # Match patterns like EFTA00039421, EFTA-00039421, or similar document IDs
    title_matches = re.findall(r'\bEFTA\d{8}\b', question, re.IGNORECASE)
    if not title_matches:
        return []

    conn = sqlite3.connect(str(db_path))
    extra: list[dict] = []
    for title_id in set(t.upper() for t in title_matches):
        rows = conn.execute(
            """
            SELECT d.doc_id, d.title, p.page_number, p.text_content
            FROM documents d
            JOIN pages p ON p.doc_id = d.doc_id
            WHERE d.title = ?
            ORDER BY p.page_number
            LIMIT 5
            """,
            (title_id,),
        ).fetchall()
        for row in rows:
            key = (row[0], row[2])
            if key not in seen:
                seen.add(key)
                extra.append({
                    "doc_id": row[0],
                    "title": row[1],
                    "page_number": row[2],
                    "text": row[3][:2000],
                    "snippet": row[3][:200],
                })
    conn.close()
    return extra


def _sanitize_fts5(query: str) -> str:
    """Strip characters that cause FTS5 syntax errors.

    Preserves * only when used as a valid FTS5 prefix wildcard (immediately
    following a word character, e.g. recommend*). All other * are stripped.
    """
    # Preserve prefix wildcards: word* → keep as-is
    # Strip bare * not attached to a word
    cleaned = re.sub(r'(\w)\*', r'\1__WILDCARD__', query)
    cleaned = re.sub(r'[?!;:@#$%^&*()\[\]{}<>~/\\|`]', ' ', cleaned)
    cleaned = cleaned.replace('__WILDCARD__', '*')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
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


# Maximum number of distinct source documents shown per answer.
# One chip per document (lowest-page-number hit) keeps the UI readable.
_MAX_SOURCE_DOCS = 15

# Maximum number of prior Q&A turns to include in LLM context verbatim.
# Older turns are compacted (not dropped) into a structured summary block
# that is prepended to the recent history, preserving investigative context.
# Each "turn" = 1 user message + 1 assistant message.
_MAX_HISTORY_TURNS = 6

# Max chars of each answer to include in the compacted summary.
_COMPACT_ANSWER_CHARS = 400


def _compact_history_turns(dropped: list[dict]) -> tuple[dict, dict]:
    """Compact dropped Q&A turns into a synthetic user/assistant message pair.

    Returns a (user_msg, assistant_ack) tuple to prepend to recent history so
    the LLM retains prior investigative findings without verbatim token cost.
    """
    lines = ["[Prior investigation context — earlier conversation turns condensed]\n"]
    i = 0
    while i < len(dropped) - 1:
        if dropped[i]["role"] == "user" and dropped[i + 1]["role"] == "assistant":
            q = dropped[i]["content"][:150].strip()
            a = dropped[i + 1]["content"]
            a_trimmed = a[:_COMPACT_ANSWER_CHARS].strip()
            if len(a) > _COMPACT_ANSWER_CHARS:
                a_trimmed += "..."
            lines.append(f"Q: {q}")
            lines.append(f"A: {a_trimmed}\n")
            i += 2
        else:
            i += 1
    user_msg = {"role": "user", "content": "\n".join(lines)}
    assistant_ack = {
        "role": "assistant",
        "content": "Understood. I have the prior investigation context from earlier in this conversation.",
    }
    return user_msg, assistant_ack


def _get_corpus_stats(db_path: Path) -> dict:
    """Return quick corpus statistics for no-results messaging."""
    try:
        conn = sqlite3.connect(str(db_path))
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        # Only include titles that look like real descriptions (>20 chars, not a plain ID).
        sample_titles = [
            row[0] for row in conn.execute(
                "SELECT title FROM documents WHERE LENGTH(title) > 20 ORDER BY ROWID LIMIT 6"
            ).fetchall()
        ]
        conn.close()
        return {"doc_count": doc_count, "sample_titles": sample_titles}
    except Exception:
        return {"doc_count": 0, "sample_titles": []}


def _dedupe_sources(results: list[dict]) -> list[dict]:
    """Return one source entry per unique doc_id, capped at _MAX_SOURCE_DOCS.

    FTS5 returns results ordered by rank (best match first). We keep the page
    from the FIRST occurrence per document — that's the highest-ranked passage,
    which is the most useful navigation target. Using the lowest page number
    was wrong: it navigated to cover pages instead of the relevant content.
    """
    seen: dict[str, dict] = {}
    for r in results:
        doc_id = r["doc_id"]
        if doc_id not in seen:
            seen[doc_id] = {"doc_id": doc_id, "title": r["title"], "page": r["page_number"]}
        # Do NOT update — first seen is best-ranked, keep it.
    return list(seen.values())[:_MAX_SOURCE_DOCS]


# ---------------------------------------------------------------------------
# Hybrid search: semantic (vector) + FTS5 merged via Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

# Module-level caches so the model and embeddings are loaded once per process.
_st_model = None  # sentence-transformers model instance
_emb_cache: dict[str, tuple[list[tuple[int, str, int]], "object"]] = {}  # db_path → (meta, matrix)


def _get_st_model():
    """Lazy-load the sentence-transformers model (cached after first call)."""
    global _st_model
    if _st_model is not None:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    model_name = os.environ.get(
        "CASESTACK_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    logger.info("Loading sentence-transformers model: %s", model_name)
    _st_model = SentenceTransformer(model_name, trust_remote_code=True)
    return _st_model


def _load_page_embeddings(db_path: Path):
    """Load page embeddings from DB into a numpy matrix (cached per db_path).

    Returns (page_meta, matrix) where page_meta is a list of
    (page_id, doc_id, page_number) tuples and matrix is shape (N, dims).
    Returns None if page_embeddings table is empty or numpy unavailable.
    """
    cache_key = str(db_path)
    if cache_key in _emb_cache:
        return _emb_cache[cache_key]

    try:
        import numpy as np
        import struct
    except ImportError:
        return None

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT pe.page_id, p.doc_id, p.page_number, pe.dims, pe.embedding "
            "FROM page_embeddings pe JOIN pages p ON pe.page_id = p.id"
        ).fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        conn.close()
        return None
    conn.close()

    if not rows:
        return None

    dims = rows[0][3]
    page_meta = [(r[0], r[1], r[2]) for r in rows]
    matrix = np.array(
        [np.frombuffer(r[4], dtype=np.float32) for r in rows],
        dtype=np.float32,
    )
    if matrix.shape[1] != dims:
        logger.warning("Embedding dims mismatch: expected %d got %d", dims, matrix.shape[1])
        return None

    result = (page_meta, matrix)
    _emb_cache[cache_key] = result
    logger.info("Loaded %d page embeddings (%d dims) from %s", len(rows), dims, db_path.name)
    return result


def _search_semantic(db_path: Path, query: str, top_k: int = 20) -> list[dict]:
    """Semantic similarity search over stored page embeddings.

    Returns results in the same dict format as _search_pages().
    Returns an empty list when embeddings are unavailable (graceful fallback).
    """
    loaded = _load_page_embeddings(db_path)
    if loaded is None:
        return []

    model = _get_st_model()
    if model is None:
        return []

    try:
        import numpy as np
    except ImportError:
        return []

    page_meta, matrix = loaded

    query_emb = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)
    scores = matrix @ query_emb  # cosine sim (vectors already normalized)

    top_indices = np.argsort(scores)[::-1][:top_k]

    conn = sqlite3.connect(str(db_path))
    results: list[dict] = []
    for idx in top_indices:
        sim = float(scores[idx])
        if sim < 0.25:  # minimum semantic similarity threshold
            break
        page_id, doc_id, page_number = page_meta[idx]
        row = conn.execute(
            "SELECT p.text_content, d.title "
            "FROM pages p JOIN documents d ON p.document_id = d.id "
            "WHERE p.id = ?",
            (page_id,),
        ).fetchone()
        if row:
            text, title = row
            results.append({
                "doc_id": doc_id,
                "page_number": page_number,
                "text": text,
                "snippet": text[:200],
                "title": title or doc_id,
                "score": sim,
            })
    if results:
        adj_conn = sqlite3.connect(str(db_path))
        _add_adjacent_context(adj_conn, results)
        adj_conn.close()
    return results


def _rrf_merge(
    fts_results: list[dict],
    sem_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion of FTS5 and semantic search results.

    RRF score = Σ 1/(k + rank_i).  Results that appear in both lists get
    a score boost.  Preserves page text from whichever source ranked it first.
    """
    scores: dict[tuple[str, int], float] = {}
    data: dict[tuple[str, int], dict] = {}

    for rank, r in enumerate(fts_results):
        key = (r["doc_id"], r["page_number"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        data[key] = r

    for rank, r in enumerate(sem_results):
        key = (r["doc_id"], r["page_number"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in data:
            data[key] = r

    merged_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [data[k] for k in merged_keys]


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
      1. ANTHROPIC_API_KEY  -> Anthropic Messages API
      2. OPENAI_API_KEY     -> OpenAI API
      3. OPENROUTER_API_KEY -> OpenRouter (OpenAI-compatible)
      4. OLLAMA_BASE_URL    -> Local Ollama (OpenAI-compatible)

    Returns dict with keys: provider, api_key, base_url, model
    or None if no provider is available.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        return {
            "provider": "anthropic",
            "api_key": anthropic_key,
            "base_url": "https://api.anthropic.com/v1/messages",
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        }

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        return {
            "provider": "openai",
            "api_key": openai_key,
            "base_url": "https://api.openai.com/v1/chat/completions",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key:
        return {
            "provider": "openrouter",
            "api_key": openrouter_key,
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "model": os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash-preview"),
        }

    ollama_url = os.environ.get("OLLAMA_BASE_URL", "")
    if ollama_url:
        return {
            "provider": "ollama",
            "api_key": "ollama",
            "base_url": ollama_url.rstrip("/") + "/v1/chat/completions",
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2"),
        }

    return None


# ---------------------------------------------------------------------------
# Streaming LLM calls
# ---------------------------------------------------------------------------


async def _stream_anthropic(config: dict, system: str, messages: list[dict]):
    """Stream tokens from Anthropic Messages API. messages is OpenAI-style."""
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
                "messages": messages,
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
                if data.get("type") == "content_block_delta":
                    text = data.get("delta", {}).get("text", "")
                    if text:
                        yield text


async def _stream_openai_compatible(config: dict, system: str, messages: list[dict]):
    """Stream tokens from OpenAI-compatible endpoint (OpenAI, OpenRouter, Ollama)."""
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            config["base_url"],
            headers=headers,
            json={
                "model": config["model"],
                "messages": full_messages,
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
                    text = choices[0].get("delta", {}).get("content", "")
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
            return resp.json()["content"][0]["text"]
    else:
        # OpenAI-compatible (openai, openrouter, ollama)
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
            return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------


@router.post("/cases/{slug}/ask")
async def ask_endpoint(slug: str, body: AskRequest):
    """Stream a RAG-based answer as Server-Sent Events."""
    db_path = get_case_db(slug)
    question = body.question.strip()
    app_state = get_app_state()

    if not question:
        async def error_stream():
            yield _sse("error", {"message": "Question cannot be empty."})
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    llm_config = _get_llm_config()

    # Resolve or create conversation
    conv_id = body.conversation_id
    if conv_id:
        conv = app_state.get_conversation(conv_id)
        if not conv or conv["case_slug"] != slug:
            conv_id = None  # invalid id, start fresh

    if not conv_id:
        conv = app_state.create_conversation(slug, title=question[:60])
        conv_id = conv["id"]

    # Load existing history.  If the conversation is long, compact older turns
    # into a structured summary block rather than silently discarding them —
    # this preserves investigative findings across context boundaries.
    existing_messages = app_state.get_conversation_messages(conv_id)
    max_verbatim = _MAX_HISTORY_TURNS * 2
    if len(existing_messages) > max_verbatim:
        dropped = existing_messages[:-max_verbatim]
        recent = existing_messages[-max_verbatim:]
        user_ctx, asst_ack = _compact_history_turns(dropped)
        history: list[dict] = [user_ctx, asst_ack] + [
            {"role": m["role"], "content": m["content"]} for m in recent
        ]
    else:
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in existing_messages
        ]

    # Persist the user's question immediately
    app_state.add_message(conv_id, "user", question)

    async def generate():
        full_answer = ""
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
                    logger.info("Query planner generated %d queries: %r", len(queries), queries)
                except Exception as exc:
                    logger.warning("Query planner failed: %s", exc)
                    queries = []
            else:
                queries = []

            if not queries:
                queries = [_sanitize_fts5(question)]

            # ---- Stage 2: Search documents ----
            yield _sse("status", {"message": "Searching documents..."})
            fts_results = _search_pages(db_path, queries)
            sem_results = _search_semantic(db_path, question)
            if sem_results:
                results = _rrf_merge(fts_results, sem_results)
                logger.info(
                    "Hybrid search: %d FTS5 + %d semantic → %d merged",
                    len(fts_results), len(sem_results), len(results),
                )
            else:
                results = fts_results

            # If question names specific documents by title, inject their opening pages
            seen_keys: set[tuple[str, int]] = {(r["doc_id"], r["page_number"]) for r in results}
            doc_overviews = _fetch_doc_overview_pages(db_path, question, seen_keys)
            if doc_overviews:
                results = doc_overviews + results

            if not results:
                stats = _get_corpus_stats(db_path)
                lines = ["**No matching documents found.**\n"]
                lines.append(f"Searched {stats['doc_count']} documents using {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}:")
                for q in queries:
                    lines.append(f"- `{q}`")
                lines.append("\nTry rephrasing with different keywords, or use the Search page to browse all documents.")
                no_result_msg = "\n".join(lines)
                yield _sse("token", {"text": no_result_msg})
                yield _sse("done", {"sources": [], "conversation_id": conv_id})
                app_state.add_message(conv_id, "assistant", no_result_msg, sources=[])
                return

            yield _sse("status", {"message": f"Found {len(results)} relevant passages. Generating answer..."})

            # ---- Stage 3: Synthesize answer ----
            if not llm_config:
                no_key_msg = "**Note:** No LLM API key configured. Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or `OLLAMA_BASE_URL` to enable AI answers.\n\n---\n\n"
                yield _sse("token", {"text": no_key_msg})
                full_answer = no_key_msg
                for r in results[:10]:
                    chunk = f"### {r['title']} [{r['doc_id']}, page {r['page_number']}]\n{r['snippet']}\n\n"
                    yield _sse("token", {"text": chunk})
                    full_answer += chunk
                sources = _dedupe_sources(results)
                yield _sse("done", {"sources": sources, "conversation_id": conv_id})
                app_state.add_message(conv_id, "assistant", full_answer, sources=sources)
                return

            # Build evidence context
            evidence = "\n\n".join(
                f"### {r['title']} [{r['doc_id']}, page {r['page_number']}]\n{r['text']}"
                for r in results
            )
            user_msg = ANSWER_USER.format(evidence=evidence, question=question)

            # Build messages array: history (without current Q, already included) + new user turn
            messages_for_llm = history + [{"role": "user", "content": user_msg}]

            # Stream
            if llm_config["provider"] == "anthropic":
                streamer = _stream_anthropic(llm_config, ANSWER_SYSTEM, messages_for_llm)
            else:
                streamer = _stream_openai_compatible(llm_config, ANSWER_SYSTEM, messages_for_llm)

            async for token in streamer:
                full_answer += token
                yield _sse("token", {"text": token})

            sources = _dedupe_sources(results)
            yield _sse("done", {"sources": sources, "conversation_id": conv_id})
            app_state.add_message(conv_id, "assistant", full_answer, sources=sources)

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
