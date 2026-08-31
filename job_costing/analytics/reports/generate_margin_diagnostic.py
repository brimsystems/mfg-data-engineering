"""Margin analytics diagnostic -> docs/reports/margin_diagnostic.html

About the business, not the data: how margin is spread across the shop's jobs and
why, from the corrected job cost. The report attributes and does not project: the
2025 shortfall is split by cost element and by cause on the jobs themselves, the
effect of each action is stated on the jobs or parts it touched, and nothing is
summed into an "opportunity". Every dollar figure carries the measured share of
the cost behind it. Every number is read from a dbt mart (analytics/data/marts).

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
OUT = REPO / "docs" / "reports" / "margin_diagnostic.html"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

YEAR = 2025
TARGET = C.TARGET_MARKUP
TM = TARGET / (1 + TARGET)                  # the standard markup as a margin, used by the repricing queue
ALLOYS = ["Ti 6Al-4V bar", "Inconel 718 bar"]
CELL = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horizontal mills", "VMC": "Vertical mills",
        "MTN": "Mill-turn", "FAX": "5-axis", "SAW": "Saw", "MDP": "Manual drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
ELEMENTS = [("c_material", "Material"), ("c_setup", "Setup hours"), ("c_run", "Run hours"),
            ("c_outside", "Outside processing"), ("c_scrap_rework", "Scrap and rework")]
CAUSES = [("cause_revision_work_unbilled", "Revision work not billed"),
          ("cause_alloy_run_hours", "Titanium and Inconel run hours"),
          ("cause_standard_below_cycle", "Routing standard below the measured cycle"),
          ("cause_older_machine", "Run on an older vertical mill"),
          ("cause_small_lot_setup", "Small-lot setup, mill-turn and 5-axis"),
          ("cause_first_run_after_revision", "First run after a revision"),
          ("cause_plating_rate", "Plating at a stale rate"),
          ("cause_vendor_price", "Other vendors above the estimate"),
          ("cause_osp_allocated", "Outside processing allocated from the ledger"),
          ("cause_scrap_rework", "Scrap and rework"),
          ("cause_material", "Material over estimate"),
          ("not_attributable", "Not attributable"),
          ("offset_elements", "Elements under estimate")]
# the causes an engagement decision now acts on, and the decision that does
ADDRESSED = {"cause_revision_work_unbilled": "A7", "cause_alloy_run_hours": "A5", "cause_standard_below_cycle": "A1",
             "cause_older_machine": "A8", "cause_small_lot_setup": "A6", "cause_plating_rate": "A4"}


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
    s = f"${a/1e6:.2f}M" if a >= 1e6 else f"${a/1e3:.0f}K" if a >= 1e3 else f"${a:,.0f}"
    return ("&minus;" if x < 0 else "") + s


def pct(x, d=0):
    if pd.isna(x):
        return "&ndash;"
    return f"{round(x * 100, d) + 0.0:.{d}f}%"


def measured_share(df):
    """The measured share of the cost behind a set of jobs."""
    c = df["act_total_cost"].sum()
    return float((df["coverage"].clip(upper=1) * df["act_total_cost"]).sum() / c) if c else np.nan


def ms(df):
    return f"({pct(measured_share(df))} of the cost measured)"


def nw(x):
    return f'<span style="white-space:nowrap;">{x}</span>'


def sub(t):
    return f'<p style="font-size:18px;font-weight:700;color:{B.DARK_GREY};margin-top:30px;">{t}</p>'


def widths(table_html, pcts):
    cols = "".join(f'<col style="width:{p}%;">' for p in pcts)
    return table_html.replace('<table class="data-table">', f'<table class="data-table" style="table-layout:fixed;"><colgroup>{cols}</colgroup>', 1)


# ── data ────────────────────────────────────────────────────────────────────
def gather():
    d = {}
    j = _pq("mart_margin_by_job")
    j["hours_ratio"] = j["act_labor_hours"] / (j["est_setup_hours"] + j["est_run_hours"]).replace(0, np.nan)
    d["jobs"] = j
    d["j25"] = j[j["release_year"] == YEAR].copy()
    s = _pq("mart_job_shortfall")
    d["s25"] = s[s["release_year"] == YEAR].copy()
    d["cause"] = _pq("mart_job_cause")
    d["driver"] = _pq("mart_job_driver")
    d["replay"] = _pq("mart_inprogress_replay")
    d["spread"] = _pq("mart_part_margin_spread")
    d["queue"] = _pq("mart_repricing_queue")
    d["own"] = _pq("mart_own_products")
    d["est"] = _pq("mart_margin_by_estimator")
    d["estimate"] = _pq("int_estimate_by_job")
    d["osp"] = _pq("int_osp_by_job")
    d["ops"] = _pq("int_job_op_progress")
    d["age"] = _pq("int_machine_age_cycle")
    d["machine"] = _pq("int_machine_hours_by_job")
    d["actions"] = _pq("mart_engagement_actions")
    d["coverage"] = _pq("mart_coverage_weekly")
    d["t8"] = _pq("dq_t8_material_wrong_job")
    d["t6"] = _pq("dq_t6_rework_as_run")
    d["std_log"] = pd.read_csv(REPO / "data_source" / "raw" / "remediation" / "standard_update_log.csv")
    d["customers"] = pd.read_csv(REPO / "data_source" / "raw" / "erp" / "customers.csv")
    d["quotes"] = pd.read_csv(REPO / "data_source" / "raw" / "erp" / "quotes.csv", parse_dates=["quote_date"])
    return d


# ── charts ──────────────────────────────────────────────────────────────────
def _hist(ax, m, color, bins, fs, ymax=None, share_axis=False, points=False, min_label=0.0, red_below=0.0):
    """One margin histogram: bars below zero red, the rest in the series color, each labeled with
    its share of the jobs, and the average dashed."""
    bins = np.round(bins, 6)
    w = bins[1] - bins[0]
    weights = np.full(len(m), 1 / len(m)) if share_axis else None
    n, edges, patches = ax.hist(m.clip(bins[0], bins[-1] - 1e-9), bins=bins, weights=weights, color=color, edgecolor="white", linewidth=0.6)
    for pch, left, cnt in zip(patches, edges[:-1], n):
        if left + w <= red_below + 1e-9:
            pch.set_facecolor(B.ACCENT_RED)
        share = cnt if share_axis else cnt / len(m)
        if cnt and share >= min_label:
            ax.text(left + w / 2, cnt, "<1%" if round(share * 100) < 1 else f"{share:.0%}", ha="center", va="bottom", fontsize=fs, zorder=5,
                    bbox=dict(facecolor="white", edgecolor="none", pad=0.4, alpha=0.9))
    mean = m.mean()
    top = ymax or n.max() * 1.18
    ax.set_ylim(0, top)
    ax.axvline(mean, color=B.DARK_GREY, linewidth=1.4, linestyle="--")
    avg = f" average {mean * 100:+.1f} pts" if points else f" average {mean:.0%}"
    ax.text(mean, top * 0.99, avg.replace("-", "\u2212"), color=B.DARK_GREY, fontsize=fs + 1, va="top", ha="left")
    if points:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v * 100:+.0f}".replace("-", "\u2212") if abs(v) > 1e-9 else "0"))
    else:
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    if share_axis:
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    B.chart_style(ax)


def chart_histogram(j25):
    fig, ax = B.make_fig(4.2)
    _hist(ax, j25["margin_on_price"], B.LIGHT_BLUE, np.arange(-0.40, 0.601, 0.05), 6.5)
    ax.set_xlabel("Margin"); ax.set_ylabel("Jobs")
    return B.b64(fig)


TYPE_COLORS = [("repeat", "Repeat parts", B.LIGHT_BLUE), ("new", "New quoted work", B.LIGHT_BLUE)]


def chart_histogram_types(j25):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(B.CHART_W, 3.6), sharey=True)
    for ax, (t, lab, col) in zip(axes, TYPE_COLORS):
        x = j25[j25["job_type"] == t]
        _hist(ax, x["margin_on_price"], col, np.arange(-0.40, 0.601, 0.10), 7, ymax=1000)
        ax.set_title(f"{lab} ({len(x):,} jobs)", fontsize=10, fontweight="bold")
        ax.tick_params(labelsize=8.5)
        ax.set_xlabel("Margin", fontsize=9)
        ax.yaxis.set_tick_params(labelleft=True)
    axes[0].set_ylabel("Jobs")
    fig.tight_layout()
    return B.b64(fig)


SIZE_BANDS = [("Under 25 pieces", 0, 24), ("25–100 pieces", 25, 100), ("Over 100 pieces", 101, 10 ** 9)]


def chart_histogram_sizes(j25):
    import matplotlib.pyplot as plt
    bins = np.round(np.arange(-0.40, 0.601, 0.10), 6)
    peak = max(np.histogram(j25[j25["quantity"].between(lo, hi)]["margin_on_price"].clip(bins[0], bins[-1] - 1e-9), bins=bins)[0].max()
               for _, lo, hi in SIZE_BANDS)
    ymax = np.ceil(peak * 1.18 / 100) * 100
    fig, axes = plt.subplots(1, 3, figsize=(B.CHART_W, 3.5), sharey=True)
    for ax, (lab, lo, hi) in zip(axes, SIZE_BANDS):
        x = j25[j25["quantity"].between(lo, hi)]
        _hist(ax, x["margin_on_price"], B.LIGHT_BLUE, bins, 6.5, ymax=ymax, min_label=0.01)
        ax.set_title(f"{lab} ({len(x):,} jobs)", fontsize=9.5, fontweight="bold")
        ax.tick_params(labelsize=8)
        ax.yaxis.set_tick_params(labelleft=True)
        ax.set_xlabel("Margin", fontsize=9)
    axes[0].set_ylabel("Jobs")
    fig.tight_layout()
    return B.b64(fig)


GAP_BINS = np.arange(-0.60, 0.401, 0.05)


def chart_margin_gap(j25):
    fig, ax = B.make_fig(4.2)
    gap = j25["margin_on_price"] - j25["estimated_margin_on_price"]
    _hist(ax, gap, B.LIGHT_BLUE, GAP_BINS, 6.5, points=True, red_below=-0.20)
    ax.set_xlabel("Actual less estimated margin, points"); ax.set_ylabel("Jobs")
    return B.b64(fig)


def chart_margin_gap_panels(groups):
    """The gap chart in panels, one per group, counted on a common scale."""
    import matplotlib.pyplot as plt
    bins = np.round(np.arange(-0.60, 0.401, 0.10), 6)
    gaps = [(lab, x["margin_on_price"] - x["estimated_margin_on_price"]) for lab, x in groups]
    peak = max(np.histogram(g.clip(bins[0], bins[-1] - 1e-9), bins=bins)[0].max() for _, g in gaps)
    ymax = np.ceil(peak * 1.18 / 100) * 100
    fig, axes = plt.subplots(1, len(gaps), figsize=(B.CHART_W, 3.5), sharey=True)
    for ax, (lab, g) in zip(axes, gaps):
        _hist(ax, g, B.LIGHT_BLUE, bins, 6.5, ymax=ymax, points=True, min_label=0.01, red_below=-0.20)
        ax.set_title(f"{lab} ({len(g):,} jobs)", fontsize=9.5, fontweight="bold")
        ax.tick_params(labelsize=8)
        ax.yaxis.set_tick_params(labelleft=True)
        ax.set_xlabel("Actual less estimated margin, points", fontsize=8.5)
    axes[0].set_ylabel("Jobs")
    fig.tight_layout()
    return B.b64(fig)


def chart_waterfall(labels, values, total_label):
    fig, ax = B.make_fig(4.2)
    x = np.arange(len(labels) + 1)
    cum = 0.0
    for i, v in enumerate(values):
        bottom = cum if v >= 0 else cum + v
        ax.bar(i, abs(v), bottom=bottom, color=B.ACCENT_RED if v >= 0 else B.DARK_BLUE, width=0.62)
        ax.text(i, max(cum, cum + v) + max(values) * 0.02, k(v).replace("&minus;", "-"), ha="center", va="bottom", fontsize=9)
        cum += v
    ax.bar(len(labels), cum, color=B.DARK_GREY, width=0.62)
    ax.text(len(labels), cum + max(values) * 0.02, k(cum), ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.axhline(0, color=B.MED_GREY, linewidth=0.8)
    ax.set_xticks(x); ax.set_xticklabels(labels + [total_label], rotation=0, fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v/1e6:.1f}M" if abs(v) >= 1e6 else f"${v/1e3:.0f}K"))
    ax.set_ylabel("Actual cost over estimate")
    B.chart_style(ax)
    return B.b64(fig)


def chart_bars(labels, values, color=B.DARK_BLUE, fmt=lambda v: f"{v:.0%}", ylabel="", target=None, h=None, colors=None, rotate=0, ref=None):
    fig, ax = B.make_fig(h)
    x = np.arange(len(labels))
    ax.bar(x, values, color=colors or color, width=0.62)
    top = max(values) if len(values) else 1
    for xi, v in zip(x, values):
        ax.text(xi, v + top * 0.015, fmt(v), ha="center", va="bottom", fontsize=9)
    if target is not None:
        ax.axhline(target, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    if ref is not None:
        ax.axhline(ref, color=B.MED_GREY, linewidth=1.0, linestyle=":")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=rotate, ha="right" if rotate else "center")
    ax.set_ylabel(ylabel)
    if fmt(0.5).endswith("%"):
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    B.chart_style(ax)
    return B.b64(fig)


def chart_hbar(labels, values, xlabel):
    fig, ax = B.make_fig(0.42 * len(labels) + 1.0)
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, color=[B.ACCENT_RED if v >= 0 else B.DARK_BLUE for v in values], height=0.62)
    span = max(abs(v) for v in values)
    for yi, v in zip(y, values):
        ax.text(v + (span * 0.01 if v >= 0 else -span * 0.01), yi, k(v).replace("&minus;", "-"), va="center",
                ha="left" if v >= 0 else "right", fontsize=9)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9.5); ax.set_xlabel(xlabel)
    ax.axvline(0, color=B.MED_GREY, linewidth=0.8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"-${abs(v)/1e3:,.0f}K" if v < 0 else f"${v/1e3:,.0f}K"))
    ax.set_xlim(min(0, min(values)) * 1.25, max(values) * 1.18)
    B.chart_style(ax); ax.xaxis.grid(True, color=B.LIGHT_GREY); ax.yaxis.grid(False)
    return B.b64(fig)


def chart_lot(lot):
    order = ["1-9", "10-24", "25-49", "50-99", "100-249", "250+"]
    lot = lot.reindex(order)
    fig, ax = B.make_fig()
    x = np.arange(len(order))
    ax.bar(x, lot["margin"], color=[B.ACCENT_RED if v < 0 else B.DARK_BLUE for v in lot["margin"]], width=0.6)
    for xi, v in zip(x, lot["margin"]):
        ax.text(xi, v + 0.006, f"{v:.0%}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels([f"{o} pieces" for o in order]); ax.set_ylabel("Margin")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax2 = ax.twinx()
    ax2.plot(x, lot["setup_ratio"], color=B.ACCENT_RED, marker="o", linewidth=2, label="Setup hours over standard, mill-turn and 5-axis")
    ax2.set_ylabel("Setup hours / standard"); ax2.set_ylim(0.5, max(2.0, lot["setup_ratio"].max() * 1.1))
    ax2.spines["top"].set_visible(False)
    ax2.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=9)
    B.chart_style(ax)
    return B.b64(fig)


def chart_plating(osp, jobs):
    """On jobs whose only outside process is plating: the invoice over the estimate, by quarter released."""
    lines = osp[osp["job_id"].notna()]
    only = lines.groupby("job_id")["service_type"].agg(lambda s_: set(s_) == {"plating"})
    v = jobs[jobs["job_id"].isin(only[only].index) & (jobs["est_outside"] > 0)].copy()
    v["ratio"] = v["act_outside"] / v["est_outside"]
    v["q"] = pd.to_datetime(v["release_date"]).dt.to_period("Q").dt.to_timestamp()
    g = v.groupby("q").agg(r=("ratio", "median"), n=("job_id", "size"))
    g = g[g["n"] >= 5]
    fig, ax = B.make_fig()
    ax.plot(g.index, g["r"], color=B.DARK_BLUE, marker="o", linewidth=2)
    ax.axhline(1.0, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_ylabel("Plating invoice / estimate (median of jobs)")
    B.chart_style(ax)
    return B.b64(fig), g


def chart_spread(spread_by_part):
    fig, ax = B.make_fig()
    v = (spread_by_part * 100).clip(upper=80)
    bins = np.arange(0, 82, 4)
    n, edges, patches = ax.hist(v, bins=bins, color=B.LIGHT_BLUE, edgecolor="white", linewidth=0.6)
    for p, left in zip(patches, edges[:-1]):
        if left >= 20:
            p.set_facecolor(B.DARK_BLUE)
    ax.set_xlabel("Best job's margin less worst job's margin, points (80 or more shown at the edge)"); ax.set_ylabel("Repeat parts")
    B.chart_style(ax)
    return B.b64(fig)


def chart_replay(r):
    """Where on the routing the flag fired, as a share of the routing, for the jobs flagged."""
    f = r[r["flagged"]].copy()
    f["pos"] = np.where(f["flag_op_index"] >= f["ops"], "Last operation", np.where(f["flag_op_index"] == 1, "First operation", "A middle operation"))
    order = ["First operation", "A middle operation", "Last operation"]
    a = f[f["flagged_while_open"]]["pos"].value_counts().reindex(order).fillna(0)
    b = f[~f["flagged_while_open"]]["pos"].value_counts().reindex(order).fillna(0)
    fig, ax = B.make_fig(3.6)
    x = np.arange(len(order))
    ax.bar(x, a, color=B.DARK_BLUE, width=0.6, label=f"Flagged {C_ACT} or more days before ship, with operations left")
    ax.bar(x, b, bottom=a, color=B.MED_GREY, width=0.6, label="Flagged too late to act")
    for xi, (u, w) in enumerate(zip(a, b)):
        ax.text(xi, u + w + 8, f"{int(u + w):,}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(order); ax.set_ylabel("Jobs flagged")
    ax.legend(frameon=False, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    B.chart_style(ax)
    return B.b64(fig)


C_ACT = 3   # the dbt var inprogress_actionable_days


def chart_customers(top):
    fig, ax = B.make_fig(4.0)
    x = np.arange(len(top)); w = 0.38
    ax.bar(x - w / 2, top["est_margin"], w, color=B.MED_GREY, label="Estimated margin")
    ax.bar(x + w / 2, top["margin"], w, color=[B.ACCENT_RED if v < 0 else B.DARK_BLUE for v in top["margin"]], label="Margin")
    ax.set_xticks(x); ax.set_xticklabels(top.index, rotation=45, ha="right")
    ax.set_ylabel("Margin"); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    B.chart_style(ax)
    return B.b64(fig)


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


# ── the report ──────────────────────────────────────────────────────────────
def build(d):
    j, j25, s25, q = d["jobs"], d["j25"], d["s25"], d["queue"]
    rev25 = j25["price"].sum(); margin25 = j25["contribution"].sum() / rev25
    mg = j25["margin_on_price"]
    neg = j25["contribution"] < 0
    m_mean, m_sd = mg.mean(), mg.std()
    est_m25 = 1 - j25["est_total_cost"].sum() / rev25; est_mean = j25["estimated_margin_on_price"].mean()
    size_x = [j25[j25["quantity"].between(lo, hi)] for _, lo, hi in SIZE_BANDS]
    size_avg = [x["margin_on_price"].mean() for x in size_x]; size_neg = [(x["contribution"] < 0).mean() for x in size_x]
    gap = j25["margin_on_price"] - j25["estimated_margin_on_price"]
    size_gap = [x["margin_on_price"] - x["estimated_margin_on_price"] for x in size_x]
    in_sd = ((mg >= m_mean - m_sd) & (mg <= m_mean + m_sd)).mean()
    by_type = {t: j25[j25["job_type"] == t] for t in ["repeat", "new", "own_product"]}
    gap_rep = by_type["repeat"]["margin_on_price"] - by_type["repeat"]["estimated_margin_on_price"]
    gap_new = by_type["new"]["margin_on_price"] - by_type["new"]["estimated_margin_on_price"]
    cov25 = measured_share(j25)
    q1, q3 = mg.quantile([0.25, 0.75])

    # ── section 2: actual against estimate, every job ─────────────────────
    b = s25.copy()
    # elements under estimate (the price line is not part of actual against estimate)
    b["offset_elements"] = b["offsets"] - b["c_price"].clip(upper=0)
    bj = j25
    est_total = b["est_cost_at_pool"].sum(); act_total = b["act_total_cost"].sum()
    el = {c: b[c].sum() for c, _ in ELEMENTS}
    el_pos = {c: b[c].clip(lower=0).sum() for c, _ in ELEMENTS}
    el_neg = {c: b[c].clip(upper=0).sum() for c, _ in ELEMENTS}
    el_jobs = {c: int((b[c] > 1).sum()) for c, _ in ELEMENTS}
    over = sum(el.values()); over_pos = sum(el_pos.values()); over_neg = sum(el_neg.values())
    el_sorted = sorted([(c, lab, el[c]) for c, lab in ELEMENTS], key=lambda t: -t[2])
    ca = {c: b[c].sum() for c, _ in CAUSES}
    ca_jobs = {c: int((b[c].abs() > 1).sum()) for c, _ in CAUSES}
    ca_ms = {c: measured_share(bj[bj["job_id"].isin(b.loc[b[c].abs() > 1, "job_id"])]) for c, _ in CAUSES}
    ca_ms["cause_osp_allocated"] = 0.0          # an allocation, not a measurement, by definition
    gross = sum(v for c, v in ca.items() if not c.startswith("offset"))
    addressed = sum(ca[c] for c in ADDRESSED)

    # run hours: titanium and Inconel
    alloy = j25[j25["material_spec"].isin(ALLOYS) & (j25["est_run_hours"] > 0)]
    rest = j25[~j25["material_spec"].isin(ALLOYS) & (j25["est_run_hours"] > 0)]
    run_alloy, run_rest = alloy["run_hours_ratio"].median(), rest["run_hours_ratio"].median()
    alloy_by_cell = alloy.groupby("primary_work_center_group")["run_hours_ratio"].agg(["median", "size"])
    alloy_by_cell = alloy_by_cell[alloy_by_cell["size"] >= 10].sort_values("median", ascending=False)
    rest_by_cell = rest.groupby("primary_work_center_group")["run_hours_ratio"].median()
    alloy_hours = (b["cause_alloy_run_hours"] / b["rate"]).sum()
    age = d["age"]; age_vmc = age[age["work_center_group"] == "VMC"]
    older_factor = age_vmc["older_over_newer"].median()
    std_over = (d["std_log"]["old_std_run_min"] / d["std_log"]["measured_run_min"]).median() - 1
    mh = d["machine"].groupby("job_id")[["machine_run_hours", "machine_alarm_hours", "machine_idle_hours"]].sum()
    stop_share = ((mh["machine_alarm_hours"] + mh["machine_idle_hours"]) / mh.sum(axis=1)).median()
    std_acc = d["std_log"]; std_acc = std_acc[std_acc["reviewer_decision"] == "accepted"]

    # setup hours: small lots on mill-turn and 5-axis, measured at the cell against the routing standard
    ops = d["ops"].merge(j25[["job_id", "quantity", "lot_band", "small_lot"]], on="job_id")
    mf = ops[ops["work_center_group"].isin(["MTN", "FAX"]) & (ops["std_setup_hours"] > 0) & (ops["act_setup_hours"] > 0)].copy()
    mf["r"] = mf["act_setup_hours"] / mf["std_setup_hours"]
    setup_small, setup_large = mf.loc[mf["small_lot"], "r"].median(), mf.loc[~mf["small_lot"], "r"].median()
    lot = j25.groupby("lot_band").agg(rev=("price", "sum"), c=("contribution", "sum"), jobs=("job_id", "size"), neg=("contribution", lambda x: (x < 0).mean()))
    lot["margin"] = lot["c"] / lot["rev"]
    lot["setup_ratio"] = mf.groupby("lot_band")["r"].median()
    small_jobs = int((b["cause_small_lot_setup"] > 1).sum())

    # labor with no routing cause: the change-order customer
    cust_rec = d["customers"].set_index("customer_id")
    co_id = d["customers"].sort_values("change_order_count_12m", ascending=False)["customer_id"].iloc[0]
    co_name = cust_rec.loc[co_id, "name"]
    co_jobs = j25[j25["customer_id"] == co_id]; oth = j25[j25["customer_id"] != co_id]
    hr = lambda x: x["act_labor_hours"].sum() / (x["est_setup_hours"] + x["est_run_hours"]).sum()
    co_ratio, oth_ratio = hr(co_jobs), hr(oth)
    co_per_job = (co_jobs["act_labor_hours"] - co_jobs["est_setup_hours"] - co_jobs["est_run_hours"]).mean()
    oth_per_job = (oth["act_labor_hours"] - oth["est_setup_hours"] - oth["est_run_hours"]).mean()
    co_fam = co_jobs.groupby("part_family").apply(hr, include_groups=False)
    oth_fam = oth.groupby("part_family").apply(hr, include_groups=False)
    co_fam_n = co_jobs.groupby("part_family").size()
    co_hours = (b["cause_revision_work_unbilled"] / b["rate"]).sum()
    co_m = co_jobs["contribution"].sum() / co_jobs["price"].sum()

    # outside processing
    plating_png, plating_idx = chart_plating(d["osp"], j)
    osp_alloc = ca["cause_osp_allocated"]

    # scrap and rework
    sr = b.groupby("part_family")["c_scrap_rework"].sum().sort_values(ascending=False)
    t6_n = len(d["t6"]); t8_n = len(d["t8"])

    # ── section 4: same part, different outcomes ──────────────────────────
    sp = d["spread"]
    by_part = sp.groupby("part_number").agg(spread=("part_margin_spread", "first"), jobs=("job_id", "size"), fam=("part_family", "first"),
                                            cust=("customer_name", "first"), med=("part_median_margin", "first"),
                                            worst=("margin_on_price", "min"), best=("margin_on_price", "max"))
    examples = pick_examples(sp)

    # ── section 5: the in-progress replay ─────────────────────────────────
    r = d["replay"]; r25 = r[r["release_year"] == YEAR]
    flagged = r25[r25["flagged"]]; open_ = r25[r25["flagged_while_open"]]
    lev = r25[r25["lever"].notna()].groupby("lever").agg(jobs=("job_id", "size"), over=("overrun", "sum"),
                                                        days=("days_before_ship", "median"), ms_=("job_id", lambda x: measured_share(j25[j25["job_id"].isin(x)])))
    order = ["Change order billed", "Expedite avoided", "Quantity or scope discussed", "Nothing: no lever while open", "Nothing: flagged too late"]
    lev = lev.reindex([o for o in order if o in lev.index])
    first3 = lev.loc[[o for o in order[:3] if o in lev.index]]

    # ── section 6: loss jobs ──────────────────────────────────────────────
    # the driver of each job, assigned by the reporting layer's rules (the same model the Job Variance report reads)
    drv = d["driver"].set_index("job_id")
    loss = s25[s25["loss"]].copy()
    loss["primary"] = loss["job_id"].map(drv["driver"]).fillna("Not attributable")
    loss["action"] = loss["job_id"].map(drv["action"]).fillna("Accept")
    loss = loss.sort_values("contribution")
    lj = j25[j25["job_id"].isin(loss["job_id"])]
    by_action = loss.groupby("action").agg(jobs=("job_id", "size"), loss_=("contribution", "sum")).sort_values("loss_")

    # ── section 7: customers (2025) ───────────────────────────────────────
    cu = j25.groupby("customer_id").agg(name=("customer_name", "first"), industry=("industry", "first"), jobs=("job_id", "size"),
                                         rev=("price", "sum"), c=("contribution", "sum"), est=("est_total_cost", "sum"),
                                         hours=("act_labor_hours", "sum"), est_h=("est_setup_hours", "sum"), est_r=("est_run_hours", "sum"))
    cu["margin"] = cu["c"] / cu["rev"]; cu["est_margin"] = 1 - cu["est"] / cu["rev"]
    cu = cu.sort_values("rev", ascending=False)
    cu_ms = {cid: measured_share(j25[j25["customer_id"] == cid]) for cid in cu.index[:20]}
    tot_rev, tot_c = cu["rev"].sum(), cu["c"].sum()
    conc = {n: (cu.head(n)["rev"].sum() / tot_rev, cu.head(n)["c"].sum() / tot_c) for n in (1, 5, 10)}
    real = cu[cu.index.notna() & (cu["name"] != "Own products, to stock")]
    neg_c = real[(real["margin"] < 0) & (real["jobs"] >= 3)].sort_values("margin")
    if len(neg_c) == 0:
        neg_c = real[real["jobs"] >= 3].sort_values("margin").head(1)
    neg_id = neg_c.index[0]
    neg_jobs = s25[s25["customer_id"] == neg_id].sort_values("contribution")

    # ── section 8: repricing ──────────────────────────────────────────────
    bq = q[q["below_target"]].copy()
    bq["gap"] = bq["target_price"] / bq["standing_price"] - 1
    bq["rev"] = bq["standing_price"] * bq["annual_volume"]
    exposure = bq["gap_to_target_annual"].sum()
    own = d["own"]
    own_exp = ((own["current_unit_cost"] * (1 + TARGET) - own["list_price"]).clip(lower=0) * own["annual_volume"]).sum()
    own_gap = own["list_price"] / (own["current_unit_cost"] * (1 + TARGET)) - 1
    rp = bq[bq["decision"] == "reprice"]
    captured = ((rp["new_price"] - rp["standing_price"]).clip(lower=0) * rp["annual_volume"]).clip(upper=rp["gap_to_target_annual"]).sum()
    two_step = rp[rp["rationale"].str.contains("halfway", na=False)]
    two_step_bal = two_step["gap_to_target_annual"].sum() - ((two_step["new_price"] - two_step["standing_price"]) * two_step["annual_volume"]).clip(upper=two_step["gap_to_target_annual"]).sum()
    held = bq.loc[bq["decision"] == "hold", "gap_to_target_annual"].sum() + two_step_bal
    exited = bq.loc[bq["decision"] == "exit", "gap_to_target_annual"].sum()
    held_parts = bq[bq["decision"] == "hold"]
    moved = bq[["moved_material", "moved_rate", "moved_standard", "moved_outside"]].clip(lower=0)
    driver = moved.idxmax(axis=1).where(moved.sum(axis=1) > 0).map({"moved_material": "Material", "moved_rate": "Labor rate",
                                                                      "moved_standard": "Measured standard", "moved_outside": "Outside processing"})
    bq["driver"] = driver
    above_q = q[~q["below_target"]]
    cost_move = lambda x: (x["current_unit_cost"] / x["quoted_unit_cost"] - 1).median()
    from data_source.generate.generators.quotes_jobs import _letters_between
    letters_move = lambda x: x["last_quote_date"].map(lambda dt: _letters_between(pd.Timestamp(dt).date(), C.END_DATE) - 1).median()
    refreshed_share = q["any_standard_refreshed"].mean()
    letters = list(C.ANNUAL_INCREASE_LETTER.values())

    # ── section 9: estimate accuracy ──────────────────────────────────────
    acc_png, acc = chart_accuracy(j)
    est = d["est"].sort_values("jobs", ascending=False)
    qy = j.merge(d["estimate"][["job_id", "quote_id"]].rename(columns={"quote_id": "qid"}), on="job_id", how="left")
    qd = d["quotes"].groupby("quote_id")["quote_date"].min()
    qy["quote_year"] = qy["qid"].map(qd).dt.year
    qy = qy[qy["job_type"] == "new"].groupby("quote_year").agg(jobs=("job_id", "size"), rev=("price", "sum"), c=("contribution", "sum"), hr=("hours_ratio", "median"))
    qy["m"] = qy["c"] / qy["rev"]; qy = qy[qy["jobs"] >= 50]
    eng = j[(j["version"] == "restructured") & (j["status"] == "completed")]
    cov = d["coverage"].dropna(subset=["measured_cost_share"]).iloc[-1]
    plated = set(d["osp"].loc[(d["osp"]["service_type"] == "plating") & d["osp"]["job_id"].notna(), "job_id"])
    osp_ratio = lambda x: (x["act_outside"] / x["est_outside"].replace(0, np.nan)).median()
    pl25, pl_eng = osp_ratio(j25[j25["job_id"].isin(plated)]), osp_ratio(eng[eng["job_id"].isin(plated)])
    n_pl_eng = int(eng["job_id"].isin(plated).sum())
    alloy_eng = eng[eng["material_spec"].isin(ALLOYS) & (eng["est_run_hours"] > 0)]

    h_run, e_run = acc[("Run hours", "hist")], acc[("Run hours", "eng")]
    h_set, e_set = acc[("Setup hours", "hist")], acc[("Setup hours", "eng")]
    eff_std = d["std_log"].groupby("part_number")["effective_date"].min()
    eng_rep = eng[eng["job_type"] == "repeat"]
    pre_refresh = (pd.to_datetime(eng_rep["release_date"]) < pd.to_datetime(eng_rep["part_number"].map(eff_std))).mean()

    # ── section 10: actions ───────────────────────────────────────────────
    acts = d["actions"].set_index("action_id")
    older_cost = b["cause_older_machine"].sum()

    # ── tables ───────────────────────────────────────────────────────────
    el_rows = [[lab, k(el_pos[c]), k(el_neg[c]), k(el[c]), f"{el_jobs[c]:,}",
                pct(measured_share(bj[bj["job_id"].isin(b.loc[b[c] > 1, "job_id"])]))] for c, lab in ELEMENTS]
    el_rows.append(["<strong>All elements</strong>", f"<strong>{k(over_pos)}</strong>", f"<strong>{k(over_neg)}</strong>", f"<strong>{k(over)}</strong>",
                    f"{int((b['act_total_cost'] > b['est_cost_at_pool']).sum()):,}", pct(measured_share(bj))])
    el_table = B.data_table(["Element", "Over estimate", "Under estimate", "Net", "Jobs over estimate", "Cost measured"], el_rows, right=[1, 2, 3, 4, 5])

    cause_rows = []
    for c, lab in CAUSES:
        cause_rows.append([lab, k(ca[c]), pct(ca[c] / gross), f"{ca_jobs[c]:,}", "0% (allocated)" if c == "cause_osp_allocated" else pct(ca_ms[c])])
    cause_rows.append(["<strong>Net over estimate</strong>", f"<strong>{k(over)}</strong>", "", f"{len(b):,}", pct(measured_share(bj))])
    cause_table = B.data_table(["Cause", "Amount", "Share of the overrun before offsets", "Jobs", "Cost measured"], cause_rows, right=[1, 2, 3, 4])

    alloy_rows = [[CELL.get(g, g), f"{int(r_['size']):,}", f"{r_['median']:.2f}&times;", f"{rest_by_cell.get(g, np.nan):.2f}&times;"] for g, r_ in alloy_by_cell.iterrows()]
    alloy_table = B.data_table(["Primary cell", "Titanium and Inconel jobs", "Run hours / estimate", "Other materials"], alloy_rows, right=[1, 2, 3])

    co_rows = [[f, f"{int(co_fam_n[f]):,}", f"{co_fam[f]:.2f}&times;", f"{oth_fam.get(f, np.nan):.2f}&times;"] for f in co_fam.sort_values(ascending=False).index if co_fam_n[f] >= 5]
    co_table = B.data_table(["Part family", f"{co_name} jobs", "Labor hours / estimate", "Every other customer"], co_rows, right=[1, 2, 3])

    ex_html = ""
    for ex in examples:
        rows = [[x.job_id, pd.Timestamp(x.release_date).strftime("%d %b %Y"), f"{int(x.quantity):,}", x.revision,
                 x.vmc_machines if isinstance(x.vmc_machines, str) else "&ndash;",
                 f"{x.setup_hours_ratio:.2f}&times;" if pd.notna(x.setup_hours_ratio) else "&ndash;",
                 f"{x.run_hours_ratio:.2f}&times;" if pd.notna(x.run_hours_ratio) else "&ndash;", pct(x.margin_on_price)]
                for x in ex["jobs"].sort_values("release_date").itertuples()]
        ex_html += f"<p>{ex['text']}</p>" + sub(ex["title"]) + B.data_table(["Job", "Released", "Pieces", "Revision", "Vertical mill", "Setup / estimate", "Run / estimate", "Margin"], rows, right=[2, 5, 6, 7])

    lev_rows = [[i, f"{int(r_.jobs):,}", k(r_.over), f"{r_.days:.0f}", pct(r_.ms_)] for i, r_ in lev.iterrows()]
    lev_table = B.data_table(["What the flag allowed", "Jobs", "Cost over estimate", "Median days before ship", "Cost measured"], lev_rows, right=[1, 2, 3, 4])

    loss_rows = lambda df: [[nw(x.job_id), nw(x.part_number), x.customer_name if isinstance(x.customer_name, str) else "&ndash;", f"{int(x.quantity):,}",
                             pct(x.estimated_margin_on_price), pct(x.margin_on_price), nw(money(x.contribution)), x.primary, x.action, pct(min(x.coverage, 1))] for x in df.itertuples()]
    loss_head = ["Job", "Part", "Customer", "Pieces", "Estimated margin", "Margin", "Loss", "Driver", "Action", "Measured"]
    loss_table = widths(B.data_table(loss_head, loss_rows(loss.head(25)), right=[3, 4, 5, 6, 9]), [9, 8, 13, 6, 9, 8, 9, 15, 14, 9])
    loss_all = widths(B.data_table(loss_head, loss_rows(loss), right=[3, 4, 5, 6, 9]), [9, 8, 13, 6, 9, 8, 9, 15, 14, 9])
    est_loss = loss[loss["estimated_margin_on_price"] < 0]; est_gain = loss[loss["estimated_margin_on_price"] >= 0]
    act_rows = [[a, f"{int(r_.jobs):,}", money(r_.loss_), pct(-r_.loss_ / -loss["contribution"].sum())] for a, r_ in by_action.iterrows()]
    act_table = B.data_table(["Action", "Jobs", "Loss", "Share of the loss"], act_rows, right=[1, 2, 3])

    top15 = cu[cu["name"] != "Own products, to stock"].head(15)
    cust_rows = [[i, r_["name"], r_["industry"], f"{int(r_['jobs']):,}", k(r_["rev"]), pct(r_["rev"] / tot_rev), pct(r_["est_margin"]), pct(r_["margin"]),
                  pct(cu_ms.get(i, np.nan))] for i, r_ in top15.iterrows()]
    cust_table = B.data_table(["", "Customer", "Industry", "Jobs", "Revenue", "Share", "Estimated margin", "Margin", "Cost measured"], cust_rows, right=[3, 4, 5, 6, 7, 8])
    negj_rows = [[x.job_id, x.part_number, pd.Timestamp(x.release_date).strftime("%d %b %Y"), f"{int(x.quantity):,}", money(x.price), pct(x.estimated_margin_on_price),
                  money(x.contribution), pct(x.margin_on_price), str(drv["driver"].get(x.job_id, "&ndash;"))] for x in neg_jobs.itertuples()]
    negj_table = B.data_table(["Job", "Part", "Released", "Pieces", "Price", "Estimated margin", "Gross profit", "Margin", "Driver"], negj_rows, right=[3, 4, 5, 6, 7])

    rp_rows = []
    for x in bq.sort_values("gap_to_target_annual", ascending=False).head(12).itertuples():
        dec = x.decision + (f" at {money(x.new_price, 2)}" if pd.notna(x.new_price) else "")
        rp_rows.append([x.part_number, x.customer_name, money(x.standing_price, 2), money(x.target_price, 2), pct(x.gap, 1), money(x.gap_to_target_annual),
                        x.driver if isinstance(x.driver, str) else "&ndash;", dec,
                        str(x.rationale).replace("cost plus target", "cost plus the standard markup").replace("no path to target", "no path to the markup price")])
    rp_table = widths(B.data_table(["Part", "Customer", "Standing price", "Markup price", "Gap", "Gap a year", "What moved most", "Decision", "Reason"], rp_rows, right=[2, 3, 4, 5]),
                      [7, 11, 8, 8, 6, 8, 11, 12, 29])
    dec_rows = []
    held_only = bq.loc[bq["decision"] == "hold", "gap_to_target_annual"].sum()
    for lab, parts_, amt in [("Repriced", f"{int((bq['decision'] == 'reprice').sum()):,}", captured),
                             ("Held, with the reason recorded", f"{int((bq['decision'] == 'hold').sum()):,}", held_only),
                             ("Second step of the two-step increases, due at renewal", f"{len(two_step)} of the repriced", held - held_only),
                             ("Exited", f"{int((bq['decision'] == 'exit').sum()):,}", exited)]:
        dec_rows.append([lab, parts_, k(amt), pct(amt / exposure)])
    dec_rows.append(["<strong>All parts below the markup price</strong>", f"<strong>{len(bq):,}</strong>", f"<strong>{k(exposure)}</strong>", "100%"])
    dec_table = B.data_table(["Decision", "Parts", "Gap a year", "Share of the gap"], dec_rows, right=[1, 2, 3])
    reasons = held_parts.groupby("rationale").agg(n=("part_number", "size"), g=("gap_to_target_annual", "sum")).sort_values("g", ascending=False)
    reason_rows = [[str(i).replace("no path to target", "no path to the markup price"), f"{int(r_.n):,}", k(r_.g)] for i, r_ in reasons.iterrows()]
    if len(two_step):
        reason_rows.append([f"Balance of the {len(two_step)} parts repriced in two steps, due at the blanket renewal", f"{len(two_step):,}", k(two_step_bal)])
    reason_table = B.data_table(["Reason recorded for holding", "Parts", "Gap a year"], reason_rows, right=[1, 2])
    drv = bq.groupby("driver").agg(n=("part_number", "size"), g=("gap_to_target_annual", "sum"),
                                   rep=("decision", lambda x: (x == "reprice").mean())).sort_values("g", ascending=False)
    drv_rows = [[i, f"{int(r_.n):,}", k(r_.g), pct(r_.rep)] for i, r_ in drv.iterrows()]
    drv_table = B.data_table(["What moved most since the last quote", "Parts", "Gap a year", "Share repriced"], drv_rows, right=[1, 2, 3])
    own_rows = [[x.part_number, x.description, money(x.list_price, 2), money(x.current_unit_cost, 2), money(x.current_unit_cost * (1 + TARGET), 2),
                 pct(x.list_price / (x.current_unit_cost * (1 + TARGET)) - 1), f"{x.annual_volume:,.0f}", B.badge("below cost", B.ACCENT_RED) if x.below_cost_at_list else ""]
                for x in own.sort_values("margin_on_list_price").itertuples()]
    own_table = B.data_table(["Part", "Description", "List price", "Current cost", "Cost plus markup", "List against cost plus markup", "Annual volume", ""], own_rows, right=[2, 3, 4, 5, 6])

    acc_rows = []
    for lab in ["Material", "Setup hours", "Run hours", "Labor and burden", "Outside processing"]:
        h, e = acc[(lab, "hist")], acc[(lab, "eng")]
        acc_rows.append([lab, f"{h[1]:.2f}", f"{h[0]:.2f} to {h[2]:.2f}", f"{e[1]:.2f}", f"{e[0]:.2f} to {e[2]:.2f}"])
    acc_table = B.data_table(["Element", f"{YEAR} median", f"{YEAR} interquartile range", "Engagement median", "Engagement interquartile range"], acc_rows, right=[1, 2, 3, 4])
    est_rows = [[x.estimator_id, f"{x.jobs:,}", k(x.revenue), pct(x.estimated_margin_on_price), pct(x.margin_on_price), f"{(x.margin_on_price - x.estimated_margin_on_price) * 100:+.0f} pts"]
                for x in est.itertuples() if pd.notna(x.estimator_id)]
    est_table = B.data_table(["Estimator", "Jobs", "Revenue", "Estimated margin", "Margin", "Gap"], est_rows, right=[1, 2, 3, 4, 5])
    qy_rows = [[int(y), f"{int(x.jobs):,}", pct(x.m), f"{x.hr:.2f}"] for y, x in qy.iterrows()]
    qy_table = B.data_table(["Quote year", "Jobs", "Margin", "Labor hours / estimate (median)"], qy_rows, right=[1, 2, 3])

    # actions: effects on what each one touched
    h_run, e_run = acc[("Run hours", "hist")], acc[("Run hours", "eng")]
    h_set, e_set = acc[("Setup hours", "hist")], acc[("Setup hours", "eng")]
    eff_std = d["std_log"].groupby("part_number")["effective_date"].min()
    eng_rep = eng[eng["job_type"] == "repeat"]
    pre_refresh = (pd.to_datetime(eng_rep["release_date"]) < pd.to_datetime(eng_rep["part_number"].map(eff_std))).mean()
    exited_parts = bq[bq["decision"] == "exit"]
    effect = {
        "A1": f"{len(std_acc):,} operations moved to the measured cycle. On engagement-period jobs the run-hours median is {e_run[1]:.2f} (interquartile {e_run[0]:.2f} to {e_run[2]:.2f}) against {h_run[1]:.2f} ({h_run[0]:.2f} to {h_run[2]:.2f}) in {YEAR}.",
        "A2": f"{int((bq['decision'] == 'reprice').sum()):,} parts; {k(captured)} a year at current volume, {pct(captured / exposure)} of the gap.",
        "A3": f"{len(exited_parts):,} parts carrying {k(exited)} of the gap a year.",
        "A4": f"Plated jobs in the engagement period came in at {pl_eng:.2f}&times; the outside-processing estimate ({n_pl_eng} jobs) against {pl25:.2f}&times; in {YEAR}.",
        "A5": f"Stated as decided. The {len(alloy_eng)} engagement-period jobs in the two alloys were estimated before it and ran {alloy_eng['run_hours_ratio'].median():.2f}&times; their run hours.",
        "A6": "Stated as decided: no small lot has yet been quoted and completed under the new setup.",
        "A7": f"Stated as decided: applies to revisions issued from week {int(acts.loc['A7', 'engagement_week'])}.",
        "A8": "Stated as decided: effective as capacity on the newer mills allows.",
        "A9": f"{len(own):,} products; the gap at list is {k(own_exp)} a year at current volume.",
    }
    declined_effect = {
        "D1": f"{len(held_parts):,} parts, {k(held_parts['gap_to_target_annual'].sum())} of the gap a year",
        "D2": f"{int(held_parts['rationale'].str.startswith('Owner declines').sum())} parts, {k(held_parts.loc[held_parts['rationale'].str.startswith('Owner declines'), 'gap_to_target_annual'].sum())} of the gap a year",
        "D3": f"{k(ca['cause_revision_work_unbilled'])} of revision work in {YEAR} not recovered",
        "D4": f"{k(older_cost)} of run hours on the older mills in {YEAR}",
        "D5": ", ".join(own.loc[own["below_cost_at_list"], "part_number"]) or "&ndash;",
    }
    taken = acts[acts["decision"] == "taken"]; notak = acts[acts["decision"] != "taken"]
    taken_rows = [[r_.action.replace("cost plus target", "cost plus the standard markup").replace("no path to target", "no path to the markup price"), r_.decided_by, f"Week {int(r_.engagement_week)}", effect.get(i, "")] for i, r_ in taken.iterrows()]
    taken_table = widths(B.data_table(["Action taken", "Decided by", "When", "Effect on the jobs or parts it touched"], taken_rows), [30, 14, 8, 48])
    not_rows = [[r_.action, r_.decision.capitalize(), r_.decided_by, declined_effect.get(i, ""), r_.reason] for i, r_ in notak.iterrows()]
    not_table = widths(B.data_table(["Action", "Decision", "By", "What it leaves in place", "Reason"], not_rows), [22, 9, 11, 20, 38])

    spread_rows = []
    for pn, x in by_part.sort_values("spread", ascending=False).iterrows():
        w = sp[(sp["part_number"] == pn) & sp["worst_job"]].iloc[0]
        spread_rows.append([pn, x["fam"], x["cust"], f"{int(x['jobs'])}", pct(x["worst"]), pct(x["med"]), pct(x["best"]), f"{x['spread'] * 100:.0f}", explain(w)])
    spread_table = widths(B.data_table(["Part", "Family", "Customer", "Jobs", "Worst", "Median", "Best", "Spread, pts", "The worst job"], spread_rows, right=[3, 4, 5, 6, 7]),
                          [7, 15, 15, 5, 7, 7, 7, 7, 30])

    toc = "".join([
        '<a href="#summary">Executive Summary</a>',
        '<a href="#distribution">1 &middot; The Margin Distribution</a>',
        '<a href="#anatomy">2 &middot; Actual against Estimate</a>',
        '<a class="sub" href="#run">2.1 Run hours</a>', '<a class="sub" href="#setup">2.2 Setup hours</a>',
        '<a class="sub" href="#revision">2.3 Labor with no routing cause</a>', '<a class="sub" href="#osp">2.4 Outside processing</a>',
        '<a class="sub" href="#scrap">2.5 Scrap and rework</a>', '<a class="sub" href="#material">2.6 Material</a>',
        '<a class="sub" href="#attribution">2.7 The overrun by cause</a>',
        '<a href="#samepart">3 &middot; Same Part, Different Outcomes</a>',
        '<a href="#inprogress">4 &middot; Jobs That Could Have Been Caught in Progress</a>',
        '<a href="#losses">5 &middot; The Jobs That Lost Money</a>',
        '<a href="#customers">6 &middot; Customer Profitability</a>',
        '<a href="#repricing">7 &middot; Repricing</a>',
        '<a href="#accuracy">8 &middot; Estimate Accuracy</a>',
        '<a href="#actions">9 &middot; Actions Decided</a>',
        '<a href="#appendix">Appendix</a>',
    ])

    two = el_sorted[:2]
    body = f"""
{B.section("summary", "Summary", "Executive Summary")}
<p>Across the {len(j25):,} jobs the shop released in {YEAR}, gross margin ("margin": price less the job's full manufacturing
cost, as a share of price) averaged <strong>{pct(m_mean)}</strong> a job, with a standard deviation of {m_sd * 100:.0f} points, and
<strong>{pct(neg.mean())}</strong> of jobs lost money; on revenue the year earned {pct(margin25, 1)} against the
{pct(est_m25, 1)} the jobs' estimates promised. Actual cost came in
<strong>{k(over)}</strong> over the jobs' estimates, {pct(over / est_total, 1)} {ms(bj)}: elements over estimate added {k(over_pos)} and
elements under estimate took back {k(-over_neg)}. Two cost elements carry most of the overrun: {el_sorted[0][1].lower()} ({k(el_sorted[0][2])}) and
{el_sorted[1][1].lower()} ({k(el_sorted[1][2])}). The largest named causes are revision work at one customer that was worked and never
billed ({k(ca['cause_revision_work_unbilled'])}) and titanium and Inconel jobs that ran well past their estimated run hours
({k(ca['cause_alloy_run_hours'])}); {k(ca['not_attributable'])} has no cause the data can name. The decisions the owner took during
the engagement act on causes that account for {k(addressed)}, {pct(addressed / gross)} of the {k(gross)} over estimate before offsets.
The rest has no cause the data can name, sits in vendor prices and estimates no decision has reached yet, or is a cost the
owner declined to act on; Section 9 lists the decisions both ways. What the job-level comparison showed, and the P&amp;L could
not, is that the year's {pct(margin25, 1)} was an average of jobs running from a loss to well over {pct(m_mean + m_sd)}, and that the
same part could do both in the same year.</p>

