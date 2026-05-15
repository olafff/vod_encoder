#!/usr/bin/env python3
"""
VOD Encoder API + frontend server.

  python api.py

Serves the web UI at http://<host>:8000 and the REST API at /api/*.
Run one instance anywhere on the network; workers are separate processes.
"""

import io
import os

import logging
import uvicorn

logging.getLogger("paramiko").setLevel(logging.WARNING)
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import job_manager
from sftp_manager import sftp_connection

app = FastAPI(title="VOD Encoder", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


# ── Jobs ───────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def get_jobs():
    return job_manager.list_jobs()


class JobIn(BaseModel):
    input_file: str
    preset: str
    output_name: str | None = None
    priority: int = 5
    custom_args: list | None = None
    assigned_to: str | None = None
    output_path: str | None = None


@app.post("/api/jobs", status_code=201)
def add_job(body: JobIn):
    if body.preset not in config.PRESETS and body.preset != "custom" and not body.custom_args:
        raise HTTPException(400, f"Unknown preset '{body.preset}'. "
                                 f"Available: {list(config.PRESETS.keys())} or 'custom'")
    existing = job_manager.list_jobs()
    for j in existing:
        if j.get("input_file") == body.input_file and j.get("status") in ("queue", "processing", "completed"):
            raise HTTPException(409, f"A job for this input file already exists (id={j['id']}, status={j['status']})")
    return job_manager.create_job(
        input_file=body.input_file,
        preset=body.preset,
        output_name=body.output_name,
        priority=max(1, min(10, body.priority)),
        custom_args=body.custom_args,
        assigned_to=body.assigned_to,
        output_path=body.output_path,
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str):
    if not job_manager.delete_job(job_id):
        raise HTTPException(404, "Job not found (only queued or failed jobs can be deleted)")
    return {"ok": True}


# ── Workers ────────────────────────────────────────────────────────────────────

@app.get("/api/workers")
def get_workers():
    return job_manager.list_workers()


# ── Presets ────────────────────────────────────────────────────────────────────

@app.get("/api/presets")
def get_presets():
    return {k: {"description": v["description"], "ext": v["ext"]}
            for k, v in config.PRESETS.items()}


# ── Files ──────────────────────────────────────────────────────────────────────

@app.get("/api/files")
def list_input_files():
    with sftp_connection() as sftp:
        path = f"{config.SFTP_BASE_PATH}/input"
        try:
            attrs = sftp.listdir_attr(path)
            return [
                {"name": a.filename, "size": a.st_size, "modified": a.st_mtime}
                for a in attrs
                if not a.filename.startswith(".")
            ]
        except Exception:
            return []


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = os.path.basename(file.filename or "upload").replace(" ", "_")
    if not filename:
        raise HTTPException(400, "Invalid filename")

    content = await file.read()
    remote_path = f"{config.SFTP_BASE_PATH}/input/{filename}"

    def do_upload():
        with sftp_connection() as sftp:
            sftp.putfo(io.BytesIO(content), remote_path)

    await run_in_threadpool(do_upload)
    return {"filename": filename, "path": f"input/{filename}"}


if __name__ == "__main__":
    job_manager.ensure_dirs()
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
