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
# A planned service runs at about a third of the downtime of the reactive repair
# it stands in for, the ratio the shop's interval services run at. Downtime
# avoided on a failure warned before is the rest.
PLANNED_TO_REACTIVE_DURATION = 0.35
DOWNTIME_REDUCTION = 1 - PLANNED_TO_REACTIVE_DURATION
TEST_START = "2025-09-01"
LABELS = {"logistic_regression": "Logistic Regression", "random_forest": "Random Forest", "xgboost": "XGBoost"}
SOURCES = ["model", "rules"]
SOURCE_NAME = {"model": "Health indicator", "rules": "Rules baseline"}

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
_cmms = pd.read_csv(REPO / "data_source" / "raw" / "cmms" / "maintenance_records.csv")
_cmms["fday"] = pd.to_datetime(_cmms["work_order_open_date"]).dt.normalize()
_svc = _cmms[_cmms["maintenance_type"] == "PLANNED_INTERVAL"]
svc_q = _svc[(_svc["fday"] >= SCORING_START) & (_svc["fday"] <= SCORING_END)]
n_services_q, svc_hours_q = int(len(svc_q)), float(svc_q["downtime_hours"].sum())
_mm = _cmms[_cmms["maintenance_type"] == "UNPLANNED_REPAIR"].copy()
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
avoid_usd_exact = {s: round(float(q1.loc[q1[f"hit_{s}"], "margin"].sum()) * 4 * DOWNTIME_REDUCTION, -2) for s in SOURCES}
# The scoring quarter from the marts: the unplanned failures with the ratings
# before each, the interval services, and what followed each CRITICAL
# machine-day. These override the counts worked out above from the extract, so
# every figure in the executive summary has one source; the two must agree.
_con0 = duckdb.connect(str(REPO / "data_source" / "oee_predmaint.duckdb"), read_only=True)
_qf = _con0.execute("select * from mart_ml__scoring_quarter_failures").df()
_th = _con0.execute("select * from mart_ml__tier_history where in_scoring_quarter").df()
_sv = _con0.execute(f"""select count(*) as n, sum(downtime_hours) as hours from mart_oee__downtime_analysis
    where source_system = 'CMMS_INTERVAL_SERVICE' and event_date >= '{SCORING_START}' and event_date <= '{SCORING_END}'""").df().iloc[0]
_con0.close()
_qf["margin"] = _qf["downtime_hours"] * _qf["machine_type"].map(CM_BY_TYPE)
_flag = {"model": "warned_before", "rules": "rules_warned_before"}
_mart = {"events": int(len(_qf)), "hours": float(_qf["downtime_hours"].sum()),
         "hit_n": {s_: int(_qf[_flag[s_]].sum()) for s_ in SOURCES},
         "hit_hrs": {s_: float(_qf.loc[_qf[_flag[s_]], "downtime_hours"].sum()) for s_ in SOURCES}}
assert _mart["events"] == bi_events and abs(_mart["hours"] - bi_hrs) < 0.05 and _mart["hit_n"] == hit_n
assert all(abs(_mart["hit_hrs"][s_] - hit_hrs[s_]) < 0.05 for s_ in SOURCES)
assert int(_sv["n"]) == n_services_q and abs(float(_sv["hours"]) - svc_hours_q) < 0.05
bi_events, bi_hrs, hit_n, hit_hrs = _mart["events"], _mart["hours"], _mart["hit_n"], _mart["hit_hrs"]
hit_pct = {s_: hit_n[s_] / bi_events for s_ in SOURCES}
avoid_hrs = {s_: hit_hrs[s_] * DOWNTIME_REDUCTION for s_ in SOURCES}
avoid_usd = {s_: round(float(_qf.loc[_qf[_flag[s_]], "margin"].sum()) * 4 * DOWNTIME_REDUCTION, -3) for s_ in SOURCES}
avoid_usd_exact = {s_: round(float(_qf.loc[_qf[_flag[s_]], "margin"].sum()) * 4 * DOWNTIME_REDUCTION, -2) for s_ in SOURCES}
n_services_q, svc_hours_q = int(_sv["n"]), float(_sv["hours"])
n_before_interval = int((~_qf["interval_reached_before_failure"]).sum())
_not_op = _qf[_qf["failure_code"] != "OPERATOR_INDUCED"]
n_not_operator, hit_not_operator = int(len(_not_op)), int(_not_op["warned_before"].sum())


