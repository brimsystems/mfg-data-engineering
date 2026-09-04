"""Job margin analytics diagnostic -> docs/reports/margin_diagnostic.html

About the business, not the data: how margin is spread across the shop's jobs and
why, from the corrected job cost. The report attributes and does not project: the
2025 overrun is split by cost element on the jobs themselves, what a lever was
worth is what the 2025 jobs would have earned with it applied, and nothing is
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
RAW = REPO / "data_source" / "raw"
OUT = REPO / "docs" / "reports" / "margin_diagnostic.html"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

YEAR = C.ANALYSIS_YEAR
TARGET = C.TARGET_MARKUP
TM = TARGET / (1 + TARGET)                  # the standard markup as a margin
C_ACT = 3                                   # the dbt var inprogress_actionable_days
THRESHOLD = 0.15                            # the dbt var inprogress_threshold
CELL = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horizontal mills", "VMC": "Vertical mills",
        "MTN": "Mill-turn", "FAX": "5-axis", "SAW": "Saw", "MDP": "Manual drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
# the cost elements of actual against estimate, with the column each sits in on the shortfall mart
ELEMENTS = [("c_run", "Run hours"), ("c_outside", "Outside processing"), ("c_setup", "Setup hours"),
            ("c_scrap_rework", "Scrap and rework"), ("c_material", "Material")]


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
        return "n/a"
    return f"&minus;${abs(x):,.{d}f}" if x < 0 else f"${x:,.{d}f}"


def k(x):
    """Compact money: $116K, $2.0M."""
    a = abs(x)
    s = f"${a/1e6:.2f}M" if a >= 1e6 else f"${a/1e3:.0f}K" if a >= 1e3 else f"${a:,.0f}"
    return ("&minus;" if x < 0 else "") + s


def pct(x, d=0):
    if pd.isna(x):
        return "n/a"
    return f"{round(x * 100, d) + 0.0:.{d}f}%".replace("-", "&minus;")


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
    d["jobs"] = j
    d["j25"] = j[j["release_year"] == YEAR].copy()
    s = _pq("mart_job_shortfall")
    d["short"] = s
    d["s25"] = s[s["release_year"] == YEAR].copy()
    for name, mart in [("driver", "mart_job_driver"), ("replay", "mart_inprogress_replay"), ("thresholds", "mart_inprogress_threshold_replay"),
                       ("family", "mart_margin_by_family_rate_basis"), ("release", "mart_release_setup_charge"), ("spread", "mart_part_margin_spread"),
                       ("queue", "mart_repricing_queue"), ("own", "mart_own_products"), ("est", "mart_margin_by_estimator"),
                       ("estimate", "int_estimate_by_job"), ("osp", "int_osp_by_job"), ("ops", "int_job_op_progress"),
                       ("machine", "int_machine_hours_by_job"), ("actions", "mart_engagement_actions"), ("coverage", "mart_coverage_weekly"),
                       ("rework_as_run", "dq_rework_as_run")]:
        d[name] = _pq(mart)
    d["std_log"] = pd.read_csv(RAW / "remediation" / "standard_update_log.csv")
    d["rate_pools"] = pd.read_csv(RAW / "remediation" / "rate_pools.csv")
    d["customers"] = pd.read_csv(RAW / "erp" / "customers.csv")
    d["quotes"] = pd.read_csv(RAW / "erp" / "quotes.csv", parse_dates=["quote_date"])
    return d


# ── charts ──────────────────────────────────────────────────────────────────
def _hist(ax, m, color, bins, fs, ymax=None, points=False, red_below=0.0):
    """One margin histogram: bars below zero red, the rest in the series color, each labeled with
    its number of jobs, and the average dashed."""
    bins = np.round(bins, 6)
    w = bins[1] - bins[0]
    n, edges, patches = ax.hist(m.clip(bins[0], bins[-1] - 1e-9), bins=bins, color=color, edgecolor="white", linewidth=0.6)
    for pch, left, cnt in zip(patches, edges[:-1], n):
        if left + w <= red_below + 1e-9:
            pch.set_facecolor(B.ACCENT_RED)
        if cnt:
            ax.text(left + w / 2, cnt, f"{int(cnt):,}", ha="center", va="bottom", fontsize=fs, zorder=5,
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


SIZE_BANDS = [("Under 25 pieces", 0, 24), ("25 to 100 pieces", 25, 100), ("Over 100 pieces", 101, 10 ** 9)]


def chart_histogram_sizes(j25):
    import matplotlib.pyplot as plt
    bins = np.round(np.arange(-0.40, 0.601, 0.10), 6)
    peak = max(np.histogram(j25[j25["quantity"].between(lo, hi)]["margin_on_price"].clip(bins[0], bins[-1] - 1e-9), bins=bins)[0].max()
               for _, lo, hi in SIZE_BANDS)
    ymax = np.ceil(peak * 1.18 / 100) * 100
    fig, axes = plt.subplots(1, 3, figsize=(B.CHART_W, 3.5), sharey=True)
    for ax, (lab, lo, hi) in zip(axes, SIZE_BANDS):
        x = j25[j25["quantity"].between(lo, hi)]
        _hist(ax, x["margin_on_price"], B.LIGHT_BLUE, bins, 6.5, ymax=ymax)
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
        _hist(ax, g, B.LIGHT_BLUE, bins, 6.5, ymax=ymax, points=True, red_below=-0.20)
        ax.set_title(f"{lab} ({len(g):,} jobs)", fontsize=9.5, fontweight="bold")
        ax.tick_params(labelsize=8)
        ax.yaxis.set_tick_params(labelleft=True)
        ax.set_xlabel("Actual less estimated margin, points", fontsize=8.5)
    axes[0].set_ylabel("Jobs")
    fig.tight_layout()
    return B.b64(fig)


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



def _kfmt(v, _=None):
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:,.0f}K"
    return ("−" if v < 0 else "") + s


def chart_pareto(rows):
    """Gross over estimate by element, largest first, with what came in under estimate drawn below
    the axis and the net marked. `rows` are (label, [(part label, amount, style)], [(part label,
    amount, style)] for what came in under, net)."""
    fig, ax = B.make_fig(4.6)
    styles = {"solid": dict(color=B.ACCENT_RED), "light": dict(color="#E58A8A"),
              "hatched": dict(facecolor="white", edgecolor=B.ACCENT_RED, hatch="////", linewidth=1.0),
              "under": dict(color=B.DARK_BLUE), "under hatched": dict(facecolor="white", edgecolor=B.DARK_BLUE, hatch="////", linewidth=1.0)}
    seen = {}
    top = max(sum(a for _, a, _ in parts) for _, parts, _, _ in rows)
    for i, (lab, parts, under, net) in enumerate(rows):
        bottom = 0.0
        for plab, amt, style in parts:
            h = ax.bar(i, amt, bottom=bottom, width=0.6, **styles[style])
            if plab and plab not in seen:
                seen[plab] = h
            bottom += amt
        ax.text(i, bottom + top * 0.02, _kfmt(bottom), ha="center", va="bottom", fontsize=9)
        low = 0.0
        for plab, amt, style in under:
            if amt < 0:
                u = ax.bar(i, amt, bottom=low, width=0.6, **styles[style])
                seen.setdefault(plab, u)
                low += amt
        if low < 0:
            ax.text(i, low - top * 0.02, _kfmt(low), ha="center", va="top", fontsize=9)
        n = ax.scatter([i], [net], marker="D", s=46, color=B.DARK_GREY, zorder=5)
        seen.setdefault("Net", n)
        ax.annotate(_kfmt(net), (i, net), xytext=(26, 0), textcoords="offset points", ha="left", va="center", fontsize=8.5, color=B.DARK_GREY)
    ax.axhline(0, color=B.MED_GREY, linewidth=0.8)
    ax.set_xticks(range(len(rows))); ax.set_xticklabels([r[0].replace("Outside ", "Outside\n").replace(" and ", " and\n") for r in rows], fontsize=9.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_kfmt))
    ax.set_ylabel("Actual cost against estimate")
    ax.set_xlim(-0.6, len(rows) - 0.2)
    ax.legend(list(seen.values()), list(seen.keys()), frameon=False, fontsize=8, loc="upper right")
    B.chart_style(ax)
    return B.b64(fig)


def chart_family_rates(fam):
    """Margin by part family at the blended rate and at the pool rates, ordered by the pool-rate margin."""
    fig, ax = B.make_fig(4.4)
    f = fam.sort_values("margin_at_pool_rates", ascending=False)
    x = np.arange(len(f)); w = 0.38
    ax.bar(x - w / 2, f["margin_at_blended_rate"], w, color=B.MED_GREY, label="At the blended shop rate")
    ax.bar(x + w / 2, f["margin_at_pool_rates"], w, color=B.DARK_BLUE, label="At the work-center pool rates")
    for xi, (a, b_) in enumerate(zip(f["margin_at_blended_rate"], f["margin_at_pool_rates"])):
        ax.text(xi - w / 2, a + 0.004, f"{a * 100:.0f}", ha="center", va="bottom", fontsize=7.5)
        ax.text(xi + w / 2, b_ + 0.004, f"{b_ * 100:.0f}", ha="center", va="bottom", fontsize=7.5)
    ax.axhline(TM, color=B.DARK_GREY, linewidth=1.1, linestyle="--")
    ax.text(1.008, TM, f"standard\nmarkup\n{TM:.1%}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8, color=B.DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels(list(f["part_family"]), fontsize=8.5, rotation=32, ha="right")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); ax.set_ylabel("Margin on price")
    ax.set_ylim(0, max(f["margin_at_blended_rate"].max(), f["margin_at_pool_rates"].max()) * 1.2)
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    B.chart_style(ax)
    return B.b64(fig)


def chart_funnel(steps, positions):
    """The flag's funnel beside where on the routing it fired."""
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(B.CHART_W, 3.6), gridspec_kw={"width_ratios": [1.55, 1]})
    labs = [s[0] for s in steps]; vals = [s[1] for s in steps]
    y = np.arange(len(steps))[::-1]
    a1.barh(y, vals, color=[B.MED_GREY, B.LIGHT_BLUE, B.LIGHT_BLUE, B.DARK_BLUE], height=0.62)
    for yi, v in zip(y, vals):
        a1.text(v + vals[0] * 0.015, yi, f"{v:,}  ({v / vals[0]:.0%})", va="center", ha="left", fontsize=9)
    a1.set_yticks(y); a1.set_yticklabels(labs, fontsize=9); a1.set_xlim(0, vals[0] * 1.28); a1.set_xlabel("Jobs")
    a1.set_title("From completed jobs to flags with time to act", fontsize=10, fontweight="bold")
    B.chart_style(a1); a1.xaxis.grid(True, color=B.LIGHT_GREY); a1.yaxis.grid(False)
    x = np.arange(len(positions))
    a2.bar(x, [p[1] for p in positions], color=B.LIGHT_BLUE, width=0.6)
    tot = sum(p[1] for p in positions)
    for xi, p in zip(x, positions):
        a2.text(xi, p[1] + tot * 0.01, f"{p[1]:,}\n({p[1] / tot:.0%})", ha="center", va="bottom", fontsize=8.5)
    a2.set_xticks(x); a2.set_xticklabels([p[0] for p in positions], fontsize=8.5); a2.set_ylim(0, max(p[1] for p in positions) * 1.25)
    a2.set_title("Where the flag fired", fontsize=10, fontweight="bold"); a2.set_ylabel("Jobs flagged")
    B.chart_style(a2)
    fig.tight_layout()
    return B.b64(fig)


