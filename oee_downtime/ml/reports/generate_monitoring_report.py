"""MLOps Monitoring Report for the machine health indicator -> docs/reports/monitoring_report.html
Status & Decision, Performance, Target Drift, Prediction Drift, Feature Drift,
Data Quality, Monitoring Log."""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

import sys
sys.path.insert(0, str(Path(__file__).parent))
import brand as B
from brand import DARK_BLUE, LIGHT_BLUE, ACCENT_RED, AMBER, GREEN, MED_GREY, LIGHT_GREY, BG_GREY, DARK_GREY
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features import CATEGORICAL_FEATURES, ALL_FEATURES

REPO    = Path(__file__).resolve().parents[2]
DB_PATH = REPO / "data_source" / "oee_predmaint.duckdb"
MODELS  = REPO / "ml" / "models"
FEATS   = REPO / "ml" / "data" / "features"
SCORING = REPO / "ml" / "data" / "scoring"
MON     = REPO / "ml" / "data" / "monitoring"
MLRUNS  = REPO / "ml" / "mlruns"
OUT     = REPO / "docs" / "reports" / "monitoring_report.html"
MLFLOW_TRACKING = f"sqlite:///{(MLRUNS / 'mlflow.db').as_posix()}"

DRIFT_THRESHOLD = 0.10
AP_TOL = 0.10
MODEL_NAME = "machine_health_indicator"
MAX_DRIFT_FEATS = 3
PERIOD_DATES = {"202601": ("2026-01-01", "2026-01-31"), "202602": ("2026-02-01", "2026-02-28"),
                "202603": ("2026-03-01", "2026-03-31")}
HEAT = LinearSegmentedColormap.from_list("d", [BG_GREY, MUTED := "#FFA3A3", ACCENT_RED])

m    = json.loads((MODELS / "metrics.json").read_text(encoding="utf-8"))
summ = json.loads((MON / "monitoring_summary.json").read_text(encoding="utf-8"))
pm   = pd.read_csv(MON / "period_monitoring.csv", dtype={"period_label": str})
names = pm["period_name"].tolist()
labels = pm["period_label"].tolist()
latest = pm.iloc[-1]
val_ref = pd.read_parquet(FEATS / "validation_predictions.parquet")
preds_by = {l: pd.read_parquet(SCORING / f"predictions_{l}.parquet") for l in labels}
drift_by = {l: pd.read_csv(MON / f"feature_drift_{l}.csv") for l in labels if (MON / f"feature_drift_{l}.csv").exists()}

STATUS = {"HEALTHY": (GREEN, "&#10003;", "NO ACTION REQUIRED"),
          "INVESTIGATE": (AMBER, "&#9680;", "INVESTIGATE"),
          "RETRAIN": (ACCENT_RED, "&#9888;", "RETRAIN RECOMMENDED")}
rec = summ["recommendation"]
rec_color, rec_icon, rec_label = STATUS.get(rec, (MED_GREY, "&bull;", rec))

# ── MLflow version history ──────────────────────────────────────────────────
version_rows = []
prod_ver = None
try:
    import mlflow
    from mlflow import MlflowClient
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    client = MlflowClient()
    prod_ver = client.get_model_version_by_alias(MODEL_NAME, "production").version
    for v in sorted(client.search_model_versions(f"name='{MODEL_NAME}'"), key=lambda x: int(x.version)):
        try:
            r = client.get_run(v.run_id)
            vap = r.data.metrics.get("test_ap_7d")
            mtype = r.data.tags.get("best_model_type", "-")
        except Exception:
            vap, mtype = None, "-"
        version_rows.append((v.version, mtype, vap))
except Exception:
    version_rows = []

# Registry timestamps reflect when the code was last run, which does not match
# the Q1 2026 analysis window, so the log shows the version, its type, its test
# score and its alias, and no registration date.

