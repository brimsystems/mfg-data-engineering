"""Analytics diagnostic report, job costing and margin -> docs/reports/margin_diagnostic.html

About the business, not the data: how margin is spread across the shop's jobs and
why, from the corrected job cost. The report attributes and does not project: the
2025 overrun is split by cost element on the jobs themselves, the blended rate is
set against the work-center pools, and the jobs that lost money are laid out by
the action each one's driver maps to. Every number is read from a dbt mart
(analytics/data/marts).

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
CELL = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathes", "HMC": "Horizontal mills", "VMC": "Vertical mills",
        "MTN": "Mill-turn", "FAX": "5-axis", "SAW": "Saw", "MDP": "Manual drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
# the cost elements of actual against estimate, with the column each sits in on the shortfall mart
ELEMENTS = [("c_run", "Run hours"), ("c_outside", "Outside processing"), ("c_setup", "Setup hours"),
            ("c_scrap_rework", "Scrap and rework"), ("c_material", "Material")]
# the drivers of the loss-making jobs, in the chart colors
DRIVER_COLORS = {"Routing standard": B.DARK_BLUE, "Unbilled revision work": B.ACCENT_RED, "Priced below estimated cost": B.LIGHT_BLUE,
                 "New or infrequent part setup": B.GREEN, "Vendor rate": B.MUTED_RED, "Material": B.AMBER, "Scrap and rework": B.DARK_GREY,
                 "Not attributable": B.MED_GREY}


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


def k1(x):
    """Compact money to one decimal: $224.2K."""
    return f"${abs(x) / 1e3:.1f}K"


def km(x):
    """Money in millions to one decimal: $56.1M."""
    return f"${x / 1e6:.1f}M"


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
    for name, mart in [("driver", "mart_job_driver"), ("family", "mart_margin_by_family_rate_basis"), ("osp", "int_osp_by_job")]:
        d[name] = _pq(mart)
    d["rate_pools"] = pd.read_csv(RAW / "remediation" / "rate_pools.csv")
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


def _kfmt(v, _=None):
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:,.0f}K"
    return ("−" if v < 0 else "") + s


def chart_bridge(labels, values, total_label):
    """Net actual cost against estimate by element, largest first, walking up to the total."""
    fig, ax = B.make_fig(4.2)
    top = max(np.cumsum(values).max(), max(values))
    cum = 0.0
    for i, v in enumerate(values):
        ax.bar(i, abs(v), bottom=cum if v >= 0 else cum + v, color=B.ACCENT_RED if v >= 0 else B.DARK_BLUE, width=0.62)
        ax.text(i, max(cum, cum + v) + top * 0.02, _kfmt(v), ha="center", va="bottom", fontsize=9)
        cum += v
    ax.bar(len(labels), cum, color=B.DARK_GREY, width=0.62)
    ax.text(len(labels), cum + top * 0.02, _kfmt(cum), ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.axhline(0, color=B.MED_GREY, linewidth=0.8)
    ax.set_xticks(np.arange(len(labels) + 1))
    ax.set_xticklabels([lab.replace("Outside ", "Outside\n").replace(" and ", " and\n") for lab in labels] + [total_label], fontsize=9.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_kfmt))
    ax.set_ylabel("Actual cost against estimate")
    ax.set_ylim(top=top * 1.12)
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


def chart_pool_rates(pg, blended, year):
    """The work-center pool rate by cell, lowest first, with the blended shop rate dashed across."""
    fig, ax = B.make_fig(3.8)
    x = np.arange(len(pg))
    ax.bar(x, pg.values, color=B.DARK_BLUE, width=0.62)
    for xi, v in zip(x, pg.values):
        ax.text(xi, v + pg.max() * 0.012, f"${v:,.0f}", ha="center", va="bottom", fontsize=8.5)
    ax.axhline(blended, color=B.DARK_GREY, linewidth=1.2, linestyle="--")
    ax.text(-0.45, blended + pg.max() * 0.012, f"Blended shop rate, {year}: ${blended:,.0f}", ha="left", va="bottom", fontsize=9, color=B.DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels([CELL.get(g, g) for g in pg.index], fontsize=8.5, rotation=32, ha="right")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}")); ax.set_ylabel("Pool rate, an hour")
    ax.set_ylim(0, pg.max() * 1.12)
    B.chart_style(ax)
    return B.b64(fig)


def chart_loss_by_driver(t):
    """The loss carried by each driver, largest at the top, labeled with the dollars and the jobs."""
    fig, ax = B.make_fig(3.5)
    y = np.arange(len(t))[::-1]
    ax.barh(y, t["loss"], color=[DRIVER_COLORS[a] for a in t.index], height=0.62)
    for yi, x in zip(y, t.itertuples()):
        ax.text(x.loss + t["loss"].max() * 0.012, yi, f"{int(x.jobs)} jobs, {k1(x.loss)}", va="center", ha="left", fontsize=9.5)
    ax.set_yticks(y); ax.set_yticklabels(list(t.index), fontsize=10)
    ax.set_xlim(0, t["loss"].max() * 1.24); ax.xaxis.set_major_formatter(mticker.FuncFormatter(_kfmt)); ax.set_xlabel("Loss")
    B.chart_style(ax); ax.xaxis.grid(True, color=B.LIGHT_GREY); ax.yaxis.grid(False)
    return B.b64(fig)


EST_CLIP, ACT_CLIP = (-0.45, 0.60), (-1.00, 0.03)


def chart_est_vs_actual(loss):
    """One dot per loss-making job: the margin estimated against the margin earned, by driver."""
    fig, ax = B.make_fig(4.8)
    x, y = loss["estimated_margin_on_price"], loss["margin_on_price"]
    beyond = int((~(x.between(*EST_CLIP) & y.between(*ACT_CLIP))).sum())
    for a in ["Not attributable"] + [a for a in DRIVER_COLORS if a != "Not attributable"]:
        g = loss[loss["driver"] == a]
        ax.scatter(g["estimated_margin_on_price"], g["margin_on_price"], s=20, color=DRIVER_COLORS[a], alpha=0.55 if a == "Not attributable" else 0.85,
                   edgecolor="white", linewidth=0.4, label=f"{a} ({len(g)})", zorder=2 if a == "Not attributable" else 3)
    ax.axvline(0, color=B.DARK_GREY, linewidth=1.0); ax.axhline(0, color=B.DARK_GREY, linewidth=1.0)
    ax.set_xlim(*EST_CLIP); ax.set_ylim(*ACT_CLIP)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0)); ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Estimated margin on price"); ax.set_ylabel("Actual margin on price")
    h, lab = ax.get_legend_handles_labels()
    ax.legend(h[1:] + h[:1], lab[1:] + lab[:1], frameon=False, fontsize=8.5, loc="lower left", ncol=1, handletextpad=0.3, borderaxespad=0.6)
    B.chart_style(ax)
    if beyond:
        fig.text(0.01, -0.02, f"{beyond} jobs earned a margin below {ACT_CLIP[0]:.0%} and are beyond the axis.".replace("-", "\u2212"),
                 fontsize=8.5, color=B.DARK_GREY, ha="left", va="top")
    return B.b64(fig)


def chart_repeat_losers(t):
    """The parts with the largest loss over two or more jobs, colored by the driver on most of the
    loss-making jobs and hatched where those jobs do not share one driver."""
    from matplotlib.patches import Patch
    fig, ax = B.make_fig(5.0)
    y = np.arange(len(t))[::-1]
    for yi, x in zip(y, t.itertuples()):
        ax.barh(yi, x.loss, color=DRIVER_COLORS[x.driver], height=0.66, edgecolor="white", linewidth=0, hatch=None if x.same else "////")
        ax.text(x.loss + t["loss"].max() * 0.012, yi, f"{int(x.loss_jobs)} of {int(x.releases)} jobs", va="center", ha="left", fontsize=8.5)
    ax.set_yticks(y); ax.set_yticklabels(list(t["part_number"]), fontsize=9)
    ax.set_xlim(0, t["loss"].max() * 1.2); ax.xaxis.set_major_formatter(mticker.FuncFormatter(_kfmt)); ax.set_xlabel("Loss on the part's loss-making jobs")
    seen = [dr for dr in DRIVER_COLORS if dr in set(t["driver"])]
    handles = [Patch(facecolor=DRIVER_COLORS[dr], label=dr) for dr in seen]
    if (~t["same"]).any():
        handles.append(Patch(facecolor=B.MED_GREY, edgecolor="white", linewidth=0, hatch="////", label="Hatched: more than one driver on the loss-making jobs"))
    ax.legend(handles=handles, frameon=False, fontsize=8.5, loc="lower right")
    B.chart_style(ax); ax.xaxis.grid(True, color=B.LIGHT_GREY); ax.yaxis.grid(False)
    return B.b64(fig)


def chart_concentration(cum, half_n):
    """Cumulative share of the loss as jobs are added from the largest loss down."""
    fig, ax = B.make_fig(3.6)
    n = np.arange(1, len(cum) + 1)
    ax.plot(n, cum, color=B.DARK_BLUE, linewidth=1.8)
    ax.axhline(0.5, color=B.MED_GREY, linewidth=0.9, linestyle="--")
    ax.scatter([half_n], [cum[half_n - 1]], color=B.ACCENT_RED, s=28, zorder=4)
    ax.annotate(f"Half of the loss at {half_n} jobs", (half_n, cum[half_n - 1]), xytext=(half_n + 26, 0.33), fontsize=9.5,
                arrowprops=dict(arrowstyle="-", color=B.MED_GREY, linewidth=0.8))
    ax.set_xlim(0, len(cum) + 2); ax.set_ylim(0, 1.03)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Jobs, ranked from the largest loss"); ax.set_ylabel("Share of the total loss")
    B.chart_style(ax)
    return B.b64(fig)


# ── the report ──────────────────────────────────────────────────────────────
def build(d):
    j25, b = d["j25"], d["s25"]
    short = d["short"]
    cov = j25.set_index("job_id")
    J = lambda ids: cov.loc[cov.index.intersection(list(ids))]
    rev25 = j25["price"].sum(); margin25 = j25["contribution"].sum() / rev25
    mg = j25["margin_on_price"]; neg = j25["contribution"] < 0
    m_mean = mg.mean(); above_avg = mg > m_mean
    est_m25 = 1 - j25["est_total_cost"].sum() / rev25; est_mean = j25["estimated_margin_on_price"].mean()
    gap = j25["margin_on_price"] - j25["estimated_margin_on_price"]
    by_type = {t: j25[j25["job_type"] == t] for t in ["repeat", "new", "own_product"]}
    gap_rep = by_type["repeat"]["margin_on_price"] - by_type["repeat"]["estimated_margin_on_price"]
    gap_new = by_type["new"]["margin_on_price"] - by_type["new"]["estimated_margin_on_price"]
    size_x = [j25[j25["quantity"].between(lo, hi)] for _, lo, hi in SIZE_BANDS]
    size_avg = [x["margin_on_price"].mean() for x in size_x]; size_neg = [(x["contribution"] < 0).mean() for x in size_x]
    size_gap = [x["margin_on_price"] - x["estimated_margin_on_price"] for x in size_x]
    s_one = b.set_index("job_id")

    # ── section 2: actual against estimate, by element ────────────────────
    over_pos = sum(b[c].clip(lower=0).sum() for c, _ in ELEMENTS); over_neg = sum(b[c].clip(upper=0).sum() for c, _ in ELEMENTS)
    over = over_pos + over_neg
    el_order = sorted(ELEMENTS, key=lambda e: -b[e[0]].clip(lower=0).sum())
    bridge = sorted(((lab, b[c].sum()) for c, lab in ELEMENTS), key=lambda e: -e[1])   # net by element, largest first
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
    # cost the quote did not carry at all, as the sum of its two parts to the thousand so the three figures agree
    not_quoted = round(osp_noq_over, -3) + round(b["c_scrap_rework"].sum(), -3)
    osp_po_under = o.loc[both, "c_outside"].clip(upper=0).sum(); osp_unmatched_under = o.loc[unmatched, "c_outside"].clip(upper=0).sum()
    po_ratio = o.loc[both, "po"].sum() / o.loc[both, "est_outside"].sum()

    def el_stats(c):
        return b[c].clip(lower=0).sum(), b[c].clip(upper=0).sum(), b[c].sum(), int((b[c] > 1).sum()), measured_share(J(b.loc[b[c] > 1, "job_id"]))

    el_rows = []
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
        else:
            el_rows.append([lab, k(g), k(u), k(n), f"{nj:,}", pct(m_)])
    el_rows.append(["<strong>All elements</strong>", f"<strong>{k(over_pos)}</strong>", f"<strong>{k(over_neg)}</strong>", f"<strong>{k(over)}</strong>",
                    f"{int((b['act_total_cost'] > b['est_cost_at_pool']).sum()):,}", pct(measured_share(j25))])
    el_table = widths(B.data_table(["Element", "Over estimate", "Under estimate", "Net", "Jobs over estimate", "Cost measured"], el_rows, right=[1, 2, 3, 4, 5]), [40, 13, 13, 11, 12, 11])

    run_med = (b["act_run_hours"] / b["est_run_hours"].replace(0, np.nan)).pipe(lambda r: r[(r > 0) & (r < 5)]).median()
    setup = j25[j25["est_setup_hours"] > 0].copy()
    setup["far"] = setup["job_id"].map(short.set_index("job_id")["first_after_revision"]).fillna(False).astype(bool)
    sr = lambda m: setup.loc[m, "setup_hours_ratio"].median()
    s_far, s_known = sr(setup["far"]), sr(~setup["far"] & ~setup["infrequent_part"])

    # ── section 3: the blended rate ───────────────────────────────────────
    fam = d["family"].sort_values("margin_at_pool_rates", ascending=False).copy()
    fam["cost_moved"] = fam["cost_at_pool_rates"] - fam["cost_at_blended_rate"]
    fam_rows = [[r_.part_family, f"{int(r_.jobs):,}", k(r_.revenue), pct(r_.margin_at_blended_rate, 1), int(r_.rank_at_blended_rate), pct(r_.margin_at_pool_rates, 1),
                 int(r_.rank_at_pool_rates), f"{r_.margin_points_moved * 100:+.1f}".replace("-", "&minus;"), k(r_.cost_moved), k(r_.cost_moved * (1 + TARGET)),
                 pct(measured_share(j25[j25["part_family"] == r_.part_family]))] for r_ in fam.itertuples()]
    fam_table = widths(B.data_table(["Part family", "Jobs", "Revenue", "Margin, blended rate", "Rank", "Margin, pool rates", "Rank", "Points moved",
                                     "Pool cost less blended cost", "The same at the markup price", "Cost measured"], fam_rows, right=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
                       [17, 6, 9, 9, 5, 9, 5, 8, 11, 11, 10])
    pools = d["rate_pools"]; pools["rate"] = pools["labor_rate"] * pools["attended_ratio"] + pools["burden_rate"]
    pg = pools.assign(g=pools["work_center_id"].str[:3]).groupby("g")["rate"].mean().sort_values()
    top_blended = fam.sort_values("margin_at_blended_rate", ascending=False)["part_family"].tolist()
    top_pool = fam["part_family"].tolist()
    gainers = fam.sort_values("margin_points_moved", ascending=False).head(2); losers = fam.sort_values("margin_points_moved").head(2)
    pool_png = chart_pool_rates(pg, C.BLENDED_RATE[YEAR + 1], YEAR + 1)

    # ── section 4: the jobs that lost money ───────────────────────────────
    drv = d["driver"].set_index("job_id")
    loss = j25[j25["contribution"] < 0].copy()
    loss["driver"] = loss["job_id"].map(drv["driver"]).fillna("Not attributable")
    loss["action"] = loss["job_id"].map(drv["action"]).fillna("Accept")
    loss = loss.sort_values("contribution").reset_index(drop=True)          # largest loss first
    loss["loss_"] = -loss["contribution"]; tot_loss = loss["loss_"].sum()
    loss["fall"] = loss["estimated_margin_on_price"] - loss["margin_on_price"]
    est_loss = loss[loss["estimated_margin_on_price"] < 0]; est_gain = loss[loss["estimated_margin_on_price"] >= 0]
    accepted = loss[loss["action"] == "Accept"]
    by_driver = loss[loss["action"] != "Accept"].groupby("driver").agg(jobs=("job_id", "size"), loss=("loss_", "sum")).sort_values("loss", ascending=False)
    drv_share = lambda drvs: by_driver.loc[drvs, "loss"].sum() / tot_loss
    routing = loss[loss["driver"] == "Routing standard"]; revision = loss[loss["driver"] == "Unbilled revision work"]
    fall_med = loss[loss["driver"] != "Not attributable"].groupby("driver")["fall"].median().sort_values(ascending=False)
    furthest = loss[loss["driver"] == fall_med.index[0]]
    # parts with two or more loss-making jobs; the driver is the one on most of them, the larger loss on a tie
    releases = j25.groupby("part_number").size()
    rows = []
    for pn, g in loss.groupby("part_number"):
        if len(g) < 2:
            continue
        dv = g.groupby("driver")["loss_"].agg(["size", "sum"]).sort_values(["size", "sum"], ascending=False)
        rows.append({"part_number": pn, "customer": g["customer_name"].iloc[0], "releases": int(releases[pn]), "loss_jobs": len(g),
                     "loss": g["loss_"].sum(), "driver": dv.index[0], "same": len(dv) == 1})
    parts = pd.DataFrame(rows).sort_values("loss", ascending=False); top15 = parts.head(15)
    cum = (loss["loss_"].cumsum() / tot_loss).to_numpy()
    half_n = int((cum >= 0.5).argmax()) + 1
    top_half = loss.head(half_n)
    in_half = lambda dr: int((top_half["driver"] == dr).sum())
    n_other = int((~top_half["driver"].isin(["Routing standard", "Unbilled revision work", "Priced below estimated cost", "Not attributable"])).sum())
    other_clause = f", and the other {n_other} carry other drivers" if n_other else ""
    estimator_drivers = ["Routing standard", "Priced below estimated cost", "New or infrequent part setup", "Vendor rate"]
    floor_drivers = ["Unbilled revision work", "Scrap and rework", "Material"]
    job_share = lambda drvs: by_driver.loc[drvs, "jobs"].sum() / len(loss)

    toc = "".join([
        '<a href="#distribution">1 &middot; Job Margin Overview</a>',
        '<a href="#elements">2 &middot; Job Cost Overruns</a>',
        '<a href="#rates">3 &middot; Blended Rate Adjustments</a>',
        '<a href="#losses">4 &middot; Jobs that Lost Money</a>',
    ])

    body = f"""
{B.section("distribution", "Section 1", "Job Margin Overview")}
<p>In {YEAR}, the shop earned {km(rev25)} of revenue from {len(j25):,} jobs. It earned {km(j25['contribution'].sum())} of gross margin (revenue less
variable production costs and overhead), a {pct(margin25, 1)} rate. This actual margin was {round(est_m25 * 100, 1) - round(margin25 * 100, 1):.1f} percentage points lower than the
{pct(est_m25, 1)} rate the shop's estimates promised as actual job costs came in {k(over)} over the jobs' estimates.</p>
<p>At the job-level, the average margin was {pct(m_mean, 1)} in {YEAR} against the {pct(est_mean, 1)} estimates. Larger jobs carry a higher margin, which
is why the shop's total margin was {round(margin25 * 100, 1) - round(m_mean * 100, 1):.1f} percentage points higher than the job-level average. In the distribution below, we see
that {int(above_avg.sum()):,} jobs ({pct(above_avg.mean())} of total) had margins above the {pct(m_mean, 1)} average and {int((~above_avg).sum()):,} jobs
({pct((~above_avg).mean())}) were below it, while {int(neg.sum()):,} jobs ({pct(neg.mean(), 1)}) lost money. The second chart shows each job's actual
margin less its estimated margin: {pct((gap < 0).mean())} of jobs came in below their estimate, by a median of {-gap[gap < 0].median() * 100:.0f} points,
and the red bars are the {pct((gap < -0.20).mean())} more than 20 points below.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin Distribution", chart_histogram(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin", chart_margin_gap(j25))}
</div>
<p>Jobs on repeat parts carry a higher average margin than new quoted work ({pct(by_type['repeat']['margin_on_price'].mean(), 1)} versus
{pct(by_type['new']['margin_on_price'].mean(), 1)}). At the same time, jobs on repeat parts missed their margin estimates more frequently than new
quoted work ({pct((gap_rep < 0).mean(), 1)} vs {pct((gap_new < 0).mean(), 1)}), and the magnitude of the miss was also greater
({-gap_rep.mean() * 100:.1f} points vs {-gap_new.mean() * 100:.1f}). Jobs on both repeat parts and new quoted work lost money at
similar rates, {pct((by_type['repeat']['contribution'] < 0).mean(), 1)} and {pct((by_type['new']['contribution'] < 0).mean(), 1)}, respectively. A repeat
part's estimate comes from its original quote, and as this report details, underestimates the movements in material, rates and standards since then; a
new part's estimate is weeks old.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Type", chart_histogram_types(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Type", chart_margin_gap_panels([("Repeat parts", by_type["repeat"]), ("New quoted work", by_type["new"])]))}
</div>
<p>There are significant margin differences between jobs of different sizes. Jobs with lots under {C.SMALL_LOT_THRESHOLD} pieces average
{pct(size_avg[0], 1)} margin and lose money on {pct(size_neg[0], 1)} of them; lots of 25 to 100 pieces average {pct(size_avg[1], 1)} margin and lose money on
{pct(size_neg[1], 1)}, and lots over 100 pieces average {pct(size_avg[2], 1)} margin and lose money on {pct(size_neg[2], 1)}. The small lots also miss their
estimates by the most, an average of {-size_gap[0].mean() * 100:.1f} points against {-size_gap[1].mean() * 100:.1f} and {-size_gap[2].mean() * 100:.1f}.
The primary driver for this is that setup hours, which are consistent across jobs, have a larger impact on small jobs' lower revenue.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Size", chart_histogram_sizes(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Size", chart_margin_gap_panels([(lab, x) for (lab, _, _), x in zip(SIZE_BANDS, size_x)]))}
</div>

