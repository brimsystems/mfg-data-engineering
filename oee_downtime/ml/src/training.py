"""
training.py
Trains the machine health indicator.

Two binary classifiers, one per window: an unplanned repair opening in the
CMMS within 7 and within 21 days. Each window runs a three-way
bake-off (regularized logistic regression, random forest, XGBoost), tuned with
Optuna against validation average precision. The candidate with the highest
mean validation average precision across the two windows is kept; its two
window models are calibrated (isotonic, fitted on validation), each given one
fixed probability threshold chosen on validation (the threshold with the highest
F1), and registered in MLflow as one version under the "production" alias. The
model and the baselines are evaluated once on the held-out test set. Model,
metrics and chart data are written to ml/models/ for the report generators.
"""
import json
import logging
import warnings
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import optuna
import mlflow
import mlflow.sklearn
from mlflow import MlflowClient
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OrdinalEncoder, OneHotEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (average_precision_score, precision_recall_curve,
                             roc_auc_score)
from sklearn.model_selection import learning_curve as sk_learning_curve
from sklearn.base import clone
from xgboost import XGBClassifier

import sys
sys.path.insert(0, str(Path(__file__).parent))
from features import (
    ALL_FEATURES, CATEGORICAL_FEATURES, NUMERICAL_FEATURES,
    INTERACTION_FEATURES, SENSOR_FEATURES, TARGETS, WINDOWS, ID_COL,
)
from health import (
    HealthIndicator, PROB_COLS, TRAIN_END, add_tiers, evaluate, load_mart,
    load_repairs, out_of_order_share, shap_values,
)

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
REPO_ROOT     = Path(__file__).resolve().parents[2]
FEATURES_DIR  = REPO_ROOT / "ml" / "data" / "features"
MODELS_DIR    = REPO_ROOT / "ml" / "models"
MLRUNS_DIR    = REPO_ROOT / "ml" / "mlruns"

# Time-based split (never shuffled). Train Jan 2023-Dec 2024, Validate
# Jan-Aug 2025, Test Sep-Dec 2025; TRAIN_END is declared in health.py. The
# Jan-Mar 2026 scoring window is held out
# entirely (handled by scoring.py) and must not leak into any split here.
VAL_END    = "2025-08-31"
TEST_START = "2025-09-01"
TEST_END   = "2025-12-31"

MLFLOW_TRACKING = f"sqlite:///{(MLRUNS_DIR / 'mlflow.db').as_posix()}"
EXPERIMENT_NAME = "c02_machine_health_indicator"
MODEL_NAME      = "machine_health_indicator"
PROD_ALIAS      = "production"
N_TRIALS        = 100
RANDOM_SEED     = 42

# The sensor layer: the nine sensor features and the anomaly flag built on them.
SENSOR_LAYER = SENSOR_FEATURES + ["is_sensor_anomaly"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════
def prepare_features() -> pd.DataFrame:
    """Write the three splits and return the full mart with the baseline tiers."""
    log.info("Preparing feature splits from mart...")
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    df = load_mart()
    log.info(f"  Loaded {len(df):,} observations from mart")

    train_mask = df["observation_date"] <= TRAIN_END
    val_mask   = (df["observation_date"] > TRAIN_END) & (df["observation_date"] <= VAL_END)
    test_mask  = (df["observation_date"] > VAL_END) & (df["observation_date"] <= TEST_END)

    export_cols = [ID_COL, "machine_id", "observation_date"] + ALL_FEATURES + list(TARGETS.values())
    export_cols = list(dict.fromkeys(export_cols))
    for label, mask in [("train", train_mask), ("validation", val_mask), ("test", test_mask)]:
        split = df[mask][export_cols]
        split.to_parquet(FEATURES_DIR / f"{label}.parquet", index=False)
        rates = "  ".join(f"{n}d {split[TARGETS[n]].mean():.3f}" for n in WINDOWS)
        log.info(f"  {label:<12} {len(split):>7,} rows  positive rate: {rates}")
    return df


def build_preprocessors(X: pd.DataFrame) -> tuple:
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in X.columns]
    num_cols = [c for c in X.columns if c not in cat_cols]

    tree_prep = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cat_cols),
        ("num", "passthrough", num_cols),
    ], remainder="drop")

    linear_prep = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat_cols),
        ("num", StandardScaler(), num_cols),
    ], remainder="drop")

    return tree_prep, linear_prep


