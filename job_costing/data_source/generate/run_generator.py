"""Generate the shop's ERP and machine-monitoring extracts.

Order of build: customers, work centers and rates, material and vendor price
history, parts and routings; quotes and standing prices; jobs with their truth;
the schedule; scrap and rework; labor, material, outside processing and the
machine-monitoring feed with the defects laid over them; the engagement's
artifacts; then the extracts under data_source/raw and the truth under
data_source/truth.

Run:  python -m data_source.generate.run_generator
"""
from __future__ import annotations

import json
import time
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config as C
from .generators import masters as M
from .generators import quotes_jobs as QJ
from .generators import transactions as TX
from .generators.costing import CostModel, blended_rate
from . import engagement as ENG

PUBLIC = {
    "part_master": ["part_number", "revision", "description", "material_spec", "stock_form", "part_family",
                    "customer_id", "status", "first_quote_date", "standing_price", "standing_price_date",
                    "own_product_flag", "list_price"],
    "routings": ["part_number", "revision", "op_seq", "work_center_id", "std_setup_hours", "std_run_min_per_piece",
                 "program_number", "last_updated"],
    "work_centers": ["work_center_id", "type", "monitored_flag", "machine_id"],
    "quotes": ["quote_id", "line", "break_seq", "part_number", "revision", "customer_id", "quantity", "estimator_id", "quote_date",
               "estimate_basis", "est_material", "est_setup_hours", "est_run_hours", "est_outside", "est_total_cost", "quoted_price",
               "status", "won_job_id"],
    "customers": ["customer_id", "name", "industry", "terms", "change_order_count_12m", "expedite_count_12m"],
    "labor_transactions": ["txn_id", "job_id", "op_seq", "work_center_id", "employee_id", "clock_on", "clock_off",
                           "type", "source", "hours"],
    "machine_monitoring": ["interval_id", "machine_id", "start_time", "end_time", "state", "program_number",
                           "cycle_count", "assigned_job_id"],
    "material_transactions": ["txn_id", "job_id", "material_spec", "quantity", "uom", "unit_cost", "issue_date", "source"],
    "outside_processing": ["po_id", "line", "vendor_id", "service_type", "job_id", "gl_account", "description",
                           "quantity", "unit_price", "order_date", "receipt_date", "invoice_amount"],
    "scrap_rework": ["event_id", "job_id", "op_seq", "type", "quantity", "reason_code", "reported_by", "event_date"],
}


def _write(df, name, cols=None):
    sub = C.TABLE_SYSTEM_MAP.get(name, "erp")
    out = C.RAW_DIR / sub
    out.mkdir(parents=True, exist_ok=True)
    d = df[cols] if cols else df
    d.to_csv(out / f"{name}.csv", index=False)
    C.SAMPLES_DIR.joinpath(sub).mkdir(parents=True, exist_ok=True)
    d.head(C.SAMPLE_SIZE).to_csv(C.SAMPLES_DIR / sub / f"{name}_sample.csv", index=False)


def _truth(df, name):
    C.TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".csv", ".parquet"):
        (C.TRUTH_DIR / f"{name}{ext}").unlink(missing_ok=True)
    if len(df) > 200_000:
        df.to_parquet(C.TRUTH_DIR / f"{name}.parquet", index=False)
    else:
        df.to_csv(C.TRUTH_DIR / f"{name}.csv", index=False)