{B.section("elements", "Section 2", "Job Cost Overruns")}
<p>As shown above, actual job margin was consistently lower than estimated. The reason for this is that the actual job costs overrun in {YEAR} was
{k(over)}. As the chart below shows, the primary drivers were {bridge[0][0].lower()} and {bridge[1][0].lower()}.</p>
{B.chart(f"Actual Cost against Estimate on the {YEAR} Jobs, by Element", chart_bridge([lab for lab, _ in bridge], [v for _, v in bridge], "Net over\nestimate"))}
<p>A significant portion of this {k(over)} cost overrun is from cost elements not being included in the quote ({k(not_quoted)} total;
{k(osp_noq_over)} of outside processing and {k(b['c_scrap_rework'].sum())} of scrap and rework).</p>
<p>Of the remaining {k(over - not_quoted)}:</p>
<ul style="margin:0 0 16px 56px;">
<li><strong>Run hours</strong> came in {k(b['c_run'].sum())} over estimate on net, with the median job at {run_med:.2f}&times; its estimated run
hours.</li>
<li><strong>Outside processing</strong> came in {k(b['c_outside'].sum() - osp_noq_over)} over on net; on the {int(both.sum()):,}
jobs with both an estimate and a purchase order, invoices came to {po_ratio:.2f}&times; the estimates.</li>
<li><strong>Setup hours</strong> came in {k(b['c_setup'].sum())} over on net: the median job took {s_far:.2f}&times; its estimated setup on a part's
first run after a revision (versus {s_known:.2f}&times; on a part run within the year).</li>
</ul>
{el_table}

