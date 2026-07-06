"""
health.py
The machine health indicator: the model object, the tier rule, the two
baselines and the evaluation shared by training, scoring and monitoring.

Two calibrated classifiers, one per window (an unplanned repair opening in the
CMMS within 7 and within 21 days), each with one fixed probability threshold.
The tier is CRITICAL when the 7-day probability is at or above its threshold,
ELEVATED when the 21-day probability is, otherwise OK. Where the 7-day
probability is above the 21-day one, the same rule takes the higher tier.
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shap
from sklearn.base import BaseEstimator
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             precision_score, recall_score, roc_auc_score)

from features import ALL_FEATURES, PM_INTERVAL_DAYS, TARGETS, WINDOWS, engineer_features

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH   = REPO_ROOT / "data_source" / "oee_predmaint.duckdb"
RAW_CMMS  = REPO_ROOT / "data_source" / "raw" / "cmms" / "maintenance_records.csv"

# End of the training window: the reference for the rules baseline's alarm level.
TRAIN_END = "2024-12-31"

TIERS      = ["CRITICAL", "ELEVATED", "OK"]
TIER_RANK  = {"CRITICAL": 2, "ELEVATED": 1, "OK": 0}
WINDOW_TIER = {7: "CRITICAL", 21: "ELEVATED"}
BASELINES  = ["calendar_pm", "rules", "interval"]
PROB_COLS  = {n: f"prob_failure_{n}d" for n in WINDOWS}

# Baseline constants.
PM_DUE_SOON_DAYS       = 7     # calendar PM: due within this many days
RULE_ALARM_MULTIPLE    = 1.5   # rules: 7-day alarm count above this multiple of the machine's level
RULE_PM_OVERDUE_DAYS   = 14    # rules: PM more than this many days overdue
RULE_ELEVATED_LOOKBACK = 21    # rules: ELEVATED when a condition held in this many days
INTERVAL_CRITICAL_DAYS  = 7     # interval: within this many days of the machine's median, or past it
INTERVAL_ELEVATED_DAYS  = 21    # interval: within this many days of the machine's median


class HealthIndicator(BaseEstimator):
    """The window pipelines with their isotonic calibrators and thresholds."""

    def __init__(self, pipelines=None, calibrators=None, thresholds=None, model_type=None):
        self.pipelines = pipelines
        self.calibrators = calibrators
        self.thresholds = thresholds
        self.model_type = model_type

    def predict_proba_windows(self, X: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for n in WINDOWS:
            raw = self.pipelines[n].predict_proba(X[ALL_FEATURES])[:, 1]
            out[PROB_COLS[n]] = self.calibrators[n].predict(raw)
        return pd.DataFrame(out, index=X.index)

    def tiers(self, probs: pd.DataFrame) -> np.ndarray:
        tier = np.full(len(probs), "OK", dtype=object)
        for n in sorted(WINDOWS, reverse=True):
            tier[probs[PROB_COLS[n]].values >= self.thresholds[n]] = WINDOW_TIER[n]
        return tier

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.tiers(self.predict_proba_windows(X))


def out_of_order_share(probs: pd.DataFrame) -> float:
    """Share of rows where the 7-day probability is above the 21-day one."""
    return float((probs[PROB_COLS[7]].values > probs[PROB_COLS[21]].values).mean())


# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════
def load_mart() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("select * from mart_ml__health_features "
                     "order by observation_date, machine_id, shift").df()
    con.close()
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    # Kept beside the imputed features for the calendar PM and interval baselines.
    df["days_since_last_pm_recorded"] = df["days_since_last_pm"]
    df["days_since_last_repair_recorded"] = df["days_since_last_unplanned_failure"]
    return engineer_features(df)


def load_repairs() -> pd.DataFrame:
    """Unplanned repairs from the CMMS: machine, the date opened and the date closed."""
    df = pd.read_csv(RAW_CMMS, parse_dates=["work_order_open_date", "work_order_close_date"])
    df = df[df["maintenance_type"] == "UNPLANNED_REPAIR"]
    out = pd.DataFrame({
        "machine_id":  df["machine_id"].values,
        "opened_date": df["work_order_open_date"].dt.normalize().values,
        "closed_date": df["work_order_close_date"].dt.normalize().values,
    })
    return out.sort_values(["machine_id", "opened_date"]).reset_index(drop=True)


def machine_days(rows: pd.DataFrame, tier_col: str = "tier") -> pd.DataFrame:
    """One row per machine and day: the higher tier of the day's shift rows."""
    d = rows[["machine_id", "observation_date", tier_col]].copy()
    d["rank"] = d[tier_col].map(TIER_RANK)
    d = d.groupby(["machine_id", "observation_date"], as_index=False)["rank"].max()
    inv = {v: k for k, v in TIER_RANK.items()}
    d["tier"] = d["rank"].map(inv)
    return d[["machine_id", "observation_date", "tier"]]