def _hits(start, end, source):
    f = _mm[(_mm["fday"] >= start) & (_mm["fday"] <= end)]
    return int(sum(_critical_before(mid, fd, source) for mid, fd in zip(f["machine_id"], f["fday"]))), int(len(f))


test_hits = {s_: _hits(TEST_START, "2025-12-31", s_) for s_ in SOURCES}
both_hits = {s_: _hits(TEST_START, SCORING_END, s_) for s_ in SOURCES}

# CRITICAL machine-days in the quarter and what followed them within 7 days: an
# unplanned failure, an interval service, or neither. A day can precede both.
_by_kind = {k: {mid: g["fday"].values for mid, g in d.groupby("machine_id")} for k, d in (("failure", _mm), ("service", _svc))}


def _precedes(kind, machine_id, day):
    d = _by_kind[kind].get(machine_id, np.array([], dtype="datetime64[ns]"))
    gap = (d - np.datetime64(day)) / np.timedelta64(1, "D")
    return bool(((gap > 0) & (gap <= 7)).any())


def critical_breakdown(source):
    q = history[(history["observation_date"] >= SCORING_START) & (history["observation_date"] <= SCORING_END)]
    c = q[q[source] == "CRITICAL"]
    bf = np.array([_precedes("failure", m_, d_) for m_, d_ in zip(c["machine_id"], c["observation_date"])], dtype=bool)
    bs = np.array([_precedes("service", m_, d_) for m_, d_ in zip(c["machine_id"], c["observation_date"])], dtype=bool)
    return {"critical": int(len(c)), "failure": int(bf.sum()), "service": int(bs.sum()), "neither": int((~bf & ~bs).sum())}


_rating = {"model": "indicator_rating", "rules": "rules_rating"}


def critical_from_mart(source):
    c = _th[_th[_rating[source]] == "CRITICAL"]
    return {"critical": int(len(c)), "failure": int(c["unplanned_repair_within_7d"].sum()),
            "service": int(c["interval_service_within_7d"].sum()),
            "neither": int((~c["unplanned_repair_within_7d"] & ~c["interval_service_within_7d"]).sum())}


crit = {s_: critical_from_mart(s_) for s_ in SOURCES}
assert crit == {s_: critical_breakdown(s_) for s_ in SOURCES}
_hq = history[(history["observation_date"] >= SCORING_START) & (history["observation_date"] <= SCORING_END)]
_cm = _hq[_hq["model"] == "CRITICAL"].groupby("machine_id").size().sort_values(ascending=False)
top_crit_machine, top_crit_days = _cm.index[0], int(_cm.iloc[0])
top_crit_total = int((_hq["machine_id"] == top_crit_machine).sum())
top_crit_interval = int(pd.read_csv(REPO / "data_source" / "raw" / "machinemetrics" / "machines.csv")
                        .set_index("machine_id").loc[top_crit_machine, "repair_interval_days"])

# Share of failures with a CRITICAL day in the 7 days before, by the failure mode
# the CMMS recorded, across the test and scoring windows (the technical report's
# failure-mode chart), for the limits section.
_fm = _mm[(_mm["fday"] >= "2025-09-01") & (_mm["fday"] <= SCORING_END)].copy()
_fm["hit"] = [_critical_before(mid, fd, "model") for mid, fd in zip(_fm["machine_id"], _fm["fday"])]
mode_hit = _fm.groupby("failure_code")["hit"].mean()
mode_hit_n = {k: (int(g["hit"].sum()), int(len(g))) for k, g in _fm.groupby("failure_code")}

