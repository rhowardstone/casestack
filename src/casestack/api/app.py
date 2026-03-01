"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from casestack.api.deps import get_app_state


def create_app() -> FastAPI:
    app = FastAPI(title="CaseStack", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize app state DB
    get_app_state()

    # Register API routes
    from casestack.api.routes import (
        cases, pipeline, ingest, search,
        documents, entities, images, transcripts,
        map as map_routes,
        ask,
    )
    app.include_router(cases.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(entities.router, prefix="/api")
    app.include_router(images.router, prefix="/api")
    app.include_router(transcripts.router, prefix="/api")
    app.include_router(map_routes.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")

    # Serve static frontend (if built)
    import importlib.resources
    static_dir = importlib.resources.files("casestack") / "static"
    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        from fastapi.responses import FileResponse
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            return FileResponse(str(static_dir / "index.html"))
    else:
        @app.get("/")
        async def placeholder():
            return {"status": "CaseStack API running", "frontend": "not built yet"}

    return app
