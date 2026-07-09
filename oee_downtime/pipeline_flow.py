"""
pipeline_flow.py
The monthly flow: rebuild the warehouse, regenerate the analytics deliverables,
rescore and monitor the machine health indicator, and regenerate the ML
deliverables. Each step runs the same command as the manual steps in the README,
in the same order, so one run of the flow gives the same outputs.

  1. dbt build
  2. analytics report and dashboard generators
  3. ML scoring, then monitoring
  4. the four ML report generators

Training is not part of the flow. It stays manual and is triggered by the
monitoring verdict (RETRAIN), so the flow always scores with the model under
the production alias in the MLflow registry.

Schedule: monthly, on the first business day at 06:00. The schedule is defined
below as MONTHLY_SCHEDULE and attached in monthly_deployment(); this file does
not deploy or serve it.

Run once locally:  python pipeline_flow.py
"""
import subprocess
import sys
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.schedules import RRule

ROOT = Path(__file__).resolve().parent

# First business day of each month at 06:00 (iCalendar recurrence rule): of the
# month's weekdays, the first one.
MONTHLY_SCHEDULE = "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1;BYHOUR=6;BYMINUTE=0;BYSECOND=0"
SCHEDULE_TIMEZONE = "America/New_York"


def _run(args: list, cwd: Path) -> None:
    """Run one command of the manual steps and fail the task if it fails."""
    log = get_run_logger()
    log.info(f"{cwd.relative_to(ROOT).as_posix() or '.'}$ {' '.join(args)}")
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
    for line in tail:
        log.info(line)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} exited with {done.returncode}")


def _python(script: str, cwd: Path) -> None:
    _run([sys.executable, script], cwd)


@task(name="dbt build")
def dbt_build():
    _run([sys.executable, "-m", "dbt.cli.main", "build"], ROOT / "data_pipeline")


@task(name="analytics report")
def analytics_report():
    _python("generate_analytics_report.py", ROOT / "analytics" / "reports")


@task(name="analytics dashboard")
def analytics_dashboard():
    _python("generate_dashboard.py", ROOT / "analytics" / "dashboard")


@task(name="ml scoring")
def ml_scoring():
    _python("src/scoring.py", ROOT / "ml")


@task(name="ml monitoring")
def ml_monitoring():
    _python("src/monitoring.py", ROOT / "ml")


@task(name="ml reports")
def ml_reports():
    for script in ("generate_cmms_dashboard.py", "generate_model_overview.py",
                   "generate_ml_technical.py", "generate_monitoring_report.py"):
        _python(script, ROOT / "ml" / "reports")


@flow(name="oee-downtime-monthly")
def monthly_pipeline():
    dbt_build()
    analytics_report()
    analytics_dashboard()
    ml_scoring()
    ml_monitoring()
    ml_reports()


def monthly_deployment():
    """The monthly deployment definition. Returned, not applied: deploying or
    serving it is a separate, deliberate step."""
    return monthly_pipeline.to_deployment(
        name="monthly-first-business-day",
        schedule=RRule(MONTHLY_SCHEDULE, timezone=SCHEDULE_TIMEZONE),
    )


if __name__ == "__main__":
    monthly_pipeline()
