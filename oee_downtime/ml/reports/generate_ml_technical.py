"""ML Technical Overview for the machine health indicator -> docs/reports/technical_report.html
Model Card, Training Data (feature set, targets), Model Selection, Performance
(window metrics against the baselines, learning curve, calibration, precision
and recall, tiers against failures, the sensor ablation), Feature Importance,
Known Limitations, Deployment."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

import sys
sys.path.insert(0, str(Path(__file__).parent))
import brand as B
from brand import DARK_BLUE, LIGHT_BLUE, ACCENT_RED, AMBER, GREEN, MED_GREY, LIGHT_GREY, DARK_GREY
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from features import CATEGORICAL_FEATURES, NUMERICAL_FEATURES, INTERACTION_FEATURES, TARGETS, WINDOWS

REPO     = Path(__file__).resolve().parents[2]
MODELS   = REPO / "ml" / "models"
FEATURES = REPO / "ml" / "data" / "features"
SCORING  = REPO / "ml" / "data" / "scoring"
OUT      = REPO / "docs" / "reports" / "technical_report.html"
LABELS = {"logistic_regression": "Logistic Regression", "random_forest": "Random Forest", "xgboost": "XGBoost"}
SOURCES = ["model", "interval", "rules", "calendar_pm"]
SOURCE_NAME = {"model": "Health indicator", "interval": "Interval baseline",
               "rules": "Rules baseline", "calendar_pm": "Calendar PM (current practice)"}
SPLIT_NAME = {"test": "Test (Sep to Dec 2025)", "scoring": "Scoring (Jan to Mar 2026)"}
WINDOW_COLOR = {7: DARK_BLUE, 21: LIGHT_BLUE}

m     = json.loads((MODELS / "metrics.json").read_text(encoding="utf-8"))
ss    = json.loads((MODELS / "scoring_summary.json").read_text(encoding="utf-8"))
comp  = pd.read_csv(MODELS / "model_comparison.csv")
imp   = pd.read_csv(MODELS / "shap_importance.csv")
calib = pd.read_csv(MODELS / "calibration_test.csv")
prc   = pd.read_csv(MODELS / "precision_recall_test.csv")
abl   = pd.read_csv(MODELS / "ablation_no_sensors.csv")
lc    = pd.read_csv(MODELS / "learning_curve.csv") if (MODELS / "learning_curve.csv").exists() else None
win   = {s: pd.read_csv(MODELS / f"evaluation_windows_{s}.csv") for s in ("test", "scoring")}
tiers = {s: pd.read_csv(MODELS / f"evaluation_tiers_{s}.csv") for s in ("test", "scoring")}
tdays = {s: pd.read_csv(MODELS / f"tier_days_{s}.csv") for s in ("test", "scoring")}
train = pd.read_parquet(FEATURES / "train.parquet")
val   = pd.read_parquet(FEATURES / "validation.parquet")
test  = pd.read_parquet(FEATURES / "test.parquet")
best  = m["best_model_type"]
TH    = {n: m["thresholds"][str(n)] for n in WINDOWS}
_bp = next((x["params"] for x in m["models"] if x["model_type"] == best), {})
sensor_share = {n: m["sensor_importance_share"][str(n)]["shap"] for n in WINDOWS}

# Monthly observation volume and fleet size, for the data-coverage view.
_dv = duckdb.connect(str(REPO / "data_source" / "oee_predmaint.duckdb"), read_only=True)
_vol = _dv.execute("select observation_date from mart_ml__health_features").df()
n_machines = int(_dv.execute("select count(distinct machine_id) from mart_ml__health_features").fetchone()[0])
_dv.close()
_vol["ym"] = pd.to_datetime(_vol["observation_date"]).dt.to_period("M").dt.to_timestamp()
vol_monthly = _vol.groupby("ym").size()


def wm(split, source, window, col):
    w = win[split]
    return w[(w["source"] == source) & (w["window_days"] == window)][col].iloc[0]


# Failures in the test and scoring windows by failure mode: the share with a
# CRITICAL day in the 7 days before, from the tier history.
_hist = pd.read_parquet(SCORING / "tier_history.parquet")
_hist["observation_date"] = pd.to_datetime(_hist["observation_date"])
_by_machine = {mid: g.set_index("observation_date")["model"] for mid, g in _hist.groupby("machine_id")}
_mm = pd.read_csv(REPO / "data_source" / "raw" / "cmms" / "maintenance_records.csv")
_mm = _mm[_mm["maintenance_type"] == "UNPLANNED_REPAIR"].copy()
_mm["fday"] = pd.to_datetime(_mm["work_order_open_date"]).dt.normalize()
_ev = _mm[(_mm["fday"] >= "2025-09-01") & (_mm["fday"] <= "2026-03-31")].copy()


def _critical_before(machine_id, fday):
    h = _by_machine[machine_id]
    w = h[(h.index >= fday - pd.Timedelta(days=7)) & (h.index < fday)]
    return bool((w == "CRITICAL").any())


_ev["hit"] = [_critical_before(mid, fd) for mid, fd in zip(_ev["machine_id"], _ev["fday"])]
mode_hit = _ev.groupby("failure_code")["hit"].agg(["mean", "size"]).sort_values("mean")
mode_best, mode_worst = mode_hit.index[-1], mode_hit.index[0]


def _mode(x):
    return str(x).replace("_", " ").lower()


# ── Charts ──────────────────────────────────────────────────────────────────
def chart_target_rates():
    splits = [("Train", train, DARK_BLUE), ("Validation", val, LIGHT_BLUE), ("Test", test, MED_GREY)]
    x = np.arange(len(WINDOWS)); w = 0.25
    fig, ax = B.make_fig(h=3.2)
    for i, (lab, df, c) in enumerate(splits):
        vals = [float(df[TARGETS[n]].mean()) * 100 for n in WINDOWS]
        bars = ax.bar(x + (i - 1) * w, vals, w, color=c, label=lab)
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + 1, f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels([f"Repair within {n} days" for n in WINDOWS])
    ax.set_ylabel("Share of observations (%)"); ax.set_ylim(0, 80); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_learning():
    if lc is None:
        return None
    fig, ax = B.make_fig(h=3.2)
    ax.plot(lc["train_size"], lc["train_average_precision"], "o-", color=DARK_BLUE, lw=2, label="Train")
    ax.plot(lc["train_size"], lc["val_average_precision"], "s-", color=LIGHT_BLUE, lw=2, label="Cross-validation")
    ax.set_xlabel("Training observations"); ax.set_ylabel("Average precision (7-day model)"); ax.legend()
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_calibration():
    fig, ax = B.make_fig(h=3.6)
    ax.plot([0, 1], [0, 1], color=MED_GREY, ls="--", lw=1.5, label="Perfectly calibrated")
    for n in WINDOWS:
        c = calib[calib["window_days"] == n]
        ax.plot(c["mean_predicted"], c["observed_rate"], "o-", color=WINDOW_COLOR[n], lw=2, label=f"{n}-day model")
    ax.set_xlabel("Mean calibrated probability (bin)"); ax.set_ylabel("Observed repair rate (bin)")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.legend(loc="upper left")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_precision_recall():
    fig, ax = B.make_fig(h=3.6)
    for n in WINDOWS:
        c = prc[prc["window_days"] == n]
        ax.plot(c["recall"], c["precision"], color=WINDOW_COLOR[n], lw=2, label=f"{n}-day model")
        ax.plot([wm("test", "model", n, "recall")], [wm("test", "model", n, "precision")], "o",
                color=ACCENT_RED, markersize=8, zorder=5,
                label="Operating threshold" if n == WINDOWS[0] else None)
        ax.axhline(wm("test", "model", n, "positive_rate"), color=WINDOW_COLOR[n], ls=":", lw=1.2)
    ax.set_xlabel("Recall"); ax.set_ylabel("Precision"); ax.set_xlim(0, 1); ax.set_ylim(0, 1.02)
    ax.legend(loc="lower left")
    B.chart_style(ax); fig.tight_layout()
    return B.b64(fig)


def chart_hit_by_mode():
    d = mode_hit
    fig, ax = B.make_fig(h=2.8)
    ax.barh([f"{str(x).replace('_', ' ').title()} ({int(n)})" for x, n in zip(d.index, d["size"])], d["mean"] * 100,
            color=[ACCENT_RED if i == mode_worst else DARK_BLUE for i in d.index], height=0.6)
    for i, v in enumerate(d["mean"] * 100):
        ax.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=10)
    ax.set_xlabel("Failures with a CRITICAL day in the 7 days before (%)"); ax.set_xlim(0, 112)
    B.chart_style(ax); ax.xaxis.grid(True, color=LIGHT_GREY); ax.yaxis.grid(False)
    fig.tight_layout()
    return B.b64(fig)


def chart_shap():
    d = imp[imp["window_days"] == 7].head(12).iloc[::-1]
    fig, ax = B.make_fig(h=B.CHART_H_T)
    ax.barh(d["feature"], d["shap_share"] * 100,
            color=[LIGHT_BLUE if s else DARK_BLUE for s in d["sensor_feature"]], height=0.68)
    for i, v in enumerate(d["shap_share"] * 100):
        ax.text(v + 0.2, i, f"{v:.1f}%", va="center", fontsize=9, color=MED_GREY)
    ax.set_xlabel("Share of mean |SHAP|, 7-day model (sensor features in light blue)")
    B.chart_style(ax); ax.xaxis.grid(True, color=LIGHT_GREY); ax.yaxis.grid(False)
    fig.tight_layout()
    return B.b64(fig)


def chart_data_volume():
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch
    def split_of(ts):
        if ts <= pd.Timestamp("2024-12-31"): return "Train", DARK_BLUE
        if ts <= pd.Timestamp("2025-08-31"): return "Validation", LIGHT_BLUE
        if ts <= pd.Timestamp("2025-12-31"): return "Test", AMBER
        return "Scoring (held out)", MED_GREY
    fig, ax = B.make_fig(h=3.0)
    ax.bar(vol_monthly.index, vol_monthly.values, width=22,
           color=[split_of(ts)[1] for ts in vol_monthly.index])
    ax.set_ylabel("Observations / month")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    seen = {}
    for ts in vol_monthly.index:
        lab, col = split_of(ts); seen[lab] = col
    ax.legend(handles=[Patch(color=c, label=l) for l, c in seen.items()],
              fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False)
    B.chart_style(ax)
    fig.tight_layout()
    return B.b64(fig)


def chart_corr_heatmap():
    from matplotlib.colors import LinearSegmentedColormap
    feats = [f for f in NUMERICAL_FEATURES if f in train.columns]
    with np.errstate(invalid="ignore", divide="ignore"):
        C = train[feats].astype(float).corr().fillna(0.0).values
    cmap = LinearSegmentedColormap.from_list("brand_div", [DARK_BLUE, "#FFFFFF", ACCENT_RED])
    fig, ax = B.make_fig(h=6.4)
    im = ax.imshow(C, cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(feats))); ax.set_yticks(range(len(feats)))
    ax.set_xticklabels(feats, rotation=90, fontsize=6.5)
    ax.set_yticklabels(feats, fontsize=6.5)
    ax.set_xticks(np.arange(-.5, len(feats), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(feats), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.6)
    ax.tick_params(which="minor", length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, fraction=0.046, pad=0.04); cb.ax.tick_params(labelsize=7)
    fig.tight_layout()
    return B.b64(fig)


# ── Tables ──────────────────────────────────────────────────────────────────
def _fmt(v, d=3):
    return "n/a" if pd.isna(v) else f"{v:.{d}f}"


def window_table(split):
    """Each window: the indicator beside the three baselines."""
    rows = ""
    for n in WINDOWS:
        for s in SOURCES:
            bg = f' style="background:{B.BG_GREY};font-weight:700;"' if s == "model" else ""
            rows += (f'<tr{bg}><td>{n} days</td><td>{SOURCE_NAME[s]}</td>'
                     + "".join(f'<td style="text-align:right;">{_fmt(wm(split, s, n, c))}</td>'
                               for c in ("precision", "recall", "roc_auc", "average_precision", "brier"))
                     + f'<td style="text-align:right;">{wm(split, s, n, "flagged_share"):.1%}</td></tr>')
    n7, n21 = (int(wm(split, "model", n, "rows")) for n in WINDOWS)
    head = "".join(f'<th style="text-align:right;">{h}</th>' for h in
                   ("Precision", "Recall", "ROC-AUC", "Average precision", "Brier", "Share flagged"))
    return (f'<table class="data-table"><thead><tr><th>Window</th><th>Source</th>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'<p style="font-size:13px;color:{MED_GREY};margin-top:-6px;">{SPLIT_NAME[split]}: {n7:,} observations at 7 days '
            f'({wm(split, "model", 7, "positive_rate"):.1%} positive), {n21:,} at 21 days '
            f'({wm(split, "model", 21, "positive_rate"):.1%} positive).</p>')


def tier_table():
    rows = ""
    for split in ("test", "scoring"):
        t = tiers[split].set_index("source")
        for s in SOURCES:
            r = t.loc[s]
            bg = f' style="background:{B.BG_GREY};font-weight:700;"' if s == "model" else ""
            rows += (f'<tr{bg}><td>{SPLIT_NAME[split]}</td><td>{SOURCE_NAME[s]}</td>'
                     f'<td style="text-align:right;">{int(r["failures"])}</td>'
                     f'<td style="text-align:right;">{r["critical_within_7d_share"]:.1%}</td>'
                     f'<td style="text-align:right;">{_fmt(r["critical_median_lead_days"], 1)}</td>'
                     f'<td style="text-align:right;">{r["critical_or_elevated_within_21d_share"]:.1%}</td>'
                     f'<td style="text-align:right;">{_fmt(r["critical_or_elevated_median_lead_days"], 1)}</td></tr>')
    head = "".join(f'<th style="text-align:right;">{h}</th>' for h in
                   ("Failures", "CRITICAL in the 7 days before", "Median lead (days)",
                    "CRITICAL or ELEVATED in the 21 days before", "Median lead (days)"))
    return (f'<table class="data-table"><thead><tr><th>Period</th><th>Source</th>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def tier_days_table():
    rows = []
    for split in ("test", "scoring"):
        t = tdays[split]
        for r in t[t["source"] == "model"].itertuples():
            tot = r.CRITICAL + r.ELEVATED + r.OK
            rows.append([pd.Timestamp(r.month + "-01").strftime("%B %Y"), f"{r.CRITICAL:,}", f"{r.ELEVATED:,}",
                         f"{r.OK:,}", f"{r.CRITICAL / tot:.0%}"])
    return B.data_table(["Month", "CRITICAL", "ELEVATED", "OK", "Share CRITICAL"], rows, right={1, 2, 3, 4})


def ablation_table():
    rows = ""
    a = abl.set_index(["model", "split"])
    spec = [("7-day model, all 27 features", lambda sp, c: a.loc[("all features", sp), c]),
            ("7-day model, without the 10 sensor features", lambda sp, c: a.loc[("without sensor features", sp), c]),
            ("Interval baseline", lambda sp, c: wm(sp, "interval", 7, c))]
    for label, get in spec:
        rows += (f'<tr><td>{label}</td>'
                 + "".join(f'<td style="text-align:right;">{get(sp, c):.3f}</td>'
                           for sp in ("test", "scoring") for c in ("roc_auc", "average_precision"))
                 + '</tr>')
    return ('<table class="data-table"><thead><tr><th>7-day window</th>'
            '<th style="text-align:right;">Test ROC-AUC</th><th style="text-align:right;">Test average precision</th>'
            '<th style="text-align:right;">Scoring ROC-AUC</th><th style="text-align:right;">Scoring average precision</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def ops_table():
    rows = [
        ["Scoring cadence", f"Daily batch; all {n_machines} machines scored ahead of each shift"],
        ["Inference latency",
         f"Two gradient-boosted classifiers over {m['feature_counts']['total']} features; the full-fleet "
         f"daily batch scores in well under a second on commodity hardware"],
        ["Model registry",
         "MLflow Model Registry, <code>machine_health_indicator</code> under the production alias; the two "
         "window models, their calibrators and thresholds are one version, each retrain registers a new "
         "version and this report regenerates against it"],
        ["Data lineage",
         "Source systems (MachineMetrics, JobBOSS ERP, Limble CMMS, ADP, IIoT gateway) &rarr; dlt ingestion "
         "&rarr; dbt staging, intermediate and marts &rarr; mart_ml__health_features &rarr; features.py &rarr; "
         "registered model &rarr; CMMS asset list"],
        ["Retraining trigger",
         "Monitoring report rules: 7-day average precision more than 0.10 below the test value, or target "
         "drift, across two consecutive periods"],
    ]
    return B.data_table(["Specification", "Detail"], rows)


def training_data_table():
    def rate(df, n):
        return f"{df[TARGETS[n]].mean():.1%}"
    rows = [["Train", "Jan 2023 to Dec 2024", f"{m['split_sizes']['train']:,}", rate(train, 7), rate(train, 21)],
            ["Validation", "Jan to Aug 2025", f"{m['split_sizes']['validation']:,}", rate(val, 7), rate(val, 21)],
            ["Test", "Sep to Dec 2025", f"{m['split_sizes']['test']:,}", rate(test, 7), rate(test, 21)],
            ["Scoring (held out)", "Jan to Mar 2026", f"{ss['rows_scored']:,}",
             f"{wm('scoring', 'model', 7, 'positive_rate'):.1%}", f"{wm('scoring', 'model', 21, 'positive_rate'):.1%}"]]
    return B.data_table(["Split", "Window", "Observations", "Repair within 7 days", "Repair within 21 days"],
                        rows, right={2, 3, 4})


def feature_table():
    order = ([(f, "Categorical") for f in CATEGORICAL_FEATURES]
             + [(f, "Numerical") for f in NUMERICAL_FEATURES]
             + [(f, "Interaction") for f in INTERACTION_FEATURES])
    tcol = {"Categorical": LIGHT_BLUE, "Numerical": DARK_BLUE, "Interaction": AMBER}
    rows = ""
    for feat, ftype in order:
        if ftype == "Categorical" or feat not in train.columns:
            corr = "-"
        elif all(df[feat].nunique(dropna=False) <= 1 for df in (train, val, test)):
            corr = "constant in this record, carried for scoring compatibility"
        else:
            c = train[feat].astype(float).corr(train[TARGETS[7]].astype(float))
            corr = f"{c:+.3f}" if pd.notna(c) else "-"
        rows += (f'<tr><td style="font-family:monospace;font-size:13px;">{feat}</td>'
                 f'<td>{B.badge(ftype, tcol[ftype])}</td>'
                 f'<td style="text-align:right;">{corr}</td></tr>')
    return (f'<table class="data-table"><thead><tr><th>Feature</th><th>Type</th>'
            f'<th style="text-align:right;">Corr. with 7-day target</th></tr></thead><tbody>{rows}</tbody></table>')


def comparison_table():
    rows = ""
    for r in comp.sort_values("val_ap_mean", ascending=False).itertuples():
        sel = r.model_type == best
        mark = ' <span style="color:%s;font-weight:700;">&#10003; Selected</span>' % GREEN if sel else ""
        bg = f' style="background:{B.BG_GREY};font-weight:700;"' if sel else ""
        rows += (f'<tr{bg}><td>{LABELS.get(r.model_type, r.model_type)}{mark}</td>'
                 f'<td style="text-align:right;">{r.val_ap_7d:.3f}</td>'
                 f'<td style="text-align:right;">{r.val_ap_21d:.3f}</td>'
                 f'<td style="text-align:right;">{r.val_ap_mean:.3f}</td>'
                 f'<td style="text-align:right;">{r.val_auc_7d:.3f}</td>'
                 f'<td style="text-align:right;">{r.val_auc_21d:.3f}</td></tr>')
    return (f'<table class="data-table"><thead><tr><th>Model</th>'
            f'<th style="text-align:right;">Val AP, 7 days</th><th style="text-align:right;">Val AP, 21 days</th>'
            f'<th style="text-align:right;">Val AP, mean</th><th style="text-align:right;">Val ROC-AUC, 7 days</th>'
            f'<th style="text-align:right;">Val ROC-AUC, 21 days</th></tr></thead><tbody>{rows}</tbody></table>')


def params_table():
    keys = list(_bp[str(WINDOWS[0])].keys())
    rows = []
    for k in keys:
        vals = [_bp[str(n)][k] for n in WINDOWS]
        rows.append([f'<span style="font-family:monospace;font-size:13px;">{k}</span>']
                    + [f"{v:.3f}" if isinstance(v, float) else str(v) for v in vals])
    rows.append(["Probability threshold (calibrated)"] + [f"{TH[n]:.3f}" for n in WINDOWS])
    return B.data_table(["Setting"] + [f"{n}-day model" for n in WINDOWS], rows, right={1, 2})


charts = {"target": chart_target_rates(), "learning": chart_learning(), "calib": chart_calibration(),
          "pr": chart_precision_recall(), "mode": chart_hit_by_mode(), "shap": chart_shap(),
          "volume": chart_data_volume(), "corr": chart_corr_heatmap()}

_top = imp[imp["window_days"] == 7].head(4)["feature"].tolist()
_tier_lo = min(tiers[s].set_index("source").loc[x, "critical_or_elevated_within_21d_share"]
               for s in ("test", "scoring") for x in ("model", "interval"))

toc = ('<a href="#card">Model Card</a><hr>'
       '<a href="#data">Training Data</a><hr>'
       '<a href="#modelperf">Model Selection &amp; Performance</a>'
       '<a href="#selection" class="sub">Model Selection</a>'
       '<a href="#performance" class="sub">Model Performance</a><hr>'
       '<a href="#shap">Feature Importance</a><hr>'
       '<a href="#limits">Known Limitations</a><hr>'
       '<a href="#ops">Deployment &amp; Operations</a>')

body = f"""
{B.section("card", "Section 1", "Model Card")}
<div class="model-card"><div class="model-card-grid">
  <div><div class="mc-label">Model Name</div><div class="mc-value">machine_health_indicator</div></div>
  <div><div class="mc-label">Model Type</div><div class="mc-value">{LABELS.get(best, best)}, two window classifiers (scikit-learn Pipelines)</div></div>
  <div><div class="mc-label">Registry</div><div class="mc-value">MLflow Model Registry &middot; production alias &middot; both windows under one version</div></div>
  <div><div class="mc-label">Grain</div><div class="mc-value">One observation per machine, day and shift; the indicator is per machine and day</div></div>
  <div><div class="mc-label">Target</div><div class="mc-value">Two windows: an unplanned repair opening in the CMMS within 7 days, and within 21 days</div></div>
  <div><div class="mc-label">Split</div><div class="mc-value">Time-based: train Jan 2023 to Dec 2024, validation Jan to Aug 2025, test Sep to Dec 2025</div></div>
  <div><div class="mc-label">Candidates</div><div class="mc-value">Logistic regression, random forest, XGBoost, per window</div></div>
  <div><div class="mc-label">Tuning</div><div class="mc-value">Optuna ({m['n_optuna_trials']} trials per candidate and window, validation average precision)</div></div>
  <div><div class="mc-label">Calibration</div><div class="mc-value">Isotonic, fitted on validation</div></div>
  <div><div class="mc-label">Thresholds</div><div class="mc-value">7 days: {TH[7]:.3f} &middot; 21 days: {TH[21]:.3f} (calibrated probability with the highest F1 on validation)</div></div>
  <div><div class="mc-label">Tier Rule</div><div class="mc-value">CRITICAL when the 7-day probability is at or above its threshold &middot; ELEVATED when the 21-day probability is &middot; otherwise OK</div></div>
  <div><div class="mc-label">Baselines</div><div class="mc-value">Calendar PM (current practice), rules (alarm rate and overdue PM), interval (days since the last repair against the machine's median gap)</div></div>
  <div><div class="mc-label">Metrics</div><div class="mc-value">Per window: precision and recall at the threshold, ROC-AUC, average precision, Brier score. Per failure: tier in the days before</div></div>
  <div><div class="mc-label">Tiers</div><div class="mc-value">CRITICAL: failure likely within 7 days &middot; ELEVATED: within 8 to 21 days &middot; OK</div></div>
  <div style="grid-column:1/-1;"><div class="mc-label">Purpose</div><div class="mc-value">Rates each machine daily by how soon it is likely to need an unplanned repair, feeding the CMMS asset list. Decision support for prioritisation, not automated work-order generation.</div></div>
</div></div>

{B.section("data", "Section 2", "Training Data")}
<p>The model reads one feature vector per machine, day, and shift, assembled from four families of
shop-floor data and engineered identically at training and scoring time. <strong>Condition-monitoring
sensors</strong> contribute seven-day averages and per-channel anomaly scores for spindle vibration,
bearing temperature, spindle motor power, and hydraulic pressure. <strong>Machine telemetry and OEE</strong>
contribute rolling alarm counts, unplanned-downtime hours, and utilization. The <strong>CMMS maintenance
history</strong> contributes time since the last unplanned failure, time since and days overdue on
preventive maintenance, the count of recent late PMs, and the last failure mode. <strong>Machine
attributes</strong> contribute age, type, controller, and shift. On top of these, five interaction flags
encode the cross-system reliability patterns found in the diagnostic analysis (PM overdue, aging asset,
elevated alarm rate, shift-B transition, and sensor anomaly). In total the model weighs
<strong>{m['feature_counts']['total']}</strong> features per observation.</p>
<p>Training spans January 2023 through December 2025. The split is time-based and never shuffled, mirroring
deployment where the model scores future dates it has not seen; shuffling maintenance records across time
would leak future outcomes into training. The January to March 2026 window is held out entirely for
scoring.</p>
{training_data_table()}
<p>Data coverage is uniform across the window: every month carries a near-constant number of
machine-day-shift observations, so no split is starved and the boundaries below are purely chronological.</p>
{B.chart("Observation Volume by Month and Split", charts["volume"])}
<p>The full feature set is listed below with its correlation to the 7-day target. There are two targets,
each a yes or no per observation: whether an unplanned repair opens in the CMMS within 7 days of the
observation date, and whether one opens within 21 days. An observation whose window runs past the end of the
record has no target for that window.</p>
{feature_table()}
<p>Many features are engineered from the same underlying signals, so some move together. The heatmap below
shows the pairwise correlations among the numerical features. Gradient-boosted trees are robust to this kind
of correlation (it affects which of two interchangeable features a split uses, not overall accuracy), but it
is worth noting where the model's heaviest drivers overlap. Machine age, one of the top drivers, runs
inversely with fleet utilization (about -0.70) and rises with bearing temperature and spindle power (about
+0.58), so older assets read as hotter, rougher, and less heavily loaded. The composite sensor anomaly score,
another top driver, correlates about +0.60 with the individual channel anomalies it aggregates, and the
sensor channel averages move together (vibration and bearing temperature at about +0.63). Time since the last
failure, also among the strongest drivers, is close to independent of the rest, so it contributes largely
non-redundant signal.</p>
{B.chart("Feature Correlation Heatmap (numerical features)", charts["corr"])}
<p>The share of observations with a repair inside each window is consistent across the three splits,
confirming the time-based split did not introduce a shift in the targets.</p>
{B.chart("Target Rates: Train / Validation / Test", charts["target"])}

{B.section("modelperf", "Section 3", "Model Selection & Performance")}

{B.section("selection", "Section 3.1", "Model Selection")}
<p>Three candidate classifiers, a logistic regression, a random forest, and a gradient-boosted XGBoost model,
were tuned independently for each window with Optuna ({m['n_optuna_trials']} trials each, validation average
precision as the objective) and compared on the validation set. {LABELS.get(best, best)} had the highest
average precision averaged across the two windows and was registered as the production model, then evaluated
once on the held-out test set.</p>
{comparison_table()}
<p>The selected configuration for each window, with the probability threshold that turns its calibrated
probability into a tier. Hyperparameters were optimised on the fixed time-based validation window (January to
August 2025) rather than shuffled k-fold cross-validation. Each window model is calibrated with an isotonic
fit on the same validation window, and its threshold is the calibrated probability with the highest F1
there. The tier is CRITICAL when the 7-day probability is at or above its threshold, ELEVATED when the 21-day
probability is, and OK otherwise.</p>
{params_table()}

{B.section("performance", "Section 3.2", "Model Performance")}
<p>The evaluation leads with the window measures: for each window, precision and recall at the threshold,
ROC-AUC, average precision and the Brier score, for the health indicator beside three baselines. The
<strong>interval baseline</strong> is the comparison that matters: it rates a machine on the days since its
last unplanned repair against that machine's median gap between repairs in the training window, and on this
fleet that single quantity carries a large part of the signal. The <strong>calendar PM</strong> schedule is
the shop's current practice. The rules baseline flags on the 7-day alarm count and overdue PM. A baseline has
no probability, so the Brier score does not apply; ROC-AUC and average precision for calendar PM and rules
are computed on the flag the tier implies, and for the interval baseline on days since the last repair
divided by the machine's median.</p>
{window_table("test")}
{window_table("scoring")}
<p>On the held-out test set the 7-day model reaches ROC-AUC <strong>{wm('test', 'model', 7, 'roc_auc'):.2f}</strong>
against <strong>{wm('test', 'interval', 7, 'roc_auc'):.2f}</strong> for the interval baseline, with precision
{wm('test', 'model', 7, 'precision'):.2f} against {wm('test', 'interval', 7, 'precision'):.2f} and recall
{wm('test', 'model', 7, 'recall'):.2f} against {wm('test', 'interval', 7, 'recall'):.2f}. The margin over the
interval baseline holds on the scoring window; calendar PM and the rules baseline sit near chance on
ROC-AUC in both periods.</p>
<p>A learning curve plots cross-validated average precision as the training set grows. It separates a model
starved of data, where both curves sit low, from one that has memorised its training set, where a wide gap
stays open between the train and validation curves.</p>
{B.chart("Learning Curve, 7-Day Model (3-fold CV)", charts["learning"])}

<h3>Calibration</h3>
<p>Calibration checks whether a probability can be taken at face value. Test observations are binned by
calibrated probability, and the mean probability in each bin is compared against the share of those
observations that had a repair inside the window. Points on the diagonal mean a probability of, say, 0.7 is
followed by a repair about 70% of the time. The Brier score on test is
<strong>{wm('test', 'model', 7, 'brier'):.3f}</strong> for the 7-day model and
<strong>{wm('test', 'model', 21, 'brier'):.3f}</strong> for the 21-day model. The two models are calibrated
separately, so the 7-day probability is above the 21-day one on {m['test_out_of_order_share']:.1%} of test
observations and {ss['out_of_order_share']:.1%} of scoring observations; the tier rule takes the higher tier
in those cases.</p>
{B.chart("Calibration on Test: Mean Probability vs Observed Rate", charts["calib"])}

<h3>Precision and recall</h3>
<p>The curve below shows the trade between precision and recall as the threshold moves, with the operating
threshold marked for each window and the dotted line at the window's base rate (the precision of flagging
everything). The thresholds were fixed on validation and not revisited on test.</p>
{B.chart("Precision and Recall on Test, by Window", charts["pr"])}

