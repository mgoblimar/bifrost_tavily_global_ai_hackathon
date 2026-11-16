"""Assemble the demo video from the raw recordings.

Order: title card, terminal clip, browser clip, closing card. The long waits
recorded in the cuts files are trimmed out. Output: demo/carbon-date-demo.mp4

Run after record_terminal and record_browser:   python -m demo.build_video
"""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

DEMO_DIR = Path(__file__).parent
RAW_DIR = DEMO_DIR / "raw"
OUTPUT = DEMO_DIR / "carbon-date-demo.mp4"
WIDTH, HEIGHT, FPS = 1280, 720, 25
CARD_SECONDS = 5
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-an"]

CARD_HTML = """<html><body style="margin:0;width:1280px;height:720px;background:#10182B;
color:#F3F1EA;font-family:Arial,sans-serif;display:flex;flex-direction:column;
justify-content:center;padding:0 110px;box-sizing:border-box">
<div style="font-size:19px;letter-spacing:3px;color:#F2A65A;font-weight:700">{eyebrow}</div>
<div style="font-size:92px;font-weight:700;margin:18px 0 22px">{title}</div>
<div style="font-size:31px;line-height:1.4;color:#B9C2D3;max-width:980px">{body}</div>
</body></html>"""

CAPTION_HTML = """<html><body style="margin:0;background:transparent">
<div id="c" style="display:inline-block;padding:12px 22px;border-radius:10px;
background:rgba(16,24,43,0.94);color:#F3F1EA;font:600 21px/1.35 Arial,sans-serif">{text}</div>
</body></html>"""

CARDS = {
    "intro": {
        "eyebrow": "GEEK ROOM GLOBAL AI HACKATHON 2026 · TEAM JENX",
        "title": "Carbon Date",
        "body": "AI answers carry no date. Carbon Date tells your AI app how old an "
        "answer really is, before your user sees it. Built on Tavily and Bifrost.",
    },
    "outro": {
        "eyebrow": "TEAM JENX",
        "title": "Carbon Date",
        "body": "A verification layer for AI applications, and a briefing agent built on it. "
        "github.com/mgoblimar/bifrost_tavily_global_ai_hackathon",
    },
}
TERMINAL_CAPTION = "A chat app asks a model, then calls Carbon Date before showing the answer."


def run(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


def render_images() -> None:
    """Draw the title cards and the terminal caption with a headless browser."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        for name, text in CARDS.items():
            page.set_content(CARD_HTML.format(**text))
            page.screenshot(path=str(RAW_DIR / f"card_{name}.png"))
        page.set_content(CAPTION_HTML.format(text=TERMINAL_CAPTION))
        page.locator("#c").screenshot(
            path=str(RAW_DIR / "caption_terminal.png"), omit_background=True
        )
        browser.close()


def keep_filter(cuts: list[list[float]]) -> str:
    """ffmpeg filter that drops the cut ranges and closes the gaps."""
    if not cuts:
        return f"fps={FPS}"
    dropped = "+".join(f"between(t,{start:.2f},{end:.2f})" for start, end in cuts)
    return f"fps={FPS},select='not({dropped})',setpts=N/{FPS}/TB"


def build_card(name: str) -> Path:
    target = RAW_DIR / f"seg_{name}.mp4"
    run(["-loop", "1", "-t", str(CARD_SECONDS), "-i", str(RAW_DIR / f"card_{name}.png"),
         "-vf", f"fps={FPS}", *ENCODE, str(target)])
    return target


def build_terminal() -> Path:
    cuts = json.loads((RAW_DIR / "terminal_cuts.json").read_text(encoding="utf-8"))["cuts"]
    target = RAW_DIR / "seg_terminal.mp4"
    fit = (
        f"scale={WIDTH - 120}:{HEIGHT - 150}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:40:color=0x0C0C0C"
    )
    graph = (
        f"[0:v]{keep_filter(cuts)},{fit}[base];"
        f"[base][1:v]overlay=(W-w)/2:H-h-22[out]"
    )
    run(["-i", str(RAW_DIR / "terminal.mkv"), "-i", str(RAW_DIR / "caption_terminal.png"),
         "-filter_complex", graph, "-map", "[out]", *ENCODE, str(target)])
    return target


def build_browser() -> Path:
    cuts = json.loads((RAW_DIR / "cuts.json").read_text(encoding="utf-8"))["cuts"]
    target = RAW_DIR / "seg_browser.mp4"
    run(["-i", str(RAW_DIR / "browser.webm"),
         "-vf", f"{keep_filter(cuts)},scale={WIDTH}:{HEIGHT}", *ENCODE, str(target)])
    return target


def main() -> None:
    render_images()
    segments = [build_card("intro"), build_terminal(), build_browser(), build_card("outro")]
    playlist = RAW_DIR / "playlist.txt"
    playlist.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8"
    )
    run(["-f", "concat", "-safe", "0", "-i", str(playlist), "-c", "copy", str(OUTPUT)])


if __name__ == "__main__":
    main()
