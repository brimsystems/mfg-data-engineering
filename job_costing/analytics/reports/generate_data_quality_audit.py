"""ERP System Data Quality Audit -> docs/reports/data_quality_audit.html

The audit delivered at the end of the twelve-week engagement to the controller and
the owner. Four sections in the structure of the demand-forecasting case's audit:
what was found (the seventeen error types across the master, configuration and
transaction tables, with their scale), what was done about each, the before-and-
after measures, and the system settings and process changes that keep job cost
reliable. Every figure comes from the dbt warehouse; no financial or operational
cost figures here, those belong to the margin diagnostic.

Run:  python -m analytics.reports.generate_data_quality_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brand as B  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MARTS = REPO / "analytics" / "data" / "marts"
RAW = REPO / "data_source" / "raw"
REM = RAW / "remediation"
OUT = REPO / "docs" / "reports" / "data_quality_audit.html"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

LIVE = pd.Timestamp(C.CONFIG_DATES["scrap_reason_req"])      # the last configuration change: the new process in full
CODES = pd.Timestamp(C.CONFIG_DATES["labor_type_codes"])
MONITORED = ["VMC", "FAX", "HMC", "LTH", "MTN", "SWS", "EDM"]


def _pq(name):
    df = pd.read_parquet(MARTS / f"{name}.parquet")
    for c in df.columns:
        if df[c].dtype == object:
            first = df[c].dropna()
            if len(first) and hasattr(first.iloc[0], "year") and not isinstance(first.iloc[0], str):
                df[c] = pd.to_datetime(df[c])
    return df


def _rows(p):
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def pc(x, d=0):
    return "&ndash;" if pd.isna(x) else f"{round(x * 100, d) + 0.0:.{d}f}%"


# ── gather ──────────────────────────────────────────────────────────────────
def gather():
    d = {}
    reg = _pq("mart_dq_error_summary").set_index("error_code")
    d["reg"] = reg
    d["lc"] = _pq("int_labor_cleaned")
    d["jobs"] = _pq("fct_job_cost")
    d["hours"] = _pq("int_labor_hours_by_job")
    d["mh"] = _pq("int_machine_hours_by_job")
    d["cov"] = _pq("mart_coverage_weekly")
    d["queue"] = _pq("mart_repricing_queue")
    d["osp"] = _pq("int_osp_by_job")
    d["config"] = pd.read_csv(REM / "config_change_log.csv", parse_dates=["effective_date"])
    d["interviews"] = pd.read_csv(REM / "interview_log.csv")
    d["gaps"] = pd.read_csv(REM / "config_gap_list.csv")
    d["std"] = pd.read_csv(REM / "standard_update_log.csv")
    d["xw"] = pd.read_csv(REM / "program_crosswalk.csv")
    d["att"] = pd.read_csv(REM / "po_attribution.csv")
    d["backfill"] = pd.read_csv(REM / "estimate_backfill.csv")
    d["scrap"] = pd.read_csv(RAW / "erp" / "scrap_rework.csv", parse_dates=["event_date"])
    d["labor"] = pd.read_csv(RAW / "erp" / "labor_transactions.csv", low_memory=False, parse_dates=["clock_on"])
    for k in ["t1", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "m2", "m4", "m5", "m6", "m7"]:
        name = {"t1": "dq_t1_open_clock_records", "t3": "dq_t3_wrong_job", "t4": "dq_t4_multi_machine_tending", "t5": "dq_t5_indirect_time_on_jobs",
                "t6": "dq_t6_rework_as_run", "t7": "dq_t7_scrap_unrecorded", "t8": "dq_t8_material_wrong_job", "t9": "dq_t9_missing_scans",
                "m2": "dq_m2_stale_routing_standards", "m4": "dq_m4_standing_price_below_target", "m5": "dq_m5_stale_material_cost",
                "m6": "dq_m6_outside_processing_no_job", "m7": "dq_m7_generic_program_numbers"}[k]
        d[k] = _pq(name)

    # scope: the tables examined
    d["master_comp"] = [("Part master", _rows(RAW / "erp" / "part_master.csv")), ("Routings", _rows(RAW / "erp" / "routings.csv")),
                        ("Work centers and rates", _rows(RAW / "erp" / "work_center_rates.csv")),
                        ("Customers", _rows(RAW / "erp" / "customers.csv"))]
    d["txn_comp"] = [("Quotes", _rows(RAW / "erp" / "quotes.csv")), ("Jobs", _rows(RAW / "erp" / "jobs.csv")), ("Labor transactions", _rows(RAW / "erp" / "labor_transactions.csv")),
                     ("Machine monitoring", _rows(RAW / "monitoring" / "machine_monitoring.csv")), ("Material transactions", _rows(RAW / "erp" / "material_transactions.csv")),
                     ("Outside processing", _rows(RAW / "erp" / "outside_processing.csv")), ("Scrap and rework", _rows(RAW / "erp" / "scrap_rework.csv"))]
    d["total_rows"] = sum(n for _, n in d["master_comp"] + d["txn_comp"])
    d["mm_rows"] = dict(d["txn_comp"])["Machine monitoring"]
    d["erp_rows"] = d["total_rows"] - d["mm_rows"]

    # ── remediation counts ──────────────────────────────────────────────
    lc = d["lc"]
    st = lambda ids: lc[lc["txn_id"].isin(ids)]["status"].value_counts()
    s1, s3, s4, s5 = st(d["t1"]["txn_id"]), st(d["t3"]["txn_id"]), st(d["t4"]["txn_id"]), st(d["t5"]["txn_id"])
    d["t1_repaired"] = int(s1.get("superseded", 0) + s1.get("corrected", 0) + s1.get("removed", 0)); d["t1_unrep"] = int(s1.get("unrepairable", 0))
    d["t3_repaired"] = int(s3.get("corrected", 0)); d["t3_unrep"] = int(len(d["t3"]) - d["t3_repaired"])
    d["t4_repaired"] = int(s4.get("superseded", 0) + s4.get("removed", 0) + s4.get("corrected", 0)); d["t4_unrep"] = int(s4.get("unrepairable", 0))
    d["t5_removed"] = int(s5.get("removed", 0))
    pre = lc[~lc["after_codes"] & lc["job_id"].notna()]
    d["pre_records"] = len(pre)
    d["pre_superseded"] = float((pre["status"] == "superseded").mean())
    # the records carrying a labor error (T1, T3, T4, T5, the catch-all rework): repaired, or flagged unrepairable
    err_ids = set(d["t1"]["txn_id"]) | set(d["t3"]["txn_id"]) | set(d["t4"]["txn_id"]) | set(d["t5"]["txn_id"]) | set(lc.loc[lc["op_seq"] == 999, "txn_id"])
    err = lc[lc["txn_id"].isin(err_ids)]
    d["err_records"] = len(err)
    d["pre_repaired"] = float(err["status"].isin(["superseded", "corrected", "removed"]).mean())
    d["pre_unrep"] = float((err["status"] == "unrepairable").mean())
    d["unrep_by_cell"] = lc[~lc["after_codes"]].assign(g=lambda x: x["work_center_id"].str[:3]).groupby("g")["status"].apply(lambda s: (s == "unrepairable").mean())
    d["t6_999"] = int(d["t6"]["hours_on_999"].notna().sum()); d["t6_run"] = int(d["t6"]["hours_on_999"].isna().sum())
    d["t7_rec"] = int((d["t7"]["detection"] == "recorded event").sum()); d["t7_inf"] = int((d["t7"]["detection"] != "recorded event").sum())
    d["t7_noreason"] = int(d["t7"]["evidence"].str.contains("reason").sum()); d["t7_nojob"] = int(d["t7"]["evidence"].str.contains("job").sum())
    d["t8_over"] = int(d["t8"]["evidence"].str.contains("another").sum()); d["t8_under"] = len(d["t8"]) - d["t8_over"]
    std = d["std"]; d["std_parts"] = std["part_number"].nunique(); d["std_ops"] = len(std)
    dec = std["reviewer_decision"].value_counts(); d["std_accepted"] = int(dec.get("accepted", 0)); d["std_kept"] = int(dec.get("disputed, standard kept", 0)); d["std_adj"] = int(dec.get("disputed, adjusted", 0))
    m2 = d["m2"]; d["m2_parts"] = m2["part_number"].nunique(); d["m2_refreshed"] = m2[m2["refresh_decision"].notna()]["part_number"].nunique()
    d["m2_ops_refreshed"] = int(m2["refresh_decision"].notna().sum())
    d["m2_faster"] = float((m2["direction"] == "cycle now faster than standard").mean())
    xw = d["xw"]; d["xw_unique"] = int((xw["method"] == "routing match").sum()); d["xw_generic"] = xw[xw["method"].str.startswith("cell")]["program_number"].nunique()
    d["xw_unresolved"] = int((xw["status"] == "unresolved").sum()); d["m7_programs"] = d["m7"]["program_number"].nunique()
    att = d["att"]; d["att_ok"] = int((att["status"] == "attributed").sum()); d["att_res"] = int((att["status"] != "attributed").sum())
    d["att_methods"] = att[att["status"] == "attributed"]["method"].value_counts().to_dict()
    d["m6_pre"] = int(d["reg"].loc["M6", "scope_affected"]); d["m6_scope"] = int(d["reg"].loc["M6", "scope_rows"])
    d["m6_rows"] = int(d["reg"].loc["M6", "rows_affected"])
    d["m2_rows"] = int(d["reg"].loc["M2", "rows_affected"]); d["m5_rows"] = int(d["reg"].loc["M5", "rows_affected"])
    d["m7_rows"] = int(d["reg"].loc["M7", "rows_affected"]); d["m3_rows"] = int(d["reg"].loc["M3", "rows_affected"])
    d["t9_jobs"] = int(d["reg"].loc["T9", "rows_affected"])
    bf = d["backfill"]; d["bf_quote"] = int(bf["est_total_cost"].notna().sum()); d["bf_none"] = int(bf["est_total_cost"].isna().sum())
    d["bf_methods"] = bf["method"].value_counts().to_dict()
    q = d["queue"]; below = q[q["below_target"]]; d["m4_n"] = len(below); d["m4_dec"] = int(below["decision"].notna().sum()); d["m4_decisions"] = below["decision"].value_counts().to_dict()
    d["m5_specs"] = d["m5"]["material_spec"].nunique(); d["m5_lines"] = len(d["m5"]); d["m5_lag"] = float(d["m5"]["lag_months"].median())
    d["t9_n"] = len(d["t9"])
    d["t10"] = _pq("dq_t10_labor_posting_off"); d["t10_jobs"] = d["t10"]["job_id"].nunique(); d["t10_hours"] = float(d["t10"]["standard_hours_missing"].sum())

    # ── results: before (raw, the twelve months before the engagement) and after (the new process in full) ──
    j = d["jobs"]
    before_ids = set(j[(j["version"] == "cleaned") & (j["release_date"] >= pd.Timestamp(C.ENGAGEMENT_START) - pd.DateOffset(years=1)) & (j["release_date"] < pd.Timestamp(C.ENGAGEMENT_START))]["job_id"])
    after = j[(j["version"] == "restructured") & (j["status"] == "completed") & (j["release_date"] >= LIVE)]
    after_ids = set(after["job_id"])
    raw_b = j[(j["version"] == "raw") & j["job_id"].isin(before_ids)]
    d["n_before"], d["n_after"] = len(before_ids), len(after_ids)
    r = {}
    r["estimate"] = (float(raw_b["est_total_cost"].notna().mean()), float(after["estimate_source"].eq("job").mean()))
    r["measured"] = (np.nan, float((after["coverage"] * after["act_total_cost"]).sum() / after["act_total_cost"].sum()))
    # job cost dollars on accurate transactions, recorded on the right job. Before: the ERP's own
    # dollars on records the audit found no error on, over those dollars plus the cost that never
    # reached the job (outside processing with no job number, labor never posted). After: the cost
    # on jobs completed under the new process that rests on a transaction.
    el = _pq("fct_job_cost_elements")
    raw = el[(el["version"] == "raw") & el["job_id"].isin(before_ids)]
    cln = el[(el["version"] == "cleaned") & el["job_id"].isin(before_ids)]
    missing = cln.loc[cln["source"].isin(["PO, attributed", "GL residual, allocated", "standard-fallback"]), "amount"].sum()
    lcb = d["lc"][d["lc"]["job_id"].isin(before_ids)].copy()
    lcb["cost"] = lcb["hours"] * lcb["clock_on"].dt.year.map(C.BLENDED_RATE)
    flagged = set(d["t1"]["txn_id"]) | set(d["t3"]["txn_id"]) | set(d["t4"]["txn_id"]) | set(d["t5"]["txn_id"])
    bad = lcb["txn_id"].isin(flagged) | (lcb["op_seq"] == 999)
    mat = raw[raw["element"] == "material"]; mat_bad = mat["job_id"].isin(set(d["t8"]["job_id"]))
    osp_raw = raw.loc[raw["element"] == "outside", "amount"].sum()
    clean = lcb.loc[~bad, "cost"].sum() + mat.loc[~mat_bad, "amount"].sum() + osp_raw
    total = lcb["cost"].sum() + mat["amount"].sum() + osp_raw + missing
    r["accurate"] = (float(clean / total), r["measured"][1])
    h = d["hours"]; ha = h[h["job_id"].isin(after_ids)]; mon = ha["work_center_id"].str[:3].isin(MONITORED)
    r["machine"] = (0.0, float(ha[mon & (ha["source"] == "machine")]["hours"].sum() / ha[mon]["hours"].sum()))
    lab = d["labor"][d["labor"]["job_id"].notna() & (d["labor"]["type"] != "indirect")]
    cl = lab.groupby(["job_id", "work_center_id"])["hours"].sum().rename("clocked").reset_index().merge(d["mh"][["job_id", "work_center_id", "machine_hours"]], on=["job_id", "work_center_id"])
    cl["ratio"] = cl["clocked"] / cl["machine_hours"]
    within = lambda ids: float(((cl[cl["job_id"].isin(ids)]["ratio"] - 1).abs() <= 0.10).mean())
    r["clocked"] = (within(before_ids), within(after_ids))
    sec = ~mon
    r["scan"] = (0.0, float(ha[sec & (ha["source"] == "scan")]["hours"].sum() / ha[sec]["hours"].sum()))
    lab_b = d["labor"][(d["labor"]["clock_on"] < pd.Timestamp(C.ENGAGEMENT_START)) & (d["labor"]["source"] == "terminal")]
    lab_a = d["labor"][(d["labor"]["clock_on"] >= LIVE) & (d["labor"]["source"] == "terminal")]
    r["codes"] = (float((lab_b["type"] != "run").mean()), float(lab_a["type"].isin(["setup", "run", "rework", "indirect"]).mean()))
    osp = d["osp"]; ob = osp[(osp["order_date"] >= pd.Timestamp(C.ENGAGEMENT_START) - pd.DateOffset(years=1)) & (osp["order_date"] < pd.Timestamp(C.ENGAGEMENT_START))]
    oa = osp[osp["order_date"] >= pd.Timestamp(C.CONFIG_DATES["po_job_required"])]
    r["osp"] = (float(ob["erp_job_id"].notna().mean()), float(oa["erp_job_id"].notna().mean()))
    r["standards"] = (0.0, d["std_parts"] / len(q))
    r["priced"] = (0.0, d["m4_dec"] / max(d["m4_n"], 1))
    r["rates"] = (0.0, 1.0)
    sc = d["scrap"]; sb = sc[(sc["event_date"] >= pd.Timestamp(C.ENGAGEMENT_START) - pd.DateOffset(years=1)) & (sc["event_date"] < pd.Timestamp(C.ENGAGEMENT_START))]
    sa = sc[sc["event_date"] >= LIVE]
    r["scrap"] = (float((sb["job_id"].notna() & sb["reason_code"].notna()).mean()), float((sa["job_id"].notna() & sa["reason_code"].notna()).mean()))
    r["history"] = (0.0, d["pre_repaired"] + d["pre_unrep"])
    d["results"] = r
    m2 = d["m2"]
    dec2 = m2["refresh_decision"].value_counts()
    d["m2_acc"], d["m2_adj"], d["m2_kept"] = int(dec2.get("accepted", 0)), int(dec2.get("disputed, adjusted", 0)), int(dec2.get("disputed, standard kept", 0))
    d["m2_fixed"] = d["m2_acc"] + d["m2_adj"]; d["m2_open"] = len(m2) - d["m2_ops_refreshed"]
    # standing prices: the parts below target, by the decision taken on each
    d["m4_fixed"] = int(d["m4_decisions"].get("reprice", 0) + d["m4_decisions"].get("exit", 0))
    d["m4_open"] = d["m4_n"] - d["m4_dec"]
    # outside processing: every line with no job number, attributed, residual or placed after the requirement
    m6 = d["m6"]; d["m6_att"] = int(m6["attributed_job_id"].notna().sum()); d["m6_after"] = int(m6["after_config"].sum())
    d["m6_resid"] = len(m6) - d["m6_att"] - d["m6_after"]
    # generic programs: the routing operations that name one, and those on a program-machine pair the leads could not place
    un = d["xw"][d["xw"]["status"] == "unresolved"][["program_number", "machine_id"]]
    k = d["m7"].merge(un, left_on=["program_number", "work_center_id"], right_on=["program_number", "machine_id"], how="left", indicator=True)
    d["m7_unres_ops"] = int((k["_merge"] == "both").sum()); d["m7_fixed"] = len(d["m7"]) - d["m7_unres_ops"]
    d["own_below"] = int(_pq("mart_own_products")["below_cost_at_list"].sum())
    d["values"] = process_values(d, r)
    cov = d["cov"].dropna(subset=["scan_coverage"]); d["scan_last"] = float(cov["scan_coverage"].iloc[-1]); d["scan_first"] = float(cov["scan_coverage"].iloc[0])
    d["scan_week_first"], d["scan_week_last"] = int(cov["engagement_week"].iloc[0]), int(cov["engagement_week"].iloc[-1])
    return d


def money(x):
    return f"${x:,.0f}"


def process_values(d, r):
    """What each process change is worth, from the marts, for the Process Changes table."""
    v = {"year": 2025}
    q = d["queue"]; below = q[q["below_target"]]
    v["n_below"] = len(below); v["gap"] = float(below["gap_to_target_annual"].sum())
    rep = q[q["decision"] == "reprice"]; v["taken"] = float(((rep["new_price"] - rep["standing_price"]) * rep["annual_volume"]).sum())
    # standards: run-hours error on engagement-period repeat jobs, refreshed against not
    m = _pq("mart_margin_by_job"); cc = _pq("int_current_cost").set_index("part_number")
    eng = m[(m["version"] == "restructured") & (m["status"] == "completed") & (m["job_type"] == "repeat") & (m["est_run_hours"] > 0)].copy()
    eff = d["std"].assign(effective_date=pd.to_datetime(d["std"]["effective_date"])).groupby("part_number")["effective_date"].min()
    month_start = pd.to_datetime(eng["release_date"]).dt.to_period("M").dt.to_timestamp()
    eng["used"] = eng["part_number"].map(eff) <= month_start          # the refreshed standard was in force when the job was estimated
    err = (eng["act_run_hours"] / eng["est_run_hours"] - 1).abs()
    v["acc_refreshed"] = float(err[eng["used"]].median()); v["acc_stale"] = float(err[~eng["used"]].median())
    v["n_used"] = int(eng["used"].sum()); v["n_not"] = int((~eng["used"]).sum())
    v["parts_unrefreshed"] = int((~cc.loc[cc["part_type"] == "repeat", "any_standard_refreshed"].astype(bool)).sum())
    # coverage: the last week with completed jobs
    cw = d["cov"].dropna(subset=["measured_cost_share"]).tail(4)
    v["cov_weeks"] = f"{int(cw['engagement_week'].iloc[0])} to {int(cw['engagement_week'].iloc[-1])}"
    v["fallback_cost"] = float((cw["fallback_share"] * cw["actual_cost"]).sum()); v["fallback_share"] = float((cw["fallback_share"] * cw["actual_cost"]).sum() / cw["actual_cost"].sum())
    sc = d["cov"].dropna(subset=["scan_coverage"]).tail(4); v["scan_last"] = float(sc["scan_coverage"].iloc[-1])
    # the alloy bias, on new work in the year
    y = m[m["release_year"] == 2025]
    bias = y[(y["job_type"] == "new") & y["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]
    rate = bias["act_labor"] / bias["act_labor_hours"].replace(0, np.nan)
    v["p5"] = float(((bias["act_run_hours"] - bias["est_run_hours"]).clip(lower=0) * rate).sum())
    v["run_bias"] = float(y[y["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]["run_hours_ratio"].median())
    v["run_rest"] = float(y[~y["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]["run_hours_ratio"].median())
    # the blended rate: the family it flattered to below target
    tm = C.TARGET_MARKUP / (1 + C.TARGET_MARKUP)
    fam = _pq("mart_margin_by_part_family")
    hidden = fam[(fam["margin_on_price_blended"] >= fam["margin_on_price"] + 0.05) & (fam["margin_on_price"] < tm - 0.02)].sort_values("margin_on_price")
    h = hidden.iloc[0]
    v["hidden_family"] = h["part_family"]; v["hidden_blended"] = float(h["margin_on_price_blended"]); v["hidden_pool"] = float(h["margin_on_price"])
    v["p4"] = float(((tm - hidden["margin_on_price"]) * hidden["revenue"]).sum()) / 3
    # scrap
    inf = d["t7"][d["t7"]["detection"] != "recorded event"]
    v["t7_inferred"] = len(inf); v["t7_pieces"] = int(inf["quantity"].sum()); v["scrap_after"] = r["scrap"][1]
    # the spreadsheet: accuracy by the basis the quote line was priced on
    est = _pq("int_estimate_by_job").set_index("job_id")
    hist = m[(m["version"] == "cleaned") & (m["status"] == "completed") & (m["est_total_cost"] > 0)].copy()
    hist["basis"] = hist["job_id"].map(est["estimate_basis"])
    for k, a_, e_ in [("total", "act_total_cost", "est_total_cost"), ("material", "act_material", "est_material"), ("outside", "act_outside", "est_outside")]:
        sub = hist[hist[e_] > 0]
        terr = (sub[a_] / sub[e_] - 1).abs()
        v[f"acc_ss_{k}"] = float(terr[sub["basis"] == "spreadsheet"].median()); v[f"acc_erp_{k}"] = float(terr[sub["basis"] == "ERP"].median())
    v["m5_lines"] = len(d["m5"]); v["m5_ss"] = float((d["m5"]["estimate_basis"] == "spreadsheet").mean())
    ql = pd.read_csv(RAW / "erp" / "quotes.csv").drop_duplicates(["quote_id", "line"])
    v["ss_share"] = float((ql["estimate_basis"] == "spreadsheet").mean())
    return v


# ── ERD ─────────────────────────────────────────────────────────────────────
def chart_erd(d):
    """The sources job cost is built from and how information flows between them.
    Masters on top; the quote, the job and the monitoring feed in the middle; the
    ERP transactions below, keyed on the job number and rolled up into the job.
    Where a line has to cross another it hops it: the vertical passes over a break
    in the horizontal."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    rows = dict(d["master_comp"] + d["txn_comp"])
    fig, ax = plt.subplots(figsize=(10.5, 4.95))
    ax.set_xlim(0, 101); ax.set_ylim(-4.6, 49); ax.axis("off")
    H = 9.0

    def box(x, y, w, title, key, kind):
        face = {"master": B.DARK_BLUE, "transaction": B.MED_GREY, "external": B.AMBER}[kind]
        text = B.DARK_GREY if kind == "external" else "white"
        ax.add_patch(FancyBboxPatch((x, y), w, H, boxstyle="round,pad=0,rounding_size=0.8", facecolor=face, edgecolor=face, linewidth=1.3, zorder=4))
        ax.text(x + w / 2, y + H * 0.64, title, ha="center", va="center", fontsize=9.2, color=text, fontweight="bold", linespacing=1.1, zorder=5)
        ax.text(x + w / 2, y + H * 0.24, f"{rows[key]:,} records", ha="center", va="center", fontsize=7.8, color=text, zorder=5)

    def lane(pts):
        # horizontal runs, drawn first so verticals can hop them
        xs, ys = zip(*pts); ax.plot(xs, ys, color=B.MED_GREY, linewidth=1.1, zorder=1, solid_capstyle="round")

    def drop(pts):
        # vertical runs, with a white halo that breaks any lane they cross
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color="white", linewidth=4.5, zorder=2, solid_capstyle="butt")
        ax.plot(xs, ys, color=B.MED_GREY, linewidth=1.1, zorder=3, solid_capstyle="round")

    def head(p0, p1):
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=13, color=B.MED_GREY, linewidth=1.1, shrinkA=0, shrinkB=0, zorder=3))

    # every box the same width
    W = 22.0
    mx = [1, 26.5, 52, 77.5]
    for x, (title, key) in zip(mx, [("Customers", "Customers"), ("Part master", "Part master"), ("Routings", "Routings"), ("Work centers", "Work centers and rates")]):
        box(x, 38, W, title, key, "master")
    head((mx[1] + W, 42.5), (mx[2], 42.5))                                         # part -> routing
    # the two costing tables and the monitoring feed
    box(12, 19, W, "Quotes", "Quotes", "transaction"); box(41.5, 19, W, "Jobs", "Jobs", "transaction")
    ax.add_patch(FancyBboxPatch((41.5 - 1.2, 19 - 1.2), W + 2.4, H + 2.4, boxstyle="round,pad=0,rounding_size=1.2",
                                facecolor="none", edgecolor=B.DARK_GREY, linewidth=1.3, linestyle=(0, (4, 3)), zorder=4))
    box(77.5, 19, W, "Machine monitoring", "Machine monitoring", "external")
    # lanes between the master row and the costing tables: the near sources bend high,
    # the far sources pass beneath them and above the arrowheads into the costing tables
    lane([(12, 37), (18, 37)]); lane([(31, 36.5), (28, 36.5)]); lane([(44, 36), (47, 36)]); lane([(66, 36), (58, 36)])
    lane([(55, 34), (22, 34)]); lane([(95, 32.5), (25, 32.5)]); lane([(82, 35), (68, 35)])
    drop([(12, 38), (12, 37)]); drop([(18, 37), (18, 28.6)]); head((18, 29.4), (18, 28))                # customer -> quote
    drop([(31, 38), (31, 36.5)]); drop([(28, 36.5), (28, 28.6)]); head((28, 29.4), (28, 28))            # part -> quote
    drop([(44, 38), (44, 36)]); drop([(47, 36), (47, 29.8)]); head((47, 30.6), (47, 29.2))              # part -> job
    drop([(55, 38), (55, 34)]); drop([(22, 34), (22, 28.6)]); head((22, 29.4), (22, 28))                # routing -> quote: the standards
    drop([(66, 38), (66, 36)]); drop([(58, 36), (58, 29.8)]); head((58, 30.6), (58, 29.2))              # routing -> job: the measured standards
    drop([(95, 38), (95, 32.5)]); drop([(25, 32.5), (25, 28.6)]); head((25, 29.4), (25, 28))            # work centers -> quote: the rates
    drop([(82, 38), (82, 35)]); drop([(68, 35), (68, 26)]); head((68, 26), (64.7, 26))                  # work centers -> job: the rates
    lane([(3, 38), (3, 16), (37, 16), (37, 22)]); head((37, 22), (40.3, 22))                            # customer -> job, around the quote
    head((34, 25), (40.3, 25))                                                                         # quote -> job
    head((77.5, 23), (64.7, 23))                                                                       # monitoring -> job: the connection
    # ERP transactions, rolled up into the job
    tx = [1, 26.5, 52, 77.5]
    for x, (title, key) in zip(tx, [("Labor transactions", "Labor transactions"), ("Material transactions", "Material transactions"),
                                    ("Outside processing", "Outside processing"), ("Scrap and rework", "Scrap and rework")]):
        box(x, 1, W, title, key, "transaction")
        cx = x + W / 2
        lane([(cx, 10), (cx, 13), (52.5, 13)])
    lane([(52.5, 13), (52.5, 14)]); head((52.5, 14), (52.5, 17.8))
    # legend, centered under the diagram
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=c, edgecolor=c, label=l) for c, l in [(B.DARK_BLUE, "ERP master-level tables"),
               (B.MED_GREY, "ERP transaction-level tables"), (B.AMBER, "Vendor-provided system")]]
    ax.legend(handles=handles, loc="center", bbox_to_anchor=(50.25, -3.2), bbox_transform=ax.transData, ncol=3,
              frameon=False, fontsize=8.6, handlelength=1.1, handleheight=1.1, columnspacing=2.4, handletextpad=0.6,
              labelcolor=B.DARK_GREY)
    return B.b64(fig)


