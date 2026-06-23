"""
The numbers behind the diagnostic report, computed from the marts.

Definitions (the same in the report, the dashboard and the pipeline):
  Defect rate   quantity failed over quantity inspected at final inspection,
                after deduplication, volume-weighted across a group.
  Multiplier    a group's rate over its comparison group's rate, with a 95%
                interval and p-value from a bootstrap over jobs (2,000 resamples).
  Scrap cost    material plus rework labor on the scrap and rework events,
                attributed to the work order.
  Savings       segment scrap cost x (current rate - target rate) / current rate,
                where the target is the comparison group's rate.

Usage: python findings.py [output.md]   writes every table as Markdown.
"""
import sys
import zlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DB_PATH = REPO / "data_source" / "defects_scrap.duckdb"

DEVIATION_BANDS = ["under 1%", "1 to 2%", "2 to 4%", "over 4%"]
EXPERIENCE_BANDS = ["under 50", "50 to 150", "150 to 300", "over 300"]
LOT_AGE_BANDS = ["under 60 days", "60 to 120 days", "over 120 days"]
BUSY_MONTHS = (3, 4, 10)


def load() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    d = con.execute("select * from mart_quality__defect_rates order by job_start, work_order_id").df()
    con.close()
    for c in ("production_month", "production_day", "job_start"):
        d[c] = pd.to_datetime(d[c])
    return d


# ── Rates and the score test ─────────────────────────────────────────────────
def rate(g: pd.DataFrame) -> float:
    n = g["quantity_inspected"].sum()
    return g["quantity_failed"].sum() / n if n else float("nan")


def code_rate(g: pd.DataFrame, codes) -> float:
    n = g["quantity_inspected"].sum()
    return g.loc[g["defect_code"].isin(codes), "quantity_failed"].sum() / n if n else float("nan")


N_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260331


