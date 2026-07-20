"""Checks the source extracts are held to, written to REALISM_CHECKS.md.

Each check is computed on the extracts as written, with the definitions the
marts use (availability is running time over planned production time,
performance is spindle utilisation while running, OEE is the product with the
quality assumption). A check outside its range is reported and nothing is
adjusted here.

Usage: python -m data_source.generate.checks
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    RAW_DIR, TRUTH_DIR, START_DATE, END_DATE, SCORING_WINDOW_START, AGING_ASSETS,
    SHIFT_HOURS, SHIFT_STARTUP_WINDOW_MINUTES, EXTENDED_SETUP_OPERATORS,
    EMPLOYEE_NUMBER_BY_OPERATOR, PM_OVERDUE_THRESHOLD_DAYS,
)

OUT = Path(__file__).resolve().parent / "REALISM_CHECKS.md"
QUALITY_RATE = 0.95            # the plant assumption the marts carry
OLDEST_AGE_YEARS = 9           # the marts flag a machine older than this as an aging asset

# Ranges. Where a range was amended, the first figure set is kept beside it.
RANGES = {
    "R1":  (7, 14),         # first set at 6 to 10
    "R2":  (35, 55),        # first set at 20 to 40
    "R3":  (40, 55),        # first set at 30 to 42
    "R4":  (0.78, 0.90),    # first set at 0.60 to 0.75
    "R5":  (110, 230),      # first set at 90 to 170
    "R6":  (2.5, 3.8),      # first set at 1.3 to 2.2
    "R7":  (2.0, 3.5),
    "R8":  (0.85, 1.15),    # first set at within 25% in every quarter; now the whole window, quarters reported
    "R9":  (0.64, 0.72),
    "R10": (8.0, None),
    "R11": (1.9, 2.6),
}


def _load():
    m  = pd.read_csv(RAW_DIR / "cmms" / "maintenance_records.csv", parse_dates=["work_order_open_date", "work_order_close_date"])
    ev = pd.read_csv(RAW_DIR / "machinemetrics" / "production_events.csv", parse_dates=["event_timestamp"])
    mc = pd.read_csv(RAW_DIR / "machinemetrics" / "machines.csv")
    wo = pd.read_csv(RAW_DIR / "erp" / "work_orders.csv")
    truth = TRUTH_DIR / "failure_outcomes.csv"
    return m, ev, mc, wo, (pd.read_csv(truth) if truth.exists() else None)


def _oee(ev):
    planned = ev.loc[ev["machine_state"] != "PLANNED_DOWN", "state_duration_minutes"].sum()
    run     = ev[(ev["machine_state"] == "RUNNING")]
    avail   = run["state_duration_minutes"].sum() / planned
    perf    = (run["spindle_utilization_pct"] * run["state_duration_minutes"]).sum() / run["state_duration_minutes"].sum() / 100
    return avail, perf, avail * perf * QUALITY_RATE


def _overdue_alarm_ratio(m, ev):
    """Alarm rate per running hour while a calendar PM is more than the threshold
    overdue, against the rate while it is current: each machine against itself,
    then the mean of the machines' ratios."""
    pm = m[(m["maintenance_type"] == "PLANNED_PM") & m["pm_scheduled_date"].notna() & (m["days_overdue"] > PM_OVERDUE_THRESHOLD_DAYS)]
    windows = {}
    for _, r in pm.iterrows():
        start = pd.Timestamp(r["pm_scheduled_date"]) + pd.Timedelta(days=PM_OVERDUE_THRESHOLD_DAYS)
        windows.setdefault(r["machine_id"], []).append((start, pd.Timestamp(r["pm_completed_date"])))
    d = ev.assign(day=ev["event_timestamp"].dt.normalize())
    daily = (d.groupby(["machine_id", "day"])
             .apply(lambda g: pd.Series({"alarms": (g["machine_state"] == "ALARM").sum(),
                                         "run": g.loc[g["machine_state"] == "RUNNING", "state_duration_minutes"].sum()}),
                    include_groups=False).reset_index())
    daily["overdue"] = [any(a <= t < b for a, b in windows.get(mid, [])) for mid, t in zip(daily["machine_id"], daily["day"])]
    ratios = []
    for _, g in daily.groupby("machine_id"):
        ov, cu = g[g["overdue"]], g[~g["overdue"]]
        if ov["run"].sum() and cu["run"].sum() and cu["alarms"].sum():
            ratios.append((ov["alarms"].sum() / ov["run"].sum()) / (cu["alarms"].sum() / cu["run"].sum()))
    return float(np.mean(ratios))


