"""Screenshot of the rendered CMMS asset list -> docs/screenshots/cmms_queue.png
and ml/reports/assets/cmms_screenshot.png (the copy the model overview embeds).

Renders docs/index.html at 1440 px wide, full page, with Playwright, in the
installed Edge or Chrome, or in Playwright's own Chromium where neither is
installed. Run after generate_cmms_dashboard.py and before
generate_model_overview.py. Needs the optional dependency: pip install -e ".[dev]"
"""
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO   = Path(__file__).resolve().parents[2]
PAGE   = REPO / "docs" / "index.html"
OUT    = REPO / "docs" / "screenshots" / "cmms_queue.png"
ASSET  = Path(__file__).resolve().parent / "assets" / "cmms_screenshot.png"
WIDTH  = 1440


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome", None):
            try:
                # software rendering: the same page gives the same image on every run
                browser = (p.chromium.launch(channel=channel, args=["--disable-gpu"]) if channel
                           else p.chromium.launch(args=["--disable-gpu"]))
                break
            except Exception:
                continue
        if browser is None:
            print("No browser available; the committed screenshot is left as it is")
            return
        page = browser.new_page(viewport={"width": WIDTH, "height": 900}, device_scale_factor=1)
        page.goto(PAGE.as_uri())
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    shutil.copyfile(OUT, ASSET)
    print(f"CMMS screenshot written to {OUT} and {ASSET}")


if __name__ == "__main__":
    main()