{B.section("distribution", "Section 1", "The Margin Distribution")}
<p>This is the view only job costing produces. The P&amp;L gave the shop one number for {YEAR}: the jobs' {k(rev25)} of
revenue earned a {pct(margin25, 1)} margin. The average job earned {pct(m_mean, 1)}, lower because the smaller jobs earn less,
and the histogram shows how widely jobs spread around it. The jobs' estimates promised {pct(est_m25, 1)} on the same
revenue and {pct(est_mean, 1)} for the average job; what separates the two is the subject of Section 2. The dashed line is the average job. The red bars left of zero
are the {int(neg.sum()):,} jobs that lost money. Each bar is labeled with its share of all jobs.</p>
{B.chart(f"{YEAR} Job Margin Distribution", chart_histogram(j25))}
<p>By revenue the losses are smaller than by count, because the jobs that lose money are smaller than average:
{pct(neg.mean())} of jobs but {pct(j25.loc[neg, 'price'].sum() / rev25)} of revenue.</p>
<p>The spread holds for repeat and new work alike, which is the first sign that no single pricing decision explains it.
Repeat parts on standing prices average {pct(by_type['repeat']['margin_on_price'].mean())} a job and new quoted work
{pct(by_type['new']['margin_on_price'].mean())}; on revenue, where the larger jobs count for more, they earn
{pct(by_type['repeat']['contribution'].sum() / by_type['repeat']['price'].sum())} and {pct(by_type['new']['contribution'].sum() / by_type['new']['price'].sum())}.
The two spread about as widely as each other, and each loses money on {pct((by_type['repeat']['contribution'] < 0).mean())}
and {pct((by_type['new']['contribution'] < 0).mean())} of its jobs. Both charts are on the same scale.</p>
{B.chart(f"{YEAR} Job Margin, by Job Type", chart_histogram_types(j25))}
<p>Job size separates the jobs more sharply than job type does. Lots under {C.SMALL_LOT_THRESHOLD} pieces average
{pct(size_avg[0])} a job and lose money on {pct(size_neg[0])} of them; lots of 25 to 100 pieces average
{pct(size_avg[1])} and lose money on {pct(size_neg[1])}, and lots over 100 pieces average {pct(size_avg[2])} and lose money on
{pct(size_neg[2])}. The setup costs the
same whatever the lot, so a small lot carries it over fewer pieces, and Section 2.2 shows the setup itself runs over on small
lots. The panels count jobs on a common scale, and each bar is labeled with its share of that band's jobs; bars under 1%
are left unlabeled.</p>
{B.chart(f"{YEAR} Job Margin, by Job Size", chart_histogram_sizes(j25))}
<p>Set against their estimates, the jobs came in lower more often than not. The chart shows each job's actual margin less its
estimated margin, in points. {pct((gap < 0).mean())} of jobs came in below their estimate, by a median of
{-gap[gap < 0].median() * 100:.0f} points; the average job missed by {-gap.mean() * 100:.1f} points. The misses are one-sided: the jobs
that beat their estimate did so by less, a median of {gap[gap >= 0].median() * 100:.0f} points. The red bars are the
{pct((gap < -0.20).mean())} of jobs that came in more than 20 points below their estimate. The gap includes the price movement
between quote and job as well as the jobs taking more than their estimates; Section 2 separates the two.</p>
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin", chart_margin_gap(j25))}
<p>Repeat parts miss their estimates by more than new work: an average of {-gap_rep.mean() * 100:.1f} points against
{-gap_new.mean() * 100:.1f}, with {pct((gap_rep < -0.20).mean())} of repeat jobs more than 20 points below against
{pct((gap_new < -0.20).mean())} of new ones. A repeat part's estimate comes from its original quote, so its gap carries every
movement in material, rates and standards since then; a new part's estimate is weeks old.</p>
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Type", chart_margin_gap_panels([("Repeat parts", by_type["repeat"]), ("New quoted work", by_type["new"])]))}
<p>Lot size separates the misses more sharply still. Lots under {C.SMALL_LOT_THRESHOLD} pieces missed their estimates by an average of
{-size_gap[0].mean() * 100:.1f} points, and {pct((size_gap[0] < -0.20).mean())} of them by more than 20; lots of 25 to 100 pieces missed by
{-size_gap[1].mean() * 100:.1f} and lots over 100 by {-size_gap[2].mean() * 100:.1f}. Small lots are where the setup runs over the
standard (Section 2.2), and that is what the estimate does not carry.</p>
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Lot Size", chart_margin_gap_panels([(lab, x) for (lab, _, _), x in zip(SIZE_BANDS, size_x)]))}
<p>The P&amp;L showed the shop one average. The jobs show a spread from losses to margins above {pct(mg.quantile(0.9))} on
the best tenth, and the average was hiding it. The rest of this report compares each job's actual cost with its estimate:
what the difference was made of, which of it could have been seen while the jobs were open, and what has been decided
about it.</p>

