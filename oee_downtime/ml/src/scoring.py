"""
scoring.py
Batch scoring for the machine health indicator.

Loads the registered production model, scores each month of the forward window
(Jan-Mar 2026) independently, assigns the health indicator tier from the three
window probabilities, and derives the top plain-language risk drivers per
observation from SHAP. Writes one file per period for the monitoring layer, the
tier history by machine and day, the evaluation of the model and both baselines
on the scoring window, and a one-row-per-machine fleet snapshot that feeds the
CMMS asset list.

These steps are plain functions; in production they would be wrapped as a
scheduled orchestration flow. Run:  python ml/src/scoring.py
"""
import json
import logging
import warnings
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn

import sys
sys.path.insert(0, str(Path(__file__).parent))
from features import ALL_FEATURES, TARGETS, WINDOWS, ID_COL
from health import (
    PROB_COLS, TIER_RANK, WINDOW_TIER, add_tiers, evaluate, load_mart,
    load_repairs, machine_days, out_of_order_share, shap_values,
)

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
REPO_ROOT   = Path(__file__).resolve().parents[2]
MODELS_DIR  = REPO_ROOT / "ml" / "models"
SCORING_DIR = REPO_ROOT / "ml" / "data" / "scoring"
MLRUNS_DIR  = REPO_ROOT / "ml" / "mlruns"

MLFLOW_TRACKING = f"sqlite:///{(MLRUNS_DIR / 'mlflow.db').as_posix()}"
EXPERIMENT_NAME = "c02_machine_health_indicator"
MODEL_NAME      = "machine_health_indicator"
PROD_ALIAS      = "production"

N_DRIVERS    = 3
PERIODS = [
    ("2026-01-01", "2026-01-31"),
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
]
SCORING_START, SCORING_END = PERIODS[0][0], PERIODS[-1][1]

# The window model that explains each tier; an OK machine is explained by the
# longest window.
TIER_WINDOW = {tier: n for n, tier in WINDOW_TIER.items()} | {"OK": max(WINDOWS)}


# Plain-language risk drivers, keyed by model feature. Each returns a sentence
# built from the machine's own value, with no feature names exposed. Only shown
# when the feature is actually pushing the probability of a repair upward.
def driver_phrase(feature: str, value) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = value
    if feature in ("vibration_anomaly", "vibration_7d_mean"):
        return "Spindle vibration trending above its normal baseline"
    if feature in ("bearing_temp_anomaly", "bearing_temp_7d_mean"):
        return "Bearing temperature running above normal"
    if feature in ("spindle_power_anomaly", "spindle_power_7d_mean"):
        return "Spindle motor power draw elevated"
    if feature in ("hydraulic_pressure_anomaly", "hydraulic_pressure_7d_mean"):
        return "Hydraulic pressure deviating from its normal range"
    if feature in ("sensor_anomaly_score", "is_sensor_anomaly"):
        return "Condition-monitoring sensors flag an anomaly"
    if feature in ("days_overdue_for_pm", "is_pm_overdue") and isinstance(v, float) and v > 0:
        return f"Preventive maintenance overdue by {int(v)} days" if feature == "days_overdue_for_pm" \
               else "Preventive maintenance interval exceeded"
    if feature in ("rolling_7d_alarm_count", "is_high_alarm_rate", "rolling_30d_alarm_count"):
        return "Alarm frequency elevated over the recent window"
    if feature in ("machine_age_years", "is_aging_machine"):
        return "Machine age and failure history indicate elevated mechanical wear risk"
    if feature == "rolling_7d_unplanned_downtime_hours" and isinstance(v, float) and v > 0:
        return f"Recent unplanned downtime elevated ({v:.1f} hrs in the past week)"
    if feature == "days_since_last_unplanned_failure":
        return "Short interval since the last unplanned failure"
    if feature == "count_late_pms_last_6m" and isinstance(v, float) and v > 0:
        return "Repeated late preventive maintenance over the past six months"
    if feature == "rolling_30d_utilization_rate":
        return "Sustained high utilization limiting maintenance windows"
    if feature in ("is_shift_b_transition", "shift"):
        return "Shift-transition downtime pattern detected on this asset"
    if feature == "last_failure_mode":
        return "Recent failure history on this asset"
    return None


# ══════════════════════════════════════════════════════════════════════════════
def load_model():
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    try:
        model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@{PROD_ALIAS}")
        log.info(f"Loaded '{MODEL_NAME}@{PROD_ALIAS}' from MLflow registry")
    except Exception as e:
        log.info(f"Registry load failed ({e}); falling back to local model")
        model = joblib.load(MODELS_DIR / "health_indicator.pkl")
    return model


def risk_drivers(indicator, df: pd.DataFrame) -> list:
    """Top drivers per row: the features pushing the probability of a repair
    upward in the window model behind the row's tier."""
    drivers = [[] for _ in range(len(df))]
    pos = {idx: i for i, idx in enumerate(df.index)}
    for n in WINDOWS:
        rows = df[df["health_indicator"].map(TIER_WINDOW) == n]
        if rows.empty:
            continue
        try:
            sv, names = shap_values(indicator.pipelines[n], rows[ALL_FEATURES])
        except Exception as e:
            log.info(f"  SHAP unavailable for the {n}-day model ({e}); drivers left blank")
            continue
        for i, idx in enumerate(rows.index):
            row = sv[i]
            phrases = []
            for j in np.argsort(-row):         # most positive first = strongest risk
                if row[j] <= 0:
                    break
                ph = driver_phrase(names[j], rows.iloc[i].get(names[j]))
                if ph and ph not in phrases:
                    phrases.append(ph)
                if len(phrases) >= N_DRIVERS:
                    break
            drivers[pos[idx]] = phrases
    return drivers


