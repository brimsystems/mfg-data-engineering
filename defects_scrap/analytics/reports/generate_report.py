"""
Analytics diagnostic report: defect rates and scrap cost.

Reads the marts through findings.py, draws every chart, and writes the report
to analytics/reports/report.html and docs/reports/report.html.

Usage: python generate_report.py
"""
import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import findings as F

HERE = Path(__file__).resolve().parent
OUTPUTS = [HERE / "report.html", F.REPO / "docs" / "reports" / "report.html"]

# ── Palette (BRIM house style) ─────────────────────────────────────────────
DARK_GREY  = "#322B4B"   # header bars, titles, divider lines
BG_GREY    = "#F3F5F7"   # box and card backgrounds
TEXT       = "#000000"
DARK_BLUE  = "#381FA1"   # chart primary
LIGHT_BLUE = "#54C0E8"   # chart secondary
ACCENT_RED = "#CC0000"   # chart accent
MUTED_RED  = "#FFA3A3"
MED_GREY   = "#8093A4"   # chart neutral
LIGHT_GREY = "#D5DCE1"   # gridlines
MEAN_GREY  = "#4A5563"   # mean reference lines
GREEN      = "#00A84C"
AMBER      = "#FFBA3F"
HEAT_CMAP = LinearSegmentedColormap.from_list("brim_heat", [BG_GREY, LIGHT_BLUE, DARK_BLUE])
CODE_COLORS = {"Bend Angle": DARK_BLUE, "Dimensional": LIGHT_BLUE, "Burr": MED_GREY, "Surface Scratch": LIGHT_GREY,
               "Weld Defect": MUTED_RED, "Porosity": ACCENT_RED, "Surface Contamination": AMBER,
               "Incorrect Material": GREEN}

CHART_W, CHART_H, CHART_DPI = 8.2, 3.8, 130
BODY_FS, TITLE_FS = 11, 13
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": LIGHT_GREY, "axes.grid": False,
    "font.family": "sans-serif", "font.size": BODY_FS, "axes.titlesize": TITLE_FS, "axes.titleweight": "bold",
    "axes.labelsize": BODY_FS, "xtick.labelsize": BODY_FS, "ytick.labelsize": BODY_FS, "legend.fontsize": BODY_FS,
    "text.color": TEXT, "axes.labelcolor": TEXT, "xtick.color": TEXT, "ytick.color": TEXT, "figure.dpi": CHART_DPI,
})


def chart_style(ax):
    ax.yaxis.grid(True, color=LIGHT_GREY, linestyle="-", linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LIGHT_GREY)


def make_fig(h=None, w=None):
    return plt.subplots(figsize=(w or CHART_W, h or CHART_H))


def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=CHART_DPI, metadata={"Software": None})
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def pct_axis(ax, decimals=0):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.{decimals}f}%"))


def month_ticks(ax, months, step=3):
    x = np.arange(len(months))
    ax.set_xticks(x[::step])
    ax.set_xticklabels([pd.Timestamp(m).strftime("%b '%y") for m in months][::step], rotation=45, ha="right")
    return x


def bar_chart(labels, values, colors, ylabel, counts=None, h=None, ymax=None):
    """Bars of rates in percent, labelled with the rate and, below, the job count."""
    fig, ax = make_fig(h)
    x = np.arange(len(labels))
    ax.bar(x, values, color=colors, width=0.6)
    top = ymax or max(values) * 1.22
    for xi, v in zip(x, values):
        ax.text(xi, v + top * 0.015, f"{v:.1f}%", ha="center", va="bottom", fontsize=BODY_FS, fontweight="bold")
    ticks = [f"{l}\n({c:,} jobs)" for l, c in zip(labels, counts)] if counts is not None else labels
    ax.set_xticks(x); ax.set_xticklabels(ticks)
    ax.set_ylabel(ylabel); ax.set_ylim(0, top); pct_axis(ax)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def grouped_bars(groups, series, ylabel, colors, h=None, ymax=None, note=None):
    """`series` maps a legend label to one value per group, in percent."""
    fig, ax = make_fig(h)
    x = np.arange(len(groups)); w = 0.8 / len(series)
    top = ymax or max(v for vals in series.values() for v in vals if not np.isnan(v)) * 1.22
    for i, (label, vals) in enumerate(series.items()):
        pos = x + (i - (len(series) - 1) / 2) * w
        ax.bar(pos, vals, width=w * 0.92, color=colors[i], label=label)
        for xi, v in zip(pos, vals):
            if not np.isnan(v):
                ax.text(xi, v + top * 0.012, f"{v:.1f}%", ha="center", va="bottom", fontsize=BODY_FS - 1)
    ax.set_xticks(x); ax.set_xticklabels(groups)
    ax.set_ylabel(ylabel); ax.set_ylim(0, top); pct_axis(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=len(series), frameon=False)
    if note:
        ax.text(0.99, 0.97, note, transform=ax.transAxes, ha="right", va="top", fontsize=BODY_FS - 2, color=MED_GREY)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def dual_monthly(months, bars, bar_label, line, line_label, bar_fmt="{:.1f}%", line_fmt="{:.1f}%", line_color=DARK_BLUE):
    """Monthly bars on the left axis and a line on the right axis."""
    fig, ax = make_fig()
    x = month_ticks(ax, months)
    ax.bar(x, bars, color=LIGHT_BLUE, width=0.7, label=bar_label)
    ax.set_ylabel(bar_label); ax.set_ylim(0, np.nanmax(bars) * 1.35)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: bar_fmt.format(v)))
    ax2 = ax.twinx()
    ax2.plot(x, line, color=line_color, linewidth=2, marker="o", markersize=3, label=line_label)
    ax2.set_ylabel(line_label); ax2.set_ylim(0, np.nanmax(line) * 1.35)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: line_fmt.format(v)))
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    chart_style(ax); ax2.grid(False); ax2.spines["top"].set_visible(False)
    plt.tight_layout()
    return fig_to_b64(fig)


# ── Data ─────────────────────────────────────────────────────────────────────
d = F.load()
T = F.build()
months = sorted(d["production_month"].unique())
n_months = len(months)
years = F.window_years(d)          # days in the window over 365.25
ttm_months = months[-12:]
ttm = d[d["production_month"].isin(ttm_months)]
DATE_MIN, DATE_MAX = pd.Timestamp(months[0]).strftime("%B %Y"), pd.Timestamp(months[-1]).strftime("%B %Y")
TTM_MIN, TTM_MAX = pd.Timestamp(ttm_months[0]).strftime("%B %Y"), pd.Timestamp(ttm_months[-1]).strftime("%B %Y")

rate, code_rate = F.rate, F.code_rate
BEND = ["Bend Angle"]
overall = rate(d)
cost_year = d["scrap_cost"].sum() / years
cost_share = d["scrap_cost"].sum() / d["revenue"].sum()
# the shop's defect rate target, and what reaching it is worth at current volume and defect mix
TARGET_RATE = 0.045
target_save = cost_year * (overall - TARGET_RATE) / overall


