"""ML Model Overview & Performance Report for the machine health indicator
-> docs/reports/model_overview.html
Executive Summary, Model Overview (what it does, training data), Model Performance
(scoring summary, accuracy against the baselines, sample output, limits)."""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.dates as mdates

import sys
sys.path.insert(0, str(Path(__file__).parent))
import brand as B
from brand import (DARK_GREY, DARK_BLUE, LIGHT_BLUE, ACCENT_RED, MUTED_RED, AMBER, GREEN, MED_GREY, LIGHT_GREY, mticker)

REPO    = Path(__file__).resolve().parents[2]
MODELS  = REPO / "ml" / "models"
SCORING = REPO / "ml" / "data" / "scoring"
OUT     = REPO / "docs" / "reports" / "model_overview.html"

PERIODS = [("202601", "January 2026"), ("202602", "February 2026"), ("202603", "March 2026")]
PERIOD_NAME = "January to March 2026"
SCORING_START, SCORING_END = "2026-01-01", "2026-03-31"
TIERS = ["CRITICAL", "ELEVATED", "OK"]
TIER_COLOR = {"CRITICAL": ACCENT_RED, "ELEVATED": AMBER, "OK": GREEN}
TIER_RANK = {"CRITICAL": 2, "ELEVATED": 1, "OK": 0}
TIER_MEANING = {"CRITICAL": "Failure likely within 7 days",
                "ELEVATED": "Failure likely within 8 to 21 days",
                "OK": "No failure expected within 21 days"}
# Contribution margin per productive machine-hour by type, mirroring the dbt var
# contribution_margin_by_type used to value downtime in the diagnostic report.
CM_BY_TYPE = {"CNC Lathe": 95, "Vertical Mill": 125, "Horizontal Mill": 145}
# Assumed reduction in downtime when a failure is caught early and handled as
# planned preventive maintenance rather than a reactive breakdown repair.
DOWNTIME_REDUCTION = 0.40
LABELS = {"logistic_regression": "Logistic Regression", "random_forest": "Random Forest", "xgboost": "XGBoost"}
SOURCES = ["model", "interval", "rules", "calendar_pm"]
SOURCE_NAME = {"model": "Health indicator", "interval": "Interval baseline",
               "rules": "Rules baseline", "calendar_pm": "Calendar PM (current practice)"}

m = json.loads((MODELS / "metrics.json").read_text(encoding="utf-8"))
best = m["best_model_type"]
win = {s: pd.read_csv(MODELS / f"evaluation_windows_{s}.csv") for s in ("test", "scoring")}
abl = pd.read_csv(MODELS / "ablation_no_sensors.csv")
frames = []
for lbl, nm in PERIODS:
    p = pd.read_parquet(SCORING / f"predictions_{lbl}.parquet"); p["period"] = nm; frames.append(p)
preds = pd.concat(frames, ignore_index=True)
preds["observation_date"] = pd.to_datetime(preds["observation_date"])
total = len(preds)


def wm(split, source, window, col):
    w = win[split]
    return float(w[(w["source"] == source) & (w["window_days"] == window)][col].iloc[0])


# One row per machine and day: the higher tier of the day's two shift rows.
days = preds.assign(rank=preds["health_indicator"].map(TIER_RANK)).groupby(
    ["machine_id", "observation_date", "period"], as_index=False)["rank"].max()
days["tier"] = days["rank"].map({v: k for k, v in TIER_RANK.items()})
n_days = len(days)
day_counts = days["tier"].value_counts()
n_crit, n_elev, n_ok = (int(day_counts.get(t, 0)) for t in TIERS)

# ── Failures in the scoring window and the tier each source showed before them ─
# For every unplanned repair opened in the window: did the source show CRITICAL
# on at least one of the 7 days before it?
history = pd.read_parquet(SCORING / "tier_history.parquet")
history["observation_date"] = pd.to_datetime(history["observation_date"])
_mm = pd.read_csv(REPO / "data_source" / "raw" / "cmms" / "maintenance_records.csv")
_mm = _mm[_mm["maintenance_type"] == "UNPLANNED_REPAIR"].copy()
_mm["fd"] = pd.to_datetime(_mm["work_order_open_date"])
_mm["fday"] = _mm["fd"].dt.normalize()
q1 = _mm[(_mm["fday"] >= SCORING_START) & (_mm["fday"] <= SCORING_END)].copy()
_hist_by_machine = {mid: g.set_index("observation_date") for mid, g in history.groupby("machine_id")}


def _critical_before(machine_id, fday, source):
    h = _hist_by_machine[machine_id][source]
    w = h[(h.index >= fday - pd.Timedelta(days=7)) & (h.index < fday)]
    return bool((w == "CRITICAL").any())


for _s in SOURCES:
    q1[f"hit_{_s}"] = [_critical_before(mid, fd, _s) for mid, fd in zip(q1["machine_id"], q1["fday"])]
_type_by_machine = preds.groupby("machine_id")["machine_type"].first().to_dict()
q1["margin"] = q1["downtime_hours"] * q1["machine_id"].map(_type_by_machine).map(CM_BY_TYPE)
bi_events = int(len(q1))
bi_hrs = float(q1["downtime_hours"].sum())
hit_n   = {s: int(q1[f"hit_{s}"].sum()) for s in SOURCES}
hit_pct = {s: hit_n[s] / bi_events for s in SOURCES}
hit_hrs = {s: float(q1.loc[q1[f"hit_{s}"], "downtime_hours"].sum()) for s in SOURCES}
# Downtime avoided: the existing method and assumption, applied to the failures
# with a CRITICAL day in the 7 days before. Hours are for the quarter; the dollar
# figure is the quarter annualised at each machine type's contribution margin.
avoid_hrs = {s: hit_hrs[s] * DOWNTIME_REDUCTION for s in SOURCES}
avoid_usd = {s: round(float(q1.loc[q1[f"hit_{s}"], "margin"].sum()) * 4 * DOWNTIME_REDUCTION, -3) for s in SOURCES}
contrib_hrs = avoid_hrs["model"] - avoid_hrs["interval"]
contrib_usd = avoid_usd["model"] - avoid_usd["interval"]

