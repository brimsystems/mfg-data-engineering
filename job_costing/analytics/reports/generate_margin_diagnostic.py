"""Margin analytics diagnostic -> docs/reports/margin_diagnostic.html

About the business, not the data: where the shop's margin goes and why, from the
corrected job cost. Mirrors the analytics diagnostics in the OEE and scrap cases:
executive summary, the overall margin picture, the patterns found with a
subsection each and the annual dollars behind each one, customer and product
profitability, the repricing list, estimate accuracy, recommended actions and an
appendix. Every figure carries the measured-versus-estimated share of the cost
behind it.

Run:  python -m analytics.reports.generate_margin_diagnostic
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
OUT = REPO / "docs" / "reports" / "margin_diagnostic.html"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

YEAR = 2025
TARGET = C.TARGET_MARKUP
TM = TARGET / (1 + TARGET)                  # target margin on price
BAND = 0.02                                 # within two points of target counts as on target
HURDLE = 0.10                               # margin on price below which a customer does not cover the shop's cost of capital
COHORT_YEAR = 2022                          # the erosion cohort: repeat parts first quoted in this year or earlier


def _pq(name):
    df = pd.read_parquet(MARTS / f"{name}.parquet")
    for c in df.columns:
        if df[c].dtype == object:
            first = df[c].dropna()
            if len(first) and hasattr(first.iloc[0], "year") and not isinstance(first.iloc[0], str):
                df[c] = pd.to_datetime(df[c])
    return df


def money(x, d=0):
    if pd.isna(x):
        return "&ndash;"
    return f"&minus;${abs(x):,.{d}f}" if x < 0 else f"${x:,.{d}f}"


def k(x):
    """Compact money: $116K, $2.0M."""
    a = abs(x)
    s = f"${a/1e6:.1f}M" if a >= 1e6 else f"${a/1e3:.0f}K" if a >= 1e3 else f"${a:,.0f}"
    return ("&minus;" if x < 0 else "") + s


def pct(x, d=0):
    if pd.isna(x):
        return "&ndash;"
    return f"{round(x * 100, d) + 0.0:.{d}f}%"


def pts(x):
    v = round(x * 100) + 0.0
    return f"{v:+.0f} pts"


def measured_share(df):
    """The measured share of the cost behind a set of jobs."""
    c = df["act_total_cost"].sum()
    return float((df["coverage"] * df["act_total_cost"]).sum() / c) if c else np.nan


def ms(df):
    return f"({pct(measured_share(df))} of the cost measured)"


# ── data ────────────────────────────────────────────────────────────────────
def gather():
    d = {}
    j = _pq("mart_margin_by_job")
    j["hours_ratio"] = j["act_labor_hours"] / (j["est_setup_hours"] + j["est_run_hours"]).replace(0, np.nan)
    d["jobs"] = j
    d["j25"] = j[j["release_year"] == YEAR].copy()
    d["queue"] = _pq("mart_repricing_queue")
    cust = _pq("mart_margin_by_customer").sort_values("revenue", ascending=False)
    cust["customer_id"] = cust["customer_id"].fillna("OWN")          # the own-product line, sold to stock
    d["cust"] = cust
    d["fam"] = _pq("mart_margin_by_part_family")
    d["lot"] = _pq("mart_margin_by_lot_band")
    d["wc"] = _pq("mart_margin_by_work_center")
    d["est"] = _pq("mart_margin_by_estimator")
    d["own"] = _pq("mart_own_products")
    d["cvm"] = _pq("mart_clocked_vs_machine")
    d["month"] = _pq("mart_margin_by_month")
    d["osp"] = _pq("int_osp_by_job")
    d["estimate"] = _pq("int_estimate_by_job")
    d["quotes"] = pd.read_csv(RAW / "erp" / "quotes.csv", parse_dates=["quote_date"])
    d["parts"] = pd.read_csv(RAW / "erp" / "part_master.csv", parse_dates=["first_quote_date"])
    d["customers"] = pd.read_csv(RAW / "erp" / "customers.csv")
    d["coverage"] = _pq("mart_coverage_weekly")
    return d


# ── charts ──────────────────────────────────────────────────────────────────
def chart_histogram(j25):
    fig, ax = B.make_fig()
    m = j25["margin_on_price"].clip(-0.6, 0.8)
    bins = np.arange(-0.6, 0.81, 0.04)
    n, edges, patches = ax.hist(m, bins=bins, color=B.LIGHT_BLUE, edgecolor="white", linewidth=0.6)
    for p, left in zip(patches, edges[:-1]):
        if left + 0.04 <= 0:
            p.set_facecolor(B.ACCENT_RED)
        elif left >= TM - BAND and left + 0.04 <= TM + BAND + 1e-9:
            p.set_facecolor(B.DARK_BLUE)
    ax.axvline(TM, color=B.DARK_GREY, linewidth=1.4, linestyle="--")
    ax.text(TM + 0.01, ax.get_ylim()[1] * 0.95, f"target {TM:.0%}", color=B.DARK_GREY, fontsize=9.5, va="top")
    ax.set_xlabel("Margin on price"); ax.set_ylabel("Jobs")
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    B.chart_style(ax)
    return B.b64(fig)


def chart_month(month):
    m = month[month["version"] != "raw"].sort_values("release_month")
    fig, ax = B.make_fig()
    ax.plot(m["release_month"], m["margin_on_price"], color=B.DARK_BLUE, linewidth=2, label="Margin on price, corrected cost")
    ax.plot(m["release_month"], m["estimated_margin_on_price"], color=B.MED_GREY, linewidth=1.4, linestyle="--", label="Margin at estimate")
    ax.axhline(TM, color=B.DARK_GREY, linewidth=1, linestyle=":", label=f"Target {TM:.0%}")
    ax.axvline(pd.Timestamp(C.CONFIG_DATES["estimate_to_job"]), color=B.LIGHT_BLUE, linewidth=1.2)
    ax.text(pd.Timestamp(C.CONFIG_DATES["estimate_to_job"]) + pd.Timedelta(days=4), 0.02, "restructured", color=B.LIGHT_BLUE, fontsize=9)
    ax.set_ylim(0, 0.45); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, loc="upper left", ncol=3, fontsize=9)
    B.chart_style(ax)
    return B.b64(fig)


def chart_bars(labels, values, color=B.DARK_BLUE, fmt=lambda v: f"{v:.0%}", ylabel="", target=None, h=None, colors=None, rotate=0):
    fig, ax = B.make_fig(h)
    x = np.arange(len(labels))
    ax.bar(x, values, color=colors or color, width=0.62)
    for xi, v in zip(x, values):
        ax.text(xi, v + (0.006 if v >= 0 else -0.02), fmt(v), ha="center", va="bottom", fontsize=9)
    if target is not None:
        ax.axhline(target, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=rotate, ha="right" if rotate else "center")
    ax.set_ylabel(ylabel)
    if fmt(0.5).endswith("%"):
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    B.chart_style(ax)
    return B.b64(fig)


def chart_paired(labels, a, b, la, lb, target=None, ylabel="Margin on price", h=None):
    fig, ax = B.make_fig(h)
    x = np.arange(len(labels)); w = 0.38
    ax.bar(x - w / 2, a, w, color=B.MED_GREY, label=la)
    ax.bar(x + w / 2, b, w, color=B.DARK_BLUE, label=lb)
    if target is not None:
        ax.axhline(target, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel(ylabel); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, fontsize=9)
    B.chart_style(ax)
    return B.b64(fig)


def chart_lot(lot, j25):
    order = ["1-9", "10-24", "25-49", "50-99", "100-249", "250+"]
    lot = lot.set_index("lot_band").reindex(order)
    # setup hours against the standard, on the mill-turn and 5-axis cells where the standard assumes a repeat setup
    sub = j25[j25["primary_work_center_group"].isin(C.SMALL_LOT_GROUPS) & (j25["act_setup_hours"] > 0)]
    ratio = sub.groupby("lot_band")["setup_hours_ratio"].median().reindex(order)
    fig, ax = B.make_fig()
    x = np.arange(len(order))
    ax.bar(x, lot["margin_on_price"], color=[B.ACCENT_RED if v < TM - BAND else B.DARK_BLUE for v in lot["margin_on_price"]], width=0.6)
    for xi, v in zip(x, lot["margin_on_price"]):
        ax.text(xi, v + 0.006, f"{v:.0%}", ha="center", va="bottom", fontsize=9)
    ax.axhline(TM, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_xticks(x); ax.set_xticklabels([f"{o} pieces" for o in order]); ax.set_ylabel("Margin on price")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax2 = ax.twinx()
    ax2.plot(x, ratio, color=B.ACCENT_RED, marker="o", linewidth=2, label="Setup hours vs standard, mill-turn and 5-axis")
    ax2.set_ylabel("Setup hours / standard"); ax2.set_ylim(0.6, 1.5)
    for sp in ("top",):
        ax2.spines[sp].set_visible(False)
    ax2.legend(frameon=False, loc="upper right", fontsize=9)
    B.chart_style(ax)
    return B.b64(fig)


def chart_customers(cust):
    top = cust.head(15)
    labels = [f"{r.customer_id}" for r in top.itertuples()]
    colors = [B.ACCENT_RED if v < HURDLE else B.AMBER if v < TM - BAND else B.DARK_BLUE for v in top["margin_on_price"]]
    return chart_bars(labels, top["margin_on_price"].tolist(), colors=colors, target=TM, ylabel="Margin on price", rotate=45)


def chart_material(j25):
    sub = j25[(j25["est_run_hours"] > 0) & (j25["run_hours_ratio"].notna())]
    g = sub.groupby("material_spec").agg(n=("job_id", "size"), r=("run_hours_ratio", "median")).sort_values("r", ascending=False)
    g = g[g["n"] >= 100]
    colors = [B.ACCENT_RED if m in C.ESTIMATOR_BIAS_MATERIALS else B.LIGHT_BLUE for m in g.index]
    return chart_bars(g.index.tolist(), g["r"].tolist(), colors=colors, fmt=lambda v: f"{v:.2f}", ylabel="Run hours / estimate (median)", target=1.0, rotate=45, h=4.2)


def chart_plating(osp, jobs):
    """The plating vendor's price against what the estimator carried, per piece, by quarter."""
    v = osp[(osp["vendor_id"] == "VEND-009") & osp["job_id"].notna()].merge(jobs[["job_id", "est_outside", "part_number"]], on="job_id")
    v["q"] = v["order_date"].dt.to_period("Q").dt.to_timestamp()
    # index each part's price to its first order so the mix does not move the line
    base = v.sort_values("order_date").groupby("part_number")["unit_price"].first().rename("base")
    v = v.merge(base, on="part_number"); v["idx"] = v["unit_price"] / v["base"]
    v["est_idx"] = (v["est_outside"] / v["quantity"]) / v["base"]
    g = v.groupby("q").agg(paid=("idx", "median"), est=("est_idx", "median"), n=("job_id", "size"))
    fig, ax = B.make_fig()
    ax.plot(g.index, g["paid"], color=B.DARK_BLUE, marker="o", linewidth=2, label="Price paid on the PO, indexed")
    ax.plot(g.index, g["est"], color=B.MED_GREY, marker="s", linewidth=1.6, linestyle="--", label="Price in the estimate, indexed")
    ax.set_ylabel("Index, first order = 1.00"); ax.legend(frameon=False, fontsize=9, loc="upper left")
    B.chart_style(ax)
    return B.b64(fig), g