def row(table, group):
    t = T[table]
    return t[t["Group"] == group].iloc[0]


def mult(r):
    return f"{r['Multiplier']:.2f}&times;"


def pc(x, n=1):
    return f"{x:.{n}%}"


def usd_k(x):
    return f"${x / 1e3:,.0f}K"


fin = T["7.1 Financial impact: one row per finding"].set_index("Finding")
FIN_ROWS = [k for k in fin.index if not k.startswith("4b")]
save = {k[0]: fin.loc[k, "Savings a year"] for k in FIN_ROWS}
total_save = sum(save.values())
overlap = T["7.2 Overlap between the finding segments"].iloc[0]

known = d[d["supplier"].notna()]
brake = d[d["machine_type"] == "Bending"]
bm = brake[brake["thickness_deviation_band"].notna()]
first, second, later = (d[d["run_position"] == k] for k in (1, 2, 3))
rush, routine = d[d["is_rush"]], d[~d["is_rush"]]
gs = d[d["is_gauge_steel"] & d["lot_age_band"].notna()]
other_mat = d[~d["is_gauge_steel"] & d["lot_age_band"].notna()]

r_sup_all = row("0.6 The shop's own view as multipliers", "Supplier C, all jobs")
r_cx = row("0.6 The shop's own view as multipliers", "High complexity")
r_cx_later = row("0.8 Restatement: complexity within later runs (first and second runs left out)", "High complexity, later runs")
r_dev = row("1.2 Bend-angle rate against the under 1% band (brake jobs)", "2% and over")
r_dev_top = row("1.2 Bend-angle rate against the under 1% band (brake jobs)", "over 4%")
r_sup_brake = row("1.4 Supplier C against the others on brake jobs (all defect codes)", "Supplier C, brake jobs")
r_first = row("2.1 Defect rate by run position on the drawing revision", "First run")
r_second = row("2.1 Defect rate by run position on the drawing revision", "Second run")
r_change = row("3.1 Brake jobs after a gauge change against jobs following the same gauge", "After a gauge change, bend-angle rate")
r_change_all = row("3.1 Brake jobs after a gauge change against jobs following the same gauge", "After a gauge change, all defect codes")
r_laser = row("3.4 Laser jobs after a gauge change (no effect expected)", "Laser job after a gauge change")
SP = "4.1 Schedule pressure: rate tables"
r_rush, r_nofp = row(SP, "Rush jobs"), row(SP, "No first-piece record")
EX = "5.1 Defect rate by cumulative jobs on the machine type"
r_exp50, r_exp150, r_exp300 = row(EX, "under 50"), row(EX, "50 to 150"), row(EX, "150 to 300")
LA = "6.1 Gauge steel: defect rate by days since receipt"
r_age60, r_age120, r_age_all = row(LA, "60 to 120 days"), row(LA, "over 120 days"), row(LA, "60 days and over")
r_age_other = row(LA, "Other materials, 60 days and over")
comp1 = T["1.6 Jobs by lot information available"].iloc[0]
lots_sup = T["1.5 Lots received by supplier: measurement, deviation and cert status"].set_index("supplier")
comp2 = T["2.3 First runs: composition"].iloc[0]
comp3 = T["3.5 Gauge changes on the brakes: composition"].iloc[0]
comp4 = T["4.2 Schedule pressure: composition"].iloc[0]
comp5 = T["5.3 Experience: composition"].iloc[0]
comp6 = T["6.4 Lot age: composition"].iloc[0]
within = T["0.7 Restatement: Supplier C against the others within thickness deviation band (brake jobs, bend-angle rate)"].set_index("Deviation band")
cx_first = T["2.2 Defect rate by complexity, first runs against later runs"].set_index("Complexity")


# ═══════════════════════════════════════════════════════════════════════════
# CHARTS (each returns a base64 PNG string)
# ═══════════════════════════════════════════════════════════════════════════
def chart_defect_trend():
    m = ttm.groupby("production_month").agg(qi=("quantity_inspected", "sum"), qf=("quantity_failed", "sum")).reset_index()
    x = np.arange(len(m)); r = m["qf"] / m["qi"] * 100
    fig, ax = make_fig()
    ax.bar(x, m["qf"], color=LIGHT_BLUE, width=0.62, label="Pieces failed")
    for xi, v in zip(x, m["qf"]):
        ax.text(xi, m["qf"].max() * 0.03, f"{v:,.0f}", ha="center", va="bottom", fontsize=BODY_FS - 2)
    ax.set_ylabel("Pieces failed"); ax.set_ylim(0, m["qf"].max() * 1.75)
    ax2 = ax.twinx()
    ax2.plot(x, r, color=DARK_BLUE, linewidth=2, marker="o", markersize=4, label="Defect rate")
    for xi, v in zip(x, r):
        ax2.text(xi, v + 0.35, f"{v:.1f}%", ha="center", va="bottom", fontsize=BODY_FS - 2, color=DARK_BLUE, fontweight="bold")
    ax2.axhline(overall * 100, color=MEAN_GREY, linestyle="--", linewidth=1.5, label=f"Mean ({overall:.1%})")
    ax2.axhline(TARGET_RATE * 100, color=ACCENT_RED, linestyle="--", linewidth=1.5, label=f"Target ({TARGET_RATE:.1%})")
    ax2.set_ylabel("Defect rate"); ax2.set_ylim(0, 9.5); pct_axis(ax2)
    ax.set_xticks(x); ax.set_xticklabels([pd.Timestamp(v).strftime("%b '%y") for v in m["production_month"]], rotation=45, ha="right")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=4, frameon=False, columnspacing=1.2)
    chart_style(ax); ax2.grid(False); plt.tight_layout()
    return fig_to_b64(fig)


def chart_cost_trend():
    m = ttm.groupby("production_month")["scrap_cost"].sum().reset_index()
    x = np.arange(len(m)); v = m["scrap_cost"] / 1000
    mean_month = d["scrap_cost"].sum() / n_months / 1000
    fig, ax = make_fig()
    ax.bar(x, v, color=DARK_BLUE, width=0.65)
    for xi, val in zip(x, v):
        ax.text(xi, val + v.max() * 0.02, f"${val:,.0f}K", ha="center", va="bottom", fontsize=BODY_FS - 2)
    ax.axhline(mean_month, color=MEAN_GREY, linestyle="--", linewidth=1.5, label=f"Mean (${mean_month:,.0f}K a month)")
    ax.set_xticks(x); ax.set_xticklabels([pd.Timestamp(t).strftime("%b '%y") for t in m["production_month"]], rotation=45, ha="right")
    ax.set_ylim(0, v.max() * 1.22); ax.set_ylabel("Scrap and rework cost")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda t, _: f"${t:,.0f}K"))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def chart_overlap():
    labels = ["None", "One", "Two", "Three or more"]
    vals = [overlap[k] * 100 for k in ("Rate, no segment", "Rate, one", "Rate, two", "Rate, three or more")]
    counts = [int(overlap[k]) for k in ("Jobs in no segment", "In one segment", "In two", "In three or more")]
    return bar_chart(labels, vals, [MED_GREY, LIGHT_BLUE, DARK_BLUE, ACCENT_RED], "Defect rate", counts, h=3.4)


