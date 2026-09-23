from .workspace import CODE_ROOT
"""Local workstation API; retired demo and plugin routes are deliberately absent."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, contextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .helper_api import router as helper_router
from .library_tools_api import router as library_tools_router
from .preparation_api import router as preparation_router
from .sample_api import router as sample_router
from .sound_api import router as sound_router
from .ui_api import router as ui_router
from .workspace import DATA, ROOT, connect

_last_user_activity = time.monotonic()


@asynccontextmanager
async def lifespan(app):
    async def maintain():
        from .cache_storage import automatic_maintenance

        last = 0.0
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            if now - _last_user_activity >= 300 and now - last >= 3600:
                last = now
                try:
                    await asyncio.to_thread(automatic_maintenance)
                except Exception:
                    logging.getLogger(__name__).exception("Idle cache maintenance skipped")

    task = asyncio.create_task(maintain())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="OttoSmasher", version="0.12.0", lifespan=lifespan)
for router in (
    helper_router,
    preparation_router,
    sample_router,
    ui_router,
    library_tools_router,
    sound_router,
):
    app.include_router(router)
if (CODE_ROOT / "desktop/dist").is_dir():
    app.mount("/helper", StaticFiles(directory=CODE_ROOT / "desktop/dist", html=True), name="helper")


@app.get("/")
def index():
    return RedirectResponse("/helper/?view=library")


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Prevent browser-based cross-origin writes and DNS-rebinding to a local media service.
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse({"detail": "Local access only"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in {
        f"http://{request.headers.get('host')}",
        f"https://{request.headers.get('host')}",
    }:
        return JSONResponse({"detail": "Cross-origin access denied"}, status_code=403)
    global _last_user_activity
    # Any active client conservatively delays eviction, including GUI polling.
    _last_user_activity = time.monotonic()
    response = await call_next(request)
    if request.url.path.rstrip("/") in {"/helper", "/helper/index.html"}:
        response.headers["Cache-Control"] = "no-store"
    return response


@contextmanager
def database():
    db = connect()
    try:
        yield db
    finally:
        db.close()


@app.exception_handler(OSError)
@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/previews/{preview_id}.wav")
def preview_audio(preview_id: str):
    import re

    if not re.fullmatch("[a-f0-9]{24}", preview_id):
        raise ValueError("Invalid preview identifier")
    path = DATA / "previews" / f"{preview_id}.wav"
    if not path.is_file():
        raise ValueError("Preview expired; render again")
    return FileResponse(path, media_type="audio/wav")