# ══════════════════════════════════════════════════════════════════════════════
# BASELINES
# ══════════════════════════════════════════════════════════════════════════════
def calendar_pm_tier(mart: pd.DataFrame) -> np.ndarray:
    """CRITICAL when PM is due within 7 days or overdue, otherwise OK."""
    since = pd.to_numeric(mart["days_since_last_pm_recorded"], errors="coerce").astype(float).fillna(-1.0).values
    due_soon = since >= (PM_INTERVAL_DAYS - PM_DUE_SOON_DAYS)   # false before the first PM on record
    return np.where(due_soon, "CRITICAL", "OK")


def rules_tier(mart: pd.DataFrame, train_end: str) -> np.ndarray:
    """CRITICAL when the 7-day alarm count is above 1.5 times the machine's
    training mean or PM is more than 14 days overdue; ELEVATED when either held
    in the last 21 days; otherwise OK."""
    days = (mart.groupby(["machine_id", "observation_date"], as_index=False)
            .agg(alarms=("rolling_7d_alarm_count", "max"),
                 overdue=("days_overdue_for_pm", "max")))
    level = (days[days["observation_date"] <= train_end]
             .groupby("machine_id")["alarms"].mean().rename("alarm_level"))
    days = days.join(level, on="machine_id")

    days["critical"] = ((days["alarms"] > RULE_ALARM_MULTIPLE * days["alarm_level"])
                        | (days["overdue"] > RULE_PM_OVERDUE_DAYS))
    tiers = []
    for _, g in days.groupby("machine_id", sort=False):
        g = g.sort_values("observation_date")
        s = pd.Series(g["critical"].astype(int).values, index=g["observation_date"])
        held = (s.rolling(f"{RULE_ELEVATED_LOOKBACK}D", closed="left").sum().fillna(0) > 0).values
        t = np.where(g["critical"].values, "CRITICAL", np.where(held, "ELEVATED", "OK"))
        tiers.append(pd.DataFrame({"machine_id": g["machine_id"].values,
                                   "observation_date": g["observation_date"].values, "rules": t}))
    lookup = pd.concat(tiers).set_index(["machine_id", "observation_date"])["rules"]
    return lookup.reindex(pd.MultiIndex.from_arrays(
        [mart["machine_id"], mart["observation_date"]])).values


def interval_baseline(mart: pd.DataFrame, repairs: pd.DataFrame, train_end: str) -> tuple:
    """The interval baseline. For each machine, the median days between unplanned
    repairs in the training window. CRITICAL when days since the last repair are
    within 7 days of that median or past it; ELEVATED when within 21 days;
    otherwise OK. Returns the tier and the score (days since the last repair
    divided by the machine's median; 0 before the first repair on record)."""
    tr = repairs[repairs["opened_date"] <= train_end].drop_duplicates(["machine_id", "opened_date"])
    median = (tr.sort_values(["machine_id", "opened_date"]).groupby("machine_id")["opened_date"]
              .apply(lambda s: s.diff().dt.days.median()))
    med = mart["machine_id"].map(median).astype(float).values
    since = pd.to_numeric(mart["days_since_last_repair_recorded"], errors="coerce").astype(float).values
    known = ~np.isnan(since)
    tier = np.where(known & (since >= med - INTERVAL_CRITICAL_DAYS), "CRITICAL",
                    np.where(known & (since >= med - INTERVAL_ELEVATED_DAYS), "ELEVATED", "OK"))
    score = np.where(known, since / med, 0.0)
    return tier, score


def tier_flags(tier: np.ndarray) -> dict:
    """The window flags a tier implies: CRITICAL for 7 days, CRITICAL or ELEVATED
    for 21."""
    rank = pd.Series(tier).map(TIER_RANK).values
    return {7: (rank >= 2).astype(int), 21: (rank >= 1).astype(int)}


def add_tiers(df: pd.DataFrame, indicator, repairs: pd.DataFrame) -> pd.DataFrame:
    """Score every row and attach the model tier and the baseline tiers."""
    df = df.copy()
    probs = indicator.predict_proba_windows(df)
    for c in probs.columns:
        df[c] = probs[c].values
    df["tier_model"]       = indicator.tiers(probs)
    df["tier_calendar_pm"] = calendar_pm_tier(df)
    df["tier_rules"]       = rules_tier(df, TRAIN_END)
    df["tier_interval"], df["score_interval"] = interval_baseline(df, repairs, TRAIN_END)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# EXPLANATION
# ══════════════════════════════════════════════════════════════════════════════
def _transformed(pipeline, X: pd.DataFrame) -> pd.DataFrame:
    prep = pipeline.named_steps["prep"]
    Xt = np.asarray(prep.transform(X), dtype="float64")
    names = [n.split("__")[-1] for n in prep.get_feature_names_out()]
    return pd.DataFrame(Xt, columns=names, index=X.index)


def shap_values(pipeline, X: pd.DataFrame) -> tuple:
    """SHAP values toward the positive class (a repair within the window)."""
    model = pipeline.named_steps["model"]
    Xt = _transformed(pipeline, X)
    if model.__class__.__name__ in ("XGBClassifier", "RandomForestClassifier"):
        vals = shap.TreeExplainer(model).shap_values(Xt)
        if isinstance(vals, list):
            vals = vals[1]
        vals = np.asarray(vals)
        if vals.ndim == 3:
            vals = vals[:, :, 1]
    else:
        vals = np.asarray(shap.LinearExplainer(model, Xt).shap_values(Xt))
    return vals, list(Xt.columns)