def chart_supplier_view():
    t = T["0.3 The shop's own view: defect rate by supplier (all jobs with a scanned lot)"]
    colors = [DARK_BLUE if s == "Supplier C" else MED_GREY for s in t["supplier"]]
    return bar_chart(list(t["supplier"]), list(t["Rate"] * 100), colors, "Defect rate, all jobs", list(t["Jobs"]), h=3.4)


def chart_dev_by_supplier():
    fig, ax = make_fig()
    x = np.arange(len(F.DEVIATION_BANDS))
    styles = {"Supplier A": (MED_GREY, "o"), "Supplier B": (LIGHT_BLUE, "s"), "Supplier C": (DARK_BLUE, "D"), "Supplier D": (MUTED_RED, "^")}
    for sup, (color, marker) in styles.items():
        g = bm[bm["supplier"] == sup]
        ys = []
        for band in F.DEVIATION_BANDS:
            b = g[g["thickness_deviation_band"] == band]
            ys.append(code_rate(b, BEND) * 100 if len(b) >= 30 else np.nan)
        ax.plot(x, ys, color=color, marker=marker, linewidth=2.2 if sup == "Supplier C" else 1.6, markersize=6, label=sup)
    ax.set_xticks(x); ax.set_xticklabels(F.DEVIATION_BANDS)
    ax.set_xlabel("Lot thickness deviation from nominal at receiving"); ax.set_ylabel("Bend-angle defect rate,\nbrake jobs")
    ax.set_ylim(0, 11); pct_axis(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=4, frameon=False)
    top_band = bm[bm["thickness_deviation_band"] == F.DEVIATION_BANDS[-1]]
    n_b, n_c = (int((top_band["supplier"] == s).sum()) for s in ("Supplier B", "Supplier C"))
    ax.text(0.5, -0.36, f"Bands with fewer than 30 jobs not included.\nNote there were only {n_b} jobs from Supplier B "
            f"material >4% deviation, compared to {n_c} jobs from Supplier C", transform=ax.transAxes, ha="center", va="top",
            fontsize=BODY_FS - 2, color=MED_GREY)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def chart_run_position():
    return bar_chart(["First run", "Second run", "Later runs"], [rate(first) * 100, rate(second) * 100, rate(later) * 100],
                     [ACCENT_RED, AMBER, MED_GREY], "Defect rate", [len(first), len(second), len(later)], h=3.4)


def chart_complexity_split():
    cx = ["Low", "Medium", "High"]
    return grouped_bars(cx, {"First runs": [cx_first.loc[c, "First-run rate"] * 100 for c in cx],
                             "Later runs": [cx_first.loc[c, "Later-run rate"] * 100 for c in cx]},
                        "Defect rate", [ACCENT_RED, MED_GREY])


def chart_first_run_monthly():
    t = T["2.5 Monthly: first-run share of jobs and first-run defect rate"]
    return dual_monthly(months, t["First-run share"].values * 100, "First runs as a share of jobs",
                        t["First-run rate"].values * 100, "First-run defect rate", line_color=ACCENT_RED)


def code_mix_bars(table, columns, colors, h=4.2):
    t = T[table].set_index("Defect code")
    t = t.loc[t[columns[0]].sort_values().index]
    fig, ax = make_fig(h)
    y = np.arange(len(t)); hgt = 0.8 / len(columns)
    for i, c in enumerate(columns):
        pos = y - (i - (len(columns) - 1) / 2) * hgt      # the first column's bar sits on top
        ax.barh(pos, t[c] * 100, height=hgt * 0.9, color=colors[i], label=c)
        for yi, v in zip(pos, t[c] * 100):
            ax.text(v + 0.5, yi, f"{v:.0f}%", va="center", fontsize=BODY_FS - 2)
    ax.set_yticks(y); ax.set_yticklabels(t.index)
    ax.set_xlabel("Share of failed pieces"); ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.legend(loc="lower right", frameon=False)
    chart_style(ax); ax.yaxis.grid(False); ax.xaxis.grid(True, color=LIGHT_GREY)
    plt.tight_layout()
    return fig_to_b64(fig)


def _positions():
    pos = brake.assign(change=brake["is_after_gauge_change"].astype(int))
    pos["block"] = pos.groupby("machine_id")["change"].cumsum()
    pos["n"] = pos.groupby(["machine_id", "block"]).cumcount() + 1
    pos = pos[pos["block"] > 0]
    pos["position"] = np.where(pos["n"] == 1, "First job", np.where(pos["n"] == 2, "Second job", "Third or later"))
    return pos


POS = _positions()
POS_ORDER = ["First job", "Second job", "Third or later"]


def chart_change_position():
    g = [POS[POS["position"] == p] for p in POS_ORDER]
    return bar_chart(POS_ORDER, [code_rate(x, BEND) * 100 for x in g], [ACCENT_RED, LIGHT_BLUE, MED_GREY],
                     "Bend-angle defect rate", [len(x) for x in g], h=3.4)


def chart_change_by_brake():
    brakes = sorted(POS["machine_name"].unique())
    series = {p: [code_rate(POS[(POS["machine_name"] == b) & (POS["position"] == p)], BEND) * 100 for b in brakes] for p in POS_ORDER}
    return grouped_bars(brakes, series, "Bend-angle defect rate", [ACCENT_RED, LIGHT_BLUE, MED_GREY], h=3.4)


def chart_change_heatmap():
    t = POS.assign(hour=POS["job_start"].dt.hour).groupby(["position", "hour"]).size().unstack(fill_value=0).reindex(POS_ORDER)
    hours = [h for h in list(range(6, 24)) + [0, 1] if h in t.columns]
    t = t[hours]
    fig, ax = make_fig(h=2.9)
    im = ax.imshow(t.values, aspect="auto", cmap=HEAT_CMAP)
    ax.set_xticks(range(len(hours))); ax.set_xticklabels([f"{h:02d}" for h in hours])
    ax.set_yticks(range(len(POS_ORDER))); ax.set_yticklabels(POS_ORDER)
    ax.set_xlabel("Hour of day the job started")
    for i in range(t.shape[0]):
        for j in range(t.shape[1]):
            v = t.values[i, j]
            ax.text(j, i, f"{v}", ha="center", va="center", fontsize=BODY_FS - 3, color="white" if v > t.values.max() * 0.55 else TEXT)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02); cb.set_label("Brake jobs")
    plt.tight_layout()
    return fig_to_b64(fig)


def chart_rush():
    return bar_chart(["Rush", "Routine"], [rate(rush) * 100, rate(routine) * 100], [ACCENT_RED, MED_GREY],
                     "Defect rate", [len(rush), len(routine)], h=3.2)


def chart_first_piece_split():
    g = lambda x, fp: rate(x[x["has_first_piece_inspection"] == fp]) * 100
    return grouped_bars(["Rush jobs", "Routine jobs"], {"No first-piece record": [g(rush, False), g(routine, False)],
                                                        "First-piece record": [g(rush, True), g(routine, True)]},
                        "Defect rate", [ACCENT_RED, MED_GREY], h=3.4)


