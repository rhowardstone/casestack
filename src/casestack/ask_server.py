"""HTTP endpoint for the CaseStack ask-proxy.

A simple ASGI app (Starlette) that exposes /api/ask for the web UI
and /api/health for availability probes.

Usage::

    from casestack.ask_server import create_ask_app

    app = create_ask_app(db_path=Path("output/case/case.db"))
    # Run with: uvicorn casestack.ask_server:app

Requires ``starlette`` (optional dependency — not required for the CLI).
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health_endpoint(request: Request) -> JSONResponse:
    """Lightweight probe — no LLM calls, no DB queries."""
    return JSONResponse({"status": "ok"})


async def ask_endpoint(request: Request) -> JSONResponse:
    """Handle GET /api/ask?q=<question> or POST /api/ask with JSON body."""
    if request.method == "POST":
        try:
            body = await request.json()
            question = body.get("q", "").strip()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    else:
        question = request.query_params.get("q", "").strip()

    if not question:
        return JSONResponse(
            {"error": "Missing ?q= parameter"},
            status_code=400,
        )

    db_path: Path = request.app.state.db_path
    api_key: str | None = request.app.state.api_key

    from casestack.ask import ask

    try:
        answer = await ask(question, db_path, api_key=api_key)
        return JSONResponse({"question": question, "answer": answer})
    except ValueError as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=400,
        )
    except RuntimeError as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=502,
        )


def create_ask_app(
    db_path: Path,
    api_key: str | None = None,
    allowed_origins: list[str] | None = None,
) -> Starlette:
    """Create a Starlette ASGI app with /api/ask and /api/health endpoints.

    Parameters
    ----------
    db_path:
        Path to the CaseStack SQLite database.
    api_key:
        Optional API key for the LLM provider.
    allowed_origins:
        CORS origins to allow.  Defaults to ``["*"]`` (any origin)
        which is safe here because the ask endpoint is read-only and
        auth is handled via the API key, not cookies.
    """
    if allowed_origins is None:
        allowed_origins = ["*"]

    app = Starlette(
        routes=[
            Route("/api/health", health_endpoint),
            Route("/api/ask", ask_endpoint, methods=["GET", "POST"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
            ),
        ],
    )
    app.state.db_path = db_path
    app.state.api_key = api_key
    return app