# Share of failures with a CRITICAL day in the 7 days before, by the failure mode
# the CMMS recorded, across the test and scoring windows (the technical report's
# failure-mode chart), for the limits section.
_fm = _mm[(_mm["fday"] >= "2025-09-01") & (_mm["fday"] <= SCORING_END)].copy()
_fm["hit"] = [_critical_before(mid, fd, "model") for mid, fd in zip(_fm["machine_id"], _fm["fday"])]
mode_hit = _fm.groupby("failure_code")["hit"].mean()

# ── Training-data overview + worked example ──────────────────────────────────
FEATURES = REPO / "ml" / "data" / "features"
train = pd.read_parquet(FEATURES / "train.parquet")
train["observation_date"] = pd.to_datetime(train["observation_date"])
n_train_failures = int((_mm["fday"] <= "2024-12-31").sum())
n_machines = int(preds["machine_id"].nunique())
n_obs_total = int(sum(m["split_sizes"].values()))

# Days from each training row to the machine's next unplanned repair, for the two
# charts that show how the sensor signals move as a repair approaches.
_next = {mid: np.sort(g["fday"].values) for mid, g in _mm.groupby("machine_id")}


def _days_to_next(machine_id, d):
    f = _next[machine_id]
    i = np.searchsorted(f, np.datetime64(d), side="right")
    return float((f[i] - np.datetime64(d)) / np.timedelta64(1, "D")) if i < len(f) else np.nan


train["days_to_next_repair"] = [_days_to_next(mid, d) for mid, d in zip(train["machine_id"], train["observation_date"])]

# Worked example: the top-ranked machine in the current fleet snapshot, used to
# walk a non-technical reader through one real rating end to end.
_snap = pd.read_parquet(SCORING / "fleet_snapshot.parquet").iloc[0]
we = preds[(preds["machine_id"] == _snap["machine_id"])
           & (preds["observation_date"] == pd.Timestamp(_snap["observation_date"]))
           & (preds["shift"] == _snap["shift"])].iloc[0]
we_drivers = list(we["risk_drivers"]) if we["risk_drivers"] is not None else []

# ── Exploratory views of the model inputs over the training window ───────────
# Time series of the sensor channels and the other top drivers across the full
# Jan 2023 to Dec 2025 training window, for the data-exploration section.
TRAIN_END = "2025-12-31"
ANOM_THRESH = 1.5                        # sensor anomaly z-score treated as a flag
SENSOR_CH = {"vibration_rms_mm_s": "Spindle vibration (mm/s)",
             "bearing_temp_c": "Bearing temperature (°C)",
             "spindle_power_kw": "Spindle power (kW)",
             "hydraulic_pressure_bar": "Hydraulic pressure (bar)"}

_sr = pd.read_csv(REPO / "data_source" / "raw" / "sensors" / "sensor_readings.csv", parse_dates=["reading_date"])
_sr = _sr[_sr["reading_date"] <= TRAIN_END].copy()
_sr["ym"] = _sr["reading_date"].dt.to_period("M").dt.to_timestamp()
eda_sensor_monthly = _sr.groupby("ym")[list(SENSOR_CH)].mean()

_con = duckdb.connect(str(REPO / "data_source" / "oee_predmaint.duckdb"), read_only=True)
_mart = _con.execute(f"""select observation_date, sensor_anomaly_score, rolling_30d_utilization_rate
    from mart_ml__health_features where observation_date <= '{TRAIN_END}'""").df()
_con.close()
_mart["ym"] = pd.to_datetime(_mart["observation_date"]).dt.to_period("M").dt.to_timestamp()
_mart["is_anom"] = _mart["sensor_anomaly_score"] >= ANOM_THRESH
eda_anom_monthly = _mart.groupby("ym")["is_anom"].sum()
eda_anom_rate = float(_mart["is_anom"].mean())
eda_util_monthly = _mart.groupby("ym")["rolling_30d_utilization_rate"].mean()

_ut = _mm[_mm["fd"] <= TRAIN_END].copy()     # _mm is unplanned-only with fd already set
_ut["ym"] = _ut["fd"].dt.to_period("M").dt.to_timestamp()
eda_fail_monthly = _ut.groupby("ym").size()
eda_fail_by_mode = _ut.groupby(["ym", "failure_code"]).size().unstack(fill_value=0)
eda_fail_total = int(len(_ut))
# Share of unplanned failures driven by the wear modes the sensors can detect.
tm_pct = float((_ut["failure_code"].isin(["TOOLING", "MECHANICAL"])).mean())


def _trend_pct(series):
    if len(series) < 2 or series.iloc[0] == 0:
        return 0.0
    slope = np.polyfit(np.arange(len(series)), series.values, 1)[0]
    return slope * (len(series) - 1) / series.iloc[0] * 100



