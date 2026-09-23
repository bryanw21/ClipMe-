"""ClipMee processing service.

This turns the AI-Youtube-Shorts-Generator fork into a service the ClipMee
web app can call. It intentionally accepts only URLs or file paths supplied by
the authenticated ClipMee application; source-rights validation belongs in the
web application before a job is created.
"""

from __future__ import annotations

import os
import secrets
import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from shorts_generator import generate_shorts

app = FastAPI(title="ClipMee Engine", version="0.1.0")
jobs: dict[str, dict[str, Any]] = {}


class ClipRequest(BaseModel):
    source_url: str = Field(min_length=1)
    num_clips: int = Field(default=5, ge=1, le=10)
    aspect_ratio: str = Field(default="9:16")
    mode: str = Field(default_factory=lambda: os.getenv("CLIP_ENGINE_MODE", "local"))


def authorize(key: str | None) -> None:
    required = os.getenv("CLIP_ENGINE_SHARED_SECRET")
    if required and not secrets.compare_digest(key or "", required):
        raise HTTPException(status_code=401, detail="Invalid ClipMee engine key.")


def run_job(job_id: str, request: ClipRequest) -> None:
    try:
        result = generate_shorts(
            request.source_url,
            num_clips=request.num_clips,
            aspect_ratio=request.aspect_ratio,
            mode=request.mode,
        )
        jobs[job_id] = {
            "status": "completed",
            "clips": [item.get("clip_url") for item in result.get("shorts", []) if item.get("clip_url")],
            "highlights": result.get("highlights", []),
        }
    except Exception as exc:  # Jobs must report an error instead of disappearing.
        jobs[job_id] = {"status": "failed", "error": str(exc)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "clipmee-engine"}


@app.post("/v1/clips", status_code=202)
def create_clips(request: ClipRequest, x_clipmee_service_key: str | None = Header(default=None)) -> dict[str, str]:
    authorize(x_clipmee_service_key)
    job_id = secrets.token_urlsafe(18)
    jobs[job_id] = {"status": "processing"}
    threading.Thread(target=run_job, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id, "status": "processing"}


@app.get("/v1/clips/{job_id}")
def get_clip_job(job_id: str, x_clipmee_service_key: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_clipmee_service_key)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip job not found.")
    return job