def chart_clocked(cvm):
    g = cvm[(cvm["month"] >= f"{YEAR}-01-01") & (cvm["month"] < f"{YEAR + 1}-01-01")].groupby("work_center_group").agg(c=("clocked_hours", "sum"), m=("machine_active_hours", "sum"))
    g["over"] = g["c"] / g["m"] - 1
    g = g.sort_values("over", ascending=False)
    names = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horizontal mills", "VMC": "Vertical mills", "MTN": "Mill-turn", "FAX": "5-axis"}
    colors = [B.ACCENT_RED if v > 0.5 else B.DARK_BLUE for v in g["over"]]
    return chart_bars([f"{names.get(i, i)}" for i in g.index], g["over"].tolist(), colors=colors, fmt=lambda v: f"+{v:.0%}", ylabel="Clocked hours over machine hours", rotate=30), g


def chart_accuracy(jobs):
    """Actual over estimate by element: 2025 history against the engagement period, as distributions."""
    hist = jobs[(jobs["release_year"] == YEAR)]
    eng = jobs[(jobs["version"] == "restructured") & (jobs["status"] == "completed")]
    elements = [("Material", "act_material", "est_material"), ("Setup hours", "act_setup_hours", "est_setup_hours"),
                ("Run hours", "act_run_hours", "est_run_hours"), ("Labor and burden", "act_labor", "est_labor"),
                ("Outside processing", "act_outside", "est_outside")]
    fig, ax = B.make_fig(4.4)
    pos, data, cols, ticks = [], [], [], []
    for i, (lab, a, e) in enumerate(elements):
        for kx, (df, col) in enumerate([(hist, B.MED_GREY), (eng, B.DARK_BLUE)]):
            r = (df[a] / df[e].replace(0, np.nan)).dropna()
            r = r[(r > 0) & (r < 5)]
            if a == "act_setup_hours":
                r = r[df.loc[r.index, "est_setup_hours"] > 0]
            data.append(r.clip(0.2, 2.5).values); pos.append(i * 3 + kx); cols.append(col)
        ticks.append(i * 3 + 0.5)
    bp = ax.boxplot(data, positions=pos, widths=0.8, showfliers=False, patch_artist=True, medianprops={"color": "white", "linewidth": 1.5})
    for patch, col in zip(bp["boxes"], cols):
        patch.set_facecolor(col); patch.set_edgecolor(col)
    ax.axhline(1.0, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_xticks(ticks); ax.set_xticklabels([e[0] for e in elements])
    ax.set_ylabel("Actual / estimate"); ax.set_ylim(0.3, 2.3)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=B.MED_GREY, label=f"{YEAR} history, estimates backfilled"), Patch(color=B.DARK_BLUE, label="Engagement period, estimate on the job")], frameon=False, fontsize=9, loc="upper left")
    B.chart_style(ax)
    stats = {}
    for lab, a, e in elements:
        for name, df in [("hist", hist), ("eng", eng)]:
            r = (df[a] / df[e].replace(0, np.nan)).dropna(); r = r[(r > 0) & (r < 5)]
            stats[(lab, name)] = (r.quantile(0.25), r.median(), r.quantile(0.75), len(r))
    return B.b64(fig), stats


