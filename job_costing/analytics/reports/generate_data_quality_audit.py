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
                        ("Work centers and rates", _rows(RAW / "erp" / "work_centers.csv") + _rows(RAW / "erp" / "work_center_rates.csv")),
                        ("Own-product standards", 14), ("Customers", _rows(RAW / "erp" / "customers.csv"))]
    d["txn_comp"] = [("Quotes", _rows(RAW / "erp" / "quotes.csv")), ("Jobs", _rows(RAW / "erp" / "jobs.csv")), ("Labor transactions", _rows(RAW / "erp" / "labor_transactions.csv")),
                     ("Machine monitoring", _rows(RAW / "monitoring" / "machine_monitoring.csv")), ("Material transactions", _rows(RAW / "erp" / "material_transactions.csv")),
                     ("Outside processing", _rows(RAW / "erp" / "outside_processing.csv")), ("Scrap and rework", _rows(RAW / "erp" / "scrap_rework.csv"))]
    d["total_rows"] = sum(n for _, n in d["master_comp"] + d["txn_comp"])

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
    d["m2_faster"] = float((m2["direction"] == "cycle now faster than standard").mean())
    xw = d["xw"]; d["xw_unique"] = int((xw["method"] == "routing match").sum()); d["xw_generic"] = xw[xw["method"].str.startswith("cell")]["program_number"].nunique()
    d["xw_unresolved"] = int((xw["status"] == "unresolved").sum()); d["m7_programs"] = d["m7"]["program_number"].nunique()
    att = d["att"]; d["att_ok"] = int((att["status"] == "attributed").sum()); d["att_res"] = int((att["status"] != "attributed").sum())
    d["att_methods"] = att[att["status"] == "attributed"]["method"].value_counts().to_dict()
    d["m6_pre"] = int(d["reg"].loc["M6", "rows_affected"]); d["m6_scope"] = int(d["reg"].loc["M6", "rows_in_scope"])
    bf = d["backfill"]; d["bf_quote"] = int(bf["est_total_cost"].notna().sum()); d["bf_none"] = int(bf["est_total_cost"].isna().sum())
    d["bf_methods"] = bf["method"].value_counts().to_dict()
    q = d["queue"]; below = q[q["below_target"]]; d["m4_n"] = len(below); d["m4_dec"] = int(below["decision"].notna().sum()); d["m4_decisions"] = below["decision"].value_counts().to_dict()
    d["m5_specs"] = d["m5"]["material_spec"].nunique(); d["m5_lines"] = len(d["m5"]); d["m5_lag"] = float(d["m5"]["lag_months"].median())
    d["t9_n"] = len(d["t9"])

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
    cov = d["cov"].dropna(subset=["scan_coverage"]); d["scan_last"] = float(cov["scan_coverage"].iloc[-1]); d["scan_first"] = float(cov["scan_coverage"].iloc[0])
    d["scan_week_first"], d["scan_week_last"] = int(cov["engagement_week"].iloc[0]), int(cov["engagement_week"].iloc[-1])
    return d


