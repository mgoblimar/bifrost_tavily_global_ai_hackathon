"""Assemble the demo video from the raw recordings.

Order: title, then three parts each introduced by a section card (API, detector
page, briefing page), a card on where this fits in real AI applications, and a
closing card. The long waits noted in the cuts files are trimmed out.

Output: demo/carbon-date-demo.mp4
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
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-an"]
PAGE_SWITCH_SECONDS = 1.8  # blank frames while the browser loads the next page
WAIT_LEAD_SECONDS = 1.2  # how much of each wait stays visible before the cut
# The recorders note each wait as [start + 2.0, end - margin] on their own clock.
RECORDED_LEAD_SECONDS = 2.0
BROWSER_END_MARGIN = 0.5
TERMINAL_START_DELAY = 0.5  # ffmpeg takes about this long to begin capturing

CARD_HTML = """<html><body style="margin:0;width:1280px;height:720px;background:{background};
color:{ink};font-family:Arial,sans-serif;display:flex;flex-direction:column;
justify-content:center;padding:0 110px;box-sizing:border-box">
<div style="font-size:19px;letter-spacing:3px;color:{accent};font-weight:700">{eyebrow}</div>
<div style="font-size:{title_size}px;font-weight:700;margin:18px 0 22px;line-height:1.08">{title}</div>
<div style="font-size:30px;line-height:1.42;color:{muted};max-width:1010px">{body}</div>
</body></html>"""

CAPTION_HTML = """<html><body style="margin:0;background:transparent">
<div id="c" style="display:inline-block;padding:12px 22px;border-radius:10px;
background:rgba(16,24,43,0.94);color:#F3F1EA;font:600 21px/1.35 Arial,sans-serif">{text}</div>
</body></html>"""

DARK = {"background": "#10182B", "ink": "#F3F1EA", "accent": "#F2A65A", "muted": "#B9C2D3"}
LIGHT = {"background": "#F6F4EE", "ink": "#10182B", "accent": "#A84E0B", "muted": "#3D4658"}

# name -> (seconds on screen, colours, text)
CARDS = {
    "intro": (5, DARK, {
        "eyebrow": "GEEK ROOM GLOBAL AI HACKATHON 2026 · TEAM JENX",
        "title": "Carbon Date", "title_size": 92,
        "body": "AI answers carry no date. Carbon Date tells your AI app how old an "
        "answer really is, before your user sees it. Built on Tavily and Bifrost.",
    }),
    "part1": (6, LIGHT, {
        "eyebrow": "PART 1 OF 3 · FOR AI APPLICATIONS",
        "title": "The API", "title_size": 80,
        "body": "This is how another program uses Carbon Date. An app sends the answer its "
        "model produced to one HTTP endpoint and gets each claim back with a verdict. "
        "First a small chat app in a terminal, then the same call in the API's docs page.",
    }),
    "part2": (6, LIGHT, {
        "eyebrow": "PART 2 OF 3 · FOR A PERSON",
        "title": "The Stale-Answer Detector page", "title_size": 64,
        "body": "The same check, as a web page. You paste an AI-generated answer and read "
        "the result on screen. It is a way to try the engine by hand, with nothing to code.",
    }),
    "part3": (6, LIGHT, {
        "eyebrow": "PART 3 OF 3 · AN AI APP BUILT ON IT",
        "title": "The Pre-Meeting Briefing page", "title_size": 64,
        "body": "A separate web page, and a full AI application of its own. It researches a "
        "company, drafts a one-page briefing with a model, then uses Carbon Date to "
        "check its own draft and your talking points.",
    }),
    "realworld": (8, DARK, {
        "eyebrow": "BEYOND THIS DEMO",
        "title": "Where the API fits", "title_size": 72,
        "body": "Any app that shows a model's answer without live search: a support bot "
        "quoting prices and policies, an internal assistant answering from old documents, "
        "a coding assistant recommending versions, a research or briefing agent. "
        "These are intended uses, not deployments.",
    }),
    "outro": (5, DARK, {
        "eyebrow": "TEAM JENX",
        "title": "Carbon Date", "title_size": 92,
        "body": "A verification layer for AI applications, and a briefing agent built on it. "
        "github.com/mgoblimar/bifrost_tavily_global_ai_hackathon",
    }),
}
TERMINAL_CAPTION = "A chat app asks a model, then calls Carbon Date before showing the answer."


def run(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


def render_images() -> None:
    """Draw the cards and the terminal caption with a headless browser."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        for name, (_, colours, text) in CARDS.items():
            page.set_content(CARD_HTML.format(**colours, **text))
            page.screenshot(path=str(RAW_DIR / f"card_{name}.png"))
        page.set_content(CAPTION_HTML.format(text=TERMINAL_CAPTION))
        page.locator("#c").screenshot(
            path=str(RAW_DIR / "caption_terminal.png"), omit_background=True
        )
        browser.close()


