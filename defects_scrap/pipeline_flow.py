"""
pipeline_flow.py
The monthly flow: rebuild the warehouse from the latest extracts and regenerate
the diagnostic report and the dashboard. Each step runs the same command as the
manual steps in the README, in the same order, so one run of the flow gives the
same outputs.

  1. dbt build
  2. the diagnostic report
  3. the dashboard

Schedule: monthly, on the first weekday at 06:00. The schedule is defined below
as MONTHLY_SCHEDULE and attached in monthly_deployment(); this file does not
deploy or serve it.

Run once locally:  python pipeline_flow.py
"""
import subprocess
import sys
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.schedules import RRule

ROOT = Path(__file__).resolve().parent

# First weekday of each month at 06:00 (iCalendar recurrence rule).
MONTHLY_SCHEDULE = "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1;BYHOUR=6;BYMINUTE=0;BYSECOND=0"
SCHEDULE_TIMEZONE = "America/New_York"


def _run(args: list, cwd: Path) -> None:
    """Run one command of the manual steps and fail the task if it fails."""
    log = get_run_logger()
    log.info(f"{cwd.relative_to(ROOT).as_posix() or '.'}$ {' '.join(args)}")
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    for line in (done.stdout + done.stderr).strip().splitlines()[-3:]:
        log.info(line)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} exited with {done.returncode}")


@task(name="dbt build")
def dbt_build():
    _run([sys.executable, "-m", "dbt.cli.main", "build"], ROOT / "data_pipeline")


@task(name="diagnostic report")
def diagnostic_report():
    _run([sys.executable, "generate_report.py"], ROOT / "analytics" / "reports")


@task(name="dashboard")
def dashboard():
    _run([sys.executable, "generate_dashboard.py"], ROOT / "analytics" / "reports")


@flow(name="defects-scrap-monthly")
def monthly_pipeline():
    dbt_build()
    diagnostic_report()
    dashboard()


def monthly_deployment():
    """The monthly deployment definition. Returned, not applied: deploying or
    serving it is a separate, deliberate step."""
    return monthly_pipeline.to_deployment(
        name="monthly-first-weekday",
        schedule=RRule(MONTHLY_SCHEDULE, timezone=SCHEDULE_TIMEZONE),
    )


if __name__ == "__main__":
    monthly_pipeline()