{B.section("anatomy", "Section 2", "Actual against Estimate")}
<p>Every {YEAR} job's actual cost is set against its estimate, element by element: material, setup hours, run hours, outside
processing, and scrap and rework, which the estimate does not carry. The estimate is first re-costed at the prices of the
job's own day (its hours, as the estimate carried them, at the pool rate of the job's year; its material at the part's need
at the job's issue price), so the labor elements compare hours and the material element compares usage. What prices moved
since the quote is a pricing question, taken up in Section 7.</p>
<p>In margin terms: the estimates on the jobs promised {pct(est_m25, 1)} on the year's revenue. Re-costed at the prices of each
job's own day they come to {pct(1 - est_total / rev25, 1)}, and the jobs earned {pct(margin25, 1)}. The first
{(est_m25 - (1 - est_total / rev25)) * 100:.1f} points are what material prices and labor rates moved between quote and job; the other
{((1 - est_total / rev25) - margin25) * 100:.1f} points are the jobs taking more than their estimates, and the rest of this section is
about those.</p>
<p>Across the {len(b):,} jobs, actual cost came to {k(act_total)} against a re-costed estimate of {k(est_total)}:
<strong>{k(over)} over</strong>, {pct(over / est_total, 1)} {ms(bj)}. The net figure hides the two sides: elements over estimate
added {k(over_pos)}, and elements under estimate took back {k(-over_neg)}. {el_sorted[0][1]} and {el_sorted[1][1].lower()} are the largest
elements over estimate, followed by {el_sorted[2][1].lower()}.</p>
{B.chart(f"Actual Cost over Estimate on the {YEAR} Jobs, by Element", chart_waterfall([lab.replace('Outside ', 'Outside\n').replace(' and ', ' and\n') for _, lab in ELEMENTS], [el[c] for c, _ in ELEMENTS], "Net over\nestimate"))}
{el_table}

