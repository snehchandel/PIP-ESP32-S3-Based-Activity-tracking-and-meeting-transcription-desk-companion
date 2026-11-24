"""PIP host service entrypoint: FastAPI on 127.0.0.1:18421 (REST + WebSocket + desktop UI)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import routes_ai, routes_alarms, routes_core, routes_more, routes_settings
from .config import ROOT, Settings, get_settings
from .services import Services

UI_DIST = ROOT / "host" / "desktop_ui" / "dist"


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svcs = services or Services(settings)
        app.state.services = svcs
        await svcs.start()
        try:
            yield
        finally:
            await svcs.stop()

    app = FastAPI(title="PIP Host Service", version="1.0.0", lifespan=lifespan)
    app.include_router(routes_core.router)
    app.include_router(routes_more.router)
    app.include_router(routes_alarms.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_ai.router)

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await app.state.services.hub.serve(ws)

    if (UI_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False, response_model=None)
        def spa(path: str) -> FileResponse | JSONResponse:
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (UI_DIST / path).resolve()
            if path and candidate.is_file() and UI_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")  # client-side routes

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = get_settings()
    Path(s.pip_db_path).parent.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(s), host="127.0.0.1", port=s.pip_host_port, log_level="info")


if __name__ == "__main__":
    main()