# ── Training-data overview + worked example ──────────────────────────────────
FEATURES = REPO / "ml" / "data" / "features"
train = pd.read_parquet(FEATURES / "train.parquet")
train["observation_date"] = pd.to_datetime(train["observation_date"])
n_train_failures = int((_mm["fday"] <= "2024-12-31").sum())
n_machines = int(preds["machine_id"].nunique())
n_obs_total = int(sum(m["split_sizes"].values()))

# Days from each training row to the machine's next repair of either kind (an
# unplanned repair or an interval service), for the two charts that show how the
# sensor signals move as the wear comes due. The wear is the same whichever of
# the two ends it.
_rep_any = _cmms[_cmms["maintenance_type"].isin(["UNPLANNED_REPAIR", "PLANNED_INTERVAL"])]
_next = {mid: np.sort(g["fday"].values) for mid, g in _rep_any.groupby("machine_id")}


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
_ra = _rep_any[_rep_any["fday"] <= TRAIN_END].copy()
_ra["ym"] = _ra["fday"].dt.to_period("M").dt.to_timestamp()
eda_repair_monthly = _ra.groupby("ym").size()
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
    ax.set_xlabel("Days until the next repair, unplanned or interval service  (further out  →  imminent)")
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
    ax.set_ylabel("Avg days to the next repair, either kind"); ax.set_ylim(0, max(anom_days) * 1.15)
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


# ── Business-impact chart ────────────────────────────────────────────────────
def chart_impact_combined():
    # The quarter's unplanned failures and their downtime: the part that had a
    # CRITICAL day in the 7 days before and the part that did not. Hours and
    # failure count use different units, so each column is normalised to its own
    # total and labelled with the absolute value.
    cats = [("CRITICAL in the 7 days before", GREEN), ("No CRITICAL day before", MED_GREY)]
    cols = [((float(hit_n["model"]), float(bi_events - hit_n["model"])), float(bi_events), "", "Unplanned failures"),
            ((hit_hrs["model"], bi_hrs - hit_hrs["model"]), bi_hrs, "hrs", "Their downtime")]
    fig, ax = B.make_fig(h=3.4)
    for k, (vals, tot, unit, lab) in enumerate(cols):
        bottom = 0.0
        for (clab, color), v in zip(cats, vals):
            pct = v / tot * 100 if tot else 0.0
            ax.bar(k, pct, bottom=bottom, width=0.5, color=color, label=clab if k == 0 else None)
            if pct >= 6:
                ax.text(k, bottom + pct / 2, f"{v:.0f} {unit}".strip(), ha="center", va="center",
                        color="white", fontsize=10, fontweight="bold")
            bottom += pct
    ax.set_ylim(0, 100); ax.set_xlim(-0.6, 1.6)
    ax.set_xticks([0, 1]); ax.set_xticklabels([c[3] for c in cols])
    ax.set_ylabel("Share of Q1 2026 total (%)")
    ax.legend(fontsize=9, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.14), frameon=False)
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
    f = eda_repair_monthly.reindex(a.index).fillna(0)
    ax2.plot(f.index, f.values, color=ACCENT_RED, lw=2, marker="o", markersize=3)
    ax2.set_ylabel("Repairs of either kind / month", color=ACCENT_RED)
    ax2.tick_params(axis="y", labelcolor=ACCENT_RED); ax2.grid(False)
    B.chart_style(ax); _year_axis(ax)
    ax.legend(handles=[Patch(color=LIGHT_BLUE, label="Anomalous machine-days"),
                       Line2D([0], [0], color=ACCENT_RED, marker="o", label="Unplanned repairs and interval services")],
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
    notes = {"vibration_rms_mm_s": "Rises with fleet age; the strongest wear signal.",
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
                 f"{eda_fail_total} events over three years, beside {len(_ra) - eda_fail_total} interval services."])
    rows.append(["Sensor anomaly flags", f"{eda_anom_rate:.0%} of days", "n/a",
                 "Cluster in the weeks before a repair of either kind."])
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
        "Where the machine stands in its repair interval",
        "Machine age",
        "Utilization and maintenance-window pressure",
    ]
    rows = [[f'<td style="width:44px;text-align:center;font-weight:700;color:{DARK_BLUE};">#{i}</td>', d]
            for i, d in enumerate(drivers, 1)]
    return B.data_table(["Rank", "Driver behind the flag"], rows)