{B.section("run", "Section 2.1", "Run hours over estimate")}
<p>Run hours are over estimate almost everywhere a little, and in titanium and Inconel a lot. The little is stoppages: a
job's run hours include the alarms and in-operation idle the machines record, {pct(stop_share)} of machine time, and the routing
standard carries no allowance for them. Standards set generously at first quote absorb part of it (before the refresh they sat
a median {pct(std_over)} above the measured cycle), so the median job runs {run_rest:.2f}&times; its estimated run hours. Jobs in the two alloys ran
<strong>{run_alloy:.2f}&times;</strong> their estimated run hours in {YEAR} against {run_rest:.2f}&times; for every other material,
and the gap shows on every cell that cuts them, which says the estimate is wrong rather than the floor: the
estimator's speeds and feeds for the two alloys were never checked against a measured cycle. Across the {YEAR} jobs the
excess over the shop's normal overrun comes to {alloy_hours:,.0f} hours and <strong>{k(ca['cause_alloy_run_hours'])}</strong> across
{ca_jobs['cause_alloy_run_hours']:,} jobs {ms(bj[bj['job_id'].isin(b.loc[b['cause_alloy_run_hours'] > 1, 'job_id'])])}. The action is to validate the
two alloys' speeds and feeds against the measured cycles.</p>
{sub(f"Titanium and Inconel Run Hours against Estimate by Cell, {YEAR} (median of jobs)")}
{alloy_table}
<p>Two further causes sit in run hours. Parts whose routing standard was below the cycle the machines measured ran over
the estimate by the difference until the standard was refreshed: {k(ca['cause_standard_below_cycle'])} on {ca_jobs['cause_standard_below_cycle']:,} jobs.
And the two oldest vertical mills, installed in {C.INSTALL_YEAR['VMC-01']} and {C.INSTALL_YEAR['VMC-02']}, run the same program
{older_factor:.2f}&times; as long as the newer ones on the {len(age_vmc):,} parts that ran on both; a job the schedule put on one of
them carried that difference, {k(ca['cause_older_machine'])} on {ca_jobs['cause_older_machine']:,} jobs.</p>