def run():
    SCORING_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    mlflow.set_experiment(EXPERIMENT_NAME)
    indicator = load_model()
    repairs = load_repairs()

    # Every row is scored so the baselines and the event lookback have the days
    # before the window; only the scoring window is written out per period.
    scored = add_tiers(load_mart(), indicator, repairs)
    scored["health_indicator"] = scored["tier_model"]

    keep = list(dict.fromkeys(
        [ID_COL, "machine_id", "observation_date", "shift", "machine_type"] + ALL_FEATURES
        + list(PROB_COLS.values()) + ["health_indicator", "risk_drivers", "tier_calendar_pm", "tier_rules"]
        + list(TARGETS.values())))
    all_scored = []

    for start, end in PERIODS:
        label = datetime.strptime(start, "%Y-%m-%d").strftime("%Y%m")
        period = scored[(scored["observation_date"] >= start) & (scored["observation_date"] <= end)].copy()
        period["risk_drivers"] = risk_drivers(indicator, period)
        period[[c for c in keep if c in period.columns]].to_parquet(
            SCORING_DIR / f"predictions_{label}.parquet", index=False)

        tiers = machine_days(period, "health_indicator")["tier"].value_counts()
        log.info(f"Period {label}: {len(period):,} scored | machine-days "
                 f"CRITICAL {tiers.get('CRITICAL',0)} ELEVATED {tiers.get('ELEVATED',0)} "
                 f"MONITOR {tiers.get('MONITOR',0)} OK {tiers.get('OK',0)}")

        with mlflow.start_run(run_name=f"scoring_{label}"):
            mlflow.set_tags({"run_type": "scoring", "period": label,
                             "scoring_start": start, "scoring_end": end})
            mlflow.log_metrics({"rows_scored": len(period),
                                "critical_machine_days": int(tiers.get("CRITICAL", 0)),
                                "elevated_machine_days": int(tiers.get("ELEVATED", 0))})
        all_scored.append(period)

    # Tier history by machine and day, all dates: the model and both baselines.
    history = machine_days(scored, "tier_model").rename(columns={"tier": "model"})
    for source in ("calendar_pm", "rules"):
        history[source] = machine_days(scored, f"tier_{source}")["tier"].values
    history.to_parquet(SCORING_DIR / "tier_history.parquet", index=False)

    # Evaluation on the scoring window: the model and both baselines.
    win, events, monthly = evaluate(scored, repairs, indicator.thresholds,
                                    SCORING_START, SCORING_END, "scoring")
    in_window = scored[(scored["observation_date"] >= SCORING_START) & (scored["observation_date"] <= SCORING_END)]
    out_of_order = out_of_order_share(in_window)
    win.to_csv(MODELS_DIR / "evaluation_windows_scoring.csv", index=False)
    events.to_csv(MODELS_DIR / "evaluation_tiers_scoring.csv", index=False)
    monthly.to_csv(MODELS_DIR / "tier_days_scoring.csv", index=False)
    (MODELS_DIR / "scoring_summary.json").write_text(json.dumps({
        "scoring_start": SCORING_START, "scoring_end": SCORING_END,
        "rows_scored": int(len(in_window)),
        "out_of_order_share": out_of_order,
        "windows": win.to_dict(orient="records"),
        "tiers": events.to_dict(orient="records"),
    }, indent=2), encoding="utf-8")
    log.info("\nScoring window, by window:\n" + win.round(4).to_string(index=False))
    log.info("\nScoring window, tiers against failures:\n" + events.round(3).to_string(index=False))
    log.info(f"Window probabilities out of order on {out_of_order:.2%} of scored rows")

    # Fleet snapshot: the latest day per machine, one row per machine, ranked by
    # tier and then by the 7-day probability, for the CMMS asset list.
    combined = pd.concat(all_scored, ignore_index=True)
    last_day = combined[combined["observation_date"]
                        == combined.groupby("machine_id")["observation_date"].transform("max")].copy()
    last_day["tier_rank"] = last_day["health_indicator"].map(TIER_RANK)
    order = ["tier_rank", PROB_COLS[7], "machine_id"]
    latest = (last_day.sort_values(order, ascending=[False, False, True])
              .groupby("machine_id", as_index=False).head(1).reset_index(drop=True))
    snap_cols = (["machine_id", "machine_type", "observation_date", "shift", "health_indicator"]
                 + list(PROB_COLS.values())
                 + ["risk_drivers", "days_overdue_for_pm", "rolling_7d_alarm_count", "machine_age_years"])
    latest[snap_cols].to_parquet(SCORING_DIR / "fleet_snapshot.parquet", index=False)
    log.info(f"Fleet snapshot: {len(latest)} machines -> fleet_snapshot.parquet")
    log.info("Scoring complete.")


if __name__ == "__main__":
    run()
