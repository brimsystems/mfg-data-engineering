"""The job-costing pipeline as a Prefect flow: dbt build, mart export, then the
deliverables. Each step is a task so a failure stops the run where it happened
and the log says which step it was.

    python -m analytics.src.flow              # dbt build -> export -> reports
    python -m analytics.src.flow --generate   # regenerate the source data first

The generator is a task too, but it runs only when asked: the raw extracts are
the inputs to the pipeline, not a product of it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from prefect import flow, task, get_run_logger

REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "data_pipeline"

REPORTS = [
    "analytics.reports.generate_data_quality_audit",
    "analytics.reports.generate_margin_diagnostic",
    "analytics.reports.generate_erp_screens",
    "analytics.reports.generate_job_cost_reporting",
    "analytics.reports.capture_screenshots",
]


def _run(cmd, cwd=REPO):
    logger = get_run_logger()
    logger.info("running: %s  (in %s)", " ".join(cmd), cwd)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        logger.info(result.stdout[-4000:])
    if result.returncode != 0:
        logger.error(result.stderr[-4000:])
        raise RuntimeError(f"step failed: {' '.join(cmd)}")


@task(name="generate source data")
def generate():
    _run([sys.executable, "-m", "data_source.generate.run_generator"])


@task(name="dbt build, all but the repricing queue", retries=0)
def dbt_build():
    _run([sys.executable, "-m", "dbt.cli.main", "build", "--profiles-dir", ".", "--exclude", "stg_remediation__repricing_decisions+"], cwd=PIPELINE)


@task(name="repricing review from the queue")
def repricing_review():
    _run([sys.executable, "-m", "data_source.generate.repricing_review"])


@task(name="dbt build, the decisions and the queue", retries=0)
def dbt_build_queue():
    _run([sys.executable, "-m", "dbt.cli.main", "build", "--profiles-dir", ".", "--select", "stg_remediation__repricing_decisions+"], cwd=PIPELINE)


@task(name="export marts")
def export_marts():
    _run([sys.executable, "-m", "analytics.src.export_marts"])


@task(name="render deliverable")
def render(module: str):
    _run([sys.executable, "-m", module])


@flow(name="job-costing-pipeline", log_prints=True)
def pipeline(regenerate: bool = False):
    if regenerate:
        generate()
    dbt_build()
    repricing_review()
    dbt_build_queue()
    export_marts()
    for module in REPORTS:
        render(module)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true", help="regenerate the source data before the build")
    args = ap.parse_args()
    pipeline(regenerate=args.generate)
