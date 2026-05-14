import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sftp_manager import sftp_connection
import config

SUBDIRS = ["queue", "processing", "completed", "failed", "input", "output", "workers"]


def ensure_dirs():
    with sftp_connection() as sftp:
        for sub in SUBDIRS:
            path = f"{config.SFTP_BASE_PATH}/{sub}"
            try:
                sftp.stat(path)
            except Exception:
                try:
                    sftp.mkdir(path)
                except Exception:
                    pass


# ── low-level helpers ──────────────────────────────────────────────────────────

def _read(sftp, path: str) -> dict:
    with sftp.open(path, "r") as f:
        return json.load(f)


def _write(sftp, path: str, data: dict):
    blob = json.dumps(data, indent=2).encode()
    with sftp.open(path, "wb") as f:
        f.write(blob)


# ── public API ─────────────────────────────────────────────────────────────────

def list_jobs() -> list[dict]:
    jobs = []
    with sftp_connection() as sftp:
        for status in ("queue", "processing", "completed", "failed"):
            dir_path = f"{config.SFTP_BASE_PATH}/{status}"
            try:
                names = sftp.listdir(dir_path)
            except Exception:
                continue
            for name in names:
                if not name.endswith(".json"):
                    continue
                try:
                    job = _read(sftp, f"{dir_path}/{name}")
                    job["status"] = status
                    jobs.append(job)
                except Exception:
                    pass
    return jobs


def create_job(
    input_file: str,
    preset: str,
    output_name: Optional[str] = None,
    priority: int = 5,
    custom_args: Optional[list] = None,
    assigned_to: Optional[str] = None,
    output_path: Optional[str] = None,
) -> dict:
    job_id = str(uuid.uuid4())
    base_name = input_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    job = {
        "id": job_id,
        "input_file": input_file,
        "preset": preset,
        "output_name": output_name or f"{base_name}_{preset}",
        "output_path": output_path,
        "custom_args": custom_args,
        "priority": priority,
        "assigned_to": assigned_to,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
        "worker_id": None,
        "progress": 0,
        "output_file": None,
        "error": None,
    }
    with sftp_connection() as sftp:
        _write(sftp, f"{config.SFTP_BASE_PATH}/queue/{job_id}.json", job)
    return job


def get_job(job_id: str) -> Optional[dict]:
    with sftp_connection() as sftp:
        for status in ("queue", "processing", "completed", "failed"):
            path = f"{config.SFTP_BASE_PATH}/{status}/{job_id}.json"
            try:
                sftp.stat(path)
                job = _read(sftp, path)
                job["status"] = status
                return job
            except Exception:
                pass
    return None


def delete_job(job_id: str) -> bool:
    """Delete a job from queue or failed (not from processing/completed)."""
    with sftp_connection() as sftp:
        for status in ("queue", "failed"):
            path = f"{config.SFTP_BASE_PATH}/{status}/{job_id}.json"
            try:
                sftp.stat(path)
                sftp.remove(path)
                return True
            except Exception:
                pass
    return False


def claim_next_job(worker_id: str) -> Optional[dict]:
    """Atomically claim the highest-priority available job."""
    with sftp_connection() as sftp:
        queue_dir = f"{config.SFTP_BASE_PATH}/queue"
        try:
            names = sftp.listdir(queue_dir)
        except Exception:
            return None

        candidates = []
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                job = _read(sftp, f"{queue_dir}/{name}")
            except Exception:
                continue
            if job.get("assigned_to") in (None, "", worker_id):
                candidates.append(job)

        if not candidates:
            return None

        candidates.sort(key=lambda j: (-j.get("priority", 5), j.get("created_at", "")))

        for job in candidates:
            src = f"{queue_dir}/{job['id']}.json"
            dst = f"{config.SFTP_BASE_PATH}/processing/{job['id']}.json"
            try:
                sftp.rename(src, dst)  # atomic on POSIX SFTP servers
            except Exception:
                continue  # another worker claimed it first

            job["worker_id"] = worker_id
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            job["progress"] = 0
            _write(sftp, dst, job)
            return job

    return None


def update_progress(job_id: str, progress: int):
    with sftp_connection() as sftp:
        path = f"{config.SFTP_BASE_PATH}/processing/{job_id}.json"
        try:
            job = _read(sftp, path)
            job["progress"] = progress
            _write(sftp, path, job)
        except Exception:
            pass


def complete_job(job_id: str, output_file: str):
    with sftp_connection() as sftp:
        src = f"{config.SFTP_BASE_PATH}/processing/{job_id}.json"
        dst = f"{config.SFTP_BASE_PATH}/completed/{job_id}.json"
        job = _read(sftp, src)
        job["progress"] = 100
        job["output_file"] = output_file
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write(sftp, src, job)
        sftp.rename(src, dst)


def fail_job(job_id: str, error: str):
    with sftp_connection() as sftp:
        src = f"{config.SFTP_BASE_PATH}/processing/{job_id}.json"
        dst = f"{config.SFTP_BASE_PATH}/failed/{job_id}.json"
        try:
            job = _read(sftp, src)
        except Exception:
            return
        job["error"] = error
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write(sftp, src, job)
        sftp.rename(src, dst)


def register_worker(worker_id: str, hostname: str, capabilities: dict):
    info = {
        "id": worker_id,
        "hostname": hostname,
        "capabilities": capabilities,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "current_job": None,
    }
    with sftp_connection() as sftp:
        _write(sftp, f"{config.SFTP_BASE_PATH}/workers/{worker_id}.json", info)


def heartbeat(worker_id: str, current_job: Optional[str] = None):
    with sftp_connection() as sftp:
        path = f"{config.SFTP_BASE_PATH}/workers/{worker_id}.json"
        try:
            info = _read(sftp, path)
        except Exception:
            info = {"id": worker_id}
        info["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        info["current_job"] = current_job
        _write(sftp, path, info)


def list_workers() -> list[dict]:
    workers = []
    with sftp_connection() as sftp:
        path = f"{config.SFTP_BASE_PATH}/workers"
        try:
            names = sftp.listdir(path)
        except Exception:
            return workers
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                w = _read(sftp, f"{path}/{name}")
            except Exception:
                continue
            try:
                last_hb = datetime.fromisoformat(w["last_heartbeat"])
                age = (datetime.now(timezone.utc) - last_hb).total_seconds()
                w["alive"] = age < config.WORKER_TIMEOUT
            except Exception:
                w["alive"] = False
            workers.append(w)
    return workers