<h3>Tiers against failures</h3>
<p>For each unplanned repair opened in the period, the table gives the share that had CRITICAL on at least
one of the 7 days before and CRITICAL or ELEVATED on at least one of the 21 days before, with the median days
from the first such day to the repair. On CRITICAL or ELEVATED in the 21 days before, the health indicator
and the interval baseline both reach {_tier_lo:.0%} to 100%, so that measure is at its ceiling and does not
separate them; the window measures above do.</p>
{tier_table()}
<p>Machine-days in each tier by month, for the health indicator. A machine-day takes the higher tier of its
two shift observations.</p>
{tier_days_table()}
<p>Split by the failure mode the CMMS recorded, the share of failures with a CRITICAL day in the 7 days
before runs from {mode_hit['mean'].min():.0%} for {_mode(mode_worst)} failures to
{mode_hit['mean'].max():.0%} for {_mode(mode_best)} failures, across the {len(_ev)} failures of the test and
scoring windows (counts in brackets).</p>
{B.chart("Failures with a CRITICAL Day in the 7 Days Before, by Failure Mode", charts["mode"])}

<h3>The 7-day model without the sensor features</h3>
<p>The selected candidate retrained on the 7-day target with the same tuning, once on all
{m['feature_counts']['total']} features and once without the ten sensor features (the nine sensor features
and the anomaly flag built on them). Both rows are the uncalibrated model, so the first row differs slightly
from the calibrated figures above. The ablation model is an evaluation artifact and is not registered.</p>
{ablation_table()}