# ══════════════════════════════════════════════════════════════════════════════
# HYPERPARAMETER SEARCH (objective = validation average precision, maximized)
# ══════════════════════════════════════════════════════════════════════════════
def _study():
    return optuna.create_study(direction="maximize",
                               sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED))


def _ap(pipe, X_val, y_val) -> float:
    return float(average_precision_score(y_val, pipe.predict_proba(X_val)[:, 1]))


def tune_linear(X_train, y_train, X_val, y_val, linear_prep):
    def make(alpha):
        # alpha is the regularization strength, as in the ridge it replaces.
        return Pipeline([("prep", clone(linear_prep)),
                         ("model", LogisticRegression(C=1.0 / alpha, max_iter=2000,
                                                      random_state=RANDOM_SEED))])

    def objective(trial):
        alpha = trial.suggest_float("alpha", 1e-2, 100.0, log=True)
        return _ap(make(alpha).fit(X_train, y_train), X_val, y_val)

    study = _study(); study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    best = study.best_params
    return make(best["alpha"]).fit(X_train, y_train), best


def tune_random_forest(X_train, y_train, X_val, y_val, tree_prep):
    def make(params):
        return Pipeline([("prep", clone(tree_prep)),
                         ("model", RandomForestClassifier(**params, random_state=RANDOM_SEED, n_jobs=-1))])

    def fit(params):
        # Fitted on every core, scored on one: the trees' votes are then summed
        # in a fixed order, so the same model gives the same scores on every run.
        pipe = make(params).fit(X_train, y_train)
        pipe.named_steps["model"].set_params(n_jobs=1)
        return pipe

    def objective(trial):
        params = {
            "n_estimators":     trial.suggest_int("n_estimators", 200, 600),
            "max_depth":        trial.suggest_int("max_depth", 4, 20),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 40),
            "max_features":     trial.suggest_categorical("max_features", ["sqrt", "log2", 0.5]),
        }
        return _ap(fit(params), X_val, y_val)

    study = _study(); study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    best = study.best_params
    return fit(best), best


def tune_xgboost(X_train, y_train, X_val, y_val, tree_prep):
    prep = clone(tree_prep).fit(X_train)
    X_tr, X_va = prep.transform(X_train), prep.transform(X_val)

    def make(params):
        return XGBClassifier(**params, n_estimators=1000, objective="binary:logistic",
                             eval_metric="aucpr", early_stopping_rounds=30,
                             random_state=RANDOM_SEED, verbosity=0)

    def objective(trial):
        params = {
            "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "max_depth":        trial.suggest_int("max_depth", 3, 10),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 12),
        }
        model = make(params).fit(X_tr, y_train, eval_set=[(X_va, y_val)], verbose=False)
        return float(average_precision_score(y_val, model.predict_proba(X_va)[:, 1]))

    study = _study(); study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    best = study.best_params
    model = make(best).fit(X_tr, y_train, eval_set=[(X_va, y_val)], verbose=False)
    return Pipeline([("prep", prep), ("model", model)]), best


TUNERS = {"logistic_regression": tune_linear, "random_forest": tune_random_forest, "xgboost": tune_xgboost}


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATION AND THRESHOLD
# ══════════════════════════════════════════════════════════════════════════════
def calibrate(pipe, X_val, y_val) -> IsotonicRegression:
    raw = pipe.predict_proba(X_val)[:, 1]
    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, y_val)


def choose_threshold(y_val, prob_val) -> float:
    """The calibrated probability with the highest F1 on validation; the lowest
    such value where several tie."""
    precision, recall, thresholds = precision_recall_curve(y_val, prob_val)
    f1 = 2 * precision[:-1] * recall[:-1] / np.clip(precision[:-1] + recall[:-1], 1e-12, None)
    return float(thresholds[int(np.argmax(f1))])