def keep_filter(cuts: list[list[float]], start: float = 0.0, end: float | None = None) -> str:
    """ffmpeg filter keeping [start, end] minus the cut ranges, with gaps closed."""
    conditions = [f"gte(t,{start:.2f})"]
    if end is not None:
        conditions.append(f"lt(t,{end:.2f})")
    conditions += [f"not(between(t,{a:.2f},{b:.2f}))" for a, b in cuts]
    return f"fps={FPS},select='{'*'.join(conditions)}',setpts=N/{FPS}/TB"


def video_seconds(path: Path) -> float:
    """Length of a recording, read by decoding it."""
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    stamp = result.stderr.rsplit("time=", 1)[1].split()[0]
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def browser_cuts() -> list[list[float]]:
    """Wait ranges on the video's own timeline.

    The recorder's clock starts a few seconds before the video does, so its
    timestamps are shifted by the difference between the two lengths.
    """
    data = json.loads((RAW_DIR / "cuts.json").read_text(encoding="utf-8"))
    offset = data["total"] - video_seconds(RAW_DIR / "browser.webm")
    return [
        [
            start - RECORDED_LEAD_SECONDS - offset + WAIT_LEAD_SECONDS,
            end + BROWSER_END_MARGIN - offset - 0.3,
        ]
        for start, end in data["cuts"]
    ]


def terminal_cuts() -> list[list[float]]:
    data = json.loads((RAW_DIR / "terminal_cuts.json").read_text(encoding="utf-8"))
    return [
        [
            start - RECORDED_LEAD_SECONDS - TERMINAL_START_DELAY + WAIT_LEAD_SECONDS,
            end - TERMINAL_START_DELAY,
        ]
        for start, end in data["cuts"]
    ]


def build_card(name: str) -> Path:
    seconds = CARDS[name][0]
    target = RAW_DIR / f"seg_{name}.mp4"
    run(["-loop", "1", "-t", str(seconds), "-i", str(RAW_DIR / f"card_{name}.png"),
         "-vf", f"fps={FPS}", *ENCODE, str(target)])
    return target


def build_terminal() -> Path:
    cuts = terminal_cuts()
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


def build_browser_part(name: str, start: float, end: float | None) -> Path:
    cuts = browser_cuts()
    target = RAW_DIR / f"seg_{name}.mp4"
    run(["-i", str(RAW_DIR / "browser.webm"),
         "-vf", f"{keep_filter(cuts, start, end)},scale={WIDTH}:{HEIGHT}", *ENCODE, str(target)])
    return target


def main() -> None:
    marks = json.loads((RAW_DIR / "cuts.json").read_text(encoding="utf-8"))["marks"]
    detector_at, briefing_at = marks["detector"], marks["briefing"]
    render_images()
    segments = [
        build_card("intro"),
        build_card("part1"),
        build_terminal(),
        build_browser_part("api", PAGE_SWITCH_SECONDS, detector_at),
        build_card("part2"),
        build_browser_part("detector", detector_at + PAGE_SWITCH_SECONDS, briefing_at),
        build_card("part3"),
        build_browser_part("briefing", briefing_at + PAGE_SWITCH_SECONDS, None),
        build_card("realworld"),
        build_card("outro"),
    ]
    playlist = RAW_DIR / "playlist.txt"
    playlist.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8"
    )
    run(["-f", "concat", "-safe", "0", "-i", str(playlist), "-c", "copy", str(OUTPUT)])


if __name__ == "__main__":
    main()