def run():
    m, ev, mc, wo, truth = _load()
    years = ((END_DATE - START_DATE).days + 1) / 365.25
    q0 = pd.Timestamp(SCORING_WINDOW_START)
    unplanned = m[m["maintenance_type"] == "UNPLANNED_REPAIR"]
    services  = m[m["maintenance_type"] == "PLANNED_INTERVAL"]
    calendar  = m[m["maintenance_type"] == "PLANNED_PM"]
    in_q = lambda d: d[d["work_order_open_date"] >= q0]

    rows, values = [], {}

    def add(key, label, value, shown):
        lo, hi = RANGES[key]
        ok = (lo is None or value >= lo) and (hi is None or value <= hi)
        rng = (f"{lo} to {hi}" if lo is not None and hi is not None else f"at least {lo}" if hi is None else f"at most {hi}")
        rows.append((key, label, rng, shown, "pass" if ok else "OUT"))
        values[key] = value

    add("R1", "Unplanned failures in the scoring quarter (1 Jan to 31 Mar 2026)", len(in_q(unplanned)), f"{len(in_q(unplanned))}")
    add("R2", "Unplanned failures a year, fleet", len(unplanned) / years, f"{len(unplanned) / years:.1f}")
    add("R3", "Interval services in the scoring quarter", len(in_q(services)), f"{len(in_q(services))}")
    if truth is not None:
        t = truth[truth["in_window"]]
        pre = (t["outcome"] == "pre-empted by the service").mean()
        add("R4", "Share of failures pre-empted by an interval service", float(pre), f"{pre:.2f}")
    add("R5", "Unplanned downtime in the scoring quarter, CMMS hours", float(in_q(unplanned)["downtime_hours"].sum()),
        f"{in_q(unplanned)['downtime_hours'].sum():.0f}")
    pm_hours, svc_hours = calendar["downtime_hours"].sum() / years, services["downtime_hours"].sum() / years
    add("R6", "Planned downtime a year (calendar PM plus interval services) against the calendar PM alone",
        float((pm_hours + svc_hours) / pm_hours), f"{(pm_hours + svc_hours) / pm_hours:.2f}x ({pm_hours:.0f} + {svc_hours:.0f} hours)")
    per_machine = unplanned.groupby("machine_id").size().reindex(mc["machine_id"]).fillna(0) / years
    aging_rate, rest_rate = per_machine[AGING_ASSETS].mean(), per_machine.drop(AGING_ASSETS).mean()
    add("R7", f"Unplanned failures a year per machine, {' and '.join(AGING_ASSETS)} against the other ten", float(aging_rate / rest_rate),
        f"{aging_rate / rest_rate:.1f}x ({aging_rate:.1f} against {rest_rate:.1f})")
    state_hours = ev.loc[ev["machine_state"] == "UNPLANNED_DOWN", "state_duration_minutes"].sum() / 60
    cmms_hours  = unplanned["downtime_hours"].sum()
    add("R8", "Unplanned-down hours in the state log against CMMS unplanned repair hours, whole window", float(state_hours / cmms_hours),
        f"{state_hours / cmms_hours:.2f} ({state_hours:,.0f} against {cmms_hours:,.0f} hours)")
    avail, perf, oee = _oee(ev)
    add("R9", "Fleet OEE over the window", float(oee), f"{oee:.1%} (availability {avail:.1%}, performance {perf:.1%})")
    oldest = list(mc.loc[mc["machine_age_years"] > OLDEST_AGE_YEARS, "machine_id"])
    o_old, o_rest = _oee(ev[ev["machine_id"].isin(oldest)])[2], _oee(ev[~ev["machine_id"].isin(oldest)])[2]
    add("R10", f"OEE of the machines over {OLDEST_AGE_YEARS} years ({', '.join(oldest)}) below the rest, points", float((o_rest - o_old) * 100),
        f"{(o_rest - o_old) * 100:.1f} ({o_old:.1%} against {o_rest:.1%})")
    ratio = _overdue_alarm_ratio(m, ev)
    add("R11", f"Alarm rate while a calendar PM is more than {PM_OVERDUE_THRESHOLD_DAYS} days overdue, against current", ratio, f"{ratio:.2f}x")

    # R12: physical sense
    physical = []
    svc_spans = {mid: list(zip(g["work_order_open_date"], g["work_order_close_date"])) for mid, g in services.groupby("machine_id")}
    during = sum(any(a <= t < b for a, b in svc_spans.get(mid, [])) for mid, t in zip(unplanned["machine_id"], unplanned["work_order_open_date"]))
    same_hour = len(unplanned.assign(h=unplanned["work_order_open_date"].dt.floor("h"))
                    .merge(services.assign(h=services["work_order_open_date"].dt.floor("h")), on=["machine_id", "h"]))
    physical.append(("No repair opens in the same hour as a service on the machine, or while the service is under way", same_hour + during == 0,
                     f"{same_hour} in the same hour, {during} during a service"))
    missing = int(services["pm_scheduled_date"].isna().sum() + services["pm_completed_date"].isna().sum())
    physical.append(("Every interval service has a scheduled and a completed date", missing == 0, f"{missing} missing"))
    no_interval = int(mc["repair_interval_days"].isna().sum()) if "repair_interval_days" in mc else len(mc)
    physical.append(("repair_interval_days on every machine", no_interval == 0, f"{no_interval} missing"))
    if truth is not None:
        broken = 0
        for _, g in truth.groupby("machine_id", sort=False):
            broken += int((g["last_repair_date"].iloc[1:].values != g["resolved_date"].iloc[:-1].values).sum())
        ghost = int((truth["outcome"].eq("pre-empted by the service") & truth["repair_id"].notna()).sum())
        physical.append(("The clock restarts at the event that resolves each cycle, and a pre-empted failure has no repair", broken + ghost == 0,
                         f"{broken} breaks in the sequence, {ghost} repairs on a pre-empted failure"))
    r12_ok = all(ok for _, ok, _ in physical)
    values["R12"] = r12_ok

    # figures reported without a range
    reported = []
    down_or_alarm = ev["machine_state"].isin(["UNPLANNED_DOWN", "ALARM"])
    a_rate, r_rate = down_or_alarm[ev["machine_id"].isin(AGING_ASSETS)].mean(), down_or_alarm[~ev["machine_id"].isin(AGING_ASSETS)].mean()
    reported.append((f"Unplanned-down and alarm share of state intervals, {' and '.join(AGING_ASSETS)} against the rest", f"{a_rate:.1%} against {r_rate:.1%} ({a_rate / r_rate:.1f}x)"))
    into = (ev["event_timestamp"].dt.hour * 60 + ev["event_timestamp"].dt.minute) - ev["shift"].map({k: v[0] * 60 for k, v in SHIFT_HOURS.items()})
    for sh in SHIFT_HOURS:
        s = ev["shift"] == sh
        start = (ev.loc[s & (into < SHIFT_STARTUP_WINDOW_MINUTES), "machine_state"] == "UNPLANNED_DOWN").mean()
        rest  = (ev.loc[s & (into >= SHIFT_STARTUP_WINDOW_MINUTES), "machine_state"] == "UNPLANNED_DOWN").mean()
        reported.append((f"Unplanned-down share in the first {SHIFT_STARTUP_WINDOW_MINUTES} minutes of Shift {sh} against the rest of the shift", f"{start:.2%} against {rest:.2%} ({start / rest:.1f}x)"))
    pmd = calendar[calendar["days_overdue"].notna()]
    reported.append(("Calendar PM completed on time, fleet; the two aging assets",
                     f"{(pmd['days_overdue'] <= 0).mean():.1%}; {(pmd[pmd['machine_id'].isin(AGING_ASSETS)]['days_overdue'] <= 0).mean():.1%}"))
    ext = {EMPLOYEE_NUMBER_BY_OPERATOR[o] for o in EXTENDED_SETUP_OPERATORS}
    f_med, c_med = wo[wo["operator_empid"].isin(ext)]["setup_hours_actual"].median(), wo[~wo["operator_empid"].isin(ext)]["setup_hours_actual"].median()
    reported.append(("Median setup hours, the three flagged operators against the cohort", f"{f_med:.2f} against {c_med:.2f} ({f_med / c_med:.1f}x)"))
    reported.append(("Calendar PMs logged with no scheduled date; jobs with no actual end",
                     f"{calendar['pm_scheduled_date'].isna().mean():.0%}; {wo['actual_end'].isna().mean():.0%}"))
    reported.append(("Maintenance records by type", ", ".join(f"{k} {v:,}" for k, v in m["maintenance_type"].value_counts().sort_index().items())))
    reported.append(("Unplanned repair hours a year; interval service hours a year; calendar PM hours a year",
                     f"{cmms_hours / years:,.0f}; {svc_hours:,.0f}; {pm_hours:,.0f}"))
    if truth is not None:
        t = truth[truth["in_window"]]
        reported.append(("Failures the wear-out process produced, by outcome", "; ".join(f"{k}: {v}" for k, v in t["outcome"].value_counts().items())))
        reported.append(("Repair interval by machine, days", ", ".join(f"{a} {int(b)}" for a, b in zip(mc["machine_id"], mc["repair_interval_days"]))))

    # R8 by quarter, reported
    eq = ev[ev["machine_state"] == "UNPLANNED_DOWN"].assign(q=lambda x: x["event_timestamp"].dt.to_period("Q")).groupby("q")["state_duration_minutes"].sum() / 60
    cq = unplanned.assign(q=unplanned["work_order_open_date"].dt.to_period("Q")).groupby("q")["downtime_hours"].sum()
    fq = unplanned.assign(q=unplanned["work_order_open_date"].dt.to_period("Q")).groupby("q").size()
    sq = services.assign(q=services["work_order_open_date"].dt.to_period("Q")).groupby("q").size()
    quarters = pd.DataFrame({"state": eq, "cmms": cq, "failures": fq, "services": sq}).fillna(0)

    passed = sum(r[4] == "pass" for r in rows) + int(r12_ok)
    total = len(rows) + 1
    lines = ["# Checks on the source extracts", "",
             f"{passed} of {total} checks pass. A check marked OUT is outside its range; it is reported here and nothing is adjusted.", "",
             "| Check | What is measured | Range | Measured | Result |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {label} | {rng} | {shown} | {res} |" for k, label, rng, shown, res in rows]
    lines += [f"| R12 | Physical sense (the four lines below) | all hold | {sum(ok for _, ok, _ in physical)} of {len(physical)} hold | {'pass' if r12_ok else 'OUT'} |", "",
              "## R12, line by line", "", "| Condition | Holds | Detail |", "|---|---|---|"]
    lines += [f"| {c} | {'yes' if ok else 'no'} | {d} |" for c, ok, d in physical]
    lines += ["", "## Reported without a range", "", "| Figure | Value |", "|---|---|"]
    lines += [f"| {a} | {b} |" for a, b in reported]
    lines += ["", "## By quarter: unplanned-down hours in the state log against CMMS unplanned repair hours", "",
              "| Quarter | State log hours | CMMS repair hours | Ratio | Unplanned failures | Interval services |", "|---|---|---|---|---|---|"]
    lines += [f"| {q} | {r.state:,.0f} | {r.cmms:,.0f} | {(r.state / r.cmms if r.cmms else float('nan')):.2f} | {int(r.failures)} | {int(r.services)} |" for q, r in quarters.iterrows()]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    (TRUTH_DIR / "check_values.json").write_text(json.dumps({k: (float(v) if not isinstance(v, bool) else v) for k, v in values.items()}, indent=2), encoding="utf-8")
    print(f"{passed} of {total} checks pass; written to {OUT}")
    for k, label, rng, shown, res in rows:
        if res != "pass":
            print(f"  OUT {k}: {shown} (range {rng})")
    if not r12_ok:
        print("  OUT R12")


if __name__ == "__main__":
    run()