# ══════════════════════════════════════════════════════════════════════════════
# ARTIFACTS (data only; the report generators draw the brand-styled charts)
# ══════════════════════════════════════════════════════════════════════════════
def model_importance(pipeline) -> pd.Series:
    """The fitted model's own importance: gain for the tree models, absolute
    standardized coefficient for the logistic regression."""
    model = pipeline.named_steps["model"]
    names = [n.split("__")[-1] for n in pipeline.named_steps["prep"].get_feature_names_out()]
    vals = np.abs(model.coef_[0]) if hasattr(model, "coef_") else model.feature_importances_
    return pd.Series(np.asarray(vals, dtype=float), index=names)


def importance_table(indicator: HealthIndicator, X_sample: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for n in WINDOWS:
        vals, names = shap_values(indicator.pipelines[n], X_sample)
        imp = model_importance(indicator.pipelines[n])
        frames.append(pd.DataFrame({
            "window_days": n, "feature": names,
            "mean_abs_shap": np.abs(vals).mean(axis=0),
            "model_importance": imp.reindex(names).values,
        }))
    t = pd.concat(frames, ignore_index=True)
    for col in ("mean_abs_shap", "model_importance"):
        t[col.replace("mean_abs_", "") + "_share"] = t[col] / t.groupby("window_days")[col].transform("sum")
    t["sensor_feature"] = t["feature"].isin(SENSOR_LAYER)
    return t.sort_values(["window_days", "mean_abs_shap"], ascending=[True, False]).reset_index(drop=True)


def learning_curve_data(pipeline, X_train, y_train) -> pd.DataFrame:
    lc_pipe = clone(pipeline)
    step = lc_pipe.named_steps["model"]
    if isinstance(step, XGBClassifier):
        step.set_params(early_stopping_rounds=None, n_estimators=300)
    sizes, train_sc, val_sc = sk_learning_curve(
        lc_pipe, X_train, y_train, cv=3, scoring="average_precision",
        train_sizes=np.linspace(0.15, 1.0, 6), n_jobs=1)
    return pd.DataFrame({
        "train_size": sizes,
        "train_average_precision": train_sc.mean(axis=1),
        "val_average_precision":   val_sc.mean(axis=1),
    })


def curves(test: pd.DataFrame, thresholds: dict) -> tuple:
    calib, pr = [], []
    for n in WINDOWS:
        y, p = test[TARGETS[n]].astype(int).values, test[PROB_COLS[n]].values
        bins = pd.qcut(p, 10, duplicates="drop")
        g = pd.DataFrame({"p": p, "y": y}).groupby(bins, observed=True)
        calib.append(pd.DataFrame({"window_days": n, "mean_predicted": g["p"].mean().values,
                                   "observed_rate": g["y"].mean().values, "count": g.size().values}))
        precision, recall, thr = precision_recall_curve(y, p)
        pr.append(pd.DataFrame({"window_days": n, "threshold": np.append(thr, np.nan),
                                "precision": precision, "recall": recall}))
    return pd.concat(calib, ignore_index=True), pd.concat(pr, ignore_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    MLRUNS_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    mlflow.set_experiment(EXPERIMENT_NAME)

    mart = prepare_features()
    repairs = load_repairs()
    train = mart[mart["observation_date"] <= TRAIN_END]
    val   = mart[(mart["observation_date"] > TRAIN_END) & (mart["observation_date"] <= VAL_END)]
    test  = mart[(mart["observation_date"] > VAL_END) & (mart["observation_date"] <= TEST_END)]
    X_train, X_val, X_test = train[ALL_FEATURES], val[ALL_FEATURES], test[ALL_FEATURES]
    log.info(f"Train {len(X_train):,} | Val {len(X_val):,} | Test {len(X_test):,}")

    tree_prep, linear_prep = build_preprocessors(X_train)
    run_name = f"training_{datetime.now():%Y%m%d_%H%M}"

    with mlflow.start_run(run_name=run_name) as parent:
        mlflow.set_tags({"targets": ",".join(TARGETS.values()), "train_rows": len(X_train),
                         "val_rows": len(X_val), "test_rows": len(X_test),
                         "n_optuna_trials": N_TRIALS, "random_seed": RANDOM_SEED})
        results = []
        for name, tuner in TUNERS.items():
            log.info(f"Training {name}...")
            prep = linear_prep if name == "logistic_regression" else tree_prep
            pipes, params, val_m = {}, {}, {}
            for n in WINDOWS:
                y_tr, y_va = train[TARGETS[n]].astype(int), val[TARGETS[n]].astype(int)
                pipes[n], params[n] = tuner(X_train, y_tr, X_val, y_va, prep)
                p = pipes[n].predict_proba(X_val)[:, 1]
                val_m[f"val_ap_{n}d"]  = float(average_precision_score(y_va, p))
                val_m[f"val_auc_{n}d"] = float(roc_auc_score(y_va, p))
                log.info(f"  {name} {n}d best {params[n]}  val_ap={val_m[f'val_ap_{n}d']:.4f}")
            val_m["val_ap_mean"] = float(np.mean([val_m[f"val_ap_{n}d"] for n in WINDOWS]))
            with mlflow.start_run(run_name=name, nested=True):
                for n in WINDOWS:
                    mlflow.log_params({f"{name}__{n}d__{k}": v for k, v in params[n].items()})
                mlflow.log_metrics(val_m)
                mlflow.set_tag("model_type", name)
            results.append({"model_type": name, "pipelines": pipes, "params": params, **val_m})

        comparison = pd.DataFrame([{
            "model_type": r["model_type"],
            **{f"val_ap_{n}d": round(r[f"val_ap_{n}d"], 4) for n in WINDOWS},
            **{f"val_auc_{n}d": round(r[f"val_auc_{n}d"], 4) for n in WINDOWS},
            "val_ap_mean": round(r["val_ap_mean"], 4),
        } for r in results]).sort_values("val_ap_mean", ascending=False).reset_index(drop=True)
        log.info("\nModel comparison (validation, higher average precision is better):\n"
                 + comparison.to_string(index=False))

        best = max(results, key=lambda r: r["val_ap_mean"])
        best_type = best["model_type"]
        mlflow.set_tag("best_model_type", best_type)
        log.info(f"\nBest model: {best_type} (mean val_ap={best['val_ap_mean']:.4f})")

        # Calibration and thresholds, both on validation.
        calibrators, thresholds = {}, {}
        for n in WINDOWS:
            y_va = val[TARGETS[n]].astype(int).values
            calibrators[n] = calibrate(best["pipelines"][n], X_val, y_va)
            prob_va = calibrators[n].predict(best["pipelines"][n].predict_proba(X_val)[:, 1])
            thresholds[n] = choose_threshold(y_va, prob_va)
            log.info(f"  {n}d threshold {thresholds[n]:.4f}")
        indicator = HealthIndicator(best["pipelines"], calibrators, thresholds, best_type)

        # Every row scored once: the tier history the evaluation reads, and the
        # validation probabilities that monitoring uses as its reference.
        scored = add_tiers(mart, indicator, repairs)
        scored_val = scored[(scored["observation_date"] > TRAIN_END) & (scored["observation_date"] <= VAL_END)]
        scored_val[list(PROB_COLS.values()) + ["tier_model"] + list(TARGETS.values())].to_parquet(
            FEATURES_DIR / "validation_predictions.parquet", index=False)

        # Held-out test evaluation (touched once): the model and the baselines.
        win, events, monthly = evaluate(scored, repairs, thresholds, TEST_START, TEST_END, "test")
        scored_test = scored[(scored["observation_date"] > VAL_END) & (scored["observation_date"] <= TEST_END)]
        out_of_order = out_of_order_share(scored_test)
        log.info("\nTest, by window:\n" + win.round(4).to_string(index=False))
        log.info("\nTest, tiers against failures:\n" + events.round(3).to_string(index=False))
        log.info(f"Window probabilities out of order on {out_of_order:.2%} of test rows")
        for _, r in win[win["source"] == "model"].iterrows():
            n = int(r["window_days"])
            mlflow.log_metrics({f"test_auc_{n}d": r["roc_auc"], f"test_ap_{n}d": r["average_precision"],
                                f"test_precision_{n}d": r["precision"], f"test_recall_{n}d": r["recall"],
                                f"test_brier_{n}d": r["brier"]})

        # ── Chart data for the reports ──────────────────────────────────────
        win.to_csv(MODELS_DIR / "evaluation_windows_test.csv", index=False)
        events.to_csv(MODELS_DIR / "evaluation_tiers_test.csv", index=False)
        monthly.to_csv(MODELS_DIR / "tier_days_test.csv", index=False)

        imp = importance_table(indicator, X_val)
        imp.to_csv(MODELS_DIR / "shap_importance.csv", index=False)
        sensor_share = {n: {"shap": float(imp[(imp["window_days"] == n) & imp["sensor_feature"]]["shap_share"].sum()),
                            "model_importance": float(imp[(imp["window_days"] == n) & imp["sensor_feature"]]["model_importance_share"].sum())}
                        for n in WINDOWS}
        log.info(f"Sensor features' share of importance: {json.dumps(sensor_share)}")

        calib, pr = curves(scored_test, thresholds)
        calib.to_csv(MODELS_DIR / "calibration_test.csv", index=False)
        pr.to_csv(MODELS_DIR / "precision_recall_test.csv", index=False)

        try:
            learning_curve_data(best["pipelines"][7], X_train, train[TARGETS[7]].astype(int)).to_csv(
                MODELS_DIR / "learning_curve.csv", index=False)
        except Exception as e:
            log.info(f"  learning curve skipped: {e}")

        comparison.to_csv(MODELS_DIR / "model_comparison.csv", index=False)
        mlflow.log_artifact(str(MODELS_DIR / "model_comparison.csv"))

        # ── Register the two window models as one version ── ─────────────────
        info = mlflow.sklearn.log_model(indicator, name="machine_health_indicator",
                                        serialization_format="cloudpickle")
        mv = mlflow.register_model(info.model_uri, MODEL_NAME)
        client = MlflowClient()
        client.set_registered_model_alias(MODEL_NAME, PROD_ALIAS, mv.version)
        m7 = win[(win["source"] == "model") & (win["window_days"] == 7)].iloc[0]
        client.update_model_version(MODEL_NAME, mv.version,
            description=(f"{best_type}, two windows (7 and 21 days). Mean val AP {best['val_ap_mean']:.3f}; "
                         f"7-day test AP {m7['average_precision']:.3f}, ROC-AUC {m7['roc_auc']:.3f}."))
        mlflow.set_tag("model_version", mv.version)

        # ── Persist model + metrics summary for scoring and reports ─────────
        joblib.dump(indicator, MODELS_DIR / "health_indicator.pkl")
        summary = {
            "model_name": MODEL_NAME,
            "best_model_type": best_type,
            "n_optuna_trials": N_TRIALS,
            "windows_days": WINDOWS,
            "targets": TARGETS,
            "selection": "highest mean validation average precision across the two windows",
            "calibration": "isotonic, fitted on validation",
            "threshold_rule": "calibrated probability with the highest F1 on validation",
            "thresholds": {str(n): thresholds[n] for n in WINDOWS},
            "feature_counts": {"categorical": len(CATEGORICAL_FEATURES),
                               "numerical": len(NUMERICAL_FEATURES),
                               "interaction": len(INTERACTION_FEATURES),
                               "total": len(ALL_FEATURES)},
            "split_sizes": {"train": len(X_train), "validation": len(X_val), "test": len(X_test)},
            "positive_rate": {s: {str(n): float(d[TARGETS[n]].mean()) for n in WINDOWS}
                              for s, d in (("train", train), ("validation", val), ("test", test))},
            "models": [{"model_type": r["model_type"],
                        "params": {str(n): r["params"][n] for n in WINDOWS},
                        **{k: round(v, 6) for k, v in r.items() if k.startswith("val_")}} for r in results],
            "test_windows": win.to_dict(orient="records"),
            "test_tiers": events.to_dict(orient="records"),
            "test_out_of_order_share": out_of_order,
            "sensor_importance_share": {str(n): v for n, v in sensor_share.items()},
        }
        (MODELS_DIR / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        log.info(f"Saved model + metrics to {MODELS_DIR}")
        log.info(f"Registered '{MODEL_NAME}' v{mv.version} @{PROD_ALIAS}")


if __name__ == "__main__":
    main()