def chart_opportunity(items):
    labels = [i[0] for i in items]; vals = [i[2] for i in items]
    fig, ax = B.make_fig(4.2)
    y = np.arange(len(labels))[::-1]
    ax.barh(y, vals, color=B.DARK_BLUE, height=0.6)
    for yi, v in zip(y, vals):
        ax.text(v + max(vals) * 0.01, yi, k(v).replace("&minus;", "-"), va="center", fontsize=9.5)
    ax.set_yticks(y); ax.set_yticklabels(labels); ax.set_xlabel("Annual margin, on the year's activity")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v/1e3:.0f}K" if v < 1e6 else f"${v/1e6:.1f}M"))
    ax.set_xlim(0, max(vals) * 1.18)
    B.chart_style(ax); ax.xaxis.grid(True, color=B.LIGHT_GREY); ax.yaxis.grid(False)
    return B.b64(fig)


# ── the report ──────────────────────────────────────────────────────────────
def build(d):
    j, j25, q = d["jobs"], d["j25"], d["queue"]
    rev25 = j25["price"].sum(); margin25 = j25["contribution"].sum() / rev25
    above = (j25["margin_on_price"] > TM + BAND).mean(); below = (j25["margin_on_price"] < TM - BAND).mean()
    on = 1 - above - below; neg = (j25["contribution"] < 0).mean()
    below_rev = j25.loc[j25["margin_on_price"] < TM - BAND, "price"].sum() / rev25
    neg_rev = j25.loc[j25["contribution"] < 0, "price"].sum() / rev25
    neg_loss = j25.loc[j25["contribution"] < 0, "contribution"].sum()
    q1, q3 = j25["margin_on_price"].quantile([0.25, 0.75])
    est_margin25 = (rev25 - j25["est_total_cost"].sum()) / rev25
    cov25 = measured_share(j25)

    # ── patterns, each with its annual dollars ───────────────────────────
    # P1: repeat parts quoted two to four years ago
    q["first_quote_year"] = q["first_quote_date"].dt.year
    coh = q[q["first_quote_year"] <= COHORT_YEAR]; rest = q[q["first_quote_year"] > COHORT_YEAR]
    p1_gap = q.loc[q["below_target"], "gap_to_target_annual"].sum()
    p1_taken = ((q["new_price"] - q["standing_price"]) * q["annual_volume"])[q["decision"] == "reprice"].sum()
    is_bar = q["material_spec"].str.contains("AL 6061-T6 bar|AL 7075-T6 bar|SS 30[34] bar|SS 316 bar")
    p1_bar, p1_other = q[is_bar], q[~is_bar]
    # P2: small lots, on new quoted work (repeat parts are priced through the queue)
    new25 = j25[j25["job_type"] == "new"]
    small = new25[new25["small_lot"]]
    rate = (small["act_labor"] / small["act_labor_hours"].replace(0, np.nan))
    p2_dollars = float(((small["act_setup_hours"] - small["est_setup_hours"]).clip(lower=0) * rate).sum())
    lot = d["lot"].set_index("lot_band")
    mt = j25[j25["primary_work_center_group"].isin(C.SMALL_LOT_GROUPS) & (j25["act_setup_hours"] > 0)]
    setup_small = mt.loc[mt["small_lot"], "setup_hours_ratio"].median(); setup_large = mt.loc[~mt["small_lot"], "setup_hours_ratio"].median()
    # P3: the change-order customer
    cust = d["cust"]; top15 = cust.head(15); top15c = top15[top15["customer_id"] != "OWN"]
    co_id = C.CHANGE_ORDER_CUSTOMER_RANK and cust.iloc[C.CHANGE_ORDER_CUSTOMER_RANK - 1]["customer_id"]
    co = cust[cust["customer_id"] == co_id].iloc[0]
    co_jobs = j25[j25["customer_id"] == co_id]
    co_m = co_jobs["contribution"].sum() / co_jobs["price"].sum()
    p3_dollars = float((co_jobs["act_labor"] - co_jobs["est_labor"]).clip(lower=0).sum())
    co_hours_ratio = co_jobs["act_labor_hours"].sum() / (co_jobs["est_setup_hours"] + co_jobs["est_run_hours"]).sum()
    other_ratio = j25.loc[j25["customer_id"] != co_id, "act_labor_hours"].sum() / (j25.loc[j25["customer_id"] != co_id, "est_setup_hours"] + j25.loc[j25["customer_id"] != co_id, "est_run_hours"]).sum()
    co_rec = d["customers"].set_index("customer_id").loc[co_id]
    co_rank = int(np.where(cust["customer_id"].values == co_id)[0][0]) + 1
    # P4: the blended rate against the pools, by family
    fam = d["fam"].sort_values("margin_on_price")
    fam["rank_pool"] = fam["margin_on_price"].rank(); fam["rank_blended"] = fam["margin_on_price_blended"].rank()
    hidden = fam[fam["margin_on_price_blended"] >= fam["margin_on_price"] + 0.05]
    hidden_below = hidden[hidden["margin_on_price"] < TM - BAND]
    flattered = fam[(fam["margin_on_price"] >= fam["margin_on_price_blended"] + 0.05)]
    p4_dollars = float(((TM - hidden_below["margin_on_price"]) * hidden_below["revenue"]).sum()) / 3   # three years of revenue in the mart
    # P5: titanium and Inconel, on new quoted work
    bias = new25[new25["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]
    rate5 = bias["act_labor"] / bias["act_labor_hours"].replace(0, np.nan)
    p5_dollars = float(((bias["act_run_hours"] - bias["est_run_hours"]).clip(lower=0) * rate5).sum())
    run_bias = j25[j25["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]["run_hours_ratio"].median()
    run_rest = j25[~j25["material_spec"].isin(C.ESTIMATOR_BIAS_MATERIALS)]["run_hours_ratio"].median()
    # P6: the plating vendor
    # jobs whose only outside process is the plating vendor's, so the estimate's outside element is the plating estimate
    by_job = d["osp"][d["osp"]["job_id"].notna()].groupby("job_id")["vendor_id"].agg(lambda s: (s == "VEND-009").all() and len(s) == 1)
    plating_jobs = set(by_job[by_job].index)
    pl = j25[j25["job_id"].isin(plating_jobs)]
    p6_dollars = float((pl["act_outside"] - pl["est_outside"]).clip(lower=0).sum())
    plating_png, plating_idx = chart_plating(d["osp"], j[j["job_id"].isin(plating_jobs)])
    # P7: own products
    own = d["own"]
    p7_dollars = float(((own["current_unit_cost"] * (1 + TARGET) - own["list_price"]).clip(lower=0) * own["annual_volume"]).sum())
    own_below = own[own["below_cost_at_list"]]
    own_jobs = j25[j25["job_type"] == "own_product"]; own_m = own_jobs["contribution"].sum() / own_jobs["price"].sum()
    # P8: clocked against machine hours
    clocked_png, cvm = chart_clocked(d["cvm"])
    p8_over = cvm["c"].sum() / cvm["m"].sum() - 1
    p8_hours = cvm["c"].sum() - cvm["m"].sum()
    blended25 = float(pd.read_csv(RAW / "erp" / "work_center_rates.csv").query("effective_date == '2025-01-01'").eval("labor_rate + burden_rate").iloc[0])
    p8_dollars = p8_hours * blended25

    items = [
        ("Reprice repeat parts to current cost plus target (P1)", "P1", p1_gap, f"{money(p1_taken)} taken by the week 7 to 9 decisions", ms(j25[j25["job_type"] == "repeat"])),
        ("Quote small lots at the measured first-article setup (P2)", "P2", p2_dollars, f"new quoted work under {C.SMALL_LOT_THRESHOLD} pieces", ms(small)),
        (f"Bill revision work at {co_rec['name']} (P3)", "P3", p3_dollars, "labor over estimate on the customer's jobs", ms(co_jobs)),
        ("Validate titanium and Inconel speeds and feeds (P5)", "P5", p5_dollars, "run hours over estimate on new quoted work", ms(bias)),
        ("Carry the plating vendor's current price (P6)", "P6", p6_dollars, "outside processing over estimate on the vendor's jobs", ms(pl)),
        ("Reprice the own-product line to current cost (P7)", "P7", p7_dollars, "gap to target on the fourteen products", ms(own_jobs)),
    ]
    total = sum(i[2] for i in items)
    items_sorted = sorted(items, key=lambda i: i[2], reverse=True)

    # customer concentration
    total_rev = cust["revenue"].sum(); total_c = cust["contribution"].sum()
    conc = {n: (cust.head(n)["revenue"].sum() / total_rev, cust.head(n)["contribution"].sum() / total_c) for n in (1, 5, 10)}
    top1 = cust.iloc[0]
    below_hurdle = cust[(cust["margin_on_price"] < HURDLE) & (cust["customer_id"] != "OWN")]
    est = d["est"].sort_values("jobs", ascending=False)
    # by quote year
    qy = j.merge(d["estimate"][["job_id", "quote_id"]].rename(columns={"quote_id": "qid"}), on="job_id", how="left")
    qd = d["quotes"].groupby("quote_id")["quote_date"].min()
    qy["quote_year"] = qy["qid"].map(qd).dt.year
    qy = qy[qy["job_type"] == "new"].groupby("quote_year").agg(jobs=("job_id", "size"), rev=("price", "sum"), c=("contribution", "sum"), hr=("hours_ratio", "median"))
    qy["m"] = qy["c"] / qy["rev"]; qy = qy[qy["jobs"] >= 50]

    # figures the situation overview cites
    reg = _pq("mart_dq_error_summary").set_index("error_code")
    m1 = int(reg.loc["M1", "rows_affected"])
    bf = pd.read_csv(RAW / "remediation" / "estimate_backfill.csv"); bf_quote = int(bf["est_total_cost"].notna().sum())
    att = pd.read_csv(RAW / "remediation" / "po_attribution.csv"); att_ok = int((att["status"] == "attributed").sum())
    r_osp_before = 1 - int(reg.loc["M6", "rows_affected"]) / int(reg.loc["M6", "rows_in_scope"])
    # the records carrying a labor error, as the audit counts them: flagged by T1, T3, T4 or T5, or posted to the catch-all operation
    lc = _pq("int_labor_cleaned")
    err_ids = set()
    for name in ["dq_t1_open_clock_records", "dq_t3_wrong_job", "dq_t4_multi_machine_tending", "dq_t5_indirect_time_on_jobs"]:
        err_ids |= set(_pq(name)["txn_id"])
    err_ids |= set(lc.loc[lc["op_seq"] == 999, "txn_id"])
    err = lc[lc["txn_id"].isin(err_ids)]
    pc_unrep = pct((err["status"] == "unrepairable").mean(), 1)
    acc_png, acc = chart_accuracy(j)
    cov = d["coverage"].dropna(subset=["measured_cost_share"]).iloc[-1]
    eng = j[(j["version"] == "restructured") & (j["status"] == "completed")]
    eng_m = eng["contribution"].sum() / eng["price"].sum()

    # ── tables ───────────────────────────────────────────────────────────
    sub = lambda t: f'<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">{t}</p>'
    type_rows = []
    for t, lab in [("repeat", "Repeat parts on standing prices"), ("new", "New quoted work"), ("own_product", "Own products at list")]:
        s = j25[j25["job_type"] == t]
        type_rows.append([lab, f"{len(s):,}", k(s["price"].sum()), pct(s["price"].sum() / rev25), pct(s["contribution"].sum() / s["price"].sum()),
                          pct((s["price"].sum() - s["est_total_cost"].sum()) / s["price"].sum()), pct((s["margin_on_price"] < TM - BAND).mean()), pct(measured_share(s))])
    type_rows.append(["<strong>All jobs</strong>", f"<strong>{len(j25):,}</strong>", f"<strong>{k(rev25)}</strong>", "100%", f"<strong>{pct(margin25)}</strong>", pct(est_margin25), pct(below), pct(cov25)])
    type_table = B.data_table(["Job type", "Jobs", "Revenue", "Share", "Margin on price", "Margin at estimate", "Below target", "Cost measured"], type_rows, right=[1, 2, 3, 4, 5, 6, 7])

    cust_rows = [[r.customer_id, r.customer_name, r.industry, f"{r.jobs:,}", k(r.revenue), pct(r.revenue / total_rev), pct(r.margin_on_price),
                  pct(r.estimated_margin_on_price), pct(r.coverage)] for r in top15.itertuples()]
    cust_table = B.data_table(["", "Customer", "Industry", "Jobs", "Revenue", "Share", "Margin on price", "At estimate", "Cost measured"], cust_rows, right=[3, 4, 5, 6, 7, 8])

    fam_rows = [[r.part_family, f"{r.jobs:,}", k(r.revenue / 3), pct(r.margin_on_price_blended), pct(r.margin_on_price), pts(r.margin_on_price - r.margin_on_price_blended)]
                for r in fam.sort_values("margin_on_price").itertuples()]
    fam_table = B.data_table(["Part family", "Jobs", "Revenue a year", "Margin, blended rate", "Margin, rate pools", "Change"], fam_rows, right=[1, 2, 3, 4, 5])

    own_rows = [[r.part_number, r.description, money(r.standard_cost, 2), pd.Timestamp(r.standard_cost_date).strftime("%b %Y"), money(r.list_price, 2), money(r.current_unit_cost, 2),
                 pct(r.margin_on_list_price), f"{r.annual_volume:,.0f}", B.badge("below cost", B.ACCENT_RED) if r.below_cost_at_list else ""] for r in own.sort_values("margin_on_list_price").itertuples()]
    own_table = B.data_table(["Part", "Description", "Standard cost", "Set", "List price", "Current cost", "Margin at list", "Annual volume", ""], own_rows, right=[2, 4, 5, 6, 7])

    dec = q["decision"].value_counts()
    bottom = q[q["margin_quartile"] == 1]
    rp_rows = []
    for r in q[q["decision"].notna()].sort_values("gap_to_target_annual", ascending=False).head(12).itertuples():
        rp_rows.append([r.part_number, r.customer_name, r.part_family, money(r.standing_price, 2), money(r.current_unit_cost, 2), pct(r.implied_margin_on_price), money(r.target_price, 2),
                        money(r.gap_to_target_annual), f"{r.decision}" + (f" at {money(r.new_price, 2)}" if pd.notna(r.new_price) else ""), r.decided_by])
    rp_table = B.data_table(["Part", "Customer", "Family", "Standing price", "Current cost", "Implied margin", "Target price", "Gap, annual", "Decision", "By"], rp_rows, right=[3, 4, 5, 6, 7])

    acc_rows = []
    for lab in ["Material", "Setup hours", "Run hours", "Labor and burden", "Outside processing"]:
        h, e = acc[(lab, "hist")], acc[(lab, "eng")]
        acc_rows.append([lab, f"{h[1]:.2f}", f"{h[0]:.2f} to {h[2]:.2f}", f"{e[1]:.2f}", f"{e[0]:.2f} to {e[2]:.2f}"])
    acc_table = B.data_table(["Element", f"{YEAR} median", f"{YEAR} interquartile range", "Engagement median", "Engagement interquartile range"], acc_rows, right=[1, 2, 3, 4])

    est_rows = [[r.estimator_id, f"{r.jobs:,}", k(r.revenue), pct(r.estimated_margin_on_price), pct(r.margin_on_price), pts(r.margin_on_price - r.estimated_margin_on_price)] for r in est.itertuples() if pd.notna(r.estimator_id)]
    est_table = B.data_table(["Estimator", "Jobs", "Revenue", "Margin at estimate", "Margin realized", "Gap"], est_rows, right=[1, 2, 3, 4, 5])
    qy_rows = [[int(y), f"{int(r.jobs):,}", pct(r.m), f"{r.hr:.2f}"] for y, r in qy.iterrows()]
    qy_table = B.data_table(["Quote year", "Jobs", "Margin realized", "Labor hours vs estimate (median)"], qy_rows, right=[1, 2, 3])

    action_rows = "".join(f"<tr><td>{a}</td><td>{f}</td><td style='text-align:right;font-weight:700;'>{k(v)}</td><td>{m}</td></tr>" for a, _c, v, f, m in items_sorted)
    actions_table = f'<table class="data-table"><thead><tr><th>Action</th><th>Supporting finding</th><th style="text-align:right;">Annual margin</th><th>Cost measured</th></tr></thead><tbody>{action_rows}</tbody></table>'

    wc = d["wc"].groupby("work_center_group").agg(hours=("hours", "sum"), c=("contribution_allocated", "sum"), r=("revenue_allocated", "sum"), cb=("cost_blended", "sum"), cp=("cost_pool", "sum"))
    wc["m"] = wc["c"] / wc["r"]; wc["rate_shift"] = wc["cp"] / wc["cb"] - 1
    names = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horizontal mills", "VMC": "Vertical mills", "MTN": "Mill-turn", "FAX": "5-axis",
             "SAW": "Saw", "MDP": "Manual drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
    wc = wc.sort_values("rate_shift")
    wc_png = chart_bars([names.get(i, i) for i in wc.index], wc["rate_shift"].tolist(), colors=[B.ACCENT_RED if v > 0 else B.DARK_BLUE for v in wc["rate_shift"]],
                        fmt=lambda v: f"{v:+.0%}", ylabel="Pool rate against the blended rate", rotate=30)

    toc = "".join([
        '<a href="#summary">1 &middot; Executive Summary</a>',
        '<a href="#situation">2 &middot; Situation Overview</a>',
        '<a href="#overall">3 &middot; The Margin Picture</a>',
        '<a href="#findings">4 &middot; Findings</a>',
        '<a class="sub" href="#p1">4.1 Repeat-part erosion</a>', '<a class="sub" href="#p2">4.2 Small-lot setups</a>',
        '<a class="sub" href="#p3">4.3 One customer\'s change orders</a>', '<a class="sub" href="#p4">4.4 The blended rate</a>',
        '<a class="sub" href="#p5">4.5 Titanium and Inconel</a>', '<a class="sub" href="#p6">4.6 Outside processing creep</a>',
        '<a class="sub" href="#p7">4.7 Own products</a>', '<a class="sub" href="#p8">4.8 Clocked hours vs machine hours</a>',
        '<a href="#customers">5 &middot; Customer Profitability</a>',
        '<a href="#repricing">6 &middot; The Repricing List</a>',
        '<a href="#accuracy">7 &middot; Estimate Accuracy</a>',
        '<a href="#actions">8 &middot; Recommended Actions</a>',
        '<a href="#appendix">Appendix &middot; Method</a>',
    ])

    body = f"""
{B.section("summary", "Section 1", "Executive Summary")}
<p>Across the {len(j25):,} jobs released in {YEAR}, the shop earned a contribution margin of
<strong>{pct(margin25, 1)}</strong> on {k(rev25)} of revenue, against the {pct(TM)} it quotes to
(a {pct(TARGET)} markup on cost). The average hides the shape of the problem. <strong>{pct(above)}</strong>
of jobs came in above target, <strong>{pct(below)}</strong> came in below it, and <strong>{pct(neg)}</strong>
lost money outright: those {int(neg * len(j25)):,} negative jobs carried {pct(neg_rev)} of the year's revenue and
cost the shop {money(-neg_loss)} in contribution. The jobs below target carried {pct(below_rev)} of revenue.
These figures rest on the corrected job cost, {pct(cov25)} of which is measured from transactions and the
rest carried at the routing standard; every figure in this report states that share.</p>
{B.chart(f"Margin on Price by Job, {YEAR}", chart_histogram(j25))}
<p>Six patterns explain most of the spread, and each one is worth a stated amount of margin a year.
The largest is the older half of the repeat book, parts first quoted in {COHORT_YEAR} or earlier, whose material
and rates have moved while their prices moved only by the annual letter: {money(p1_gap)} a year separates the standing
prices below target from current cost plus target, of which the week 7 to 9 repricing review has
already taken {money(p1_taken)}. Small lots are quoted at a repeat setup and run at a first-article
setup, one customer's revision changes are worked and never billed, the estimator's speeds and feeds
for titanium and Inconel were never validated, one plating vendor's prices rose {pct(C.OSP_PLATING_VENDOR_RISE_2Y)} while the
estimate stayed put, and the own-product line sells at a list price built on standard costs set at
launch.</p>
{B.chart("Annual Margin by Pattern", chart_opportunity(items_sorted))}
<p>Together the six are worth <strong>{k(total)} a year</strong> on {YEAR}'s activity, about
{pct(total / rev25, 1)} of revenue. Two further findings change the picture without adding to that figure: costing
every work center at its own rate rather than one blended shop rate reverses the ranking of the part
families, so the families the shop believed were its most profitable are not, and the clocked hours the
old records carried on the monitored cells overstate machine time by {pct(p8_over)}, which is why the
history had to be rebuilt from the machines before any of this could be measured. The actions in
Section 8 follow directly: reprice through the queue, quote setups and difficult materials at their
measured cost, bill revision work, and carry vendor prices forward.</p>


{B.section("situation", "Section 2", "Situation Overview")}
<p><strong>How job costing was done.</strong> It was not. The ERP's job costing module was installed at go-live and never
configured, and nobody had run its job cost report. What the shop had instead was an estimate and a set of
disconnected actuals. The estimate lived in the estimator's spreadsheet and was keyed into the quoting module
line by line: material from the spreadsheet's price list, setup and run hours from the routing standards set at
first quote, both hours costed at the one blended shop rate on the work-center rate table, and outside processing
at the vendor rate the spreadsheet carried. When a quote was won the job was created without it. A repeat part
never went back through quoting at all: it released against the standing price on the part master, moved once a
year by the across-the-board letter. On the actual side the ERP recorded what its transactions gave it. Operators
clocked on and off at two terminals by the shop door, with one code (run), and the labor transactions carried
those hours at the blended rate. Stock issues posted material at the price of the day. Outside-processing
purchase orders were coded to a general-ledger account, and only the lines where the buyer happened to type a job
number reached a job. Scrap was written down when someone got to it. The machine-monitoring system logged every
machine's state around the clock into the vendor's portal, where the production manager watched utilization; it
was never joined to a job.</p>
<p><strong>The tables it relied on.</strong> The estimate side used the quotes, the routings, the part master's standing
prices and the single rate on the work-center rate table. The actual side used the jobs, the labor transactions
and the material transactions. The outside-processing lines and the scrap events existed but mostly did not
carry a job number, and the machine-monitoring intervals were outside the ERP altogether.</p>
<p><strong>What that could not do.</strong> No job could be compared with its estimate, so the estimator had never seen
whether a quote was right, and margin was known only at the level of the monthly P&amp;L. The labor hours were
right in total and wrong by job: a record left open overnight, one operator's record covering three machines and
indirect time posted on whatever job was open all landed as production hours on some job, and the shop's own
records said the monitored cells had been clocked {pct(p8_over)} more than the machines ran. One rate for every work center
made a manual deburr hour cost the same as a five-axis hour, which flattered the families that use the expensive
cells. Outside processing, {pct(1 - r_osp_before)} of it, never reached the job that incurred it. Standards and material
prices set at first quote aged in place, and standing prices aged with them. Nothing measured how much of any
job's cost rested on a real transaction, because nothing assembled a job's cost at all.</p>
<p><strong>What changed in the existing tables.</strong> Every table on the estimate and actual sides now carries what
job cost needs, through configuration rather than new tables. The jobs table carries the estimate by element,
copied from the quote on conversion, and a job cannot be released without one. The labor transactions come from
terminals at the cells with a setup, run, rework or indirect code, one open operation per employee and an
auto-close at shift end. The machine-monitoring intervals carry the job the operator opened at the cell, so the
feed posts setup, cycle, alarm and in-operation idle time to jobs on its own. The outside-processing lines require
a job number. The scrap events require a reason code. The work-center rate table carries a labor rate, a burden
rate and an attended ratio per work center in place of the one blended rate. The routings carry standards
refreshed from the machine-measured cycles where the estimator accepted the measurement, with an effective date.</p>
<p><strong>What was introduced.</strong> A reporting layer that builds job cost from the transactions, never from an
entry: the program crosswalk that maps the monitoring feed's program numbers to parts so machine hours can be
assigned to jobs; the estimate backfill that loaded a quote-line estimate onto {bf_quote:,} of the {m1:,} historic jobs;
the attribution that tied {att_ok:,} historic outside-processing lines to their jobs; the labor correction log that
records, for every clock record, which rule fired and what changed, with {pc_unrep} of the affected records
flagged unrepairable rather than guessed; the job cost by element with a source tag on every actual (machine,
terminal, scan, issue, purchase order, routing standard, unrepairable), in three versions (as the ERP had it, the
history corrected, and the engagement-period jobs under the new process); and a current-cost recalculation of
every repeat part at today's material prices, pool rates and measured standards.</p>
<p><strong>What it provides.</strong> Actual against estimate by element on every job, in progress and at close-out, with
each element marked measured or estimated and the job's coverage stated; the repricing queue, which puts every
repeat part's standing price against its current cost, shows what moved since the last quote and carries the
controller's and owner's decisions; margin by customer, part family, lot size, work center, material, estimator and
month on the corrected cost, which is what this report reads; and a dashboard that keeps the measures current.
Coverage is reported rather than assumed: on jobs completed under the new process {pct(cov['measured_cost_share'])} of cost
rests on a transaction, and the remainder is named on each job.</p>
{B.section("overall", "Section 3", "The Margin Picture")}
<p>Repeat parts on standing prices are {pct(j25.loc[j25['job_type'] == 'repeat', 'price'].sum() / rev25)} of
revenue and earn {type_rows[0][4]}; new quoted work earns {type_rows[1][4]}; the own-product line, sold from
a price list built on launch-day standards, earns {type_rows[2][4]}. The margin at estimate, what the
estimator expected when the price was set, is shown beside the margin realized: the estimate flattered
every type.</p>
{sub(f"Margin by Job Type, {YEAR}")}
{type_table}
<p>Month by month the realized margin held between the mid-twenties and the low thirties through the
history, well below what the estimates promised, and the gap between the two lines is the sum of the
patterns below. The engagement period, marked from the week the estimate began to carry to the job, is
costed under the new process: completed jobs released since then earn {pct(eng_m)} with
{pct(cov['measured_cost_share'])} of their cost measured.</p>
{B.chart("Margin on Price by Release Month, Realized against Estimated", chart_month(d["month"]))}
<p>The interquartile range of job margin in {YEAR} runs from {pct(q1)} to {pct(q3)}: half of all jobs
fall inside that band, and the quarter below it is where the money goes. The remainder of this report
is about that quarter.</p>

{B.section("findings", "Section 4", "Findings")}
<p>Eight patterns were found in the corrected job cost. Each is stated with its evidence, the share of
the underlying cost that is measured rather than estimated, and, where it is a pricing or estimating
problem, the annual margin it is worth on {YEAR}'s activity. The dollar figures are sized so they do
not overlap: repeat parts are priced through the repricing queue (4.1), and the estimating patterns
(4.2, 4.5, 4.6) are sized on new quoted work only.</p>

{B.section("p1", "Section 4.1", "Repeat-part erosion: the parts quoted longest ago")}
<p>Of the {len(q):,} repeat parts, <strong>{int(q['below_target'].sum())}</strong> ({pct(q['below_target'].mean())})
now stand below current cost plus the target markup, and {int(q['below_cost'].sum())} stand below cost.
They concentrate in the {len(coh)} parts first quoted in {COHORT_YEAR} or earlier, three to five years ago:
<strong>{pct(coh['below_target'].mean())}</strong> of that cohort is below target against {pct(rest['below_target'].mean())} of the
parts quoted since, and its median implied margin is {pct(coh['implied_margin_on_price'].median())} against
{pct(rest['implied_margin_on_price'].median())}. The mechanism is visible part by part on the queue: on the
cohort, material moved {money(coh['moved_material'].median(), 2)} a piece since the part was last quoted and the
rate moved {money(coh['moved_rate'].median(), 2)}, against {money(rest['moved_material'].median(), 2)} and
{money(rest['moved_rate'].median(), 2)} on the newer parts, while the standing price moved only with the annual
letters ({', '.join(f'{v:.1%}' for v in C.ANNUAL_INCREASE_LETTER.values())}). Aluminum and stainless bar parts,
whose stock prices rose fastest, are {pct(p1_bar['below_target'].mean())} below target against
{pct(p1_other['below_target'].mean())} of the rest.</p>
{B.chart("Repeat Parts Below Cost plus Target, by Year First Quoted", chart_bars([str(int(y)) for y in sorted(q['first_quote_date'].dt.year.unique())], [q.loc[q['first_quote_date'].dt.year == y, 'below_target'].mean() for y in sorted(q['first_quote_date'].dt.year.unique())], ylabel="Share of parts below target", colors=[B.ACCENT_RED if y <= COHORT_YEAR else B.DARK_BLUE for y in sorted(q['first_quote_date'].dt.year.unique())]))}
{B.callout(f"<strong>{money(p1_gap)} a year</strong> separates the standing prices below target from current cost plus target on the last twelve months' volume {ms(j25[j25['job_type'] == 'repeat'])}. The repricing review in Section 6 has taken {money(p1_taken)} of it.")}

{B.section("p2", "Section 4.2", "Small-lot setup underestimation")}
<p>Margin falls off sharply below {C.SMALL_LOT_THRESHOLD} pieces, not gradually: lots of 1 to 9 pieces earn
{pct(lot.loc['1-9', 'margin_on_price'])} and {pct(lot.loc['1-9', 'share_negative'])} of them lose money, lots of
10 to 24 earn {pct(lot.loc['10-24', 'margin_on_price'])}, and everything from 25 up sits near or above
target. The cause is on the mill-turn and 5-axis cells, where the routing standard assumes a repeat
setup and a small lot gets a first-article setup every time: measured setup hours run
{setup_small:.2f}&times; the standard on lots under {C.SMALL_LOT_THRESHOLD} pieces against {setup_large:.2f}&times; above it, a
{setup_small / setup_large:.1f}&times; difference that the routing does not carry.</p>
{B.chart("Margin by Lot Size, with Setup Hours against Standard on the Mill-turn and 5-axis Cells", chart_lot(d["lot"], j25))}
{B.callout(f"On new quoted work under {C.SMALL_LOT_THRESHOLD} pieces, setup hours beyond the standard cost <strong>{money(p2_dollars)}</strong> in {YEAR} that the quotes did not carry {ms(small)}. Quoting small lots at the measured first-article setup recovers it.")}

{B.section("p3", "Section 4.3", "One customer's change orders")}
<p>{co_rec['name']} ({co_id}, {co_rec['industry']}) is the shop's number {co_rank} customer by revenue and its
least profitable large account: {pct(co_m)} margin on price in {YEAR} against {pct(margin25)} for the shop, with
{pct(co['estimated_margin_on_price'])} expected at estimate. The customer issued {int(co_rec['change_order_count_12m'])}
revision changes in the last twelve months against a median of {int(d['customers']['change_order_count_12m'].median())}
across the book, and each one adds programming and first-article time after release that is never billed. Labor
hours on the account's jobs run {co_hours_ratio:.2f}&times; the estimate against {other_ratio:.2f}&times; for everyone else,
on every family it buys.</p>
{B.chart("Margin on Price, Top 15 Customers by Revenue", chart_customers(cust))}
{B.callout(f"Labor over the estimate on {co_rec['name']}'s {YEAR} jobs came to <strong>{money(p3_dollars)}</strong> {ms(co_jobs)}. A change-order line on every revision recovers it; the customer's contract allows one.")}

{B.section("p4", "Section 4.4", "The blended rate reversed the ranking of the part families")}
<p>Until week 5 the ERP costed every hour at one blended shop rate, so a manual deburr hour cost the
same as a 5-axis hour. Under the work-center pool rates the estimate for each family moves in
opposite directions: the manual and secondary-heavy families ({', '.join(flattered['part_family'].head(3))}) that looked marginal
under the blended rate are fine, and the 5-axis-heavy families ({' and '.join(hidden['part_family'])}) that looked
fine lose eight to twelve points, {' and '.join(hidden_below['part_family'])} to below target. The chart shows how far each
cell's pool rate sits from the blended rate; the table shows what that did to each family.</p>
{B.chart("Work-center Pool Rate against the Blended Shop Rate", wc_png)}
{fam_table}
{B.callout(f"This is a measurement finding rather than a recovery: it changes which families to quote carefully. {'The family' if len(hidden_below) == 1 else 'The ' + str(len(hidden_below)) + ' families'} the blended rate flattered to below target ({', '.join(hidden_below['part_family'])}) {'is' if len(hidden_below) == 1 else 'are'} {money(p4_dollars)} a year short of target under the pools {ms(j25[j25['part_family'].isin(hidden_below['part_family'])])}, an amount that overlaps 4.2 and 4.5 and is not added to the total.")}

{B.section("p5", "Section 4.5", "Estimator bias on titanium and Inconel")}
<p>Jobs in titanium and Inconel run <strong>{run_bias:.2f}&times;</strong> their estimated run hours, consistently, against
{run_rest:.2f}&times; for every other material. The spreadsheet's speeds and feeds for the two alloys were entered
at go-live and never validated against a cycle; every other material's standard was at least as good
as the machines could measure. The effect is the same size in every family and on every machine that
cuts them, which points to the estimate, not the floor.</p>
{B.chart("Run Hours against Estimate by Material (median of jobs)", chart_material(j25))}
{B.callout(f"Run hours beyond the estimate on new titanium and Inconel work cost <strong>{money(p5_dollars)}</strong> in {YEAR} {ms(bias)}. Validating the two alloys' speeds and feeds against the measured cycles closes it at the quote.")}

{B.section("p6", "Section 4.6", "Outside processing creep")}
<p>The plating vendor raised its prices {pct(C.OSP_PLATING_VENDOR_RISE_2Y)} over two years, in steps. The estimator's
spreadsheet still carries the rate from before the first step, and because the purchase-order lines were
coded to the general ledger with no job number, nobody compared the two. On the jobs whose only outside
process is plating, indexed to each part's first order, the price paid is now {plating_idx['paid'].iloc[-1]:.2f}&times;
while the price in the estimate is {plating_idx['est'].iloc[-1]:.2f}&times;.</p>
{B.chart("Plating: Price Paid against Price Estimated, Indexed to Each Part's First Order", plating_png)}
{B.callout(f"Outside processing over the estimate on the {YEAR} jobs plated by the vendor came to <strong>{money(p6_dollars)}</strong> {ms(pl)}. With the job number now on every PO the comparison runs itself; the spreadsheet rate needs to move to the vendor's current price.")}

{B.section("p7", "Section 4.7", "Own products under standard")}
<p>The fourteen own products sell from a price list set at {C.OWN_PRODUCT_LIST_MARKUP - 1:.0%} over a standard cost that was
fixed at each product's launch and never revised. At current cost, <strong>{len(own_below)} of the 14</strong>
({', '.join(own_below['part_number'])}) sell below cost at list, and the line as a whole earned {pct(own_m)} in {YEAR}.</p>
{own_table}
{B.callout(f"Bringing the fourteen list prices to current cost plus target is worth <strong>{money(p7_dollars)}</strong> a year on the last twelve months' volume {ms(own_jobs)}.")}

{B.section("p8", "Section 4.8", "Clocked hours against machine hours")}
<p>On the monitored cells the clock records the door terminals produced in {YEAR} carry
<strong>{pct(p8_over)} more hours</strong> than the machines ran: {p8_hours:,.0f} hours, worth {money(p8_dollars)} at the
blended rate, that no machine spent on a job. The gap is widest exactly where multi-machine tending and
overnight runs are commonest: the Swiss and wire EDM cells, where one operator tends two or three
machines and a record left open at the door runs until the next morning. This is why the history was
rebuilt from the machines: on every monitored cell the cleaned job cost uses the machine's own hours, and the
clock record is a check rather than the source.</p>
{B.chart(f"Clocked Hours over Machine Hours by Cell, {YEAR}", clocked_png)}

{B.section("customers", "Section 5", "Customer Profitability")}
<p>Revenue is concentrated: the top customer is {pct(conc[1][0])} of revenue over the three years and
{pct(conc[1][1])} of contribution, the top five are {pct(conc[5][0])} and {pct(conc[5][1])}, the top ten
{pct(conc[10][0])} and {pct(conc[10][1])}. Margin by customer, after change orders, expedites and rework,
ranges from {pct(top15c['margin_on_price'].min())} to {pct(top15c['margin_on_price'].max())} across the top fifteen.
{'One customer earns' if len(below_hurdle) == 1 else str(len(below_hurdle)) + ' customers earn'} less than {pct(HURDLE)} on price, below the shop's cost of capital:
{', '.join(f"{r.customer_name} ({pct(r.margin_on_price)}, {k(r.revenue / 3)} a year)" for r in below_hurdle.head(6).itertuples())}.
Among the large accounts the lowest is {co_rec['name']} at {pct(co['margin_on_price'])}, for the reason in 4.3; the own-product
line, sold to stock, earns {pct(cust.loc[cust['customer_id'] == 'OWN', 'margin_on_price'].iloc[0])} for the reason in 4.7.</p>
{cust_table}

{B.section("repricing", "Section 6", "The Repricing List")}
<p>The repricing queue puts every repeat part against its current cost at today's material prices, the
pool rates and the measured standards. The bottom quartile by implied margin, {len(bottom)} parts, went to the
controller and the owner in weeks 7 to 9. They repriced {int(dec.get('reprice', 0))}, held {int(dec.get('hold', 0))}
(two of them large-customer parts the owner declined to touch before contract renewal, and said so),
exited {int(dec.get('exit', 0))} and left {int(dec.get('pending', 0))} pending the customer's answer. The decisions taken recover
<strong>{money(p1_taken)}</strong> a year against the {money(p1_gap)} available across every part below target;
the queue carries the rest, and the monthly review works down it.</p>
{sub("The Largest Gaps and the Decisions Taken")}
{rp_table}

{B.section("accuracy", "Section 7", "Estimate Accuracy")}
<p>Estimate accuracy is shown as the distribution of actual over estimate by cost element, for the
{YEAR} history (estimates backfilled from the quoting module) and for the completed jobs of the engagement
period (estimate carried on the job, measured standards, pool rates). Material and outside processing moved
to 1.0 and their spread closed, because the estimate now carries the price of the day and the vendor's
current price. Run hours narrowed. Setup hours still come in under the standard on most jobs and over it on
small lots, because the measured refresh reached only the parts the machines had measured by week 8; the
rest still carry the standard set at first quote, and the quarterly refresh works through them.</p>
{B.chart(f"Actual over Estimate by Element, {YEAR} History against the Engagement Period", acc_png)}
{acc_table}
<p>By estimator the gap between the margin expected and the margin realized runs two to four points on the two
estimators who quote most of the work. By quote year the realized margin on new work held flat through
{YEAR} and moved only in {YEAR + 1}, once the refreshed standards and pool rates reached the quotes: the estimates
were not getting better on their own.</p>
{sub("Margin by Estimator, All Jobs")}
{est_table}
{sub("New Quoted Work by Year Quoted")}
{qy_table}

{B.section("actions", "Section 8", "Recommended Actions")}
<p>The findings resolve into six actions, ranked by the annual margin each one carries on {YEAR}'s
activity. None needs capital; each needs the queue, the measured standards and the job-level comparison
that now exist to be used at the point of quoting and pricing.</p>
{actions_table}
<p>The total, <strong>{k(total)} a year</strong>, is stated on the year's activity with no growth assumed
and no projection. The two measurement findings (4.4 and 4.8) are what make the six measurable and are
not counted.</p>

{B.section("appendix", "Appendix", "Method and Definitions")}
<p><strong>Job cost.</strong> Material at the issued price; labor and burden as hours at the work
center's pool rate (labor rate &times; attended ratio + burden), machine hours on the monitored cells and
corrected clock records elsewhere; outside processing at the invoiced price; scrapped pieces at the
job's material cost. History is costed in the cleaned version of the job cost mart, engagement-period
jobs in the restructured version.</p>
<p><strong>Measured share.</strong> The share of a job's cost resting on a transaction (a machine interval
assigned to the job, a clock record, a scan, an issue, a purchase order) rather than on the routing
standard, an allocated ledger residual or a record flagged unrepairable. Stated beside every dollar figure
as the coverage of the jobs behind it.</p>
<p><strong>Margin conventions.</strong> Markup on cost is the quoting convention (target {pct(TARGET)}); margin
on price is the reporting convention (target {pct(TM)}). A job is on target within {BAND * 100:.0f} points of {pct(TM)}.</p>
<p><strong>Annual dollars.</strong> Sized on {YEAR} activity, or the last twelve months' volume for standing
prices, with no growth or projection. Repeat parts are sized once, through the repricing gap; the
estimating patterns are sized on new quoted work only, so the six do not overlap.</p>
<p><strong>Data.</strong> The datasets are generated; defect types and rates reflect patterns commonly seen in
job-shop ERPs.</p>
"""
    return body, toc


def run():
    d = gather()
    body, toc = build(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = B.page("Margin Analytics Diagnostic", "", toc, body)
    OUT.write_text(html, encoding="utf-8")
    print(f"Margin diagnostic written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
