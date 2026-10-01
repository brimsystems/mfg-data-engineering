"""
Analytics dashboard: defect rates and scrap cost.

Weekly, monthly and trailing-twelve-month tiles, and trend charts over the
trailing twelve months. Reads the marts and writes analytics/reports/dashboard.html
and docs/reports/dashboard.html.

Usage: python generate_dashboard.py
"""
import base64
import io
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DB_PATH = REPO / "data_source" / "defects_scrap.duckdb"
OUTPUTS = [Path(__file__).resolve().parent / "dashboard.html", REPO / "docs" / "reports" / "dashboard.html"]

con = duckdb.connect(str(DB_PATH), read_only=True)
dr = con.execute("select * from mart_quality__defect_rates order by job_start, work_order_id").df()
sc = con.execute("select * from mart_quality__scrap_summary order by scrap_date, scrap_id").df()
codes = con.execute("select * from mart_quality__defect_codes order by production_month, machine_type, defect_code").df()
con.close()

for frame, cols in ((dr, ["production_month", "production_day", "job_start"]), (sc, ["scrap_date", "scrap_month"]),
                    (codes, ["production_month"])):
    for c in cols:
        frame[c] = pd.to_datetime(frame[c])

CURRENT_MONTH = dr["production_month"].max()
PRIOR_MONTH = CURRENT_MONTH - pd.DateOffset(months=1)
TTM_START = CURRENT_MONTH - pd.DateOffset(months=11)
TTM_PRIOR_END = CURRENT_MONTH - pd.DateOffset(years=1)
TTM_PRIOR_START = TTM_PRIOR_END - pd.DateOffset(months=11)
WEEK_END = dr["production_day"].max() + pd.Timedelta(days=1)
WEEK_START = WEEK_END - pd.Timedelta(days=7)
PRIOR_WEEK_START = WEEK_START - pd.Timedelta(days=7)

# ── Palette (BRIM house style) ─────────────────────────────────────────────
DARK_GREY, BG_GREY, TEXT = "#322B4B", "#F3F5F7", "#000000"
DARK_BLUE, LIGHT_BLUE, ACCENT_RED, MUTED_RED = "#381FA1", "#54C0E8", "#CC0000", "#FFA3A3"
MED_GREY, LIGHT_GREY, GREEN, AMBER = "#8093A4", "#D5DCE1", "#00A84C", "#FFBA3F"
SERIES = [DARK_BLUE, LIGHT_BLUE, MED_GREY, ACCENT_RED, MUTED_RED, AMBER, LIGHT_GREY, GREEN]
COMPLEXITY_COLORS = {"Low": LIGHT_GREY, "Medium": LIGHT_BLUE, "High": DARK_BLUE}
BAND_COLORS = {"under 1%": MED_GREY, "1 to 2%": LIGHT_BLUE, "2 to 4%": DARK_BLUE, "over 4%": ACCENT_RED}
DEVIATION_BANDS = ["under 1%", "1 to 2%", "2 to 4%", "over 4%"]

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": LIGHT_GREY, "axes.grid": False,
    "font.family": "sans-serif", "font.size": 18, "axes.titlesize": 18, "axes.titleweight": "bold",
    "axes.labelsize": 18, "xtick.labelsize": 15, "ytick.labelsize": 15, "legend.fontsize": 15,
    "text.color": TEXT, "axes.labelcolor": TEXT, "xtick.color": TEXT, "ytick.color": TEXT, "figure.dpi": 130,
})


def rate(df):
    n = df["quantity_inspected"].sum()
    return df["quantity_failed"].sum() / n if n > 0 else 0.0


def fmt_pct(x): return f"{x:.1%}"
def fmt_usd(x): return f"${x:,.0f}"
def fmt_usd_k(x): return f"${x / 1000:,.0f}K"
def fmt_num(x): return f"{x:,.0f}"


def between(df, col, start, end):
    return df[(df[col] >= start) & (df[col] < end)]


def in_month(df, col, month):
    return df[df[col] == month]