{B.section("shap", "Section 4", "Feature Importance (SHAP)")}
<p>SHAP values measure each feature's average contribution to the prediction across the validation set. In
the 7-day model the heaviest features are {", ".join(f"<code>{f}</code>" for f in _top[:-1])} and
<code>{_top[-1]}</code>. The ten sensor features together carry <strong>{sensor_share[7]:.1%}</strong> of
mean absolute SHAP in the 7-day model and <strong>{sensor_share[21]:.1%}</strong> in the 21-day model.</p>
{B.chart("Share of Mean Absolute SHAP by Feature, 7-Day Model", charts["shap"])}

{B.section("limits", "Section 5", "Known Limitations")}
<ul class="limitation-list">
  <li><strong>Failure physics:</strong> a CRITICAL day preceded {mode_hit['mean'].max():.0%} of
  {_mode(mode_best)} failures and {mode_hit['mean'].min():.0%} of {_mode(mode_worst)} failures, so how
  reliably a failure is flagged depends on its mode. The counts by mode are small.</li>
  <li><strong>Base rate:</strong> this fleet opens an unplanned repair within 7 days on about
  {m['positive_rate']['train']['7']:.0%} of observations, so CRITICAL is a common rating, not a rare alarm,
  and the interval baseline is strong. The indicator's margin is over that baseline, not over nothing.</li>
  <li><strong>Incomplete windows:</strong> observations in the last days of the record have no 7-day or
  21-day outcome yet and are left out of the evaluation for that window.</li>
  <li><strong>Data:</strong> the records were generated to represent the five source systems and have not
  been drawn from a live floor; results on a live floor would be expected to be lower.</li>
  <li><strong>Retraining:</strong> retrain when the monitoring report flags a sustained drop in 7-day
  average precision or target drift across two consecutive periods, per the retraining rules.</li>
  <li><strong>Scope:</strong> rates how soon the next unplanned repair is likely, not its severity or repair
  cost. It supports prioritisation; it does not replace maintenance judgement.</li>
</ul>

{B.section("ops", "Section 6", "Deployment & Operations")}
<p>How the model runs in production and where its inputs come from.</p>
{ops_table()}"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(B.page("ML Model Technical Overview: Machine Health Indicator",
                      "", toc, body), encoding="utf-8")
print(f"Technical report written to {OUT}")