{B.section("setup", "Section 2.2", "Setup hours over estimate")}
<p>Setup overruns concentrate in small lots on the mill-turn and 5-axis cells. Measured at the cell against the routing
standard, setup on lots under {C.SMALL_LOT_THRESHOLD} pieces runs <strong>{setup_small:.2f}&times;</strong> the standard against
{setup_large:.2f}&times; on larger lots: the standard assumes a repeat setup and a small lot gets a first-article setup every
time. Margin by lot size shows the result, falling off sharply below {C.SMALL_LOT_THRESHOLD} pieces rather than gradually.</p>
{B.chart(f"Margin by Lot Size, with Setup Hours against Standard on the Mill-turn and 5-axis Cells, {YEAR}", chart_lot(lot))}
<p>Across the {YEAR} jobs the setup excess on those cells comes to <strong>{k(ca['cause_small_lot_setup'])}</strong> across {small_jobs}
jobs {ms(bj[bj['job_id'].isin(b.loc[b['cause_small_lot_setup'] > 1, 'job_id'])])}; the first run after a revision adds
{k(ca['cause_first_run_after_revision'])} on {ca_jobs['cause_first_run_after_revision']:,} jobs, the same first-article effect on a
part the shop already knew. The action is to quote small lots at the measured first-article setup.</p>