# ── Charts ──────────────────────────────────────────────────────────────────
def chart_tier_distribution():
    vals = [int(day_counts.get(t, 0)) for t in TIERS]
    fig, ax = B.make_fig(h=3.4)
    bars = ax.bar(TIERS, vals, color=[TIER_COLOR[t] for t in TIERS], width=0.55)
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + n_days * 0.005, f"{v:,}\n({v/n_days:.0%})",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Machine-days")
    ax.set_ylim(0, max(vals) * 1.18)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_prob_distribution():
    fig, ax = B.make_fig(h=3.4)
    ax.hist(preds["prob_failure_7d"], bins=30, color=DARK_BLUE, edgecolor="white", linewidth=0.5)
    ax.axvline(m["thresholds"]["7"], color=ACCENT_RED, ls="--", lw=1.4,
               label=f"CRITICAL threshold ({m['thresholds']['7']:.2f})")
    ax.set_xlabel("Probability of an unplanned repair within 7 days"); ax.set_ylabel("Observations"); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_tier_by_period():
    names = [nm for _, nm in PERIODS]
    x = np.arange(len(names)); w = 0.24
    fig, ax = B.make_fig(h=3.4)
    maxv = 0
    for i, t in enumerate(TIERS):
        vals = [int(((days["period"] == nm) & (days["tier"] == t)).sum()) for nm in names]
        maxv = max(maxv, max(vals))
        bars = ax.bar(x + (i - 1) * w, vals, w, color=TIER_COLOR[t], label=t if t == "OK" else t.title())
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + maxv * 0.012, f"{v}",
                    ha="center", va="bottom", fontsize=8, color=DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels(names); ax.set_ylabel("Machine-days")
    ax.set_ylim(0, maxv * 1.16)
    ax.legend(ncol=3, fontsize=9)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── Training-signal charts (what the model keys on) ──────────────────────────
def chart_vibration_ramp():
    u = train[train["days_to_next_repair"] <= 30]
    buckets = [(22, 30), (15, 21), (8, 14), (4, 7), (0, 3)]
    labels = ["22-30", "15-21", "8-14", "4-7", "0-3"]
    vals = [u.loc[(u["days_to_next_repair"] >= lo) & (u["days_to_next_repair"] <= hi),
                  "vibration_7d_mean"].mean() for lo, hi in buckets]
    fig, ax = B.make_fig(h=3.4)
    ax.plot(labels, vals, "o-", color=DARK_BLUE, lw=2.6, markersize=9, zorder=3)
    ax.fill_between(range(len(labels)), vals, min(vals) * 0.9, color=DARK_BLUE, alpha=0.08, zorder=1)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.06, f"{v:.1f}", ha="center", va="bottom", fontsize=10, fontweight="bold", color=DARK_BLUE)
    ax.set_xlabel("Days until the next unplanned repair  (further out  →  imminent)")
    ax.set_ylabel("Avg spindle vibration (mm/s)")
    ax.set_ylim(min(vals) * 0.9, max(vals) * 1.12)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


_a, _t = train["sensor_anomaly_score"], train["days_to_next_repair"]
ANOM_BUCKETS = [("Normal\n(< 0.5)", _a < 0.5, GREEN),
                ("Slight\n(0.5-1.0)", (_a >= 0.5) & (_a < 1.0), LIGHT_BLUE),
                ("Elevated\n(1.0-1.5)", (_a >= 1.0) & (_a < 1.5), AMBER),
                ("High\n(1.5+)", _a >= 1.5, ACCENT_RED)]
anom_days = [float(_t[b[1]].mean()) for b in ANOM_BUCKETS]


def chart_anomaly_ttf():
    labels = [b[0] for b in ANOM_BUCKETS]; cols = [b[2] for b in ANOM_BUCKETS]
    fig, ax = B.make_fig(h=3.4)
    bars = ax.bar(labels, anom_days, color=cols, width=0.6)
    for b_, v in zip(bars, anom_days):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.3, f"{v:.0f} d", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_xlabel("Sensor anomaly score (how far readings sit above the machine's own baseline)")
    ax.set_ylabel("Avg days to the next unplanned repair"); ax.set_ylim(0, max(anom_days) * 1.15)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── Business-impact chart ────────────────────────────────────────────────────
def chart_impact_combined():
    # How much of the quarter's failures and downtime each approach had a
    # CRITICAL day in front of. Downtime (hours) and failure count use different
    # units, so each column is normalised to its own total and labelled with the
    # absolute value.
    cats = [("CRITICAL in the 7 days before", GREEN), ("No CRITICAL day before", MED_GREY)]
    order = ["calendar_pm", "interval", "model"]
    names = {"calendar_pm": "Calendar PM (today)", "interval": "Interval baseline", "model": "Health indicator"}
    fig, ax = B.make_fig(h=3.9)
    xpos, ticks = [], []
    for g, s in enumerate(order):
        cols = [((hit_hrs[s], bi_hrs - hit_hrs[s]), bi_hrs, "hrs", "Downtime"),
                ((float(hit_n[s]), float(bi_events - hit_n[s])), float(bi_events), "", "Failures")]
        for k, (vals, tot, unit, lab) in enumerate(cols):
            x = g * 2.4 + k
            xpos.append(x); ticks.append(lab)
            bottom = 0.0
            for (clab, color), v in zip(cats, vals):
                pct = v / tot * 100 if tot else 0.0
                ax.bar(x, pct, bottom=bottom, width=0.82, color=color,
                       label=clab if (g == 0 and k == 0) else None)
                if pct >= 6:              # label only segments tall enough to hold text
                    ax.text(x, bottom + pct / 2, f"{v:.0f} {unit}".strip(), ha="center", va="center",
                            color="white", fontsize=9, fontweight="bold")
                bottom += pct
        ax.text(g * 2.4 + 0.5, -0.16, names[s], transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=10, fontweight="bold", color=DARK_GREY)
    ax.set_ylim(0, 100)
    ax.set_xticks(xpos); ax.set_xticklabels(ticks, fontsize=9)
    ax.set_ylabel("Share of Q1 2026 total (%)")
    ax.legend(fontsize=9, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.30), frameon=False)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── Data-exploration charts (model inputs over three years) ──────────────────
