"""Thin FastAPI application exposing workflow job/run endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.assets import router as assets_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.runs import router as runs_router

app = FastAPI(title="paper2slides API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health endpoint for local development checks."""
    return {"status": "ok"}


app.include_router(jobs_router)
app.include_router(runs_router)
app.include_router(artifacts_router)
app.include_router(assets_router)
