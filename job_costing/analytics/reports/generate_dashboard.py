"""KPI dashboard -> docs/reports/dashboard.html

Current state, monthly with trailing twelve, in the layout of the scrap and OEE
dashboards: a KPI tile row with weekly, monthly and trailing-twelve comparisons
against the prior period, then the trend charts. Gross margin by job type,
estimate accuracy by element, the share of jobs below target, cost coverage
measured against estimated by work center, scan coverage at the secondary
operations, repeat parts below target by decision, customer margin
for the top fifteen, outside-processing variance, and scrap and rework cost by
part family. Everything reads from the dbt marts.

Run:  python -m analytics.reports.generate_dashboard
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.ticker as mticker

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brand as B  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MARTS = REPO / "analytics" / "data" / "marts"
RAW = REPO / "data_source" / "raw"
OUT = REPO / "docs" / "reports" / "dashboard.html"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

AS_OF = pd.Timestamp(C.END_DATE)
TM = C.TARGET_MARKUP / (1 + C.TARGET_MARKUP)
BAND = 0.02
GOOD, BAD, NEUTRAL = B.GREEN, B.ACCENT_RED, B.MED_GREY
CHART_FS = 13


def _pq(name):
    df = pd.read_parquet(MARTS / f"{name}.parquet")
    for c in df.columns:
        if df[c].dtype == object:
            first = df[c].dropna()
            if len(first) and hasattr(first.iloc[0], "year") and not isinstance(first.iloc[0], str):
                df[c] = pd.to_datetime(df[c])
    return df


# ── periods ─────────────────────────────────────────────────────────────────
# the dashboard reads on the last day of the window; a week is Monday to Sunday
CUR_WEEK_END = AS_OF - pd.Timedelta(days=(AS_OF.weekday() + 1) % 7)   # the last Sunday on or before as-of
CUR_WEEK_START = CUR_WEEK_END - pd.Timedelta(days=6)
PRI_WEEK_START, PRI_WEEK_END = CUR_WEEK_START - pd.Timedelta(days=7), CUR_WEEK_START - pd.Timedelta(days=1)
CUR_MONTH = AS_OF.to_period("M"); PRI_MONTH = CUR_MONTH - 1
TTM_START = (CUR_MONTH - 11).to_timestamp(); TTM_END = CUR_MONTH.to_timestamp(how="end")
TTMP_START = (CUR_MONTH - 23).to_timestamp(); TTMP_END = (CUR_MONTH - 12).to_timestamp(how="end")


def load():
    d = {}
    j = _pq("mart_margin_by_job")
    j["hours_ratio"] = j["act_labor_hours"] / (j["est_setup_hours"] + j["est_run_hours"]).replace(0, np.nan)
    j["done"] = j["completed_date"]
    # rework cost: rework hours at the job's own labor rate
    j["rework_cost"] = j["act_rework_hours"].fillna(0) * (j["act_labor"] / j["act_labor_hours"].replace(0, np.nan)).fillna(0)
    d["jobs"] = j
    d["scan"] = _pq("int_scan_coverage_weekly")
    d["cov"] = _pq("mart_coverage_weekly")
    d["queue"] = _pq("mart_repricing_queue")
    d["elements"] = _pq("fct_job_cost_elements")
    d["cust"] = _pq("mart_margin_by_customer")
    d["wcs"] = pd.read_csv(RAW / "erp" / "work_centers.csv")
    return d


def in_range(df, col, a, b):
    return df[(df[col] >= a) & (df[col] <= b)]


# ── KPI values on a set of completed jobs ───────────────────────────────────
def kpis(jobs):
    if len(jobs) == 0:
        return dict(revenue=0.0, margin=np.nan, below=np.nan, coverage=np.nan, accuracy=np.nan, jobs=0)
    rev = jobs["price"].sum()
    return dict(revenue=rev, margin=jobs["contribution"].sum() / rev, below=(jobs["margin_on_price"] < TM - BAND).mean(),
                coverage=(jobs["coverage"] * jobs["act_total_cost"]).sum() / jobs["act_total_cost"].sum(),
                accuracy=jobs["hours_ratio"].median(), jobs=len(jobs))


def scan_cov(scan, a, b):
    """Scan coverage over the engagement weeks whose start falls in [a, b]."""
    s = scan.copy()
    s["week_start"] = pd.Timestamp(C.ENGAGEMENT_START) + pd.to_timedelta((s["engagement_week"] - 1) * 7, unit="D")
    s = s[(s["week_start"] >= a) & (s["week_start"] <= b)]
    return s["operations_scanned"].sum() / s["operations_expected"].sum() if s["operations_expected"].sum() else np.nan


def fmt_pct(v, d=1):
    return "&ndash;" if pd.isna(v) else f"{v * 100:.{d}f}%"


def fmt_usd_k(v):
    return "&ndash;" if pd.isna(v) else (f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.0f}K")


def fmt_ratio(v):
    return "&ndash;" if pd.isna(v) else f"{v:.2f}"


def direction(cur, pri, lower_is_better, neutral=False, points=False):
    if neutral or pd.isna(cur) or pd.isna(pri) or pri == 0:
        return "", NEUTRAL, ""
    delta = cur - pri if points else (cur - pri) / abs(pri)
    if abs(delta) < 1e-9:
        return "", NEUTRAL, ""
    better = delta < 0 if lower_is_better else delta > 0
    arrow = "&#9650;" if delta > 0 else "&#9660;"
    color = GOOD if better else BAD
    return arrow, color, (f"{abs(delta) * 100:.1f} pts" if points else f"{abs(delta):.1%}")


def kpi_card(cur_val, pri_val, arrow, arrow_color, pct_str, bar_color):
    indicator = (f'<span style="font-size:18px;color:{arrow_color};font-weight:bold;margin-left:4px;">{arrow} {pct_str}</span>' if arrow else "")
    return f'''<div style="border:1px solid {B.LIGHT_GREY};border-radius:8px;padding:16px 8px 0 28px;background:white;flex:1;min-width:0;overflow:hidden;">
      <div style="display:flex;align-items:baseline;flex-wrap:wrap;margin-bottom:2px;">
        <span style="font-size:28px;font-weight:700;color:{B.DARK_GREY};line-height:1.1;">{cur_val}</span>{indicator}</div>
      <div style="font-size:18px;color:{B.TEXT};margin-bottom:12px;">Current</div>
      <div style="font-size:22px;font-weight:600;color:{B.MED_GREY};">{pri_val}</div>
      <div style="font-size:14px;color:{B.MED_GREY};margin-bottom:0;">Prior</div>
      <div style="height:8px;background:{bar_color};border-radius:0 0 8px 8px;margin-top:12px;margin-left:-28px;margin-right:-8px;"></div>
    </div>'''


def col_header(label):
    return f'<div style="flex:1;min-width:0;text-align:center;font-size:18px;font-weight:700;color:{B.DARK_GREY};padding-bottom:8px;">{label}</div>'


ROW_LABEL_W = "130px"


def kpi_row(label, left, right):
    return f'''
    <div style="display:flex;margin-bottom:10px;align-items:stretch;">
      <div style="width:{ROW_LABEL_W};flex-shrink:0;font-weight:700;color:{B.DARK_GREY};font-size:18px;display:flex;align-items:center;padding-right:8px;">{label}</div>
      <div style="display:flex;gap:4px;flex:1;padding-right:9px;">{"".join(left)}</div>
      <div style="display:flex;gap:4px;flex:1;padding-left:9px;">{"".join(right)}</div>
    </div>'''


def margin_cards(cur, pri):
    a, c, p = direction(cur["revenue"], pri["revenue"], False, neutral=True)
    a2, c2, p2 = direction(cur["margin"], pri["margin"], False, points=True)
    a3, c3, p3 = direction(cur["below"], pri["below"], True, points=True)
    return [kpi_card(fmt_usd_k(cur["revenue"]), fmt_usd_k(pri["revenue"]), a, NEUTRAL, p, NEUTRAL),
            kpi_card(fmt_pct(cur["margin"]), fmt_pct(pri["margin"]), a2, c2, p2, c2),
            kpi_card(fmt_pct(cur["below"], 0), fmt_pct(pri["below"], 0), a3, c3, p3, c3)]


def quality_cards(cur, pri, scan_c, scan_p):
    a, c, p = direction(cur["coverage"], pri["coverage"], False, points=True)
    acc_c, acc_p = abs(cur["accuracy"] - 1) if pd.notna(cur["accuracy"]) else np.nan, abs(pri["accuracy"] - 1) if pd.notna(pri["accuracy"]) else np.nan
    a2, c2, p2 = direction(acc_c, acc_p, True, points=True)
    a3, c3, p3 = direction(scan_c, scan_p, False, points=True)
    return [kpi_card(fmt_pct(cur["coverage"], 0), fmt_pct(pri["coverage"], 0), a, c, p, c),
            kpi_card(fmt_ratio(cur["accuracy"]), fmt_ratio(pri["accuracy"]), a2, c2, p2, c2),
            kpi_card(fmt_pct(scan_c, 0), fmt_pct(scan_p, 0), a3, c3, p3, c3)]


# ── charts ──────────────────────────────────────────────────────────────────
def style(ax):
    B.chart_style(ax)
    for item in ([ax.xaxis.label, ax.yaxis.label] + ax.get_xticklabels() + ax.get_yticklabels()):
        item.set_fontsize(CHART_FS)


def fig():
    import matplotlib.pyplot as plt
    return plt.subplots(figsize=(8.2, 4.2))


def month_labels(idx):
    return [pd.Timestamp(m).strftime("%b %y") for m in idx]


def chart_margin_by_type(j):
    m = j[(j["done"] >= TTM_START) & (j["done"] <= TTM_END)].copy(); m["month"] = m["done"].dt.to_period("M").dt.to_timestamp()
    f, ax = fig()
    for t, lab, col in [("repeat", "Repeat parts", B.DARK_BLUE), ("new", "New quoted work", B.LIGHT_BLUE), ("own_product", "Own products", B.MED_GREY)]:
        g = m[m["job_type"] == t].groupby("month").agg(c=("contribution", "sum"), r=("price", "sum")); g = g["c"] / g["r"]
        ax.plot(g.index, g.values, marker="o", linewidth=2, color=col, label=lab)
    ax.axhline(TM, color=B.DARK_GREY, linestyle="--", linewidth=1.3, label=f"Target {TM:.0%}")
    ax.set_ylim(-0.1, 0.45); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); ax.set_ylabel("Margin on price")
    ax.set_xticks(g.index); ax.set_xticklabels(month_labels(g.index), rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="lower left", ncol=2); style(ax)
    return B.b64(f)


def chart_below_target(j):
    m = j[(j["done"] >= TTM_START) & (j["done"] <= TTM_END)].copy(); m["month"] = m["done"].dt.to_period("M").dt.to_timestamp()
    g = m.groupby("month").apply(lambda x: pd.Series({"below": (x["margin_on_price"] < TM - BAND).mean(), "neg": (x["contribution"] < 0).mean()}), include_groups=False)
    f, ax = fig(); x = np.arange(len(g))
    ax.bar(x, g["below"], color=B.LIGHT_BLUE, width=0.62, label="Below target")
    ax.bar(x, g["neg"], color=B.ACCENT_RED, width=0.62, label="Negative contribution")
    for xi, v in zip(x, g["below"]):
        ax.text(xi, v + 0.005, f"{v:.0%}", ha="center", va="bottom", fontsize=CHART_FS - 2)
    avg = g["below"].mean(); ax.axhline(avg, color=B.DARK_GREY, linestyle="--", linewidth=1.3, label=f"TTM avg ({avg:.0%})")
    ax.set_xticks(x); ax.set_xticklabels(month_labels(g.index), rotation=45, ha="right"); ax.set_ylabel("Share of jobs")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); ax.set_ylim(0, 0.6)
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="upper right", ncol=3); style(ax)
    return B.b64(f)


def chart_accuracy(j):
    m = j[(j["done"] >= TTM_START) & (j["done"] <= TTM_END)].copy(); m["month"] = m["done"].dt.to_period("M").dt.to_timestamp()
    f, ax = fig()
    for col_a, col_e, lab, col in [("act_material", "est_material", "Material", B.MED_GREY), ("act_labor_hours", None, "Labor hours", B.DARK_BLUE), ("act_outside", "est_outside", "Outside processing", B.LIGHT_BLUE)]:
        r = m["hours_ratio"] if col_e is None else m[col_a] / m[col_e].replace(0, np.nan)
        r = r.where((r > 0) & (r < 5))
        g = r.groupby(m["month"]).agg(["median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75)]); g.columns = ["med", "q1", "q3"]
        ax.plot(g.index, g["med"], marker="o", linewidth=2, color=col, label=lab)
        if lab == "Labor hours":
            ax.fill_between(g.index, g["q1"], g["q3"], color=col, alpha=0.15, label="Labor hours, interquartile range")
    ax.axhline(1.0, color=B.DARK_GREY, linestyle="--", linewidth=1.3)
    ax.set_ylim(0.7, 1.5); ax.set_ylabel("Actual / estimate (median)")
    ax.set_xticks(g.index); ax.set_xticklabels(month_labels(g.index), rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="upper right", ncol=2); style(ax)
    return B.b64(f)


def chart_customers(cust):
    top = cust.sort_values("revenue", ascending=False).head(15)
    labels = [c if pd.notna(c) else "OWN" for c in top["customer_id"]]
    f, ax = fig(); x = np.arange(len(top))
    colors = [B.ACCENT_RED if v < 0.10 else B.AMBER if v < TM - BAND else B.DARK_BLUE for v in top["margin_on_price"]]
    ax.bar(x, top["margin_on_price"], color=colors, width=0.62)
    for xi, v in zip(x, top["margin_on_price"]):
        ax.text(xi, v + 0.005, f"{v:.0%}", ha="center", va="bottom", fontsize=CHART_FS - 3)
    ax.axhline(TM, color=B.DARK_GREY, linestyle="--", linewidth=1.3)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45, ha="right"); ax.set_ylabel("Margin on price")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); style(ax)
    return B.b64(f)


def chart_coverage_by_wc(elements, jobs, wcs):
    e = elements[(elements["version"] == "restructured") & (elements["element"] == "labor")].merge(jobs[["job_id", "status"]], on="job_id")
    e = e[e["status"] == "completed"].copy(); e["group"] = e["work_center_id"].str[:3]
    g = e.groupby("group").apply(lambda x: pd.Series({"measured": x.loc[x["measured"], "amount"].sum(), "estimated": x.loc[~x["measured"], "amount"].sum()}), include_groups=False)
    g["share"] = g["measured"] / (g["measured"] + g["estimated"]); g = g.sort_values("share")
    names = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horiz. mills", "VMC": "Vert. mills", "MTN": "Mill-turn", "FAX": "5-axis",
             "SAW": "Saw", "MDP": "Drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
    f, ax = fig(); x = np.arange(len(g))
    ax.bar(x, g["share"], color=B.DARK_BLUE, width=0.62, label="Measured")
    ax.bar(x, 1 - g["share"], bottom=g["share"], color=B.AMBER, width=0.62, label="Estimated")
    for xi, v in zip(x, g["share"]):
        ax.text(xi, v / 2, f"{v:.0%}", ha="center", va="center", fontsize=CHART_FS - 2, color="white", fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels([names.get(i, i) for i in g.index], rotation=45, ha="right"); ax.set_ylabel("Share of labor cost")
    ax.set_ylim(0, 1.12); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="upper center", ncol=2); style(ax)
    return B.b64(f)


def chart_scan(scan):
    s = scan.copy(); s["group"] = s["work_center_group"]
    g = s.groupby(["engagement_week", "group"]).agg(e=("operations_expected", "sum"), sc=("operations_scanned", "sum")).reset_index()
    g["cov"] = g["sc"] / g["e"]
    names = {"SAW": "Saw", "MDP": "Drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
    f, ax = fig()
    for grp, col in zip(["SAW", "MDP", "DBR", "INS", "ASM"], [B.DARK_BLUE, B.LIGHT_BLUE, B.MED_GREY, B.ACCENT_RED, B.AMBER]):
        gg = g[g["group"] == grp]
        ax.plot(gg["engagement_week"], gg["cov"], marker="o", linewidth=2, color=col, label=names[grp])
    ax.set_ylim(0.4, 1.0); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); ax.set_ylabel("Operations scanned")
    ax.set_xlabel("Engagement week"); ax.set_xticks(range(2, 13))
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="lower right", ncol=3); style(ax)
    return B.b64(f)


def chart_repricing(queue):
    q = queue
    below = q[q["below_target"]]
    dec = below["decision"].value_counts()
    order = ["reprice", "hold", "exit"]
    vals = [int(dec.get(o, 0)) for o in order]
    cols = [B.GREEN, B.AMBER, B.ACCENT_RED]
    f, ax = fig(); x = np.arange(len(order))
    ax.bar(x, vals, color=cols, width=0.62)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1, f"{v}", ha="center", va="bottom", fontsize=CHART_FS - 1)
    ax.set_xticks(x); ax.set_xticklabels([o.capitalize() for o in order]); ax.set_ylabel("Repeat parts below target")
    ax.set_ylim(0, max(vals) * 1.18); style(ax)
    return B.b64(f), int(below.shape[0])


def chart_osp_variance(j):
    m = j[(j["done"] >= TTM_START) & (j["done"] <= TTM_END) & (j["est_outside"] > 0)].copy(); m["month"] = m["done"].dt.to_period("M").dt.to_timestamp()
    g = m.groupby("month").agg(a=("act_outside", "sum"), e=("est_outside", "sum")); g["var"] = g["a"] / g["e"] - 1
    f, ax = fig(); x = np.arange(len(g))
    ax.bar(x, g["var"], color=[B.ACCENT_RED if v > 0.05 else B.DARK_BLUE for v in g["var"]], width=0.62)
    for xi, v in zip(x, g["var"]):
        ax.text(xi, v + (0.004 if v >= 0 else -0.02), f"{v:+.0%}", ha="center", va="bottom", fontsize=CHART_FS - 2)
    ax.axhline(0, color=B.DARK_GREY, linewidth=1)
    ax.set_xticks(x); ax.set_xticklabels(month_labels(g.index), rotation=45, ha="right"); ax.set_ylabel("Actual over estimate")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); style(ax)
    return B.b64(f)


def chart_scrap_rework(j):
    m = j[(j["done"] >= TTM_START) & (j["done"] <= TTM_END)]
    g = m.groupby("part_family").agg(scrap=("act_scrap", "sum"), rework=("rework_cost", "sum")); g["t"] = g["scrap"] + g["rework"]; g = g.sort_values("t", ascending=False)
    f, ax = fig(); x = np.arange(len(g))
    ax.bar(x, g["scrap"] / 1e3, color=B.DARK_BLUE, width=0.62, label="Scrap material")
    ax.bar(x, g["rework"] / 1e3, bottom=g["scrap"] / 1e3, color=B.LIGHT_BLUE, width=0.62, label="Rework labor")
    ax.set_xticks(x); ax.set_xticklabels(g.index, rotation=45, ha="right"); ax.set_ylabel("Cost, $K")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}K"))
    ax.legend(frameon=False, fontsize=CHART_FS - 1, loc="upper right"); style(ax)
    return B.b64(f)


def chart_card(png, title):
    return f'''<div style="background:white;border:1px solid {B.LIGHT_GREY};border-radius:8px;padding:20px;">
      <div style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-bottom:14px;">{title}</div>
      <img src="data:image/png;base64,{png}" style="width:100%;height:auto;display:block;"></div>'''


def trend_header(label):
    return f'''<div style="font-size:18px;font-weight:700;color:{B.DARK_GREY};border-bottom:2px solid {B.DARK_GREY};padding-bottom:8px;text-align:center;margin:24px 0 16px 0;">{label}</div>'''


def run():
    d = load(); j = d["jobs"]
    done = j[j["status"] == "completed"]
    cw, pw = in_range(done, "done", CUR_WEEK_START, CUR_WEEK_END), in_range(done, "done", PRI_WEEK_START, PRI_WEEK_END)
    cm, pm = done[done["done"].dt.to_period("M") == CUR_MONTH], done[done["done"].dt.to_period("M") == PRI_MONTH]
    ttm, ttmp = in_range(done, "done", TTM_START, TTM_END), in_range(done, "done", TTMP_START, TTMP_END)
    rows = []
    for label, cur, pri, (sa, sb), (pa, pb) in [
        ("Weekly", cw, pw, (CUR_WEEK_START, CUR_WEEK_END), (PRI_WEEK_START, PRI_WEEK_END)),
        ("Monthly", cm, pm, (CUR_MONTH.to_timestamp(), CUR_MONTH.to_timestamp(how="end")), (PRI_MONTH.to_timestamp(), PRI_MONTH.to_timestamp(how="end"))),
        ("Trailing 12M", ttm, ttmp, (TTM_START, TTM_END), (TTMP_START, TTMP_END)),
    ]:
        kc, kp = kpis(cur), kpis(pri)
        rows.append(kpi_row(label, margin_cards(kc, kp), quality_cards(kc, kp, scan_cov(d["scan"], sa, sb), scan_cov(d["scan"], pa, pb))))
    kpi_header = f'''<div style="background:{B.DARK_GREY};color:white;border-radius:8px;padding:12px 20px;font-size:20px;font-weight:700;margin-bottom:12px;text-align:center;">KPIs &middot; completed jobs, as of {AS_OF:%m/%d/%Y}</div>'''
    section_headers = f'''
<div style="display:flex;margin-bottom:4px;">
  <div style="width:{ROW_LABEL_W};flex-shrink:0;"></div>
  <div style="flex:1;padding-right:9px;"><div style="font-size:18px;font-weight:700;color:{B.DARK_GREY};border-bottom:2px solid {B.DARK_GREY};padding-bottom:8px;text-align:center;">Margin</div></div>
  <div style="flex:1;padding-left:9px;"><div style="font-size:18px;font-weight:700;color:{B.DARK_GREY};border-bottom:2px solid {B.DARK_GREY};padding-bottom:8px;text-align:center;">Job Cost Quality</div></div>
</div>'''
    col_headers = f'''
<div style="display:flex;margin-bottom:8px;margin-top:10px;">
  <div style="width:{ROW_LABEL_W};flex-shrink:0;"></div>
  <div style="display:flex;gap:4px;flex:1;padding-right:9px;">{col_header("Revenue Completed")}{col_header("Gross Margin on Price")}{col_header("Jobs Below Target")}</div>
  <div style="display:flex;gap:4px;flex:1;padding-left:9px;">{col_header("Cost Measured")}{col_header("Labor Hours / Estimate")}{col_header("Scan Coverage")}</div>
</div>'''
    kpi_section = kpi_header + section_headers + col_headers + "".join(rows)

    rp_png, n_below = chart_repricing(d["queue"])
    charts = {
        "type": chart_margin_by_type(j), "below": chart_below_target(j), "acc": chart_accuracy(j), "cust": chart_customers(d["cust"]),
        "wc": chart_coverage_by_wc(d["elements"], j, d["wcs"]), "scan": chart_scan(d["scan"]), "rp": rp_png,
        "osp": chart_osp_variance(j), "scrap": chart_scrap_rework(j),
    }
    chart_grid = f'''
<div style="margin-top:36px;">
  <div style="background:{B.DARK_GREY};color:white;border-radius:8px;padding:12px 20px;font-size:20px;font-weight:700;margin-bottom:16px;text-align:center;">Trend Charts (Trailing 12 Months)</div>
  {trend_header("Margin")}
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    {chart_card(charts["type"], "Gross Margin on Price by Job Type")}
    {chart_card(charts["below"], "Share of Jobs Below Target")}
    {chart_card(charts["cust"], "Customer Margin, Top 15 by Revenue (Trailing 36 Months)")}
    {chart_card(charts["acc"], "Estimate Accuracy by Cost Element")}
  </div>
  {trend_header("Job Cost Quality")}
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    {chart_card(charts["wc"], "Labor Cost Measured vs Estimated by Work Center (Engagement Period)")}
    {chart_card(charts["scan"], "Scan Coverage at Secondary Operations by Week")}
    {chart_card(charts["rp"], f"Repeat Parts Below Target by Decision ({n_below} Parts)")}
    {chart_card(charts["osp"], "Outside Processing: Actual over Estimate")}
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
    {chart_card(charts["scrap"], "Scrap and Rework Cost by Part Family")}
  </div>
  <div style="font-size:13px;color:{B.TEXT};margin-top:12px;font-style:italic;">Periods run by completion date: the week is Monday to Sunday ending {CUR_WEEK_END:%m/%d/%Y}; the month is {CUR_MONTH.strftime("%B %Y")}; trailing twelve months against the twelve before. Cost measured is the share of job cost resting on a transaction rather than a routing standard. Labor hours / estimate is the median across jobs (1.00 is exact). Scan coverage is the share of secondary operations with a traveler scan, from the week the rollout began.</div>
</div>'''
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Analytics Dashboard: Job Costing &amp; Margin</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: {B.BG_GREY}; margin: 0; padding: 0; color: {B.TEXT}; }}
    .page-header {{ background: {B.DARK_GREY}; color: white; padding: 20px 40px; }}
    .page-header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
    .container {{ max-width: 1600px; margin: 0 auto; padding: 28px 32px 64px 32px; }}
  </style>
</head>
<body>
  <div class="page-header"><h1>Analytics Dashboard: Job Costing &amp; Margin</h1></div>
  <div class="container">
    {kpi_section}
    {chart_grid}
  </div>
</body>
</html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    kt = kpis(ttm)
    print(f"Dashboard written to {OUT}: TTM margin {kt['margin']:.1%}, below target {kt['below']:.0%}, measured {kt['coverage']:.0%}, month {CUR_MONTH}")


if __name__ == "__main__":
    run()
