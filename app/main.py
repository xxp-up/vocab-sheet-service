from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import router


app = FastAPI(
    title="Vocab Sheet Service",
    version="0.1.0",
    summary="Extract vocabulary from teaching materials and fill Excel templates.",
)
app.include_router(router)
app.mount("/assets", StaticFiles(directory=Path(__file__).resolve().parent / "web" / "assets"), name="assets")


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
