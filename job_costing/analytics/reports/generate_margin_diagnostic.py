"""Analytics diagnostic report, job costing and margin -> docs/reports/margin_diagnostic.html

About the business, not the data: how margin is spread across the shop's jobs and
why, from the corrected job cost. The report attributes and does not project: the
2025 overrun is split by cost element on the jobs themselves, what a lever was
worth is what the 2025 jobs would have earned with it applied, and nothing is
summed into an "opportunity". Every number is read from a dbt mart
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
    for name, mart in [("driver", "mart_job_driver"), ("replay", "mart_inprogress_replay"), ("thresholds", "mart_inprogress_threshold_replay"),
                       ("family", "mart_margin_by_family_rate_basis"), ("release", "mart_release_setup_charge"),
                       ("queue", "mart_repricing_queue"), ("own", "mart_own_products"), ("osp", "int_osp_by_job")]:
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



# ── the report ──────────────────────────────────────────────────────────────
def build(d):
    j, j25, b, q = d["jobs"], d["j25"], d["s25"], d["queue"]
    short = d["short"]
    cov = j25.set_index("job_id")
    J = lambda ids: cov.loc[cov.index.intersection(list(ids))]
    msi = lambda ids: ms(J(ids))
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
    top25 = loss.head(25)

    funnel_png = chart_funnel(
        [("Jobs completed", len(r25)), ("Flagged", len(fl)), ("Flagged with\noperations left", len(left)), (f"...and {C_ACT} or more\ndays before ship", len(op_))],
        [("First\noperation", int(posn.get("first operation", 0))), ("A middle\noperation", int(posn.get("a middle operation", 0))), ("Last\noperation", int(posn.get("last operation", 0)))])

    toc = "".join([
        '<a href="#distribution">1 &middot; Job Margin Overview</a>',
        '<a href="#elements">2 &middot; Actual Cost against Estimate, by Element</a>',
        '<a href="#rates">3 &middot; What the Blended Rate Hid</a>',
        '<a href="#inprogress">4 &middot; Jobs Caught in Progress</a>',
        '<a href="#repricing">5 &middot; Repricing</a>',
        '<a href="#losses">6 &middot; The Jobs That Lost Money</a>',
    ])

    body = f"""
<p>This report details the findings from the shop's new job costing functionality. Presented below is analysis of job margins, job cost
overruns vs. estimates, blended vs. work-center pool rates, job cost overrun flags, repricing opportunities, and the characteristics of jobs with
negative margins.</p>

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
quoted work ({pct((gap_rep < 0).mean(), 1)} vs {pct((gap_new < 0).mean(), 1)}). Against their estimates, jobs on repeat parts missed by an average of
{-gap_rep.mean() * 100:.1f} points versus new quoted work at {-gap_new.mean() * 100:.1f}. Jobs on both repeat parts and new quoted work lost money at
similar rates, {pct((by_type['repeat']['contribution'] < 0).mean(), 1)} and {pct((by_type['new']['contribution'] < 0).mean(), 1)}, respectively. A repeat
part's estimate comes from its original quote, so its gap carries every movement in material, rates and standards since then; a new part's estimate is
weeks old. The panels in each chart share a scale.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Type", chart_histogram_types(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Type", chart_margin_gap_panels([("Repeat parts", by_type["repeat"]), ("New quoted work", by_type["new"])]))}
</div>
<p>There are significant margin differences between jobs of different sizes. Jobs with lots under {C.SMALL_LOT_THRESHOLD} pieces average
{pct(size_avg[0], 1)} a job and lose money on {pct(size_neg[0], 1)} of them; lots of 25 to 100 pieces average {pct(size_avg[1], 1)} and lose money on
{pct(size_neg[1], 1)}, and lots over 100 pieces average {pct(size_avg[2], 1)} and lose money on {pct(size_neg[2], 1)}. The small lots also miss their
estimates by the most, an average of {-size_gap[0].mean() * 100:.1f} points against {-size_gap[1].mean() * 100:.1f} and {-size_gap[2].mean() * 100:.1f}.
The primary reason for this is that setup hours, which are consistent across jobs, have a larger impact on small jobs' lower revenue.</p>
<div class="chart-stack">
{B.chart(f"{YEAR} Job Margin, by Job Size", chart_histogram_sizes(j25))}
{B.chart(f"{YEAR} Actual vs. Estimated Job Margin, by Job Size", chart_margin_gap_panels([(lab, x) for (lab, _, _), x in zip(SIZE_BANDS, size_x)]))}
</div>

{B.section("elements", "Section 2", "Actual Cost against Estimate, by Element")}
<p>As shown above, actual job margin was consistently lower than estimated. The reason for this is that the actual job costs overrun in {YEAR} was
{k(over)}. As the chart below shows, the primary drivers were {bridge[0][0].lower()} and {bridge[1][0].lower()}.</p>
{B.chart(f"Actual Cost against Estimate on the {YEAR} Jobs, by Element", chart_bridge([lab for lab, _ in bridge], [v for _, v in bridge], "Net over\nestimate"))}
<p>A significant portion of this {k(over)} cost overrun is from cost elements not being included in the quote ({k(not_quoted)} total;
{k(osp_noq_over)} of outside processing and {k(b['c_scrap_rework'].sum())} of scrap and rework).</p>
<p>Of the remaining {k(over - not_quoted)}:</p>
<ul>
<li><strong>Run hours</strong> came in {k(b['c_run'].sum())} over estimate on net: {k(b['c_run'].clip(lower=0).sum())} over on
{int((b['c_run'] > 1).sum()):,} jobs and {k(-b['c_run'].clip(upper=0).sum())} under on the rest, with the median job at {run_med:.2f}&times; its
estimated run hours.</li>
<li><strong>Outside processing</strong> that was in the quote came in {k(b['c_outside'].sum() - osp_noq_over)} over on net; on the {int(both.sum()):,}
jobs with both an estimate and a purchase order, invoices came to {po_ratio:.2f}&times; the estimates.</li>
<li><strong>Setup hours</strong> came in {k(b['c_setup'].sum())} over on net ({k(b['c_setup'].clip(lower=0).sum())} over and
{k(-b['c_setup'].clip(upper=0).sum())} under): the median job took {s_known:.2f}&times; its estimated setup on a part run within the year and
{s_far:.2f}&times; on the first run after a revision. Material came in {k(-b['c_material'].sum())} under.</li>
</ul>
{el_table}

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
at list. The list moves to current cost plus the markup at the next price list.</p>
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
Job Variance report applies to every job, and the action the driver maps to: correct the routing standard, correct the quote, bill the change
order, reprice the part, fix the process, or accept it as a one-off. This is the list the owner and estimator work from, and it matches what they see in
the ERP.</p>
{sub("Loss-making Jobs by Action")}
{act_table}
<p>Of the 25 largest losses, {int((top25['primary'] == 'Routing standard').sum())} trace to a routing standard the part's jobs keep
overrunning, {int((top25['primary'] == 'Unbilled revision work').sum())} are unbilled revision work, {int((top25['primary'] == 'Priced below estimated cost').sum())} were
priced below their own estimated cost, {int((top25['primary'] == 'Not attributable').sum())} fire no rule with a dominant share and are accepted as one-offs, and
the other {int((~top25['primary'].isin(['Routing standard', 'Unbilled revision work', 'Priced below estimated cost', 'Not attributable'])).sum())} carry other drivers.</p>

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