def run():
    t0 = time.time()
    # a clean slate, so nothing from an earlier generation survives
    for d_ in (C.RAW_DIR, C.TRUTH_DIR):
        if d_.exists():
            for f in d_.rglob("*"):
                if f.is_file():
                    f.unlink()
    rng = np.random.default_rng(C.RANDOM_SEED)
    cust = M.customers(rng)
    wcs, wc_rates = M.work_centers(rng)
    mat_prices = M.material_prices(rng)
    vendors, vendor_prices = M.vendors(rng)
    parts, routings, programs = M.parts_and_routings(rng, cust, wcs)
    cm = CostModel(parts, routings, wcs, mat_prices, vendors, vendor_prices)
    plan = QJ.osp_plan(rng, cm, parts)
    top_customer = cust.sort_values("revenue_weight", ascending=False)["customer_id"].iloc[0]
    quotes, standing = QJ.quotes_and_prices(rng, cm, parts, plan, top_customer,
                                            cust.set_index("customer_id")["industry"].to_dict())
    own_std = QJ.own_product_prices(rng, cm, parts, plan)
    breaks = QJ.quote_breaks(rng, cm, quotes, plan)
    jobs = QJ.jobs(rng, cm, parts, routings, quotes, standing, own_std, plan, breaks)
    print(f"  masters, quotes and {len(jobs):,} jobs  ({time.time() - t0:.0f}s)")

    # the cost pools reallocate the same total the blended rate charged
    tp = tb = 0.0
    for j in jobs.itertuples():
        for o in j.ops:
            h = o["setup_hours"] + o["run_hours"] + o["change_order_hours"]
            tp += h * cm.pool_rate(o["work_center_id"], j.release_date); tb += h * blended_rate(j.release_date)
    pool_scale = tb / tp
    wcs["true_labor_rate"] = (wcs["true_labor_rate"] * pool_scale).round(2)
    wcs["true_burden_rate"] = (wcs["true_burden_rate"] * pool_scale).round(2)
    cm = CostModel(parts, routings, wcs, mat_prices, vendors, vendor_prices)

    # the floor
    emps = TX.employees(rng, wcs)
    ops, completed = TX.schedule(rng, jobs, wcs, emps)
    co_cust = cust.loc[cust["change_order_customer"], "customer_id"].iloc[0]
    TX.CHANGE_ORDER_CUSTOMER[0] = co_cust
    TX.TOP_CUSTOMER[0] = top_customer
    scrap = TX.scrap_rework(rng, jobs, ops)
    lab, shadow = TX.labor(rng, ops, jobs, wcs, scrap)
    mat, unissued = TX.material(rng, jobs, ops, cm, scrap)
    osp = TX.outside_processing(rng, jobs, ops, cm, plan)
    print(f"  schedule, scrap, labor ({len(lab):,}), material ({len(mat):,}), outside ({len(osp):,})  ({time.time() - t0:.0f}s)")
    mm = TX.machine_monitoring(rng, ops, wcs)
    # the extract is taken on the last day of the window: nothing dated after it exists yet
    cutoff = pd.Timestamp(C.END_DATE) + pd.Timedelta(days=1)
    lab = lab[lab["clock_on"] < cutoff].reset_index(drop=True)
    mat = mat[pd.to_datetime(mat["issue_date"]) < cutoff].reset_index(drop=True)
    scrap = scrap[pd.to_datetime(scrap["event_date"]) < cutoff].reset_index(drop=True)
    print(f"  machine monitoring {len(mm):,} intervals  ({time.time() - t0:.0f}s)")

    # completion from the schedule
    jobs["completed_date"] = [TX._ts(completed[j]).date() + timedelta(days=1) if TX._ts(completed[j]).date() + timedelta(days=1) <= C.END_DATE else None
                              for j in jobs["job_id"]]
    jobs["status"] = np.where(jobs["completed_date"].notna(), "completed", "in_process")

    # the engagement: what the cleanup produced and decided
    ENG.BREAKS[0] = breaks
    eng = ENG.build(rng, cm, parts, routings, wcs, jobs, ops, lab, shadow, mat, unissued, osp, scrap, mm, quotes,
                    standing, own_std, plan, cust, emps)
    routings_after = eng["routings_after"]

    # estimates carried to the job after the configuration change
    est_cols = ["est_material", "est_setup_hours", "est_run_hours", "est_outside", "est_total_cost"]
    for c in est_cols:
        jobs[c] = np.nan
    cm_after = CostModel(parts, routings_after, wcs, mat_prices, vendors, vendor_prices)
    std_effective = eng["std_effective"]
    own_idx = own_std.set_index("part_number")
    for i, j in jobs[jobs["release_date"] >= C.CONFIG_DATES["estimate_to_job"]].iterrows():
        if j["job_type"] == "new":
            # new quoted work: the quote line's estimate at the nearest break, per piece, times the ordered quantity
            e, _ = QJ.break_estimate(breaks, j["quote_id"], j["quantity"])
        elif j["job_type"] == "own_product":
            # own products: the standard cost, split the way the launch estimate was
            std = float(own_idx.loc[j["part_number"], "standard_cost"])
            launch = cm.estimate(j["part_number"], 100, own_idx.loc[j["part_number"], "standard_cost_date"], standards="true",
                                 material="actual", osp_base=plan[j["part_number"]])
            tot = launch["est_total_cost"]
            e = {"est_material": launch["est_material"] / tot * std * j["quantity"], "est_setup_hours": launch["est_setup_hours"] * j["quantity"] / 100,
                 "est_run_hours": launch["est_run_hours"] * j["quantity"] / 100, "est_outside": launch["est_outside"] / tot * std * j["quantity"],
                 "est_total_cost": std * j["quantity"]}
        else:
            # repeat parts: the current-cost estimate the pipeline computes monthly, at the month's
            # material prices and rates and the standards in force on the first of the month
            month_start = j["release_date"].replace(day=1)
            rates = "pool" if month_start >= C.CONFIG_DATES["rate_pools_live"] else "blended"
            model = cm_after if std_effective.get(j["part_number"], C.END_DATE + timedelta(days=1)) <= month_start else cm
            e = model.estimate(j["part_number"], j["quantity"], max(month_start, C.START_DATE), rates=rates, material="actual",
                               osp_base=plan[j["part_number"]])
        for c in est_cols:
            jobs.at[i, c] = round(e[c], 2)

    # the ERP's own actuals, from its transactions as recorded
    rate_of = {y: r for y, r in C.BLENDED_RATE.items()}
    lab_rec = lab[lab["job_id"].notna()].copy()
    lab_rec["cost"] = lab_rec["hours"] * lab_rec["clock_on"].dt.year.map(rate_of)
    jobs["actual_labor_hours"] = jobs["job_id"].map(lab_rec.groupby("job_id")["hours"].sum()).fillna(0).round(2)
    jobs["actual_labor_cost"] = jobs["job_id"].map(lab_rec.groupby("job_id")["cost"].sum()).fillna(0).round(2)
    mat["value"] = mat["quantity"] * mat["unit_cost"]
    jobs["actual_material"] = jobs["job_id"].map(mat.groupby("job_id")["value"].sum()).fillna(0).round(2)
    osp_rec = osp[osp["job_id"].notna() & osp["invoice_amount"].notna()]
    jobs["actual_outside"] = jobs["job_id"].map(osp_rec.groupby("job_id")["invoice_amount"].sum()).fillna(0).round(2)
    sc_rec = scrap[(~scrap["_unrecorded"]) & (scrap["type"] == "scrap") & scrap["job_id"].notna()]
    jobs["actual_scrap_qty"] = jobs["job_id"].map(sc_rec.groupby("job_id")["quantity"].sum()).fillna(0).astype(int)
    jobs["actual_total_cost"] = (jobs["actual_material"] + jobs["actual_labor_cost"] + jobs["actual_outside"]).round(2)

    # part master public fields
    parts["standing_price"] = parts["part_number"].map(
        lambda pn: round(standing.loc[pn, "standing_price_at_start"] * QJ._letters_between(C.START_DATE, C.END_DATE), 2)
        if pn in standing.index else np.nan)
    parts["standing_price_date"] = parts["part_number"].map(
        lambda pn: QJ._last_letter_date(C.END_DATE) if pn in standing.index else None)
    parts["list_price"] = parts["part_number"].map(own_std.set_index("part_number")["list_price"])
    parts.loc[parts["own_product_flag"], "status"] = "active"
    won_any = set(quotes.loc[quotes["status"] == "won", "part_number"])
    parts.loc[(parts["job_type"] == "new") & ~parts["part_number"].isin(won_any), "status"] = "quoted"

    # ── write the extracts ────────────────────────────────────────────────
    _write(parts, "part_master", PUBLIC["part_master"])
    _write(routings_after, "routings", PUBLIC["routings"])
    _write(wcs, "work_centers", PUBLIC["work_centers"])
    _write(wc_rates, "work_center_rates")
    # the quoting module's extract: one row per quote line and quantity break
    quote_rows = breaks.merge(quotes.drop(columns=["quantity", "est_material", "est_setup_hours", "est_run_hours", "est_outside",
                                                   "est_labor", "est_total_cost", "quoted_price"]), on=["quote_id", "line"])
    _write(quote_rows.sort_values(["quote_id", "line", "break_seq"]), "quotes", PUBLIC["quotes"])
    _write(cust, "customers", PUBLIC["customers"])
    _write(own_std, "own_product_standards")
    job_cols = ["job_id", "part_number", "revision", "customer_id", "quantity", "job_type", "quote_id", "release_date",
                "due_date", "completed_date", "status", "price"] + est_cols + \
               ["actual_material", "actual_labor_hours", "actual_labor_cost", "actual_outside", "actual_scrap_qty",
                "actual_total_cost"]
    _write(jobs, "jobs", job_cols)
    _write(lab, "labor_transactions", PUBLIC["labor_transactions"])
    _write(mm, "machine_monitoring", PUBLIC["machine_monitoring"])
    _write(mat, "material_transactions", PUBLIC["material_transactions"])
    _write(osp, "outside_processing", PUBLIC["outside_processing"])
    rec = scrap[~scrap["_unrecorded"]]
    _write(rec, "scrap_rework", PUBLIC["scrap_rework"])
    for name, df in eng["artifacts"].items():
        out = C.RAW_DIR / "remediation"; out.mkdir(parents=True, exist_ok=True)
        df.to_csv(out / f"{name}.csv", index=False)
    print(f"  extracts written  ({time.time() - t0:.0f}s)")

    # ── truth ─────────────────────────────────────────────────────────────
    _truth(parts[["part_number", "job_type", "weight_lb", "p1_cohort", "change_order_customer",
                  "estimator_bias_material", "outside_services"]], "parts_truth")
    _truth(routings[["part_number", "op_seq", "work_center_id", "work_center_group", "true_setup_hours",
                     "true_run_min_per_piece", "standard_stale", "standard_gap"]], "routings_truth")
    _truth(wcs[["work_center_id", "group", "lights_out_share", "true_labor_rate", "true_burden_rate", "attended_ratio"]],
           "work_centers_truth")
    _truth(standing.reset_index(), "standing_prices_truth")
    _truth(ops[["job_id", "op_seq", "work_center_id", "group", "monitored", "start_h", "end_h", "setup_hours",
                "run_hours", "change_order_hours", "employee_id"]], "ops_truth")
    _truth(lab[["txn_id", "_true_job_id", "_true_hours", "_t1_added", "_t3", "_t4", "_t5", "_t6_as_run", "_rework"]],
           "labor_truth")
    _truth(shadow, "t4_shadow_truth")
    _truth(mat[["txn_id", "_true_job_id", "_t8"]], "material_truth")
    _truth(unissued[["job_id", "material_spec", "quantity", "uom", "unit_cost", "issue_date"]], "material_unissued_truth")
    _truth(osp[["po_id", "_true_job_id"]], "osp_truth")
    _truth(scrap[["event_id", "_true_job_id", "type", "quantity", "_hours", "_unrecorded", "work_center_id", "op_seq"]],
           "scrap_truth")
    _truth(mm[["interval_id", "_true_job_id"]], "machine_truth")
    _truth(plan_df(plan), "osp_plan_truth")
    _truth(eng["current_cost_review"], "current_cost_truth")
    _truth(eng["own_product_review"], "own_product_truth")
    _truth(mat_prices, "material_prices_truth")
    _truth(vendor_prices, "vendor_prices_truth")
    _truth(vendors, "vendors_truth")
    job_truth = jobs[["job_id", "part_number", "quantity", "job_type", "release_date", "price"]].copy()
    tot = ops.groupby("job_id").agg(true_setup_hours=("setup_hours", "sum"), true_run_hours=("run_hours", "sum"),
                                    true_change_order_hours=("change_order_hours", "sum"))
    job_truth = job_truth.join(tot, on="job_id")
    _truth(job_truth, "jobs_truth")
    meta = {"pool_scale": pool_scale, "change_order_customer": co_cust, "generated_at": pd.Timestamp.now().isoformat()}
    (C.TRUTH_DIR / "generation_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"Generation complete in {time.time() - t0:.0f}s: {len(jobs):,} jobs, {len(lab):,} labor records, "
          f"{len(mm):,} machine intervals, {len(mat):,} material transactions, {len(osp):,} PO lines, "
          f"{len(rec):,} scrap/rework events recorded of {len(scrap):,}")


def plan_df(plan):
    return pd.DataFrame([(pn, s, v, b) for pn, items in plan.items() for s, v, b in items],
                        columns=["part_number", "service_type", "vendor_id", "base_price_per_piece"])


if __name__ == "__main__":
    run()
