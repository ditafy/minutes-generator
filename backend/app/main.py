from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pipeline import process_audio_to_markdown


STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@dataclass
class JobState:
    status: str = "queued"  # queued | running | success | failed
    progress: int = 0  # 0..100
    stage: str = "queued"  # stt | clean | extract | render | queued | ...
    error: Optional[str] = None
    result_markdown: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


app = FastAPI(title="Minutes Generator (Offline)")

# Serve frontend
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# In-memory job store (MVP). Later you can replace with SQLite/Redis.
JOBS: Dict[str, JobState] = {}
JOBS_LOCK = asyncio.Lock()


def _get_job(job_id: str) -> JobState:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return FileResponse(str(index_path))


@app.post("/api/v1/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    meeting_title: str = Form(""),
    meeting_date: str = Form(""),
    club_name: str = Form(""),
):
    # Minimal validation
    if not audio.filename:
        raise HTTPException(status_code=400, detail="missing audio filename")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = JobState(
        status="queued",
        progress=0,
        stage="queued",
        meta={
            "meeting_title": meeting_title or None,
            "meeting_date": meeting_date or None,
            "club_name": club_name or None,
            "audio_filename": audio.filename,
        },
    )

    # Save uploaded audio to a local temp file (offline processing).
    uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    audio_path = uploads_dir / f"{job_id}_{audio.filename}"

    with audio_path.open("wb") as f:
        shutil.copyfileobj(audio.file, f)

    async def _run():
        job = _get_job(job_id)
        try:
            job.status = "running"
            job.stage = "stt"
            job.progress = 5
            md = await process_audio_to_markdown(
                audio_path=audio_path,
                meta=job.meta,
                on_stage=lambda stage, progress: _update_job(job_id, stage, progress),
            )
            job.result_markdown = md
            job.status = "success"
            job.progress = 100
            job.stage = "done"
        except Exception as e:
            job.status = "failed"
            job.stage = "failed"
            job.error = str(e)

        # Optional cleanup (keep audio for debugging if you want)
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass

    background_tasks.add_task(_run)

    return {
        "jobId": job_id,
        "statusUrl": f"/api/v1/jobs/{job_id}",
    }


def _update_job(job_id: str, stage: str, progress: int) -> None:
    # Fire-and-forget updates from pipeline.
    job = _get_job(job_id)
    job.stage = stage
    job.progress = max(job.progress, progress)


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = _get_job(job_id)
    return {
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "meta": job.meta,
    }


@app.get("/api/v1/jobs/{job_id}/result")
async def get_job_result(job_id: str):
    job = _get_job(job_id)
    if job.status != "success" or not job.result_markdown:
        raise HTTPException(status_code=400, detail="result not ready")
    return {
        "markdown": job.result_markdown,
    }

