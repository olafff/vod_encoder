import os
from dotenv import load_dotenv

load_dotenv()

SFTP_HOST     = os.getenv("VOD_SFTP_HOST", "10.0.0.12")
SFTP_PORT     = int(os.getenv("VOD_SFTP_PORT", "22"))
SFTP_USER     = os.getenv("VOD_SFTP_USER", "vod")
SFTP_PASSWORD = os.getenv("VOD_SFTP_PASSWORD")
SFTP_KEY_PATH = os.getenv("VOD_SFTP_KEY_PATH")
SFTP_BASE_PATH = os.getenv("VOD_SFTP_BASE_PATH", "/home/vod/vod_studio")

API_HOST = os.getenv("VOD_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("VOD_API_PORT", "8000"))

POLL_INTERVAL      = int(os.getenv("VOD_POLL_INTERVAL", "5"))
HEARTBEAT_INTERVAL = int(os.getenv("VOD_HEARTBEAT_INTERVAL", "10"))
WORKER_TIMEOUT     = int(os.getenv("VOD_WORKER_TIMEOUT", "60"))

PRESETS = {
    "720p": {
        "description": "H.264 720p HD",
        "args": ["-vf", "scale=1280:720", "-c:v", "libx264", "-crf", "23",
                 "-preset", "medium", "-c:a", "aac", "-b:a", "128k"],
        "ext": "mp4",
    },
    "1080p": {
        "description": "H.264 1080p Full HD",
        "args": ["-vf", "scale=1920:1080", "-c:v", "libx264", "-crf", "20",
                 "-preset", "medium", "-c:a", "aac", "-b:a", "192k"],
        "ext": "mp4",
    },
    "4k_hevc": {
        "description": "H.265/HEVC 4K UHD",
        "args": ["-vf", "scale=3840:2160", "-c:v", "libx265", "-crf", "28",
                 "-preset", "medium", "-c:a", "aac", "-b:a", "256k"],
        "ext": "mp4",
    },
    "webm_720p": {
        "description": "VP9 WebM 720p",
        "args": ["-vf", "scale=1280:720", "-c:v", "libvpx-vp9", "-crf", "33",
                 "-b:v", "0", "-c:a", "libopus", "-b:a", "128k"],
        "ext": "webm",
    },
    "audio_aac": {
        "description": "AAC Audio Only (256 kbps)",
        "args": ["-vn", "-c:a", "aac", "-b:a", "256k"],
        "ext": "m4a",
    },
}