# ── Charts ──────────────────────────────────────────────────────────────────
def chart_ap_trend():
    fig, ax = B.make_fig(h=3.2)
    colors = [STATUS.get(s, (MED_GREY,))[0] for s in pm["status"]]
    base = pm["baseline_ap_7d"].iloc[0]
    bars = ax.bar(names, pm["ap_7d"], color=colors, width=0.5)
    ax.axhline(base, color=MED_GREY, ls="--", lw=1.4, label=f"Test value {base:.2f}")
    ax.axhline(base - AP_TOL, color=ACCENT_RED, ls="--", lw=1.4, label=f"Degraded below {base - AP_TOL:.2f}")
    for b_, v in zip(bars, pm["ap_7d"]):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.01, f"{v:.2f}", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("7-day average precision"); ax.set_ylim(0, 1); ax.legend(loc="lower right")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_tier_mix():
    tiers = ["CRITICAL", "ELEVATED", "OK"]
    tcol = {"CRITICAL": ACCENT_RED, "ELEVATED": AMBER, "OK": GREEN}
    x = np.arange(len(names)); w = 0.24
    fig, ax = B.make_fig(h=3.2)
    maxv = 0
    for i, t in enumerate(tiers):
        vals = [int((preds_by[l]["health_indicator"] == t).sum()) for l in labels]
        maxv = max(maxv, max(vals))
        bars = ax.bar(x + (i - 1) * w, vals, w, color=tcol[t], label=t if t == "OK" else t.title())
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + maxv * 0.012, f"{v}",
                    ha="center", va="bottom", fontsize=8, color=DARK_GREY)
    ax.set_xticks(x); ax.set_xticklabels(names); ax.set_ylabel("Observations")
    ax.set_ylim(0, maxv * 1.16)
    ax.legend(ncol=3, fontsize=9); B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_drift_bar(col):
    vals = pm[col].values
    colors = [ACCENT_RED if v >= DRIFT_THRESHOLD else GREEN for v in vals]
    fig, ax = B.make_fig(h=3.2)
    bars = ax.bar(names, vals, color=colors, width=0.5)
    ax.axhline(DRIFT_THRESHOLD, color=ACCENT_RED, ls="--", lw=1.4, label=f"Threshold {DRIFT_THRESHOLD}")
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.005, f"{v:.3f}", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Jensen-Shannon distance")
    ax.set_ylim(0, max(DRIFT_THRESHOLD * 1.3, vals.max() * 1.3))
    ax.legend(); B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_pred_dist():
    fig, ax = B.make_fig(h=3.4)
    bins = np.linspace(0, 1, 26)
    ax.hist(val_ref["prob_failure_7d"], bins=bins, density=True, alpha=0.55, color=MED_GREY,
            label="Validation reference", edgecolor="white", linewidth=0.4)
    ax.hist(preds_by[labels[-1]]["prob_failure_7d"], bins=bins, density=True, alpha=0.6,
            color=DARK_BLUE, label=f"Current ({names[-1]})", edgecolor="white", linewidth=0.4)
    ax.axvline(m["thresholds"]["7"], color=ACCENT_RED, ls="--", lw=1.2)
    ax.set_xlabel("Probability of an unplanned repair within 7 days"); ax.set_ylabel("Density"); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_feature_heatmap():
    present = [l for l in labels if l in drift_by]
    if not present:
        return None
    mat = drift_by[present[0]][["feature"]].set_index("feature")
    for l in present:
        mat[l] = drift_by[l].set_index("feature")["drift_score"]
    mat["_m"] = mat.mean(axis=1); mat = mat.sort_values("_m").drop(columns="_m")
    M = mat[present].values
    fig, ax = plt.subplots(figsize=(B.CHART_W, max(3.6, len(mat) * 0.32)))
    im = ax.imshow(M, aspect="auto", cmap=HEAT, vmin=0, vmax=max(DRIFT_THRESHOLD, float(np.nanmax(M))))
    ax.set_xticks(range(len(present))); ax.set_xticklabels([dict(zip(labels, names))[l] for l in present])
    ax.set_yticks(range(len(mat))); ax.set_yticklabels(mat.index, fontsize=9)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if v >= DRIFT_THRESHOLD else DARK_GREY)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02); cb.set_label("Drift distance", fontsize=9)
    plt.tight_layout()
    return B.b64(fig)