cw_dr, pw_dr = between(dr, "production_day", WEEK_START, WEEK_END), between(dr, "production_day", PRIOR_WEEK_START, WEEK_START)
cw_sc, pw_sc = between(sc, "scrap_date", WEEK_START, WEEK_END), between(sc, "scrap_date", PRIOR_WEEK_START, WEEK_START)
cm_dr, pm_dr = in_month(dr, "production_month", CURRENT_MONTH), in_month(dr, "production_month", PRIOR_MONTH)
cm_sc, pm_sc = in_month(sc, "scrap_month", CURRENT_MONTH), in_month(sc, "scrap_month", PRIOR_MONTH)
ttm_dr = dr[dr["production_month"] >= TTM_START]
ttm_sc = sc[sc["scrap_month"] >= TTM_START]
ttmp_dr = dr[(dr["production_month"] >= TTM_PRIOR_START) & (dr["production_month"] <= TTM_PRIOR_END)]
ttmp_sc = sc[(sc["scrap_month"] >= TTM_PRIOR_START) & (sc["scrap_month"] <= TTM_PRIOR_END)]
ttm_codes = codes[codes["production_month"] >= TTM_START]


# ── KPI tiles ──────────────────────────────────────────────────────────────
def direction(current, prior, lower_is_better, neutral=False):
    if prior == 0 or pd.isna(prior) or pd.isna(current):
        return "", MED_GREY, ""
    delta = (current - prior) / abs(prior)
    better = delta < 0 if lower_is_better else delta > 0
    arrow = "▲" if delta > 0 else "▼"
    return arrow, (MED_GREY if neutral else GREEN if better else ACCENT_RED), f"{abs(delta):.1%}"


def kpi_card(cur_val, pri_val, arrow, arrow_color, pct_str, bar_color, label="Current", prior_label="Prior"):
    indicator = (f'<span style="font-size:18px;color:{arrow_color};font-weight:bold;margin-left:4px;">{arrow} {pct_str}</span>'
                 if arrow else "")
    return f'''<div style="border:1px solid {LIGHT_GREY};border-radius:8px;padding:16px 8px 0 28px;background:white;flex:1;min-width:0;overflow:hidden;display:flex;flex-direction:column;">
      <div style="display:flex;align-items:baseline;flex-wrap:wrap;margin-bottom:2px;">
        <span style="font-size:28px;font-weight:700;color:{DARK_GREY};line-height:1.1;">{cur_val}</span>{indicator}
      </div>
      <div style="font-size:18px;color:{TEXT};margin-bottom:12px;">{label}</div>
      <div style="font-size:22px;font-weight:600;color:{MED_GREY};">{pri_val}</div>
      <div style="font-size:14px;color:{MED_GREY};margin-bottom:12px;">{prior_label}</div>
      <div style="height:8px;background:{bar_color};border-radius:0 0 8px 8px;margin-top:auto;margin-left:-28px;margin-right:-8px;flex-shrink:0;"></div>
    </div>'''


def card(cur, pri, fmt, lower_is_better=True, neutral=False, **kw):
    arrow, color, pct = direction(cur, pri, lower_is_better, neutral)
    return kpi_card(fmt(cur), fmt(pri), arrow, color, pct, color, **kw)


def defect_cards(cur, pri):
    return [card(cur["quantity_inspected"].sum(), pri["quantity_inspected"].sum(), fmt_num, neutral=True),
            card(cur["quantity_failed"].sum(), pri["quantity_failed"].sum(), fmt_num),
            card(rate(cur), rate(pri), fmt_pct)]


def cost_cards(cur, pri):
    per_event = lambda x: x["total_scrap_cost"].sum() / max(len(x), 1)
    return [card(cur["quantity_scrapped"].sum(), pri["quantity_scrapped"].sum(), fmt_num),
            card(cur["total_scrap_cost"].sum(), pri["total_scrap_cost"].sum(), fmt_usd_k),
            card(per_event(cur), per_event(pri), fmt_usd)]


ROW_LABEL_W = "120px"


def kpi_row(label, left, right):
    return f'''
    <div style="display:flex;margin-bottom:10px;align-items:stretch;">
      <div style="width:{ROW_LABEL_W};flex-shrink:0;font-weight:700;color:{DARK_GREY};font-size:18px;display:flex;align-items:center;padding-right:8px;">{label}</div>
      <div style="display:flex;gap:4px;flex:1;padding-right:9px;">{"".join(left)}</div>
      <div style="display:flex;gap:4px;flex:1;padding-left:9px;">{"".join(right)}</div>
    </div>'''


def banner(text):
    return (f'<div style="background:{DARK_GREY};color:white;border-radius:8px;padding:12px 20px;font-size:20px;'
            f'font-weight:700;margin-bottom:12px;text-align:center;">{text}</div>')


def col_header(label):
    return f'<div style="flex:1;min-width:0;text-align:center;font-size:18px;font-weight:700;color:{DARK_GREY};padding-bottom:8px;">{label}</div>'


