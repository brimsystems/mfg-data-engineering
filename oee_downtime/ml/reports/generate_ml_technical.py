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
SOURCES = ["model", "rules", "calendar_pm"]
SOURCE_NAME = {"model": "Health indicator", "rules": "Rules baseline",
               "calendar_pm": "Calendar PM (the shop's routine PM)"}
MODEL_KIND = {"xgboost": "gradient-boosted classifiers", "random_forest": "random forest classifiers",
              "logistic_regression": "logistic regression classifiers"}
INTERVAL_FEATURES = ["share_of_interval_elapsed", "days_to_next_interval_service"]
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
ref   = pd.read_csv(MODELS / "reference_interval_features.csv")
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
# What followed each rated machine-day, in three exclusive parts (an unplanned
# repair; an interval service and no repair; neither), and the failures warned,
# from the same marts the model overview reads. At 7 days the rating counted is
# CRITICAL; at 21 days it is CRITICAL or ELEVATED.
_th = _dv.execute("select * from mart_ml__tier_history where in_scoring_quarter or in_test_period").df()
_fl = {"test": _dv.execute("select * from mart_ml__test_failures").df(),
       "scoring": _dv.execute("select * from mart_ml__scoring_quarter_failures").df()}
_dv.close()
_RATING = {"model": "indicator_rating", "rules": "rules_rating", "calendar_pm": "calendar_pm_rating"}
_WARN = {"model": "warned_before", "rules": "rules_warned_before", "calendar_pm": "calendar_pm_warned_before"}
_PERIOD = {"test": "in_test_period", "scoring": "in_scoring_quarter"}


def partition(split, source, window):
    d = _th[_th[_PERIOD[split]]]
    f = d[d[_RATING[source]].isin(["CRITICAL"] if window == 7 else ["CRITICAL", "ELEVATED"])]
    r = f[f"unplanned_repair_within_{window}d"].values.astype(bool); sv = f[f"interval_service_within_{window}d"].values.astype(bool)
    out = {"days": int(len(f)), "repair": int(r.sum()), "service": int((sv & ~r).sum()), "neither": int((~r & ~sv).sum())}
    assert out["repair"] + out["service"] + out["neither"] == out["days"]
    return out


def warned(split, source, window):
    f = _fl[split]
    return int(f[_WARN[source] + ("" if window == 7 else "_21d")].sum()), int(len(f))


PART = {(sp, s, n): partition(sp, s, n) for sp in ("test", "scoring") for s in SOURCES for n in (7, 21)}
CHART_SOURCE = {"model": "Health indicator", "rules": "Rules baseline", "calendar_pm": "Calendar PM baseline"}


def chart_what_followed(window):
    """The model overview's chart of what followed each rated machine-day, from the shared chart function."""
    part = lambda sp, s: {"critical": PART[(sp, s, window)]["days"], "failure": PART[(sp, s, window)]["repair"],
                          "service": PART[(sp, s, window)]["service"], "neither": PART[(sp, s, window)]["neither"]}
    return B.chart_what_followed([(CHART_SOURCE[s], [("Test set", part("test", s)), ("Scoring quarter", part("scoring", s))]) for s in SOURCES])


# The reading paragraph of Section 3.2 rests on these; the run stops if the record stops supporting it.
_nshare = lambda sp, s, n: PART[(sp, s, n)]["neither"] / PART[(sp, s, n)]["days"]
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

# Distinct unplanned repairs behind each split's positive rows: the repair each
# positive row is counting down to.
_next_fail = {mid: np.sort(g["fday"].values) for mid, g in _mm.groupby("machine_id")}


def distinct_repairs(df, n):
    pos = df[df[TARGETS[n]] == 1]
    out = set()
    for mid, d in zip(pos["machine_id"], pd.to_datetime(pos["observation_date"])):
        f = _next_fail[mid]; i = np.searchsorted(f, np.datetime64(d), side="right")
        if i < len(f):
            out.add((mid, f[i]))
    return len(out)