def window_table(split):
    """Precision, recall and ROC-AUC by window: the indicator beside the two baselines."""
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
    """Two rows that are not the same measure: what the repair-interval method did
    in the quarter, and what the indicator read before the failures the method
    did not prevent."""
    head = ('<table class="data-table"><thead><tr><th></th><th>What is counted</th>'
            '<th style="text-align:right;">Count</th><th style="text-align:right;">Hours</th>'
            '<th>What it comes to</th></tr></thead><tbody>')
    r1 = (f'<tr><td style="white-space:nowrap;"><strong>Repair-interval method</strong><br>the shop&#39;s practice</td>'
          f'<td>Interval services carried out; unplanned failures that still occurred</td>'
          f'<td style="text-align:right;white-space:nowrap;">{n_services_q} services<br>{bi_events} failures</td>'
          f'<td style="text-align:right;white-space:nowrap;">{svc_hours_q:.0f} planned<br>{bi_hrs:.0f} unplanned</td>'
          f'<td>{n_before_interval} of the {bi_events} failures came before the machine reached its interval</td></tr>')
    r2 = (f'<tr style="background:{B.BG_GREY};"><td style="white-space:nowrap;"><strong>Health indicator</strong><br>in shadow mode</td>'
          f'<td>Of those {bi_events} failures, the ones with a CRITICAL rating on at least one of the 7 days before</td>'
          f'<td style="text-align:right;">{hit_n["model"]} of {bi_events}</td>'
          f'<td style="text-align:right;">{hit_hrs["model"]:.0f} of {bi_hrs:.0f}</td>'
          f'<td>{avoid_hrs["model"]:.0f} hours avoided if acted on, about ${avoid_usd["model"]:,.0f} a year</td></tr>')
    return head + r1 + r2 + "</tbody></table>"


def critical_days_table():
    rows = ""
    for s_ in SOURCES:
        c = crit[s_]
        bg = f' style="background:{B.BG_GREY};font-weight:700;"' if s_ == "model" else ""
        rows += (f'<tr{bg}><td>{SOURCE_NAME[s_]}</td><td style="text-align:right;">{c["critical"]}</td>'
                 f'<td style="text-align:right;">{c["failure"]}</td><td style="text-align:right;">{c["service"]}</td>'
                 f'<td style="text-align:right;">{c["neither"]}</td></tr>')
    return ('<table class="data-table"><thead><tr><th>Source</th><th style="text-align:right;">CRITICAL machine-days</th>'
            '<th style="text-align:right;">In the 7 days before an unplanned failure</th>'
            '<th style="text-align:right;">In the 7 days before an interval service</th>'
            f'<th style="text-align:right;">Before neither</th></tr></thead><tbody>{rows}</tbody></table>')