def _widths(table_html, widths):
    cols = "".join(f'<col style="width:{w}%;">' for w in widths)
    return table_html.replace('<table class="data-table">', f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


def numcell(i):
    return f'<td style="vertical-align:middle;text-align:center;">#{i}</td>'


def build(d):
    reg = d["reg"]; r = d["results"]
    toc = "".join(['<a href="#impl">Job Costing ERP Implementation</a>', '<a href="#audit">Data Quality Audit</a>', '<a class="sub" href="#found">2.1 Findings</a>', '<a class="sub" href="#did">2.2 Error Remediation</a>', '<a class="sub" href="#results">2.3 Results</a>', '<a class="sub" href="#process">2.4 Process Changes</a>',
                   '<a href="#appendix">Appendix (ERP Detail)</a>'])
    sub = lambda t: f'<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">{t}</p>'

    def rows_of(code):
        r_ = reg.loc[code]
        n, tot = int(r_["rows_affected"]), int(r_["table_rows"])
        return f"{n:,} of {tot:,}<br><em>({n / tot * 100:.1f}%)</em>"

    def rem_of(n, tot, note=""):
        s = f"{n:,} of {tot:,} ({n / tot * 100:.0f}%)" if tot else f"{n:,}"
        return s + (f"<br><em>{note}</em>" if note else "")

    JOBS, ROUT, RATES, PARTS, QUOTES, OSP = "Jobs", "Routings", "Work centers", "Part master", "Quotes", "Outside processing"
    LAB, SCRAP, MAT = "Labor transactions", "Scrap and rework", "Material transactions"
    MASTER = [
        ("Stale Routing Standards", "Setup and run standards found to be stale when checked against the machine-monitoring feed", ROUT, rows_of("M2")),
        ("One Blended Shop Rate", "A single labor and burden rate was used for every work center in the shop and refreshed once a year and didn't account for differences among work centers", RATES, rows_of("M3")),
        ("Standing Prices Not Repriced", "Repeat parts sold at the price set at first quote, moved only by the annual across-the-board increases, which were found to be too low", PARTS, rows_of("M4")),
        ("Stale Material Cost in Estimates", "Material estimates pulled from a stale data source", QUOTES, rows_of("M5")),
        ("Outside Processing Not Tied to Jobs", "Purchase-order lines for plating, heat treat, coating and grinding coded to a general-ledger account with no job number", OSP, rows_of("M6")),
        ("Generic Program Numbers", "CNC programs named generically (MAIN, TEST, PROG1) or reused across parts, preventing the program-to-part mapping process", ROUT, rows_of("M7")),
        ("Stale Own-product Standard Costs", "The standard cost carried on the part master for each of the fourteen own products was found to be stale", PARTS, rows_of("M8")),
    ]
    TXN = [
        ("Jobs Left Clocked In", "Clock records left open across a break or shift end", LAB, rows_of("T1")),
        ("Setup and Run Not Separated", "The door terminal offered one clock-on, so every record posted as run time; setup, rework and indirect were indistinguishable", LAB, rows_of("T2")),
        ("Time Charged to the Wrong Job", "Time posted to an adjacent job number picked from the terminal's dropdown; the job's routing does not fit the record", LAB, rows_of("T3")),
        ("Multi-machine Tending Recorded as One Job", "One operator tending two or three monitored machines under a single clock record on the first job", LAB, rows_of("T4")),
        ("Indirect Time Charged to Jobs", "Waiting, meetings and cleanup posted on top of whatever job the operator had open", LAB, rows_of("T5")),
        ("Rework Recorded as Run Time", "No rework operation on the routing and no rework code, so rework hours posted as production on the operation or on a catch-all operation", SCRAP, rows_of("T6")),
        ("Scrap Without Reason or Without Job", "Recorded scrap and rework events missing the reason code or the job number", SCRAP, rows_of("T7")),
        ("Material Issued to the Wrong Job or Not Issued", "Material pulled for two jobs and charged to one, or remnants used and never issued", JOBS, rows_of("T8")),
        ("Missing Scans During Rollout", "Secondary operations the job reached with no traveler scan, from the week the scanning pilot began", JOBS, rows_of("T9")),
        ("Labor Posting Never Turned On at Three Secondary Cells", "Data collection was never enabled at DBR-03, INS-02 and MDP-01, so no clock record exists for any operation through them before the rollout and every job's actual labor is short by those operations", JOBS, rows_of("T10")),
    ]
    W2 = [4, 19, 40, 16, 21]; W3 = [4, 14, 42, 23, 17]
    hdr = ["", "Error", "Description", "ERP table", "Scale<br><em style=\"font-weight:400;text-transform:none;\">(rows affected)</em>"]
    master_table = _widths(B.data_table(hdr, [[numcell(i), n, desc, loc, sc] for i, (n, desc, loc, sc) in enumerate(MASTER, 1)], right=[]), W2)
    txn_table = _widths(B.data_table(hdr, [[numcell(i), n, desc, loc, sc] for i, (n, desc, loc, sc) in enumerate(TXN, len(MASTER) + 1)], right=[]), W2)

    m1 = len(_pq("dq_m1_estimate_not_on_job")); t1n = int(reg.loc["T1", "rows_affected"]); m6n = int(reg.loc["M6", "scope_affected"])
    impl = f"""
{B.section("impl", "Section 1", "Job Costing ERP Implementation")}
<p>Within the shop's ERP system, new job costing functionality was added to track the estimated and actual cost
of every job. This report details the changes made to the ERP system to capture and monitor job cost detail, as
well as the data quality audit that improved the accuracy of these job cost figures. These changes enabled the
findings in the <a href="margin_diagnostic.html">Margin Analytics Diagnostic</a> and the monitoring capabilities
shown in the <a href="dashboard.html">KPI Dashboard</a>.</p>
<p>As a result of this implementation, we made numerous changes to the shop's data sources to improve the accuracy
of the ERP's estimated and actual job cost figures, as summarized below.</p>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:26px;">Changes to improve estimated job costs</p>
<ul class="limitation-list">
<li>When a quote line becomes a job, its part-level estimate is now written onto the Jobs table by cost element, at the ordered quantity.</li>
<li>Repeat parts, which ran on standing prices from previous quotes with no current estimate, now receive a current-cost estimate computed monthly from today's material prices, work-center rates and measured cycle times.</li>
<li>Routing standards for repeat parts were replaced with cycle and setup times measured from machine data.</li>
<li>Own products, previously priced from a launch-date standard plus annual adjustment, now carry a standard cost refreshed with the repeat parts.</li>
<li>The single blended shop rate was replaced with rate pools by work center, so both estimated and actual costs now reflect actual machine and labor costs.</li>
</ul>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:26px;">Changes to improve actual job costs</p>
<ul class="limitation-list">
<li>Machine monitoring on the CNC cells was connected to the ERP, and actual machine hours now serve as the basis for run time on those cells.</li>
<li>Setup, run, rework and indirect time are now recorded separately, improving each job's labor cost accuracy.</li>
<li>Purchase orders for outside processing now require a job number when created, so actual vendor costs connect to each job.</li>
<li>Labor is now captured at every operation, including the secondary cells that previously posted none, and clock records no longer run across breaks and shifts or cover several machines at once.</li>
</ul>
<p>A diagram of the data sources feeding the updated Jobs table is below.</p>
{B.chart("Job Costing Data Sources", chart_erd(d))}
<p>As mentioned, one of the important changes to ensure the accuracy of job costs was a comprehensive data audit and
error remediation process. The rest of this report details this data audit's findings, error remediation and
results.</p>
"""
    found = f"""
{B.section("audit", "Section 2", "Data Quality Audit")}
{B.section("found", "Section 2.1", "Findings")}
<p>Over the 36 months from {pd.Timestamp(C.START_DATE):%B %Y} to {pd.Timestamp(C.END_DATE):%B %Y}, <strong>{d['erp_rows'] / 1e3:,.0f}K</strong>
records were produced across the ERP's 10 tables. This audit reviewed all of them and found <strong>17</strong>
types of data quality error recurring over the period: seven at the master-level tables and 10 at the
transaction-level tables. An additional {d['mm_rows'] / 1e6:.1f} million rows of machine monitoring data were
reviewed, but no data quality issues were found. As a result of these data errors across the ERP system, both the
estimated and actual job cost figures were inaccurate and unable to be relied upon.</p>

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Master and Configuration-level Table Errors</p>
{master_table}

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Transaction-level Table Errors</p>
{txn_table}

"""

    # ── remediation ──────────────────────────────────────────────────────
    ERP = "ERP records only"
    REM_M = [
        (f"Setup and cycle times on all {d['m2_rows']:,} stale operations measured from the machine-monitoring feed over the last three lots, and each reviewed by the "
         f"estimator: {d['m2_acc']:,} accepted, {d['m2_adj']} disputed and adjusted, {d['m2_kept']} disputed with the old standard kept.",
         "Machine-monitoring cycle and setup intervals, mapped through the program crosswalk; estimator review",
         rem_of(d['m2_fixed'], d['m2_rows'], f"{d['m2_kept']} kept after dispute")),
        ("Work-center rate pools built from the rate history, the machine hours and the headcount by cell: a labor rate, a burden rate and an attended ratio per work center, "
         "with the attended ratios set from floor observation",
         "Rate history, machine hours, headcount; production manager's observation of attended ratios", rem_of(d['m3_rows'], d['m3_rows'], "replaced by 38 rate pools")),
        (f"Every repeat part put against its current cost at today's material price, the pool rates and the measured standards on the repricing queue. The controller and the "
         f"owner reviewed all {d['m4_n']} parts below target: {d['m4_decisions'].get('reprice', 0)} repriced and {d['m4_decisions'].get('exit', 0)} exited; "
         f"{d['m4_decisions'].get('hold', 0)} held at the current price with the reason recorded",
         "Current cost from the warehouse; controller and owner decisions",
         rem_of(d['m4_fixed'], d['m4_n'], f"{d['m4_decisions'].get('hold', 0)} held by decision")),
        (f"Not corrected line by line: the spreadsheet's price list was retired and the quoting module now prices material at the current issued price, with the lag "
         f"({d['m5_lag']:.0f} months at the median on the {d['m5_specs']} specs affected) closed at source.",
         "Material issues at actual price against the quote's implied price", f"0 of {d['m5_rows']:,} (controlled at source)"),
        (f"Lines re-tied to jobs by the part number on the line where the buyer typed one ({d['att_methods'].get('part number and date on the PO line', 0):,}), otherwise by vendor, "
         f"service, quantity and receipt window against the jobs open ({d['att_methods'].get('vendor, service, quantity and receipt window', 0):,}); each with a confidence and the "
         f"controller's or production manager's confirmation. {d['m6_resid']:,} lines with a generic description and several open jobs could not be attributed and stay in the general ledger, allocated to the month's jobs and tagged" + (f"; {d['m6_after']} lines placed after the job number became required still carry none" if d['m6_after'] else ""),
         "PO lines, vendor records, the jobs open on the receipt window; controller and production manager",
         rem_of(d['m6_att'], d['m6_rows'], f"{d['m6_resid']:,} residual in GL, allocated")),
        (f"A program crosswalk built with the cell leads maps each of the {d['xw_generic']} generic programs to the parts that share it, and the warehouse settles each machine interval on the job "
         f"open for one of those parts that day. Of the {d['m7_rows']} routing operations that name a generic program, {d['m7_unres_ops']} run on the {d['xw_unresolved']} program-machine pairs "
         f"the cell leads could not place; those operations are costed from the corrected clock record instead",
         "Routings and the monitoring feed; CNC cell leads",
         rem_of(d['m7_fixed'], d['m7_rows'], f"{d['m7_unres_ops']} costed from the clock record")),
        ("Each own product recosted at current material, pool rates and measured standards",
         "Current cost from the warehouse; controller review", rem_of(14, 14)),
    ]
    REM_T = [
        (f"Records left open were capped and reallocated where the machine data supports it: on the monitored cells the job's hours come from the machine, so the open record is superseded; "
         f"elsewhere the record is flagged unrepairable and its hours shown but not relied on.",
         "Machine-monitoring hours assigned to the job; the operator's next record on the job", rem_of(d['t1_repaired'], t1n, f"{d['t1_unrep']:,} flagged unrepairable")),
        ("Not corrected in the history, because a single run record cannot be split after the fact. Controlled at source: the cell terminals now carry setup, run, rework and indirect codes",
         ERP, f"0 of {int(reg.loc['T2', 'rows_affected']):,} (controlled at source)"),
        ("Each record re-pointed to the adjacent job number whose routing fits the record and which was open on the day; where no adjacent job fits the record is flagged.",
         "The job's routing against the record's operation and cell; the adjacent jobs open", rem_of(d['t3_repaired'], int(reg.loc['T3', 'rows_affected']), f"{d['t3_unrep']} flagged unrepairable")),
        ("Split by machine hours: each machine's own hours go to the job it ran, so the single record is superseded on the cell it names and the other machines' jobs carry their own measured time.",
         "Machine-monitoring hours by job on each cell", rem_of(d['t4_repaired'], int(reg.loc['T4', 'rows_affected']), f"{d['t4_unrep']} unassignable, flagged")),
        ("Moved to indirect: the record posted on top of an open record on the same job is taken off the job and its hours go to indirect.",
         "The operator's open record on the same job; machine idle through the record where the cell is monitored", rem_of(d['t5_removed'], int(reg.loc['T5', 'rows_affected']))),
        (f"Hours posted to the catch-all operation retyped as rework ({d['t6_999']} events). The {d['t6_run']} events whose hours posted as production on the operation cannot be separated from it "
         f"and stay in run time, noted on the job. Controlled at source by the rework code",
         "Rework events against the labor records on the job and operation", rem_of(d['t6_999'], d['t6_999'] + d['t6_run'], f"{d['t6_run']} stay in run time")),
        (f"Reason codes and job numbers on the {d['t7_rec']:,} recorded events are not recoverable and were left as posted; the {d['t7_inf']:,} jobs that drew a few percent more stock than the part "
         f"needs with no scrap event are listed as probable unrecorded scrap for the quality manager. Controlled at source: the reason code is required and scrap is logged at the cell",
         "Recorded events; stock issued against the part's need", f"0 of {d['t7_rec']:,} (controlled at source)"),
        (f"Material on each affected job corrected to the part's need at the job's own issued price: {d['t8_over']:,} jobs charged another job's bar brought back to need, {d['t8_under']:,} jobs "
         f"whose bar was never issued charged their need. Each correction carries the confidence of the detection; the stockroom lead reviewed the list.",
         "Issues against the part's need per piece, measured across its jobs; stockroom lead", rem_of(len(d['t8']), len(d['t8']))),
        (f"Not corrected: an operation with no scan is costed at the routing standard and tagged estimated on the job. Scan coverage at the secondary operations now stands at {pc(d['scan_last'])}, and the cell leads chase missing scans daily",
         "Routing operations the job reached against the scan records", f"0 of {d['t9_jobs']:,} jobs (costed at standard, tagged)"),
        (f"Not repaired in the history: the hours were never recorded and cannot be recovered, so every operation through the three cells before the rollout is costed at the routing standard and tagged estimated "
         f"({d['t10_hours']:,.0f} standard hours across {d['t10_jobs']:,} jobs). Controlled at source: every secondary operation is now scanned and every cell has its own terminal, with coverage tracked weekly",
         "Routing operations against the labor records; the weekly scan coverage series", f"0 of {d['t10_jobs']:,} jobs (costed at standard, tagged)"),
    ]
    rem_hdr = ["", "Error", "Remediation", "Evidence", "Remediated (rows)"]
    rem_master_table = _widths(B.data_table(rem_hdr, [[numcell(i), e[0], *REM_M[i - 1]] for i, e in enumerate(MASTER, 1)], right=[]), W3)
    rem_txn_table = _widths(B.data_table(rem_hdr, [[numcell(i), e[0], *REM_T[i - len(MASTER) - 1]] for i, e in enumerate(TXN, len(MASTER) + 1)], right=[]), W3)
    did = f"""
{B.section("did", "Section 2.2", "Error Remediation")}
<p>Most of the errors in Section 2.1 were closed in full, and the reasons for any partial remediation are given in
the table below. Five errors were controlled at source rather than repaired in the history (setup and run
separation, the scrap reason code, the material price list, the missing scans and the three cells that never
posted labor), so the records still carry them but will be clean going forward.</p>

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Master and Configuration-level Table Error Remediation</p>
{rem_master_table}

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Transaction-level Table Error Remediation</p>
{rem_txn_table}

"""

    # ── results ──────────────────────────────────────────────────────────
    res_rows = [
        ["Jobs with an estimate attached by cost element", "The comparison that job costing exists for is possible", pc(r["estimate"][0]), pc(r["estimate"][1])],
        ["Job cost dollars on accurate transactions, recorded on the right job", "Actual job cost reflects what each job really consumed", pc(r["accurate"][0]), pc(r["accurate"][1])],
        ["CNC run hours sourced from machine monitoring", "The largest cost element no longer depends on clock-ins", pc(r["machine"][0]), pc(r["machine"][1])],
        ["Clocked hours within 10% of machine hours on monitored cells", "The labor record agrees with an independent measurement", pc(r["clocked"][0]), pc(r["clocked"][1])],
        ["Secondary-operation hours captured by scan", "Hours at the saw, deburr, inspection and assembly operations, which have no machine monitoring, are recorded rather than taken from the routing standard", pc(r["scan"][0]), pc(r["scan"][1])],
        ["Labor records with setup, run, rework and indirect separated", "Small-lot economics and rework cost are visible", pc(r["codes"][0]), pc(r["codes"][1])],
        ["Outside processing tied to a job", "Vendor cost lands on the job that incurred it", pc(r["osp"][0]), pc(r["osp"][1])],
        ["Repeat parts with routing standards measured from machine data", "Estimates rest on current cycle times", pc(r["standards"][0]), pc(r["standards"][1])],
        ["Repeat parts below target with a pricing decision", "Standing prices reflect today's material and rates", pc(r["priced"][0]), pc(r["priced"][1])],
        ["Work centers costed at their own rate", "Manual and 5-axis jobs are no longer averaged together", "0 of 38", "38 of 38"],
        ["Scrap events with a job and a reason", "Scrap cost reaches the job and the cause is known", pc(r["scrap"][0]), pc(r["scrap"][1])],
        ["Historic labor records with an error repaired or explicitly flagged", "The three-year history can be used with its limits stated", pc(r["history"][0]), f"{pc(r['history'][1])}<br><em>{pc(d['pre_repaired'])} repaired, {pc(d['pre_unrep'], 1)} flagged</em>"],
    ]
    res_table = _widths(B.data_table(["Measure", "Why it matters", "Before", "After"], res_rows, right=[2, 3]), [36, 36, 14, 14])
    results = f"""
{B.section("results", "Section 2.3", "Results")}
<p>The error remediation process above improved the accuracy of the ERP's data records and the reliability of its
job cost figures. Every job now carries its estimate by element, and {pc(r['measured'][1])} of the cost on jobs
completed under the new process is measured from a transaction. The results of the error remediation are presented
below. Before is the twelve months before the engagement ({d['n_before']:,} jobs, the records as the ERP held them);
after is the {d['n_after']:,} jobs released and completed following remediation.</p>
{res_table}
"""

    # ── process changes ──────────────────────────────────────────────────
    CONFIG = [
        ("Estimate carries to the job on conversion", "Converting a quote copies its estimate by element (material, setup, run by work center, outside processing) onto the job, and a job cannot be released without one.", "Puts the estimate on every new job, the system change described in Section 1."),
        ("Job number required on outside-processing purchase orders", "A PO line on the outside-processing account cannot be saved without a job number; the line and its receipt land on that job.", "Closes #5."),
        ("Work-center rate pools", "Each work center carries its own labor rate, burden rate and attended ratio; estimates and actuals cost at the cell's rate.", "Closes #2. Addresses #3: current cost is right by cell."),
        ("Terminals at the cells", "The two door terminals are retired; each cell has its own, so the operator clocks on where the work is, and every cell posts.", "Closes #17. Addresses #8, #11 and #12: a record is opened at the machine, not at the door."),
        ("One open operation per employee", "Opening a second operation closes the first; a record cannot cover two machines.", "Closes #11."),
        ("Auto-close at shift end with review flag", "Any record still open at shift end closes at the shift boundary and is flagged for the cell lead's review the next morning.", "Closes #8."),
        ("Setup, run, rework and indirect codes", "The terminal asks for the code; setup and run post separately, rework posts under its own code, indirect posts with no job.", "Closes #9, #12 and #13."),
        ("Scrap reason required", "A scrap or rework event cannot be saved without a job, an operation and a reason code from the list.", "Closes #14 for recorded events; addresses the unrecorded ones by making the entry a thirty-second job at the cell."),
        ("Monitoring feed posts machine hours to jobs", "The machine-monitoring feed carries the job the operator opened at the cell, so setup, cycle, alarm and in-operation idle post to the job automatically.", "Closes #1 at source and #6: the standard is measured from the feed, and the program name no longer matters. Addresses #8 and #11: the machine's hours replace the clock record on every monitored cell."),
        ("Standard-cost fallback with estimated tag", "An operation with no scan, record or machine hours by the time the next operation starts is costed at the routing standard and tagged estimated on the job.", "Addresses #16 and #17: a missing scan or a cell that has not posted is visible on the job and on the coverage screen rather than silently absent."),
    ]
    config_table = _widths(B.data_table(["Change", "What it does", "Impact"], [list(c) for c in CONFIG], right=[]), [24, 46, 30])
    v = d["values"]
    PROCESS = [
        ("Monthly repricing review", "The controller opens the repricing queue on the first Tuesday of the month; the parts below cost plus target are decided one by one, and a held part comes back the next month.", "Closes #3 and #7 going forward: a standing price can be no more than a month behind current cost.",
         f"{money(v['gap'])} a year separates the {v['n_below']} repeat parts below target from current cost plus target; the repricing decisions took {money(v['taken'])}; the {money(v['gap'] - v['taken'])} balance sits on the parts held by decision, which the review revisits each month.", "Controller, owner", "Monthly"),
        ("Quarterly routing standard refresh from machine data", "Setup and cycle times measured over the last three lots on every repeat part the machines ran; the estimator reviews each change.", "Closes #1 going forward.",
         f"On engagement-period repeat jobs, the median run-hours error is {pc(v['acc_refreshed'])} on the {v['n_used']} jobs estimated after the part's refreshed standard took effect, against {pc(v['acc_stale'])} on the {v['n_not']} estimated before it; the {v['parts_unrefreshed']:,} repeat parts that did not run on a monitored cell are measured the next time they run.", "Estimator, production manager", "Quarterly"),
        ("Weekly coverage review by work center", "Measured share of cost and scan coverage by cell; a cell below 85% two weeks running is raised with the production manager.", "Addresses #16 and #17 and the estimated tag: coverage cannot drift unnoticed.",
         f"In the most recent week, {pc(1 - v['scan_last'])} of secondary operations went unscanned; over the last four weeks, {money(v['fallback_cost'])} of the cost on completed jobs sat on the routing standard ({pc(v['fallback_share'], 1)} of that cost), each dollar named on its job.", "Production manager", "Weekly"),
        ("Monthly estimate-accuracy review by element", "Actual over estimate by element on the month's closed jobs, by estimator, material and lot band; the estimating rules change where the ratio drifts.", "Addresses #1, #4 and the estimator bias the diagnostic found.",
         f"The titanium and Inconel bias it would have surfaced: run hours over the estimate on new work in those two alloys cost {money(v['p5'])} in {v['year']} (jobs ran {v['run_bias']:.2f} times their estimated run hours against {v['run_rest']:.2f} on every other material).", "Estimator, controller", "Monthly"),
        ("Quarterly rate pool refresh", "Pool rates recomputed from the rate history and the quarter's machine hours and headcount by cell.", "Keeps #2 closed.",
         f"What the one blended rate hid: {v['hidden_family']} looked {pc(v['hidden_blended'])} on price under the blended rate and earns {pc(v['hidden_pool'])} under the pools, {money(v['p4'])} a year short of target.", "Controller", "Quarterly"),
        ("Scrap reason review", "The month's scrap and rework events by reason, cell and part family; the probable unrecorded scrap list is walked with the cell leads.", "Addresses #14 and #15.",
         f"{v['t7_inferred']:,} jobs before the reason code drew 1 to 7% more stock than the part needs with no scrap event, {v['t7_pieces']:,} probable pieces never written down; since the code, {pc(v['scrap_after'])} of events carry a job and a reason.", "Quality manager", "Monthly"),
        ("Retirement of the estimator's spreadsheet into the quoting module", "Material prices, speeds and feeds, vendor prices and the measured standards live in the quoting module; the spreadsheet is retired once the last quote template is migrated.", "Closes #4 and the vendor-price gap; addresses #1.",
         f"{pc(v['ss_share'])} of quote lines were priced on the spreadsheet's figures rather than the ERP's. {pc(v['m5_ss'])} of the {v['m5_lines']:,} stale-material lines (#4) are spreadsheet lines. Across all lines the accuracy difference is small: median material error {pc(v['acc_ss_material'], 1)} against {pc(v['acc_erp_material'], 1)}, outside processing {pc(v['acc_ss_outside'])} against {pc(v['acc_erp_outside'])}, total cost {pc(v['acc_ss_total'], 1)} against {pc(v['acc_erp_total'], 1)}; the value is in closing #4 and the vendor-price gap, not in the average.", "Estimator, ERP administrator", "Once, then continuous"),
        ("The monthly metrics on the dashboard with targets", "Gross margin by job type, estimate accuracy by element, jobs below target, cost coverage, scan coverage, repricing decisions, customer margin, outside-processing variance and scrap cost, each against a target.", "Addresses all seventeen: any error that returns shows up in a number someone owns.",
         "No value of its own: it is where the seven above are seen each month, and it is not counted.", "Controller; reviewed by the owner", "Monthly"),
    ]
    process_table = _widths(B.data_table(["Change", "What it does", "Impact", "Value, from the data", "Owner", "Cadence"], [list(p) for p in PROCESS], right=[]), [15, 25, 18, 24, 10, 8])
    keep = f"""
{B.section("process", "Section 2.4", "Process Changes")}
<p>The error remediation in Section 2.2 corrected the ERP's records. The changes in this section are designed to
keep them cleaned, and fall into two categories.</p>
<p>The first category is the ERP system settings. These are configured once, take effect for every user, and
stop most of the errors at the point of entry. This category holds on its own.
The table lists each change, what it does and the errors it <em>closes</em> (the error can no longer occur) or
<em>addresses</em> (the error is caught or reduced, but not prevented).</p>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Changes to ERP System Settings</p>
{config_table}
<p>The second group is process changes that will require ongoing ownership and organizational alignment. That
makes this category the harder lift. The shop has committed to the owners and cadences below, and keeping them is
what protects the results in Section 2.3.</p>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Changes Requiring Ongoing Processes and Ownership</p>
{process_table}
"""
    appendix = build_appendix(d)
    return impl + found + did + results + keep + appendix, toc


APPENDIX_TABLES = [
    ("Part master", "erp/part_master.csv", "One row per part number and revision: what it is made of, who buys it, the standing price and when it was set; on the fourteen own products the flag is set and the part carries its standard cost and list price."),
    ("Routings", "erp/routings.csv", "One row per operation on a part's routing: the work center, the setup and run standards, the CNC program and when the standard was last touched."),
    ("Work centers", "erp/work_centers.csv", "One row per work center, with the monitoring flag and the machine the feed reports under."),
    ("Work center rates", "erp/work_center_rates.csv", "One row per work center and effective date: the labor and burden rates the ERP costs an hour at, and the attended ratio."),
    ("Customers", "erp/customers.csv", "One row per customer, with the change-order and expedite counts of the last twelve months."),
    ("Quotes", "erp/quotes.csv", "One row per quote line and quantity break: a line prices one part number at several quantities (for example 25, 50, 100 and 250 pieces), with the estimate by element and the price per piece at each break, the basis the line was priced on (the ERP's figures or the estimator's spreadsheet), the status and the job it became."),
    ("Jobs", "erp/jobs.csv", "One row per job: the part, customer, quantity, dates and price, the estimate by element (blank before the configuration change) and the ERP's own actuals."),
    ("Labor transactions", "erp/labor_transactions.csv", "One row per clock record: job, operation, work center, employee, clock-on and clock-off, the labor code and the source (door or cell terminal, traveler scan, auto-close)."),
    ("Machine monitoring", "monitoring/machine_monitoring.csv", "One row per machine state interval from the monitoring feed: setup, in cycle, idle, alarm or offline, with the program, the cycle count and, once the feed was connected, the job."),
    ("Material transactions", "erp/material_transactions.csv", "One row per stock issue or return: job, material spec, quantity, unit cost, date and source (saw, stockroom, backflush). Issues are valued at the average cost of the stock on hand at issue time, which sits a little off the purchase price when material is moving."),
    ("Outside processing", "erp/outside_processing.csv", "One row per purchase-order line: vendor, service, the job number where the buyer entered one, the GL account, the typed description, quantity, price, dates and the invoice."),
    ("Scrap and rework", "erp/scrap_rework.csv", "One row per scrap or rework event: job, operation, type, quantity, reason code (blank where none was given), who reported it and when."),
]


def _cell(v):
    if pd.isna(v) or str(v).strip() in ("", "nan", "None"):
        return '<span style="color:#9AA5B1;">(blank)</span>'
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 100 else f"{v:g}"
    return str(v)


def build_appendix(d):
    """Every table in the diagram: what a row is, its columns, and five representative rows."""
    parts = []
    for title, rel, what in APPENDIX_TABLES:
        path = RAW / rel
        n = _rows(path)
        # rows from the middle of the file rather than the top, so dates and blanks look like the run of the data
        df = pd.read_csv(path, low_memory=False)
        pick = df.iloc[[int(len(df) * f) for f in (0.10, 0.30, 0.50, 0.70, 0.90)]] if len(df) > 5 else df
        rows = [[_cell(v) for v in r] for r in pick.itertuples(index=False)]
        table = B.data_table(list(df.columns), rows)
        table = table.replace('<table class="data-table">', '<table class="data-table appendix">', 1)
        parts.append(f'<p style="font-size:16px;font-weight:700;color:{B.DARK_GREY};margin:26px 0 4px;">{title} <span style="font-weight:400;color:{B.MED_GREY};font-size:13px;">'
                     f'{n:,} rows &middot; {len(df.columns)} columns</span></p><p style="font-size:14px;margin-bottom:6px;">{what}</p>'
                     f'<div style="overflow-x:auto;">{table}</div>')
    return f"""
{B.section("appendix", "Appendix", "Appendix (ERP Detail)")}
{''.join(parts)}
"""


def cl_over(d):
    """Clocked hours over machine hours on the monitored cells in the year before the engagement."""
    cvm = _pq("mart_clocked_vs_machine")
    y = cvm[(cvm["month"] >= pd.Timestamp(C.ENGAGEMENT_START) - pd.DateOffset(years=1)) & (cvm["month"] < pd.Timestamp(C.ENGAGEMENT_START))]
    return y["clocked_hours"].sum() / y["machine_active_hours"].sum() - 1


def run():
    d = gather()
    body, toc = build(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = B.page("Report: Job Costing ERP Implementation &amp; Data Quality Audit", "", toc, body)
    html = html.replace("</style></head>", ".section-title-block.sub .section-title{font-size:18px;font-weight:700;}"
                        ".data-table.appendix{font-size:11.5px;white-space:nowrap;margin:6px 0 4px;}"
                        ".data-table.appendix th{font-size:10.5px;padding:6px 8px;}.data-table.appendix td{padding:5px 8px;}</style></head>", 1)
    OUT.write_text(html, encoding="utf-8")
    print(f"Data quality audit written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