# ── Data quality from the raw mart (latest period) ──────────────────────────
start, end = PERIOD_DATES[labels[-1]]
con = duckdb.connect(str(DB_PATH), read_only=True)
raw = con.execute(f"select * from mart_ml__health_features where observation_date>='{start}' and observation_date<='{end}'").df()
train_raw = con.execute("select * from mart_ml__health_features where observation_date<='2024-12-31'").df()
con.close()


def chart_data_quality():
    cols = [c for c in ALL_FEATURES if c in raw.columns] + [c for c in ["days_since_last_pm", "last_failure_mode"] if c in raw.columns]
    cols = list(dict.fromkeys(cols))
    nr = (raw[cols].isna().mean() * 100).sort_values(ascending=False)
    nr = nr[nr > 0]
    if nr.empty:
        nr = pd.Series([0.0], index=["No nulls detected"])
    fig, ax = B.make_fig(h=max(2.6, len(nr) * 0.4))
    colors = [ACCENT_RED if v > 10 else AMBER if v > 5 else DARK_BLUE for v in nr.values]
    ax.barh(nr.index[::-1], nr.values[::-1], color=colors[::-1], height=0.6)
    ax.set_xlabel("Null rate (%)")
    B.chart_style(ax); ax.xaxis.grid(True, color=LIGHT_GREY); ax.yaxis.grid(False); fig.tight_layout()
    return B.b64(fig)


charts = {"ap": chart_ap_trend(), "mix": chart_tier_mix(), "target": chart_drift_bar("target_drift_score"),
          "pred": chart_drift_bar("prediction_drift_score"), "pdist": chart_pred_dist(),
          "heat": chart_feature_heatmap(), "dq": chart_data_quality()}

# ── Tables & blocks ─────────────────────────────────────────────────────────
def reasons_latest():
    r = []
    if latest["perf_degraded"]:
        r.append(f"7-day average precision ({latest['ap_7d']:.2f}) is more than {AP_TOL:.2f} below the test value")
    if latest["target_drift"]:
        r.append(f"7-day positive rate drifted from training (distance {latest['target_drift_score']:.3f})")
    if latest["prediction_drift"]:
        r.append(f"7-day probability distribution drifted from the validation reference (distance {latest['prediction_drift_score']:.3f})")
    if latest["n_features_drifted"] > MAX_DRIFT_FEATS:
        r.append(f"{int(latest['n_features_drifted'])} input features drifted (more than {MAX_DRIFT_FEATS})")
    return r


def status_block():
    rs = reasons_latest()
    reason_html = ("<ul class='trigger-list'>" + "".join(f"<li>{x}</li>" for x in rs) + "</ul>") if rs \
        else "<p style='margin:8px 0 0;color:#8093A4;'>No triggers met in the latest period.</p>"
    def c(cond):
        return ACCENT_RED if cond else GREEN
    return f"""<div class="status-block" style="border-color:{rec_color};">
      <div class="status-header" style="background:{rec_color};">
        <span class="status-icon">{rec_icon}</span><span class="status-label">{rec_label}</span>
        <span style="margin-left:auto;font-size:13px;opacity:0.9;">As of {names[-1]}</span></div>
      <div class="status-body">
        <div class="status-meta">
          <div><span class="meta-label">Model Version</span><span class="meta-val">{"v" + str(prod_ver) if prod_ver else "production"} ({m['best_model_type']})</span></div>
          <div><span class="meta-label">Periods Monitored</span><span class="meta-val">{names[0]} to {names[-1]}</span></div>
          <div><span class="meta-label">Reference</span><span class="meta-val">Train Jan 2023 to Dec 2024</span></div>
          <div><span class="meta-label">Latest 7-Day AP</span><span class="meta-val" style="color:{c(latest['perf_degraded'])};">{latest['ap_7d']:.2f} (test {latest['baseline_ap_7d']:.2f})</span></div>
          <div><span class="meta-label">Target Drift</span><span class="meta-val" style="color:{c(latest['target_drift'])};">{latest['target_drift_score']:.3f}</span></div>
          <div><span class="meta-label">Prediction Drift</span><span class="meta-val" style="color:{c(latest['prediction_drift'])};">{latest['prediction_drift_score']:.3f}</span></div>
          <div><span class="meta-label">Features Drifted</span><span class="meta-val" style="color:{c(latest['n_features_drifted']>MAX_DRIFT_FEATS)};">{int(latest['n_features_drifted'])} / {int(latest['n_features'])}</span></div>
        </div>
        <div><div style="font-size:12px;font-weight:700;color:{MED_GREY};text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;">Trigger Reasons</div>{reason_html}</div>
      </div></div>"""