def group_header(label, side):
    return (f'<div style="flex:1;padding-{side}:9px;"><div style="font-size:18px;font-weight:700;color:{DARK_GREY};'
            f'border-bottom:2px solid {DARK_GREY};padding-bottom:8px;text-align:center;">{label}</div></div>')


kpi_section = (
    banner("KPIs")
    + f'<div style="display:flex;margin-bottom:4px;"><div style="width:{ROW_LABEL_W};flex-shrink:0;"></div>'
    + group_header("Defects", "right") + group_header("Scrap Costs", "left") + "</div>"
    + f'<div style="display:flex;margin-bottom:8px;margin-top:10px;"><div style="width:{ROW_LABEL_W};flex-shrink:0;"></div>'
    + '<div style="display:flex;gap:4px;flex:1;padding-right:9px;">'
    + col_header("Parts Inspected") + col_header("Defects") + col_header("Defect Rate") + "</div>"
    + '<div style="display:flex;gap:4px;flex:1;padding-left:9px;">'
    + col_header("Scrapped Parts") + col_header("Total Scrap Cost") + col_header("Cost / Scrap Event") + "</div></div>"
    + kpi_row("Weekly", defect_cards(cw_dr, pw_dr), cost_cards(cw_sc, pw_sc))
    + kpi_row("Monthly", defect_cards(cm_dr, pm_dr), cost_cards(cm_sc, pm_sc))
    + kpi_row("Trailing 12 Months", defect_cards(ttm_dr, ttmp_dr), cost_cards(ttm_sc, ttmp_sc))
)

# ── Chart helpers ──────────────────────────────────────────────────────────
def chart_style(ax):
    ax.yaxis.grid(True, color=LIGHT_GREY, linestyle="-", linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LIGHT_GREY)


def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130, metadata={"Software": None})
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


MONTHS = sorted(ttm_dr["production_month"].unique())
X = np.arange(len(MONTHS))
MONTH_LABELS = [pd.Timestamp(m).strftime("%b '%y") for m in MONTHS]


def month_axis(ax):
    ax.set_xticks(X)
    ax.set_xticklabels(MONTH_LABELS, rotation=45, ha="right")


def pct_axis(ax, decimals=0):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.{decimals}f}%"))


def legend_below(ax, ncol=4, y=-0.18):
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, y), ncol=ncol, frameon=False)


def monthly_rate(df):
    return np.array([rate(df[df["production_month"] == m]) * 100 for m in MONTHS])


def stacked_months(ax, table, colors, labels_pct=True, total_fmt=None, min_share=0.07, label_size=13):
    """Stacked monthly bars from a month-by-series table, with share labels."""
    bottoms = np.zeros(len(MONTHS))
    totals = table.sum(axis=1).values
    for i, col in enumerate(table.columns):
        vals = table[col].values
        ax.bar(X, vals, bottom=bottoms, width=0.7, color=colors[i % len(colors)], label=col)
        if labels_pct:
            for xi, v, bot, tot in zip(X, vals, bottoms, totals):
                if tot > 0 and v / tot >= min_share:
                    ax.text(xi, bot + v / 2, f"{v / tot:.0%}", ha="center", va="center", fontsize=label_size,
                            color="white" if colors[i % len(colors)] in (DARK_BLUE, ACCENT_RED, MED_GREY, GREEN) else TEXT, fontweight="bold")
        bottoms += vals
    if total_fmt:
        for xi, tot in zip(X, totals):
            ax.text(xi, tot * 1.01, total_fmt(tot), ha="center", va="bottom", fontsize=13)
    month_axis(ax)


charts = {}

# ── Defect rate ────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(13, 5.5))
vals = monthly_rate(ttm_dr)
ax.plot(X, vals, color=DARK_BLUE, linewidth=2.5, marker="o", markersize=7)
ax.axhline(rate(ttm_dr) * 100, color=ACCENT_RED, linestyle="--", linewidth=2, label=f"Trailing 12 months ({rate(ttm_dr):.1%})")
for xi, v in zip(X, vals):
    ax.text(xi, v + 0.12, f"{v:.1f}%", ha="center", va="bottom", fontsize=15)
month_axis(ax); pct_axis(ax, 1); ax.set_ylabel("Defect Rate"); ax.set_ylim(vals.min() - 0.8, vals.max() + 0.8)
ax.legend(); chart_style(ax); plt.tight_layout()
charts["defect_rate"] = fig_to_b64(fig)

