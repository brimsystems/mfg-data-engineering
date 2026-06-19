"""
Builds the eight source tables and writes them under data_source/raw/<system>/,
with a 200-row sample of each under data_source/samples/<system>/. The per-job
working table is archived under data_source/generate/truth/.

Usage: python -m data_source.generate.run_generator
"""
from pathlib import Path

import pandas as pd

from . import config as C
from .generators.machines import build_machines
from .generators.operators import build_operators, HR_COLUMNS
from .generators.part_catalog import build_part_catalog, CATALOG_COLUMNS
from .generators.shop_floor import run_shop_floor, erp_work_orders, mes_job_log, material_lots
from .generators.inspections import build_inspections
from .generators.scrap_events import build_scrap_events

_JOB_COLUMNS = ["work_order_id", "part_number", "part_revision", "machine_id", "operator_id", "shift",
                "order_date", "job_start", "job_end", "rush", "quantity", "run_position", "jobs_before",
                "hours_into_day", "after_gauge_change", "lot_age_days", "has_first_piece", "long_day",
                "f_deviation", "f_first_run", "f_gauge_change", "f_no_first_piece", "f_past_tenth_hour",
                "f_experience", "f_lot_age", "f_complexity", "defect_probability", "quantity_failed"]


def _save(df: pd.DataFrame, name: str, base_dir: Path, sample: bool = False) -> None:
    out_dir = base_dir / C.TABLE_SYSTEM_MAP[name]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}{'_sample' if sample else ''}.csv"
    df.to_csv(path, index=False, lineterminator="\n")
    print(f"  [{C.TABLE_SYSTEM_MAP[name]:>9}]  {path.name:<34} {len(df):>7,} rows")


def run() -> dict:
    operators = build_operators()
    parts, revisions = build_part_catalog()
    jobs, lots = run_shop_floor(parts, revisions, operators)
    orders = erp_work_orders(jobs, operators)
    job_log = mes_job_log(jobs, operators)
    inspections = build_inspections(jobs, operators)
    scrap = build_scrap_events(jobs)

    tables = {
        "machines":           build_machines(),
        "job_log":            job_log,
        "operators":          operators[HR_COLUMNS].assign(hire_date=operators["hire_date"].astype(str)),
        "material_lots":      material_lots(lots),
        "part_catalog":       parts[CATALOG_COLUMNS].assign(released_date=parts["released_date"].astype(str),
                                                            revision_date=parts["revision_date"].astype(str)),
        "production_orders":  orders,
        "inspection_records": inspections,
        "scrap_events":       scrap,
    }
    print(f"Full tables -> {C.RAW_DIR}")
    for name, df in tables.items():
        _save(df, name, C.RAW_DIR)
    print(f"Samples ({C.SAMPLE_SIZE} rows) -> {C.SAMPLES_DIR}")
    for name, df in tables.items():
        _save(df.head(C.SAMPLE_SIZE), name, C.SAMPLES_DIR, sample=True)

    C.TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    working = pd.DataFrame([{k: j[k] for k in _JOB_COLUMNS} | {"lot_id": j["lot"]["lot_id_clean"],
                                                              "lot_deviation_pct": j["lot"]["deviation_pct"]}
                            for j in jobs])
    working.to_csv(C.TRUTH_DIR / "jobs.csv", index=False, lineterminator="\n")
    revisions.assign(effective_date=revisions["effective_date"].astype(str)).to_csv(
        C.TRUTH_DIR / "revisions.csv", index=False, lineterminator="\n")
    operators.astype(str).to_csv(C.TRUTH_DIR / "operators.csv", index=False, lineterminator="\n")
    lots.assign(receipt_date=lots["receipt_date"].astype(str)).to_csv(
        C.TRUTH_DIR / "lots.csv", index=False, lineterminator="\n")
    print(f"Working tables -> {C.TRUTH_DIR}")
    return tables


if __name__ == "__main__":
    run()