def retraining_rules():
    rules = [("Primary", f"7-day average precision falls more than {AP_TOL:.2f} below the test value", bool(latest["perf_degraded"])),
             ("Primary", f"7-day positive rate drifts from training (distance &ge; {DRIFT_THRESHOLD})", bool(latest["target_drift"])),
             ("Secondary", "7-day probability distribution drifts vs validation reference", bool(latest["prediction_drift"])),
             ("Secondary", f"More than {MAX_DRIFT_FEATS} input features drift vs training", bool(latest["n_features_drifted"] > MAX_DRIFT_FEATS))]
    rows = ""
    for tier, rule, trig in rules:
        col = ACCENT_RED if trig else GREEN
        rows += (f'<tr><td style="width:30px;text-align:center;color:{col};font-size:16px;">{"&#9888;" if trig else "&#10003;"}</td>'
                 f'<td><span style="font-size:11px;font-weight:700;color:{DARK_GREY};">{tier}</span></td>'
                 f'<td>{rule}</td><td style="text-align:center;color:{col};font-weight:700;">{"TRIGGERED" if trig else "OK"}</td></tr>')
    return f'<table class="data-table"><thead><tr><th></th><th>Tier</th><th>Rule</th><th style="text-align:center;">Status</th></tr></thead><tbody>{rows}</tbody></table>'


def period_table(cols_spec):
    rows = []
    for r in pm.itertuples():
        rows.append([getattr(r, c) if not fmt else fmt(getattr(r, c)) for c, _, fmt in cols_spec])
    heads = [h for _, h, _ in cols_spec]
    right = {i for i, (_, _, f) in enumerate(cols_spec) if i > 0}
    return B.data_table(heads, [[str(c) for c in row] for row in rows], right=right)


def drift_status_table(score_col, flag_col):
    rows = ""
    for r in pm.itertuples():
        drift = getattr(r, flag_col)
        col = ACCENT_RED if drift else GREEN
        rows += (f'<tr><td style="font-weight:600;">{r.period_name}</td>'
                 f'<td style="text-align:right;">{getattr(r, score_col):.4f}</td>'
                 f'<td style="text-align:right;">{DRIFT_THRESHOLD:.2f}</td>'
                 f'<td style="text-align:center;color:{col};font-weight:700;">{"&#9888; Drift" if drift else "&#10003; Stable"}</td></tr>')
    return f'<table class="data-table"><thead><tr><th>Period</th><th style="text-align:right;">Distance</th><th style="text-align:right;">Threshold</th><th style="text-align:center;">Status</th></tr></thead><tbody>{rows}</tbody></table>'