interval_shap = {n: float(imp[(imp["window_days"] == n) & imp["feature"].isin(INTERVAL_FEATURES)]["shap_share"].sum()) for n in WINDOWS}
_num = train[[f for f in NUMERICAL_FEATURES if f in train.columns]].astype(float).corr()


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
    ax.set_ylabel("Share of observations (%)")
    ax.set_ylim(0, max(float(df[TARGETS[n]].mean()) for _, df, _ in splits for n in WINDOWS) * 130); ax.legend()
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
    """Each window: the indicator beside the two baselines."""
    rows = ""
    for n in WINDOWS:
        for s in SOURCES:
            bg = f' style="background:{B.BG_GREY};font-weight:700;"' if s == "model" else ""
            pt = PART[(split, s, n)]
            rows += (f'<tr{bg}><td>{n} days</td><td>{SOURCE_NAME[s]}</td>'
                     + "".join(f'<td style="text-align:right;">{_fmt(wm(split, s, n, c))}</td>'
                               for c in ("precision", "recall", "roc_auc", "average_precision", "brier"))
                     + f'<td style="text-align:right;">{wm(split, s, n, "flagged_share"):.1%}</td>'
                     + f'<td style="text-align:right;">{pt["days"]:,}</td>'
                     + "".join(f'<td style="text-align:right;white-space:nowrap;">{pt[k]} ({pt[k] / pt["days"]:.0%})</td>'
                               for k in ("repair", "service", "neither")) + '</tr>')
    n7, n21 = (int(wm(split, "model", n, "rows")) for n in WINDOWS)
    head = "".join(f'<th style="text-align:right;">{h}</th>' for h in
                   ("Precision", "Recall", "ROC-AUC", "Average precision", "Brier", "Share flagged",
                    "Rated machine-days", "Followed by a repair", "By a service", "By neither"))
    return (f'<table class="data-table"><thead><tr><th>Window</th><th>Source</th>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'<p style="font-size:13px;color:{MED_GREY};margin-top:-6px;">{SPLIT_NAME[split]}: {n7:,} observations at 7 days '
            f'({wm(split, "model", 7, "positive_rate"):.1%} positive), {n21:,} at 21 days '
            f'({wm(split, "model", 21, "positive_rate"):.1%} positive). Precision to share flagged are measured on '
            f'machine-shift observations. The last four columns count machine-days: those rated CRITICAL at 7 days and '
            f'CRITICAL or ELEVATED at 21 days, and what followed each within the window, in three exclusive parts.</p>')


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
    n_all = int(abl[abl["model"] == "all features"]["features"].iloc[0])
    n_without = int(abl[abl["model"] == "without sensor features"]["features"].iloc[0])
    spec = [(f"7-day model, all {n_all} features", lambda sp, c: a.loc[("all features", sp), c]),
            (f"7-day model, without the {n_all - n_without} sensor features", lambda sp, c: a.loc[("without sensor features", sp), c])]
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
         f"Two {MODEL_KIND.get(best, 'classifiers')} over {m['feature_counts']['total']} features; the full-fleet "
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

    def pos(df, n):
        return f"{int((df[TARGETS[n]] == 1).sum()):,} rows, {distinct_repairs(df, n)} repairs"
    rows = [["Train", "Jan 2023 to Dec 2024", f"{m['split_sizes']['train']:,}", rate(train, 7), pos(train, 7), rate(train, 21), pos(train, 21)],
            ["Validation", "Jan to Aug 2025", f"{m['split_sizes']['validation']:,}", rate(val, 7), pos(val, 7), rate(val, 21), pos(val, 21)],
            ["Test", "Sep to Dec 2025", f"{m['split_sizes']['test']:,}", rate(test, 7), pos(test, 7), rate(test, 21), pos(test, 21)],
            ["Scoring (held out)", "Jan to Mar 2026", f"{ss['rows_scored']:,}",
             f"{wm('scoring', 'model', 7, 'positive_rate'):.1%}", "", f"{wm('scoring', 'model', 21, 'positive_rate'):.1%}", ""]]
    return B.data_table(["Split", "Window", "Observations", "Repair within 7 days", "Positives behind it",
                         "Repair within 21 days", "Positives behind it"], rows, right={2, 3, 5})