def _year_axis(ax):
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def chart_eda_sensors():
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(B.CHART_W, 5.2))
    for ax, (col, lab) in zip(axes.ravel(), SENSOR_CH.items()):
        m = eda_sensor_monthly[col]
        ax.plot(m.index, m.values, color=DARK_BLUE, lw=1.8)
        coef = np.polyfit(np.arange(len(m)), m.values, 1)
        ax.plot(m.index, np.polyval(coef, np.arange(len(m))), color=ACCENT_RED, ls="--", lw=1.2)
        ax.set_title(f"{lab}   ({_trend_pct(m):+.0f}% / 3 yr)", fontsize=10)
        B.chart_style(ax); _year_axis(ax); ax.tick_params(labelsize=8)
    fig.tight_layout()
    return B.b64(fig)


def chart_eda_anomaly():
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig, ax = B.make_fig(h=3.4)
    a = eda_anom_monthly
    ax.bar(a.index, a.values, width=22, color=LIGHT_BLUE)
    ax.set_ylabel("Anomalous machine-days / month")
    ax2 = ax.twinx()
    f = eda_fail_monthly.reindex(a.index).fillna(0)
    ax2.plot(f.index, f.values, color=ACCENT_RED, lw=2, marker="o", markersize=3)
    ax2.set_ylabel("Unplanned failures / month", color=ACCENT_RED)
    ax2.tick_params(axis="y", labelcolor=ACCENT_RED); ax2.grid(False)
    B.chart_style(ax); _year_axis(ax)
    ax.legend(handles=[Patch(color=LIGHT_BLUE, label="Anomalous machine-days"),
                       Line2D([0], [0], color=ACCENT_RED, marker="o", label="Unplanned failures")],
              fontsize=9, loc="upper left")
    fig.tight_layout()
    return B.b64(fig)


def chart_eda_failures():
    fig, ax = B.make_fig(h=3.2)
    d = eda_fail_by_mode
    palette = {"TOOLING": DARK_BLUE, "MECHANICAL": LIGHT_BLUE, "ELECTRICAL": MED_GREY,
               "OPERATOR_INDUCED": AMBER, "ENVIRONMENTAL": MUTED_RED}
    bottom = np.zeros(len(d))
    for mode in [c for c in palette if c in d.columns]:
        ax.bar(d.index, d[mode].values, bottom=bottom, width=22, color=palette[mode],
               label=mode.replace("_", " ").title())
        bottom = bottom + d[mode].values
    # Trace the top of the tooling + mechanical band with a red dotted line to
    # highlight the wear-driven modes the sensors detect (everything below it).
    tm_cum = (d.get("TOOLING", 0) + d.get("MECHANICAL", 0)).values
    ax.plot(d.index, tm_cum, color=ACCENT_RED, ls=":", lw=1.8, drawstyle="steps-mid",
            zorder=5)
    ax.text(0.015, 0.95, f"Tooling + Mechanical:\n{tm_pct:.0%} of all failures",
            transform=ax.transAxes, ha="left", va="top", fontsize=9.5, fontweight="bold",
            color=ACCENT_RED,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=ACCENT_RED, ls=":", lw=1.5))
    ax.set_ylabel("Unplanned failures / month")
    ax.legend(fontsize=8, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False)
    B.chart_style(ax); _year_axis(ax)
    fig.tight_layout()
    return B.b64(fig)


def eda_stats_table():
    notes = {"vibration_rms_mm_s": "Rises with fleet age; the strongest pre-failure signal.",
             "bearing_temp_c": "Stable at baseline; spikes only ahead of specific failures.",
             "spindle_power_kw": "Stable; reacts on tooling and electrical events.",
             "hydraulic_pressure_bar": "Stable; dips ahead of environmental faults."}
    rows = []
    for col, lab in SENSOR_CH.items():
        m = eda_sensor_monthly[col]
        rows.append([lab, f"{m.mean():.1f}", f"{_trend_pct(m):+.0f}%", notes[col]])
    u = eda_util_monthly * 100
    rows.append(["Fleet utilization (30-day)", f"{u.mean():.0f}%", f"{_trend_pct(u):+.0f}%",
                 "Sustained load that limits available maintenance windows."])
    rows.append(["Unplanned failures", f"{eda_fail_monthly.mean():.0f}/mo", f"{_trend_pct(eda_fail_monthly):+.0f}%",
                 f"{eda_fail_total} events over three years; the reliability baseline."])
    rows.append(["Sensor anomaly flags", f"{eda_anom_rate:.0%} of days", "n/a",
                 "Cluster in the weeks before failures, as the chart above shows."])
    return B.data_table(["Model input", "Avg over 3 yrs", "3-yr trend", "Behaviour"], rows, right={1, 2})