def feature_drift_table():
    df = drift_by.get(labels[-1])
    if df is None:
        return "<p style='color:#8093A4;'>Feature drift detail not found.</p>"
    rows = ""
    for r in df.sort_values("drift_score", ascending=False).itertuples():
        col = ACCENT_RED if r.drift_detected else GREEN
        ftype = ("interaction" if r.feature.startswith("is_") else
                 "categorical" if r.feature in CATEGORICAL_FEATURES else "numerical")
        rows += (f'<tr><td style="font-family:monospace;font-size:13px;">{r.feature}</td><td>{ftype}</td>'
                 f'<td style="text-align:right;">{r.drift_score:.4f}</td><td style="text-align:right;">{DRIFT_THRESHOLD:.2f}</td>'
                 f'<td style="text-align:center;color:{col};font-weight:700;">{"&#9888; Drift" if r.drift_detected else "&#10003; Stable"}</td></tr>')
    return f'<table class="data-table"><thead><tr><th>Feature</th><th>Type</th><th style="text-align:right;">Distance</th><th style="text-align:right;">Threshold</th><th style="text-align:center;">Status</th></tr></thead><tbody>{rows}</tbody></table>'


def data_quality_table():
    cols = [c for c in ALL_FEATURES if c in raw.columns] + [c for c in ["days_since_last_pm", "last_failure_mode"] if c in raw.columns]
    cols = list(dict.fromkeys(cols))
    rows = ""
    for c in cols:
        nullp = raw[c].isna().mean() * 100
        nun = raw[c].nunique()
        if c in CATEGORICAL_FEATURES:
            new = set(raw[c].dropna().unique()) - set(train_raw[c].dropna().unique())
            newstr = f"{len(new)} new" if new else "&mdash;".replace("&mdash;", "-")
        else:
            newstr = "&mdash;".replace("&mdash;", "-")
        ncol = ACCENT_RED if nullp > 10 else AMBER if nullp > 5 else TEXT if False else "#000000"
        rows += (f'<tr><td style="font-family:monospace;font-size:13px;">{c}</td>'
                 f'<td style="text-align:right;color:{ncol};">{nullp:.1f}%</td>'
                 f'<td style="text-align:right;">{nun:,}</td><td style="text-align:center;">{newstr}</td></tr>')
    return f'<table class="data-table"><thead><tr><th>Feature</th><th style="text-align:right;">Null rate</th><th style="text-align:right;">Unique values</th><th style="text-align:center;">New categories</th></tr></thead><tbody>{rows}</tbody></table>'


def version_history_table():
    if not version_rows:
        return "<p style='color:#8093A4;'>Registry history unavailable.</p>"
    rows = ""
    for ver, mtype, vap in version_rows:
        cur = str(ver) == str(prod_ver)
        bg = f' style="background:{BG_GREY};font-weight:700;"' if cur else ""
        stage = f'<span style="color:{DARK_BLUE};font-weight:700;">production</span>' if cur else "archived"
        score = f"{vap:.3f}" if vap is not None else "-"
        rows += (f'<tr{bg}><td>v{ver}{" &larr; current" if cur else ""}</td><td>{mtype}</td>'
                 f'<td style="text-align:right;">{score}</td><td>{stage}</td></tr>')
    return f'<table class="data-table"><thead><tr><th>Version</th><th>Type</th><th style="text-align:right;">Test AP, 7 days</th><th>Alias</th></tr></thead><tbody>{rows}</tbody></table>'


# ── Sentences that state what the periods show ──────────────────────────────
def _months(flag):
    hit = [n.split()[0] for n, f in zip(names, pm[flag]) if f]
    if not hit:
        return "no period"
    return hit[0] if len(hit) == 1 else ", ".join(hit[:-1]) + " and " + hit[-1]