def reference_table():
    """The selected model with and without the two interval features."""
    rows = ""
    for r in ref.itertuples():
        sel = r.model.startswith("with ")
        bg = f' style="background:{B.BG_GREY};font-weight:700;"' if sel else ""
        rows += (f'<tr{bg}><td>{r.model.capitalize()}</td><td>{LABELS.get(r.selected_candidate, r.selected_candidate)}</td>'
                 f'<td style="text-align:right;">{int(r.features)}</td><td style="text-align:right;">{r.val_ap_mean:.3f}</td>'
                 f'<td style="text-align:right;">{r.test_auc_7d:.3f}</td><td style="text-align:right;">{r.test_precision_7d:.3f}</td>'
                 f'<td style="text-align:right;">{r.test_recall_7d:.3f}</td><td style="text-align:right;">{r.test_auc_21d:.3f}</td>'
                 f'<td style="text-align:right;">{r.test_out_of_order_share:.1%}</td>'
                 f'<td style="text-align:right;">{int(r.warned_before_test_and_scoring)} of {int(r.failures_test_and_scoring)}</td>'
                 f'<td style="text-align:right;">{int(r.critical_machine_days_test_and_scoring)}</td></tr>')
    head = "".join(f'<th style="text-align:right;">{h}</th>' for h in
                   ("Features", "Val AP, mean", "Test ROC-AUC, 7 days", "Test precision, 7 days", "Test recall, 7 days",
                    "Test ROC-AUC, 21 days", "Windows out of order, test", "Failures warned before, test and scoring",
                    "CRITICAL machine-days, test and scoring"))
    return (f'<table class="data-table"><thead><tr><th>Feature set</th><th>Candidate selected</th>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


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
    exact = pd.DataFrame(m["models"]).set_index("model_type")
    c2 = comp.assign(val_ap_7d=comp["model_type"].map(exact["val_ap_7d"]), val_ap_21d=comp["model_type"].map(exact["val_ap_21d"]),
                     val_ap_mean=comp["model_type"].map(exact["val_ap_mean"]))
    for r in c2.sort_values("val_ap_mean", ascending=False).itertuples():
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


for _sp in ("test", "scoring"):
    assert all(wm(_sp, "model", 7, "roc_auc") > wm(_sp, b, 7, "roc_auc") and _nshare(_sp, "model", 7) < _nshare(_sp, b, 7) for b in ("rules", "calendar_pm"))
assert 0 < wm("test", "model", 21, "roc_auc") - wm("test", "rules", 21, "roc_auc") < 0.15
assert warned("scoring", "rules", 21)[0] > warned("scoring", "model", 21)[0]
assert PART[("scoring", "rules", 21)]["days"] > 2 * PART[("scoring", "model", 21)]["days"]

# Section 3.2 opens with the accuracy and validation section of the model overview, as that report builds it
# (run generate_model_overview.py first; the flow does).
_acc = Path(__file__).resolve().parent / "assets" / "accuracy_validation.html"
if not _acc.exists():
    raise SystemExit("accuracy_validation.html is missing: run generate_model_overview.py before the technical report")
ACCURACY_HTML = _acc.read_text(encoding="utf-8")

charts = {"target": chart_target_rates(), "learning": chart_learning(), "calib": chart_calibration(),
          "pr": chart_precision_recall(), "mode": chart_hit_by_mode(), "shap": chart_shap(),
          "volume": chart_data_volume(), "corr": chart_corr_heatmap()}

_top = imp[imp["window_days"] == 7].head(4)["feature"].tolist()

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
  <div><div class="mc-label">Baselines</div><div class="mc-value">Rules (alarm rate and overdue calendar PM); calendar PM, the shop's routine PM. The repair-interval method is the shop's practice and is not a comparator</div></div>
  <div><div class="mc-label">Metrics</div><div class="mc-value">Per window: precision and recall at the threshold, ROC-AUC, average precision, Brier score. Per failure: tier in the days before</div></div>
  <div><div class="mc-label">Tiers</div><div class="mc-value">CRITICAL: failure likely within 7 days &middot; ELEVATED: within 8 to 21 days &middot; OK</div></div>
  <div style="grid-column:1/-1;"><div class="mc-label">Purpose</div><div class="mc-value">Rates each machine daily by how soon it is likely to need an unplanned repair, feeding the CMMS asset list beside the shop's repair-interval method and calendar PM. Decision support for prioritisation, not automated work-order generation.</div></div>
</div></div>

{B.section("data", "Section 2", "Training Data")}
<p>The model reads one feature vector per machine, day, and shift, assembled from four families of
shop-floor data and engineered identically at training and scoring time. <strong>Condition-monitoring
sensors</strong> contribute seven-day averages and per-channel anomaly scores for spindle vibration,
bearing temperature, spindle motor power, and hydraulic pressure. <strong>Machine telemetry and OEE</strong>
contribute rolling alarm counts, unplanned-downtime hours, and utilization. The <strong>CMMS maintenance
history</strong> contributes days since the last repair (an unplanned repair or an interval service), the
machine's place in its repair interval, time since and days overdue on the calendar PM, the count of recent
late PMs, and the failure mode of the last repair. <strong>Machine
attributes</strong> contribute age, type, controller, and shift. On top of these, five interaction flags
encode the cross-system reliability patterns found in the diagnostic analysis (PM overdue, aging asset,
elevated alarm rate, shift-B transition, and sensor anomaly). In total the model weighs
<strong>{m['feature_counts']['total']}</strong> features per observation.</p>
<p>Two of the features were added after the first retraining on this record:
<code>share_of_interval_elapsed</code> (days since the last repair over the machine's repair interval) and
<code>days_to_next_interval_service</code> (the interval less days since the last repair, floored at zero).
The shop services each machine at a set interval, so where a machine stands in that interval is information
the shop has, and the first retraining, without it, warned before few of the failures. They were added with
those results in view; Section 3.1 sets the two models side by side.</p>
<p>Training spans January 2023 through December 2025. The split is time-based and never shuffled, mirroring
deployment where the model scores future dates it has not seen; shuffling maintenance records across time
would leak future outcomes into training. The January to March 2026 window is held out entirely for
scoring.</p>
{training_data_table()}
<p>The positives are the scarce resource. Unplanned repairs are rare under the repair-interval method, so each
positive row is one of a small number of repairs seen from several days out: the table gives the rows and
the distinct repairs behind them. Calibration and the thresholds are fitted on the validation set.</p>
<p>Data coverage is uniform across the window: every month carries a near-constant number of
machine-day-shift observations, so no split is starved and the boundaries below are purely chronological.</p>
{B.chart("Observation Volume by Month and Split", charts["volume"])}
<p>The full feature set is listed below with its correlation to the 7-day target. There are two targets,
each a yes or no per observation: whether an unplanned repair opens in the CMMS within 7 days of the
observation date, and whether one opens within 21 days. An observation whose window runs past the end of the
record has no target for that window.</p>
{feature_table()}
<p>Many features are engineered from the same underlying signals, so some move together. The heatmap below
shows the pairwise correlations among the numerical features. Tree ensembles are robust to this kind of
correlation (it affects which of two interchangeable features a split uses, not overall accuracy), but it is
worth noting where the heaviest drivers overlap. Machine age runs inversely with fleet utilization
({_num.loc['machine_age_years', 'rolling_30d_utilization_rate']:+.2f}) and rises with bearing temperature
({_num.loc['machine_age_years', 'bearing_temp_7d_mean']:+.2f}) and spindle power
({_num.loc['machine_age_years', 'spindle_power_7d_mean']:+.2f}). The composite sensor anomaly score correlates
{_num.loc['sensor_anomaly_score', 'vibration_anomaly']:+.2f} with the vibration anomaly it aggregates, and
vibration and bearing temperature move together
({_num.loc['vibration_7d_mean', 'bearing_temp_7d_mean']:+.2f}). The two interval features are close to mirror
images of each other within a machine
({_num.loc['share_of_interval_elapsed', 'days_to_next_interval_service']:+.2f} across the fleet).</p>
{B.chart("Feature Correlation Heatmap (numerical features)", charts["corr"])}
<p>The share of observations with a repair inside each window is similar across the three splits
({min(float(d_[TARGETS[7]].mean()) for d_ in (train, val, test)):.1%} to
{max(float(d_[TARGETS[7]].mean()) for d_ in (train, val, test)):.1%} at 7 days).</p>
{B.chart("Target Rates: Train / Validation / Test", charts["target"])}

{B.section("modelperf", "Section 3", "Model Selection & Performance")}

{B.section("selection", "Section 3.1", "Model Selection")}
<p>Three candidate classifiers, a logistic regression, a random forest, and a gradient-boosted XGBoost model,
were tuned independently for each window with Optuna ({m['n_optuna_trials']} trials each, validation average
precision as the objective) and compared on the validation set. The {LABELS.get(best, best).lower()} had the
highest average precision averaged across the two windows and was registered as the production model, then
evaluated once on the held-out test set. The margin over the second candidate is narrow, and the selection
rule was applied as written.</p>
{comparison_table()}
<p>The same pipeline was first run without the two interval features. The table sets the two selected models
side by side. With the features the 7-day model ranks better and its recall rises; precision does not move,
so the gain comes with about three times as many CRITICAL machine-days. The two window models also disagree
more often.</p>
{reference_table()}
<p>The selected configuration for each window, with the probability threshold that turns its calibrated
probability into a tier. Hyperparameters were optimised on the fixed time-based validation window (January to
August 2025) rather than shuffled k-fold cross-validation. Each window model is calibrated with an isotonic
fit on the same validation window, and its threshold is the calibrated probability with the highest F1
there. The tier is CRITICAL when the 7-day probability is at or above its threshold, ELEVATED when the 21-day
probability is, and OK otherwise.</p>
{params_table()}

{B.section("performance", "Section 3.2", "Model Performance")}
{ACCURACY_HTML}
<h3>Learning Curve</h3>
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
<strong>{wm('test', 'model', 21, 'brier'):.3f}</strong> for the 21-day model. With positives this rare a
low Brier score mostly reflects the base rate. The two models are calibrated separately, and the 7-day
probability is above the 21-day one on <strong>{m['test_out_of_order_share']:.1%}</strong> of test
observations and {ss['out_of_order_share']:.1%} of scoring observations. A repair within 7 days is also a
repair within 21, so a well-ordered pair would never do this; the rate is a measure of how loosely the 21-day
model is fitted. The tier rule takes the higher tier in those cases.</p>
{B.chart("Calibration on Test: Mean Probability vs Observed Rate", charts["calib"])}

<h3>Precision and recall</h3>
<p>The curve below shows the trade between precision and recall as the threshold moves, with the operating
threshold marked for each window and the dotted line at the window's base rate (the precision of flagging
everything). The thresholds were fixed on validation and not revisited on test.</p>
{B.chart("Precision and Recall on Test, by Window", charts["pr"])}

<h3>Tiers against failures</h3>
<p>For each unplanned repair opened in the period, the table gives the share that had CRITICAL on at least
one of the 7 days before and CRITICAL or ELEVATED on at least one of the 21 days before, with the median days
from the first such day to the repair. The counts are small: {int(tiers['test'].set_index('source').loc['model', 'failures'])}
failures on test and {int(tiers['scoring'].set_index('source').loc['model', 'failures'])} on the scoring
window.</p>
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
and the anomaly flag built on them). Both rows are the uncalibrated model retuned for this comparison, so the
first row differs from the production figures above. The ablation model is an evaluation artifact and is not
registered.</p>
{ablation_table()}

