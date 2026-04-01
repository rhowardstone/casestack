"""WebSocket endpoint for live ingest progress."""
from __future__ import annotations

import asyncio
import threading

from fastapi import WebSocket, WebSocketDisconnect

# Registry of active WebSocket connections per case slug.
# Each entry stores (websocket, event_loop) so we can safely send from threads.
_ws_connections: dict[str, list[tuple[WebSocket, asyncio.AbstractEventLoop]]] = {}
_lock = threading.Lock()


def register_ws(slug: str, ws: WebSocket, loop: asyncio.AbstractEventLoop) -> None:
    with _lock:
        _ws_connections.setdefault(slug, []).append((ws, loop))


def unregister_ws(slug: str, ws: WebSocket) -> None:
    with _lock:
        if slug in _ws_connections:
            _ws_connections[slug] = [(w, l) for w, l in _ws_connections[slug] if w is not ws]


def broadcast_event(slug: str, event_type: str, data: dict) -> None:
    """Send event to all WebSocket connections for a case (thread-safe)."""
    with _lock:
        connections = list(_ws_connections.get(slug, []))
    payload = {"type": event_type, **data}
    for ws, loop in connections:
        try:
            # Schedule send on the WebSocket's own event loop from ingest thread
            future = asyncio.run_coroutine_threadsafe(ws.send_json(payload), loop)
            future.result(timeout=2)
        except Exception:
            pass  # Connection may be closed or timed out


class WebSocketCallback:
    """IngestCallback that broadcasts events via WebSocket."""

    def __init__(self, slug: str) -> None:
        self.slug = slug

    def on_step_start(self, step_id: str, total: int) -> None:
        broadcast_event(self.slug, "step_start", {"step_id": step_id, "total": total})

    def on_step_progress(self, step_id: str, current: int, total: int) -> None:
        broadcast_event(self.slug, "step_progress", {
            "step_id": step_id, "current": current, "total": total,
        })

    def on_step_complete(self, step_id: str, stats: dict) -> None:
        broadcast_event(self.slug, "step_complete", {"step_id": step_id, "stats": stats})

    def on_log(self, message: str, level: str) -> None:
        broadcast_event(self.slug, "log", {"message": message, "level": level})

    def on_complete(self, stats: dict) -> None:
        broadcast_event(self.slug, "complete", {"stats": stats})

    def on_error(self, step_id: str, message: str) -> None:
        broadcast_event(self.slug, "error", {"step_id": step_id, "message": message})