REC_TEXT = {
    "HEALTHY": "The flag currently reads NO ACTION REQUIRED: no primary or secondary trigger has held for two "
               "consecutive periods, so the production model continues to score the fleet as it is.",
    "INVESTIGATE": "The flag currently reads INVESTIGATE: no primary trigger has fired, so there is no case to "
                   "retrain, but a secondary trigger (prediction or feature drift) has held for two consecutive "
                   "periods. The production model continues to score the fleet while the drifting inputs are reviewed.",
    "RETRAIN": "The flag currently reads RETRAIN RECOMMENDED: a primary trigger has held for two consecutive "
               "periods, so the production model is due to be retrained on data extended through the latest "
               "period and promoted once it clears validation.",
}
_ap_lo, _ap_hi, _ap_base = pm["ap_7d"].min(), pm["ap_7d"].max(), pm["baseline_ap_7d"].iloc[0]
PERF_TEXT = (f"Across the three periods 7-day average precision runs from {_ap_lo:.2f} to {_ap_hi:.2f} against "
             f"{_ap_base:.2f} on test, " + ("and falls below the degraded line in " + _months("perf_degraded") + "."
                                           if pm["perf_degraded"].any() else
                                           f"and stays above the degraded line of {_ap_base - AP_TOL:.2f} in every period, "
                                           "so the performance layer gives no reason to retrain."))
TARGET_TEXT = (f"The 7-day positive rate runs from {pm['positive_rate_7d'].min():.1%} to {pm['positive_rate_7d'].max():.1%} "
               f"against {pm['train_positive_rate_7d'].iloc[0]:.1%} in training; the distance peaks at "
               f"{pm['target_drift_score'].max():.3f}, " + ("crossing the threshold in " + _months("target_drift") + "."
                                                            if pm["target_drift"].any() else
                                                            "below the threshold in every period, so the target has not drifted."))
PRED_TEXT = ("Prediction drift is flagged in " + _months("prediction_drift") + f", with the distance peaking at "
             f"{pm['prediction_drift_score'].max():.3f}. As a secondary trigger it supports investigation rather than "
             "driving the decision on its own." if pm["prediction_drift"].any() else
             f"Prediction drift stays below the threshold in every period (peak {pm['prediction_drift_score'].max():.3f}).")
_movers = (pd.concat([d.set_index("feature")["drift_score"] for d in drift_by.values()], axis=1)
           .mean(axis=1).sort_values(ascending=False).head(3).index.tolist())
FEATURE_TEXT = (f"Between {int(pm['n_features_drifted'].min())} and {int(pm['n_features_drifted'].max())} of "
                f"{int(pm['n_features'].iloc[0])} features are flagged each period. The largest movers on average are "
                + ", ".join(f"<code>{f}</code>" for f in _movers[:-1]) + f" and <code>{_movers[-1]}</code>.")
_dq_cols = list(dict.fromkeys([c for c in ALL_FEATURES if c in raw.columns]
                              + [c for c in ["days_since_last_pm", "last_failure_mode"] if c in raw.columns]))
_max_null = float(raw[_dq_cols].isna().mean().max() * 100)
_new_cats = sum(len(set(raw[c].dropna().unique()) - set(train_raw[c].dropna().unique()))
                for c in CATEGORICAL_FEATURES if c in raw.columns)
DQ_TEXT = (f"The latest period arrives with a highest null rate of {_max_null:.1f}% and "
           f"{'no' if _new_cats == 0 else _new_cats} unseen categor{'ies' if _new_cats != 1 else 'y'}"
           + (", which rules out broken inputs as the source of the drift above." if _max_null == 0 and _new_cats == 0 else "."))

toc = ('<a href="#status">1 &middot; Status &amp; Decision</a>'
       '<a href="#summary">2 &middot; MLOps Monitoring Summary</a>'
       '<a href="#perf" class="sub">Performance</a>'
       '<a href="#target" class="sub">Target Drift</a>'
       '<a href="#prediction" class="sub">Prediction Drift</a>'
       '<a href="#feature" class="sub">Feature Drift</a>'
       '<a href="#quality" class="sub">Data Quality</a>'
       '<a href="#log">3 &middot; Monitoring Log</a>')

perf_tbl = period_table([("period_name", "Period", None), ("n_scored", "Scored", lambda v: f"{int(v):,}"),
                         ("ap_7d", "7-day average precision", lambda v: f"{v:.3f}"),
                         ("roc_auc_7d", "7-day ROC-AUC", lambda v: f"{v:.3f}"),
                         ("tier_recall", "CRITICAL or ELEVATED before failures", lambda v: f"{v:.0%}"),
                         ("status", "Status", None)])

