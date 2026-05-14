# VOD Encoder

Distributed video encoding system. A shared job queue lives on an SFTP server;
any number of worker machines pull jobs, encode with FFmpeg, and push results back.
A web UI and REST API let you manage the queue from a browser or scripts.

## Architecture

```
                    ┌─────────────────────────────────┐
                    │  SFTP server  10.0.0.12          │
                    │  /home/vod/vod_studio/           │
                    │    queue/       ← pending jobs   │
                    │    processing/  ← claimed jobs   │
                    │    completed/                    │
                    │    failed/                       │
                    │    input/       ← source files   │
                    │    output/      ← encoded files  │
                    │    workers/     ← heartbeats     │
                    └──────────────┬──────────────────┘
                                   │ SFTP
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   ┌──────▼──────┐          ┌──────▼──────┐         ┌──────▼──────┐
   │  api.py     │          │  worker.py  │         │  worker.py  │
   │  Web UI     │          │  machine A  │         │  machine B  │
   │  :8000      │          │             │         │             │
   └─────────────┘          └─────────────┘         └─────────────┘
```

Workers race to claim jobs by atomically renaming files from `queue/` to
`processing/` — no separate database or message broker required.

## Two encoding modes

**SFTP mode** (default) — worker downloads source from `input/`, encodes to a temp
directory, uploads the result to `output/`. Works from any machine with SFTP access.

**NAS mode** — `input_file` is an absolute path (e.g. `/mnt/nas/movie.mkv`) and
`output_path` is also absolute. The worker encodes in-place with no SFTP transfer.
Use this when your workers mount the NAS directly (NFS/SMB) for large files.

## Files

```
vod_encoder/
├── api.py          — FastAPI server: REST API + web UI
├── worker.py       — Worker daemon: polls queue, encodes, reports progress
├── encoder.py      — FFmpeg wrapper (frame-count progress, HEVC-safe)
├── job_manager.py  — Job CRUD + worker heartbeats over SFTP
├── sftp_manager.py — SFTP connection (SSH key → password fallback)
├── config.py       — All settings via env vars / .env file
├── static/
│   └── index.html  — Single-page web UI (no build step)
├── .env            — Your local credentials (not committed)
├── .env.example    — Template
└── requirements.txt
```

## Quick start

```bash
# 1 — install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2 — configure (copy .env.example → .env, fill in credentials)
cp .env.example .env

# 3 — start the web UI / API (any one machine)
.venv/bin/python api.py
# open http://localhost:8000

# 4 — start a worker (each encoding machine)
.venv/bin/python worker.py
```

See **HOWTO.md** for full setup instructions, multi-machine deployment, NAS mode,
API reference, and troubleshooting.