def chart_first_piece_monthly():
    t = T["4.4 Monthly: rush share, first-piece presence and jobs past the tenth hour"]
    fig, ax = make_fig()
    x = month_ticks(ax, months)
    ax.bar(x, t["Rush share"] * 100, color=LIGHT_BLUE, width=0.7, label="Rush share of jobs")
    ax.set_ylabel("Rush share of jobs"); ax.set_ylim(0, 40); pct_axis(ax)
    ax2 = ax.twinx()
    ax2.plot(x, t["First-piece presence"] * 100, color=DARK_BLUE, linewidth=2, marker="o", markersize=3, label="Jobs with a first-piece record")
    ax2.set_ylabel("Jobs with a first-piece record"); ax2.set_ylim(60, 90); pct_axis(ax2)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    chart_style(ax); ax2.grid(False); plt.tight_layout()
    return fig_to_b64(fig)


def chart_experience():
    g = [d[d["experience_band"] == b] for b in F.EXPERIENCE_BANDS]
    return bar_chart([f"{b} jobs" for b in F.EXPERIENCE_BANDS], [rate(x) * 100 for x in g],
                     [ACCENT_RED, AMBER, LIGHT_BLUE, MED_GREY], "Defect rate", [len(x) for x in g], h=3.6)


def chart_experience_groups():
    t = T["5.2 The experience curve for new hires and for coverage jobs"]
    fig, ax = make_fig(h=3.6)
    x = np.arange(len(F.EXPERIENCE_BANDS))
    for label, color, marker in (("Operators hired in the period", DARK_BLUE, "o"), ("Coverage jobs (secondary machine type)", LIGHT_BLUE, "s")):
        g = t[t["Group"] == label].set_index("Experience band").loc[F.EXPERIENCE_BANDS]
        ax.plot(x, g["Rate"] * 100, color=color, marker=marker, linewidth=2, markersize=6, label=label)
    allj = [rate(d[d["experience_band"] == b]) * 100 for b in F.EXPERIENCE_BANDS]
    ax.plot(x, allj, color=MED_GREY, linestyle=":", linewidth=1.6, label="All jobs")
    ax.set_xticks(x); ax.set_xticklabels([f"{b} jobs" for b in F.EXPERIENCE_BANDS])
    ax.set_xlabel("Jobs the operator had run on the machine type"); ax.set_ylabel("Defect rate"); ax.set_ylim(0, 14); pct_axis(ax)
    ax.legend(loc="upper right", frameon=False)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def chart_operators():
    t = T["5.4 Current roster: experience and defect rate by operator and machine type (50 jobs or more in the period)"]
    types = ["Laser Cutting", "Bending", "Welding", "Punching"]
    fig, axes = plt.subplots(1, 4, figsize=(CHART_W, 3.3), sharey=True)
    for ax, mt in zip(axes, types):
        g = t[t["machine_type"] == mt]
        for cover, color, label in ((False, DARK_BLUE, "Primary machine type"), (True, LIGHT_BLUE, "Coverage")):
            x = g[g["is_coverage"] == cover]
            ax.scatter(x["Jobs on the machine type at the end"], x["Rate"] * 100, s=28, color=color, label=label, alpha=0.9)
        ax.set_xscale("log"); ax.set_title(mt, fontsize=BODY_FS); ax.set_xlabel("Jobs by Operator")
        ax.set_xlim(50, 12000); ax.set_xticks([100, 1000, 10000])
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.xaxis.set_minor_formatter(mticker.NullFormatter())
        chart_style(ax)
    axes[0].set_ylabel("Defect rate in the period"); pct_axis(axes[0])
    handles, labels = axes[0].get_legend_handles_labels()
    plt.tight_layout()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=2, frameon=False, fontsize=BODY_FS - 1)
    return fig_to_b64(fig)


def chart_lot_age():
    t = T["6.2 Defect rate by lot age band and material group"]
    series = {m: list(t[t["Material"] == m].set_index("Lot age").loc[F.LOT_AGE_BANDS, "Rate"] * 100)
              for m in ("Gauge steel", "Plate, aluminum and stainless")}
    return grouped_bars(F.LOT_AGE_BANDS, series, "Defect rate", [DARK_BLUE, MED_GREY], h=3.6)


def chart_lot_age_codes():
    t = T["6.3 Defect code mix on gauge steel by lot age band"].set_index("Defect code")[F.LOT_AGE_BANDS]
    fig, ax = make_fig(h=3.8)
    bottoms = np.zeros(len(F.LOT_AGE_BANDS))
    for code in ["Surface Contamination", "Porosity", "Bend Angle", "Dimensional", "Burr", "Surface Scratch", "Weld Defect", "Incorrect Material"]:
        if code not in t.index:
            continue
        v = t.loc[code].values * 100
        ax.bar(F.LOT_AGE_BANDS, v, bottom=bottoms, color=CODE_COLORS[code], width=0.6, label=code)
        for i, (val, b) in enumerate(zip(v, bottoms)):
            if val >= 6:
                ax.text(i, b + val / 2, f"{val:.0f}%", ha="center", va="center", fontsize=BODY_FS - 2,
                        color="white" if code in ("Bend Angle", "Porosity", "Burr") else TEXT)
        bottoms += v
    ax.set_ylim(0, 100); ax.set_ylabel("Share of failed pieces, gauge steel"); pct_axis(ax)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=BODY_FS - 1)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


def chart_lot_age_monthly():
    t = T["6.5 Monthly: share of gauge-steel jobs on lots 60 days and over"]
    fig, ax = make_fig(h=3.3)
    x = month_ticks(ax, months)
    ax.bar(x, t["On lots 60 days and over"] * 100, color=DARK_BLUE, width=0.7)
    ax.set_ylabel("Gauge-steel jobs on lots 60 days and over"); pct_axis(ax)
    chart_style(ax); plt.tight_layout()
    return fig_to_b64(fig)


print("Generating charts...")
charts = {
    "defect_trend": chart_defect_trend(), "cost_trend": chart_cost_trend(), "overlap": chart_overlap(),
    "supplier_view": chart_supplier_view(), "dev_by_supplier": chart_dev_by_supplier(),
    "run_position": chart_run_position(), "complexity_split": chart_complexity_split(),
    "first_run_monthly": chart_first_run_monthly(),
    "first_run_codes": code_mix_bars("2.4 Defect code mix: first runs against later runs", ["First runs", "Later runs"], [ACCENT_RED, MED_GREY]),
    "change_position": chart_change_position(), "change_by_brake": chart_change_by_brake(), "change_heatmap": chart_change_heatmap(),
    "rush": chart_rush(), "first_piece_split": chart_first_piece_split(), "first_piece_monthly": chart_first_piece_monthly(),
    "experience": chart_experience(), "experience_groups": chart_experience_groups(),
    "operators": chart_operators(),
    "lot_age": chart_lot_age(), "lot_age_codes": chart_lot_age_codes(), "lot_age_monthly": chart_lot_age_monthly(),
}
print("Charts complete.")


