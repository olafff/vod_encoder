import json
import subprocess
import threading
from typing import Callable, Optional

import config


def get_frame_count(path: str) -> Optional[int]:
    """Estimate total frames from duration × r_frame_rate (reliable for HEVC)."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        fps_str = data["streams"][0]["r_frame_rate"]
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
        return int(duration * fps)
    except Exception:
        return None


def encode(
    input_path: str,
    output_path: str,
    preset: str,
    custom_args: Optional[list] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> None:
    if custom_args:
        ffmpeg_args = custom_args
    elif preset in config.PRESETS:
        ffmpeg_args = config.PRESETS[preset]["args"]
    else:
        raise ValueError(f"Unknown preset '{preset}'")

    # Use frame count for progress — out_time_us is N/A for HEVC remux sources
    total_frames = get_frame_count(input_path) if progress_cb else None

    cmd = (
        ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path]
        + ffmpeg_args
        + ["-progress", "pipe:1", output_path]
    )

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    stderr_lines: list[str] = []

    def drain_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("frame=") and total_frames and progress_cb:
            try:
                n = int(line.split("=", 1)[1])
                if n > 0:
                    pct = min(99, int(n / total_frames * 100))
                    progress_cb(pct)
            except (ValueError, ZeroDivisionError):
                pass

    proc.wait()
    t.join()

    if proc.returncode != 0:
        tail = "".join(stderr_lines[-20:]).strip()
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {tail}")
