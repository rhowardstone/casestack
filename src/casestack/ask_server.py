"""HTTP endpoint for the CaseStack ask-proxy.

A simple ASGI app (Starlette) that exposes /api/ask for the web UI.
Can run alongside Datasette or be mounted as a sub-application.

Usage::

    from casestack.ask_server import create_ask_app

    app = create_ask_app(db_path=Path("output/case/case.db"))
    # Run with: uvicorn casestack.ask_server:app

Requires ``starlette`` (optional dependency — not required for the CLI).
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def ask_endpoint(request: Request) -> JSONResponse:
    """Handle GET /api/ask?q=<question>."""
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
) -> Starlette:
    """Create a Starlette ASGI app with the /api/ask endpoint.

    Parameters
    ----------
    db_path:
        Path to the CaseStack SQLite database.
    api_key:
        Optional API key for the LLM provider.

    Returns
    -------
    Starlette
        An ASGI application ready to be served.
    """
    app = Starlette(
        routes=[Route("/api/ask", ask_endpoint)],
    )
    app.state.db_path = db_path
    app.state.api_key = api_key
    return app