{B.section("revision", "Section 2.3", "Labor hours over estimate with no routing cause")}
<p>One customer's jobs run over on labor across every part family they buy. {co_name} jobs averaged
<strong>{co_per_job:,.1f} labor hours over estimate per job</strong> in {YEAR}, against {oth_per_job:,.1f} for every other customer;
in total they ran {co_ratio:.2f}&times; their estimated hours against {oth_ratio:.2f}&times;. Nothing in the routing explains it: the
excess shows on every part family the customer buys. The explanation is on the customer record. {co_name} issued
{int(cust_rec.loc[co_id, 'change_order_count_12m'])} revision changes in the last twelve months against a median of
{int(d['customers']['change_order_count_12m'].median())} across the book, and each one adds programming and first-article time
after release that was never billed.</p>
{sub(f"{co_name}: Labor Hours against Estimate by Part Family, {YEAR}")}
{co_table}
<p>Across the {YEAR} jobs the excess comes to {co_hours:,.0f} hours and <strong>{k(ca['cause_revision_work_unbilled'])}</strong> across
{ca_jobs['cause_revision_work_unbilled']:,} jobs {ms(bj[bj['job_id'].isin(b.loc[b['cause_revision_work_unbilled'] > 1, 'job_id'])])}. The action is to bill
revision work under the contract's change-order clause.</p>

{B.section("osp", "Section 2.4", "Outside processing over estimate")}
<p>Outside processing over estimate has three parts. The plating vendor is the clearest case: it raised its prices in steps while the estimator's spreadsheet kept the old rate, so the gap between invoice and
estimate widened quarter by quarter: on jobs whose only outside process is plating, the invoice ran
{plating_idx.loc[plating_idx.index.year == YEAR, 'r'].median():.2f}&times; the estimate through {YEAR}, and fell back to
{plating_idx['r'].iloc[-1]:.2f}&times; once the quoting module carried the vendor's current price.</p>
{B.chart("Plating: Invoice over Estimate by Quarter Released, Jobs Plated and Nothing Else", plating_png)}
<p>On the {YEAR} plated jobs that cost {k(ca['cause_plating_rate'])}. Other vendors' invoices above the estimate add more in
total, {k(ca['cause_vendor_price'])}, but thinly: a median of {money(b.loc[b['cause_vendor_price'] > 1, 'cause_vendor_price'].median())} a job across
{ca_jobs['cause_vendor_price']:,} jobs, the drift of vendor prices since the job was quoted. The third part, {k(osp_alloc)}, is outside
processing that could never be tied to a job and was spread over the month's jobs so the ledger reconciles; it is real
money, but where it landed is an allocation, not a measurement. The action is to carry current vendor pricing in the
quoting module; with a job number now required on every outside-processing purchase order, the comparison runs itself.</p>

{B.section("scrap", "Section 2.5", "Scrap and rework")}
<p>Scrap material and rework hours cost the {YEAR} jobs {k(el['c_scrap_rework'])}, led by {sr.index[0].lower()}
({k(sr.iloc[0])}) and {sr.index[1].lower()} ({k(sr.iloc[1])}). The figure is a floor: before the engagement most rework was
posted as run time ({t6_n:,} events the audit found), so part of it sits in the run-hours line above and can only be
partly separated after the fact.</p>

{B.section("material", "Section 2.6", "Material")}
<p>Material usage is small, as it should be once issues are costed at their own price: {k(el['c_material'])} net across the
{YEAR} jobs. What remains is the remnant and mis-issue cases the audit corrected ({t8_n:,} jobs that received another
job's bar or never had theirs issued, brought back to the part's need).</p>

{B.section("attribution", "Section 2.7", "The overrun by cause")}
<p>The same comparison, assigned to causes. Each element's overrun on each job goes to a named cause where the data shows
one, sized as the excess over what a normal job of the year shows, and to "not attributable" where it does not. Elements
that came in under their estimate are kept as an offset, so the table adds back to the net: the causes come to {k(gross)}
over estimate before the {k(-ca['offset_elements'])} of elements under estimate bring it to {k(over)}. It is a fact about {YEAR},
not a promise about next year: the column does not total to anything recoverable. The cost-measured column is the coverage
of the jobs behind each row; the outside processing allocated from the ledger is shown at 0% because it is an allocation.</p>
{B.chart("Actual Cost over Estimate by Cause", chart_hbar([lab for _, lab in CAUSES], [ca[c] for c, _ in CAUSES], f"Over estimate on the {YEAR} jobs"))}
{cause_table}