# ══════════════════════════════════════════════════════════════════════════════
# EVALUATION
# ══════════════════════════════════════════════════════════════════════════════
def window_metrics(rows: pd.DataFrame, source: str, split: str, thresholds: dict | None = None) -> list:
    """Per window, on rows whose outcome is known: ROC-AUC, average precision,
    precision and recall at the threshold, and the Brier score. For the model
    the score is the calibrated probability. A baseline has no probability, so
    the Brier score does not apply; its ROC-AUC and average precision use the
    flag its tier implies, except the interval baseline, which is scored on days
    since the last repair divided by the machine's median."""
    out = []
    flags = tier_flags(rows[f"tier_{source}"].values) if source != "model" else None
    for n in WINDOWS:
        known = rows[TARGETS[n]].notna().values
        y = rows.loc[known, TARGETS[n]].astype(int).values
        if source == "model":
            score = rows.loc[known, PROB_COLS[n]].values
            flag = (score >= thresholds[n]).astype(int)
            brier = float(brier_score_loss(y, score))
        else:
            flag = flags[n][known]
            score = (rows.loc[known, "score_interval"].values if source == "interval"
                     else flag.astype(float))
            brier = None
        both = len(np.unique(y)) > 1
        out.append({
            "split": split, "source": source, "window_days": n,
            "rows": int(known.sum()), "positive_rate": float(y.mean()),
            "roc_auc": float(roc_auc_score(y, score)) if both else None,
            "average_precision": float(average_precision_score(y, score)) if both else None,
            "threshold": float(thresholds[n]) if source == "model" else None,
            "precision": float(precision_score(y, flag, zero_division=0)),
            "recall": float(recall_score(y, flag, zero_division=0)),
            "flagged_share": float(flag.mean()),
            "brier": brier,
        })
    return out


def event_metrics(history: pd.DataFrame, repairs: pd.DataFrame, start: str, end: str,
                  source: str, split: str) -> dict:
    """For the failures opened in the period: the share that had CRITICAL on at
    least one of the 7 days before and CRITICAL or ELEVATED on at least one of the
    21 days before, with median lead days from the first such day. `history` is
    one row per machine and day with the tier, and may run before the period."""
    ev = repairs[(repairs["opened_date"] >= start) & (repairs["opened_date"] <= end)]
    ev = ev.drop_duplicates(["machine_id", "opened_date"])
    by_machine = {m: g.set_index("observation_date")["tier"] for m, g in history.groupby("machine_id")}
    hit7, hit21, lead7, lead21 = [], [], [], []
    for m, f in zip(ev["machine_id"], ev["opened_date"]):
        s = by_machine[m]
        w7  = s[(s.index >= f - pd.Timedelta(days=7))  & (s.index < f)]
        w21 = s[(s.index >= f - pd.Timedelta(days=21)) & (s.index < f)]
        c7  = w7[w7 == "CRITICAL"]
        c21 = w21[w21.isin(["CRITICAL", "ELEVATED"])]
        hit7.append(len(c7) > 0); hit21.append(len(c21) > 0)
        if len(c7):  lead7.append((f - c7.index.min()).days)
        if len(c21): lead21.append((f - c21.index.min()).days)
    n = len(ev)
    return {
        "split": split, "source": source, "failures": n,
        "critical_within_7d_share": float(np.mean(hit7)) if n else None,
        "critical_median_lead_days": float(np.median(lead7)) if lead7 else None,
        "critical_or_elevated_within_21d_share": float(np.mean(hit21)) if n else None,
        "critical_or_elevated_median_lead_days": float(np.median(lead21)) if lead21 else None,
    }


def tier_days_by_month(history: pd.DataFrame, start: str, end: str, source: str) -> pd.DataFrame:
    h = history[(history["observation_date"] >= start) & (history["observation_date"] <= end)].copy()
    h["month"] = h["observation_date"].dt.strftime("%Y-%m")
    t = (h.groupby(["month", "tier"]).size().unstack(fill_value=0)
         .reindex(columns=TIERS, fill_value=0).reset_index())
    t.insert(0, "source", source)
    return t


def evaluate(rows: pd.DataFrame, repairs: pd.DataFrame, thresholds: dict,
             start: str, end: str, split: str):
    """The evaluation of the model and the baselines on one period. `rows` holds
    every scored row (all dates) with the probabilities and the tier
    columns; the window metrics use the period's rows and the event metrics may
    look back before it."""
    period = rows[(rows["observation_date"] >= start) & (rows["observation_date"] <= end)]
    windows, events, monthly = [], [], []
    for source in ["model"] + BASELINES:
        windows += window_metrics(period, source, split, thresholds)
        hist = machine_days(rows, f"tier_{source}")
        events.append(event_metrics(hist, repairs, start, end, source, split))
        m = tier_days_by_month(hist, start, end, source); m.insert(0, "split", split)
        monthly.append(m)
    return pd.DataFrame(windows), pd.DataFrame(events), pd.concat(monthly, ignore_index=True)
