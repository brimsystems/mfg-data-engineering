"""Screenshots of the rendered ERP outputs -> docs/screenshots/

Renders four pages at 1280 px wide with Playwright, in the installed Edge or
Chrome, or in Playwright's own Chromium where neither is installed:

  job_in_progress.png      the job cost screen, in progress (docs/index.html)
  job_cost_dashboard.png   the Job Cost dashboard
  job_variance_job.png     the Job Variance report grouped by job, trailing twelve months
  job_variance_part.png    the same report grouped by part, with the first part expanded

Run after the screens are written. Needs the optional dependency:
pip install -e ".[dev]"
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
OUT = DOCS / "screenshots"
WIDTH = 1280
SHOTS = [("job_in_progress.png", "index.html", "", 760),
         ("job_cost_dashboard.png", "erp/job_cost_dashboard.html", "", 860),
         ("job_variance_job.png", "erp/job_variance_report.html", "?period=ttm&group=job", 760),
         ("job_variance_part.png", "erp/job_variance_report.html", "?period=ttm&group=part&expand=first", 760)]


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed; the committed screenshots are left as they are")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome", None):
            try:
                # software rendering: the same page gives the same image on every run
                browser = p.chromium.launch(channel=channel, args=["--disable-gpu"]) if channel else p.chromium.launch(args=["--disable-gpu"])
                break
            except Exception:
                continue
        if browser is None:
            print("No browser available; the committed screenshots are left as they are")
            return
        for name, page_path, query, height in SHOTS:
            page = browser.new_page(viewport={"width": WIDTH, "height": height}, device_scale_factor=1)
            page.goto((DOCS / page_path).as_uri() + query)
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(OUT / name), clip={"x": 0, "y": 0, "width": WIDTH, "height": height})
            page.close()
            print(f"{name} written ({WIDTH} x {height})")
        browser.close()


if __name__ == "__main__":
    main()