body = f"""
{B.section("status", "Section 1", "Status &amp; Retraining Decision")}
<p>The machine health indicator is monitored monthly across the forward window. Performance and target drift
are the primary retraining triggers; prediction and feature drift act as leading proxies. The verdict below is
the standing recommendation under the two-consecutive-period rule; the sections that follow show the
full trend.</p>
<p>{REC_TEXT.get(rec, "")}</p>
{status_block()}
<p>Retraining rules are evaluated every period. Primary rules measure harm directly; secondary rules
are leading proxies that warrant investigation rather than immediate retraining.</p>
{retraining_rules()}

{B.section("summary", "Section 2", "MLOps Monitoring Summary")}
<p>The four monitoring layers below track the model every period. Performance and target drift are the
primary retraining triggers; prediction and feature drift are leading proxies; and data quality confirms the
inputs feeding all of them are sound.</p>

{B.section("perf", "Section 2.1", "Performance")}
<p>7-day average precision each period against the held-out test value of {_ap_base:.2f}, on the
observations whose 7-day outcome is known. Performance is flagged degraded when it falls more than
{AP_TOL:.2f} below the test value. The share of failures preceded by a CRITICAL or ELEVATED day is at its
ceiling in every period, so it is shown for reference and is not the check. <strong>{PERF_TEXT}</strong></p>
{B.chart("7-Day Average Precision by Period", charts["ap"])}
{perf_tbl}
{B.chart("Health Indicator Mix by Period", charts["mix"])}

{B.section("target", "Section 2.2", "Target Drift")}
<p>Distance between each period's 7-day positive rate and the training rate
(Jensen-Shannon, flagged at {DRIFT_THRESHOLD}). A shift signals the underlying failure profile has moved,
which can degrade calibration even when inputs look stable. <strong>{TARGET_TEXT}</strong></p>
{B.chart("Target Drift Distance by Period", charts["target"])}
{drift_status_table("target_drift_score", "target_drift")}

{B.section("prediction", "Section 2.3", "Prediction Drift")}
<p>Distance between the model's 7-day probability distribution each period and the validation reference. A
label-free early indicator that catches the model behaving differently regardless of which input moved.
<strong>{PRED_TEXT}</strong></p>
{B.chart("Prediction Drift Distance by Period", charts["pred"])}
{drift_status_table("prediction_drift_score", "prediction_drift")}
{B.chart(f"7-Day Probability Distribution: Validation Reference vs {names[-1]}", charts["pdist"])}

{B.section("feature", "Section 2.4", "Feature Drift")}
<p>Per-feature distance between each period's input distribution and the training reference. Values at
or above {DRIFT_THRESHOLD} are flagged. Feature drift is diagnostic context: it helps explain a
performance change but does not, alone, establish that the model is wrong. <strong>{FEATURE_TEXT}</strong></p>
{B.chart("Per-Feature Drift Distance (feature by period)", charts["heat"])}
<p>Latest-period detail ({names[-1]}), ordered by distance:</p>
{feature_drift_table()}

{B.section("quality", "Section 2.5", "Data Quality")}
<p>Null rates, cardinality, and unseen categories for the latest scoring period, measured on the raw
feature mart before imputation. Early-window nulls are imputed with fixed constants in features.py;
unseen categories are absorbed by the model's unknown-value encoding. <strong>{DQ_TEXT}</strong></p>
{B.chart(f"Feature Null Rates: {names[-1]}", charts["dq"])}
{data_quality_table()}

{B.section("log", "Section 3", "Monitoring Log")}
<p>Model version history from the MLflow registry, for traceability.</p>
{version_history_table()}
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("MLOps Monitoring Report: Machine Health Indicator",
                      "", toc, body), encoding="utf-8")
print(f"Monitoring report written to {OUT}")