# ── Defect rate by part complexity, first runs split out ───────────────────
fig, ax = plt.subplots(figsize=(13, 6.5))
later_runs = ttm_dr[ttm_dr["run_position"] == 3]
for cx in ("Low", "Medium", "High"):
    ax.plot(X, monthly_rate(later_runs[later_runs["complexity"] == cx]), color=COMPLEXITY_COLORS[cx], linewidth=2.5,
            marker="o", markersize=6, label=f"{cx}, later runs")
ax.plot(X, monthly_rate(ttm_dr[ttm_dr["run_position"] == 1]), color=ACCENT_RED, linewidth=2.5, linestyle="--",
        marker="s", markersize=6, label="First runs, all complexity")
month_axis(ax); pct_axis(ax); ax.set_ylabel("Defect Rate"); ax.set_ylim(0, None)
legend_below(ax, ncol=2, y=-0.2); chart_style(ax); plt.tight_layout()
charts["complexity"] = fig_to_b64(fig)

# ── Defect rate by supplier and lot thickness deviation ────────────────────
fig, ax = plt.subplots(figsize=(13, 6.5))
with_dev = ttm_dr[ttm_dr["thickness_deviation_band"].notna()]
w = 0.38
for i, (label, mask, color) in enumerate((("Supplier C", with_dev["supplier"] == "Supplier C", DARK_BLUE),
                                          ("Suppliers A, B and D", with_dev["supplier"] != "Supplier C", MED_GREY))):
    v = [rate(with_dev[mask & (with_dev["thickness_deviation_band"] == b)]) * 100 for b in DEVIATION_BANDS]
    pos = np.arange(4) + (i - 0.5) * w
    ax.bar(pos, v, width=w * 0.94, color=color, label=label)
    for xi, val in zip(pos, v):
        ax.text(xi, val + 0.15, f"{val:.1f}%", ha="center", va="bottom", fontsize=15)
ax.set_xticks(np.arange(4)); ax.set_xticklabels(DEVIATION_BANDS); pct_axis(ax)
ax.set_xlabel("Lot thickness deviation from nominal at receiving"); ax.set_ylabel("Defect Rate")
ax.set_ylim(0, ax.get_ylim()[1] * 1.08); legend_below(ax, ncol=2, y=-0.2); chart_style(ax); plt.tight_layout()
charts["deviation"] = fig_to_b64(fig)

# ── Defects by machine type ────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(13, 6.5))
t = ttm_dr.pivot_table(index="production_month", columns="machine_type", values="quantity_failed", aggfunc="sum").fillna(0)
stacked_months(ax, t, SERIES, total_fmt=lambda v: f"{v:,.0f}")
ax.set_ylabel("Defects"); ax.set_ylim(0, t.sum(axis=1).max() * 1.12); legend_below(ax); chart_style(ax); plt.tight_layout()
charts["defect_machine"] = fig_to_b64(fig)

# ── Defect code Pareto and monthly mix ─────────────────────────────────────
fig, ax = plt.subplots(figsize=(13, 6.5))
p = ttm_codes.groupby("defect_code")["quantity_failed"].sum().sort_values(ascending=False)
ax.bar(np.arange(len(p)), p.values, color=DARK_BLUE, width=0.65)
for i, v in enumerate(p.values):
    ax.text(i, v + p.max() * 0.01, f"{v:,.0f}", ha="center", va="bottom", fontsize=14)
ax.set_xticks(np.arange(len(p))); ax.set_xticklabels([c.replace(" ", "\n") for c in p.index], fontsize=14)
ax.set_ylabel("Defects"); ax.set_ylim(0, p.max() * 1.12)
ax2 = ax.twinx()
cum = p.cumsum().values / p.sum() * 100
ax2.plot(np.arange(len(p)), cum, color=ACCENT_RED, linewidth=2.5, marker="o", markersize=6)
bar_top = p.values / (p.max() * 1.12) * 105        # each bar's height on the right-hand axis
for i, c in enumerate(cum):
    ax2.text(i, c + 3, f"{c:.0f}%", ha="center", va="bottom", fontsize=14, fontweight="bold",
             color="white" if c + 8 < bar_top[i] else TEXT)
ax2.set_ylim(0, 105); pct_axis(ax2); ax2.set_ylabel("Cumulative share"); ax2.spines["top"].set_visible(False)
chart_style(ax); plt.tight_layout()
charts["code_pareto"] = fig_to_b64(fig)
CODE_ORDER = list(p.index)