def chart_accuracy(series):
    """Actual over estimate by element as box plots: the analysis year against the engagement period."""
    fig, ax = B.make_fig(4.4)
    pos, data, cols, ticks = [], [], [], []
    for i, (lab, hist, eng) in enumerate(series):
        for kx, (r, col) in enumerate([(hist, B.MED_GREY), (eng, B.DARK_BLUE)]):
            data.append(r.clip(0.2, 2.5).values); pos.append(i * 3 + kx); cols.append(col)
        ticks.append(i * 3 + 0.5)
    bp = ax.boxplot(data, positions=pos, widths=0.8, showfliers=False, patch_artist=True, medianprops={"color": "white", "linewidth": 1.5})
    for patch, col in zip(bp["boxes"], cols):
        patch.set_facecolor(col); patch.set_edgecolor(col)
    ax.axhline(1.0, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.set_xticks(ticks); ax.set_xticklabels([s[0].split(" (")[0] for s in series], fontsize=9.5)
    ax.set_ylabel("Actual / estimate"); ax.set_ylim(0.3, 2.3)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=B.MED_GREY, label=f"{YEAR}, estimates backfilled from the quoting module"),
                       Patch(color=B.DARK_BLUE, label="Engagement period, estimate carried on the job")], frameon=False, fontsize=9, loc="upper left")
    B.chart_style(ax)
    return B.b64(fig)


# ── same part, different outcomes: the two examples ─────────────────────────
def pick_examples(sp):
    """Two parts chosen from the spread mart by rule. Lot size: the part with the widest spread whose
    worst job is a release at half its usual lot or less, with setup within 15% of estimate and run
    hours inside the range of the part's other jobs, so what differs is the setup carried over fewer
    pieces. Nothing in the data: among the parts whose worst job lost money at a lot within 5% of
    the usual one, on the same revision, with none of the conditions below on it and no driver rule
    carrying it, the one with the largest loss."""
    plain = lambda x: ~(x["first_after_revision"] | x["infrequent_part"] | x["revision_after_release"] | x["second_setup"]) & (x["older_vmc_share"].fillna(0) < 0.1)
    lot, none = [], []
    for pn, x in sp.groupby("part_number"):
        w = x[x["worst_job"]].iloc[0]; rest = x[~x["worst_job"]]
        if x["revision"].nunique() > 1 or not x["margin_on_price"].between(-1.5, 0.8).all():
            continue
        if (plain(x).all() and w.lot_vs_median <= 0.5 and pd.notna(w.setup_hours_ratio) and 0.85 <= w.setup_hours_ratio <= 1.15
                and rest["run_hours_ratio"].min() - 0.03 <= w.run_hours_ratio <= rest["run_hours_ratio"].max() + 0.03
                and rest["lot_vs_median"].between(0.7, 1.6).all()):
            lot.append((x["part_margin_spread"].iloc[0], pn))
        if w.margin_on_price < 0 and plain(x[x["worst_job"]]).all() and 0.95 <= w.lot_vs_median <= 1.05 and w.driver == "Not attributable":
            none.append((-w.contribution, pn))
    return (max(lot)[1] if lot else None), (max(none)[1] if none else None)


