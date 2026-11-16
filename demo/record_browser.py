"""Record the browser part of the demo with Playwright.

Drives the real app (API docs, detector page, briefing page) and records it.
Waiting periods are noted in demo/raw/cuts.json so build_video.py can trim them.

Needs: the Bifrost gateway, the API (port 8600) and the pages (port 8501) running.
Run:   python -m demo.record_browser
"""

import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

RAW_DIR = Path(__file__).parent / "raw"
WIDTH, HEIGHT = 1280, 720
RUN_TIMEOUT_MS = 240_000
API_DOCS = "http://localhost:8600/docs"
PAGES = "http://localhost:8501"

API_BODY = json.dumps(
    {"answer": "The latest stable Python release is 3.12, and Node.js 18 is the current LTS version."},
    indent=2,
)
TALKING_POINTS = (
    "Open by congratulating Jensen Huang on his leadership as CEO. "
    "Their flagship data centre GPU is the H100."
)

CAPTION_JS = """
(text) => {
  let box = document.getElementById('demo-caption');
  if (!box) {
    box = document.createElement('div');
    box.id = 'demo-caption';
    box.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);' +
      'z-index:2147483647;max-width:1080px;padding:12px 22px;border-radius:10px;' +
      'background:rgba(16,24,43,0.94);color:#F3F1EA;font:600 21px/1.35 Arial,sans-serif;' +
      'text-align:center;box-shadow:0 6px 24px rgba(0,0,0,0.35);pointer-events:none';
    document.body.appendChild(box);
  }
  box.textContent = text;
}
"""


class Recorder:
    """Tracks time since recording started and the stretches to cut out."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.started = time.monotonic()
        self.cuts: list[list[float]] = []

    def now(self) -> float:
        return time.monotonic() - self.started

    def caption(self, text: str, hold: float = 0.0) -> None:
        self.page.evaluate(CAPTION_JS, text)
        if hold:
            self.page.wait_for_timeout(int(hold * 1000))

    def wait_trimmed(self, selector_text: str) -> None:
        """Wait for a run to finish; mark all but the edges of the wait as a cut."""
        self.caption("Checking live sources through Tavily and Bifrost... (wait trimmed)")
        start = self.now()
        self.page.get_by_text(selector_text).first.wait_for(timeout=RUN_TIMEOUT_MS)
        end = self.now()
        if end - start > 5:
            self.cuts.append([start + 2.0, end - 0.5])

    def scroll(self, pixels: int, steps: int = 12) -> None:
        for _ in range(steps):
            self.page.mouse.wheel(0, pixels / steps)
            self.page.wait_for_timeout(110)


def record_api(rec: Recorder) -> None:
    page = rec.page
    page.goto(API_DOCS)
    page.get_by_text("/v1/verify").first.wait_for()
    rec.caption("Carbon Date is an HTTP API. Any AI app can call it.", hold=3.0)
    page.locator(".opblock-post").first.click()
    page.get_by_role("button", name="Try it out").click()
    page.locator("textarea.body-param__text").fill(API_BODY)
    rec.caption("An app posts the answer its model produced.", hold=3.0)
    page.get_by_role("button", name="Execute").click()
    rec.wait_trimmed("Server response")
    page.locator(".live-responses-table").scroll_into_view_if_needed()
    rec.caption("It gets back each claim: verdict, current value, score and sources.", hold=2.0)
    rec.scroll(260)
    page.wait_for_timeout(4000)


def record_detector(rec: Recorder) -> None:
    page = rec.page
    page.goto(f"{PAGES}/Stale_Answer_Detector")
    page.get_by_role("button", name="Check freshness").wait_for()
    rec.caption("The same check by hand: paste an AI-generated answer.", hold=3.5)
    page.get_by_role("button", name="Check freshness").click()
    rec.wait_trimmed("Overall freshness")
    rec.caption("Each claim gets a verdict, what is true now, and a freshness score.", hold=3.0)
    rec.scroll(520)
    page.wait_for_timeout(2500)
    page.get_by_text("Sources (").first.click()
    rec.caption("Every verdict links to its sources and says what kind they are.", hold=1.0)
    rec.scroll(360)
    page.wait_for_timeout(3500)


def record_briefing(rec: Recorder) -> None:
    page = rec.page
    page.goto(f"{PAGES}/Meeting_Briefing")
    page.get_by_label("Company or person").wait_for()
    rec.caption("An AI app built on the layer: a pre-meeting briefing.", hold=2.5)
    page.get_by_label("Company or person").fill("Nvidia")
    page.get_by_label("Your talking points (optional)").fill(TALKING_POINTS)
    page.get_by_label("Other trusted sites (optional, comma-separated)").fill("nvidia.com")
    rec.caption("Who you are meeting, your talking points, and a site you trust.", hold=1.0)
    rec.scroll(380)
    page.wait_for_timeout(2500)
    page.get_by_role("button", name="Build briefing").click()
    rec.wait_trimmed("At a glance")
    page.get_by_text("At a glance").first.scroll_into_view_if_needed()
    rec.caption("It researches the last 30 days, drafts one page, then checks itself.", hold=3.5)
    rec.scroll(620, steps=18)
    page.wait_for_timeout(2500)
    talking = page.get_by_text("Your talking points, checked").first
    if talking.count():
        talking.scroll_into_view_if_needed()
        rec.caption("It also checks your own talking points and flags what not to say.", hold=4.5)
        rec.scroll(420)
        page.wait_for_timeout(2500)
    gateway = page.get_by_text("Gateway activity (Bifrost)").first
    gateway.scroll_into_view_if_needed()
    gateway.click()
    rec.caption("Every model call goes through Bifrost, with automatic fallback.", hold=1.0)
    rec.scroll(300)
    page.wait_for_timeout(4500)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(RAW_DIR),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = context.new_page()
        rec = Recorder(page)
        record_api(rec)
        record_detector(rec)
        record_briefing(rec)
        total = rec.now()
        video = page.video
        context.close()
        browser.close()
        source = Path(video.path())
        target = RAW_DIR / "browser.webm"
        target.unlink(missing_ok=True)
        source.rename(target)
    (RAW_DIR / "cuts.json").write_text(
        json.dumps({"cuts": rec.cuts, "total": total}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
