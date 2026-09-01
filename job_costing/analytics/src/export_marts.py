"""Export the dbt marts the reports and dashboards read from the DuckDB warehouse
to parquet.

dbt builds the models (data_pipeline/models); this step writes the ones the
analytics code reads to analytics/data/marts/<model>.parquet, so the report
generators and the dashboard never query the warehouse directly and every number
in a deliverable traces to a dbt model.

Exported: every mart (fct_*, mart_*), every profiling table (prof_*), every
data-quality model (dq_*) and the intermediate tables the deliverables cite
(int_current_cost, int_labor_cleaned, int_scan_coverage_weekly,
int_machine_hours_by_job).

Run after `dbt build`:  python -m analytics.src.export_marts
"""
from __future__ import annotations

from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
WAREHOUSE = REPO / "data_source" / "job_costing.duckdb"
MARTS = REPO / "analytics" / "data" / "marts"

EXTRA = ["int_current_cost", "int_labor_cleaned", "int_scan_coverage_weekly", "int_machine_hours_by_job",
         "int_labor_hours_by_job", "int_estimate_by_job", "int_osp_by_job", "int_job_op_progress", "int_machine_age_cycle",
         "int_job_revision", "int_second_setup", "int_inprogress_flag"]


def run():
    MARTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    tables = [r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'main' and table_type = 'BASE TABLE'").fetchall()]
    chosen = sorted(t for t in tables if t.startswith(("fct_", "mart_", "prof_", "dq_")) or t in EXTRA)
    # a table renamed or dropped since the last export leaves no file behind
    for old in MARTS.glob("*.parquet"):
        if old.stem not in chosen:
            old.unlink()
    for t in chosen:
        out = MARTS / f"{t}.parquet"
        con.execute(f"copy (select * from {t}) to '{out.as_posix()}' (format parquet)")
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
        print(f"  {t:40s} {n:>10,} rows")
    print(f"exported {len(chosen)} tables to {MARTS}")


if __name__ == "__main__":
    run()