# ── the report ──────────────────────────────────────────────────────────────
def build(d):
    j, j25, b, q = d["jobs"], d["j25"], d["s25"], d["queue"]
    short = d["short"]
    cov = j25.set_index("job_id")
    J = lambda ids: cov.loc[cov.index.intersection(list(ids))]
    msi = lambda ids: ms(J(ids))
    rev25 = j25["price"].sum(); margin25 = j25["contribution"].sum() / rev25
    mg = j25["margin_on_price"]; neg = j25["contribution"] < 0
    below = (mg < TM - 0.02) & ~neg; above = ~neg & ~below
    m_mean, m_sd = mg.mean(), mg.std()
    est_m25 = 1 - j25["est_total_cost"].sum() / rev25; est_mean = j25["estimated_margin_on_price"].mean()
    gap = j25["margin_on_price"] - j25["estimated_margin_on_price"]
    by_type = {t: j25[j25["job_type"] == t] for t in ["repeat", "new", "own_product"]}
    gap_rep = by_type["repeat"]["margin_on_price"] - by_type["repeat"]["estimated_margin_on_price"]
    gap_new = by_type["new"]["margin_on_price"] - by_type["new"]["estimated_margin_on_price"]
    size_x = [j25[j25["quantity"].between(lo, hi)] for _, lo, hi in SIZE_BANDS]
    size_avg = [x["margin_on_price"].mean() for x in size_x]; size_neg = [(x["contribution"] < 0).mean() for x in size_x]
    size_gap = [x["margin_on_price"] - x["estimated_margin_on_price"] for x in size_x]
    size_est_m = [x["estimated_margin_on_price"].mean() for x in size_x]
    s_one = b.set_index("job_id")
    size_s = [s_one.loc[s_one.index.intersection(x["job_id"])] for x in size_x]
    size_est_setup = [(x["est_setup_hours"] * x["rate"] / x["est_cost_at_pool"]).mean() for x in size_s]

    # ── section 2: actual against estimate, by element ────────────────────
    est_total = b["est_cost_at_pool"].sum(); act_total = b["act_total_cost"].sum()
    over_pos = sum(b[c].clip(lower=0).sum() for c, _ in ELEMENTS); over_neg = sum(b[c].clip(upper=0).sum() for c, _ in ELEMENTS)
    over = over_pos + over_neg
    el_order = sorted(ELEMENTS, key=lambda e: -b[e[0]].clip(lower=0).sum())
    # outside processing in its parts: PO invoices against the estimate, jobs whose estimate carries no
    # outside processing (no quote line found), and the ledger residual allocated to jobs
    osp = d["osp"]
    po = osp[osp["job_id"].isin(j25["job_id"])].groupby("job_id").agg(po=("amount", "sum"), at_min=("at_minimum", "max"))
    o = cov[["est_outside", "act_outside", "job_type", "quantity", "release_date"]].join(po).join(s_one[["c_outside"]])
    o["tied"] = o["po"].notna()                      # a purchase order line tied to the job
    o["po"] = o["po"].fillna(0.0); o["resid"] = o["act_outside"] - o["po"]
    o["has_est"] = o["est_outside"] > 0
    pos_c = o["c_outside"].clip(lower=0)
    o["over_resid"] = np.where(o["c_outside"] > 0, np.minimum(o["resid"], o["c_outside"]), 0.0)
    o["over_po"] = pos_c - o["over_resid"]
    both = o["has_est"] & o["tied"]                  # an estimate and a purchase order to set against it
    unmatched = o["has_est"] & ~o["tied"]            # an estimate, and no purchase order tied to the job
    osp_po_over = o.loc[both, "over_po"].sum(); osp_noq_over = o.loc[~o["has_est"], "over_po"].sum()
    osp_resid_over = o["over_resid"].sum()
    osp_po_under = o.loc[both, "c_outside"].clip(upper=0).sum(); osp_unmatched_under = o.loc[unmatched, "c_outside"].clip(upper=0).sum()
    osp_resid_total = o["resid"].sum()
    oe = o[both].copy(); oe["r_po"] = oe["po"] / oe["est_outside"]
    po_net = (oe["po"] - oe["est_outside"]).sum(); po_ratio = oe["po"].sum() / oe["est_outside"].sum()
    no_quote = o[~o["has_est"] & (o["po"] > 0)]
    qd = d["quotes"].groupby("quote_id")["quote_date"].min()
    oe["quote_date"] = oe.index.map(d["estimate"].set_index("job_id")["quote_id"]).map(qd)
    oe["age"] = (pd.to_datetime(oe["release_date"]) - oe["quote_date"]).dt.days / 365.25
    r_new_quote = oe.loc[oe["age"] <= 0.5, "r_po"].median(); r_old_quote = oe.loc[oe["age"] > 3, "r_po"].median()
    r_at_min = oe.loc[oe["at_min"] == True, "r_po"].median(); r_no_min = oe.loc[oe["at_min"] == False, "r_po"].median()  # noqa: E712
    osp25 = osp[osp["job_id"].isin(j25["job_id"])]; atmin = osp25[osp25["at_minimum"]]

    def el_stats(c):
        return b[c].clip(lower=0).sum(), b[c].clip(upper=0).sum(), b[c].sum(), int((b[c] > 1).sum()), measured_share(J(b.loc[b[c] > 1, "job_id"]))

    el_rows, pareto = [], []
    for c, lab in el_order:
        g, u, n, nj, m_ = el_stats(c)
        if c == "c_outside":
            el_rows.append(["Outside processing, PO invoices", k(osp_po_over), k(osp_po_under), k(osp_po_over + osp_po_under), f"{int((both & (o['over_po'] > 1)).sum()):,}",
                            pct(measured_share(J(o.index[both & (o['over_po'] > 1)])))])
            el_rows.append(["Outside processing, jobs with no quote line (no outside processing in the estimate)", k(osp_noq_over), k(0), k(osp_noq_over),
                            f"{int((~o['has_est'] & (o['over_po'] > 1)).sum()):,}", pct(measured_share(J(o.index[~o['has_est'] & (o['over_po'] > 1)])))])
            el_rows.append(["Outside processing, allocated from the ledger", k(osp_resid_over), k(0), k(osp_resid_over), f"{int((o['over_resid'] > 1).sum()):,}", "0%"])
            el_rows.append(["Outside processing, estimate with no purchase order tied to the job", k(0), k(osp_unmatched_under), k(osp_unmatched_under), "0",
                            pct(measured_share(J(o.index[unmatched])))])
            pareto.append((lab, [("Over estimate", osp_po_over, "solid"), ("No quote line: no outside processing in the estimate", osp_noq_over, "light"),
                                 ("Allocated from the ledger", osp_resid_over, "hatched")],
                           [("Under estimate on other jobs", osp_po_under, "under"), ("Estimate with no PO tied to the job", osp_unmatched_under, "under hatched")], n))
        else:
            el_rows.append([lab, k(g), k(u), k(n), f"{nj:,}", pct(m_)])
            pareto.append((lab, [("Over estimate", g, "solid")], [("Under estimate on other jobs", u, "under")], n))
    el_rows.append(["<strong>All elements</strong>", f"<strong>{k(over_pos)}</strong>", f"<strong>{k(over_neg)}</strong>", f"<strong>{k(over)}</strong>",
                    f"{int((b['act_total_cost'] > b['est_cost_at_pool']).sum()):,}", pct(measured_share(j25))])
    el_table = widths(B.data_table(["Element", "Over estimate", "Under estimate", "Net", "Jobs over estimate", "Cost measured"], el_rows, right=[1, 2, 3, 4, 5]), [40, 13, 13, 11, 12, 11])

    def iqr(r):
        r = r.dropna(); r = r[(r > 0) & (r < 5)]
        return r.median(), r.quantile(0.25), r.quantile(0.75), len(r)

    see = [("Run hours", iqr(b["act_run_hours"] / b["est_run_hours"].replace(0, np.nan))),
           ("Outside processing, PO invoices", iqr(oe["r_po"])),
           ("Setup hours", iqr(b["act_setup_hours"] / b["est_setup_hours"].replace(0, np.nan))),
           ("Material, at the job's issue price", iqr(b["act_material"] / b["est_material_today"].replace(0, np.nan)))]
    see_rows = [[lab, f"{n:,}", f"{m_:.2f}", f"{a:.2f} to {z:.2f}"] for lab, (m_, a, z, n) in see]
    see_rows.append(["Scrap and rework", f"{int((b['c_scrap_rework'] > 0).sum()):,}", "not in the estimate", ""])
    see_table = B.data_table(["Element", "Jobs", "Median actual / estimate", "Interquartile range"], see_rows, right=[1, 2, 3])
    run_med, osp_med, setup_med = see[0][1][0], see[1][1][0], see[2][1][0]

    mh = d["machine"]; mh = mh[mh["job_id"].isin(j25["job_id"])]
    stop_share = (mh["machine_alarm_hours"].sum() + mh["machine_idle_hours"].sum()) / (mh["machine_run_hours"] + mh["machine_alarm_hours"] + mh["machine_idle_hours"]).sum()
    log = d["std_log"]
    # the audit's count of stale standards (error #1): repeat-part operations whose standard was more than 15% off the cycle the feed measured
    stale = _pq("dq_stale_routing_standards")
    std_low = stale[stale["direction"] == "cycle now slower than standard"]; std_high = stale[stale["direction"] == "cycle now faster than standard"]
    older = b[b["older_machine_run_hours"] > 0]; alloy = b[b["hard_alloy"]]
    alloy_fams = b[~b["hard_alloy"] & b["part_family"].isin(alloy["part_family"].unique())]
    rr = lambda x: (x["act_run_hours"] / x["est_run_hours"].replace(0, np.nan)).median()
    ss = b[b["second_setup_hours"] > 0]
    setup = j25[j25["est_setup_hours"] > 0].copy()
    setup["far"] = setup["job_id"].map(short.set_index("job_id")["first_after_revision"]).fillna(False).astype(bool)
    never_run = (setup["job_type"] == "new") & setup["days_since_part_ran"].isna()
    sr = lambda m: setup.loc[m, "setup_hours_ratio"].median()
    s_far, s_new, s_gap, s_known = sr(setup["far"]), sr(~setup["far"] & never_run), sr(~setup["far"] & setup["infrequent_part"] & ~never_run), sr(~setup["far"] & ~setup["infrequent_part"])
    s_int = sr(setup["job_id"].isin(ss["job_id"]))
    ops = d["ops"].merge(setup[["job_id", "far", "infrequent_part"]], on="job_id")
    mf = ops[ops["work_center_group"].isin(["MTN", "FAX"]) & (ops["std_setup_hours"] > 0) & (ops["act_setup_hours"] > 0)]
    mfr = mf["act_setup_hours"] / mf["std_setup_hours"]
    cell_inf = mfr[~mf["far"] & mf["infrequent_part"]].median(); cell_known = mfr[~mf["far"] & ~mf["infrequent_part"]].median()
    rework_events = len(d["rework_as_run"])
    scrap_jobs = b[b["c_scrap_rework"] > 0]

    # ── section 3: the blended rate ───────────────────────────────────────
    fam = d["family"].sort_values("margin_at_pool_rates", ascending=False).copy()
    fam["cost_moved"] = fam["cost_at_pool_rates"] - fam["cost_at_blended_rate"]
    fam_rows = [[r_.part_family, f"{int(r_.jobs):,}", k(r_.revenue), pct(r_.margin_at_blended_rate, 1), int(r_.rank_at_blended_rate), pct(r_.margin_at_pool_rates, 1),
                 int(r_.rank_at_pool_rates), f"{r_.margin_points_moved * 100:+.1f}".replace("-", "&minus;"), k(r_.cost_moved), k(r_.cost_moved * (1 + TARGET)),
                 pct(measured_share(j25[j25["part_family"] == r_.part_family]))] for r_ in fam.itertuples()]
    fam_table = widths(B.data_table(["Part family", "Jobs", "Revenue", "Margin, blended rate", "Rank", "Margin, pool rates", "Rank", "Points moved",
                                     "Pool cost less blended cost", "The same at the markup price", "Cost measured"], fam_rows, right=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
                       [17, 6, 9, 9, 5, 9, 5, 8, 11, 11, 10])
    under_f = fam[fam["cost_moved"] > 0]; over_f = fam[fam["cost_moved"] < 0]
    pools = d["rate_pools"]; pools["rate"] = pools["labor_rate"] * pools["attended_ratio"] + pools["burden_rate"]
    pg = pools.assign(g=pools["work_center_id"].str[:3]).groupby("g")["rate"].mean().sort_values()
    top_blended = fam.sort_values("margin_at_blended_rate", ascending=False)["part_family"].tolist()
    top_pool = fam["part_family"].tolist()
    gainers = fam.sort_values("margin_points_moved", ascending=False).head(2); losers = fam.sort_values("margin_points_moved").head(2)

    # ── section 4: jobs caught in progress ────────────────────────────────
    r = d["replay"]; r25 = r[r["release_year"] == YEAR]
    fl = r25[r25["flagged"]]; left = r25[r25["flagged_with_operations_left"]]; op_ = r25[r25["flagged_while_open"]]
    posn = fl["flag_position"].value_counts()
    after = op_["overrun_after_flag"].sum(); own_over = op_["overrun"].sum()
    th = d["thresholds"]; th = th[th["release_year"] == YEAR].copy(); th["threshold"] = th["threshold"].astype(float); th = th.sort_values("threshold")
    fi = _pq("int_inprogress_flag"); fi = fi[(fi["release_year"] == YEAR) & fi["flagged_while_open"]].copy(); fi["threshold"] = fi["threshold"].astype(float)
    th_over = fi.groupby("threshold")["overrun"].sum()
    th_rows = [[pct(x.threshold), f"{int(x.flagged):,}", f"{int(x.flagged_while_open):,}", f"{int(x.recovered_by_close):,} ({pct(x.recovered_by_close / x.flagged)})",
                k(x.overrun_after_flag), k(th_over.get(x.threshold, np.nan)), pct(x.overrun_after_flag / th_over.get(x.threshold, np.nan))] for x in th.itertuples()]
    th_table = B.data_table(["Threshold", "Jobs flagged", "Flagged while open", "Recovered by close", "Overrun after the flag", "What those jobs ran over in all", "Share after the flag"], th_rows, right=[1, 2, 3, 4, 5, 6])
    eng = j[(j["version"] == "restructured") & (j["status"] == "completed")]
    re_ = r[r["job_id"].isin(eng["job_id"])]; fe = re_[re_["flagged"]].copy()
    fe["week"] = [C.engagement_week(pd.Timestamp(x).date()) for x in fe["flag_date"]]
    wk = fe.groupby(["week", "flag_position"]).size().unstack(fill_value=0).reindex(columns=["first operation", "a middle operation", "last operation"], fill_value=0)
    wk_open = fe[fe["flagged_while_open"]].groupby("week").size().reindex(wk.index, fill_value=0)
    wk_rows = [[f"Week {int(w)}", *[int(v) for v in row], int(row.sum()), int(wk_open[w])] for w, row in wk.iterrows()]
    wk_rows.append(["<strong>All</strong>", *[int(v) for v in wk.sum()], f"<strong>{int(wk.values.sum())}</strong>", f"<strong>{int(wk_open.sum())}</strong>"])
    wk_table = B.data_table(["Engagement week of the flag", "First operation", "A middle operation", "Last operation", "All flags", "While open"], wk_rows, right=[1, 2, 3, 4, 5])
    full_weeks = wk.sum(axis=1).iloc[1:-1] if len(wk) > 2 else wk.sum(axis=1)

    # ── section 5: repricing ──────────────────────────────────────────────
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
    two_step_bal = rp["gap_to_target_annual"].sum() - captured
    held_parts = bq[bq["decision"] == "hold"]; held = held_parts["gap_to_target_annual"].sum()
    exited_parts = bq[bq["decision"] == "exit"]; exited = exited_parts["gap_to_target_annual"].sum()
    moved = bq[["moved_material", "moved_rate", "moved_standard", "moved_outside"]].clip(lower=0)
    bq["driver"] = moved.idxmax(axis=1).where(moved.sum(axis=1) > 0).map({"moved_material": "Material", "moved_rate": "Labor rate",
                                                                            "moved_standard": "Measured standard", "moved_outside": "Outside processing"})
    above_q = q[~q["below_target"]]
    cost_move = lambda x: (x["current_unit_cost"] / x["quoted_unit_cost"] - 1).median()
    from data_source.generate.generators.quotes_jobs import _letters_between
    letters_move = lambda x: x["last_quote_date"].map(lambda dt: _letters_between(pd.Timestamp(dt).date(), C.END_DATE) - 1).median()
    letters = list(C.ANNUAL_INCREASE_LETTER.values())
    words = lambda t: str(t).replace("cost plus target", "cost plus the standard markup").replace("no path to target", "no path to the markup price")
    dec_rows = [["Repriced now", f"{len(rp):,}", k(captured), pct(captured / exposure)],
                ["Second step of the two-step increases, due at the blanket renewal", f"{len(two_step):,} of the repriced", k(two_step_bal), pct(two_step_bal / exposure)],
                ["Held, with the reason recorded", f"{len(held_parts):,}", k(held), pct(held / exposure)],
                ["Exited at the next release", f"{len(exited_parts):,}", k(exited), pct(exited / exposure)],
                ["<strong>All parts below the markup price</strong>", f"<strong>{len(bq):,}</strong>", f"<strong>{k(exposure)}</strong>", "100%"]]
    dec_table = B.data_table(["Decision", "Parts", "Gap a year", "Share of the gap"], dec_rows, right=[1, 2, 3])
    reasons = bq.groupby(["decision", "rationale"]).agg(n=("part_number", "size"), g=("gap_to_target_annual", "sum")).reset_index().sort_values(["decision", "g"], ascending=[True, False])
    reason_table = widths(B.data_table(["Decision", "Reason recorded", "Parts", "Gap a year"],
                                       [[{"reprice": "Repriced", "hold": "Held", "exit": "Exited"}[x.decision], words(x.rationale), f"{int(x.n):,}", k(x.g)] for x in reasons.itertuples()], right=[2, 3]), [12, 62, 10, 16])
    rp_rows = []
    for x in bq.sort_values("gap_to_target_annual", ascending=False).head(12).itertuples():
        dec = {"reprice": "Repriced", "hold": "Held", "exit": "Exited"}[x.decision] + (f" at {money(x.new_price, 2)}" if pd.notna(x.new_price) else "")
        rp_rows.append([x.part_number, x.customer_name, money(x.standing_price, 2), money(x.target_price, 2), pct(x.gap, 1), money(x.gap_to_target_annual),
                        x.driver if isinstance(x.driver, str) else "n/a", dec, words(x.rationale)])
    rp_table = widths(B.data_table(["Part", "Customer", "Standing price", "Markup price", "Gap", "Gap a year", "What moved most", "Decision", "Reason"], rp_rows, right=[2, 3, 4, 5]),
                      [7, 11, 8, 8, 6, 8, 11, 12, 29])
    drv_q = bq.groupby("driver").agg(n=("part_number", "size"), g=("gap_to_target_annual", "sum"), rep=("decision", lambda x: (x == "reprice").mean())).sort_values("g", ascending=False)
    drv_table = B.data_table(["What moved most since the last quote", "Parts", "Gap a year", "Share repriced"], [[i, f"{int(x.n):,}", k(x.g), pct(x.rep)] for i, x in drv_q.iterrows()], right=[1, 2, 3])
    own_rows = [[x.part_number, x.description, money(x.list_price, 2), money(x.current_unit_cost, 2), money(x.current_unit_cost * (1 + TARGET), 2),
                 pct(x.list_price / (x.current_unit_cost * (1 + TARGET)) - 1), f"{x.annual_volume:,.0f}", B.badge("below cost", B.ACCENT_RED) if x.below_cost_at_list else ""]
                for x in own.sort_values("margin_on_list_price").itertuples()]
    own_table = B.data_table(["Part", "Description", "List price", "Current cost", "Cost plus markup", "List against cost plus markup", "Annual volume", ""], own_rows, right=[2, 3, 4, 5, 6])
    rc = d["release"]; rc25 = rc[rc["release_year"] == YEAR]; small = rc25[rc25["below_half_quoted_lot"]]; rest_rel = rc25[~rc25["below_half_quoted_lot"]]
    charge = small["release_setup_charge"].sum()
    m_small = small["contribution"].sum() / small["price"].sum(); m_small_ch = (small["contribution"].sum() + charge) / (small["price"].sum() + charge)
    rel_table = B.data_table(["Repeat-part releases", "Value"], [
        [f"Releases in {YEAR}", f"{len(rc25):,}"],
        ["Below half the quoted lot", f"{len(small):,} ({pct(len(small) / len(rc25), 1)})"],
        ["Median release against the quoted lot, those releases", pct(small["released_over_quoted"].median())],
        ["Setup charge they would have carried", f"{k(charge)} ({money(small['release_setup_charge'].median())} a release at the median)"],
        ["Margin on those releases, as earned", pct(m_small, 1)],
        ["Margin on those releases with the charge added to the price", pct(m_small_ch, 1)],
        ["Margin on the other repeat releases", pct(rest_rel["contribution"].sum() / rest_rel["price"].sum(), 1)],
        ["Share of those releases that lost money", pct((small["contribution"] < 0).mean())]], right=[1])

    # ── section 6: the jobs that lost money ───────────────────────────────
    drv = d["driver"].set_index("job_id")
    loss = b[b["loss"]].copy()
    loss["primary"] = loss["job_id"].map(drv["driver"]).fillna("Not attributable")
    loss["action"] = loss["job_id"].map(drv["action"]).fillna("Accept")
    loss = loss.sort_values("contribution")
    est_loss = loss[loss["estimated_margin_on_price"] < 0]; est_gain = loss[loss["estimated_margin_on_price"] >= 0]
    by_action = loss.groupby("action").agg(jobs=("job_id", "size"), loss_=("contribution", "sum")).sort_values("loss_")
    act_table = B.data_table(["Action", "Jobs", "Loss", "Share of the loss", "Cost measured"],
                             [[a, f"{int(x.jobs):,}", money(x.loss_), pct(x.loss_ / loss["contribution"].sum()), pct(measured_share(J(loss.loc[loss["action"] == a, "job_id"])))] for a, x in by_action.iterrows()], right=[1, 2, 3, 4])
    loss_rows = lambda df: [[nw(x.job_id), nw(x.part_number), x.customer_name if isinstance(x.customer_name, str) else "n/a", f"{int(x.quantity):,}",
                             pct(x.estimated_margin_on_price), pct(x.margin_on_price), nw(money(x.contribution)), x.primary, x.action, pct(min(x.coverage, 1))] for x in df.itertuples()]
    loss_head = ["Job", "Part", "Customer", "Pieces", "Estimated margin", "Margin", "Loss", "Driver", "Action", "Measured"]
    loss_table = widths(B.data_table(loss_head, loss_rows(loss.head(25)), right=[3, 4, 5, 6, 9]), [9, 8, 13, 6, 9, 8, 9, 15, 14, 9])
    loss_all = widths(B.data_table(loss_head, loss_rows(loss), right=[3, 4, 5, 6, 9]), [9, 8, 13, 6, 9, 8, 9, 15, 14, 9])
    top25 = loss.head(25)

    # ── section 7: same part, different outcomes ──────────────────────────
    sp = d["spread"].copy()
    jone = j.drop_duplicates("job_id").set_index("job_id"); sall = short.set_index("job_id")
    sp["infrequent_part"] = sp["job_id"].map(jone["infrequent_part"]).fillna(False).astype(bool)
    sp["revision_after_release"] = sp["job_id"].map(sall["revision_after_release"]).fillna(False).astype(bool)
    sp["second_setup"] = sp["job_id"].map(sall["second_setup_hours"]).fillna(0) > 0
    sp["driver"] = sp["job_id"].map(drv["driver"])
    sp["est_margin"] = sp["job_id"].map(jone["estimated_margin_on_price"])
    sp["setup_share"] = sp["job_id"].map(jone["est_setup_hours"]) * sp["job_id"].map(sall["rate"]) / sp["price"]
    by_part = sp.groupby("part_number").agg(spread=("part_margin_spread", "first"), jobs=("job_id", "size"), fam=("part_family", "first"),
                                            cust=("customer_name", "first"), med=("part_median_margin", "first"),
                                            worst=("margin_on_price", "min"), best=("margin_on_price", "max"))
    lot_pn, none_pn = pick_examples(sp)
    fam_words = lambda f: f.lower().replace("swiss", "Swiss").replace("edm", "EDM")

    def ex_table(x):
        rows = [[x_.job_id + (" (worst)" if x_.worst_job else ""), pd.Timestamp(x_.release_date).strftime("%d %b %Y"), f"{int(x_.quantity):,}", f"{x_.lot_vs_median:.2f}&times;", x_.revision,
                 pct(x_.setup_share), pct(x_.est_margin, 1), f"{x_.setup_hours_ratio:.2f}&times;" if pd.notna(x_.setup_hours_ratio) else "n/a",
                 f"{x_.run_hours_ratio:.2f}&times;" if pd.notna(x_.run_hours_ratio) else "n/a", pct(x_.margin_on_price, 1)] for x_ in x.sort_values("release_date").itertuples()]
        return B.data_table(["Job", "Released", "Pieces", "Lot against usual", "Revision", "Estimated setup, share of price", "Estimated margin", "Setup / estimate", "Run / estimate", "Margin"], rows, right=[2, 3, 5, 6, 7, 8, 9])

    ex_html = ""
    if lot_pn:
        x = sp[sp["part_number"] == lot_pn]; w = x[x["worst_job"]].iloc[0]; rest = x[~x["worst_job"]]
        ex_html += (f"<p><strong>Lot size.</strong> {lot_pn} ({fam_words(w.part_family)}, {w.customer_name}) ran {len(x)} jobs in {YEAR} with a "
                    f"{x['part_margin_spread'].iloc[0] * 100:.0f}-point spread. The standing price was set for the usual lot of {int(w.part_median_lot)} pieces. "
                    f"The worst job was a release of {int(w.quantity)}, {w.lot_vs_median:.2f}&times; of it, and the setup is the same whatever the lot: at {int(w.quantity)} pieces the "
                    f"estimated setup is {pct(w.setup_share)} of the price against {pct(rest['setup_share'].min())} to {pct(rest['setup_share'].max())} on the other jobs. The job's own "
                    f"current-cost estimate showed {pct(w.est_margin, 1)} before it started, and it earned {pct(w.margin_on_price, 1)} against {pct(x['margin_on_price'].max(), 1)} on the best job. "
                    f"Its setup ran {w.setup_hours_ratio:.2f}&times; the estimate and its run hours {w.run_hours_ratio:.2f}&times;, inside the range of the part's other jobs "
                    f"({rest['run_hours_ratio'].min():.2f}&times; to {rest['run_hours_ratio'].max():.2f}&times;); run hours run over on every job of the part, which is its routing standard "
                    f"and not this release.</p>" + sub(f"{lot_pn}: Lot Size") + ex_table(x))
    if none_pn:
        x = sp[sp["part_number"] == none_pn]; w = x[x["worst_job"]].iloc[0]
        ex_html += (f"<p><strong>Nothing in the data.</strong> {none_pn} ({fam_words(w.part_family)}, {w.customer_name}) ran {len(x)} jobs in {YEAR} with a "
                    f"{x['part_margin_spread'].iloc[0] * 100:.0f}-point spread. The worst job, {w.job_id}, ran at {int(w.quantity)} pieces, the part's usual lot, on the same revision as the others, "
                    f"with no change order, no time on the older mills and no year-long gap since the part last ran. It took {w.setup_hours_ratio:.2f}&times; its estimated setup and "
                    f"{w.run_hours_ratio:.2f}&times; its estimated run hours and earned {pct(w.margin_on_price, 1)} against an estimate of {pct(w.est_margin, 1)}; no driver rule carries it. "
                    f"The job record shows where the hours went and not why, and this report does not guess.</p>" + sub(f"{none_pn}: Nothing in the Data") + ex_table(x))
    spread_rows = [[pn, x["fam"], x["cust"], f"{int(x['jobs'])}", pct(x["worst"]), pct(x["med"]), pct(x["best"]), f"{x['spread'] * 100:.0f}"]
                   for pn, x in by_part.sort_values("spread", ascending=False).iterrows()]
    spread_table = widths(B.data_table(["Part", "Family", "Customer", "Jobs", "Worst", "Median", "Best", "Spread, pts"], spread_rows, right=[3, 4, 5, 6, 7]), [10, 24, 26, 8, 8, 8, 8, 8])

    # ── section 8: customers ──────────────────────────────────────────────
    cu = j25.groupby("customer_id").agg(name=("customer_name", "first"), industry=("industry", "first"), jobs=("job_id", "size"),
                                         rev=("price", "sum"), c=("contribution", "sum"), est=("est_total_cost", "sum"))
    cu["margin"] = cu["c"] / cu["rev"]; cu["est_margin"] = 1 - cu["est"] / cu["rev"]
    cu = cu.sort_values("rev", ascending=False)
    tot_c = cu["c"].sum()
    conc = {n: (cu.head(n)["rev"].sum() / rev25, cu.head(n)["c"].sum() / tot_c) for n in (1, 5, 10)}
    top15 = cu.head(15)
    # a customer whose margin rests on machine hours split across a part's open jobs: restate it with that part
    # at the margin its jobs earned together
    split_jobs = set(d["machine"].loc[d["machine"]["any_split"], "job_id"])
    notes = {}
    for cid in top15.index:
        cj = j25[j25["customer_id"] == cid]
        for pn, pj in cj.groupby("part_number"):
            allp = jone[jone["part_number"] == pn]
            if len(allp) < 3 or pj["price"].sum() < 0.25 * cj["price"].sum() or not pj["job_id"].isin(split_jobs).all():
                continue
            m_part = allp["contribution"].sum() / allp["price"].sum(); m_year = pj["contribution"].sum() / pj["price"].sum()
            if abs(m_year - m_part) > 0.05:
                restated = (cj["contribution"].sum() - pj["contribution"].sum() + m_part * pj["price"].sum()) / cj["price"].sum()
                notes[cid] = (pn, len(allp), m_part, restated, m_year)
    cust_rows = []
    for i, x in top15.iterrows():
        mark = " <sup>1</sup>" if i in notes else ""
        cust_rows.append([x["name"], x["industry"], f"{int(x['jobs']):,}", k(x["rev"]), pct(x["rev"] / rev25), pct(x["est_margin"], 1), pct(x["margin"], 1) + mark,
                          pct(measured_share(j25[j25["customer_id"] == i]))])
    cust_table = B.data_table(["Customer", "Industry", "Jobs", "Revenue", "Share", "Estimated margin", "Margin", "Cost measured"], cust_rows, right=[2, 3, 4, 5, 6, 7])
    note_html = "".join(
        f'<p style="font-size:13px;color:{B.MED_GREY};"><sup>1</sup> {cu.loc[cid, "name"]}: {YEAR} margin overstated. Before the monitoring feed carried job numbers, {pn}\'s machine hours were split by '
        f'quantity across its open jobs. Across the part\'s {n} jobs margin is {pct(mp, 1)}; with {pn} at that figure the customer\'s {YEAR} margin is {pct(restated, 1)}.</p>'
        for cid, (pn, n, mp, restated, my) in notes.items())
    top_id = top15["margin"].idxmax()
    range_note = (f" ({pct(notes[top_id][3], 1)} for {cu.loc[top_id, 'name']} with {notes[top_id][0]} corrected; note 1)" if top_id in notes else "")
    cust = d["customers"].sort_values(["change_order_count_12m", "customer_id"], ascending=[False, True])
    rid = cust["customer_id"].iloc[0]; rb = b[b["customer_id"] == rid]; ob = b[b["customer_id"] != rid]
    rev_name = cu.loc[rid, "name"]
    rev_unbilled = rb["cause_revision_work_unbilled"].sum()
    hr = lambda x: (x["act_setup_hours"] + x["act_run_hours"]).sum() / (x["est_setup_hours"] + x["est_run_hours"]).sum()
    ro = ob[ob["revision_after_release"]]
    real = cu[cu.index.notna() & (cu["name"] != "Own products, to stock")]
    lid = real[real["jobs"] >= 3].sort_values("margin").index[0]
    lj = b[b["customer_id"] == lid].sort_values("contribution")
    lnew = lj[lj["job_type"] == "new"]
    lj_table = B.data_table(["Job", "Part", "Type", "Released", "Pieces", "Price", "Estimated margin", "Gross profit", "Margin", "Driver"],
                            [[x.job_id, x.part_number, {"new": "New work", "repeat": "Repeat"}.get(x.job_type, x.job_type), pd.Timestamp(x.release_date).strftime("%d %b %Y"), f"{int(x.quantity):,}", money(x.price),
                              pct(x.estimated_margin_on_price), money(x.contribution), pct(x.margin_on_price), str(drv["driver"].get(x.job_id, "n/a"))] for x in lj.itertuples()], right=[4, 5, 6, 7, 8])

    # ── section 9: what changed in twelve weeks ───────────────────────────
    po_all = osp[osp["job_id"].notna()].groupby("job_id")["amount"].sum()

    def ratios(df, a, e, po_only=False):
        num = df["job_id"].map(po_all) if po_only else df[a]
        r_ = (num / df[e].replace(0, np.nan)).dropna()
        return r_[(r_ > 0) & (r_ < 5)]

    acc_def = [("Material (estimate as carried, at the quote's prices)", "act_material", "est_material", False), ("Setup hours", "act_setup_hours", "est_setup_hours", False),
               ("Run hours", "act_run_hours", "est_run_hours", False), ("Labor and burden", "act_labor", "est_labor", False),
               ("Outside processing (PO invoices)", "act_outside", "est_outside", True)]
    acc = [(lab, ratios(j25, a, e, p_), ratios(eng, a, e, p_)) for lab, a, e, p_ in acc_def]
    st = lambda r_: (r_.quantile(0.25), r_.median(), r_.quantile(0.75))
    accs = {lab.split(" (")[0]: (st(h), st(e)) for lab, h, e in acc}
    acc_table = B.data_table(["Element", f"{YEAR} median", f"{YEAR} interquartile range", "Engagement median", "Engagement interquartile range"],
                             [[lab, f"{st(h)[1]:.2f}", f"{st(h)[0]:.2f} to {st(h)[2]:.2f}", f"{st(e)[1]:.2f}", f"{st(e)[0]:.2f} to {st(e)[2]:.2f}"] for lab, h, e in acc], right=[1, 2, 3, 4])
    h_run, e_run = accs["Run hours"]; h_set, e_set = accs["Setup hours"]; h_osp, e_osp = accs["Outside processing"]; h_mat, e_mat = accs["Material"]
    eff_std = log.groupby("part_number")["effective_date"].min()
    eng_rep = eng[eng["job_type"] == "repeat"]
    pre_refresh = (pd.to_datetime(eng_rep["release_date"]) < pd.to_datetime(eng_rep["part_number"].map(eff_std))).mean()
    est = d["est"].sort_values("jobs", ascending=False)
    est_rows = [[x.estimator_id, f"{x.jobs:,}", k(x.revenue), pct(x.estimated_margin_on_price, 1), pct(x.margin_on_price, 1), f"{(x.margin_on_price - x.estimated_margin_on_price) * 100:+.1f} pts".replace("-", "&minus;")]
                for x in est.itertuples() if isinstance(x.estimator_id, str)]
    est_table = B.data_table(["Estimator", "Jobs", "Revenue", "Estimated margin", "Margin", "Gap"], est_rows, right=[1, 2, 3, 4, 5])
    est_named = est[est["estimator_id"].apply(lambda v: isinstance(v, str))]
    est_gap = (est_named["margin_on_price"] - est_named["estimated_margin_on_price"]).abs() * 100
    qy = j.merge(d["estimate"][["job_id", "quote_id"]].rename(columns={"quote_id": "qid"}), on="job_id", how="left")
    qy["quote_year"] = qy["qid"].map(qd).dt.year
    qy = qy[qy["job_type"] == "new"].groupby("quote_year").agg(jobs=("job_id", "size"), rev=("price", "sum"), c=("contribution", "sum"), est=("est_total_cost", "sum"), hr=("labor_hours_ratio", "median"))
    qy["m"] = qy["c"] / qy["rev"]; qy = qy[qy["jobs"] >= 50]
    qy_table = B.data_table(["Quote year", "Jobs", "Estimated margin", "Margin", "Labor hours / estimate (median)"],
                            [[int(y), f"{int(x.jobs):,}", pct(1 - x.est / x.rev, 1), pct(x.m, 1), f"{x.hr:.2f}"] for y, x in qy.iterrows()], right=[1, 2, 3, 4])
    cw = d["coverage"].dropna(subset=["measured_cost_share"]).iloc[-1]

    # ── section 10: actions ───────────────────────────────────────────────
    acts = d["actions"].set_index("action_id")
    after_q = eng[pd.to_datetime(eng["release_date"]) >= pd.Timestamp(C.CONFIG_DATES["vendor_prices_in_quoting"])]
    osp_after = ratios(after_q, "act_outside", "est_outside", True)
    alloy_eng = eng[eng["material_spec"].isin(C.HARD_ALLOY_MATERIALS) & (eng["est_run_hours"] > 0)]
    std_acc = log[log["reviewer_decision"] == "accepted"]
    all_unbilled = b["cause_revision_work_unbilled"].sum()
    effect = {
        "A1": (f"{len(std_acc):,} of the {len(log):,} CNC operations measured on repeat parts moved to the measured cycle. The audit found {len(stale):,} of the {len(log):,} more than 15% off it (error #1) and corrected {int(stale['refresh_decision'].isin(['accepted', 'disputed, adjusted']).sum()):,}. On engagement-period jobs the run-hours spread narrowed to {e_run[0]:.2f} to {e_run[2]:.2f} from {h_run[0]:.2f} to {h_run[2]:.2f} in {YEAR}, "
               f"and the median rose to {e_run[1]:.2f} from {h_run[1]:.2f}: most refreshed standards had sat above the measured cycle, so the refresh took out a cushion, and the measured cycle carries none of the stoppages."),
        "A2": f"{len(rp):,} parts; {k(captured)} a year at current volume, {pct(captured / exposure)} of the gap, with {k(two_step_bal)} more due at renewal on {len(two_step)} of them.",
        "A3": f"{len(exited_parts):,} parts carrying {k(exited)} of the gap a year.",
        "A4": (f"On engagement-period jobs released from the change, PO invoices came in at {osp_after.median():.2f}&times; the outside-processing estimate ({len(osp_after):,} jobs) "
               f"against {h_osp[1]:.2f}&times; on PO invoices in {YEAR}."),
        "A5": (f"Stated as decided. The {len(alloy_eng)} engagement-period jobs in the two alloys were estimated before it and ran "
               f"{(alloy_eng['act_run_hours'] / alloy_eng['est_run_hours']).median():.2f}&times; their run hours."),
        "A6": "Stated as decided: no job quoted since the decision has yet completed.",
        "A7": f"Applies to revisions issued from week {int(acts.loc['A7', 'engagement_week'])}. In {YEAR}, revision work that was not billed came to {k(all_unbilled)} across all customers.",
        "A8": "Stated as decided: effective as capacity on the newer mills allows.",
        "A9": f"{len(own):,} products; the gap at list is {k(own_exp)} a year at current volume.",
    }
    declined = {
        "D1": f"{len(held_parts):,} parts, {k(held)} of the gap a year",
        "D3": f"{k(rev_unbilled)} of revision work at {rev_name} in {YEAR} not recovered",
        "D4": f"{k(b['cause_older_machine'].sum())} of run hours on the older mills in {YEAR}",
        "D5": ", ".join(own.loc[own["below_cost_at_list"], "part_number"]) or "none",
        "D6": f"{len(small):,} releases in {YEAR} would have carried {k(charge)}",
    }
    taken = acts[acts["decision"] == "taken"]; notak = acts[acts["decision"] != "taken"]
    taken_table = widths(B.data_table(["Action taken", "Decided by", "When", "Effect on the jobs or parts it touched"],
                                      [[words(x.action), x.decided_by, f"Week {int(x.engagement_week)}", effect.get(i, "")] for i, x in taken.iterrows()]), [30, 14, 8, 48])
    not_table = widths(B.data_table(["Action", "Decision", "By", "What it leaves in place", "Reason"],
                                    [[x.action, x.decision.capitalize(), x.decided_by, declined.get(i, ""), x.reason] for i, x in notak.iterrows()]), [22, 9, 11, 20, 38])

    # ── executive summary ─────────────────────────────────────────────────
    first, second = el_order[0], el_order[1]
    cap_rows = [
        ["Actual against estimate by element on every job", "Standards carry a stoppage allowance; vendors' current prices and minimums in quoting; new and infrequent parts quoted at the measured first-run setup",
         f"{k(over_pos)} over estimate and {k(-over_neg)} under, {k(over)} net; {first[1].lower()} {k(b[first[0]].clip(lower=0).sum())} over and {second[1].lower()} {k(b[second[0]].clip(lower=0).sum())}, "
         f"of which {k(osp_resid_over)} is allocated from the ledger {ms(j25)}"],
        ["Margin at the work center's rate rather than one blended rate", "Repricing the families the blended rate underpriced",
         f"{k(under_f['cost_moved'].sum())} of cost on the {len(under_f)} families the blended rate underpriced, {k(under_f['cost_moved'].sum() * (1 + TARGET))} at the markup price "
         f"{ms(j25[j25['part_family'].isin(under_f['part_family'])])}"],
        ["A job running over while it is still open", "Check the standard, move the job, call the customer, or finish knowingly",
         f"{k(after)} of the {k(own_over)} the {len(op_):,} jobs flagged while open ran over came after the flag {msi(op_['job_id'])}"],
        ["Current cost per repeat part", "Monthly repricing review; a setup charge on small releases",
         f"{k(captured)} of the {k(exposure)} gap closed by the decisions; {k(charge)} on the {len(small):,} releases below half the quoted lot {msi(small['job_id'])}"],
        ["The jobs that lost money and why", "The action rule assigns to each",
         f"{len(loss):,} jobs, {k(loss['contribution'].sum())}: " + "; ".join(f"{a.lower()} {k(x.loss_)}" for a, x in by_action.iterrows()) + f" {msi(loss['job_id'])}"],
        ["The same part's spread", "Price to the worst realistic job", f"{by_part['spread'].median() * 100:.0f} points between the best and worst job at the median, across {len(by_part):,} repeat parts"],
        ["Margin by customer", "The account conversations and the below-estimate new work",
         f"{rev_name}: {pct(cu.loc[rid, 'margin'], 1)} against {pct(cu.loc[rid, 'est_margin'], 1)} estimated, with {k(rev_unbilled)} of revision work not billed; "
         f"{cu.loc[lid, 'name']}: {pct(cu.loc[lid, 'margin'], 1)} on {k(cu.loc[lid, 'rev'])}"],
    ]
    cap_table = widths(B.data_table(["What the shop can now see", "The action it supports", f"On the {YEAR} jobs"], cap_rows), [24, 30, 46])

    funnel_png = chart_funnel(
        [("Jobs completed", len(r25)), ("Flagged", len(fl)), ("Flagged with\noperations left", len(left)), (f"...and {C_ACT} or more\ndays before ship", len(op_))],
        [("First\noperation", int(posn.get("first operation", 0))), ("A middle\noperation", int(posn.get("a middle operation", 0))), ("Last\noperation", int(posn.get("last operation", 0)))])

    toc = "".join([
        '<a href="#summary">Executive Summary</a>',
        '<a href="#distribution">1 &middot; Job Margin Overview</a>',
        '<a href="#elements">2 &middot; Actual Cost against Estimate, by Element</a>',
        '<a href="#rates">3 &middot; What the Blended Rate Hid</a>',
        '<a href="#inprogress">4 &middot; Jobs Caught in Progress</a>',
        '<a href="#repricing">5 &middot; Repricing</a>',
        '<a href="#losses">6 &middot; The Jobs That Lost Money</a>',
        '<a href="#samepart">7 &middot; Same Part, Different Outcomes</a>',
        '<a href="#customers">8 &middot; Customer Profitability</a>',
        '<a href="#twelve">9 &middot; What Changed in Twelve Weeks</a>',
        '<a href="#actions">10 &middot; Actions Decided</a>',
        '<a href="#appendix">Appendix</a>',
    ])

    body = f"""
{B.section("summary", "Summary", "Executive Summary")}
<p>The {len(j25):,} jobs the shop released in {YEAR} earned <strong>{pct(margin25, 1)}</strong> on {k(rev25)} of revenue ("margin": price less
the job's full manufacturing cost, as a share of price) against the <strong>{pct(est_m25, 1)}</strong> their estimates promised, and
{pct(neg.mean(), 1)} of them lost money. Actual cost came in <strong>{k(over)}</strong> over the jobs' estimates {ms(j25)}: elements over estimate
added {k(over_pos)} and elements under estimate took back {k(-over_neg)}. The two largest elements are {first[1].lower()}
({k(b[first[0]].clip(lower=0).sum())} over) and {second[1].lower()} ({k(b[second[0]].clip(lower=0).sum())}, of which {k(osp_resid_over)} is ledger cost
allocated to jobs and not an overrun on any estimate). What the job-level comparison showed, and the P&amp;L could not, is that the overrun is
broad and modest: the median job ran {run_med:.2f}&times; its estimated run hours, the year's {pct(margin25, 1)} was an average of jobs ranging from losses on
{pct(neg.mean(), 1)} of them to margins above {pct(mg.quantile(0.9))} on one job in ten, and the same part could do both in the same year. The table sets out what the shop can now see, the action each
view supports, and what it comes to on the {YEAR} jobs. Nothing in it is projected forward.</p>
{cap_table}

{B.section("distribution", "Section 1", "Job Margin Overview")}
<p>The average {YEAR} job earned {pct(m_mean, 1)} margin against the {pct(est_mean, 1)} its estimate promised, and most jobs came in below their
estimate. The P&amp;L gave the shop one number: {pct(margin25, 1)} on {k(rev25)} of revenue. The job record shows what that number averaged over:
{int(above.sum()):,} jobs ({pct(above.mean())}) at or above the {pct(TM, 1)} the standard markup gives, {int(below.sum()):,} ({pct(below.mean())}) below it, and
{int(neg.sum()):,} ({pct(neg.mean(), 1)}) that lost money, {pct(j25.loc[neg, 'price'].sum() / rev25, 1)} of revenue because the losing jobs are smaller than
average. The second chart shows each job's margin less its estimated margin: {pct((gap < 0).mean())} of jobs came in below their estimate, by a median of
{-gap[gap < 0].median() * 100:.0f} points, and the red bars are the {pct((gap < -0.20).mean())} more than 20 points below. The gap includes the price movement
between quote and job as well as the jobs taking more than their estimates; Section 2 separates the two. Each bar is labeled with its number of jobs.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin Distribution", chart_histogram(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin", chart_margin_gap(j25))}
</div>
<p>Repeat parts earn more than new quoted work and miss their estimates by more. Repeat parts earn
{pct(by_type['repeat']['contribution'].sum() / by_type['repeat']['price'].sum(), 1)} on revenue and new work
{pct(by_type['new']['contribution'].sum() / by_type['new']['price'].sum(), 1)}; each loses money on {pct((by_type['repeat']['contribution'] < 0).mean())} and
{pct((by_type['new']['contribution'] < 0).mean())} of its jobs. Against their estimates, repeat parts miss by an average of {-gap_rep.mean() * 100:.1f} points
and new work by {-gap_new.mean() * 100:.1f}. A repeat part's estimate comes from its original quote, so its gap carries every movement in material, rates
and standards since then; a new part's estimate is weeks old. The panels in each chart share a scale.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Type", chart_histogram_types(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Type", chart_margin_gap_panels([("Repeat parts", by_type["repeat"]), ("New quoted work", by_type["new"])]))}
</div>
<p>Job size separates margin more sharply than job type. Lots under {C.SMALL_LOT_THRESHOLD} pieces average
{pct(size_avg[0], 1)} a job and lose money on {pct(size_neg[0])} of them; lots of 25 to 100 pieces average {pct(size_avg[1], 1)} and lose money on
{pct(size_neg[1])}, and lots over 100 pieces average {pct(size_avg[2], 1)} and lose money on {pct(size_neg[2])}. The small lots also miss their estimates by
the most, an average of {-size_gap[0].mean() * 100:.1f} points against {-size_gap[1].mean() * 100:.1f} and {-size_gap[2].mean() * 100:.1f}. Setup is why
a small lot is thin to begin with: it costs the same whatever the lot, so it is {pct(size_est_setup[0])} of a small lot's estimated cost against
{pct(size_est_setup[2])} for lots over 100, and small lots are estimated at {pct(size_est_m[0], 1)} against {pct(size_est_m[2], 1)}.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Size", chart_histogram_sizes(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Size", chart_margin_gap_panels([(lab, x) for (lab, _, _), x in zip(SIZE_BANDS, size_x)]))}
</div>

{B.section("elements", "Section 2", "Actual Cost against Estimate, by Element")}
<p>The estimates on the {YEAR} jobs promised {pct(est_m25, 1)} on the year's revenue. Re-costed at the prices of each job's own day (its hours at the
job's own pool rate, its material at the job's issue price) they come to {pct(1 - est_total / rev25, 1)}, and the jobs earned {pct(margin25, 1)}. The first
{(est_m25 - (1 - est_total / rev25)) * 100:.1f} points are what material prices and labor rates moved between quote and job, a pricing question taken up in
Section 5. The other {((1 - est_total / rev25) - margin25) * 100:.1f} points are the jobs taking more than their estimates: actual cost of {k(act_total)}
against a re-costed estimate of {k(est_total)}, <strong>{k(over)} over</strong> {ms(j25)}. That net figure is {k(over_pos)} over estimate on some jobs and
elements less {k(-over_neg)} under on others.</p>
<p>The chart ranks the elements by what ran over. Each bar is the cost over estimate on the jobs where the element ran over; the bar below the axis is
what the same element came in under on the other jobs, and the diamond is the net. Outside processing is drawn in three parts: PO invoices over the
estimate, PO invoices on jobs whose estimate carries no outside processing because no quote line was found for them, and the ledger residual
allocated to jobs, hatched, which no estimate carries. Below the axis, the hatched part is the estimate on jobs with no purchase order tied to them: it is
the counterpart of the allocation and not an underrun. The table gives each part its own row.</p>
{B.chart(f"Actual Cost against Estimate on the {YEAR} Jobs, by Element", chart_pareto(pareto))}
{el_table}
<p><strong>Run hours</strong> ran {k(b['c_run'].clip(lower=0).sum())} over on {int((b['c_run'] > 1).sum()):,} jobs and {k(-b['c_run'].clip(upper=0).sum())} under on the
rest, a median of {run_med:.2f}&times; the estimate. The routing standard is time in cycle, while a job's run hours also carry the alarms and in-operation
idle the machines record, {pct(stop_share, 1)} of machine time {msi(mh['job_id'].unique())}. Standards set above the measured cycle ({len(std_high):,} operations
more than 15% above it) absorb that on some parts, which is the under side. Standards below the measured cycle cost {k(b['cause_standard_below_cycle'].sum())} on
{int((b['cause_standard_below_cycle'] > 1).sum()):,} jobs {msi(b.loc[b['cause_standard_below_cycle'] > 1, 'job_id'])}, the two older vertical mills
{k(b['cause_older_machine'].sum())} on the {len(older):,} jobs the schedule put on them {msi(older['job_id'])}, and the hard alloys
{k(b['cause_hard_alloy_run_allowance'].sum())}: titanium and Inconel jobs ran {rr(alloy):.2f}&times; their estimated run hours against {rr(alloy_fams):.2f}&times;
for the other materials in the same two families {msi(alloy['job_id'])}.</p>
<p><strong>Outside processing</strong> has three parts, visible going forward because every purchase order now carries a job number. The first is the age
of the quote the estimate comes from: PO invoices run {r_new_quote:.2f}&times; the estimate where the part was quoted within six months of the job and
{r_old_quote:.2f}&times; where it was quoted more than three years before, which is vendor drift on every service. The second is the vendors' minimum
charges on small lots: {len(atmin):,} of the year's {len(osp25):,} PO lines were invoiced at a minimum, {k(atmin['minimum_excess'].sum())} more than the per-piece
price times the pieces {msi(atmin['job_id'].unique())}, and jobs with a line at a minimum run {r_at_min:.2f}&times; their estimate against {r_no_min:.2f}&times;
for the rest. The third is not an overrun at all. {k(osp_resid_total)} of {YEAR} outside-processing cost was on purchase orders with no job number that could
not be tied to a job afterwards, and is spread over the month's jobs so the ledger reconciles; {k(osp_resid_over)} of it lands on jobs that are over
estimate and is the hatched bar. Its other side is the {int(unmatched.sum()):,} jobs whose estimate carries outside processing and which have no purchase order
tied to them, {k(-osp_unmatched_under)} of estimate with nothing set against it. A further {k(no_quote['po'].sum())} sits on {len(no_quote):,} jobs with no
quote line, whose estimate carries no outside processing to compare with. On the {int(both.sum()):,} jobs that have both an estimate and a purchase order,
invoices came to {po_ratio:.2f}&times; the estimates in total, {k(po_net)} over.</p>
<p><strong>Setup hours</strong> run near or under the standard on parts the shop knows and over where something is new: the median job took
{s_known:.2f}&times; its estimated setup on a part run within the year, {s_far:.2f}&times; on the first run after a revision, and on the mill-turn and
5-axis cells a new part or one not run in a year takes {cell_inf:.2f}&times; the routing standard against {cell_known:.2f}&times; for a part the cell ran
within the year. A job stopped for another carries a second setup when it resumes: the record shows one on {len(ss):,} jobs,
{k((ss['second_setup_hours'] * ss['rate']).sum())} {msi(ss['job_id'])}.</p>
<p><strong>Scrap and rework</strong> are not in the estimate, so all {k(b['c_scrap_rework'].sum())} of it is over, on {len(scrap_jobs):,} jobs {msi(scrap_jobs['job_id'])}.
The figure is a floor: before the labor codes most rework was posted as run time ({rework_events:,} events the audit found), and those hours sit in
the run-hours bar.</p>
<p><strong>Material</strong> is flat once it is issued at actual and compared at the job's issue price: {k(b['c_material'].clip(lower=0).sum())} over and
{k(-b['c_material'].clip(upper=0).sum())} under.</p>
{sub("What the Estimator Can Now See: Actual over Estimate by Element, by Job")}
{see_table}
<p style="font-size:13px;color:{B.MED_GREY};">Outside processing excludes the ledger residual allocated to jobs ({k(osp_resid_total)} on {YEAR} jobs), which no estimate carries.
Material is set against the estimate re-costed at the job's issue price, so it reads usage; Section 9 shows material against the estimate as carried.</p>
<p>The table is the feedback the estimator did not have, and it names three changes to the estimate: a stoppage allowance in the run standards, the
vendors' current prices and minimum charges in the quoting module, and new and infrequent parts quoted at the measured first-run setup.</p>

{B.section("rates", "Section 3", "What the Blended Rate Hid")}
<p>The ERP costed every labor hour at one blended shop rate, ${C.BLENDED_RATE[YEAR]:,.0f} in {YEAR} and ${C.BLENDED_RATE[YEAR + 1]:,.0f} in {YEAR + 1}. The
work-center pools, as set in {pd.Timestamp(C.CONFIG_DATES['rate_pools_live']):%B %Y}, run from ${pg.iloc[0]:,.0f} an hour at
{CELL.get(pg.index[0], pg.index[0]).lower()} to ${pg.iloc[-1]:,.0f} at the {CELL.get(pg.index[-1], pg.index[-1]).lower()} cell. Costed at the pools, the families that
run on the manual and secondary cells gain ({gainers['part_family'].iloc[0]} {gainers['margin_points_moved'].iloc[0] * 100:+.1f} points, {gainers['part_family'].iloc[1]}
{gainers['margin_points_moved'].iloc[1] * 100:+.1f}) and the families that run on the expensive cells lose ({losers['part_family'].iloc[0]}
{losers['margin_points_moved'].iloc[0] * 100:.1f}, {losers['part_family'].iloc[1]} {losers['margin_points_moved'].iloc[1] * 100:.1f}). {top_blended[0]} is the
shop's best family at the blended rate and number {top_pool.index(top_blended[0]) + 1} of {len(fam)} at the pools. The blended rate left {k(under_f['cost_moved'].sum())}
of cost out of the {len(under_f)} families it underpriced, {k(under_f['cost_moved'].sum() * (1 + TARGET))} at the markup price, and overstated the cost of the
other {len(over_f)} by {k(-over_f['cost_moved'].sum())} {ms(j25)}. This is what the "labor rate" movements in the repricing queue are.</p>
{B.chart(f"Margin by Part Family at the Blended Rate and at the Pool Rates, {YEAR} Jobs", chart_family_rates(fam))}
{fam_table}

{B.section("inprogress", "Section 4", "Jobs Caught in Progress")}
<p>The <a href="../index.html">job cost screen</a> flags a job while it is open: at the first operation where its labor hours to date exceed the estimate to
date by more than {pct(THRESHOLD)} and by at least two hours, or at the first material issue where material exceeds the estimate by more than {pct(THRESHOLD)} and $150.
The flag is replayed here over the {len(r25):,} jobs completed from the {YEAR} releases, to show what the shop could have known and when.</p>
{B.chart(f"The Flag Replayed over the {YEAR} Jobs", funnel_png)}
<p>{len(fl):,} jobs would have been flagged, {len(left):,} of them with operations still to run and <strong>{len(op_):,}</strong> with operations left and {C_ACT} or
more days before the job shipped {msi(op_['job_id'])}. Those {len(op_):,} jobs ran {k(own_over)} over their estimates, and <strong>{k(after)} of it
({pct(after / own_over)}) came after the flag</strong>: on operations that started after it, and on material issued and outside processing received after
it. That is the part a warning could have changed.</p>
<p>A flag allows four things, none of them automatic. Check the routing standard and the program before the next operation runs. Move the remaining
operations to another machine. Call the customer about the quantity, the delivery or a change order. Or finish the job knowing what it will cost.</p>
{sub("The Flag at Three Thresholds")}
{th_table}
<p>At {pct(0.10)} the flag fires on more jobs and more of them recover on their own by close; at {pct(0.20)} it fires later and less of the overrun is still
ahead of it. {pct(THRESHOLD)} keeps most of the overrun that comes after the flag with fewer flags to work.</p>
{sub("Flags on the Jobs under the New Process, by Engagement Week")}
{wk_table}
<p>On the {len(re_):,} jobs released and completed under the new process, the flag fired {len(fe):,} times, about {int(full_weeks.min())} to {int(full_weeks.max())} a week
in the full weeks, and {pct(wk_open.sum() / max(len(fe), 1))} of them while there was still time to act. No record says whether a flag was acted on.</p>

{B.section("repricing", "Section 5", "Repricing")}
<p><strong>Exposure.</strong> At today's material prices, pool rates and measured standards, {len(bq):,} of the {len(q):,} repeat parts
({pct(len(bq) / len(q))}) have a standing price below current cost plus the shop's standard {pct(TARGET)} markup (the markup price), carrying
{pct(bq['rev'].sum() / (q['standing_price'] * q['annual_volume']).sum())} of repeat revenue. The gap is modest on most of them: a median of {pct(bq['gap'].median(), 1)},
with nine in ten under {pct(bq['gap'].quantile(0.9))}; {int(q['below_cost'].sum())} sit below cost outright. At current volume the exposure is
<strong>{k(exposure)} a year</strong>, and the own-product line adds {k(own_exp)}: together {pct((exposure + own_exp) / rev25, 1)} of {YEAR} revenue. The gap is what the
annual across-the-board letters ({min(letters):.1%} to {max(letters):.1%} a year) missed on the parts whose inputs moved most: since the last quote, current cost
rose a median {pct(cost_move(bq))} on the parts below the markup price against {pct(cost_move(above_q))} on the rest, while the letters raised the standing prices of
those parts a median {pct(letters_move(bq))}.</p>
<p><strong>What is defensible.</strong> In the shop's experience, as the owner and the controller described it, a routine annual increase of 3 to 5% is accepted
without discussion. A larger increase can land selectively, part by part, when the cost driver is documented, and most often that driver is material passed
through at what it now costs. Beyond that the relationship risk is real, and the owner decides.</p>
<p><strong>Decisions.</strong> The controller and the owner decided every part below the markup price in weeks 7 to 9 on that basis: a gap within the routine range
was repriced; a larger gap was repriced where material or outside processing drove it and the movement could be shown part by part, and held otherwise
with the reason recorded; a large gap on a small part was exited, and on the {len(two_step)} largest programs the increase was taken in two steps, half now
and the balance at the blanket renewal.</p>
{dec_table}
{sub("Reasons Recorded")}
{reason_table}
{sub("The Largest Gaps and the Decisions Taken")}
{rp_table}
<p><strong>What job costing added.</strong> Not the gap itself: a current-cost calculation gives that. What it added is the selectivity. For every part the
queue shows what moved since the last quote (material, the labor rate, the measured standard, outside processing), and that evidence is what lets a
targeted increase land where an across-the-board letter does not.</p>
{drv_table}
{sub("Own Products")}
<p>The fourteen own products sell from a list price set at launch over a standard cost that was never revised. Against current cost plus the markup the
list sits a median {pct(-own_gap.median())} short, from {pct(-own_gap.max())} to {pct(-own_gap.min())}; {int(own['below_cost_at_list'].sum())} of the fourteen sells below cost
at list. The list moves to current cost plus the markup at the next price list (Section 10).</p>
{own_table}
{sub("Pricing the Release")}
<p>A standing price is set for a quoted lot, and a blanket release is whatever the customer calls off. In {YEAR}, {len(small):,} of the {len(rc25):,} repeat-part
releases ({pct(len(small) / len(rc25), 1)}) were below half the lot the price was quoted at. The setup is the same whatever the release, so those jobs carried
it over fewer pieces than the price assumed: they earned {pct(m_small, 1)} against {pct(rest_rel['contribution'].sum() / rest_rel['price'].sum(), 1)} on the other repeat
releases, and {pct((small['contribution'] < 0).mean())} of them lost money. Charging the part of the estimated setup the price did not cover, (1 less released
over quoted) times the estimated setup hours at the pool rate, would have added {k(charge)} to those releases and taken them to {pct(m_small_ch, 1)} {msi(small['job_id'])}.
The action is a setup line on any release below half the quoted lot, or a minimum lot charge on the standing price.</p>
{rel_table}

{B.section("losses", "Section 6", "The Jobs That Lost Money")}
<p><strong>{len(loss):,}</strong> jobs lost money in {YEAR}, {money(-loss['contribution'].sum())} in total {msi(loss['job_id'])}. Set against their estimates, the losses
are mostly not a pricing story: only {len(est_loss)} of the {len(loss):,} were estimated to lose money before they started. The other {len(est_gain):,} were
estimated to make money, a median estimated margin of {pct(est_gain['estimated_margin_on_price'].median())}, and lost it in the job; they carry
{pct(est_gain['contribution'].sum() / loss['contribution'].sum())} of the loss. Each job carries the driver the reporting layer assigns by rule, the same rules the
Job Variance report applies to every job (appendix), and the action the driver maps to: correct the routing standard, correct the quote, bill the change
order, reprice the part, fix the process, or accept it as a one-off. This is the list the owner and estimator work from, and it matches what they see in
the ERP.</p>
{sub("Loss-making Jobs by Action")}
{act_table}
<p>Of the 25 largest losses (listed in the appendix), {int((top25['primary'] == 'Routing standard').sum())} trace to a routing standard the part's jobs keep
overrunning, {int((top25['primary'] == 'Unbilled revision work').sum())} are unbilled revision work, {int((top25['primary'] == 'Priced below estimated cost').sum())} were
priced below their own estimated cost, {int((top25['primary'] == 'Not attributable').sum())} fire no rule with a dominant share and are accepted as one-offs, and
the other {int((~top25['primary'].isin(['Routing standard', 'Unbilled revision work', 'Priced below estimated cost', 'Not attributable'])).sum())} carry other drivers.</p>

{B.section("samepart", "Section 7", "Same Part, Different Outcomes")}
<p>For the {len(by_part):,} repeat parts with three or more jobs in {YEAR}, the gap between each part's best and worst job has a median of
<strong>{by_part['spread'].median() * 100:.0f} points</strong>; on {pct((by_part['spread'] >= 0.20).mean())} of them it is 20 points or more. Same part, same customer,
same standing price, different outcome.</p>
{B.chart(f"Spread of Job Margin within Each Repeat Part, {YEAR}", chart_spread(by_part['spread']))}
{ex_html}
<p>For quoting this means one thing: a part's price has to cover its worst realistic job, not its average. A standing price set on the typical lot
loses money whenever the release is small, and some jobs run over for reasons no record explains; both happen several times a year on the same part
numbers.</p>

{B.section("customers", "Section 8", "Customer Profitability")}
<p>Revenue is concentrated: in {YEAR} the top customer was {pct(conc[1][0])} of revenue and {pct(conc[1][1])} of gross profit, the top five {pct(conc[5][0])} and
{pct(conc[5][1])}, the top ten {pct(conc[10][0])} and {pct(conc[10][1])}. Margin by customer ranges from {pct(top15['margin'].min(), 1)} to {pct(top15['margin'].max(), 1)}{range_note} across the
top fifteen, and {int((top15['margin'] < top15['est_margin'] - 0.005).sum())} of the fifteen earned less than their estimates promised.</p>
{B.chart(f"Estimated Margin and Margin, Top 15 Customers by Revenue, {YEAR}", chart_customers(top15.set_index("name")))}
{cust_table}
{note_html}
<p>{rev_name} is the account whose drawings are revised after release: {int(cust['change_order_count_12m'].iloc[0])} revision changes in the last twelve months
against a median of {int(cust['change_order_count_12m'].median())} across the book. {int(rb['revision_after_release'].sum()):,} of its {len(rb):,} jobs carried revision work
after release, {k(rev_unbilled)} of it not billed {msi(rb['job_id'])}, and it earned {pct(cu.loc[rid, 'margin'], 1)} against the {pct(cu.loc[rid, 'est_margin'], 1)} its
estimates promised.</p>
<p>{cu.loc[lid, 'name']} {'lost money' if cu.loc[lid, 'margin'] < 0 else 'earned the least'}: {pct(cu.loc[lid, 'margin'], 1)} on {k(cu.loc[lid, 'rev'])} across
{int(cu.loc[lid, 'jobs'])} jobs {msi(lj['job_id'])}, {len(lnew)} of them new work won in the last two years. The new work was priced at or under the shop's own
estimate (a median estimated margin of {pct(lnew['estimated_margin_on_price'].median(), 1)}), so there was no margin to absorb any overrun; the jobs are
listed below with the driver assigned to each.</p>
{sub(f"{cu.loc[lid, 'name']}: Jobs Released in {YEAR}")}
{lj_table}

{B.section("twelve", "Section 9", "What Changed in Twelve Weeks")}
<p>The same comparison of actual over estimate, by cost element, for the {YEAR} jobs (estimates backfilled from the quoting module) and for the
{len(eng):,} jobs released and completed in the engagement period with the estimate carried on the job ({pct(cw['measured_cost_share'])} of their cost measured
by week {int(cw['engagement_week'])}).</p>
{B.chart(f"Actual over Estimate by Element, {YEAR} against the Engagement Period", chart_accuracy(acc))}
{acc_table}
<p style="font-size:13px;color:{B.MED_GREY};">Material here is against the estimate as carried, at the prices of the quote, so the {YEAR} column includes
what the price moved; Section 2 re-costs it at the job's issue price. Outside processing is PO invoices over the estimate in both columns, without the
ledger residual allocated to {YEAR} jobs.</p>
<p><strong>Material</strong> moved to {e_mat[1]:.2f} and its spread closed because the estimate now carries the price of the day and not the spreadsheet's
price list. <strong>Outside processing</strong> moved to {e_osp[1]:.2f} from {h_osp[1]:.2f} because the quoting module carries the vendors' current prices and
minimums. <strong>Run hours</strong> narrowed, from {h_run[0]:.2f} to {h_run[2]:.2f} ({h_run[2] - h_run[0]:.2f} wide) to {e_run[0]:.2f} to {e_run[2]:.2f}
({e_run[2] - e_run[0]:.2f} wide), because repeat parts are now estimated on the measured cycle; and the median rose, from {h_run[1]:.2f} to {e_run[1]:.2f}.
Both follow from the refresh. Most refreshed standards had sat above the measured cycle ({len(std_high):,} operations more than 15% above it against
{len(std_low):,} more than 15% below), so the refresh took out a cushion; and the measured cycle is time in cycle, with none of the stoppages a job's run
hours carry, {pct(stop_share, 1)} of machine time. That is the case for a stoppage allowance in the standard. <strong>Setup hours</strong> have not moved yet
(a median of {e_set[1]:.2f} against {h_set[1]:.2f}): {pct(pre_refresh)} of the engagement-period repeat jobs were estimated before their part's refreshed
standard took effect, and new and infrequent parts still run over. <strong>Labor and burden</strong> tightened further because the estimate and the actual
now use the same pool rate.</p>
<p>By estimator, the gap between the estimated margin and the margin runs {est_gap.min():.1f} to {est_gap.max():.1f} points, about the same for all three: the
shortfall is in what the estimates carry, not in who writes them. By quote year, the margin on new work has not improved on its own, from
{pct(qy['m'].iloc[0], 1)} on work quoted in {int(qy.index[0])} to {pct(qy['m'].iloc[-1], 1)} on work quoted in {int(qy.index[-1])}; that is what the feedback is for.</p>
{sub("Margin by Estimator, All Jobs")}
{est_table}
{sub("New Quoted Work by Year Quoted")}
{qy_table}

{B.section("actions", "Section 10", "Actions Decided")}
<p>The actions the owner took on these findings, with their effect on the jobs or parts they touched. Effects are measured on engagement-period jobs
where there are enough of them, and otherwise stated as decided.</p>
{sub("Actions Taken during the Engagement")}
{taken_table}
<p>The actions the owner declined or deferred, and why. They are as much a part of the result as the actions taken.</p>
{sub("Actions Declined or Deferred")}
{not_table}
<p>The two tables are not added up and nothing here is projected forward.</p>

{B.section("appendix", "Appendix", "Method, Definitions and Detail")}
<p><strong>Job cost.</strong> Material at the issued price, corrected to the part's need where the audit found another job's bar or none; labor as hours at
the work center's pool rate (labor rate &times; attended ratio + burden); outside processing at the invoiced price, with lines that could not be tied to a
job allocated over the month's jobs; scrap at the job's material cost. CNC hours come from the machine-monitoring feed on every monitored cell, not from
the clock record.</p>
<p><strong>Measured share.</strong> The share of a job's cost resting on a transaction (a machine interval assigned to the job, a clock record, a scan, an
issue, a purchase order) and not on the routing standard, an allocated ledger residual or a record flagged unrepairable. Stated beside every dollar
figure as the coverage of the jobs behind it.</p>
<p><strong>Margin.</strong> Margin is gross margin: price less the job's cost (material, labor and burden at the work center's pool rate, outside processing
and scrapped material), as a share of price. Estimated margin is the same measure on the job's estimate, and a job loses money when its margin is below
zero. The shop prices as a markup on cost: its standard {pct(TARGET)} markup prices a job at cost &times; {1 + TARGET:.2f}, a margin of {TARGET:.2f} &divide;
{1 + TARGET:.2f} = {pct(TM, 1)}.</p>
<p><strong>Actual against estimate.</strong> Each job's actual cost less its estimate, with the estimate re-costed at the prices of the job's own day: its hours
at the job's pool rate, its material at the job's issue price. The difference splits exactly into the elements: material, setup hours, run hours, outside
processing, and scrap and rework, which the estimate does not carry. The outside-processing estimate is the quote line's figure and is not re-costed. A job
with no quote line is estimated from the routing standard at the shop rate with material at the month's price, and carries no outside processing in its
estimate.</p>
<p><strong>Outside-processing minimum excess.</strong> On a PO line invoiced at the vendor's minimum charge, the invoice less the per-piece price times the
pieces.</p>
<p><strong>Blended-rate margin.</strong> The job costed with every labor hour at the blended shop rate of its year; the pool-rate margin is this report's
standard margin. Both are on the same {YEAR} jobs. The dollars at the markup price are the cost difference times {1 + TARGET:.2f}.</p>
<p><strong>In-progress flag.</strong> A job is flagged at the first operation where its labor hours to date exceed the estimate to date by more than
{pct(THRESHOLD)} and by at least two hours, or at the first material issue if material exceeds the estimate by more than {pct(THRESHOLD)} and $150. An operation is a
cell on the routing, in routing order. The estimate to date is the routing standard for each operation, scaled so the operations sum to the job's
estimated hours. A flag is actionable when it fires before the last operation and {C_ACT} or more days before the job ships.</p>
<p><strong>Overrun after the flag.</strong> On a job flagged while open: the actual less the estimate on every operation that started after the flag, plus
the material and outside-processing variance in proportion to the dollars issued or received after the flag date, net of what came in under estimate
there.</p>
<p><strong>Recovered by close.</strong> A flagged job whose final cost came in at or under its re-costed estimate.</p>
<p><strong>Release setup charge.</strong> On a repeat-part release below half its quoted lot: (1 less released over quoted) &times; the job's estimated setup
hours &times; the pool rate. The quoted lot is read from the part's quote on file. Own products and new work are excluded.</p>
<p><strong>Revision work.</strong> Section 8 states the revision work not billed as the shortfall-by-cause mart sizes it: on a job with a revision after
release and no change-order line, the setup and run hours beyond the shop's median labor ratio, at the job's rate. A second measure, the account's hours
beyond the rest of the book's ratio of actual to estimated hours, gives {k((((rb['act_setup_hours'] + rb['act_run_hours']) - (rb['est_setup_hours'] + rb['est_run_hours']) * hr(ob)) * rb['rate']).sum())}
for {rev_name}; it is lower because it nets the account's jobs that ran under against those that ran over.</p>
<p><strong>Drivers.</strong> Section 6 assigns each job the driver the reporting layer's rules give it, the same rules the Job Variance report shows in the
ERP: routing standard (run hours over 1.15&times; the estimate, and the part's other jobs in the trailing twelve months over too); new or infrequent part
setup (setup over 1.30&times; on a part new to the shop or not run in the past 12 months); unbilled revision work (labor over estimate, a revision change
after release and no change order billed, at any customer); vendor rate (outside processing over 1.10&times; the estimate); scrap and rework (over 5% of
estimated cost); material (over the estimate by more than 10%); priced below estimated cost (the job's own estimate showed a loss, sized as that
estimated loss). Where several fire, the largest dollar variance is the driver; where none fires, or the largest carries under 40% of the job's overrun,
the job is not attributable.</p>
{sub(f"The 25 Largest Losses, {YEAR}")}
{loss_table}
{sub(f"All Loss-making Jobs, {YEAR}")}
{loss_all}
{sub(f"Within-part Spread, Repeat Parts with Three or More Jobs in {YEAR}")}
{spread_table}
"""
    return body, toc


def run():
    d = gather()
    body, toc = build(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = B.page("Report: Job Margin Analytics Diagnostic", "Created by Brian Davis, 2026", toc, body)
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"Margin diagnostic written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