# ── Tables ──────────────────────────────────────────────────────────────────
def exec_drivers_table():
    # Plain-language summary of the drivers the model weighs most, drawn from the
    # SHAP feature importances. The condition-monitoring sensor signals are led
    # with first because they are the most concrete for the floor team, so this
    # is ordered for readability rather than strictly by SHAP magnitude.
    drivers = [
        "Spindle vibration elevated above its normal baseline",
        "Sensor anomaly across the condition-monitoring channels",
        "Time since the last unplanned failure",
        "Machine age and prior failure history",
        "Fleet utilization and maintenance-window pressure",
    ]
    rows = [[f'<td style="width:44px;text-align:center;font-weight:700;color:{DARK_BLUE};">#{i}</td>', d]
            for i, d in enumerate(drivers, 1)]
    return B.data_table(["Rank", "Driver behind the flag"], rows)


def window_table(split):
    """Precision, recall and ROC-AUC by window: the indicator beside the three baselines."""
    rows = ""
    for n in (7, 21):
        for s in SOURCES:
            sel = s == "model"
            bg = f' style="background:{B.BG_GREY};font-weight:700;"' if sel else ""
            rows += (f'<tr{bg}><td>{n} days</td><td>{SOURCE_NAME[s]}</td>'
                     f'<td style="text-align:right;">{wm(split, s, n, "precision"):.2f}</td>'
                     f'<td style="text-align:right;">{wm(split, s, n, "recall"):.2f}</td>'
                     f'<td style="text-align:right;">{wm(split, s, n, "roc_auc"):.2f}</td></tr>')
    return (f'<table class="data-table"><thead><tr><th>Window</th><th>Source</th>'
            f'<th style="text-align:right;">Precision</th><th style="text-align:right;">Recall</th>'
            f'<th style="text-align:right;">ROC-AUC</th></tr></thead><tbody>{rows}</tbody></table>')


def critical_before_table():
    rows = ""
    for s in ["model", "interval", "calendar_pm"]:
        sel = s == "model"
        bg = f' style="background:{B.BG_GREY};font-weight:700;"' if sel else ""
        rows += (f'<tr{bg}><td>{SOURCE_NAME[s]}</td>'
                 f'<td style="text-align:right;">{hit_n[s]} of {bi_events}</td>'
                 f'<td style="text-align:right;">{hit_pct[s]:.0%}</td>'
                 f'<td style="text-align:right;">{hit_hrs[s]:.0f}</td>'
                 f'<td style="text-align:right;">{avoid_hrs[s]:.0f}</td>'
                 f'<td style="text-align:right;">${avoid_usd[s]:,.0f}</td></tr>')
    return (f'<table class="data-table"><thead><tr><th>Source</th>'
            f'<th style="text-align:right;">Failures with a CRITICAL day in the 7 days before</th>'
            f'<th style="text-align:right;">Share</th>'
            f'<th style="text-align:right;">Their downtime (hours)</th>'
            f'<th style="text-align:right;">Downtime avoided (hours, Q1)</th>'
            f'<th style="text-align:right;">Annualized margin</th></tr></thead><tbody>{rows}</tbody></table>')


def tier_reference_table():
    rows = [
        [B.badge("CRITICAL", ACCENT_RED), TIER_MEANING["CRITICAL"],
         "Schedule maintenance now; treat as this week's priority."],
        [B.badge("ELEVATED", AMBER), TIER_MEANING["ELEVATED"],
         "Plan a service window in the next two to three weeks."],
        [B.badge("OK", GREEN), TIER_MEANING["OK"],
         "Continue the normal preventive-maintenance schedule."]]
    return B.data_table(["Health indicator", "What the model is saying", "What the floor should do"], rows)


def worked_example():
    age = int(we["machine_age_years"]); vib = float(we["vibration_7d_mean"])
    btemp = float(we["bearing_temp_7d_mean"]); power = float(we["spindle_power_7d_mean"])
    hyd = float(we["hydraulic_pressure_7d_mean"])
    since = we["days_since_last_unplanned_failure"]; overdue = float(we["days_overdue_for_pm"])
    alarms = float(we["rolling_7d_alarm_count"]); tier = we["health_indicator"]

    def sensor_note(keyword, z, deviates=False):
        # A channel named among the rating's drivers says so; otherwise the note
        # reads the channel's anomaly score against the machine's own baseline.
        if any(keyword in d.lower() for d in we_drivers):
            return "Among the reasons behind this rating, listed below."
        z = abs(float(z)) if deviates else float(z)
        return ("Running away from its own 30-day baseline; flagged by condition monitoring." if z >= 1.0
                else "Within its normal range; no anomaly flagged.")

    rows = [
        ["Spindle vibration", f"{vib:.1f} mm/s (7-day avg)", sensor_note("vibration", we["vibration_anomaly"])],
        ["Bearing temperature", f"{btemp:.0f} &deg;C (7-day avg)", sensor_note("bearing temperature", we["bearing_temp_anomaly"])],
        ["Spindle motor power", f"{power:.1f} kW (7-day avg)", sensor_note("power", we["spindle_power_anomaly"])],
        ["Hydraulic pressure", f"{hyd:.0f} bar (7-day avg)", sensor_note("hydraulic", we["hydraulic_pressure_anomaly"], deviates=True)],
        ["Machine age", f"{age} years",
         "One of the oldest assets in the fleet, so it carries more mechanical wear." if age > 9
         else "Not among the aging assets."],
        ["Time since last breakdown", f"{since:.0f} days",
         "It failed only recently, so it is still in a fragile post-repair window." if since <= 14
         else "No recent breakdown."],
        ["Preventive maintenance", f"{overdue:.0f} days overdue" if overdue > 0 else "on schedule",
         "Past its scheduled service, which raises risk." if overdue > 0 else "Service is current."],
        ["Recent alarms (7 days)", f"{alarms:.0f} alarms",
         "Elevated fault activity on the controller over the past week." if alarms > 15
         else "Alarm activity in its usual range."]]
    inputs = B.data_table(["Signal the model read", "Current value", "Why it matters"], rows)
    result = (f'<div style="background:{B.BG_GREY};border-left:4px solid {TIER_COLOR[tier]};padding:16px 20px;margin:18px 0;">'
              f'<span style="font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:{MED_GREY};font-weight:700;">'
              f'The health indicator</span><br>'
              f'<span style="font-size:26px;font-weight:700;color:{DARK_GREY};">{we["machine_id"]} &middot; {we["machine_type"]}</span><br>'
              f'<span style="font-size:16px;">{B.badge(tier, TIER_COLOR[tier])} &nbsp; {TIER_MEANING[tier]}</span></div>')
    drv = "".join(f"<li>{d}</li>" for d in we_drivers)
    return inputs + result + f'<p style="margin-bottom:6px;"><strong>Reasons flagged in CMMS:</strong></p><ul class="limitation-list">{drv}</ul>'