fig, ax = plt.subplots(figsize=(13, 7.2))
t = ttm_codes.pivot_table(index="production_month", columns="defect_code", values="quantity_failed", aggfunc="sum").fillna(0)[CODE_ORDER]
stacked_months(ax, t.div(t.sum(axis=1), axis=0) * 100, SERIES, min_share=0.04, label_size=12)
ax.set_ylim(0, 100); pct_axis(ax); ax.set_ylabel("Share of Defects"); legend_below(ax, ncol=4, y=-0.2); chart_style(ax); plt.tight_layout()
charts["code_monthly"] = fig_to_b64(fig)

# ── Scrap cost ─────────────────────────────────────────────────────────────
monthly_cost = ttm_sc.groupby("scrap_month")["total_scrap_cost"].sum().reindex(MONTHS).fillna(0)
fig, ax = plt.subplots(figsize=(13, 5.5))
vals_k = monthly_cost.values / 1000
ax.bar(X, vals_k, color=DARK_BLUE, width=0.7)
ax.axhline(vals_k.mean(), color=ACCENT_RED, linestyle="--", linewidth=2, label=f"Trailing 12 months, monthly mean (${vals_k.mean():,.0f}K)")
for xi, v in zip(X, vals_k):
    ax.text(xi, v + vals_k.max() * 0.015, f"${v:,.0f}K", ha="center", va="bottom", fontsize=15, fontweight="bold")
month_axis(ax); ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}K")); ax.set_ylabel("Scrap Cost ($K)")
ax.set_ylim(0, vals_k.max() * 1.15); ax.legend(); chart_style(ax); plt.tight_layout()
charts["scrap_cost"] = fig_to_b64(fig)

# ── Scrap cost as a share of revenue ───────────────────────────────────────
fig, ax = plt.subplots(figsize=(13, 5.5))
by_month = ttm_dr.groupby("production_month").agg(cost=("scrap_cost", "sum"), revenue=("revenue", "sum")).reindex(MONTHS)
vals = (by_month["cost"] / by_month["revenue"] * 100).values
ttm_share = ttm_dr["scrap_cost"].sum() / ttm_dr["revenue"].sum()
ax.plot(X, vals, color=DARK_BLUE, linewidth=2.5, marker="o", markersize=7)
ax.axhline(ttm_share * 100, color=ACCENT_RED, linestyle="--", linewidth=2, label=f"Trailing 12 months ({ttm_share:.2%} of revenue)")
for xi, v in zip(X, vals):
    ax.text(xi, v + 0.04, f"{v:.2f}%", ha="center", va="bottom", fontsize=15)
month_axis(ax); pct_axis(ax, 1); ax.set_ylabel("Scrap Cost / Revenue"); ax.set_ylim(vals.min() - 0.3, vals.max() + 0.3)
ax.legend(); chart_style(ax); plt.tight_layout()
charts["cost_share"] = fig_to_b64(fig)

# ── Scrap cost by reason, by machine type, and by disposition share ────────
for key, col in (("scrap_reason", "scrap_reason"), ("cost_machine", "machine_type")):
    fig, ax = plt.subplots(figsize=(13, 6.8))
    t = (ttm_sc.pivot_table(index="scrap_month", columns=col, values="total_scrap_cost", aggfunc="sum").reindex(MONTHS).fillna(0) / 1000)
    stacked_months(ax, t, SERIES, total_fmt=lambda v: f"${v:,.0f}K")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}K")); ax.set_ylabel("Scrap Cost ($K)")
    ax.set_ylim(0, t.sum(axis=1).max() * 1.12); legend_below(ax, ncol=3 if key == "scrap_reason" else 4, y=-0.2)
    chart_style(ax); plt.tight_layout()
    charts[key] = fig_to_b64(fig)

DISPOSITIONS = ["Scrap", "Rework", "Use-As-Is"]
DISPOSITION_LABEL = {"Scrap": "Scrapped pieces (material and labor)", "Rework": "Rework labor", "Use-As-Is": "Use-as-is review"}
fig, ax = plt.subplots(figsize=(13, 6.8))
t = ttm_sc.pivot_table(index="scrap_month", columns="disposition", values="total_scrap_cost", aggfunc="sum").reindex(MONTHS).fillna(0)[DISPOSITIONS]
t = (t.div(t.sum(axis=1), axis=0) * 100).rename(columns=DISPOSITION_LABEL)
stacked_months(ax, t, [DARK_BLUE, LIGHT_BLUE, MED_GREY])
ax.set_ylim(0, 100); pct_axis(ax); ax.set_ylabel("% of Scrap Cost"); legend_below(ax, ncol=3, y=-0.2); chart_style(ax); plt.tight_layout()
charts["cost_split"] = fig_to_b64(fig)