def _resampled_rates(failed: np.ndarray, inspected: np.ndarray, rng) -> np.ndarray:
    """Rate of a group on each bootstrap resample of its jobs."""
    n = len(failed)
    out = np.empty(N_RESAMPLES)
    step = max(1, min(N_RESAMPLES, 4_000_000 // max(n, 1)))
    for start in range(0, N_RESAMPLES, step):
        k = min(step, N_RESAMPLES - start)
        weights = rng.multinomial(n, np.full(n, 1.0 / n), size=k)
        out[start:start + k] = (weights @ failed) / (weights @ inspected)
    return out


def ratio_test(group_failed, group_inspected, comparison_failed, comparison_inspected, seed_key=""):
    """Rate ratio with a 95% interval and a two-sided p-value from a bootstrap
    over jobs: each group's jobs are resampled with replacement, since pieces
    within a job share a setup, lot and operator."""
    ratio = (group_failed.sum() / group_inspected.sum()) / (comparison_failed.sum() / comparison_inspected.sum())
    rng = np.random.default_rng([BOOTSTRAP_SEED, zlib.crc32(seed_key.encode("utf8"))])
    ratios = (_resampled_rates(group_failed, group_inspected, rng)
              / _resampled_rates(comparison_failed, comparison_inspected, rng))
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    tail = min((ratios <= 1.0).mean(), (ratios >= 1.0).mean())
    return ratio, float(lo), float(hi), float(max(2 * tail, 1.0 / N_RESAMPLES))


def compare(label, group, against, comparison, codes=None) -> dict:
    """One row of a rate table. `codes` restricts the failed pieces to the jobs
    recorded under the given defect codes; all codes by default."""
    def arrays(g):
        failed = g["quantity_failed"].to_numpy(dtype=float)
        if codes:
            failed = np.where(g["defect_code"].isin(codes).to_numpy(), failed, 0.0)
        return failed, g["quantity_inspected"].to_numpy(dtype=float)
    f1, n1 = arrays(group)
    f0, n0 = arrays(comparison)
    ratio, lo, hi, p = ratio_test(f1, n1, f0, n0, seed_key=f"{label}|{against}")
    return {"Group": label, "Rate": f1.sum() / n1.sum(), "Jobs": len(group), "Pieces": int(n1.sum()),
            "Comparison": against, "Comparison rate": f0.sum() / n0.sum(), "Comparison jobs": len(comparison),
            "Multiplier": ratio, "95% low": lo, "95% high": hi, "p-value": p}


def codes_failed(codes):
    return lambda g: g.loc[g["defect_code"].isin(codes), "quantity_failed"].sum()


def savings(segment: pd.DataFrame, target_rate: float, years: float) -> dict:
    """Savings a year from bringing a segment to a target rate."""
    r, cost = rate(segment), segment["scrap_cost"].sum()
    return {"Segment jobs": len(segment), "Current rate": r, "Target rate": target_rate,
            "Segment scrap cost a year": cost / years,
            "Savings a year": cost * (r - target_rate) / r / years if r > target_rate else 0.0}


def by(d, col, order=None, failed=None) -> pd.DataFrame:
    """Rate, jobs and pieces by one dimension."""
    count = failed or (lambda g: g["quantity_failed"].sum())
    rows = [{col: k, "Jobs": len(g), "Pieces": int(g["quantity_inspected"].sum()),
             "Failed": int(count(g)), "Rate": count(g) / g["quantity_inspected"].sum()}
            for k, g in d.groupby(col, observed=True)]
    t = pd.DataFrame(rows)
    return t.set_index(col).loc[[k for k in order if k in set(t[col])]].reset_index() if order else t


def code_mix(d, split_col, labels=None) -> pd.DataFrame:
    """Share of failed pieces by defect code, one column per value of split_col."""
    t = (d[d["quantity_failed"] > 0].groupby([split_col, "defect_code"])["quantity_failed"].sum().unstack(split_col).fillna(0))
    t = t / t.sum()
    if labels:
        t = t.rename(columns=labels)
    return t.sort_values(t.columns[0], ascending=False).reset_index().rename(columns={"defect_code": "Defect code"})


def monthly(d, **series) -> pd.DataFrame:
    """Monthly series; each keyword is a column name and a function of the month's rows."""
    rows = []
    for m, g in d.groupby("production_month"):
        rows.append({"Month": m.strftime("%Y-%m")} | {k: f(g) for k, f in series.items()})
    return pd.DataFrame(rows)


def window_years(d: pd.DataFrame) -> float:
    """Length of the record in years: days in the window over 365.25."""
    return ((d["production_day"].max() - d["production_day"].min()).days + 1) / 365.25


# ── The tables ───────────────────────────────────────────────────────────────
def build() -> dict:
    d = load()
    months = sorted(d["production_month"].unique())
    years = window_years(d)
    ttm = d[d["production_month"].isin(months[-12:])]
    T = {}

    # Executive summary
    def totals(x, label):
        return {"Period": label, "Jobs": len(x), "Pieces inspected": int(x.quantity_inspected.sum()),
                "Pieces failed": int(x.quantity_failed.sum()), "Defect rate": rate(x),
                "Jobs with a defect": float(x.defect_flag.mean()), "Scrap and rework cost": x.scrap_cost.sum(),
                "Revenue": x.revenue.sum(), "Cost as a share of revenue": x.scrap_cost.sum() / x.revenue.sum()}
    T["0.1 Executive summary: volume, defects, rate and cost"] = pd.DataFrame([
        totals(d, f"{pd.Timestamp(months[0]):%b %Y} to {pd.Timestamp(months[-1]):%b %Y} ({len(months)} months)"),
        totals(ttm, f"Trailing twelve months ({pd.Timestamp(months[-12]):%b %Y} to {pd.Timestamp(months[-1]):%b %Y})")])
    T["0.2 Executive summary: monthly trend"] = monthly(
        d, Jobs=len, **{"Pieces failed": lambda g: int(g.quantity_failed.sum()), "Defect rate": rate,
                        "Scrap and rework cost": lambda g: g.scrap_cost.sum()})

    # The shop's own view
    known = d[d["supplier"].notna()]
    T["0.3 The shop's own view: defect rate by supplier (all jobs with a scanned lot)"] = by(known, "supplier")
    T["0.4 The shop's own view: defect rate by part complexity"] = by(d, "complexity", ["Low", "Medium", "High"])
    T["0.5 The shop's own view: defect rate by shift"] = by(d[d.shift_code.notna()], "shift_code")
    sup_c, sup_o = known[known.supplier == "Supplier C"], known[known.supplier != "Supplier C"]
    hi, lo = d[d.complexity == "High"], d[d.complexity == "Low"]
    sa, sb = d[d.shift_code == "Shift A"], d[d.shift_code == "Shift B"]
    T["0.6 The shop's own view as multipliers"] = pd.DataFrame([
        compare("Supplier C, all jobs", sup_c, "Suppliers A, B and D", sup_o),
        compare("High complexity", hi, "Low complexity", lo),
        compare("Shift B", sb, "Shift A", sa)])

    # Restatements
    brake = d[(d.machine_type == "Bending")]
    bm = brake[brake.thickness_deviation_band.notna()]
    bend = ["Bend Angle"]
    bend_failed = codes_failed(bend)
    rows = []
    for band in DEVIATION_BANDS:
        g = bm[bm.thickness_deviation_band == band]
        c, o = g[g.supplier == "Supplier C"], g[g.supplier != "Supplier C"]
        rows.append({"Deviation band": band, "Supplier C jobs": len(c), "Supplier C bend-angle rate": code_rate(c, ["Bend Angle"]),
                     "Supplier C mean deviation": c.abs_thickness_deviation_pct.mean(),
                     "Others jobs": len(o), "Others bend-angle rate": code_rate(o, ["Bend Angle"]),
                     "Others mean deviation": o.abs_thickness_deviation_pct.mean(),
                     "Ratio": code_rate(c, ["Bend Angle"]) / code_rate(o, ["Bend Angle"]) if len(o) >= 30 else np.nan})
    T["0.7 Restatement: Supplier C against the others within thickness deviation band (brake jobs, bend-angle rate)"] = pd.DataFrame(rows)
    later = d[d.run_position == 3]
    T["0.8 Restatement: complexity within later runs (first and second runs left out)"] = pd.DataFrame([
        compare("High complexity, later runs", later[later.complexity == "High"], "Low complexity, later runs", later[later.complexity == "Low"]),
        compare("Medium complexity, later runs", later[later.complexity == "Medium"], "Low complexity, later runs", later[later.complexity == "Low"])])
    ex = d[d.experience_band == "over 300"]
    T["0.9 Restatement: shift within operators with over 300 jobs on the machine type"] = pd.DataFrame([
        compare("Shift B, over 300 jobs", ex[ex.shift_code == "Shift B"], "Shift A, over 300 jobs", ex[ex.shift_code == "Shift A"])])
    comp = (d[d.shift_code.notna()].groupby("shift_code")
            .apply(lambda g: pd.Series({"Jobs": len(g), "Jobs by operators under 300 jobs": float((g.experience_band != "over 300").mean()),
                                        "Jobs by operators under 50 jobs": float((g.experience_band == "under 50").mean()),
                                        "Jobs by operators hired in the period": float(g.is_hired_in_period.mean())}), include_groups=False).reset_index())
    T["0.10 Shift composition by experience"] = comp

    # Finding 1: thickness deviation
    T["1.1 Bend-angle defect rate by thickness deviation band (brake jobs on measured lots)"] = by(bm, "thickness_deviation_band", DEVIATION_BANDS, bend_failed)
    low_band = bm[bm.thickness_deviation_band == "under 1%"]
    T["1.2 Bend-angle rate against the under 1% band (brake jobs)"] = pd.DataFrame(
        [compare(b, bm[bm.thickness_deviation_band == b], "under 1%", low_band, bend) for b in DEVIATION_BANDS[1:]]
        + [compare("2% and over", bm[bm.abs_thickness_deviation_pct >= 2], "under 2%", bm[bm.abs_thickness_deviation_pct < 2], bend),
           compare("2% and over, all defect codes", bm[bm.abs_thickness_deviation_pct >= 2], "under 2%", bm[bm.abs_thickness_deviation_pct < 2])])
    rows = []
    for label, g in (("Supplier C", bm[bm.supplier == "Supplier C"]), ("Suppliers A, B and D", bm[bm.supplier != "Supplier C"])):
        for band in DEVIATION_BANDS:
            x = g[g.thickness_deviation_band == band]
            rows.append({"Supplier": label, "Deviation band": band, "Jobs": len(x), "Bend-angle rate": code_rate(x, ["Bend Angle"])})
    T["1.3 Bend-angle rate by deviation band and supplier group"] = pd.DataFrame(rows)
    bk = known[known.machine_type == "Bending"]
    T["1.4 Supplier C against the others on brake jobs (all defect codes)"] = pd.DataFrame([
        compare("Supplier C, brake jobs", bk[bk.supplier == "Supplier C"], "Suppliers A, B and D", bk[bk.supplier != "Supplier C"])])
    con = duckdb.connect(str(DB_PATH), read_only=True)
    lots = con.execute("select * from mart_quality__lot_receipts").df()
    con.close()
    lots["abs_dev"] = lots["abs_thickness_deviation_pct"]
    T["1.5 Lots received by supplier: measurement, deviation and cert status"] = (
        lots.groupby("supplier").apply(lambda g: pd.Series({
            "Lots": len(g), "Measured at receiving": float(g.is_thickness_measured.mean()),
            "Mean deviation (measured lots)": g.abs_dev.mean(),
            "Lots at 2% or over (of measured)": float((g.abs_dev.dropna() >= 2).mean()),
            "Lots over 4% (of measured)": float((g.abs_dev.dropna() > 4).mean()),
            "Certified": float((g.cert_status == "Certified").mean())}), include_groups=False).reset_index())
    T["1.6 Jobs by lot information available"] = pd.DataFrame([
        {"Jobs": len(d), "No lot scanned": float(d.lot_id.isna().mean()),
         "Lot scanned, thickness not measured": float((d.lot_id.notna() & d.thickness_deviation_band.isna()).mean()),
         "Lot scanned and measured": float(d.thickness_deviation_band.notna().mean())}])
    T["1.7 Defect code mix on brake jobs: lots at 2% or over against under 2%"] = code_mix(
        bm.assign(dev=np.where(bm.abs_thickness_deviation_pct >= 2, "2% and over", "under 2%")), "dev")
    T["1.8 Monthly: bend-angle rate on brakes and mean deviation of lots consumed"] = monthly(
        bm, **{"Brake jobs on measured lots": len, "Bend-angle rate": lambda g: code_rate(g, ["Bend Angle"]),
               "Mean deviation of lots consumed": lambda g: g.abs_thickness_deviation_pct.mean()})
    seg = bm[bm.abs_thickness_deviation_pct >= 2]
    T["1.9 Savings: brake jobs on lots at 2% deviation or over, to the rate on lots under 2%"] = pd.DataFrame(
        [savings(seg, rate(bm[bm.abs_thickness_deviation_pct < 2]), years)])

    # Finding 2: first runs
    first, second = d[d.run_position == 1], d[d.run_position == 2]
    T["2.1 Defect rate by run position on the drawing revision"] = pd.DataFrame([
        compare("First run", first, "Later runs", later), compare("Second run", second, "Later runs", later)])
    rows = []
    for cx in ("Low", "Medium", "High"):
        a, b = first[first.complexity == cx], later[later.complexity == cx]
        rows.append({"Complexity": cx, "First-run jobs": len(a), "First-run rate": rate(a), "Later-run jobs": len(b),
                     "Later-run rate": rate(b), "Multiplier": rate(a) / rate(b),
                     "First runs as a share of jobs": len(a) / (d.complexity == cx).sum()})
    T["2.2 Defect rate by complexity, first runs against later runs"] = pd.DataFrame(rows)
    new_part = first[first.part_revision == "A"]
    T["2.3 First runs: composition"] = pd.DataFrame([{
        "First runs": len(first), "Share of jobs": len(first) / len(d), "On a new part number": len(new_part),
        "On a revised drawing": len(first) - len(new_part), "Second runs": len(second),
        "First runs with a first-piece record": float(first.has_first_piece_inspection.mean()),
        "Later runs with a first-piece record": float(later.has_first_piece_inspection.mean())}])
    T["2.4 Defect code mix: first runs against later runs"] = code_mix(
        d[d.run_position != 2].assign(run=np.where(d[d.run_position != 2].run_position == 1, "First runs", "Later runs")), "run")
    T["2.5 Monthly: first-run share of jobs and first-run defect rate"] = monthly(
        d, **{"First runs": lambda g: int((g.run_position == 1).sum()), "First-run share": lambda g: float((g.run_position == 1).mean()),
              "First-run rate": lambda g: rate(g[g.run_position == 1]), "Later-run rate": lambda g: rate(g[g.run_position == 3])})
    T["2.6 Savings: first runs to the later-run rate"] = pd.DataFrame([savings(first, rate(later), years)])

    # Finding 3: gauge change on the brakes
    after, same = brake[brake.is_after_gauge_change], brake[~brake.is_after_gauge_change]
    T["3.1 Brake jobs after a gauge change against jobs following the same gauge"] = pd.DataFrame([
        compare("After a gauge change, bend-angle rate", after, "Same gauge as the job before", same, bend),
        compare("After a gauge change, all defect codes", after, "Same gauge as the job before", same)])
    pos = brake.assign(change=brake.is_after_gauge_change.astype(int))
    pos["block"] = pos.groupby("machine_id")["change"].cumsum()
    pos["position"] = pos.groupby(["machine_id", "block"]).cumcount() + 1
    pos = pos[pos.block > 0]
    pos["Position after a gauge change"] = np.where(pos.position == 1, "First job", np.where(pos.position == 2, "Second job", "Third or later"))
    T["3.2 Bend-angle rate by position after a gauge change"] = by(pos, "Position after a gauge change", ["First job", "Second job", "Third or later"], bend_failed)
    T["3.3 Bend-angle rate by brake and position"] = pd.DataFrame([
        {"Brake": m, "Position": p, "Jobs": len(g), "Bend-angle rate": code_rate(g, ["Bend Angle"])}
        for (m, p), g in pos.groupby(["machine_name", "Position after a gauge change"])])
    laser = d[d.machine_type == "Laser Cutting"]
    T["3.4 Laser jobs after a gauge change (no effect expected)"] = pd.DataFrame([
        compare("Laser job after a gauge change", laser[laser.is_after_gauge_change], "Same gauge as the job before", laser[~laser.is_after_gauge_change])])
    T["3.5 Gauge changes on the brakes: composition"] = pd.DataFrame([{
        "Brake jobs": len(brake), "After a gauge change": float(brake.is_after_gauge_change.mean()),
        "After a change without a first-piece record": float((brake.is_after_gauge_change & ~brake.has_first_piece_inspection).mean()),
        "First-piece presence after a change": float(after.has_first_piece_inspection.mean()),
        "First-piece presence, same gauge": float(same.has_first_piece_inspection.mean())}])
    heat = pos.assign(hour=pos.job_start.dt.hour)
    T["3.6 Brake jobs by hour of day and position after a gauge change"] = (
        heat.groupby(["hour", "Position after a gauge change"]).size().unstack(fill_value=0).reset_index().rename(columns={"hour": "Hour of day"}))
    T["3.7 Defect code mix on the brakes: after a gauge change against the same gauge"] = code_mix(
        brake.assign(g=np.where(brake.is_after_gauge_change, "After a gauge change", "Same gauge")), "g")
    T["3.8 Monthly: gauge-change share of brake jobs and bend-angle rate"] = monthly(
        brake, **{"Brake jobs": len, "After a gauge change": lambda g: float(g.is_after_gauge_change.mean()),
                  "Bend-angle rate after a change": lambda g: code_rate(g[g.is_after_gauge_change], ["Bend Angle"]),
                  "Bend-angle rate, same gauge": lambda g: code_rate(g[~g.is_after_gauge_change], ["Bend Angle"])})
    T["3.9 Savings: brake jobs after a gauge change to the same-gauge rate"] = pd.DataFrame([savings(after, rate(same), years)])

    # Finding 4: schedule pressure
    rush, routine = d[d.is_rush], d[~d.is_rush]
    nofp, fp = d[~d.has_first_piece_inspection], d[d.has_first_piece_inspection]
    late, not_late = d[d.is_past_tenth_hour], d[~d.is_past_tenth_hour]
    T["4.1 Schedule pressure: rate tables"] = pd.DataFrame([
        compare("Rush jobs", rush, "Routine jobs", routine),
        compare("No first-piece record", nofp, "First-piece record", fp),
        compare("No first-piece record, rush", rush[~rush.has_first_piece_inspection], "First-piece record, rush", rush[rush.has_first_piece_inspection]),
        compare("No first-piece record, routine", routine[~routine.has_first_piece_inspection], "First-piece record, routine", routine[routine.has_first_piece_inspection]),
        compare("Rush with a first-piece record", rush[rush.has_first_piece_inspection], "Routine with a first-piece record", routine[routine.has_first_piece_inspection]),
        compare("Started past the tenth hour", late, "Started in the first ten hours", not_late)])
    short = d.setup_ratio_to_standard < 0.6
    T["4.2 Schedule pressure: composition"] = pd.DataFrame([{
        "Rush share of jobs": float(d.is_rush.mean()), "Rush share, busy months": float(d[d.production_month.dt.month.isin(BUSY_MONTHS)].is_rush.mean()),
        "First-piece skipped, rush": float(1 - rush.has_first_piece_inspection.mean()),
        "First-piece skipped, routine": float(1 - routine.has_first_piece_inspection.mean()),
        "Median setup against standard, rush": float(rush.setup_ratio_to_standard.median()),
        "Median setup against standard, routine": float(routine.setup_ratio_to_standard.median()),
        "First-piece skipped, setup under 0.6 of standard": float(1 - d[short].has_first_piece_inspection.mean()),
        "Jobs past the tenth hour": int(d.is_past_tenth_hour.sum()), "Share of jobs past the tenth hour": float(d.is_past_tenth_hour.mean()),
        "Share past the tenth hour, busy months": float(d[d.production_month.dt.month.isin(BUSY_MONTHS)].is_past_tenth_hour.mean())}])
    hb = d.assign(band=pd.cut(d.hours_into_operator_day, [-0.01, 2, 4, 6, 8, 10, 24],
                              labels=["0 to 2", "2 to 4", "4 to 6", "6 to 8", "8 to 10", "over 10"]))
    T["4.3 Defect rate by hours into the operator's day"] = by(hb, "band").rename(columns={"band": "Hours into the day"})
    T["4.4 Monthly: rush share, first-piece presence and jobs past the tenth hour"] = monthly(
        d, **{"Rush share": lambda g: float(g.is_rush.mean()), "First-piece presence": lambda g: float(g.has_first_piece_inspection.mean()),
              "Share past the tenth hour": lambda g: float(g.is_past_tenth_hour.mean()),
              "Rate without a first-piece record": lambda g: rate(g[~g.has_first_piece_inspection]),
              "Rate with a first-piece record": lambda g: rate(g[g.has_first_piece_inspection])})
    T["4.5 Savings: jobs without a first-piece record to the rate with one"] = pd.DataFrame([savings(nofp, rate(fp), years)])
    T["4.6 Savings: jobs past the tenth hour to the rate in the first ten hours"] = pd.DataFrame([savings(late, rate(not_late), years)])

    # Finding 5: experience on the machine type
    top = d[d.experience_band == "over 300"]
    T["5.1 Defect rate by cumulative jobs on the machine type"] = pd.DataFrame(
        [compare(b, d[d.experience_band == b], "over 300", top) for b in EXPERIENCE_BANDS[:-1]])
    rows = []
    for label, g in (("Operators hired in the period", d[d.is_hired_in_period]), ("Coverage jobs (secondary machine type)", d[d.is_coverage]),
                     ("Primary machine type, hired before the period", d[~d.is_hired_in_period & ~d.is_coverage])):
        for b in EXPERIENCE_BANDS:
            x = g[g.experience_band == b]
            rows.append({"Group": label, "Experience band": b, "Jobs": len(x), "Rate": rate(x)})
    T["5.2 The experience curve for new hires and for coverage jobs"] = pd.DataFrame(rows)
    T["5.3 Experience: composition"] = pd.DataFrame([{
        "Jobs under 50": int((d.experience_band == "under 50").sum()), "Share of jobs under 50": float((d.experience_band == "under 50").mean()),
        "Share of jobs under 300": float((d.experience_band != "over 300").mean()), "Coverage share of jobs": float(d.is_coverage.mean()),
        "Operators hired in the period": int(d[d.is_hired_in_period].operator_id.nunique()),
        "Jobs with experience estimated from tenure only (no log history yet)": float((d.jobs_in_log_before == 0).mean()),
        "Share of jobs by operators hired before the period": float((~d.is_hired_in_period).mean())}])
    last_month = d[d.production_month == months[-1]].operator_id.unique()
    ops = (d[d.operator_id.isin(last_month)].groupby(["operator_id", "operator_name", "assigned_shift", "machine_type", "is_coverage"])
           .apply(lambda g: pd.Series({"Jobs in the period": len(g), "Jobs on the machine type at the end": g.jobs_on_machine_type_before.max() + 1,
                                       "Rate": rate(g)}), include_groups=False).reset_index())
    T["5.4 Current roster: experience and defect rate by operator and machine type (50 jobs or more in the period)"] = ops[ops["Jobs in the period"] >= 50]
    seg = d[d.experience_band != "over 300"]
    T["5.5 Savings: jobs by operators under 300 jobs to the over-300 rate"] = pd.DataFrame([savings(seg, rate(top), years)])

    # Finding 6: lot age on cold-rolled gauge steel
    gs, other = d[d.is_gauge_steel & d.lot_age_band.notna()], d[~d.is_gauge_steel & d.lot_age_band.notna()]
    fresh = gs[gs.lot_age_band == "under 60 days"]
    T["6.1 Gauge steel: defect rate by days since receipt"] = pd.DataFrame(
        [compare(b, gs[gs.lot_age_band == b], "under 60 days", fresh) for b in LOT_AGE_BANDS[1:]]
        + [compare("60 days and over", gs[gs.lot_age_band != "under 60 days"], "under 60 days", fresh),
           compare("Other materials, 60 days and over", other[other.lot_age_band != "under 60 days"],
                   "Other materials, under 60 days", other[other.lot_age_band == "under 60 days"])])
    rows = []
    for label, g in (("Gauge steel", gs), ("Plate, aluminum and stainless", other)):
        for b in LOT_AGE_BANDS:
            x = g[g.lot_age_band == b]
            rows.append({"Material": label, "Lot age": b, "Jobs": len(x), "Rate": rate(x)})
    T["6.2 Defect rate by lot age band and material group"] = pd.DataFrame(rows)
    T["6.3 Defect code mix on gauge steel by lot age band"] = code_mix(gs, "lot_age_band")
    T["6.4 Lot age: composition"] = pd.DataFrame([{
        "Gauge-steel jobs with a scanned lot": len(gs), "On lots 60 days and over": float((gs.lot_age_band != "under 60 days").mean()),
        "On lots over 120 days": float((gs.lot_age_band == "over 120 days").mean()),
        "Porosity and surface contamination share of failed pieces, 60 days and over":
            float(gs[(gs.lot_age_band != "under 60 days") & gs.defect_code.isin(["Porosity", "Surface Contamination"])].quantity_failed.sum()
                  / gs[gs.lot_age_band != "under 60 days"].quantity_failed.sum()),
        "Porosity and surface contamination share, under 60 days":
            float(fresh[fresh.defect_code.isin(["Porosity", "Surface Contamination"])].quantity_failed.sum() / fresh.quantity_failed.sum())}])
    T["6.5 Monthly: share of gauge-steel jobs on lots 60 days and over"] = monthly(
        gs, **{"Gauge-steel jobs": len, "On lots 60 days and over": lambda g: float((g.lot_age_band != "under 60 days").mean()),
               "Rate, 60 days and over": lambda g: rate(g[g.lot_age_band != "under 60 days"]),
               "Rate, under 60 days": lambda g: rate(g[g.lot_age_band == "under 60 days"])})
    seg = gs[gs.lot_age_band != "under 60 days"]
    T["6.6 Savings: gauge-steel jobs on lots 60 days and over to the under-60-day rate"] = pd.DataFrame([savings(seg, rate(fresh), years)])

    # Financial impact
    fin = [("1. Gauge deviation at receiving", "1.9 Savings: brake jobs on lots at 2% deviation or over, to the rate on lots under 2%"),
           ("2. First runs of new and revised parts", "2.6 Savings: first runs to the later-run rate"),
           ("3. First job after a gauge change on a brake", "3.9 Savings: brake jobs after a gauge change to the same-gauge rate"),
           ("4a. First-piece inspection skipped", "4.5 Savings: jobs without a first-piece record to the rate with one"),
           ("4b. Jobs past the tenth hour", "4.6 Savings: jobs past the tenth hour to the rate in the first ten hours"),
           ("5. Experience on the machine type", "5.5 Savings: jobs by operators under 300 jobs to the over-300 rate"),
           ("6. Cold-rolled steel past 60 days", "6.6 Savings: gauge-steel jobs on lots 60 days and over to the under-60-day rate")]
    T["7.1 Financial impact: one row per finding"] = pd.DataFrame([{"Finding": name} | T[key].iloc[0].to_dict() for name, key in fin])
    seg_flags = pd.DataFrame({
        "deviation": (d.machine_type == "Bending") & (d.abs_thickness_deviation_pct >= 2),
        "first run": d.run_position == 1,
        "gauge change": (d.machine_type == "Bending") & d.is_after_gauge_change,
        "no first piece": ~d.has_first_piece_inspection,
        "past tenth hour": d.is_past_tenth_hour,
        "under 300 jobs": d.experience_band != "over 300",
        "old gauge-steel lot": d.is_gauge_steel & d.lot_age_band.isin(LOT_AGE_BANDS[1:])})
    n = seg_flags.sum(axis=1)
    T["7.2 Overlap between the finding segments"] = pd.DataFrame([{
        "Jobs in no segment": int((n == 0).sum()), "In one segment": int((n == 1).sum()), "In two": int((n == 2).sum()),
        "In three or more": int((n >= 3).sum()), "Share of scrap cost on jobs in two or more segments": float(d[n >= 2].scrap_cost.sum() / d.scrap_cost.sum()),
        "Rate, no segment": rate(d[n == 0]), "Rate, one": rate(d[n == 1]), "Rate, two": rate(d[n == 2]), "Rate, three or more": rate(d[n >= 3])}])
    return T


# ── Markdown output ──────────────────────────────────────────────────────────
def _fmt(col, v):
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        name = str(col).lower()
        if "p-value" in name:
            return "<0.001" if v < 0.001 else f"{v:.3f}"
        if any(k in name for k in ("cost", "savings", "revenue")) and "share" not in name:
            return f"${v:,.0f}"
        if any(k in name for k in ("multiplier", "95%", "ratio")) and "share" not in name:
            return f"{v:.2f}x"
        if "mean deviation" in name:
            return f"{v:.2f}%"
        if "median setup" in name:
            return f"{v:.2f}"
        if name in ("jobs on the machine type at the end",):
            return f"{v:,.0f}"
        return f"{v:.2%}" if abs(v) <= 1.0 else f"{v:,.0f}"
    return str(v)


def to_markdown(tables: dict) -> str:
    out = []
    for title, t in tables.items():
        out += [f"### {title}", "", "| " + " | ".join(map(str, t.columns)) + " |", "|" + "---|" * len(t.columns)]
        for row in t.itertuples(index=False):
            out.append("| " + " | ".join(_fmt(c, v) for c, v in zip(t.columns, row)) + " |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    text = to_markdown(build())
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf8")
        print(text)
