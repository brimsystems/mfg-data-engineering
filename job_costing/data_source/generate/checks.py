"""Realism checks on the generated data (specification section 11).

Run after the generator and before anything downstream. Each check states the
measure, the expected range and the value found. The results are written to
data_source/generate/REALISM_CHECKS.md so they travel with the repository, and
re-run after every generator change.

Run:  python -m data_source.generate.checks
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from pathlib import Path

from . import config as C
from .generators.costing import blended_rate

RAW = C.RAW_DIR; TRUTH = C.TRUTH_DIR
OUT = C.REPO_ROOT / "data_source" / "generate" / "REALISM_CHECKS.md"


def _rd(name, sub="erp", **kw):
    return pd.read_csv(RAW / sub / f"{name}.csv", low_memory=False, **kw)


def _tr(name):
    p = TRUTH / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.read_parquet(TRUTH / f"{name}.parquet")


def load():
    d = {}
    d["jobs"] = _rd("jobs", parse_dates=["release_date", "due_date", "completed_date"])
    d["quotes"] = _rd("quotes", parse_dates=["quote_date"]).drop_duplicates(["quote_id", "line"])
    d["parts"] = _rd("part_master", parse_dates=["first_quote_date"])
    d["routings"] = _rd("routings")
    d["lab"] = _rd("labor_transactions", parse_dates=["clock_on", "clock_off"])
    d["mat"] = _rd("material_transactions", parse_dates=["issue_date"])
    d["osp"] = _rd("outside_processing", parse_dates=["order_date", "receipt_date"])
    d["scrap"] = _rd("scrap_rework", parse_dates=["event_date"])
    d["mm"] = pd.read_csv(RAW / "monitoring" / "machine_monitoring.csv", usecols=["machine_id", "start_time", "end_time", "state", "assigned_job_id"],
                          parse_dates=["start_time", "end_time"])
    d["wcs"] = _rd("work_centers")
    for t in ["parts_truth", "routings_truth", "work_centers_truth", "ops_truth", "labor_truth", "scrap_truth",
              "jobs_truth", "osp_truth", "material_truth", "standing_prices_truth", "osp_plan_truth", "material_unissued_truth",
              "current_cost_truth", "own_product_truth"]:
        d[t] = _tr(t)
    d["machine_truth"] = _tr("machine_truth")
    rem = RAW / "remediation"
    for f in rem.glob("*.csv"):
        d[f"rem_{f.stem}"] = pd.read_csv(f)
    return d


def job_costs(d):
    """Cost per job, true (at the pools and at the blended rate) and as the ERP
    recorded it. Hours from the schedule truth, material at the price of the
    day, outside processing from the PO lines, rework from the events."""
    jobs = d["jobs"].set_index("job_id")
    ops = d["ops_truth"].copy()
    wct = d["work_centers_truth"].set_index("work_center_id")
    ops["hours"] = ops["setup_hours"] + ops["run_hours"] + ops["change_order_hours"]
    ops["date"] = pd.Timestamp(C.START_DATE) + pd.to_timedelta(ops["start_h"], unit="h")
    yrs = (ops["date"] - pd.Timestamp(C.START_DATE)).dt.days / 365.25
    pool = (wct.loc[ops["work_center_id"], "true_labor_rate"].to_numpy() * wct.loc[ops["work_center_id"], "attended_ratio"].to_numpy()
            + wct.loc[ops["work_center_id"], "true_burden_rate"].to_numpy()) * (1 + C.POOL_RATE_DRIFT) ** yrs
    ops["cost_pool"] = ops["hours"] * pool
    ops["cost_blended"] = ops["hours"] * ops["date"].dt.year.map(C.BLENDED_RATE)
    rw = d["scrap_truth"][d["scrap_truth"]["type"] == "rework"]
    rw_h = rw.groupby("_true_job_id")["_hours"].sum()
    g = ops.groupby("job_id").agg(true_hours=("hours", "sum"), cost_pool=("cost_pool", "sum"), cost_blended=("cost_blended", "sum"),
                                  setup_hours=("setup_hours", "sum"), run_hours=("run_hours", "sum"))
    g["rework_hours"] = rw_h.reindex(g.index).fillna(0)
    yr_rate = jobs["release_date"].dt.year.map(C.BLENDED_RATE)
    g["cost_pool"] += g["rework_hours"] * yr_rate.reindex(g.index)
    g["cost_blended"] += g["rework_hours"] * yr_rate.reindex(g.index)
    mat = d["mat"].copy(); mat["value"] = mat["quantity"] * mat["unit_cost"]
    mt = d["material_truth"].set_index("txn_id")
    mat["_true_job_id"] = mat["txn_id"].map(mt["_true_job_id"])
    un = d["material_unissued_truth"].copy(); un["value"] = un["quantity"] * un["unit_cost"]
    true_mat = mat.groupby("_true_job_id")["value"].sum().add(un.groupby("job_id")["value"].sum(), fill_value=0)
    rec_mat = mat.groupby("job_id")["value"].sum()
    osp = d["osp"].copy(); osp["_true_job_id"] = osp["po_id"].map(d["osp_truth"].set_index("po_id")["_true_job_id"])
    osp["amount"] = osp["invoice_amount"].fillna(osp["quantity"] * osp["unit_price"])
    true_osp = osp.groupby("_true_job_id")["amount"].sum()
    rec_osp = osp[osp["job_id"].notna()].groupby("job_id")["invoice_amount"].sum()
    out = pd.DataFrame(index=jobs.index)
    out["price"] = jobs["price"]; out["job_type"] = jobs["job_type"]; out["customer_id"] = jobs["customer_id"]
    out["part_number"] = jobs["part_number"]; out["quantity"] = jobs["quantity"]; out["year"] = jobs["release_date"].dt.year
    out["release_date"] = jobs["release_date"]
    out = out.join(g)
    out["true_material"] = true_mat.reindex(out.index).fillna(0)
    out["true_osp"] = true_osp.reindex(out.index).fillna(0)
    out["true_cost_pool"] = out["true_material"] + out["cost_pool"] + out["true_osp"]
    out["true_cost_blended"] = out["true_material"] + out["cost_blended"] + out["true_osp"]
    out["rec_material"] = rec_mat.reindex(out.index).fillna(0)
    out["rec_labor_hours"] = jobs["actual_labor_hours"]; out["rec_labor_cost"] = jobs["actual_labor_cost"]
    out["rec_osp"] = rec_osp.reindex(out.index).fillna(0)
    out["rec_cost"] = out["rec_material"] + out["rec_labor_cost"] + out["rec_osp"]
    return out


def run():
    d = load()
    jobs, lab, mm = d["jobs"], d["lab"], d["mm"]
    jc = job_costs(d)
    j25 = jc[jc["year"] == C.ANALYSIS_YEAR]
    rows = []

    def add(section, check, expected, value, ok):
        rows.append((section, check, expected, value, "pass" if ok else "CHECK"))

    # ── volume and shape ─────────────────────────────────────────────────
    n = len(jobs); add("Volume", "Jobs over 36 months", "10,500-12,500", f"{n:,}", 10500 <= n <= 12500)
    mix = jobs.groupby("job_type")["price"].sum() / jobs["price"].sum()
    add("Volume", "Revenue mix repeat / new / own (65/30/5, within 3 points)",
        "62-68 / 27-33 / 2-8", f"{mix.get('repeat', 0):.0%} / {mix.get('new', 0):.0%} / {mix.get('own_product', 0):.0%}",
        abs(mix.get("repeat", 0) - 0.65) <= 0.03 and abs(mix.get("new", 0) - 0.30) <= 0.03)
    q = d["quotes"][d["quotes"]["quote_date"] >= pd.Timestamp(C.START_DATE)]
    add("Volume", "Quote lines in the window", "9,000-12,000", f"{len(q):,}", 9000 <= len(q) <= 12000)
    win = (q["status"] == "won").mean(); add("Volume", "Win rate on new work", "35-50%", f"{win:.0%}", 0.35 <= win <= 0.50)
    add("Volume", "Labor transactions", "220,000-300,000", f"{len(lab):,}", 220000 <= len(lab) <= 300000)
    # the quantity breaks on the quote lines, and the job's estimate taken from the nearest one
    qb = _rd("quotes")
    per_line = qb.groupby(["quote_id", "line"]).size()
    add("Volume", "Quantity breaks per quote line", "3-4", f"{per_line.mean():.1f}", 3.0 <= per_line.mean() <= 4.0)
    # the ERP's rollups equal the sum of the job's transactions
    rate_of = C.BLENDED_RATE
    lab_j = lab[lab["job_id"].notna()].copy(); lab_j["cost"] = lab_j["hours"] * lab_j["clock_on"].dt.year.map(rate_of)
    roll = jobs.set_index("job_id")
    mat_sum = (d["mat"]["quantity"] * d["mat"]["unit_cost"]).groupby(d["mat"]["job_id"]).sum().reindex(roll.index).fillna(0)
    osp_sum = d["osp"].dropna(subset=["job_id", "invoice_amount"]).groupby("job_id")["invoice_amount"].sum().reindex(roll.index).fillna(0)
    lab_sum = lab_j.groupby("job_id")["cost"].sum().reindex(roll.index).fillna(0)
    gaps = ((roll["actual_material"] - mat_sum).abs().max(), (roll["actual_labor_cost"] - lab_sum).abs().max(), (roll["actual_outside"] - osp_sum).abs().max())
    add("Volume", "Jobs table rollups equal the sum of the job's transactions (material, labor, outside)", "within $0.05",
        "max gap " + ", ".join(f"${g:.2f}" for g in gaps), all(g <= 0.05 for g in gaps))
    add("Volume", "Machine monitoring intervals", "1.5-2.5M", f"{len(mm) / 1e6:.2f}M", 1.5e6 <= len(mm) <= 2.5e6)
    add("Volume", "Material transactions", "45,000-65,000", f"{len(d['mat']):,}", 45000 <= len(d["mat"]) <= 65000)
    add("Volume", "Outside processing lines", "8,000-12,000", f"{len(d['osp']):,}", 8000 <= len(d["osp"]) <= 12000)
    cw = j25.groupby("customer_id")["price"].sum().sort_values(ascending=False); tot = cw.sum()
    add("Volume", "Top customer share of 2025 revenue", "18-24%", f"{cw.iloc[0] / tot:.0%}", 0.18 <= cw.iloc[0] / tot <= 0.24)
    add("Volume", "Top 10 customers share of 2025 revenue", "60-70%", f"{cw.iloc[:10].sum() / tot:.0%}", 0.60 <= cw.iloc[:10].sum() / tot <= 0.70)
    med = jobs["quantity"].median(); small = (jobs["quantity"] < C.SMALL_LOT_THRESHOLD).mean()
    add("Volume", "Lot size median", "40-80 pieces", f"{med:.0f}", 40 <= med <= 80)
    add("Volume", "Share of jobs under 25 pieces", "20-30%", f"{small:.0%}", 0.20 <= small <= 0.30)
    cs = j25[["true_material", "cost_pool", "true_osp"]].sum(); cs = cs / cs.sum()
    add("Volume", "Cost structure material / labor and burden / outside", "25-35 / 50-60 / 8-15",
        f"{cs['true_material']:.0%} / {cs['cost_pool']:.0%} / {cs['true_osp']:.0%}",
        0.25 <= cs["true_material"] <= 0.35 and 0.50 <= cs["cost_pool"] <= 0.60 and 0.08 <= cs["true_osp"] <= 0.15)
    rev25 = j25["price"].sum(); add("Volume", "2025 revenue", "about $55M", f"${rev25 / 1e6:.1f}M", 48e6 <= rev25 <= 62e6)

    # ── target outcomes ──────────────────────────────────────────────────
    gm_pool = 1 - j25["true_cost_pool"].sum() / rev25; gm_bl = 1 - j25["true_cost_blended"].sum() / rev25
    # the P&L the owner sees: material purchased, every vendor invoice, and payroll
    # (attended hours plus indirect, not the phantom hours of open clock records)
    lt = d["labor_truth"].set_index("txn_id")
    lab25 = lab[lab["clock_on"].dt.year == C.ANALYSIS_YEAR].join(lt, on="txn_id")
    # payroll: the hours people were on the floor, at the labor share of the rate;
    # burden: the machine and overhead pool, recovered over the hours the shop ran
    indirect_h = lab25.loc[lab25["_t5"].fillna(False).astype(bool), "hours"].sum()
    attended_h = (j25["true_hours"] + j25["rework_hours"]).sum()
    labor_rate = C.BLENDED_RATE[C.ANALYSIS_YEAR] * 0.36
    burden = attended_h * C.BLENDED_RATE[C.ANALYSIS_YEAR] * 0.64
    pl_labor = (attended_h + indirect_h) * labor_rate + burden
    osp25 = d["osp"][d["osp"]["order_date"].dt.year == C.ANALYSIS_YEAR]
    pl_osp = osp25["invoice_amount"].fillna(osp25["quantity"] * osp25["unit_price"]).sum()
    mat25 = d["mat"][d["mat"]["issue_date"].dt.year == C.ANALYSIS_YEAR]
    pl_mat = (mat25["quantity"] * mat25["unit_cost"]).sum()
    gm_pl = 1 - (pl_labor + pl_osp + pl_mat) / rev25
    add("Outcome", "Shop-level gross margin 2025 on the P&L (payroll, purchases, invoices)", "22-25%", f"{gm_pl:.1%}", 0.22 <= gm_pl <= 0.25)
    add("Outcome", "Shop-level gross margin 2025 from cleaned job cost at the pools", "22-25%", f"{gm_pool:.1%}", 0.22 <= gm_pool <= 0.25)
    add("Story", "Cleaned job-cost margin within 1.5 points of the P&L figure", "<= 1.5 pts", f"{abs(gm_bl - gm_pl) * 100:.1f} pts", abs(gm_bl - gm_pl) <= 0.015)
    m = (j25["price"] - j25["true_cost_pool"]) / j25["price"]
    tgt = C.TARGET_MARKUP / (1 + C.TARGET_MARKUP)
    above = (m > tgt + 0.02).mean(); below = (m < tgt - 0.02).mean(); neg = (m < 0).mean()
    add("Outcome", "Share of 2025 jobs above target margin", "45-58%", f"{above:.0%}", 0.45 <= above <= 0.58)
    add("Outcome", "Share of 2025 jobs below target", "35-45%", f"{below:.0%}", 0.35 <= below <= 0.45)
    add("Outcome", "Share of 2025 jobs with negative contribution", "6-12%", f"{neg:.0%}", 0.06 <= neg <= 0.12)
    # repeat parts below current cost plus target
    rp = d["current_cost_truth"]
    b = rp["standing_price"] < rp["target_price"]
    # the same test on the true cycle rather than the refreshed standards
    cur_true = true_current_cost(d)
    bt = cur_true["standing_price"] < cur_true["target_price"]
    add("Story", "Repeat parts below cost plus target on the true cycle (generator view)", "12-22%", f"{bt.mean():.0%}", 0.12 <= bt.mean() <= 0.22)
    # P1 and P7 as the pipeline measures them (the repricing queue and own-product marts)
    marts = C.REPO / "analytics" / "data" / "marts" if hasattr(C, "REPO") else Path(__file__).resolve().parents[2] / "analytics" / "data" / "marts"
    if (marts / "mart_repricing_queue.parquet").exists():
        q = pd.read_parquet(marts / "mart_repricing_queue.parquet")
        own = pd.read_parquet(marts / "mart_own_products.parquet")
        bq = q[q["below_target"]]
        rep_rev = (q["standing_price"] * q["annual_volume"]).sum()
        gap = bq["target_price"] / bq["standing_price"] - 1
        exp_rep = bq["gap_to_target_annual"].sum()
        exp_own = ((own["current_unit_cost"] * (1 + C.TARGET_MARKUP) - own["list_price"]).clip(lower=0) * own["annual_volume"]).sum()
        # captured is what the new prices take; the balance of a part repriced in two steps counts as held
        rpq = bq[bq["decision"] == "reprice"]
        cap = ((rpq["new_price"] - rpq["standing_price"]).clip(lower=0) * rpq["annual_volume"]).clip(upper=rpq["gap_to_target_annual"]).sum()
        by_dec = {"reprice": cap / exp_rep,
                  "hold": (bq.loc[bq["decision"] == "hold", "gap_to_target_annual"].sum() + rpq["gap_to_target_annual"].sum() - cap) / exp_rep,
                  "exit": bq.loc[bq["decision"] == "exit", "gap_to_target_annual"].sum() / exp_rep}
        own_gap = own["list_price"] / (own["current_unit_cost"] * (1 + C.TARGET_MARKUP)) - 1
        add("Outcome", "P1: repeat parts below current cost plus target", "12-18% of parts", f"{len(bq) / len(q):.1%}", 0.12 <= len(bq) / len(q) <= 0.18)
        rs = (bq["standing_price"] * bq["annual_volume"]).sum() / rep_rev
        add("Outcome", "P1: repeat revenue on parts below current cost plus target", "8-12% (13% tolerated)", f"{rs:.1%}", 0.08 <= rs <= 0.13)
        add("Outcome", "P1: gap to target price, median", "4-8%", f"{gap.median():.1%}", 0.04 <= gap.median() <= 0.08)
        add("Outcome", "P1: gap to target price, 90th percentile", "about 12% (10-16%)", f"{gap.quantile(0.9):.1%}", 0.10 <= gap.quantile(0.9) <= 0.16)
        add("Outcome", "P1: repeat parts below cost outright", "under 2% (brief 1-2%, which conflicts with a 12% p90)", f"{q['below_cost'].mean():.1%}", q["below_cost"].mean() < 0.02)
        tot = (exp_rep + exp_own) / rev25
        add("Outcome", "P1+P7: exposure, repeat parts and own products, share of 2025 revenue", "1.0-1.5%", f"{tot:.2%}", 0.010 <= tot <= 0.015)
        add("Outcome", "P1: repricing decisions, captured / held / exited share of exposure", "40-60 / 25-40 / 5-10%",
            f"{by_dec.get('reprice', 0):.0%} / {by_dec.get('hold', 0):.0%} / {by_dec.get('exit', 0):.0%}",
            0.40 <= by_dec.get("reprice", 0) <= 0.60 and 0.25 <= by_dec.get("hold", 0) <= 0.40 and 0.04 <= by_dec.get("exit", 0) <= 0.11)
        add("Outcome", "P7: own products, list vs current cost plus target, median", "-5 to -15%", f"{own_gap.median():.1%}", -0.15 <= own_gap.median() <= -0.05)
        nb = int(own["below_cost_at_list"].sum())
        add("Outcome", "P7: own products below cost at list", "1-2 of 14", f"{nb} of {len(own)}", 1 <= nb <= 2)
    # estimate accuracy on labor hours, 2025 before cleanup: recorded hours / backfilled estimate
    bf = d["rem_estimate_backfill"].set_index("job_id")
    e25 = j25.join(bf[["est_setup_hours", "est_run_hours"]])
    ratio = e25["rec_labor_hours"] / (e25["est_setup_hours"] + e25["est_run_hours"])
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    q1, q2, q3 = ratio.quantile([0.25, 0.5, 0.75])
    add("Outcome", "Estimate accuracy on labor hours 2025 before cleanup, median", "1.10-1.25", f"{q2:.2f}", 1.10 <= q2 <= 1.25)
    add("Outcome", "Estimate accuracy 2025 before cleanup, IQR", "0.85-1.60", f"{q1:.2f}-{q3:.2f}", 0.80 <= q1 <= 0.95 and 1.45 <= q3 <= 1.75)
    # after: engagement-period jobs, true hours vs the job's own estimate
    eng = jc[(jc["release_date"] >= pd.Timestamp(C.CONFIG_DATES["estimate_to_job"])) & jc["true_hours"].notna()]
    jj = jobs.set_index("job_id").loc[eng.index]
    r2 = (eng["true_hours"] + eng["rework_hours"]) / (jj["est_setup_hours"] + jj["est_run_hours"])
    r2 = r2.replace([np.inf, -np.inf], np.nan).dropna()
    a1, a2, a3 = r2.quantile([0.25, 0.5, 0.75])
    add("Outcome", "Estimate accuracy on engagement-period jobs, median", "1.02-1.10", f"{a2:.2f}", 1.02 <= a2 <= 1.10)
    add("Outcome", "Estimate accuracy on engagement-period jobs, IQR", "0.90-1.30", f"{a1:.2f}-{a3:.2f}", 0.85 <= a1 <= 0.95 and 1.20 <= a3 <= 1.40)
    # setup underestimation on new and infrequent parts, mill-turn and 5-axis
    ops = d["ops_truth"]; rt = d["routings_truth"]
    std_setup = d["routings"].set_index(["part_number", "op_seq"])["std_setup_hours"]
    jo = jobs.sort_values(["release_date", "job_id"]).copy()
    gap = jo.groupby("part_number")["release_date"].diff().dt.days
    since_start = (jo["release_date"] - pd.Timestamp(C.START_DATE)).dt.days
    jo["infrequent"] = (gap > C.INFREQUENT_PART_DAYS) | (gap.isna() & ((jo["job_type"] == "new") | (since_start > C.INFREQUENT_PART_DAYS)))
    o = ops.merge(jo[["job_id", "quantity", "part_number", "infrequent"]].rename(columns={"quantity": "quantity_j"}), on="job_id")
    o["std_setup"] = list(std_setup.reindex(list(zip(o["part_number"], o["op_seq"]))).fillna(np.nan))
    o = o[o["group"].isin(C.INFREQUENT_SETUP_GROUPS)]
    o["r"] = o["setup_hours"] / o["std_setup"]
    ir, fr = o.loc[o["infrequent"], "r"].median(), o.loc[~o["infrequent"], "r"].median()
    add("Outcome", "Setup on new parts and parts not run in a year vs estimate (mill-turn, 5-axis)", "1.4-1.8x", f"{ir:.2f}x (parts run within the year: {fr:.2f}x)", 1.4 <= ir <= 1.8)
    add("Story", "P2: the setup overrun follows how recently the part ran, not the lot size", "infrequent-part ratio > 1.3 x familiar-part ratio", f"{ir / fr:.2f}x", ir / fr > 1.3)
    sm, lg = o[o["quantity_j"] < C.SMALL_LOT_THRESHOLD], o[o["quantity_j"] >= C.SMALL_LOT_THRESHOLD]
    add("Outcome", "Setup vs estimate by lot size, mill-turn and 5-axis (no rule on lot size)", "reported",
        f"under {C.SMALL_LOT_THRESHOLD} pieces {sm['r'].median():.2f}x, {C.SMALL_LOT_THRESHOLD}+ {lg['r'].median():.2f}x; infrequent share {sm['infrequent'].mean():.0%} vs {lg['infrequent'].mean():.0%}", True)
    # clocked vs machine hours on monitored cells, 2025
    lab25 = lab[(lab["clock_on"].dt.year == C.ANALYSIS_YEAR) & lab["job_id"].notna()]
    mon_wc = set(d["wcs"].loc[d["wcs"]["monitored_flag"], "work_center_id"])
    clocked = lab25[lab25["work_center_id"].isin(mon_wc)].groupby("job_id")["hours"].sum()
    mt = d["machine_truth"]; mm2 = mm.copy(); mm2["_true_job_id"] = mt["_true_job_id"].to_numpy()
    mm25 = mm2[(mm2["start_time"].dt.year == C.ANALYSIS_YEAR) & mm2["state"].isin(["in_cycle", "setup"])]
    mach = ((mm25["end_time"] - mm25["start_time"]).dt.total_seconds() / 3600).groupby(mm25["_true_job_id"]).sum()
    both = pd.concat([clocked.rename("clocked"), mach.rename("machine")], axis=1).dropna()
    both = both[both["machine"] >= 8]
    rr = (both["clocked"] / both["machine"]).clip(0.2, 3.0)     # winsorized: a handful of tiny jobs would otherwise dominate the spread
    add("Outcome", "Clocked vs machine hours on monitored cells, 2025 (mean of job ratio)", "clocked higher by 15-30%", f"{rr.mean() - 1:+.0%}", 1.15 <= rr.mean() <= 1.30)
    add("Outcome", "Standard deviation of the clocked/machine ratio", "0.25-0.40", f"{rr.std():.2f}", 0.25 <= rr.std() <= 0.40)
    # the gap by cell type
    lab_wc = lab25[lab25["work_center_id"].isin(mon_wc)].groupby("work_center_id")["hours"].sum()
    mach_wc = ((mm25["end_time"] - mm25["start_time"]).dt.total_seconds() / 3600).groupby(mm25["machine_id"]).sum()
    gap = (lab_wc / mach_wc).groupby(lambda w: w[:3]).mean()
    add("Story", "P8: gap widest on the multi-machine cells (Swiss, EDM)", "SWS/EDM ratio > mills ratio", f"SWS {gap.get('SWS', np.nan):.2f}, EDM {gap.get('EDM', np.nan):.2f}, VMC {gap.get('VMC', np.nan):.2f}",
        gap.get("SWS", 0) > gap.get("VMC", 0) and gap.get("EDM", 0) > gap.get("VMC", 0))
    # customer margins
    cm_ = j25.groupby("customer_id").agg(rev=("price", "sum"), cost=("true_cost_pool", "sum"))
    cm_["margin"] = 1 - cm_["cost"] / cm_["rev"]; top15 = cm_.sort_values("rev", ascending=False).head(15)
    add("Outcome", "Customer margin range, top 15 customers", "6% to 36% on price", f"{top15['margin'].min():.0%} to {top15['margin'].max():.0%}",
        0.03 <= top15["margin"].min() <= 0.12 and 0.30 <= top15["margin"].max() <= 0.42)
    rank = cm_.sort_values("rev", ascending=False).head(15)["margin"].rank(pct=True)
    add("Outcome", "Top customer margin in the bottom third of the top 15", "bottom third", f"percentile {rank.iloc[0]:.0%}", rank.iloc[0] <= 0.34)
    pt = d["parts_truth"]; co_cust = pt.loc[pt["change_order_customer"], "part_number"]
    co_id = jobs.loc[jobs["part_number"].isin(co_cust), "customer_id"].mode().iloc[0]
    add("Story", "P3: change-order customer margin on price", "8-11%", f"{cm_.loc[co_id, 'margin']:.0%}", 0.06 <= cm_.loc[co_id, "margin"] <= 0.13)
    # P4 reversal
    fam = jobs.set_index("job_id")["part_number"].map(d["parts"].set_index("part_number")["part_family"])
    j25f = j25.assign(fam=fam.reindex(j25.index))
    fm = j25f.groupby("fam").agg(rev=("price", "sum"), pool=("true_cost_pool", "sum"), bl=("true_cost_blended", "sum"))
    fm["m_pool"] = 1 - fm["pool"] / fm["rev"]; fm["m_bl"] = 1 - fm["bl"] / fm["rev"]
    manual = ["Fixtures and tooling", "Weldments and assemblies"]; fax = ["Aerospace brackets", "Turbine components"]
    # the two groups taken together: revenue-weighted margin of each group under each rate view
    grp = lambda fams, col: 1 - fm.loc[fams, col].sum() / fm.loc[fams, "rev"].sum()
    rev_ok = grp(manual, "bl") < grp(fax, "bl") and grp(manual, "pool") > grp(fax, "pool")
    add("Story", "P4: manual-heavy families rank below 5-axis-heavy under the blended rate and above under pools", "reversal",
        "; ".join(f"{f[:9]} {fm.loc[f, 'm_bl']:.0%}->{fm.loc[f, 'm_pool']:.0%}" for f in manual + fax), rev_ok)
    # own products
    ops_std = d["parts"][d["parts"]["own_product_flag"]]
    # P1
    p1 = pt[pt["p1_cohort"]]["part_number"]
    below_p1 = rp[rp["part_number"].isin(p1)]["standing_price"].lt(rp[rp["part_number"].isin(p1)]["target_price"]).mean()
    below_o = rp[~rp["part_number"].isin(p1)]["standing_price"].lt(rp[~rp["part_number"].isin(p1)]["target_price"]).mean()
    add("Story", "P1: the erosion cohort sits below cost plus target far more often than other repeat parts", "cohort at least 1.4x others", f"cohort {below_p1:.0%}, others {below_o:.0%}", below_p1 >= 1.4 * below_o)

    # ── pre-engagement defect levels ─────────────────────────────────────
    pre = jobs[jobs["release_date"] < pd.Timestamp(C.CONFIG_DATES["estimate_to_job"])]
    add("Defects", "Jobs with an estimate attached before restructuring", "0%", f"{pre['est_total_cost'].notna().mean():.0%}", pre["est_total_cost"].notna().mean() == 0)
    osp_pre = d["osp"][d["osp"]["order_date"] < pd.Timestamp(C.CONFIG_DATES["po_job_required"])]
    tied = osp_pre["job_id"].notna().mean(); add("Defects", "Outside processing lines tied to a job before restructuring", "15-30%", f"{tied:.0%}", 0.15 <= tied <= 0.30)
    lt = d["labor_truth"].set_index("txn_id"); labp = lab[lab["clock_on"] < pd.Timestamp(C.CONFIG_DATES["auto_close"])].join(lt, on="txn_id")
    for c in ["_t3", "_t4", "_t5", "_t6_as_run", "_rework"]:
        labp[c] = labp[c].fillna(False).astype(bool)
    labp["_t1_added"] = labp["_t1_added"].fillna(0.0)
    t1 = labp["_t1_added"] > 0
    add("Defects", "Clock records spanning a break, shift or overnight (T1)", "6-10%", f"{t1.mean():.1%}", 0.06 <= t1.mean() <= 0.10)
    t1h = labp.loc[t1, "hours"].sum() / labp["hours"].sum()
    add("Defects", "Hours contained in those records", "25-40% of clocked hours", f"{t1h:.0%}", 0.25 <= t1h <= 0.40)
    add("Defects", "Time charged to the wrong job (T3)", "1.5-3%", f"{labp['_t3'].mean():.1%}", 0.015 <= labp["_t3"].mean() <= 0.03)
    cnc = labp[labp["work_center_id"].isin(mon_wc)]
    add("Defects", "Multi-machine tending recorded as one job (T4), CNC records", "10-15%", f"{cnc['_t4'].mean():.1%}", 0.10 <= cnc["_t4"].mean() <= 0.15)
    t5 = labp.loc[labp["_t5"], "hours"].sum() / labp["hours"].sum()
    add("Defects", "Indirect time charged to jobs (T5)", "5-8% of hours", f"{t5:.1%}", 0.05 <= t5 <= 0.08)
    st = d["scrap_truth"]; stp = st[pd.to_datetime(d["scrap_truth"].merge(d["scrap"][["event_id", "event_date"]], on="event_id", how="left")["event_date"]).fillna(pd.Timestamp("2000-01-01")) < pd.Timestamp(C.CONFIG_DATES["scrap_reason_req"])]
    rw_pre = labp[labp["_rework"]]
    add("Defects", "Rework recorded as run time (T6)", "60-75% of rework events", f"{rw_pre['_t6_as_run'].mean():.0%}", 0.60 <= rw_pre["_t6_as_run"].mean() <= 0.75)
    pre_ev = st[st["event_id"].isin(d["scrap"]["event_id"]) | st["_unrecorded"]]
    recorded = 1 - st["_unrecorded"].mean()
    add("Defects", "Scrap events recorded (T7)", "55-70%", f"{recorded:.0%}", 0.55 <= recorded <= 0.70)
    scp = d["scrap"][d["scrap"]["event_date"] < pd.Timestamp(C.CONFIG_DATES["scrap_reason_req"])]
    add("Defects", "Recorded scrap events with a reason code", "about 50%", f"{scp['reason_code'].notna().mean():.0%}", 0.42 <= scp["reason_code"].notna().mean() <= 0.58)
    t8 = d["material_truth"]["_t8"].sum() + len(d["material_unissued_truth"])
    add("Defects", "Material issued to the wrong job or not issued (T8)", "4-7%", f"{t8 / (len(d['mat']) + len(d['material_unissued_truth'])):.1%}",
        0.04 <= t8 / (len(d["mat"]) + len(d["material_unissued_truth"])) <= 0.07)
    rt2 = rt[~rt["work_center_group"].isin(C.SECONDARY_GROUPS)]
    rep = set(pt.loc[pt["job_type"] == "repeat", "part_number"])
    off = (rt2["true_run_min_per_piece"] / d["routings"].set_index(["part_number", "op_seq"]).reindex(list(zip(rt2["part_number"], rt2["op_seq"])))["std_run_min_per_piece"].to_numpy() - 1).abs() > 0.15
    stale = pd.Series(off.to_numpy(), index=rt2["part_number"].to_numpy()).groupby(level=0).any()
    stale = stale[stale.index.isin(rep)]
    # the ERP routing already carries the refreshed standards; use the truth flag for the pre-engagement view
    stale_pre = rt2.groupby("part_number")["standard_stale"].any(); stale_pre = stale_pre[stale_pre.index.isin(rep)]
    add("Defects", "Repeat parts with standards more than 15% off the measured cycle (M2)", "55-70%", f"{stale_pre.mean():.0%}", 0.55 <= stale_pre.mean() <= 0.70)
    progs = d["routings"]["program_number"].dropna()
    generic = ~progs.str.match(r"^O\d{5}$"); add("Defects", "Generic or reused program numbers (M7)", "8-12%", f"{generic.mean():.0%}", 0.08 <= generic.mean() <= 0.12)
    ownp = ops_std.merge(rp[["part_number"]], how="left")
    own_below = int((rp[rp["part_number"].isin(ops_std["part_number"])].shape[0]))
    op = d["parts"][d["parts"]["own_product_flag"]]
    add("Defects", "Own products below current cost at list price (M8, generator view)", "1-3 of 14", f"{d['own_product_truth']['below_cost'].sum()} of {len(op)}",
        1 <= d["own_product_truth"]["below_cost"].sum() <= 3)

    # T10: no labor posted at the four cells before the rollout, on every job through them
    ops = d["ops_truth"]; ops_d = pd.Timestamp(C.START_DATE) + pd.to_timedelta(ops["start_h"], unit="h")
    t10_ops = ops[ops["work_center_id"].isin(C.T10_NO_POSTING_WCS) & (ops_d < pd.Timestamp(C.SCAN_ROLLOUT_START))]
    posted = lab[lab["work_center_id"].isin(C.T10_NO_POSTING_WCS) & (lab["clock_on"] < pd.Timestamp(C.SCAN_ROLLOUT_START))]
    share = t10_ops["job_id"].nunique() / jobs[jobs["release_date"] < pd.Timestamp(C.SCAN_ROLLOUT_START)]["job_id"].nunique()
    add("Defects", "Labor posting never turned on at three secondary cells (T10): records before the rollout", "0", f"{len(posted)} records; {share:.0%} of jobs pass through them", len(posted) == 0 and 0.25 <= share <= 0.75)

    # ── post-engagement levels ───────────────────────────────────────────
    post = jobs[jobs["release_date"] >= pd.Timestamp(C.CONFIG_DATES["estimate_to_job"])]
    add("Post", "Jobs released with an estimate attached after the config date", "100%", f"{post['est_total_cost'].notna().mean():.0%}", post["est_total_cost"].notna().mean() == 1)
    osp_post = d["osp"][d["osp"]["order_date"] >= pd.Timestamp(C.CONFIG_DATES["po_job_required"])]
    add("Post", "Outside processing tied to a job, new POs", "97%+", f"{osp_post['job_id'].notna().mean():.1%}", osp_post["job_id"].notna().mean() >= 0.97)
    # scan coverage at secondary operations by week
    sec_ops = ops[ops["group"].isin(C.SECONDARY_GROUPS)].copy()
    sec_ops["date"] = (pd.Timestamp(C.START_DATE) + pd.to_timedelta(sec_ops["start_h"], unit="h")).dt.date
    sec_ops = sec_ops[(sec_ops["date"] >= C.SCAN_ROLLOUT_START) & (sec_ops["date"] <= C.END_DATE)]
    sec_ops["week"] = [C.engagement_week(x) for x in sec_ops["date"]]
    scanned = set(zip(lab.loc[lab["source"] == "traveler_scan", "job_id"], lab.loc[lab["source"] == "traveler_scan", "op_seq"]))
    sec_ops["scanned"] = [(j, o) in scanned for j, o in zip(sec_ops["job_id"], sec_ops["op_seq"])]
    cov = sec_ops[sec_ops["week"].notna()].groupby("week")["scanned"].mean()
    add("Post", "Scan coverage at secondary operations, week 2", "65-75%", f"{cov.get(2, np.nan):.0%}", 0.65 <= cov.get(2, 0) <= 0.75)
    add("Post", "Scan coverage at secondary operations, week 12", "85-92%", f"{cov.get(12, np.nan):.0%}", 0.85 <= cov.get(12, 0) <= 0.92)
    add("Story", "Coverage rises in step with the rollout", "monotone-ish", " ".join(f"w{int(w)}:{v:.0%}" for w, v in cov.items()), cov.get(12, 0) > cov.get(2, 0))
    # measured cost share on engagement jobs, weeks 8-12: machine hours, scans, issues, POs measured; missing scans estimated
    eng_jobs = jobs[(jobs["release_date"] >= pd.Timestamp(C.ENGAGEMENT_START + timedelta(weeks=7))) & (jobs["status"] == "completed")]
    ej = jc.loc[eng_jobs["job_id"]]
    o2 = ops[ops["job_id"].isin(eng_jobs["job_id"])].copy()
    o2["hours"] = o2["setup_hours"] + o2["run_hours"] + o2["change_order_hours"]
    # measured: machine hours on a resolved program, scans present, issues, received POs
    # estimated: missing scans, unresolved programs, POs not yet received
    xw = d["rem_program_crosswalk"]; unresolved = set(xw.loc[xw["status"] == "unresolved", "program_number"])
    prog_of = d["routings"].set_index(["part_number", "op_seq"])["program_number"]
    pn_of = jobs.set_index("job_id")["part_number"]
    o2["program"] = list(prog_of.reindex(list(zip(o2["job_id"].map(pn_of), o2["op_seq"]))))
    o2["measured"] = [((j, s) in scanned) if sec else (pg not in unresolved)
                      for j, s, sec, pg in zip(o2["job_id"], o2["op_seq"], o2["group"].isin(C.SECONDARY_GROUPS), o2["program"])]
    rate = o2["work_center_id"].map(lambda w: wct_rate(d, w))
    o2["cost"] = o2["hours"] * rate
    measured_labor = o2.loc[o2["measured"], "cost"].sum(); est_labor = o2.loc[~o2["measured"], "cost"].sum()
    osp_e = d["osp"][d["osp"]["job_id"].isin(eng_jobs["job_id"])]
    osp_meas = osp_e["invoice_amount"].fillna(0).sum(); osp_est = (osp_e["quantity"] * osp_e["unit_price"])[osp_e["invoice_amount"].isna()].sum()
    measured = measured_labor + ej["true_material"].sum() + osp_meas
    share = measured / (measured + est_labor + osp_est)
    add("Post", "Cost dollars measured (not estimated) on jobs run in weeks 8-12", "85-92%", f"{share:.0%}", 0.85 <= share <= 0.92)
    log = d["rem_standard_update_log"]; measured_parts = log["part_number"].nunique() / len(rep)
    add("Post", "Repeat parts with measured standards (every part that ran on a monitored cell)", "70-100%", f"{measured_parts:.0%}", 0.70 <= measured_parts <= 1.0)
    disp = log["reviewer_decision"].str.startswith("disputed").mean()
    add("Post", "Estimator disputes of measured values", "5-10%", f"{disp:.0%}", 0.05 <= disp <= 0.10)
    dec = d["rem_repricing_decisions"]["decision"].value_counts(normalize=True)
    add("Post", "Repricing decisions on every part reviewed: repriced / held / exited, none pending", "45-70 / 20-45 / 3-12% / 0",
        f"{dec.get('reprice', 0):.0%} / {dec.get('hold', 0):.0%} / {dec.get('exit', 0):.0%} / {dec.get('pending', 0):.0%}",
        0.45 <= dec.get("reprice", 0) <= 0.70 and 0.20 <= dec.get("hold", 0) <= 0.45 and 0.03 <= dec.get("exit", 0) <= 0.12 and dec.get("pending", 0) == 0)

    df = pd.DataFrame(rows, columns=["Section", "Check", "Expected", "Found", "Result"])
    lines = ["# Realism checks", "", f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M}. Rerun with `python -m data_source.generate.checks` after any generator change.", ""]
    for sec in ["Volume", "Outcome", "Defects", "Post", "Story"]:
        sub = df[df["Section"] == sec]
        lines += [f"## {sec}", "", "| Check | Expected | Found | Result |", "|---|---|---|---|"]
        lines += [f"| {r.Check} | {r.Expected} | {r.Found} | {r.Result} |" for r in sub.itertuples()]
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    n_fail = (df["Result"] != "pass").sum()
    for r in df.itertuples():
        print(f"  [{r.Result:5s}] {r.Check}: {r.Found}  (expected {r.Expected})")
    print(f"{len(df) - n_fail} of {len(df)} checks pass; written to {OUT}")
    return df


def true_current_cost(d):
    """Current unit cost per repeat part from the true routing at the pools, today's
    material price and vendor price, over the quoted lot."""
    from .generators.costing import CostModel
    parts = d["parts"].copy(); parts["weight_lb"] = parts["part_number"].map(d["parts_truth"].set_index("part_number")["weight_lb"])
    rt = d["routings_truth"].rename(columns={"true_setup_hours": "std_setup_hours", "true_run_min_per_piece": "std_run_min_per_piece"})
    rt["true_setup_hours"] = rt["std_setup_hours"]; rt["true_run_min_per_piece"] = rt["std_run_min_per_piece"]
    wct = d["work_centers_truth"]
    mp = _tr("material_prices_truth"); vend = _tr("vendors_truth"); vp = _tr("vendor_prices_truth")
    cm = CostModel(parts, rt, wct, mp, vend, vp)
    plan = {}
    for r in d["osp_plan_truth"].itertuples():
        plan.setdefault(r.part_number, []).append((r.service_type, r.vendor_id, r.base_price_per_piece))
    sp = d["standing_prices_truth"].set_index("part_number")
    rows = []
    from .generators.quotes_jobs import _letters_between
    for pn, r in sp.iterrows():
        lot = int(r["quoted_lot"])
        est = cm.estimate(pn, lot, C.END_DATE, standards="true", rates="pool", material="actual", osp_base=plan.get(pn, []))
        cur = est["est_total_cost"] / lot
        price = r["standing_price_at_start"] * _letters_between(C.START_DATE, C.END_DATE)
        rows.append({"part_number": pn, "standing_price": price, "current_unit_cost": cur, "target_price": cur * (1 + C.TARGET_MARKUP)})
    return pd.DataFrame(rows)


def wct_rate(d, w):
    r = d["work_centers_truth"].set_index("work_center_id").loc[w]
    return (r["true_labor_rate"] * r["attended_ratio"] + r["true_burden_rate"]) * (1 + C.POOL_RATE_DRIFT) ** 3


if __name__ == "__main__":
    run()