# ── Disposition mix, trailing twelve months: events, pieces and cost ───────
fig, axes = plt.subplots(1, 3, figsize=(13, 5.2))
ttm_final = ttm_dr[ttm_dr["quantity_failed"] > 0]
panels = [("Jobs with failed pieces", ttm_final.groupby("disposition").size(), fmt_num),
          ("Failed pieces", ttm_final.groupby("disposition")["quantity_failed"].sum(), fmt_num),
          ("Cost", ttm_sc.groupby("disposition")["total_scrap_cost"].sum(), fmt_usd_k)]
for ax, (title, s, fmt) in zip(axes, panels):
    s = s.reindex(DISPOSITIONS).fillna(0)
    ax.bar(DISPOSITIONS, s.values, color=[DARK_BLUE, LIGHT_BLUE, MED_GREY], width=0.6)
    for i, v in enumerate(s.values):
        ax.text(i, v + s.max() * 0.015, f"{fmt(v)}\n({v / s.sum():.0%})", ha="center", va="bottom", fontsize=14)
    ax.set_title(title); ax.set_ylim(0, s.max() * 1.25); ax.set_yticks([]); chart_style(ax); ax.yaxis.grid(False)
plt.tight_layout()
charts["disposition"] = fig_to_b64(fig)

# ── Layout ─────────────────────────────────────────────────────────────────
def chart_card(key, title, wide=False):
    span = "grid-column:1 / -1;" if wide else ""
    return f'''<div style="background:white;border:1px solid {LIGHT_GREY};border-radius:8px;padding:20px;{span}">
      <div style="font-size:18px;font-weight:700;color:{DARK_GREY};margin-bottom:14px;">{title}</div>
      <img src="data:image/png;base64,{charts[key]}" style="width:100%;height:auto;display:block;">
    </div>'''


def trend_section_header(label):
    return (f'<div style="font-size:18px;font-weight:700;color:{DARK_GREY};border-bottom:2px solid {DARK_GREY};'
            f'padding-bottom:8px;text-align:center;margin:24px 0 16px 0;">{label}</div>')


GRID = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">'
chart_grid = f'''
<div id="trends" style="margin-top:36px;">
  {banner("Trend Charts (Trailing 12 Months)")}
  {trend_section_header("Defects")}
  {GRID}
    {chart_card("defect_rate", "Defect Rate")}
    {chart_card("complexity", "Defect Rate by Part Complexity, First Runs Split Out")}
    {chart_card("deviation", "Defect Rate by Supplier and Lot Thickness Deviation")}
    {chart_card("defect_machine", "Defects by Machine Type")}
    {chart_card("code_pareto", "Defect Code Pareto")}
    {chart_card("code_monthly", "Defect Code Mix by Month")}
  </div>
  {trend_section_header("Scrap Costs")}
  {GRID}
    {chart_card("scrap_cost", "Total Scrap Cost")}
    {chart_card("cost_share", "Scrap Cost as a Share of Revenue")}
    {chart_card("scrap_reason", "Scrap Cost by Reason")}
    {chart_card("cost_machine", "Scrap Cost by Machine Type")}
    {chart_card("cost_split", "Scrap Cost, Scrapped Pieces vs. Rework Labor")}
    {chart_card("disposition", "Disposition Mix: Scrap, Rework and Use-As-Is")}
  </div>
</div>'''

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KPI Dashboard: Defect Rates &amp; Scrap Costs</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: {BG_GREY}; margin: 0; padding: 0; color: {TEXT}; }}
    .page-header {{ background: {DARK_GREY}; color: white; padding: 20px 40px; display: flex;
      justify-content: space-between; align-items: center; gap: 24px; }}
    .page-header .byline {{ font-size: 12px; color: white; white-space: nowrap; }}
    .page-header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
    .container {{ max-width: 1600px; margin: 0 auto; padding: 28px 32px 64px 32px; }}
  </style>
</head>
<body>
  <div class="page-header">
    <h1>KPI Dashboard: Defect Rates &amp; Scrap Costs</h1>
    <div class="byline">Created by Brian Davis, 2026</div>
  </div>
  <div class="container">
    {kpi_section}
    {chart_grid}
  </div>
</body>
</html>'''

for path in OUTPUTS:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="\n")
    print(f"Dashboard written to {path}")
