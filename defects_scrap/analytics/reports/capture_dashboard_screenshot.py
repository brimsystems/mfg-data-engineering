"""Screenshot of the rendered dashboard -> docs/screenshots/dashboard.png

Renders docs/reports/dashboard.html at 1280 px wide with Playwright, from the
top of the page to the start of the trend charts (the header, the KPI tiles and
the tracker tiles), in the installed Edge or Chrome, or in Playwright's own
Chromium where neither is installed. Run after generate_dashboard.py. Needs the
optional dependency: pip install -e ".[dev]"
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "reports" / "dashboard.html"
OUT = REPO / "docs" / "screenshots" / "dashboard.png"
WIDTH = 1280


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome", None):
            try:
                browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
                break
            except Exception:
                continue
        if browser is None:
            print("No browser available; the committed screenshot is left as it is")
            return
        page = browser.new_page(viewport={"width": WIDTH, "height": 900}, device_scale_factor=1)
        page.goto(PAGE.as_uri())
        page.wait_for_load_state("networkidle")
        height = int(page.evaluate(
            "Math.ceil(document.querySelector('#trends').getBoundingClientRect().top + window.scrollY) - 12"))
        page.screenshot(path=str(OUT), full_page=True, clip={"x": 0, "y": 0, "width": WIDTH, "height": height})
        browser.close()
    print(f"Dashboard screenshot written to {OUT} ({WIDTH} x {height})")


if __name__ == "__main__":
    main()