# ── HTML helpers ───────────────────────────────────────────────────────────
def wrap(key, title="", caption=""):
    title_html = f'<div class="chart-title">{title}</div>' if title else ""
    caption_html = f'<div class="chart-caption">{caption}</div>' if caption else ""
    return (f'<div class="chart-wrap">{title_html}<img src="data:image/png;base64,{charts[key]}" '
            f'style="width:100%;height:auto;display:block;">{caption_html}</div>')


def bullets(items):
    return '<ul class="findings-list">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def section_title(id_, label, title):
    return (f'<div class="section-title-block" id="{id_}"><div class="section-label">{label}</div>'
            f'<h2 class="section-title">{title}</h2></div>')


def finding_block(id_, title, mult_label, mult_value, save_value, save_label):
    return f'''<div class="finding-block" id="{id_}">
      <div class="finding-left"><div class="finding-title">{title}</div></div>
      <div class="finding-right"><div class="finding-stat-group">
        <div><div class="finding-stat-val">{mult_value}</div><div class="finding-stat-lbl">{mult_label}</div></div>
        <div><div class="finding-stat-val" style="color:{GREEN};">{save_value}</div><div class="finding-stat-lbl">{save_label}</div></div>
      </div></div></div>'''


def b(x):
    return f"<strong>{x}</strong>"


# ── Bullet content ─────────────────────────────────────────────────────────
_others_off = lots_sup.drop(index="Supplier C")["Lots at 2% or over (of measured)"]
f1_bullets = bullets([
    f"On brake jobs run on lots that measured 2% or more off nominal thickness at receiving, the bend-angle defect rate is "
    f"{pc(r_dev['Rate'])} against {pc(r_dev['Comparison rate'])} on lots under 2%: {mult(r_dev)} "
    f"higher defect rate on {r_dev['Jobs']:,} jobs. The rate rises with every band, "
    f"to {pc(r_dev_top['Rate'])} on lots over 4% ({mult(r_dev_top)} the rate on lots under 1%).",
    f"The shop's own report shows this as a supplier problem: Supplier C runs at {mult(r_sup_all)} the others on all jobs "
    f"and {mult(r_sup_brake)} on brake jobs. Within the same deviation band Supplier C's bend-angle rate is level with the "
    f"others' ({pc(within.loc['under 1%', 'Supplier C bend-angle rate'])} against {pc(within.loc['under 1%', 'Others bend-angle rate'])} under 1%, "
    f"{pc(within.loc['1 to 2%', 'Supplier C bend-angle rate'])} against {pc(within.loc['1 to 2%', 'Others bend-angle rate'])} at 1 to 2%, "
    f"{pc(within.loc['2 to 4%', 'Supplier C bend-angle rate'])} against {pc(within.loc['2 to 4%', 'Others bend-angle rate'])} at 2 to 4%). "
    f"The issue is with the presence of significant (&gt;4.0%) deviation found in Supplier C's lots, which have a "
    f"{pc(within.loc['over 4%', 'Supplier C bend-angle rate'])} bend-angle defect rate.",
    f"The variation present in Supplier C's lots is higher than other suppliers: {pc(lots_sup.loc['Supplier C', 'Lots at 2% or over (of measured)'], 0)} "
    f"of its measured lots are 2% or more off nominal, against {pc(_others_off.min(), 0)} to {pc(_others_off.max(), 0)} for the other three.",
    "The effect concentrates on the brakes and in the Bend Angle code. Lasers and the punch show a smaller rise in dimensional defects; welding shows none.",
    "Likely driver: bend allowance and springback are set for nominal thickness, so a sheet that is thicker or thinner than the program assumes comes off the brake at the wrong angle.",
])

_mix2 = T["2.4 Defect code mix: first runs against later runs"].set_index("Defect code")
f2_bullets = bullets([
    f"The first work order run on a new part number or a revised drawing has a defect rate of {pc(r_first['Rate'])} against "
    f"{pc(r_first['Comparison rate'])} on later runs: {mult(r_first)} higher defect rate, "
    f"on {r_first['Jobs']:,} first runs. The second run is still elevated at {pc(r_second['Rate'])} ({mult(r_second)}); from the third run the rate is at its settled level.",
    f"First runs are {pc(comp2['Share of jobs'])} of jobs: {int(comp2['On a new part number']):,} on a new part number and "
    f"{int(comp2['On a revised drawing']):,} on a revised drawing. The shop's program, tooling and setup for a new or revised drawing are "
    f"proven on the first production lot instead of before it, and this explains the elevated defect rate presented here.",
    f"Part complexity is a separate effect. High-complexity parts run at {mult(r_cx)} low-complexity parts on all jobs and {mult(r_cx_later)} "
    f"on later runs alone, and the first-run elevation is about the same size at every complexity level "
    f"({cx_first.loc['Low', 'Multiplier']:.2f}&times; on Low, {cx_first.loc['Medium', 'Multiplier']:.2f}&times; on Medium, {cx_first.loc['High', 'Multiplier']:.2f}&times; on High).",
    f"The added defects are dimensional: the Dimensional code takes a larger share of failed pieces on first runs than on later runs "
    f"({pc(_mix2.loc['Dimensional', 'First runs'], 0)} against {pc(_mix2.loc['Dimensional', 'Later runs'], 0)}), meaning the parts come off "
    f"at the wrong size or with features out of position.",
])

f3_bullets = bullets([
    f"A brake job that follows a job on a different material thickness has a bend-angle defect rate of {pc(r_change['Rate'])} against "
    f"{pc(r_change['Comparison rate'])} for a job that follows the same thickness: {mult(r_change)} higher defect rate "
    f"on {r_change['Jobs']:,} jobs. On all defect codes the multiplier is {mult(r_change_all)}.",
    f"The elevation is confined to the first job after the change. The second job is back at "
    f"{pc(code_rate(POS[POS['position'] == 'Second job'], BEND))} and the third and later at {pc(code_rate(POS[POS['position'] == 'Third or later'], BEND))}.",
    f"{pc(comp3['After a gauge change'], 0)} of brake jobs follow a gauge change, and both brakes show the same elevated rate.",
    f"Laser cutting jobs show no elevation after a change of thickness ({mult(r_laser)}).",
    "Likely driver: a gauge change on a brake means a tooling change and a new back-gauge and angle setup, and the first job absorbs the setup error.",
])