# ── ERD ─────────────────────────────────────────────────────────────────────
def chart_erd(d):
    """The tables examined and how they relate through the job number. Masters
    on top; transactions below, every one keyed on the job."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    rows = dict(d["master_comp"] + d["txn_comp"])
    fig, ax = plt.subplots(figsize=(10.5, 4.3))
    ax.set_xlim(0, 100); ax.set_ylim(0, 48); ax.axis("off")

    def box(x, y, w, h, title, key, master):
        face = B.DARK_BLUE if master else B.MED_GREY
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8", facecolor=face, edgecolor=face, linewidth=1.2))
        ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=9.2, color="white", fontweight="bold")
        ax.text(x + w / 2, y + h * 0.28, f"{rows[key]:,} records", ha="center", va="center", fontsize=7.4, color="white")

    def seg(pts):
        xs, ys = zip(*pts); ax.plot(xs, ys, color=B.MED_GREY, linewidth=1.1, zorder=0, solid_capstyle="round")

    def head(p0, p1):
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=13, color=B.MED_GREY, linewidth=1.1, shrinkA=0, shrinkB=0, zorder=1))

    # masters on top: the part carries its routing, which names its work centers; the
    # own product carries its standard. Quotes and jobs are documents and sit in the
    # middle row; every transaction below is keyed on the job number.
    mw, gap = 15.0, 5.5
    mx = [1 + i * (mw + gap) for i in range(5)]
    for x, (title, key) in zip(mx, [("Customers", "Customers"), ("Part master", "Part master"), ("Routings", "Routings"),
                                    ("Work centers", "Work centers and rates"), ("Own products", "Own-product standards")]):
        box(x, 36, mw, 10, title, key, True)
    head((mx[1] + mw, 41), (mx[2], 41))      # a part carries its routing
    head((mx[2] + mw, 41), (mx[3], 41))      # a routing names its work centers
    head((mx[4], 41), (mx[3] + mw, 41))      # an own product's standard costs at the work centers
    # the quote prices a part for a customer; the job converts from the quote, for the part, on its routing
    box(8, 20, 22, 9, "Quotes", "Quotes", False)
    box(39, 20, 22, 9, "Jobs", "Jobs", False)
    head((mx[0] + mw / 2, 36), (mx[0] + mw / 2, 29))                       # customer -> quote
    seg([(mx[1] + mw / 2, 36), (mx[1] + mw / 2, 32.5), (19, 32.5)]); head((19, 32.5), (19, 29))   # part -> quote
    seg([(mx[1] + mw / 2 + 2, 36), (mx[1] + mw / 2 + 2, 32.5), (46, 32.5)]); head((46, 32.5), (46, 29))   # part -> job
    seg([(mx[2] + mw / 2, 36), (mx[2] + mw / 2, 32.5), (54, 32.5)]); head((54, 32.5), (54, 29))   # routing -> job
    head((30, 24.5), (39, 24.5))                                          # quote -> job
    # transactions, each keyed on the job number
    tx = [1, 20.5, 40, 59.5, 79]; tw = 19.5
    for x, (title, key) in zip(tx, [("Labor transactions", "Labor transactions"), ("Machine monitoring", "Machine monitoring"), ("Material transactions", "Material transactions"),
                                    ("Outside processing", "Outside processing"), ("Scrap and rework", "Scrap and rework")]):
        box(x, 3, tw, 9, title, key, False)
        cx = x + tw / 2
        seg([(50, 20), (50, 16), (cx, 16)]); head((cx, 16), (cx, 12))
    ax.text(50, 14.2, "job number", ha="center", va="center", fontsize=8, color=B.MED_GREY, style="italic",
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    return B.b64(fig)


def _widths(table_html, widths):
    cols = "".join(f'<col style="width:{w}%;">' for w in widths)
    return table_html.replace('<table class="data-table">', f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


def numcell(i):
    return f'<td style="vertical-align:middle;text-align:center;">#{i}</td>'


def build(d):
    reg = d["reg"]; r = d["results"]
    toc = "".join(['<a href="#found">Findings</a>', '<a href="#did">Error Remediation</a>', '<a href="#results">Results</a>', '<a href="#process">Process Changes</a>',
                   '<a href="#appendix">Appendix (ERP Detail)</a>'])
    sub = lambda t: f'<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">{t}</p>'

    def rows_of(code):
        n, tot = int(reg.loc[code, "rows_affected"]), int(reg.loc[code, "rows_in_scope"])
        return f"{n:,} of {tot:,}<br><em>({n / tot * 100:.1f}%)</em>"

    def rem_of(n, tot, note=""):
        s = f"{n:,} of {tot:,} ({n / tot * 100:.0f}%)" if tot else f"{n:,}"
        return s + (f"<br><em>{note}</em>" if note else "")

    JOBS, ROUT, RATES, PARTS, QUOTES, OSP, OWN = "Jobs", "Routings", "Work center rates", "Part master", "Quotes", "Outside processing", "Own-product standards"
    LAB, SCRAP, MAT = "Labor transactions", "Scrap and rework", "Material transactions"
    MASTER = [
        ("Estimate Not Attached to the Job", "Quotes converted to jobs without the estimate; the estimate existed only in the quoting module, and the job carried no cost to compare against.", JOBS, rows_of("M1")),
        ("Stale Routing Standards", "Setup and run standards entered at first quote and never updated, while machines were replaced and programs optimized; measured against the machine-monitoring cycle.", ROUT, rows_of("M2")),
        ("One Blended Shop Rate", "A single labor and burden rate on every work center, from the manual drill press to the five-axis cell, refreshed once a year.", RATES, rows_of("M3")),
        ("Standing Prices Not Repriced", "Repeat parts sold at the price set at first quote, moved only by the annual across-the-board letter; below current cost plus the target markup.", PARTS, rows_of("M4")),
        ("Stale Material Cost in Estimates", "The estimator's spreadsheet priced material from a list refreshed irregularly; quote lines whose material sits more than 5% under the price the shop paid that month.", QUOTES, rows_of("M5")),
        ("Outside Processing Not Tied to Jobs", "Purchase-order lines for plating, heat treat, coating and grinding coded to a general-ledger account with no job number.", OSP, rows_of("M6")),
        ("Generic Program Numbers", "CNC programs named generically (MAIN, TEST, PROG1) or reused across parts, breaking the program-to-part mapping the monitoring feed depends on.", ROUT, rows_of("M7")),
        ("Own-product Standard Costs Never Revised", "The standard cost on each own product set at launch and never revised, with the list price built on it.", OWN, rows_of("M8")),
    ]
    TXN = [
        ("Jobs Left Clocked In", "Clock records left open across a break, a shift end or the night at the door terminal, so the record carries hours the job did not take.", LAB, rows_of("T1")),
        ("Setup and Run Not Separated", "The door terminal offered one clock-on, so every record posted as run time; setup, rework and indirect were indistinguishable.", LAB, rows_of("T2")),
        ("Time Charged to the Wrong Job", "Time posted to an adjacent job number picked from the terminal's dropdown; the job's routing does not fit the record.", LAB, rows_of("T3")),
        ("Multi-machine Tending Recorded as One Job", "One operator tending two or three monitored machines under a single clock record on the first job.", LAB, rows_of("T4")),
        ("Indirect Time Charged to Jobs", "Waiting, meetings and cleanup posted on top of whatever job the operator had open.", LAB, rows_of("T5")),
        ("Rework Recorded as Run Time", "No rework operation on the routing and no rework code, so rework hours posted as production on the operation or on a catch-all operation.", SCRAP, rows_of("T6")),
        ("Scrap Without Reason or Without Job", "Recorded scrap and rework events missing the reason code or the job number; scrap thrown in the bin never reached the system at all.", SCRAP, rows_of("T7")),
        ("Material Issued to the Wrong Job or Not Issued", "Bar pulled for two jobs and charged to one; remnants used and never issued. Jobs whose issues sit far from the part's need.", MAT, rows_of("T8")),
        ("Missing Scans During Rollout", "Secondary operations the job reached with no traveler scan, from the week the scanning pilot began.", LAB, rows_of("T9")),
    ]
    W2 = [4, 19, 40, 16, 21]; W3 = [4, 19, 42, 18, 17]
    hdr = ["", "Error", "Description", "ERP table", "Scale<br><em style=\"font-weight:400;text-transform:none;\">(rows affected)</em>"]
    master_table = _widths(B.data_table(hdr, [[numcell(i), n, desc, loc, sc] for i, (n, desc, loc, sc) in enumerate(MASTER, 1)], right=[]), W2)
    txn_table = _widths(B.data_table(hdr, [[numcell(i), n, desc, loc, sc] for i, (n, desc, loc, sc) in enumerate(TXN, len(MASTER) + 1)], right=[]), W2)

    m1 = int(reg.loc["M1", "rows_affected"]); t1n = int(reg.loc["T1", "rows_affected"]); m6n = int(reg.loc["M6", "rows_affected"])
    found = f"""
{B.section("found", "Section 1", "Findings")}
<p>This data quality audit examined the shop's ERP job costing records end to end, together with the
machine-monitoring feed that had never been connected to them. The master tables examined were the
part master, the routings, the work centers and their rates, the own-product standards and the customers; the
transaction tables were the quotes, the jobs, the labor transactions, the machine-monitoring intervals, the
material transactions, the outside-processing purchase orders and the scrap and rework events. They relate
through the job number as shown below. Each table's columns and a few of its rows are in the appendix.</p>