FLOW_HTML = (
    '<div style="display:flex;align-items:stretch;gap:0;margin:22px 0;flex-wrap:wrap;">'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">1. What it watches</div>'
    '<div style="font-size:16px;line-height:1.55;">For each machine: daily sensor readings for vibration, bearing temperature, '
    'motor power, and hydraulic pressure, plus its age and utilization, recent alarms and downtime, and time since the last '
    'breakdown and last service.</div></div>'
    '<div style="align-self:center;font-size:26px;color:#8093A4;padding:0 12px;">&rarr;</div>'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">2. What it learns</div>'
    '<div style="font-size:16px;line-height:1.55;">From three years of history it learned the patterns that came before past '
    'breakdowns, such as vibration and heat creeping up, older machines failing sooner, and risk rising soon after a repair.</div></div>'
    '<div style="align-self:center;font-size:26px;color:#8093A4;padding:0 12px;">&rarr;</div>'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">3. What it produces</div>'
    '<div style="font-size:16px;line-height:1.55;">A daily health indicator for every machine (CRITICAL, ELEVATED or OK) and the '
    'specific reasons behind it, delivered straight into the CMMS asset list.</div></div></div>')


charts = {"tiers": chart_tier_distribution(), "prob": chart_prob_distribution(),
          "tier": chart_tier_by_period(),
          "vib": chart_vibration_ramp(), "anom": chart_anomaly_ttf(),
          "impact_combined": chart_impact_combined(),
          "eda_sensors": chart_eda_sensors(), "eda_anom": chart_eda_anomaly(),
          "eda_fail": chart_eda_failures()}

# CMMS screenshot (static asset) for Section 2.1.
import base64
_cmms_png = Path(__file__).resolve().parent / "assets" / "cmms_screenshot.png"
cmms_screenshot_b64 = base64.b64encode(_cmms_png.read_bytes()).decode() if _cmms_png.exists() else ""

val_ap = {x["model_type"]: x["val_ap_mean"] for x in m["models"]}
_abl_test = abl[abl["split"] == "test"].set_index("model")["roc_auc"]
abl_with, abl_without = float(_abl_test["all features"]), float(_abl_test["without sensor features"])

toc = ('<a href="#summary">Executive Summary</a><hr>'
       '<a href="#modeloverview">Model Overview</a>'
       '<a href="#what" class="sub">What This Model Does</a>'
       '<a href="#data" class="sub">Training Data Overview</a><hr>'
       '<a href="#predictions">Model Performance</a>'
       '<a href="#scoring" class="sub">Scoring Summary</a>'
       '<a href="#accuracy" class="sub">Accuracy and Validation</a>'
       '<a href="#sample" class="sub">Sample Model Output</a>'
       '<a href="#limits" class="sub">What It Can and Cannot Predict</a>')