{B.section("samepart", "Section 3", "Same Part, Different Outcomes")}
<p>For the {len(by_part):,} repeat parts with three or more jobs in {YEAR}, the gap between each part's best and worst job
has a median of <strong>{by_part['spread'].median() * 100:.0f} points</strong>; on {pct((by_part['spread'] >= 0.20).mean())} of them it is
20 points or more. Same part, same customer, same standing price, different outcome.</p>
{B.chart(f"Spread of Job Margin within Each Repeat Part, {YEAR}", chart_spread(by_part['spread']))}
{ex_html}
<p>For quoting this means one thing: a part's price has to cover its worst realistic job, not its average. A standing
price set on the typical lot on the newer machine loses money whenever the release is small, the schedule puts the job on
an older mill or the customer revises the part, and each of those happens several times a year on the same part numbers.</p>

{B.section("inprogress", "Section 4", "Jobs That Could Have Been Caught in Progress")}
<p>The job in progress screen flags a job when its actual to date runs more than {pct(0.15)} over its estimate to date
on labor hours, operation by operation, or on material at issue. Replayed over the {len(r25):,} jobs completed from the
{YEAR} releases, <strong>{len(flagged):,}</strong> would have been flagged, and <strong>{len(open_):,}</strong> of them while there
was still something to do: with operations left and {C_ACT} or more days before the job shipped. {pct((flagged['flag_op_index'] == 1).mean())} of
the flags fire at the first operation, where setup overruns show, {pct(((flagged['flag_op_index'] > 1) & (flagged['flag_op_index'] < flagged['ops'])).mean())} at a
middle operation and {pct((flagged['flag_op_index'] >= flagged['ops']).mean())} at the last, when only the next quote can change.</p>
{B.chart(f"Where on the Routing the Flag Fired, {YEAR} Jobs", chart_replay(r25))}
<p>Grouped by what the shop could have done with the warning: on {co_name}'s jobs a change order could have been raised
before the work was done; on jobs that went on to ship late, a flag at the first operation leaves time to re-sequence
rather than expedite; on small lots and first runs after a revision the quantity or scope could have been discussed with
the customer. The three groups carried {k(first3['over'].sum())} of cost over estimate across {int(first3['jobs'].sum()):,} jobs. The
rest were flagged too late or had no lever while open. The change-order figure is all cost over estimate on the jobs flagged
while open, a different measure from the revision excess in Section 2.3.</p>
{lev_table}
<p>This is what the shop could have known while the jobs were open, not what it would have recovered. A flag is a
conversation, and the conversation does not always go the shop's way.</p>

{B.section("losses", "Section 5", "The Jobs That Lost Money")}
<p><strong>{len(loss):,}</strong> jobs lost money in {YEAR}, {money(-loss['contribution'].sum())} in total {ms(lj)}. Set against their
estimates, the losses are mostly not a pricing story: only {len(est_loss)} of the {len(loss):,} were estimated to lose money before they
started. The other {len(est_gain):,} were estimated to make money, a median estimated margin of {pct(est_gain['estimated_margin_on_price'].median())},
and lost it in the job; they carry {pct(est_gain['contribution'].sum() / loss['contribution'].sum())} of the loss. Each job carries
the driver the reporting layer assigns by rule, the same rules the Job Variance report applies to every job (appendix), and
the action the driver maps to: correct the routing standard, correct the quote, bill the change order, reprice the part, fix
the process, or accept it as a one-off. The top 25 are below; the full list is in the appendix. This is the list the owner and
estimator work from, and it matches what they see in the ERP.</p>
{sub("Loss-making Jobs by Action")}
{act_table}
{sub(f"The 25 Largest Losses, {YEAR}")}
{loss_table}
<p>Of the 25 largest losses, {int((loss.head(25)['primary'] == 'Unbilled revision work').sum())} are unbilled revision work, almost all at {co_name};
{int((loss.head(25)['primary'] == 'Priced below estimated cost').sum())} were priced below their own estimated cost, {cu.loc[neg_id, 'name']}' jobs among them;
{int((loss.head(25)['primary'] == 'Routing standard').sum())} trace to a routing standard the part's jobs keep overrunning,
{int(((loss.head(25)['primary'] == 'Routing standard') & loss.head(25)['material_spec'].isin(ALLOYS)).sum())} of them in titanium or Inconel; {int((loss.head(25)['primary'] == 'Not attributable').sum())} fire no rule with a dominant share and are accepted as one-offs.</p>

{B.section("customers", "Section 6", "Customer Profitability")}
<p>Revenue is concentrated: in {YEAR} the top customer was {pct(conc[1][0])} of revenue and {pct(conc[1][1])} of gross profit, the
top five {pct(conc[5][0])} and {pct(conc[5][1])}, the top ten {pct(conc[10][0])} and {pct(conc[10][1])}. Margin by customer ranges
from {pct(top15['margin'].min())} to {pct(top15['margin'].max())} across the top fifteen, and {int((top15['margin'] < top15['est_margin'] - 0.005).sum())} of
the fifteen earned less than their estimates promised.</p>
{B.chart(f"Estimated Margin and Margin, Top 15 Customers by Revenue, {YEAR}", chart_customers(top15.set_index(top15.index)))}
{cust_table}
<p>{co_name} is the account from Section 2.3: its jobs ran {co_per_job:,.1f} labor hours over estimate each, and it earned
{pct(co_m)} against {pct(margin25)} for the shop. {cu.loc[neg_id, 'name']} {'lost money' if cu.loc[neg_id, 'margin'] < 0 else 'earned the least'}:
{pct(cu.loc[neg_id, 'margin'], 1)} on {k(cu.loc[neg_id, 'rev'])} across {int(cu.loc[neg_id, 'jobs'])} jobs, almost all of it new work won in the last
two years. The jobs were priced at or under the shop's own estimate (a median estimated margin of {pct(neg_jobs['estimated_margin_on_price'].median(), 1)}),
so there was no margin to absorb any overrun; they are listed below with the driver assigned to each.</p>
{sub(f"{cu.loc[neg_id, 'name']}: Jobs Released in {YEAR}")}
{negj_table}

{B.section("repricing", "Section 7", "Repricing")}
<p><strong>Exposure.</strong> At today's material prices, pool rates and measured standards, {len(bq):,} of the {len(q):,} repeat parts
({pct(len(bq) / len(q))}) have a standing price below current cost plus the shop's standard {pct(TARGET)} markup (the markup price), carrying {pct(bq['rev'].sum() / (q['standing_price'] * q['annual_volume']).sum())}
of repeat revenue. The gap is modest on most of them: a median of {pct(bq['gap'].median(), 1)}, with nine in ten under
{pct(bq['gap'].quantile(0.9))}; {int(q['below_cost'].sum())} sit below cost outright. At current volume the exposure is
<strong>{k(exposure)} a year</strong>, and the own-product line adds {k(own_exp)}: together {pct((exposure + own_exp) / rev25, 1)}
of {YEAR} revenue. Current cost rests on measured standards on {pct(refreshed_share)} of the parts. The gap is what the
annual across-the-board letters ({min(letters):.1%} to {max(letters):.1%} a year) missed on the parts whose inputs moved most:
since the last quote, current cost rose a median {pct(cost_move(bq))} on the parts below the markup price against {pct(cost_move(above_q))}
on the rest, while the letters raised the standing prices of those parts a median {pct(letters_move(bq))}.</p>
<p><strong>What is defensible.</strong> In the shop's experience, as the owner and the controller described it, a routine annual
increase of 3 to 5% is accepted without discussion. A larger increase can land selectively, part by part, when the cost
driver is documented, and most often that driver is material passed through at what it now costs. Beyond that the
relationship risk is real, and the owner decides.</p>
<p><strong>Decisions.</strong> The controller and the owner decided every part below the markup price in weeks 7 to 9 on that basis: a gap
within the routine range was repriced; a larger gap was repriced where material or outside processing drove it and the
movement could be shown part by part, and held otherwise with the reason recorded; a large gap on a small part was exited,
and on the {len(two_step)} largest programs the increase was taken in two steps, half now and the balance at the blanket renewal.</p>
{dec_table}
{sub("Reasons Recorded for the Parts Held")}
{reason_table}
{sub("The Largest Gaps and the Decisions Taken")}
{rp_table}
<p><strong>What job costing added.</strong> Not the gap itself: a current-cost calculation gives that. What it added is the
selectivity. For every part the queue shows what moved since the last quote (material, the labor rate, the measured
standard, outside processing), and that evidence is what lets a targeted increase land where an across-the-board letter
does not. Where material or outside processing moved most, the shop could show the customer why, and most of those
parts were repriced.</p>
{drv_table}
{sub("Own Products")}
<p>The fourteen own products sell from a list price set at launch over a standard cost that was never revised. Against
current cost plus the markup the list sits a median {pct(-own_gap.median())} short, from {pct(-own_gap.max())} to {pct(-own_gap.min())};
{int(own['below_cost_at_list'].sum())} of the fourteen sells below cost at list. The list moves to current cost plus the markup at the next
price list (Section 9).</p>
{own_table}

{B.section("accuracy", "Section 8", "Estimate Accuracy")}
<p>Estimate accuracy is the distribution of actual over estimate by cost element, for the {YEAR} history (estimates
backfilled from the quoting module) and for the completed jobs of the engagement period (estimate carried on the job).
This is the feedback loop the shop never had: the estimator can now see, element by element, whether the quotes were
right.</p>
{B.chart(f"Actual over Estimate by Element, {YEAR} History against the Engagement Period", acc_png)}
{acc_table}
<p><strong>Material</strong> moved to {acc[('Material', 'eng')][1]:.2f} and its spread closed because the estimate now carries the
price of the day rather than the spreadsheet's price list. <strong>Setup hours</strong> have not moved yet (a median of
{e_set[1]:.2f} against {h_set[1]:.2f}): {pct(pre_refresh)} of the engagement-period jobs were estimated before their part's refreshed
standard took effect, and small lots still run over, which is what action A6 is for. <strong>Run hours</strong> narrowed from
{h_run[0]:.2f} to {h_run[2]:.2f} to {e_run[0]:.2f} to {e_run[2]:.2f} because repeat parts are now estimated on the measured cycle.
The median stays at {e_run[1]:.2f} for a reason the refresh cannot fix: the measured cycle is time in cycle, while a job's
run hours also carry the alarms and in-operation idle the machines record, {pct(stop_share)} of machine time. The standard
needs an allowance for them. <strong>Labor and burden</strong>
tightened further because the estimate and the actual now use the same pool rate. <strong>Outside processing</strong> moved to
{acc[('Outside processing', 'eng')][1]:.2f} because the quoting module carries the vendors' current prices.</p>
<p>By estimator, the gap between the estimated margin and the margin runs {abs(est['margin_on_price'] - est['estimated_margin_on_price']).min() * 100:.0f}
to {abs(est['margin_on_price'] - est['estimated_margin_on_price']).max() * 100:.0f} points, about the same for all three: the shortfall is in what the
estimates carry, not in who writes them. By quote year, the margin on new work has not improved on its own, from
{pct(qy['m'].iloc[0])} on work quoted in {int(qy.index[0])} to {pct(qy['m'].iloc[-1])} on work quoted in {int(qy.index[-1])}; that is
what the feedback loop is for.</p>
{sub("Margin by Estimator, All Jobs")}
{est_table}
{sub("New Quoted Work by Year Quoted")}
{qy_table}

