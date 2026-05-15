#!/usr/bin/env python3
"""
VOD Encoder Worker — run this on any machine that should encode jobs.

  python worker.py

Authentication: set VOD_SFTP_PASSWORD or ensure your SSH key is in ~/.ssh/.
See .env.example for all configuration options.
"""

import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

import psutil

import config
import job_manager
import encoder
import sysinfo
from sftp_manager import sftp_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("paramiko").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

def _stable_id() -> str:
    """Return a persistent worker ID, creating one on first run."""
    id_file = Path(__file__).parent / ".worker_id"
    if id_file.exists():
        return id_file.read_text().strip()
    new_id = str(uuid.uuid4())[:8]
    id_file.write_text(new_id)
    return new_id

WORKER_ID = _stable_id()
HOSTNAME   = socket.gethostname()


def _download(sftp, remote: str, local: str):
    log.info(f"  ↓ {remote}")
    sftp.get(remote, local)


def _upload(sftp, local: str, remote: str):
    log.info(f"  ↑ {remote}")
    sftp.put(local, remote)


def _heartbeat_loop():
    psutil.cpu_percent()  # prime the counter; first call always returns 0.0
    while True:
        time.sleep(config.HEARTBEAT_INTERVAL)
        try:
            stats = {
                "cpu_percent": psutil.cpu_percent(),
                "mem_percent": psutil.virtual_memory().percent,
                "cpu_count": psutil.cpu_count(logical=True),
            }
            job_manager.heartbeat(WORKER_ID, stats=stats)
        except Exception as e:
            log.debug(f"Heartbeat error: {e}")


def process_job(job: dict):
    job_id      = job["id"]
    input_file  = job["input_file"]
    preset      = job.get("preset", "720p")
    custom_args = job.get("custom_args")
    output_name = job.get("output_name", job_id)
    output_path = job.get("output_path")  # absolute local path when set (NAS mode)

    last_pct = [-1]

    def on_progress(pct: int):
        if pct != last_pct[0]:
            last_pct[0] = pct
            log.info(f"  [{job_id}] {pct}%")
            try:
                job_manager.update_progress(job_id, pct)
                job_manager.heartbeat(WORKER_ID, job_id)
            except Exception:
                pass

    # NAS mode: input is absolute local path, output written directly (no SFTP)
    if input_file.startswith("/") and output_path:
        if not os.path.exists(input_file):
            raise RuntimeError(
                f"NAS source not accessible on this machine: {input_file}\n"
                f"Assign NAS jobs only to workers that have the source volume mounted."
            )
        if os.path.exists(output_path):
            log.warning(f"  Output already exists, skipping encode: {output_path}")
            job_manager.complete_job(job_id, output_path)
            log.info(f"✓ Job {job_id} skipped (output exists) → {output_path}")
            return
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        log.info(f"  NAS mode: {input_file} → {output_path}")
        encoder.encode(input_file, output_path, preset, custom_args, on_progress)
        job_manager.complete_job(job_id, output_path)
        log.info(f"✓ Job {job_id} done → {output_path}")
        return

    # SFTP mode: download input, encode to temp, upload output
    ext = "mkv" if custom_args else config.PRESETS.get(preset, {}).get("ext", "mp4")
    # Strip extension from output_name (Go includes it; avoid double extension)
    output_name_stem = output_name.rsplit(".", 1)[0] if "." in output_name and output_name.rsplit(".", 1)[1] in ("mkv", "mp4", "webm", "m4a", "mov") else output_name
    output_file = f"output/{output_name_stem}.{ext}"

    with tempfile.TemporaryDirectory(prefix="vod_") as tmp:
        suffix = Path(input_file).suffix or ".mp4"
        local_in  = os.path.join(tmp, f"input{suffix}")
        local_out = os.path.join(tmp, f"output.{ext}")

        with sftp_connection() as sftp:
            _download(sftp, f"{config.SFTP_BASE_PATH}/{input_file}", local_in)

        encoder.encode(local_in, local_out, preset, custom_args, on_progress)

        with sftp_connection() as sftp:
            _upload(sftp, local_out, f"{config.SFTP_BASE_PATH}/{output_file}")

    job_manager.complete_job(job_id, output_file)
    log.info(f"✓ Job {job_id} done → {output_file}")


def main():
    log.info(f"Worker {WORKER_ID} starting on {HOSTNAME}")
    sysinfo.start()
    log.info(f"Sysinfo server on :{sysinfo.PORT}")

    job_manager.ensure_dirs()
    job_manager.register_worker(
        WORKER_ID, HOSTNAME,
        {
            "presets": list(config.PRESETS.keys()),
            "profiles": ["home", "mobile"],  # vod_studio compatibility
            "hostname": HOSTNAME,
        },
    )

    hb = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb.start()

    log.info("Polling for jobs…")
    while True:
        try:
            job = job_manager.claim_next_job(WORKER_ID)
            if job:
                log.info(f"→ Claimed job {job['id']} (preset={job.get('preset')}, "
                         f"input={job.get('input_file')})")
                job_manager.heartbeat(WORKER_ID, job["id"])
                try:
                    process_job(job)
                except Exception as e:
                    log.error(f"✗ Job {job['id']} failed: {e}", exc_info=True)
                    job_manager.fail_job(job["id"], str(e))
                job_manager.heartbeat(WORKER_ID, None)
            else:
                time.sleep(config.POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info("Shutting down.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