{B.section("rates", "Section 3", "Blended Rate Adjustments")}
<p>The shop's existing quote system costed every labor hour at one blended shop rate, ${C.BLENDED_RATE[YEAR]:,.0f} in {YEAR} and
${C.BLENDED_RATE[YEAR + 1]:,.0f} in {YEAR + 1}. The work-center pools, as set in {pd.Timestamp(C.CONFIG_DATES['rate_pools_live']):%B %Y}, run from
${pg.iloc[0]:,.0f} an hour at {CELL.get(pg.index[0], pg.index[0]).lower()} to ${pg.iloc[-1]:,.0f} at the {CELL.get(pg.index[-1], pg.index[-1]).lower()} cell.</p>
{B.chart("Work-center Pool Rates against the Blended Shop Rate", pool_png)}
<p>The chart below shows the impact on reported vs. actual margin by part family after accounting for differences in work-center pool rates. Costed at
the pools, the families that run on the manual and secondary cells gain margin vs. their reported figures ({gainers['part_family'].iloc[0]}
{gainers['margin_points_moved'].iloc[0] * 100:+.1f} points, {gainers['part_family'].iloc[1]} {gainers['margin_points_moved'].iloc[1] * 100:+.1f}) and the
families that run on the more expensive cells lose margin vs. their reported figures ({losers['part_family'].iloc[0]}
{losers['margin_points_moved'].iloc[0] * 100:.1f}, {losers['part_family'].iloc[1]} {losers['margin_points_moved'].iloc[1] * 100:.1f}). {top_blended[0]} is the
shop's highest margin part family at the blended rate and number {top_pool.index(top_blended[0]) + 1} of {len(fam)} at the pools.</p>
{B.chart(f"Margin by Part Family at the Blended Rate and at the Pool Rates, {YEAR} Jobs", chart_family_rates(fam))}
{fam_table}