_busy = [pd.Timestamp(2000, m, 1).strftime("%B") for m in F.BUSY_MONTHS]
BUSY_MONTH_NAMES = ", ".join(_busy[:-1]) + " and " + _busy[-1]
f4_bullets = bullets([
    f"Jobs with no first-piece inspection record have a defect rate at final inspection of {pc(r_nofp['Rate'])} against {pc(r_nofp['Comparison rate'])} "
    f"for jobs with one: {mult(r_nofp)} higher defect rates on {r_nofp['Jobs']:,} jobs. This is the largest row in the financial impact table.",
    f"Rush jobs run at {mult(r_rush)} higher defect rates than routine jobs, and the first-piece check is skipped on {pc(comp4['First-piece skipped, rush'], 0)} of them against "
    f"{pc(comp4['First-piece skipped, routine'], 0)} of routine jobs. Rush jobs with a first-piece record run at the routine rate; "
    f"the rush elevation is the skipped check.",
    f"Rush setups are short: the median rush setup is {comp4['Median setup against standard, rush']:.2f} of the part's standard, and where setup runs under 0.6 of standard "
    f"the first-piece check is skipped on {pc(comp4['First-piece skipped, setup under 0.6 of standard'], 0)} of jobs.",
    f"Rush work is {pc(comp4['Rush share of jobs'], 0)} of jobs over the period and {pc(comp4['Rush share, busy months'], 0)} in {BUSY_MONTH_NAMES}, and first-piece presence falls in the same months.",
    "Likely driver: the first-piece check is the step that catches a setup error before the lot is run, and it is the step dropped when a job is expedited.",
])

f5_bullets = bullets([
    f"Operators in their first 50 jobs on a machine type have a defect rate of {pc(r_exp50['Rate'])} against {pc(r_exp50['Comparison rate'])} for operators with over 300: "
    f"{mult(r_exp50)} higher defect rate. The rate falls with every band: {mult(r_exp150)} at 50 to 150 jobs and {mult(r_exp300)} at 150 to 300.",
    f"New hires and operators covering a second machine type sit on the same curve. {int(comp5['Operators hired in the period'])} operators were hired in the period, and "
    f"{pc(comp5['Coverage share of jobs'], 0)} of jobs are run by an operator covering a machine type other than their primary one.",
    f"Jobs by operators with under 300 jobs on the machine type are {pc(comp5['Share of jobs under 300'])} of all jobs.",
    "Likely driver: the first few hundred jobs on a machine type are where an operator learns its setups, and the record shows the same curve whether the operator is new to the shop or new to the machine.",
])

_mix6 = T["6.3 Defect code mix on gauge steel by lot age band"].set_index("Defect code")
f6_bullets = bullets([
    f"On cold-rolled gauge steel (16, 14 and 12 ga), jobs run on lots received 60 days or more before have a defect rate of {pc(r_age_all['Rate'])} against "
    f"{pc(r_age_all['Comparison rate'])} on lots under 60 days: {mult(r_age_all)} higher defect rate on {r_age_all['Jobs']:,} jobs. "
    f"It is {mult(r_age60)} at 60 to 120 days and {mult(r_age120)} past 120 days.",
    f"Plate, aluminum and stainless show no elevation on old lots ({mult(r_age_other)}).",
    f"{pc(comp6['On lots 60 days and over'], 0)} of gauge-steel jobs run on lots 60 days or older.",
    f"The added defects are through surface contamination, which increases to {pc(_mix6.loc['Surface Contamination', 'over 120 days'], 0)} "
    f"of failed pieces on lots over 120 days against {pc(_mix6.loc['Surface Contamination', 'under 60 days'], 0)} on fresh ones.",
    "Likely driver: cold-rolled sheet stored for months picks up surface rust and oil residue, which shows under finish and as porosity in welds.",
])


def fin_row(key, label, target_label):
    r = fin.loc[key]
    return (f'<tr><td>{label}</td><td class="num">{int(r["Segment jobs"]):,}</td><td class="num">{pc(r["Current rate"])}</td>'
            f'<td>{target_label} ({pc(r["Target rate"])})</td><td class="save">{usd_k(r["Savings a year"])}</td></tr>')


fin_rows = "".join([
    fin_row(FIN_ROWS[0], "1 &middot; Brake jobs on lots 2% or more off nominal", "Lots under 2%"),
    fin_row(FIN_ROWS[1], "2 &middot; First runs of new and revised parts", "Later runs"),
    fin_row(FIN_ROWS[2], "3 &middot; Brake jobs after a gauge change", "Same gauge as the job before"),
    fin_row(FIN_ROWS[3], "4 &middot; Jobs with no first-piece record", "Jobs with a first-piece record"),
    fin_row(FIN_ROWS[4], "5 &middot; Jobs by operators under 300 jobs on the machine type", "Operators over 300 jobs"),
    fin_row(FIN_ROWS[5], "6 &middot; Gauge-steel jobs on lots 60 days and over", "Lots under 60 days"),
])

# ── HTML ───────────────────────────────────────────────────────────────────
CSS = f'''
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
      background: #FFFFFF; color: {TEXT}; font-size: 16px; line-height: 1.7; }}
    .page-header {{ background: {DARK_GREY}; color: white; padding: 20px 40px; }}
    .page-header h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
    .layout {{ display: flex; max-width: 1200px; margin: 0 auto; padding: 0 40px; }}
    .toc {{ width: 200px; flex-shrink: 0; padding: 40px 20px 40px 0; position: sticky; top: 0; height: 100vh;
      overflow-y: auto; border-right: 1px solid {LIGHT_GREY}; }}
    .toc-title {{ font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: {MED_GREY};
      margin-bottom: 14px; font-weight: 600; }}
    .toc a {{ display: block; font-size: 13px; color: {MED_GREY}; text-decoration: none; padding: 4px 0 4px 10px;
      border-left: 2px solid transparent; line-height: 1.4; }}
    .toc a:hover {{ color: {DARK_GREY}; border-left-color: {DARK_GREY}; }}
    .toc a.sub {{ font-size: 12px; padding-left: 20px; }}
    .toc hr {{ border: none; border-top: 1px solid {LIGHT_GREY}; margin: 8px 0; }}
    .content {{ flex: 1; padding: 40px 0 80px 52px; max-width: 880px; }}
    .section-title-block {{ margin: 48px 0 24px 0; padding-bottom: 12px; border-bottom: 2px solid {DARK_GREY}; }}
    .content > .section-title-block:first-child {{ margin-top: 12px; }}
    .section-label {{ font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: {TEXT}; font-weight: 600; margin-bottom: 4px; }}
    .section-title {{ font-size: 22px; font-weight: 700; color: {TEXT}; }}
    p {{ margin-bottom: 16px; color: {TEXT}; font-size: 16px; }}
    .finding-block {{ display: flex; align-items: center; background: {BG_GREY}; border-left: 4px solid {DARK_GREY};
      padding: 18px 22px; margin: 32px 0 20px 0; gap: 24px; }}
    .finding-left {{ flex: 1; }}
    .finding-title {{ font-size: 17px; font-weight: 700; color: {DARK_GREY}; line-height: 1.3; }}
    .finding-right {{ flex-shrink: 0; }}
    .finding-stat-group {{ display: flex; gap: 28px; text-align: right; }}
    .finding-stat-val {{ font-size: 24px; font-weight: 700; color: {ACCENT_RED}; line-height: 1; }}
    .finding-stat-lbl {{ font-size: 11px; color: {MED_GREY}; margin-top: 3px; }}
    .findings-list {{ margin: 12px 0 20px 20px; color: {TEXT}; }}
    .findings-list li {{ margin-bottom: 8px; font-size: 15px; line-height: 1.6; }}
    .chart-title {{ font-size: 17px; font-weight: 700; color: {DARK_GREY}; text-align: center; margin-bottom: 8px; }}
    .chart-wrap {{ margin: 20px 0; border: 1px solid {LIGHT_GREY}; border-radius: 4px; padding: 12px; }}
    .chart-caption {{ font-size: 12px; color: {MED_GREY}; margin-top: 8px; text-align: center; font-style: italic; }}
    .fin-table {{ width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 14px; }}
    .fin-table th {{ background: {BG_GREY}; text-align: left; padding: 9px 12px; font-size: 12px; text-transform: uppercase;
      letter-spacing: 0.5px; color: {MED_GREY}; border-bottom: 2px solid {LIGHT_GREY}; }}
    .fin-table td {{ padding: 9px 12px; border-bottom: 1px solid {LIGHT_GREY}; color: {TEXT}; }}
    .fin-table th.num, .fin-table td.num {{ text-align: right; }}
    .fin-table td.save {{ font-weight: 700; color: {GREEN}; text-align: right; }}
    .method-item {{ margin-bottom: 20px; padding-left: 18px; border-left: 2px solid {LIGHT_GREY}; }}
    .method-item strong {{ display: block; color: {DARK_GREY}; margin-bottom: 3px; font-size: 15px; }}
'''

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Analytics Diagnostic Report: Defect Rates &amp; Scrap Cost</title>
  <style>{CSS}</style>