{B.chart("ERP Tables", chart_erd(d))}

<p>Over the 36 months from {pd.Timestamp(C.START_DATE):%B %Y} to {pd.Timestamp(C.END_DATE):%B %Y}, <strong>{d['total_rows'] / 1e6:.1f} million</strong>
records were produced across these twelve tables, {d['txn_comp'][2][1] / 1e3:.0f}K of them labor transactions and
{d['txn_comp'][3][1] / 1e6:.1f} million machine-monitoring intervals. This audit reviewed all of them and found
<strong>17</strong> types of data quality error recurring over the period: eight at the master and configuration
level (the records and settings every job is costed from), nine at the transaction level. Together they left the ERP unable to say what any job had cost.</p>

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Master and Configuration-level Table Errors</p>
{master_table}

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Transaction-level Table Errors</p>
{txn_table}

<p>Three errors stand out for their scale and their effect. First, no job carried an estimate: all
{m1:,} jobs released before the configuration change converted from their quotes without the estimate, so the
comparison job costing exists for was impossible, and the estimator had never seen a job's actuals. Second,
the labor records were right in total and wrong by job: {t1n:,} clock records were left open across a break, a
shift or the night, and with the multi-machine records and the indirect time posted on open jobs, the
clocked hours on the monitored cells ran {pc(cl_over(d))} above the hours the
machines actually ran. Third, {m6n:,} of the {d['m6_scope']:,} outside-processing purchase-order lines before the change
({pc(m6n / d['m6_scope'])}) carried no job number, so the shop's plating, heat-treat, coating and grinding cost
never reached the job that incurred it.</p>
"""

    # ── remediation ──────────────────────────────────────────────────────
    ERP = "ERP records only"
    REM_M = [
        (f"Estimates loaded onto every historic job from the quoting module, by element: {d['bf_methods'].get('won quote line on the job', 0):,} from the won quote line, "
         f"{d['bf_methods'].get('standing price quote, scaled to job quantity', 0):,} from the part's standing-price quote scaled to the job quantity, "
         f"{d['bf_methods'].get('own-product standard cost', 0)} from the own-product standard; each carries a match confidence. "
         f"{d['bf_none']} jobs with no quote line carry the routing standard at the shop rate, tagged.",
         "Quoting module; material price at the quote date recovered from the issues", rem_of(d['bf_quote'], m1, f"{d['bf_none']} at the routing standard, tagged")),
        (f"Setup and cycle times measured from the machine-monitoring feed over the last three lots on {d['std_parts']:,} repeat parts ({d['std_ops']:,} operations); the estimator reviewed each and "
         f"accepted {d['std_accepted']:,}, disputed and kept the old standard on {d['std_kept']}, and disputed and adjusted {d['std_adj']}. The refreshed standard carries an effective date.",
         "Machine-monitoring cycle and setup intervals, mapped through the program crosswalk; estimator review", rem_of(d['m2_refreshed'], d['m2_parts'], "of the flagged parts; the rest in the quarterly refresh")),
        ("Work-center rate pools built from the rate history, the machine hours and the headcount by cell: a labor rate, a burden rate and an attended ratio per work center, "
         "with the attended ratios set from floor observation. Live from week 5.",
         "Rate history, machine hours, headcount; production manager's observation of attended ratios", rem_of(38, 38)),
        (f"Every repeat part put against its current cost at today's material price, the pool rates and the measured standards on the repricing queue. The controller and the owner reviewed the "
         f"bottom quartile part by part in weeks 7 to 9: {d['m4_decisions'].get('reprice', 0)} repriced, {d['m4_decisions'].get('hold', 0)} held, {d['m4_decisions'].get('exit', 0)} exited, {d['m4_decisions'].get('pending', 0)} pending.",
         "Current cost from the warehouse; controller and owner decisions", rem_of(d['m4_dec'], d['m4_n'], "of the parts below target reviewed; the rest in the monthly review")),
        (f"Not corrected line by line: the spreadsheet's price list was retired and the quoting module now prices material at the current issued price, with the lag "
         f"({d['m5_lag']:.0f} months at the median on the {d['m5_specs']} specs affected) closed at source.",
         "Material issues at actual price against the quote's implied price", f"0 of {d['m5_lines']:,} (controlled at source)"),
        (f"Lines re-tied to jobs by the part number on the line where the buyer typed one ({d['att_methods'].get('part number and date on the PO line', 0):,}), otherwise by vendor, "
         f"service, quantity and receipt window against the jobs open ({d['att_methods'].get('vendor, service, quantity and receipt window', 0):,}); each with a confidence and the "
         f"controller's or production manager's confirmation. {d['att_res']:,} lines with a generic description and several open jobs could not be attributed and stay in the general ledger, allocated to the month's jobs and tagged.",
         "PO lines, vendor records, the jobs open on the receipt window; controller and production manager", rem_of(d['att_ok'], m6n, f"{d['att_res']:,} residual in GL, allocated")),
        (f"A program crosswalk built with the cell leads: {d['xw_unique']:,} programs map to one part from the routing; the {d['xw_generic']} generic names were resolved to the parts that share them, "
         f"and the warehouse settles each interval on the job open for one of those parts that day. {d['xw_unresolved']} program-machine pairs stayed unresolved and their hours are unassigned.",
         "Routings and the monitoring feed; CNC cell leads", rem_of(d['xw_generic'], d['m7_programs'], f"{d['xw_unresolved']} program-machine pairs unresolved")),
        ("Each own product recosted at current material, pool rates and measured standards; the controller reviewed the fourteen in week 8 and the three selling below cost went to the owner with the repricing list.",
         "Current cost from the warehouse; controller review", rem_of(14, 14)),
    ]
    REM_T = [
        (f"Records left open were capped and reallocated where the machine data supports it: on the monitored cells the job's hours come from the machine, so the open record is superseded; "
         f"elsewhere the record is flagged unrepairable and its hours shown but not relied on.",
         "Machine-monitoring hours assigned to the job; the operator's next record on the job", rem_of(d['t1_repaired'], t1n, f"{d['t1_unrep']:,} flagged unrepairable")),
        ("Not corrected in the history, because a single run record cannot be split after the fact. Controlled at source from week 5: the cell terminals carry setup, run, rework and indirect codes.",
         ERP, f"0 of {int(reg.loc['T2', 'rows_affected']):,} (controlled at source)"),
        ("Each record re-pointed to the adjacent job number whose routing fits the record and which was open on the day; where no adjacent job fits the record is flagged.",
         "The job's routing against the record's operation and cell; the adjacent jobs open", rem_of(d['t3_repaired'], int(reg.loc['T3', 'rows_affected']), f"{d['t3_unrep']} flagged unrepairable")),
        ("Split by machine hours: each machine's own hours go to the job it ran, so the single record is superseded on the cell it names and the other machines' jobs carry their own measured time.",
         "Machine-monitoring hours by job on each cell", rem_of(d['t4_repaired'], int(reg.loc['T4', 'rows_affected']), f"{d['t4_unrep']} unassignable, flagged")),
        ("Moved to indirect: the record posted on top of an open record on the same job is taken off the job and its hours go to indirect.",
         "The operator's open record on the same job; machine idle through the record where the cell is monitored", rem_of(d['t5_removed'], int(reg.loc['T5', 'rows_affected']))),
        (f"Hours posted to the catch-all operation retyped as rework ({d['t6_999']} events). The {d['t6_run']} events whose hours posted as production on the operation cannot be separated from it "
         f"and stay in run time, noted on the job. Controlled at source from week 5 by the rework code.",
         "Rework events against the labor records on the job and operation", rem_of(d['t6_999'], d['t6_999'] + d['t6_run'], f"{d['t6_run']} stay in run time")),
        (f"Reason codes and job numbers on the {d['t7_rec']:,} recorded events are not recoverable and were left as posted; the {d['t7_inf']:,} jobs that drew a few percent more stock than the part "
         f"needs with no scrap event are listed as probable unrecorded scrap for the quality manager. Controlled at source from week 6: the reason code is required and scrap is logged at the cell.",
         "Recorded events; stock issued against the part's need", f"0 of {d['t7_rec']:,} (controlled at source)"),
        (f"Material on each affected job corrected to the part's need at the job's own issued price: {d['t8_over']:,} jobs charged another job's bar brought back to need, {d['t8_under']:,} jobs "
         f"whose bar was never issued charged their need. Each correction carries the confidence of the detection; the stockroom lead reviewed the list.",
         "Issues against the part's need per piece, measured across its jobs; stockroom lead", rem_of(len(d['t8']), len(d['t8']))),
        (f"Not corrected: an operation with no scan is costed at the routing standard and tagged estimated on the job. Coverage climbed from {pc(d['scan_first'])} in week {d['scan_week_first']} "
         f"to {pc(d['scan_last'])} in week {d['scan_week_last']} as the cell leads chased the missing scans daily.",
         "Routing operations the job reached against the scan records", f"0 of {d['t9_n']:,} (costed at standard, tagged)"),
    ]
    rem_hdr = ["", "Error", "Remediation", "Evidence", "Remediated (rows)"]
    rem_master_table = _widths(B.data_table(rem_hdr, [[numcell(i), e[0], *REM_M[i - 1]] for i, e in enumerate(MASTER, 1)], right=[]), W3)
    rem_txn_table = _widths(B.data_table(rem_hdr, [[numcell(i), e[0], *REM_T[i - len(MASTER) - 1]] for i, e in enumerate(TXN, len(MASTER) + 1)], right=[]), W3)
    did = f"""
{B.section("did", "Section 2", "Error Remediation")}
<p>Most of the errors in Section 1 were closed in full. The estimate now sits on every job, historic and new;
the rate pools, the program crosswalk and the measured standards are in place; and of the {d['err_records'] / 1e3:.0f}K clock
records that carried a labor error, {pc(d['pre_repaired'])} were repaired and {pc(d['pre_unrep'], 1)} flagged unrepairable. On every
monitored cell the machine's own hours now supersede the clock record, which settles {pc(d['pre_superseded'])} of the
{d['pre_records'] / 1e3:.0f}K records from before the labor codes whether or not they carried an error. Three exceptions are stated as such: the historic labor that could
not be repaired is flagged rather than guessed; {d['att_res']:,} outside-processing lines with a generic description
could not be tied to a job and stay in the general ledger; and the estimator disputed {d['std_kept'] + d['std_adj']} of the measured
standards and won {d['std_kept']} of them. Four errors were controlled at source rather than repaired in the
history (setup and run separation, the scrap reason code, the material price list and the missing scans), so
the records carry them but nothing new is added.</p>

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Master and Configuration-level Table Error Remediation</p>
{rem_master_table}