{B.section("losses", "Section 4", "Jobs that Lost Money")}
<p>Of the {len(j25):,} jobs in {YEAR}, {len(loss):,} ({pct(len(loss) / len(j25), 1)}) lost money, {k1(tot_loss)} in total. Only {len(est_loss)} of these jobs
were estimated to lose money before they started. The other {len(est_gain):,} were estimated to make money, at a median estimated margin of
{pct(est_gain['estimated_margin_on_price'].median())}, and lost it during the job; they account for {pct(est_gain['loss_'].sum() / tot_loss)} of the loss.
In the ERP, each job carries a cost overrun driver with an accompanying action the driver maps to.</p>
{sub("Loss making jobs by driver")}
<p>The chart shows the number of loss-making jobs by driver as well as the total associated loss. Overruns on routing standards accounted for
{int(by_driver.loc['Routing standard', 'jobs'])} of the loss-making jobs ({pct(job_share(['Routing standard']), 1)} of total), or
{k1(by_driver.loc['Routing standard', 'loss'])}. Along with routing standards, the other drivers that sit with the estimator, including prices set
below estimated cost, setups on new or infrequent parts and vendor rate, account for {pct(job_share(estimator_drivers), 1)} of the jobs that lost
money, or {pct(drv_share(estimator_drivers), 1)} of the total loss. The drivers that sit with the floor and the front office, unbilled revision work,
scrap and rework and material, account for {pct(job_share(floor_drivers), 1)} of the jobs that lost money, or {pct(drv_share(floor_drivers), 1)} of
the total loss. On {len(accepted)} jobs, {k1(accepted['loss_'].sum())} of the {k1(tot_loss)}, no single driver accounts for the cost overrun; those
jobs are excluded from the chart below.</p>
{B.chart(f"Loss making jobs by driver, {YEAR}", chart_loss_by_driver(by_driver))}
{sub("Loss making jobs, actual vs. estimated margin")}
<p>The chart lays out each loss-making job, placed by the margin the estimate promised and the margin the job actually earned. Dots left of the
vertical line were expected to lose money; the rest were not. The routing-standard jobs were estimated at a median margin of
{pct(routing['estimated_margin_on_price'].median())} and fell a median of {routing['fall'].median() * 100:.0f} points. The jobs with unbilled
revision work fell a median of {revision['fall'].median() * 100:.0f} points, and the {len(furthest)} jobs driven by
{fall_med.index[0][0].lower() + fall_med.index[0][1:]} fell the furthest, a median of {fall_med.iloc[0] * 100:.0f} points.</p>
{B.chart(f"Loss making jobs, actual vs. estimated margin, {YEAR}", chart_est_vs_actual(loss))}
{sub("Parts that lost money on more than one job")}
<p>{len(parts)} parts lost money on two or more jobs in {YEAR}; they account for {int(parts['loss_jobs'].sum())} jobs and
{k1(parts['loss'].sum())} of the loss. The chart shows the fifteen largest, with how many of the part's {YEAR} jobs lost money and the driver behind
them. On {int(top15['same'].sum())} of the 15 parts the driver is the same on every loss-making job.</p>
{B.chart("The Fifteen Parts with the Largest Loss over Two or More Jobs", chart_repeat_losers(top15))}
{sub("Job loss concentration")}
<p>The chart below shows the cumulative share of the total loss by job. The {half_n} largest job losses account for {pct(cum[half_n - 1])} of the
total loss. Of the {half_n} largest, {in_half('Routing standard')} trace to a routing standard overrun, {in_half('Unbilled revision work')} to
unbilled revision work and {in_half('Priced below estimated cost')} to prices set below their own estimated cost; {in_half('Not attributable')} have
no dominant driver{other_clause}.</p>
{B.chart("Cumulative Share of the Total Loss", chart_concentration(cum, half_n))}

"""
    return body, toc


def run():
    d = gather()
    body, toc = build(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = B.page("Analytics Diagnostic Report: Job Costing &amp; Margin", "Created by Brian Davis, 2026", toc, body)
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"Margin diagnostic written to {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    run()