</head>
<body>

<div class="page-header">
  <h1>Analytics Diagnostic Report: Defect Rates &amp; Scrap Cost</h1>
</div>

<div class="layout">
  <nav class="toc">
    <div class="toc-title">Contents</div>
    <a href="#exec">Executive Summary</a>
    <hr>
    <a href="#findings">Findings</a>
    <a href="#f1" class="sub">1. Gauge deviation at receiving</a>
    <a href="#f2" class="sub">2. First runs</a>
    <a href="#f3" class="sub">3. Gauge change on a brake</a>
    <a href="#f4" class="sub">4. First-piece inspection</a>
    <a href="#f5" class="sub">5. Operator experience</a>
    <a href="#f6" class="sub">6. Steel past 60 days</a>
    <hr>
    <a href="#financial">Financial Impact</a>
    <hr>
    <a href="#methodology">Methodology</a>
  </nav>

  <main class="content">

    {section_title("exec", "Section 1", "Executive Summary")}

    <p>From {DATE_MIN} to {DATE_MAX} ({n_months} months), the shop ran {len(d) / 1e3:.1f}K work orders and inspected
    {d.quantity_inspected.sum() / 1e3:.0f}K pieces at final inspection. {d.quantity_failed.sum() / 1e3:.1f}K pieces failed, a defect rate of
    <strong>{pc(overall)}</strong>, and scrap and rework cost <strong>{usd_k(cost_year)} a year</strong>,
    {pc(cost_share, 2)} of revenue. The two charts below show the trailing twelve months, {TTM_MIN} to {TTM_MAX}. In those twelve
    months the defect rate was <strong>{pc(rate(ttm))}</strong> and scrap and rework cost was
    <strong>{usd_k(ttm.scrap_cost.sum())}</strong>.</p>

    <p>The shop's defect rate target is set at {pc(TARGET_RATE)} of pieces at final inspection, based on an analysis of the
    competitive landscape and published industry benchmarks. At {pc(overall)} today, reaching the target is worth about
    <strong>{usd_k(target_save)} a year</strong> in lower scrap and rework costs at current volume and defect mix.</p>

    {wrap("defect_trend", "Pieces Failed and Defect Rate by Month (Trailing Twelve Months)")}
    {wrap("cost_trend", "Scrap and Rework Cost by Month (Trailing Twelve Months)")}

    <p>This report is intended to detail the drivers of the shop's defect rates and scrap costs. After cleaning and
    integrating five disconnected data sources (ERP, MES, QMS, Receiving, HR), we examined the combinations of operating
    conditions associated with elevated defect rates.</p>

    <p>The shop is already aware that jobs with material sourced from Supplier C are associated with a {mult(r_sup_all)} higher
    defect rate than other suppliers, and that high-complexity parts have a {mult(r_cx)} higher defect rate than low-complexity
    parts. We considered these findings and explain their root causes throughout this report.</p>

    <p>We found six conditions that account for a significant portion of the shop's elevated defect rates. These findings are
    detailed in Section 2: (1) brake jobs on lots 2% or more off nominal thickness run at <strong>{mult(r_dev)}</strong> the
    bend-angle rate of lots under 2%; (2) the first run of a new or revised part runs at <strong>{mult(r_first)}</strong> later
    runs; (3) the first brake job after a gauge change runs at <strong>{mult(r_change)}</strong> the bend-angle rate of a job on
    the same gauge; (4) jobs with no first-piece inspection, resulting from schedule pressure and rush jobs, run at
    <strong>{mult(r_nofp)}</strong> jobs with one; (5) operators in their first 50 jobs on a machine type run at
    <strong>{mult(r_exp50)}</strong> operators past 300; and (6) gauge steel on lots 60 days or older runs at
    <strong>{mult(r_age_all)}</strong> fresh lots.</p>

    <p>The cost savings associated with bringing each of these conditions to a normalized baseline target is presented in
    Section 2. As seen below, these conditions overlap across jobs, and so these savings aren't directly additive across
    conditions. Jobs that have two or more of these conditions present have defect rates above 10%, underscoring the
    importance of targeted actions to address these conditions.</p>

    {wrap("overlap", "Defect Rate by Number of Conditions Present on the Job")}

    {section_title("findings", "Section 2", "Findings")}

    {finding_block("f1", "Lots that arrive off nominal thickness produce bend-angle defects",
        "bend-angle rate, lots 2% or more off nominal", f"{r_dev['Multiplier']:.2f}&times;", f"{usd_k(save['1'])}/yr", "at the under-2% rate")}
    {f1_bullets}
    {wrap("supplier_view", "Defect Rate by Supplier")}
    {wrap("dev_by_supplier", "Bend-Angle Defect Rate by Thickness Deviation Band and Supplier")}

    {finding_block("f2", "The first run of a new or revised part fails at twice the rate of later runs",
        "first run against later runs", f"{r_first['Multiplier']:.2f}&times;", f"{usd_k(save['2'])}/yr", "at the later-run rate")}
    {f2_bullets}
    {wrap("run_position", "Defect Rate by Run on the Drawing Revision")}
    {wrap("complexity_split", "Defect Rate by Part Complexity, First Runs Against Later Runs")}
    {wrap("first_run_monthly", "First-Run Share of Jobs and First-Run Defect Rate, by Month")}
    {wrap("first_run_codes", "Defect Code Mix, First Runs Against Later Runs")}

    {finding_block("f3", "The first brake job after a gauge change carries elevated bend-angle defects",
        "bend-angle rate, after a gauge change", f"{r_change['Multiplier']:.2f}&times;", f"{usd_k(save['3'])}/yr", "at the same-gauge rate")}
    {f3_bullets}
    {wrap("change_position", "Bend-Angle Defect Rate by Position After a Gauge Change")}
    {wrap("change_by_brake", "Bend-Angle Defect Rate by Position After a Gauge Change, by Brake")}
    {wrap("change_heatmap", "Brake Jobs by Hour of Day and Position After a Gauge Change")}

    {finding_block("f4", "Lower first-piece inspection rates result from schedule pressure and rush jobs",
        "no first-piece record", f"{r_nofp['Multiplier']:.2f}&times;", f"{usd_k(save['4'])}/yr", "at the rate with a first-piece record")}
    {f4_bullets}
    {wrap("rush", "Defect Rate, Rush Against Routine Jobs")}
    {wrap("first_piece_split", "Defect Rate With and Without a First-Piece Record, Rush and Routine")}
    {wrap("first_piece_monthly", "First-Piece Presence and Rush Share of Jobs, by Month")}

    {finding_block("f5", "Defect rate falls with an operator's experience on the machine type",
        "under 50 jobs against over 300", f"{r_exp50['Multiplier']:.2f}&times;", f"{usd_k(save['5'])}/yr", "operators under 300 jobs, at the over-300 rate")}
    {f5_bullets}
    {wrap("experience", "Defect Rate by Jobs the Operator Had Run on the Machine Type")}
    {wrap("experience_groups", "The Same Curve for New Hires and for Coverage Jobs")}
    {wrap("operators", "Current Roster: Experience Against Defect Rate, Within Each Machine Type",
          "One point per operator and machine type with 50 jobs or more in the period. Operators are compared within a machine "
          "type, since bending runs a higher base rate than the other operations. Experience is on a log scale.")}

    {finding_block("f6", "Cold-rolled gauge steel held past 60 days fails more often; other materials do not",
        "gauge steel, lots 60 days and over", f"{r_age_all['Multiplier']:.2f}&times;", f"{usd_k(save['6'])}/yr", "at the under-60-day rate")}
    {f6_bullets}
    {wrap("lot_age", "Defect Rate by Days Since the Lot Was Received")}
    {wrap("lot_age_codes", "Defect Code Mix on Gauge Steel by Lot Age")}
    {wrap("lot_age_monthly", "Share of Gauge-Steel Jobs on Lots 60 Days and Over, by Month")}

    {section_title("financial", "Section 3", "Financial Impact")}

    <p>Each finding translates into scrap and rework cost that could be recovered by bringing the affected jobs to their
    comparison group's defect rate. The estimate scales the segment's recorded cost by the proportional reduction in its rate:
    <em>savings = segment scrap cost &times; (current rate &minus; target rate) &divide; current rate</em>.</p>

    <table class="fin-table">
      <thead><tr><th>Finding</th><th class="num">Jobs</th><th class="num">Current rate</th><th>Target</th>
        <th class="num">Est. savings / yr</th></tr></thead>
      <tbody>{fin_rows}
        <tr><td><strong>Total before overlap</strong></td><td></td><td></td><td></td><td class="save">{usd_k(total_save)}</td></tr>
      </tbody>
    </table>

    <p><strong>Assumptions and caveats.</strong> Scrap and rework cost is the technician's estimate on each QMS event, attributed
    to the work order. The estimates assume cost per failed piece is constant within a segment and that the full gap to the
    comparison rate is addressable, so they are an upper bound. The segments overlap:
    {pc(overlap["Share of scrap cost on jobs in two or more segments"], 0)} of scrap cost sits on jobs in two or more segments,
    so the rows are not additive and the total overstates what all six actions together would recover.</p>

    {section_title("methodology", "Section 4", "Methodology")}

    <div class="method-item">
      <strong>Data Sources</strong>
      ERP part master and work orders (part revision, rush flag, due date); MES machine register and job log (operator, start
      and end times, setup and run minutes, program or tool set); QMS final and first-piece inspections and scrap, rework and
      use-as-is events; Materials lot receipts with the thickness check at receiving; HR operator roster with hire date and
      machine types. The analysis covers {DATE_MIN} through {DATE_MAX}: {len(d):,} work orders and
      {int(d.quantity_inspected.sum()):,} pieces inspected. The shop runs seven machines (two lasers, two press brakes, two
      welding stations and one punch press) on two shifts, in lots of 5 to 25 pieces. The pipeline cleans these record
      faults before anything is measured: part numbers keyed in five formats, lot ids in four, operator names in id
      fields, duplicate final inspections, reversed job clock entries, the lot not scanned on
      {pc(comp1["No lot scanned"], 0)} of orders, and the ERP start entered late on about 30%.
    </div>

    <div class="method-item">
      <strong>Pipeline</strong>
      Each system's extract is staged, cleaned and typed in dbt on DuckDB, joined on the work order in an intermediate layer,
      and published as marts that this report and the dashboard read. Every model carries schema tests, and the build is
      reproducible from the raw files.
    </div>

    <div class="method-item">
      <strong>Definitions</strong>
      Defect rate is quantity failed over quantity inspected at final inspection, after duplicate inspection entries are
      removed, volume-weighted across a group. First-piece results are not part of it. A multiplier is a group's rate over its
      comparison group's rate, with a 95% interval and p-value from 2,000 bootstrap resamples. Intervals are from a
      bootstrap over jobs, since pieces within a job share a setup, lot and operator. Annual figures divide the total over
      the period by its length in years (days in the window over 365.25). Scrap cost is
      material plus rework labor from the scrap and rework events, attributed to the work order. Hours into the day is the job
      start minus the operator's first job start of the day in the job log, where a day begins after a break of eight hours
      or more. Lot age is the job start minus the lot's receipt date. A first run is the first work order on a new part
      number or a revised drawing.
    </div>

    <div class="method-item">
      <strong>Experience Is Partly Estimated</strong>
      An operator's experience on a machine type is the count of their jobs on it in the job log, plus the jobs they had run
      before the log begins. That prior experience is estimated from tenure: years between the HR hire date and the start of
      the job log, at the shop's measured rate of 480 jobs per operator-year on the primary machine type and a quarter of
      that on the secondary.
    </div>

    <div class="method-item">
      <strong>Known Data Limitations</strong>
      {pc(comp1["No lot scanned"], 0)} of work orders have no lot scanned at job start, and a further
      {pc(comp1["Lot scanned, thickness not measured"], 0)} run on lots whose thickness was not measured at receiving, so
      {pc(1 - comp1["Lot scanned and measured"], 0)} of jobs have no deviation figure and are outside finding 1; jobs with no
      scanned lot are also outside the supplier and lot-age comparisons. A missing first-piece record is treated as a check not
      done, although some checks may have been done and not recorded. The ERP start time is entered late on about 30% of orders,
      so job timing is taken from the MES job log. About 4% of job-log rows had the start and end clock entries reversed and were
      corrected.
    </div>

  </main>
</div>
</body>
</html>'''

for path in OUTPUTS:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="\n")
    print(f"Report written to {path}")
