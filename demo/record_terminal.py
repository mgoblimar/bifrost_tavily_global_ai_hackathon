"""Record the terminal part of the demo: a real console window running the example app.

Opens a classic console window, records only that window with ffmpeg, and notes
the waiting period in demo/raw/terminal_cuts.json so build_video.py can trim it.

Needs: the Bifrost gateway and the API (port 8600) running.
Run:   python -m demo.record_terminal
"""

import json
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg

DEMO_DIR = Path(__file__).parent
RAW_DIR = DEMO_DIR / "raw"
WINDOW_TITLE = "CarbonDateDemo"
MAX_SECONDS = 240
HOLD_AFTER_RESULT_SECONDS = 11


def wait_for(path: Path, deadline: float) -> float | None:
    while time.monotonic() < deadline:
        if path.exists():
            return time.monotonic()
        time.sleep(0.2)
    return None


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    start_marker = RAW_DIR / "term_start.txt"
    end_marker = RAW_DIR / "term_end.txt"
    for marker in (start_marker, end_marker):
        marker.unlink(missing_ok=True)
    output = RAW_DIR / "terminal.mkv"
    output.unlink(missing_ok=True)

    console = subprocess.Popen(
        ["conhost.exe", "cmd.exe", "/c", str(DEMO_DIR / "terminal_demo.bat")]
    )
    time.sleep(2.0)  # let the window appear and set its title

    recorder = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "gdigrab", "-framerate", "15", "-draw_mouse", "0",
            "-i", f"title={WINDOW_TITLE}",
            "-t", str(MAX_SECONDS),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(output),
        ],
        stdin=subprocess.PIPE,
    )
    recording_started = time.monotonic()
    deadline = recording_started + MAX_SECONDS - HOLD_AFTER_RESULT_SECONDS - 2

    run_started = wait_for(start_marker, deadline)
    run_ended = wait_for(end_marker, deadline)
    time.sleep(HOLD_AFTER_RESULT_SECONDS)

    try:
        recorder.communicate(input=b"q", timeout=20)
    except subprocess.TimeoutExpired:
        recorder.kill()
    console.wait(timeout=30)

    cuts = []
    if run_started and run_ended and run_ended - run_started > 6:
        cuts.append(
            [run_started - recording_started + 2.0, run_ended - recording_started - 0.4]
        )
    (RAW_DIR / "terminal_cuts.json").write_text(
        json.dumps({"cuts": cuts, "completed": run_ended is not None}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
