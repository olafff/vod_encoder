# VOD Encoder — How-To Guide

## Table of contents

1. [First-time setup (this machine)](#1-first-time-setup-this-machine)
2. [Setting up a worker on another machine](#2-setting-up-a-worker-on-another-machine)
3. [Running the web UI](#3-running-the-web-ui)
4. [Adding encoding jobs](#4-adding-encoding-jobs)
5. [Encoding modes: SFTP vs NAS](#5-encoding-modes-sftp-vs-nas)
6. [Presets and custom FFmpeg args](#6-presets-and-custom-ffmpeg-args)
7. [REST API reference](#7-rest-api-reference)
8. [Running as a service (systemd)](#8-running-as-a-service-systemd)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. First-time setup (this machine)

Already done on this machine. For reference:

```bash
cd ~/code/vod_encoder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The `.env` file is configured with:
- SFTP host: `10.0.0.12`, user: `vod`
- SSH key: `~/.ssh/id_ed25519`
- Base path: `/home/vod/vod_studio`
- API on port `8000`

The directory structure on the SFTP server was created automatically
(`queue/`, `processing/`, `completed/`, `failed/`, `input/`, `output/`, `workers/`).

---

## 2. Setting up a worker on another machine

Do this on every machine that should encode videos.

### Copy the project

```bash
# Option A — copy over the network
scp -r ~/code/vod_encoder user@othermachine:~/vod_encoder

# Option B — git clone if you put it in a repo
git clone <repo-url> ~/vod_encoder
```

### Install dependencies

```bash
cd ~/vod_encoder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

FFmpeg must also be installed on every worker machine:

```bash
# Debian/Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
#   and add ffmpeg.exe to PATH
```

### Configure credentials

```bash
cp .env.example .env
```

Edit `.env` on the new machine. Use either:

```
# SSH key (recommended — copy your public key to the SFTP server first)
VOD_SFTP_KEY_PATH=/home/youruser/.ssh/id_ed25519

# Or password
VOD_SFTP_PASSWORD=yourpassword
```

Copy your SSH public key to the SFTP server if you haven't already:

```bash
ssh-copy-id vod@10.0.0.12
```

### Start the worker

```bash
cd ~/vod_encoder
.venv/bin/python worker.py
```

The worker registers itself, starts polling, and picks up the next queued job.
You'll see it appear in the **Workers** tab of the web UI within a few seconds.

---

## 3. Running the web UI

Run the API server on **one machine** (doesn't need to be a worker):

```bash
cd ~/code/vod_encoder
.venv/bin/python api.py
```

Open **http://localhost:8000** in your browser, or use the machine's IP
to access from other computers on the network (e.g. `http://10.0.0.x:8000`).

The UI auto-refreshes every 5 seconds. Tabs:

| Tab | What it shows |
|-----|---------------|
| Queue | Pending jobs sorted by priority. Delete or reassign here. |
| Processing | Active jobs with live progress bars. |
| Completed | Finished jobs with output file paths. |
| Failed | Failed jobs with error messages. Delete to clear. |
| Workers | All registered workers — online/offline, current job, last heartbeat. |

---

## 4. Adding encoding jobs

### Via the web UI

1. Click **↑ Upload** to upload a source video to the `input/` directory on the server.
   Or put files there directly via SFTP.
2. Click **+ Add Job**.
3. Select the input file, preset, and priority.
4. Optionally assign to a specific worker (leave blank for any worker).
5. Click **Add to Queue**.

### Via curl / REST API

```bash
# Add a 1080p job
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"input_file": "input/movie.mkv", "preset": "1080p", "priority": 7}'

# Add a high-priority 720p job assigned to a specific worker
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_file": "input/movie.mkv",
    "preset": "720p",
    "priority": 10,
    "assigned_to": "a1b2c3d4"
  }'

# Delete a queued or failed job
curl -X DELETE http://localhost:8000/api/jobs/<job-id>
```

---

## 5. Encoding modes: SFTP vs NAS

### SFTP mode (default)

The worker downloads the source from the SFTP server, encodes it in a local
temp directory (`/tmp/vod_…`), and uploads the result back. Works from any
machine with SSH access to the SFTP server.

Use `input_file` as a path **relative to the base directory**, e.g.:

```json
{ "input_file": "input/movie.mkv", "preset": "1080p" }
```

Output is written to `output/movie_1080p.mp4` on the SFTP server.

### NAS mode

When workers have direct filesystem access (NFS or SMB mount), skip the SFTP
transfer entirely by using absolute paths:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_file": "/mnt/nas/originals/movie.mkv",
    "output_path": "/mnt/nas/encoded/movie_1080p.mp4",
    "preset": "1080p"
  }'
```

Rules for NAS mode:
- `input_file` must start with `/`
- `output_path` must also be set to an absolute path
- The worker that picks this job must be able to read `input_file` and write
  `output_path` — if the mount isn't present on that machine, the job will fail
- Use `assigned_to` to pin the job to a machine you know has the mount

---

## 6. Presets and custom FFmpeg args

### Built-in presets

| Preset | Codec | Resolution | Output |
|--------|-------|------------|--------|
| `720p` | H.264 / AAC | 1280×720 | .mp4 |
| `1080p` | H.264 / AAC | 1920×1080 | .mp4 |
| `4k_hevc` | H.265 / AAC | 3840×2160 | .mp4 |
| `webm_720p` | VP9 / Opus | 1280×720 | .webm |
| `audio_aac` | AAC only | — | .m4a |

### Custom FFmpeg arguments

Set `preset` to `"custom"` and provide `custom_args` as a list of strings.
Do **not** include `-i`, the input path, or the output path — those are added
automatically.

```bash
# Re-encode to H.265 with hardware acceleration (NVENC)
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_file": "input/movie.mkv",
    "preset": "custom",
    "output_name": "movie_hevc_nvenc",
    "custom_args": ["-c:v", "hevc_nvenc", "-cq", "28", "-c:a", "copy"]
  }'

# Extract subtitles
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_file": "input/movie.mkv",
    "preset": "custom",
    "output_name": "movie_subs",
    "custom_args": ["-map", "0:s:0", "-c:s", "srt"]
  }'
```

Custom-args jobs produce `.mkv` output in SFTP mode.

### Adding a new preset permanently

Edit `config.py` and add to the `PRESETS` dict:

```python
"prores": {
    "description": "Apple ProRes 422 HQ",
    "args": ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"],
    "ext": "mov",
},
```

Restart `api.py` and `worker.py` for it to take effect.

---

## 7. REST API reference

Base URL: `http://localhost:8000`

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | List all jobs (all statuses) |
| `GET` | `/api/jobs/{id}` | Get a single job |
| `POST` | `/api/jobs` | Create a job |
| `DELETE` | `/api/jobs/{id}` | Delete a queued or failed job |

**POST /api/jobs — request body**

```jsonc
{
  "input_file": "input/movie.mkv",  // relative path (SFTP mode) or absolute (NAS mode)
  "preset": "1080p",                // preset name or "custom"
  "output_name": "movie_hd",        // optional, no extension
  "priority": 5,                    // 1 (low) – 10 (high), default 5
  "custom_args": null,              // list of ffmpeg args when preset="custom"
  "assigned_to": null,              // worker ID prefix to pin the job to
  "output_path": null               // absolute output path for NAS mode
}
```

**Job object (response)**

```jsonc
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queue",          // queue | processing | completed | failed
  "input_file": "input/movie.mkv",
  "preset": "1080p",
  "output_name": "movie_1080p",
  "output_path": null,
  "custom_args": null,
  "priority": 5,
  "assigned_to": null,
  "created_at": "2025-05-14T20:00:00+00:00",
  "started_at": null,
  "completed_at": null,
  "worker_id": null,
  "progress": 0,              // 0–100
  "output_file": null,        // set when completed
  "error": null               // set when failed
}
```

### Workers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workers` | List all registered workers |

### Files & uploads

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/files` | List files in the `input/` directory |
| `POST` | `/api/upload` | Upload a file to `input/` (multipart/form-data, field: `file`) |

```bash
# Upload via curl
curl -X POST http://localhost:8000/api/upload \
  -F "file=@/path/to/movie.mkv"
```

### Presets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/presets` | List built-in presets with descriptions |

---

## 8. Running as a service (systemd)

To keep the worker and API running after logout, create systemd units.

### Worker service

Create `/etc/systemd/system/vod-worker.service`:

```ini
[Unit]
Description=VOD Encoder Worker
After=network.target

[Service]
User=ulav
WorkingDirectory=/home/ulav/code/vod_encoder
ExecStart=/home/ulav/code/vod_encoder/.venv/bin/python worker.py
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/ulav/code/vod_encoder/.env

[Install]
WantedBy=multi-user.target
```

### API service

Create `/etc/systemd/system/vod-api.service`:

```ini
[Unit]
Description=VOD Encoder API
After=network.target

[Service]
User=ulav
WorkingDirectory=/home/ulav/code/vod_encoder
ExecStart=/home/ulav/code/vod_encoder/.venv/bin/python api.py
Restart=on-failure
RestartSec=5
EnvironmentFile=/home/ulav/code/vod_encoder/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vod-worker vod-api
sudo journalctl -fu vod-worker   # follow worker logs
```

---

## 9. Troubleshooting

### "SSH key auth failed and VOD_SFTP_PASSWORD is not set"

Your SSH key isn't accepted by the SFTP server. Fix:

```bash
# Check your key works
ssh vod@10.0.0.12

# If not, copy it
ssh-copy-id -i ~/.ssh/id_ed25519 vod@10.0.0.12

# Or set a password in .env
VOD_SFTP_PASSWORD=yourpassword
```

### Worker picks up a job but immediately fails

Check the error in the **Failed** tab or in the worker log. Common causes:
- FFmpeg not installed (`sudo apt install ffmpeg`)
- Source file doesn't exist in `input/` on the server
- NAS mode job on a machine that doesn't have the mount

### Progress stays at 0%

FFprobe couldn't determine the frame count (unusual container or pure audio).
The job still encodes correctly — progress just won't update until it finishes.

### Job stuck in "processing" after worker crash

The job file stays in `processing/` after an unclean shutdown. Move it back manually:

```bash
# On any machine with SFTP access
sftp vod@10.0.0.12
sftp> rename /home/vod/vod_studio/processing/<id>.json /home/vod/vod_studio/queue/<id>.json
```

Or delete it via the API (failed jobs only) and re-submit.

### "Address already in use" when starting api.py

Another process is using port 8000. Change the port in `.env`:

```
VOD_API_PORT=8080
```

### Worker not appearing in the Workers tab

- Confirm `worker.py` is running and not crashing at startup
- Check the worker's `.env` has the correct SFTP credentials
- The UI considers a worker offline if its heartbeat is more than 60 seconds old
  (controlled by `VOD_WORKER_TIMEOUT`)