{B.section("shap", "Section 4", "Feature Importance (SHAP)")}
<p>SHAP values measure each feature's average contribution to the prediction across the validation set. In
the 7-day model the heaviest features are {", ".join(f"<code>{f}</code>" for f in _top[:-1])} and
<code>{_top[-1]}</code>. The ten sensor features together carry <strong>{sensor_share[7]:.1%}</strong> of
mean absolute SHAP in the 7-day model and <strong>{sensor_share[21]:.1%}</strong> in the 21-day model. The
two interval features carry {interval_shap[7]:.1%} in the 7-day model and {interval_shap[21]:.1%} in the
21-day model.</p>
{B.chart("Share of Mean Absolute SHAP by Feature, 7-Day Model", charts["shap"])}

{B.section("limits", "Section 5", "Known Limitations")}
<ul class="limitation-list">
  <li><strong>Failure physics:</strong> a CRITICAL day preceded {mode_hit['mean'].max():.0%} of
  {_mode(mode_best)} failures and {mode_hit['mean'].min():.0%} of {_mode(mode_worst)} failures, so how
  reliably a failure is flagged depends on its mode. The counts by mode are small.</li>
  <li><strong>Base rate and precision:</strong> this fleet opens an unplanned repair within 7 days on about
  {m['positive_rate']['train']['7']:.0%} of observations. About one flagged observation in five is followed
  by one. Most CRITICAL days fall in the week before an interval service that was already due, because wear
  reads the same on the sensors whichever of the two ends it.</li>
  <li><strong>Precision under the method:</strong> Precision against unplanned repairs understates the indicator
  where the method resolved the warning; the partition of CRITICAL days is the measure to read for false
  alarms.</li>
  <li><strong>Few positives:</strong> {distinct_repairs(train, 7)} distinct unplanned repairs stand behind the
  7-day target in training and {distinct_repairs(val, 7)} in validation, where calibration and the thresholds
  are fitted. Differences of two or three failures between sources are within what another period could
  reverse.</li>
  <li><strong>The 21-day model:</strong> test ROC-AUC {wm('test', 'model', 21, 'roc_auc'):.2f}, and the two
  window probabilities out of order on {m['test_out_of_order_share']:.1%} of test observations. The ELEVATED
  tier is a loose signal.</li>
  <li><strong>Features added with results in view:</strong> the two interval features were added after the
  first retraining on this record and its evaluation. The test set had been read once by then.</li>
  <li><strong>Incomplete windows:</strong> observations in the last days of the record have no 7-day or
  21-day outcome yet and are left out of the evaluation for that window.</li>
  <li><strong>Data:</strong> the model was trained and evaluated on one shop's records over 39 months; it
  has not been validated on other equipment or other shops.</li>
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