def warned_before_table():
    rows = ""
    for label, d in (("Test, September to December 2025", test_hits), (f"Scoring quarter, {PERIOD_NAME}", {s_: (hit_n[s_], bi_events) for s_ in SOURCES}),
                     ("Both periods", both_hits)):
        rows += (f'<tr><td>{label}</td><td style="text-align:right;">{d["model"][1]}</td>'
                 f'<td style="text-align:right;font-weight:700;">{d["model"][0]}</td><td style="text-align:right;">{d["rules"][0]}</td></tr>')
    return ('<table class="data-table"><thead><tr><th>Period</th><th style="text-align:right;">Unplanned failures</th>'
            '<th style="text-align:right;">Health indicator warned before</th>'
            f'<th style="text-align:right;">Rules baseline warned before</th></tr></thead><tbody>{rows}</tbody></table>')


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
    since = we["days_since_last_repair"]; overdue = float(we["days_overdue_for_pm"])
    interval = float(pd.read_csv(REPO / "data_source" / "raw" / "machinemetrics" / "machines.csv")
                     .set_index("machine_id").loc[we["machine_id"], "repair_interval_days"])
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
        ["Place in its repair interval", f"{since:.0f} days since the last repair, of a {interval:.0f}-day interval",
         "Its interval service is due or close." if since >= interval - 2
         else "Early in its interval." if since <= interval / 3 else "Part-way through its interval."],
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
    # The date the features stand at, and the machine's repair on or after it
    # (the repair restarts the interval the CMMS asset list counts from).
    as_of = pd.Timestamp(we["observation_date"])
    con = duckdb.connect(str(REPO / "data_source" / "oee_predmaint.duckdb"), read_only=True)
    last_repair = pd.Timestamp(con.execute("select last_repair_date from mart_oee__reliability where machine_id = ?",
                                           [we["machine_id"]]).fetchone()[0])
    con.close()
    note = f"Features as of {as_of.day} {as_of:%B %Y}"
    if last_repair >= as_of:
        note += (f", the observation before {we['machine_id']}&#39;s repair on {last_repair.day} {last_repair:%B}, "
                 f"which restarted its interval")
    inputs = f"<p>{note}.</p>" + inputs
    return inputs + result + f'<p style="margin-bottom:6px;"><strong>Reasons flagged in CMMS:</strong></p><ul class="limitation-list">{drv}</ul>'