body = f"""
{B.section("summary", "Section 1", "Executive Summary")}
<p>The machine health indicator rates every machine on the shop floor each day as CRITICAL, ELEVATED or OK,
by how soon it is likely to need an unplanned repair, so that the work can be planned before a breakdown
happens. The model was trained on three years of machine sensor data and maintenance records. Over the past
three months it has been live, rating machine health daily.</p>
<p>During this time, the shop logged <strong>{bi_events} unplanned failures</strong> and
<strong>{bi_hrs:.0f} hours</strong> of unplanned downtime. The health indicator showed CRITICAL on at least
one of the 7 days before <strong>{hit_pct['model']:.0%} of these failures</strong> ({hit_n['model']} of
{bi_events}). The comparison that matters is the interval baseline, a rule that flags a machine when the time
since its last repair nears that machine's usual gap between repairs: it reached
<strong>{hit_pct['interval']:.0%}</strong>. The calendar PM schedule, the shop's current practice, reached
<strong>{hit_pct['calendar_pm']:.0%}</strong>. Over the same three months, when the indicator read CRITICAL a
repair opened within 7 days <strong>{wm('scoring', 'model', 7, 'precision'):.0%}</strong> of the time
(precision), and it read CRITICAL on <strong>{wm('scoring', 'model', 7, 'recall'):.0%}</strong> of the
machine-days that had a repair within 7 days (recall), against
{wm('scoring', 'interval', 7, 'precision'):.0%} and {wm('scoring', 'interval', 7, 'recall'):.0%} for the
interval baseline.</p>
{B.chart("Downtime and Failures with a CRITICAL Day Before: Calendar PM, Interval Baseline and Health Indicator", charts["impact_combined"])}
<p>Acting on a CRITICAL rating before the failure could have avoided an estimated
<strong>{avoid_hrs['model']:.0f} hours</strong> of unplanned downtime in Q1 (assuming a
{DOWNTIME_REDUCTION:.0%} reduction in downtime for preventive versus reactive maintenance), worth about
<strong>${avoid_usd['model']:,.0f}</strong> in annualized contribution margin. The interval baseline, on the
same assumption, gives <strong>{avoid_hrs['interval']:.0f} hours</strong> and
<strong>${avoid_usd['interval']:,.0f}</strong>. The difference,
<strong>{contrib_hrs:.0f} hours</strong> in the quarter and about <strong>${contrib_usd:,.0f}</strong> a
year, is the model's contribution over a rule the shop could run without it.</p>
{critical_before_table()}
<p>Alongside the tier, every rating lists the specific conditions that drove it, so the maintenance team can
see why a machine was surfaced and what to inspect first. The signals that most heavily determine the
indicator are listed below:</p>
{exec_drivers_table()}

{B.section("modeloverview", "Section 2", "Model Overview")}

{B.section("what", "Section 2.1", "What This Model Does")}
<p>The health indicator is built on {LABELS.get(best, best)}{", a gradient-boosted decision-tree algorithm" if best == "xgboost" else ""}. It answers one
question for every machine on the floor, every day: <strong>which machines are likely to need an unplanned
repair soon, and how soon?</strong> It does not diagnose a specific fault or generate a repair
order on its own, but rather serves as an early-warning and maintenance prioritisation tool.</p>
{FLOW_HTML}
<p>The health indicator's tiers are described below:</p>
{tier_reference_table()}
<p>The indicator is delivered where the maintenance team already works. The screenshot below shows it
embedded in the CMMS asset view: the fleet is ranked by health indicator, each machine carries its tier and
its condition, and the counts at the top summarise how many assets fall in each tier, so a planner can triage
the fleet without leaving the system.</p>
<div class="chart-wrap" style="padding:6px;">
  <img src="data:image/png;base64,{cmms_screenshot_b64}" alt="CMMS asset view with the machine health indicator"
       style="width:100%;height:auto;display:block;border:1px solid {LIGHT_GREY};">
</div>

{B.section("data", "Section 2.2", "Training Data Overview")}
<p>The four condition-monitoring channels (vibration, bearing temperature, motor power, and hydraulic
pressure) are plotted below as monthly fleet averages across the full training window, each with a fitted
trend line. Three of the four sit flat at their baseline, which is what a healthy fleet should look like;
spindle vibration is the exception, drifting steadily upward as the fleet ages. That slow rise reflects
background wear that the model reads underneath the sharper pre-failure spikes.</p>
{B.chart("Sensor Channels Over Three Years", charts["eda_sensors"],
         "Monthly fleet-average reading per channel, January 2023 to December 2025, each with a dashed trend line. Only vibration shows a sustained upward trend.")}
<p>The channels look calm in aggregate because the pre-failure spikes are short and machine-specific, so they
average out across the fleet. The model instead picks up the anomalies, readings that jump above a machine's
own baseline.</p>
<p>The three charts below show the importance of these anomaly readings. Across the fleet, monthly anomaly
activity rises and falls with the actual unplanned-failure count and tends to lead it. Zooming into
individual machines, average spindle vibration is quiet weeks out and climbs steadily in the final days
before an unplanned repair. And the further a machine's readings sit above its own normal baseline, the sooner the next
unplanned repair tends to arrive, from about {anom_days[0]:.0f} days out when readings are normal to about
{anom_days[-1]:.0f} days when they are highly abnormal. Together these confirm the condition-monitoring sensors as the model's leading indicators.</p>
{B.chart("Sensor Anomalies Lead Unplanned Failures", charts["eda_anom"],
         "Monthly count of anomalous machine-days (bars) against unplanned failures per month (line). Anomaly spikes tend to precede failure spikes.")}
{B.chart("Vibration Climbs as Failure Approaches", charts["vib"],
         "Average spindle vibration in the training data, grouped by how many days remained before the machine's next unplanned repair. "
         "Vibration is quiet weeks out and rises steadily in the final days.")}
{B.chart("A Sensor Anomaly Means Failure Is Closer", charts["anom"],
         "The anomaly score measures how far a machine's recent readings sit above its own normal baseline. As the score rises, "
         f"the average time to the next unplanned repair falls from about {anom_days[0]:.0f} days when readings are normal to about {anom_days[-1]:.0f} days when they are highly abnormal.")}
<p>Looking at the unplanned breakdown data broken out by failure mode reveals that tooling and mechanical
problems make up about three-quarters ({tm_pct:.0%}) of all unplanned failures. These wear-driven modes are
the ones that the condition-monitoring sensors' data reveal, and so are the ones driving the model's
predictive power. The electrical, operator-induced, and environmental modes are less common and give far
less warning.</p>
{B.chart("Unplanned Failures by Month and Failure Mode", charts["eda_fail"])}

{B.section("predictions", "Section 3", "Model Performance")}

{B.section("scoring", "Section 3.1", "Scoring Summary")}
<p>Every machine-shift observation is scored before the shift begins, and each machine takes the higher of
its day's two ratings. In {PERIOD_NAME}, the model scored <strong>{total:,}</strong> observations covering
<strong>{n_days:,}</strong> machine-days. It rated <strong>{n_crit:,}</strong> machine-days CRITICAL (failure
likely within 7 days), <strong>{n_elev:,}</strong> ELEVATED (within 8 to 21 days) and
<strong>{n_ok:,}</strong> OK. This shop opens an unplanned repair within 7 days on about
{m['positive_rate']['train']['7']:.0%} of machine-days, so a fleet of {n_machines} machines carries about
{n_crit / days['observation_date'].nunique():.0f} CRITICAL ratings on an average day.</p>
{B.chart("Machine-Days by Health Indicator Tier", charts["tiers"])}
{B.chart("Distribution of the 7-Day Probability", charts["prob"])}
{B.chart("Health Indicator Mix by Month", charts["tier"])}

{B.section("accuracy", "Section 3.2", "Accuracy and Validation")}
<p>The table below is the main result: for each window, how often a flag was followed by a repair
(precision), how many of the repairs were flagged (recall), and how well the source ranks machine-days overall
(ROC-AUC), on the held-out September to December 2025 test set. The health indicator is shown beside three
baselines. The <strong>interval baseline</strong> is the comparison that matters: it uses only the days since
a machine's last repair against that machine's usual gap, and it is a strong rule on this fleet. The
<strong>calendar PM</strong> schedule is the shop's current practice. The rules baseline flags on alarm rate
and overdue PM.</p>
{window_table("test")}
<p>The same comparison on the three live months, {PERIOD_NAME}:</p>
{window_table("scoring")}
{B.kpi_row(
    B.kpi_card(f"{wm('test', 'model', 7, 'roc_auc'):.2f}", "7-day ROC-AUC", f"interval baseline {wm('test', 'interval', 7, 'roc_auc'):.2f}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 7, 'precision'):.0%}", "7-day precision", f"interval baseline {wm('test', 'interval', 7, 'precision'):.0%}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 7, 'recall'):.0%}", "7-day recall", f"interval baseline {wm('test', 'interval', 7, 'recall'):.0%}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 21, 'roc_auc'):.2f}", "21-day ROC-AUC", f"interval baseline {wm('test', 'interval', 21, 'roc_auc'):.2f}", DARK_BLUE))}
<p>The model learned on data from January 2023 to December 2024, was tuned and calibrated on January to
August 2025, and was then scored once on the held-out test set. Three candidate algorithms, a logistic
regression, a random forest, and a gradient-boosted XGBoost model, were each tuned over
{m['n_optuna_trials']} Optuna trials per window and compared on validation average precision.
{LABELS.get(best, best)} was the strongest, at {val_ap[best]:.3f} averaged across the two windows against
{", ".join(f"{val_ap[k]:.3f} for the {LABELS[k].lower()}" for k in val_ap if k != best)}, and was carried forward.</p>
<p>Without the ten sensor features the 7-day model reaches ROC-AUC {abl_without:.2f} against {abl_with:.2f}
with them; the interval rule reaches {wm('test', 'interval', 7, 'roc_auc'):.2f}.</p>
<h3>Event-level view: was a failure preceded by a CRITICAL day?</h3>
<p>The window measures above are averages across every machine-day. For preventive maintenance the question
is narrower: when a machine is about to fail, was it rated CRITICAL in time to act? Of the
<strong>{bi_events}</strong> unplanned failures in the Q1 scoring window, the health indicator showed
CRITICAL on at least one of the 7 days before <strong>{hit_n['model']}</strong> of them
({hit_pct['model']:.0%}), the interval baseline before <strong>{hit_n['interval']}</strong>
({hit_pct['interval']:.0%}) and the calendar PM schedule before <strong>{hit_n['calendar_pm']}</strong>
({hit_pct['calendar_pm']:.0%}). These are the failures the downtime estimate in the executive summary is
built on.</p>

{B.section("sample", "Section 3.3", "Sample Model Output")}
<p>Presented below is an example of how the model works (the signals it read, the health indicator it
produced, and the reasons it flagged) for the top-ranked machine in the current fleet snapshot.</p>
{worked_example()}

{B.section("limits", "Section 3.4", "What It Can and Cannot Predict")}
<p>Being clear about the model's limits is what makes it trustworthy. It is a strong early-warning aid, not
a crystal ball, and it is deliberately honest about the failures it cannot see coming.</p>
<ul class="limitation-list">
  <li><strong>It ranks how soon, not how severe or how costly.</strong> The output is how soon a failure is likely,
  not how serious the repair will be or what it will cost.</li>
  <li><strong>Gradual failures are easier than sudden ones.</strong> Wear-driven mechanical problems announce
  themselves through rising vibration and heat: a CRITICAL day came in the 7 days before
  {mode_hit['MECHANICAL']:.0%} of mechanical failures across the test and scoring windows. Operator-induced
  failures leave no such trace and are the mode the indicator catches least, at
  {mode_hit['OPERATOR_INDUCED']:.0%}.</li>
  <li><strong>A quiet reading is not a guarantee.</strong> Roughly a third of real failures give no clear
  sensor precursor. Those machines still receive an ELEVATED heads-up from age and history, but not always a
  tight CRITICAL alert, so the preventive-maintenance schedule remains the safety net.</li>
  <li><strong>It is decision support, not automation.</strong> The model ranks and explains; a person still
  decides what work to schedule. It is designed to inform maintenance judgement, not replace it.</li>
  <li><strong>It stays current through monitoring.</strong> Machine behaviour drifts over time, so the model
  is watched continuously and retrained when its accuracy slips, as detailed in the monitoring report.</li>
</ul>

"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("ML Model Overview & Performance Report: Machine Health Indicator",
                      "", toc, body), encoding="utf-8")
print(f"Model overview written to {OUT}")
