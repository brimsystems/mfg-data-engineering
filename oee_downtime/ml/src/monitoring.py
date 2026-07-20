"""
monitoring.py
Batch monitoring for the machine health indicator, run per calendar month
(Jan-Mar 2026), each month compared against the training/validation references.
Four layers:

  1. Performance      - 7-day average precision in the period vs the held-out
                        test value (recall of the CRITICAL plus ELEVATED tiers rests
                        on a handful of failures a month, so it is recorded but not
                        used as the check)
  2. Target drift     - the 7-day positive rate in the period vs training
  3. Prediction drift - the 7-day probability distribution vs the validation reference
  4. Feature drift    - input feature distributions vs training

Drift metric: Evidently ValueDrift with the Jensen-Shannon distance (0-1);
drift is flagged when distance >= threshold (a distance test, not a p-value).

Retraining logic: 7-day average precision more than 0.10 below test, or target
drift, are primary triggers (RETRAIN); prediction or feature drift are secondary
(INVESTIGATE). A trigger must persist across two consecutive periods before it
is recommended.

Run:  python ml/src/monitoring.py
"""
import json
import logging
import warnings
from pathlib import Path

import pandas as pd
import mlflow
from sklearn.metrics import average_precision_score, roc_auc_score
from evidently import Dataset, DataDefinition, Report
from evidently.metrics import ValueDrift

import sys
sys.path.insert(0, str(Path(__file__).parent))
from features import CATEGORICAL_FEATURES, ALL_FEATURES, TARGETS
from health import PROB_COLS, event_metrics, load_repairs

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
REPO_ROOT      = Path(__file__).resolve().parents[2]
FEATURES_DIR   = REPO_ROOT / "ml" / "data" / "features"
SCORING_DIR    = REPO_ROOT / "ml" / "data" / "scoring"
MONITORING_DIR = REPO_ROOT / "ml" / "data" / "monitoring"
MODELS_DIR     = REPO_ROOT / "ml" / "models"
MLRUNS_DIR     = REPO_ROOT / "ml" / "mlruns"

MLFLOW_TRACKING = f"sqlite:///{(MLRUNS_DIR / 'mlflow.db').as_posix()}"
EXPERIMENT_NAME = "c02_machine_health_indicator"

PERIODS = [
    ("202601", "January 2026",  "2026-01-01", "2026-01-31"),
    ("202602", "February 2026", "2026-02-01", "2026-02-28"),
    ("202603", "March 2026",    "2026-03-01", "2026-03-31"),
]

DRIFT_THRESHOLD      = 0.10   # Jensen-Shannon distance flag
AP_TOLERANCE         = 0.10   # period 7-day average precision below (test value - this) is degraded
MAX_DRIFTED_FEATURES = 3      # feature-drift count that warrants investigation
RECALL_KEY           = "critical_or_elevated_within_21d_share"


def js_drift(ref: pd.DataFrame, cur: pd.DataFrame, cols: list, cat_cols: list):
    """Per-column Jensen-Shannon drift distances (ref vs cur). Returns a table
    and the Evidently result (for the HTML artifact)."""
    num_cols = [c for c in cols if c not in cat_cols]
    r, c = ref[cols].copy(), cur[cols].copy()
    for col in cat_cols:
        r[col] = r[col].astype(str); c[col] = c[col].astype(str)
    for col in num_cols:
        r[col] = r[col].astype(float); c[col] = c[col].astype(float)
    dd = DataDefinition(numerical_columns=num_cols, categorical_columns=cat_cols)
    rds = Dataset.from_pandas(r, data_definition=dd)
    cds = Dataset.from_pandas(c, data_definition=dd)
    metrics = [ValueDrift(column=col, method="jensenshannon") for col in cols]
    res = Report(metrics).run(reference_data=rds, current_data=cds)
    vals = [float(m.get("value")) for m in res.dict()["metrics"]]
    table = pd.DataFrame({
        "feature": cols,
        "drift_score": [round(v, 4) for v in vals],
        "drift_detected": [v >= DRIFT_THRESHOLD for v in vals],
    }).sort_values("drift_score", ascending=False).reset_index(drop=True)
    return table, res


def one_col_drift(ref_vals: pd.Series, cur_vals: pd.Series, name: str, categorical: bool = False) -> float:
    if categorical:
        ref = pd.DataFrame({name: ref_vals.astype(int).astype(str).values})
        cur = pd.DataFrame({name: cur_vals.astype(int).astype(str).values})
        dd = DataDefinition(numerical_columns=[], categorical_columns=[name])
    else:
        ref = pd.DataFrame({name: ref_vals.astype(float).values})
        cur = pd.DataFrame({name: cur_vals.astype(float).values})
        dd = DataDefinition(numerical_columns=[name], categorical_columns=[])
    res = Report([ValueDrift(column=name, method="jensenshannon")]).run(
        reference_data=Dataset.from_pandas(ref, data_definition=dd),
        current_data=Dataset.from_pandas(cur, data_definition=dd))
    return float(res.dict()["metrics"][0]["value"])