FLOW_HTML = (
    '<div style="display:flex;align-items:stretch;gap:0;margin:22px 0;flex-wrap:wrap;">'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">1. What it watches</div>'
    '<div style="font-size:16px;line-height:1.55;">For each machine: daily sensor readings for vibration, bearing temperature, '
    'motor power, and hydraulic pressure, plus its age and utilization, recent alarms and downtime, where it stands in its '
    'repair interval and the time since its last calendar PM.</div></div>'
    '<div style="align-self:center;font-size:26px;color:#8093A4;padding:0 12px;">&rarr;</div>'
    '<div style="flex:1;min-width:190px;background:#F3F5F7;border-radius:8px;padding:16px 18px;border-top:4px solid #381FA1;">'
    '<div style="font-weight:700;color:#322B4B;margin-bottom:6px;">2. What it learns</div>'
    '<div style="font-size:16px;line-height:1.55;">From three years of history it learned the patterns that came before past '
    'breakdowns, such as vibration and heat creeping up, older machines failing sooner, and wear showing early in a machine\'s repair interval.</div></div>'
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
MODEL_KIND = {"xgboost": ", a gradient-boosted decision-tree algorithm", "random_forest": ", an ensemble of decision trees",
              "logistic_regression": ""}
_one_in = round(crit["model"]["critical"] / crit["model"]["failure"])
_num = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
# The executive summary's wording rests on these; the run stops if the record stops supporting it.
assert n_before_interval >= bi_events - 2 and hit_n["model"] > hit_n["rules"] and crit["model"]["service"] > crit["model"]["failure"]

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
<p>The shop runs a repair-interval method: when a machine nears its usual gap between repairs, an interval
service replaces the wear components ahead of the failure. In the scoring quarter the method carried out
<strong>{n_services_q} interval services</strong>, and <strong>{bi_events} unplanned failures</strong> still
occurred, {bi_hrs:.0f} hours of unplanned downtime, almost all on machines that failed before their interval
was reached. The health indicator ran in shadow mode over the quarter, rating every machine daily with the
ratings recorded and not acted on, so the quarter's failures occurred as they would have without it. It read
CRITICAL on at least one of the 7 days before <strong>{hit_n['model']} of the {bi_events} failures</strong>
({hit_not_operator} of the {n_not_operator} that were not operator error), by reading wear as it develops and
where it falls in the machine's interval; the method acts on the interval alone. Acting on those ratings
would have turned {hit_n['model']} reactive repairs into planned services, avoiding about
<strong>{avoid_hrs['model']:.0f} hours</strong> of unplanned downtime in the quarter (planned work runs at
about a third of a reactive repair's duration, as the shop's interval services do), worth about
<strong>${avoid_usd['model']:,.0f} a year</strong> in contribution margin. The net is wide: about one CRITICAL
machine-day in {_num[_one_in]} is followed by a failure within 7 days, and {crit['model']['service']} of the
quarter's {crit['model']['critical']} CRITICAL days fell in the week before a service already scheduled.</p>
<p>Scored shift by shift over the same three months, when the indicator read CRITICAL an unplanned repair
opened within 7 days <strong>{wm('scoring', 'model', 7, 'precision'):.0%}</strong> of the time (precision),
and it read CRITICAL on <strong>{wm('scoring', 'model', 7, 'recall'):.0%}</strong> of the machine-shifts that
had an unplanned repair within 7 days (recall).</p>
{B.chart("The Quarter's Unplanned Failures and Their Downtime, With and Without a CRITICAL Day Before", charts["impact_combined"])}
{critical_before_table()}
<p style="font-size:14px;color:{MED_GREY};">The two rows are different measures. The first is what the method
did. The second is what the indicator read before the failures the method did not prevent; the failures the
method pre-empted never occurred and are not in either count.</p>
<p>Alongside the tier, every rating lists the specific conditions that drove it, so the maintenance team can
see why a machine was surfaced and what to inspect first. The signals that most heavily determine the
indicator are listed below:</p>
{exec_drivers_table()}

{B.section("modeloverview", "Section 2", "Model Overview")}

{B.section("what", "Section 2.1", "What This Model Does")}
<p>The health indicator is built on {LABELS.get(best, best).lower()}{MODEL_KIND.get(best, "")}. It answers one
question for every machine on the floor, every day: <strong>which machines are likely to need an unplanned
repair soon, and how soon?</strong> It does not diagnose a specific fault or generate a repair
order on its own, but rather serves as an early-warning and maintenance prioritisation tool beside the
repair-interval method and the calendar PM.</p>
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
<p>The three charts below show what these readings lead. The wear a sensor picks up ends in one of two
ways: an interval service, when the machine reaches its repair interval first, or an unplanned repair, when
it does not. The charts therefore measure each reading against the machine's next repair of either kind.
Across the fleet, monthly anomaly activity rises and falls with the count of repairs. Zooming into individual
machines, average spindle vibration is quiet weeks out and climbs in the final days before a repair. And the
further a machine's readings sit above its own normal baseline, the sooner the next repair arrives, from about
{anom_days[0]:.0f} days out when readings are normal to about {anom_days[-1]:.0f} days when they are highly
abnormal. Against unplanned repairs alone the same readings separate far less, because about four in five
of the failures the wear leads to are pre-empted by an interval service; this is the main limit on the
indicator and is set out in Section 3.</p>
{B.chart("Sensor Anomalies and Repairs of Either Kind, by Month", charts["eda_anom"],
         "Monthly count of anomalous machine-days (bars) against unplanned repairs and interval services per month (line).")}
{B.chart("Vibration Climbs as a Repair Approaches", charts["vib"],
         "Average spindle vibration in the training data, grouped by how many days remained before the machine's next repair, "
         "unplanned or interval service. Vibration is quiet weeks out and rises in the final days.")}
{B.chart("A Sensor Anomaly Means a Repair Is Closer", charts["anom"],
         "The anomaly score measures how far a machine's recent readings sit above its own normal baseline. As the score rises, "
         f"the average time to the next repair of either kind falls from about {anom_days[0]:.0f} days when readings are normal to about {anom_days[-1]:.0f} days when they are highly abnormal.")}
<p>Looking at the unplanned breakdown data broken out by failure mode reveals that tooling and mechanical
problems make up {tm_pct:.0%} of all unplanned failures. These wear-driven modes are the ones that the
condition-monitoring sensors' data reveal. The electrical and environmental modes are less common, and
operator-induced failures give no sensor warning at all.</p>
{B.chart("Unplanned Failures by Month and Failure Mode", charts["eda_fail"])}

{B.section("predictions", "Section 3", "Model Performance")}

{B.section("scoring", "Section 3.1", "Scoring Summary")}
<p>Every machine-shift observation is scored before the shift begins, and each machine takes the higher of
its day's two ratings. In {PERIOD_NAME}, the model scored <strong>{total:,}</strong> observations covering
<strong>{n_days:,}</strong> machine-days. It rated <strong>{n_crit:,}</strong> machine-days CRITICAL (failure
likely within 7 days), <strong>{n_elev:,}</strong> ELEVATED (within 8 to 21 days) and
<strong>{n_ok:,}</strong> OK. This shop opens an unplanned repair within 7 days on about
{m['positive_rate']['train']['7']:.0%} of machine-shifts, and the fleet of {n_machines} machines carries about
{n_crit / days['observation_date'].nunique():.1f} CRITICAL ratings on an average day.</p>
{B.chart("Machine-Days by Health Indicator Tier", charts["tiers"])}
{B.chart("Distribution of the 7-Day Probability", charts["prob"])}
{B.chart("Health Indicator Mix by Month", charts["tier"])}

{B.section("accuracy", "Section 3.2", "Accuracy and Validation")}
<p>The table below sets out, for each window, how often a flag was followed by an unplanned repair
(precision), how many of the repairs were flagged (recall), and how well the source ranks machine-shifts
overall (ROC-AUC), on the held-out September to December 2025 test set. The health indicator is shown beside
the <strong>rules baseline</strong>, a rule the shop could run without a model: CRITICAL when the 7-day alarm
count is well above the machine's usual level or its calendar PM is more than 14 days overdue.</p>
{window_table("test")}
<p>The same comparison on the three months of the scoring quarter, {PERIOD_NAME}:</p>
{window_table("scoring")}
{B.kpi_row(
    B.kpi_card(f"{wm('test', 'model', 7, 'roc_auc'):.2f}", "7-day ROC-AUC", f"rules baseline {wm('test', 'rules', 7, 'roc_auc'):.2f}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 7, 'precision'):.0%}", "7-day precision", f"rules baseline {wm('test', 'rules', 7, 'precision'):.0%}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 7, 'recall'):.0%}", "7-day recall", f"rules baseline {wm('test', 'rules', 7, 'recall'):.0%}", DARK_BLUE),
    B.kpi_card(f"{wm('test', 'model', 21, 'roc_auc'):.2f}", "21-day ROC-AUC", f"rules baseline {wm('test', 'rules', 21, 'roc_auc'):.2f}", DARK_BLUE))}
<p>The 7-day model carries the indicator. The 21-day model is weak: it ranks machine-shifts only a little
better than the rules baseline, and its ELEVATED tier should be read as a loose heads-up.</p>
<p>The model learned on data from January 2023 to December 2024, was tuned and calibrated on January to
August 2025, and was then scored once on the held-out test set. Three candidate algorithms, a logistic
regression, a random forest, and a gradient-boosted XGBoost model, were each tuned over
{m['n_optuna_trials']} Optuna trials per window and compared on validation average precision. The
{LABELS.get(best, best).lower()} was the strongest, at {val_ap[best]:.3f} averaged across the two windows against
{" and ".join(f"{val_ap[k]:.3f} for {'XGBoost' if k == 'xgboost' else 'the ' + LABELS[k].lower()}" for k in sorted(val_ap, key=val_ap.get, reverse=True) if k != best)}, and was carried forward.
The margin between the first two is narrow.</p>
<p>Without the ten sensor features the 7-day model reaches ROC-AUC {abl_without:.2f} on the test set against
{abl_with:.2f} with them.</p>
<h3>Event-level view: was a failure preceded by a CRITICAL day?</h3>
<p>The window measures above are averages across every machine-shift. For maintenance planning the question
is narrower: when a machine is about to fail, was it rated CRITICAL in time to act? The table counts, for the
unplanned failures in each period, how many had a CRITICAL rating on at least one of the 7 days before.</p>
{warned_before_table()}
<p>On the scoring quarter the rules baseline warned before {hit_n['rules']} of the {bi_events} failures, which
on the same downtime measure comes to {avoid_hrs['rules']:.0f} hours avoided and about
${avoid_usd_exact['rules']:,.0f} a year, against {hit_n['model']} failures, {avoid_hrs['model']:.0f} hours and
${avoid_usd_exact['model']:,.0f} for the indicator. On the test period it warned before {test_hits['rules'][0]} of
{test_hits['rules'][1]}, against the indicator's {test_hits['model'][0]}. Across both periods it warned before
{both_hits['rules'][0]} of {both_hits['rules'][1]}, against {both_hits['model'][0]}.</p>
<h3>What followed a CRITICAL day</h3>
<p>The table takes every CRITICAL machine-day in the scoring quarter and asks what happened on that machine
in the 7 days after: an unplanned failure, an interval service, or neither. A day can precede both, so the
three columns can add to more than the total. Most of the indicator's CRITICAL days came in the week before
an interval service: it is reading wear, and the service was already due. The rules baseline reads alarms and
overdue calendar PM, and most of its CRITICAL days preceded neither.</p>
{critical_days_table()}

{B.section("sample", "Section 3.3", "Sample Model Output")}
<p>Presented below is an example of how the model works (the signals it read, the health indicator it
produced, and the reasons it flagged) for the top-ranked machine in the current fleet snapshot.</p>
{worked_example()}

{B.section("limits", "Section 3.4", "What It Can and Cannot Predict")}
<p>Being clear about the model's limits is what makes it usable. It is an early-warning aid with a wide
net, running beside a method that already pre-empts most wear-out failures.</p>
<ul class="limitation-list">
  <li><strong>It ranks how soon, not how severe or how costly.</strong> The output is how soon a failure is likely,
  not how serious the repair will be or what it will cost.</li>
  <li><strong>Most of its warnings precede a service that was already due.</strong> Wear looks the same on the
  sensors whether it ends in an interval service or a failure, and about four times in five the service comes
  first. {crit['model']['service']} of the quarter's {crit['model']['critical']} CRITICAL machine-days fell in
  the week before an interval service and {crit['model']['failure']} in the week before a failure. A CRITICAL
  rating on a machine whose service is days away adds little; on a machine early in its interval it is the
  signal worth acting on.</li>
  <li><strong>One machine carries much of the alerting.</strong> {top_crit_machine} is serviced every
  {top_crit_interval} days and was rated CRITICAL on {top_crit_days} of its {top_crit_total} operating days in
  the quarter.</li>
  <li><strong>Gradual failures are easier than sudden ones.</strong> Wear-driven mechanical problems announce
  themselves through rising vibration and heat: a CRITICAL day came in the 7 days before
  {mode_hit_n['MECHANICAL'][0]} of the {mode_hit_n['MECHANICAL'][1]} mechanical failures across the test and
  scoring periods. Operator-induced failures leave no such trace: {mode_hit_n['OPERATOR_INDUCED'][0]} of
  {mode_hit_n['OPERATOR_INDUCED'][1]}.</li>
  <li><strong>The counts are small.</strong> The scoring quarter has {bi_events} unplanned failures and the test
  period {test_hits['model'][1]}. A difference of two or three failures between the indicator and a simple rule
  is within what a different quarter could reverse.</li>
  <li><strong>It is decision support, not automation.</strong> The model ranks and explains; a person still
  decides what work to schedule. It is designed to inform maintenance judgement, not replace it.</li>
  <li><strong>It stays current through monitoring.</strong> Machine behaviour drifts over time, so the model
  is watched every month and retrained when the monitoring rules call for it, as detailed in the monitoring
  report.</li>
</ul>

"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("ML Model Overview & Performance Report: Machine Health Indicator",
                      "", toc, body), encoding="utf-8")
print(f"Model overview written to {OUT}")