<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Transaction-level Table Error Remediation</p>
{rem_txn_table}

<p>Evidence came from the machine-monitoring feed, the quoting module, the purchase-order and vendor records,
the rate history, and the stakeholder who confirmed each correction: the controller on the outside-processing
attributions, the production manager on the attended ratios, the two CNC cell leads on the program crosswalk,
the estimator on every measured standard, the stockroom lead on the material corrections and the quality
manager on the scrap list.</p>
"""

    # ── results ──────────────────────────────────────────────────────────
    res_rows = [
        ["Jobs with an estimate attached by cost element", "The comparison that job costing exists for is possible", pc(r["estimate"][0]), pc(r["estimate"][1])],
        ["Job cost dollars measured rather than estimated", "Actuals rest on transactions, not on routing standards", "no job cost<br><em>module never configured</em>", pc(r["measured"][1])],
        ["CNC run hours sourced from machine monitoring", "The largest cost element no longer depends on clock-ins", pc(r["machine"][0]), pc(r["machine"][1])],
        ["Clocked hours within 10% of machine hours on monitored cells", "The labor record agrees with an independent measurement", pc(r["clocked"][0]), pc(r["clocked"][1])],
        ["Secondary-operation hours captured by scan", "Coverage where the machine can't measure", pc(r["scan"][0]), pc(r["scan"][1])],
        ["Labor records with setup, run, rework and indirect separated", "Small-lot economics and rework cost are visible", pc(r["codes"][0]), pc(r["codes"][1])],
        ["Outside processing tied to a job", "Vendor cost lands on the job that incurred it", pc(r["osp"][0]), pc(r["osp"][1])],
        ["Repeat parts with routing standards measured from machine data", "Estimates rest on current cycle times", pc(r["standards"][0]), pc(r["standards"][1])],
        ["Repeat parts below target priced against current cost", "Standing prices reflect today's material and rates", pc(r["priced"][0]), pc(r["priced"][1])],
        ["Work centers costed at their own rate", "Manual and 5-axis jobs are no longer averaged together", "0 of 38", "38 of 38"],
        ["Scrap events with a job and a reason", "Scrap cost reaches the job and the cause is known", pc(r["scrap"][0]), pc(r["scrap"][1])],
        ["Historic labor records with an error repaired or explicitly flagged", "The three-year history can be used with its limits stated", pc(r["history"][0]), f"{pc(r['history'][1])}<br><em>{pc(d['pre_repaired'])} repaired, {pc(d['pre_unrep'], 1)} flagged</em>"],
    ]
    res_table = _widths(B.data_table(["Measure", "Why it matters", "Before", "After"], res_rows, right=[2, 3]), [36, 36, 14, 14])
    results = f"""
{B.section("results", "Section 3", "Results")}
<p>Job cost can now be relied on for the decisions in the margin diagnostic: every job carries its estimate
by element, {pc(r['measured'][1])} of the cost on jobs completed under the new process is measured from a
transaction, and the remainder is tagged on the job rather than silently filled in. Before is the twelve
months before the engagement ({d['n_before']:,} jobs, the records as the ERP held them); after is the
{d['n_after']:,} jobs released once every configuration change was live and completed by week 12.</p>
{res_table}
<p><em>Rows that stay short of 100% are left that way. The measured-cost, machine-hours and scan rows depend on
the traveler-scanning rollout at the secondary operations, which reached {pc(d['scan_last'])} of operations in
week {d['scan_week_last']} and is expected to plateau near ninety percent; the operations still unscanned are costed at
the routing standard and tagged. The clocked-hours row is measured on the job-cells where both a clock record
and machine hours exist. Repeat parts with measured standards will rise with each quarterly refresh; the
{pc(1 - r['priced'][1])} of parts below target not yet decided are on the queue for the monthly review.</em></p>
"""

    # ── process changes ──────────────────────────────────────────────────
    CONFIG = [
        ("Estimate carries to the job on conversion", "Converting a quote copies its estimate by element (material, setup, run by work center, outside processing) onto the job, and a job cannot be released without one.", "Closes #1."),
        ("Job number required on outside-processing purchase orders", "A PO line on the outside-processing account cannot be saved without a job number; the line and its receipt land on that job.", "Closes #6."),
        ("Work-center rate pools", "Each work center carries its own labor rate, burden rate and attended ratio; estimates and actuals cost at the cell's rate.", "Closes #3. Addresses #4: current cost is right by cell."),
        ("Terminals at the cells", "The two door terminals are retired; each cell has its own, so the operator clocks on where the work is.", "Addresses #9, #12 and #13: a record is opened at the machine, not at the door."),
        ("One open operation per employee", "Opening a second operation closes the first; a record cannot cover two machines.", "Closes #12."),
        ("Auto-close at shift end with review flag", "Any record still open at shift end closes at the shift boundary and is flagged for the cell lead's review the next morning.", "Closes #9."),
        ("Setup, run, rework and indirect codes", "The terminal asks for the code; setup and run post separately, rework posts under its own code, indirect posts with no job.", "Closes #10, #13 and #14."),
        ("Scrap reason required", "A scrap or rework event cannot be saved without a job, an operation and a reason code from the list.", "Closes #15 for recorded events; addresses the unrecorded ones by making the entry a thirty-second job at the cell."),
        ("Monitoring feed posts machine hours to jobs", "The machine-monitoring feed carries the job the operator opened at the cell, so setup, cycle, alarm and in-operation idle post to the job automatically.", "Closes #2 at source and #7: the standard is measured from the feed, and the program name no longer matters. Addresses #9 and #12: the machine's hours replace the clock record on every monitored cell."),
        ("Standard-cost fallback with estimated tag", "An operation with no scan, record or machine hours by the time the next operation starts is costed at the routing standard and tagged estimated on the job.", "Addresses #17: a missing scan is visible on the job and on the coverage screen rather than silently absent."),
    ]
    config_table = _widths(B.data_table(["Change", "What it does", "Impact"], [list(c) for c in CONFIG], right=[]), [24, 46, 30])
    PROCESS = [
        ("Monthly repricing review", "The controller opens the repricing queue on the first Tuesday of the month; the parts below cost plus target are decided one by one, and a held part comes back the next month.", "Closes #4 and #8 going forward: a standing price can be no more than a month behind current cost.", "Controller, owner", "Monthly"),
        ("Quarterly routing standard refresh from machine data", "Setup and cycle times measured over the last three lots on every repeat part the machines ran; the estimator reviews each change.", "Closes #2 going forward.", "Estimator, production manager", "Quarterly"),
        ("Weekly coverage review by work center", "Measured share of cost and scan coverage by cell; a cell below 85% two weeks running is raised with the production manager.", "Addresses #17 and the estimated tag: coverage cannot drift unnoticed.", "Production manager", "Weekly"),
        ("Monthly estimate-accuracy review by element", "Actual over estimate by element on the month's closed jobs, by estimator, material and lot band; the estimating rules change where the ratio drifts.", "Addresses #2, #5 and the estimator bias the diagnostic found.", "Estimator, controller", "Monthly"),
        ("Quarterly rate pool refresh", "Pool rates recomputed from the rate history and the quarter's machine hours and headcount by cell.", "Keeps #3 closed.", "Controller", "Quarterly"),
        ("Scrap reason review", "The month's scrap and rework events by reason, cell and part family; the probable unrecorded scrap list is walked with the cell leads.", "Addresses #15 and #16.", "Quality manager", "Monthly"),
        ("Retirement of the estimator's spreadsheet into the quoting module", "Material prices, speeds and feeds, vendor prices and the measured standards live in the quoting module; the spreadsheet is retired once the last quote template is migrated.", "Closes #5 and the vendor-price gap; addresses #2.", "Estimator, ERP administrator", "Once, then continuous"),
        ("The monthly metrics on the dashboard with targets", "Gross margin by job type, estimate accuracy by element, jobs below target, cost coverage, scan coverage, repricing backlog, customer margin, outside-processing variance and scrap cost, each against a target.", "Addresses all seventeen: any error that returns shows up in a number someone owns.", "Controller; reviewed by the owner", "Monthly"),
    ]
    process_table = _widths(B.data_table(["Change", "What it does", "Impact", "Owner", "Cadence"], [list(p) for p in PROCESS], right=[]), [18, 34, 24, 13, 11])
    keep = f"""
{B.section("process", "Section 4", "Process Changes")}
<p>The remediation in Section 2 corrected the history and connected the records. The changes in this section
keep them connected, and fall into two categories.</p>
<p>The first is the ERP system settings and the monitoring feed. These were configured once, in weeks 4 to 6,
take effect for every user, and stop most of the errors at the point of entry. This category holds on its own.
The table lists each change, what it does and the errors it <em>closes</em> (the error can no longer occur) or
<em>addresses</em> (the error is caught or reduced, but not prevented).</p>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">Changes to ERP System Settings</p>
{config_table}
<p>The second category is process changes that need sustained ownership, which makes it the harder lift. The
shop has committed to the owners and cadences below, and keeping them is what protects the results in
Section 3.</p>
<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:34px;">Changes Requiring Ongoing Processes and Ownership</p>
{process_table}
<p><em>The datasets are generated; defect types and rates reflect patterns commonly seen in job-shop ERPs.</em></p>
"""
    appendix = build_appendix(d)
    return found + did + results + keep + appendix, toc


APPENDIX_TABLES = [
    ("Part master", "erp/part_master.csv", "One row per part number and revision: what it is made of, who buys it, the standing price and when it was set."),
    ("Routings", "erp/routings.csv", "One row per operation on a part's routing: the work center, the setup and run standards, the CNC program and when the standard was last touched."),
    ("Work centers", "erp/work_centers.csv", "One row per work center, with the monitoring flag and the machine the feed reports under."),
    ("Work center rates", "erp/work_center_rates.csv", "One row per work center and effective date: the labor and burden rates the ERP costs an hour at, and the attended ratio."),
    ("Own-product standards", "erp/own_product_standards.csv", "One row per own product: the standard cost, when it was set, and the list price built on it."),
    ("Customers", "erp/customers.csv", "One row per customer, with the change-order and expedite counts of the last twelve months."),
    ("Quotes", "erp/quotes.csv", "One row per quote line: the estimate by element, the quoted price, the status and the job it became."),
    ("Jobs", "erp/jobs.csv", "One row per job: the part, customer, quantity, dates and price, the estimate by element (blank before the configuration change) and the ERP's own actuals."),
    ("Labor transactions", "erp/labor_transactions.csv", "One row per clock record: job, operation, work center, employee, clock-on and clock-off, the labor code and the source (door or cell terminal, traveler scan, auto-close)."),
    ("Machine monitoring", "monitoring/machine_monitoring.csv", "One row per machine state interval from the monitoring feed: setup, in cycle, idle, alarm or offline, with the program, the cycle count and, once the feed was connected, the job."),
    ("Material transactions", "erp/material_transactions.csv", "One row per stock issue or return: job, material spec, quantity, unit cost, date and source (saw, stockroom, backflush)."),
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
<p>The tables the audit examined, as extracted on {pd.Timestamp(C.END_DATE):%B %d, %Y}: what a row is, every column,
and five rows drawn from across each file. Blanks are shown as blanks; they are part of what the audit found.</p>
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
    html = B.page("ERP System Data Quality Audit", "", toc, body)
    html = html.replace("</style></head>", ".section-title-block.sub .section-title{font-size:18px;font-weight:700;}"
                        ".data-table.appendix{font-size:11.5px;white-space:nowrap;margin:6px 0 4px;}"
                        ".data-table.appendix th{font-size:10.5px;padding:6px 8px;}.data-table.appendix td{padding:5px 8px;}</style></head>", 1)
    OUT.write_text(html, encoding="utf-8")
    print(f"Data quality audit written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