def main():
    MONITORING_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    mlflow.set_experiment(EXPERIMENT_NAME)

    train = pd.read_parquet(FEATURES_DIR / "train.parquet")
    val_ref = pd.read_parquet(FEATURES_DIR / "validation_predictions.parquet")
    metrics = json.loads((MODELS_DIR / "metrics.json").read_text())
    baseline_recall = next(t[RECALL_KEY] for t in metrics["test_tiers"] if t["source"] == "model")
    baseline_ap = next(w["average_precision"] for w in metrics["test_windows"]
                       if w["source"] == "model" and w["window_days"] == 7)
    train_rate = float(train[TARGETS[7]].mean())

    history = pd.read_parquet(SCORING_DIR / "tier_history.parquet")
    history = history.rename(columns={"model": "tier"})[["machine_id", "observation_date", "tier"]]
    repairs = load_repairs()

    cat_cols = [c for c in CATEGORICAL_FEATURES if c in ALL_FEATURES]
    log.info(f"References: train {len(train):,} rows | test 7-day AP {baseline_ap:.3f} | "
             f"train 7-day positive rate {train_rate:.3f}")

    rows = []
    for label, name, start, end in PERIODS:
        preds = pd.read_parquet(SCORING_DIR / f"predictions_{label}.parquet")
        known = preds[preds[TARGETS[7]].notna()]

        # 1. Performance: 7-day average precision on the rows whose outcome is known
        y7 = known[TARGETS[7]].astype(int)
        ap = float(average_precision_score(y7, known[PROB_COLS[7]]))
        auc = float(roc_auc_score(y7, known[PROB_COLS[7]]))
        perf_degraded = ap < baseline_ap - AP_TOLERANCE
        # Tier recall on the failures opened in the period, recorded for reference.
        ev = event_metrics(history, repairs, start, end, "model", label)
        recall = ev[RECALL_KEY]

        # 2. Target drift (7-day positive rate vs training)
        period_rate = float(known[TARGETS[7]].mean())
        target_score = one_col_drift(train[TARGETS[7]], known[TARGETS[7]], "target_failure_7d", categorical=True)
        target_drift = target_score >= DRIFT_THRESHOLD

        # 3. Prediction drift (7-day probability vs validation reference)
        pred_score = one_col_drift(val_ref[PROB_COLS[7]], preds[PROB_COLS[7]], "prob_failure_7d")
        pred_drift = pred_score >= DRIFT_THRESHOLD

        # 4. Feature drift
        ftable, fres = js_drift(train, preds, ALL_FEATURES, cat_cols)
        ftable.to_csv(MONITORING_DIR / f"feature_drift_{label}.csv", index=False)
        try:
            fres.save_html(str(MONITORING_DIR / f"drift_report_{label}.html"))
        except Exception as e:
            log.info(f"  [{label}] HTML save skipped: {e}")
        n_drifted = int(ftable["drift_detected"].sum())

        primary   = perf_degraded or target_drift
        secondary = pred_drift or (n_drifted > MAX_DRIFTED_FEATURES)
        status = "RETRAIN" if primary else "INVESTIGATE" if secondary else "HEALTHY"

        log.info(f"[{label}] 7-day AP {ap:.3f} (test {baseline_ap:.3f}) | recall {recall:.3f} on {ev['failures']} failures | "
                 f"7-day rate {period_rate:.3f} (train {train_rate:.3f}), JS {target_score:.3f} | "
                 f"pred JS {pred_score:.3f} | feat drifted {n_drifted}/{len(ALL_FEATURES)} | {status}")

        row = {"period_label": label, "period_name": name, "n_scored": len(preds),
               "n_known_7d": len(known),
               "ap_7d": round(ap, 4), "baseline_ap_7d": round(baseline_ap, 4), "roc_auc_7d": round(auc, 4),
               "failures": ev["failures"], "tier_recall": round(recall, 4),
               "critical_recall_7d": round(ev["critical_within_7d_share"], 4),
               "baseline_tier_recall": round(baseline_recall, 4),
               "perf_degraded": perf_degraded,
               "positive_rate_7d": round(period_rate, 4), "train_positive_rate_7d": round(train_rate, 4),
               "target_drift_score": round(target_score, 4), "target_drift": target_drift,
               "prediction_drift_score": round(pred_score, 4), "prediction_drift": pred_drift,
               "n_features_drifted": n_drifted, "n_features": len(ALL_FEATURES),
               "primary_trigger": primary, "secondary_trigger": secondary, "status": status}
        rows.append(row)

        with mlflow.start_run(run_name=f"monitoring_{label}"):
            mlflow.set_tags({"run_type": "monitoring", "period": label, "status": status})
            mlflow.log_metrics({k: float(v) for k, v in row.items()
                                if isinstance(v, (int, float, bool))})

    out = pd.DataFrame(rows)
    out.to_csv(MONITORING_DIR / "period_monitoring.csv", index=False)

    # Two-consecutive-period rule for the standing recommendation.
    def consecutive(flag):
        f = out[flag].tolist()
        return any(f[i] and f[i + 1] for i in range(len(f) - 1))

    if consecutive("primary_trigger"):
        recommendation = "RETRAIN"
    elif consecutive("secondary_trigger"):
        recommendation = "INVESTIGATE"
    else:
        recommendation = "HEALTHY"
    summary = {"recommendation": recommendation,
               "periods": out["status"].tolist(),
               "latest_status": rows[-1]["status"]}
    (MONITORING_DIR / "monitoring_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log.info("\n" + out[["period_label", "ap_7d", "tier_recall", "positive_rate_7d", "target_drift_score",
                         "prediction_drift_score", "n_features_drifted", "status"]].to_string(index=False))
    log.info(f"Standing recommendation (two-consecutive rule): {recommendation}")


if __name__ == "__main__":
    main()