{B.section("actions", "Section 9", "Actions Decided")}
<p>The actions the owner took on these findings, with their effect on the jobs or parts they touched. Effects are
measured on engagement-period jobs where there are enough of them, and otherwise stated as decided.</p>
{sub("Actions Taken during the Engagement")}
{taken_table}
<p>The actions the owner declined or deferred, and why. They are as much a part of the result as the actions taken.</p>
{sub("Actions Declined or Deferred")}
{not_table}
<p>The two tables are not added up and nothing here is projected forward.</p>

{B.section("appendix", "Appendix", "Method, Definitions and Detail")}
<p><strong>Job cost.</strong> Material at the issued price, corrected to the part's need where the audit found another job's
bar or none; labor as hours at the work center's pool rate (labor rate &times; attended ratio + burden); outside processing
at the invoiced price, with lines that could not be tied to a job allocated over the month's jobs; scrap at the job's
material cost. CNC hours come from the machine-monitoring feed on every monitored cell, not from the clock record.</p>
<p><strong>Measured share.</strong> The share of a job's cost resting on a transaction (a machine interval assigned to the job,
a clock record, a scan, an issue, a purchase order) rather than on the routing standard, an allocated ledger residual or a
record flagged unrepairable. Stated beside every dollar figure as the coverage of the jobs behind it.</p>
<p><strong>Margin.</strong> Margin is gross margin: price less the job's cost (material, labor and burden at the work center's
pool rate, outside processing and scrapped material), as a share of price. Estimated margin is the same measure on the job's
estimate, and a job loses money when its margin is below zero. The shop prices as a markup on cost: its standard
{pct(TARGET)} markup, which the repricing queue in Section 7 uses, prices a job at cost &times; {1 + TARGET:.2f}, a margin of
{TARGET:.2f} &divide; {1 + TARGET:.2f} = {pct(TM, 1)}. The distribution in Section 1 shows the average and one standard deviation either
side, over all jobs.</p>
<p><strong>Actual against estimate.</strong> Each job's actual cost less its estimate, with the estimate re-costed at the
prices of the job's own day: its hours at the pool rate of the job's year, its material at the job's issue price. The
difference splits exactly into the elements: material, setup hours, run hours, outside processing, and scrap and rework,
which the estimate does not carry. A cause is sized as the
excess over what a normal {YEAR} job shows: titanium and Inconel run hours beyond the median run ratio of other materials;
small-lot and first-run setup beyond the median setup ratio of larger lots; {co_name}'s hours beyond the shop's median
labor ratio; the older mills' run hours times one less the ratio of newer to older cycle; standards below the measured
cycle by the gap in the refresh log, on jobs estimated before the refresh.</p>
<p><strong>Drivers.</strong> Section 5 assigns each job the driver the reporting layer's rules give it, the same rules the Job Variance
report shows in the ERP: routing standard (run hours over 1.15&times; the estimate, and the part's other jobs in the trailing
twelve months over too); small-lot setup (setup over 1.30&times; on a lot under {C.SMALL_LOT_THRESHOLD} pieces); unbilled revision work (labor over
estimate, a revision change after release and no change order billed); vendor rate (outside processing over 1.10&times; the
estimate); scrap and rework (over 5% of estimated cost); material (over the estimate by more than 10%); priced below
estimated cost (the job's own estimate showed a loss, sized as that estimated loss). Where several fire, the largest dollar variance
is the driver; where none fires, or the largest carries under 40% of the job's overrun, the job is not attributable. The
drivers are rules for a standing report and the Section 2 causes are an analysis of one year, so the two are close but
not identical.</p>
<p><strong>In-progress flag.</strong> A job is flagged at the first operation where its labor hours to date exceed the
estimate to date by more than {pct(0.15)} and by at least two hours, or at the first material issue if material exceeds the
estimate by more than {pct(0.15)} and $150. The estimate to date is the routing standard for each operation, scaled so the
operations sum to the job's estimated hours. A flag is actionable when it fires before the last operation and {C_ACT} or
more days before the job ships.</p>
{sub(f"All Loss-making Jobs, {YEAR}")}
{loss_all}
{sub(f"Within-part Spread, Repeat Parts with Three or More Jobs in {YEAR}")}
{spread_table}
"""
    return body, toc


def explain(w):
    """What distinguishes a part's worst job, in words."""
    bits = []
    if w.first_after_revision:
        bits.append(f"first run of revision {w.revision}")
    if w.change_order_customer:
        bits.append("revision work at the change-order customer")
    if pd.notna(w.lot_vs_median) and w.lot_vs_median <= 0.6:
        bits.append(f"{int(w.quantity)} pieces against a usual {int(w.part_median_lot)}")
    if pd.notna(w.older_vmc_share) and w.older_vmc_share >= 0.5:
        bits.append("ran on an older vertical mill")
    return "; ".join(bits) if bits else "nothing in the data"


def pick_examples(sp):
    """One part each where lot size, the machine, a revision, and nothing in the data explain the spread."""
    out, used = [], set()
    g = {pn: x for pn, x in sp.groupby("part_number")}

    def best(cond):
        cands = []
        for pn, x in g.items():
            if pn in used:
                continue
            w = x[x["worst_job"]].iloc[0]; b_ = x[x["best_job"]].iloc[0]
            if cond(x, w, b_) and x["margin_on_price"].between(-1.5, 0.8).all():
                cands.append((x["part_margin_spread"].iloc[0], pn))
        return max(cands)[1] if cands else None

    plain = lambda w: not w.first_after_revision and not w.change_order_customer

    def best_machine():
        # parts that ran on both an older and a newer vertical mill at similar lots: the one where the jobs on the
        # older mills earned least against the jobs on the newer ones, with the run hours to show why
        cands = []
        for pn, x in g.items():
            if pn in used or x["first_after_revision"].any() or x["change_order_customer"].any():
                continue
            if not (x["lot_vs_median"].between(0.6, 1.6).all() and x["run_hours_ratio"].between(0.6, 2.0).all()):
                continue
            old = x[x["older_vmc_share"].fillna(0) >= 0.8]; new = x[(x["older_vmc_share"].fillna(1) < 0.1) & (x["vmc_run_hours"].fillna(0) > 0)]
            if len(old) == 0 or len(new) == 0:
                continue
            if old["run_hours_ratio"].median() < 1.2 * new["run_hours_ratio"].median():
                continue
            cands.append((new["margin_on_price"].median() - old["margin_on_price"].median(), pn))
        return max(cands)[1] if cands else None
    oldv = lambda w: pd.notna(w.older_vmc_share) and w.older_vmc_share >= 0.5
    specs = [
        ("lot", lambda x, w, b_: plain(w) and w.lot_vs_median <= 0.5 and not oldv(w) and x["part_margin_spread"].iloc[0] > 0.15),
        ("machine", None),
        ("revision", lambda x, w, b_: w.first_after_revision and not w.change_order_customer and 0.6 <= w.lot_vs_median <= 1.6),
        ("none", lambda x, w, b_: plain(w) and x["lot_vs_median"].between(0.75, 1.3).all() and (x["older_vmc_share"].fillna(0) < 0.1).all()
         and not x["first_after_revision"].any() and not x["change_order_customer"].any() and x["part_margin_spread"].iloc[0] > 0.15
         and x["run_hours_ratio"].between(0.6, 2.0).all() and x["setup_hours_ratio"].fillna(1).between(0.3, 2.5).all() and len(x) >= 3),
    ]
    for kind, cond in specs:
        pn = best_machine() if kind == "machine" else best(cond)
        if pn is None:
            continue
        used.add(pn)
        x = g[pn]; w = x[x["worst_job"]].iloc[0]; b_ = x[x["best_job"]].iloc[0]
        fam, cust = w.part_family.lower(), w.customer_name
        spread = x["part_margin_spread"].iloc[0] * 100
        if kind == "lot":
            text = (f"<strong>Lot size.</strong> {pn} ({w.part_family.lower()}, {cust}) ran {len(x)} jobs in {YEAR} with a "
                    f"{spread:.0f}-point spread. The worst job was a release of {int(w.quantity)} pieces against a usual {int(w.part_median_lot)}: "
                    f"the setup is the same whatever the lot, so a small release carries it over fewer pieces and earned {pct(w.margin_on_price)} "
                    f"against {pct(b_.margin_on_price)} on the best job.")
            title = f"{pn}: Lot Size"
        elif kind == "machine":
            old = x[x["older_vmc_share"].fillna(0) >= 0.8]; new = x[(x["older_vmc_share"].fillna(1) < 0.1) & (x["vmc_run_hours"].fillna(0) > 0)]
            words = {1: "one job", 2: "two jobs", 3: "three jobs", 4: "four jobs"}
            n_old = words.get(len(old), f"{len(old)} jobs"); n_new = words.get(len(new), f"{len(new)} jobs")
            text = (f"<strong>The machine used.</strong> {pn} ({w.part_family.lower()}, {cust}) ran {len(x)} jobs of {int(x['quantity'].min())} to "
                    f"{int(x['quantity'].max())} pieces. The schedule put {n_old} on the two oldest vertical mills, where the run hours came in at "
                    f"{old['run_hours_ratio'].median():.2f}&times; the estimate and the margin at {pct(old['margin_on_price'].median())}; {n_new} on the newer "
                    f"mills ran at {new['run_hours_ratio'].median():.2f}&times; and earned {pct(new['margin_on_price'].median())}. Run hours against the estimate "
                    f"do not depend on the lot, so the difference in them is the machine; the lot sizes account for the rest of the gap.")
            title = f"{pn}: The Machine Used"
        elif kind == "revision":
            text = (f"<strong>The first run after a revision.</strong> {pn} ({cust}) moved from revision {x.sort_values('release_date')['revision'].iloc[0]} to "
                    f"{w.revision} during {YEAR}. The first job on the new revision took {w.setup_hours_ratio:.2f}&times; its estimated setup hours while the "
                    f"program was proved out and the first article inspected, and earned {pct(w.margin_on_price)}; the jobs either side of it earned "
                    f"{pct(x.loc[~x['worst_job'], 'margin_on_price'].median())} at the median.")
            title = f"{pn}: The First Run after a Revision"
        else:
            text = (f"<strong>Nothing in the data.</strong> {pn} ({cust}) ran {len(x)} jobs at similar quantities, on the same revision, with no "
                    f"change orders and no time on the older mills, and still spread {spread:.0f} points: the worst earned {pct(w.margin_on_price)}, "
                    f"the best {pct(b_.margin_on_price)}. The job records show where the hours went, not why, and this report does not "
                    f"guess.")
            title = f"{pn}: No Explanation in the Data"
        out.append({"text": text, "title": title, "jobs": x})
    return out


def run():
    d = gather()
    body, toc = build(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = B.page("Margin Analytics Diagnostic: Job Costing", "", toc, body)
    OUT.write_text(html, encoding="utf-8")
    print(f"Margin diagnostic written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
