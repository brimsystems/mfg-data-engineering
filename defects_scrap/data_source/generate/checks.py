"""
Checks on the source tables, computed from the raw files with the same
definitions the dbt marts use: defect rate as quantity failed over quantity
inspected at final inspection after deduplication; experience as cumulative
jobs by operator and machine type at job start, the job-log count plus the jobs
run before the log began, estimated from the HR hire date; hours into the day
from the operator's first job start; lot age from receipt date.

Prints a table of measured value, range and pass or fail for every entry in
config.CHECKS, and writes it to data_source/generate/truth/checks.csv.

Usage: python -m data_source.generate.checks
"""
import re

import numpy as np
import pandas as pd

from . import config as C

RAW = C.RAW_DIR
YEARS = (C.END_DATE - C.START_DATE).days / 365.25
_TYPE_OF = {m[0]: m[2] for m in C.MACHINES_DATA}
DEV_BANDS = [(0, 1, "under 1%"), (1, 2, "1 to 2%"), (2, 4, "2 to 4%"), (4, 1e9, "over 4%")]


def load() -> pd.DataFrame:
    """One row per work order with the measures and dimensions the marts carry."""
    po = pd.read_csv(RAW / "erp" / "production_orders.csv")
    pc = pd.read_csv(RAW / "erp" / "part_catalog.csv", parse_dates=["released_date"])
    jl = pd.read_csv(RAW / "mes" / "job_log.csv", parse_dates=["job_start", "job_end"])
    ins = pd.read_csv(RAW / "qms" / "inspection_records.csv")
    lots = pd.read_csv(RAW / "materials" / "material_lots.csv", parse_dates=["receipt_date"])
    hr = pd.read_csv(RAW / "hr" / "operators.csv", parse_dates=["hire_date"])

    # Job log: clock entries keyed the wrong way round are put back; a name in
    # the badge field is resolved to the operator id through HR.
    swapped = jl["job_end"] < jl["job_start"]
    jl.loc[swapped, ["job_start", "job_end"]] = jl.loc[swapped, ["job_end", "job_start"]].values
    name_to_id = hr.set_index("operator_name")["operator_id"].to_dict()
    jl["operator_id"] = jl["operator_badge"].map(lambda v: name_to_id.get(v, v))

    # Final inspections: the earliest entry per work order is kept.
    ins["n"] = ins["inspection_id"].str.extract(r"(\d+)").astype(int)
    final = (ins[ins["inspection_type"] == "final"].sort_values("n").drop_duplicates("work_order_id"))
    first_piece = set(ins.loc[ins["inspection_type"] == "first_piece", "work_order_id"])

    d = po.merge(jl[["work_order_id", "operator_id", "job_start", "job_end", "setup_minutes"]], on="work_order_id")
    d = d.merge(final[["work_order_id", "quantity_inspected", "quantity_failed", "defect_code_clean", "inspection_date"]],
                on="work_order_id")
    d = d.merge(pc[["part_number", "released_date", "unit_price", "std_setup_min"]],
                left_on="part_number_clean", right_on="part_number", how="left")
    d["machine_type"] = d["machine_id"].map(_TYPE_OF)
    d["has_first_piece"] = d["work_order_id"].isin(first_piece)

    # Lot: the id as scanned on the order, normalized; null where not scanned.
    def lot_key(v):
        if pd.isna(v):
            return None
        return "LOT-" + re.sub(r"\D", "", str(v))
    d["lot_id"] = d["lot_id_raw"].map(lot_key)
    d = d.merge(lots[["lot_id_clean", "supplier", "cert_status", "receipt_date", "thickness_deviation_pct"]],
                left_on="lot_id", right_on="lot_id_clean", how="left")
    d["lot_age_days"] = (d["job_start"].dt.normalize() - d["receipt_date"]).dt.days
    d["abs_dev"] = d["thickness_deviation_pct"].abs()
    d["gauge_steel"] = d["material_type"].map(lambda m: C.MATERIALS[m]["gauge_steel"])
    d["thickness"] = d["material_type"].map(lambda m: C.MATERIALS[m]["nominal_thickness_in"])

    d = d.sort_values(["job_start", "work_order_id"]).reset_index(drop=True)
    # Run position on the drawing revision; a drawing released before the record starts is not a first run.
    seq = d.groupby(["part_number_clean", "part_revision"]).cumcount() + 1
    existing = (d["part_revision"] == "A") & (d["released_date"] < pd.Timestamp(C.START_DATE))
    d["run_position"] = np.where(existing, 3, np.minimum(seq, 3))
    # Experience: jobs by the operator on the machine type before this one. The
    # job-log count, plus the jobs run before the log began: years at the shop
    # before the first logged day at the shop's rate of jobs per operator-year on
    # the primary machine type, a quarter of that on the secondary.
    d = d.merge(hr[["operator_id", "hire_date", "primary_machine_type", "secondary_machine_type"]], on="operator_id", how="left")
    years_before = ((d["job_start"].min().normalize() - d["hire_date"]).dt.days / 365.25).clip(lower=0)
    prior = np.where(d["machine_type"] == d["primary_machine_type"], years_before * C.PRIOR_JOBS_PER_TENURE_YEAR,
                     np.where(d["machine_type"] == d["secondary_machine_type"],
                              years_before * C.PRIOR_JOBS_PER_TENURE_YEAR * C.SECONDARY_PRIOR_SHARE, 0.0))
    d["jobs_in_log"] = d.groupby(["operator_id", "machine_type"]).cumcount()
    d["jobs_before"] = d["jobs_in_log"] + prior
    # Hours into the operator's day; the production day turns over at 02:00.
    d["op_day"] = (d["job_start"] - pd.Timedelta(hours=2)).dt.date
    d["hours_into_day"] = (d["job_start"] - d.groupby(["operator_id", "op_day"])["job_start"].transform("min")).dt.total_seconds() / 3600
    # The job before on the same machine ran another thickness.
    prev = d.groupby("machine_id")["thickness"].shift(1)
    d["after_gauge_change"] = prev.notna() & (prev != d["thickness"])
    # Shift: the code on the order, else from the start time.
    t = pd.to_datetime(d["actual_start"]).dt.hour
    d["shift"] = d["shift_code"].fillna(pd.Series(np.where((t >= 6) & (t < 14), "Shift A",
                                                  np.where((t >= 14) & (t < 22), "Shift B", None)), index=d.index))
    d["coverage"] = d["primary_machine_type"] != d["machine_type"]
    d["month_class"] = d["job_start"].dt.month.map(
        lambda m: "busy" if m in C.BUSY_MONTHS else "quiet" if m in C.QUIET_MONTHS else "normal")
    return d


def rate(x: pd.DataFrame) -> float:
    return x["quantity_failed"].sum() / x["quantity_inspected"].sum() if len(x) else float("nan")


def code_rate(x: pd.DataFrame, codes) -> float:
    return x.loc[x["defect_code_clean"].isin(codes), "quantity_failed"].sum() / x["quantity_inspected"].sum() if len(x) else float("nan")


def run() -> pd.DataFrame:
    d = load()
    po = pd.read_csv(RAW / "erp" / "production_orders.csv")
    jl = pd.read_csv(RAW / "mes" / "job_log.csv", parse_dates=["job_start", "job_end"])
    ins = pd.read_csv(RAW / "qms" / "inspection_records.csv")
    lots = pd.read_csv(RAW / "materials" / "material_lots.csv")
    scrap = pd.read_csv(RAW / "qms" / "scrap_events.csv")
    hr = pd.read_csv(RAW / "hr" / "operators.csv")
    pc = pd.read_csv(RAW / "erp" / "part_catalog.csv", parse_dates=["released_date"])
    truth_jobs = pd.read_csv(C.TRUTH_DIR / "jobs.csv", parse_dates=["job_start"])
    revisions = pd.read_csv(C.TRUTH_DIR / "revisions.csv")

    out = []

    def add(name, value, note=""):
        rng = C.CHECKS[name]
        if isinstance(rng, tuple):
            ok = rng[0] <= value <= rng[1]
            shown = f"{rng[0]:,} to {rng[1]:,}" if rng[1] > 5 else f"{rng[0]} to {rng[1]}"
        else:
            ok, shown = bool(value), rng
        out.append({"check": name, "measured": value, "range": shown, "result": "pass" if ok else "FAIL", "note": note})

    add("C1 overall defect rate", round(rate(d), 4), f"{len(d):,} jobs, {int(d.quantity_inspected.sum()):,} pieces")
    add("C2 scrap and rework cost a year", round(scrap["total_scrap_cost"].sum() / YEARS),
        f"${scrap['total_scrap_cost'].sum() / d['quantity_failed'].sum():.2f} per failed piece")
    scrapped = scrap.groupby("work_order_id")["quantity_scrapped"].sum()
    shipped = d["quantity_ordered"] - d["work_order_id"].map(scrapped).fillna(0)
    add("Revenue a year", round((shipped * d["unit_price"]).sum() / YEARS))

    # C3.1 thickness deviation
    brake = d[(d["machine_type"] == "Bending") & d["abs_dev"].notna()]
    groups = {"Supplier C": brake[brake.supplier == "Supplier C"], "Suppliers A, B and D": brake[brake.supplier != "Supplier C"]}
    table, mono = [], True
    for label, g in groups.items():
        kept, left_out = [], []
        for lo, hi, band in DEV_BANDS:
            b = g[(g.abs_dev >= lo) & (g.abs_dev < hi)]
            if len(b) < C.MONOTONIC_MIN_JOBS:
                left_out.append(f"{band} ({len(b)} jobs)")
            else:
                kept.append((band, code_rate(b, ["Bend Angle"]), len(b)))
        mono &= all(y[1] > x[1] for x, y in zip(kept, kept[1:]))
        table.append(f"{label}: " + ", ".join(f"{band} {r:.2%} ({n} jobs)" for band, r, n in kept)
                     + (f"; left out: {', '.join(left_out)}" if left_out else ""))
    add("C3.1 bend-angle rate rises across deviation bands, Supplier C and the others pooled", mono, " | ".join(table))
    known = d[d["supplier"].notna()]
    c_all = rate(known[known.supplier == "Supplier C"]) / rate(known[known.supplier != "Supplier C"])
    kb = known[known.machine_type == "Bending"]
    add("C3.1 Supplier C against others, brake jobs",
        round(rate(kb[kb.supplier == "Supplier C"]) / rate(kb[kb.supplier != "Supplier C"]), 3),
        f"all jobs, for information: {c_all:.3f}")
    num = den = 0.0
    for lo, hi, _ in DEV_BANDS:
        b = brake[(brake.abs_dev >= lo) & (brake.abs_dev < hi)]
        c, o = b[b.supplier == "Supplier C"], b[b.supplier != "Supplier C"]
        if len(c) and len(o):
            wgt = c["quantity_inspected"].sum()
            num += wgt * code_rate(c, ["Bend Angle"]); den += wgt * code_rate(o, ["Bend Angle"])
    add("C3.1 Supplier C against others, within band", round(num / den, 3), "bend-angle rate on brake jobs, weighted by Supplier C pieces")

    # C3.2 first runs
    first, second, later = (d[d.run_position == k] for k in (1, 2, 3))
    add("C3.2 first run against later runs", round(rate(first) / rate(later), 3),
        f"first {rate(first):.2%} ({len(first):,} jobs), second {rate(second):.2%} ({len(second):,}), later {rate(later):.2%}")
    high, low = d[d.complexity == "High"], d[d.complexity == "Low"]
    add("C3.2 first runs as a share of high-complexity jobs", round((high.run_position == 1).mean(), 4), f"{len(high):,} high-complexity jobs")
    r_all = rate(high) / rate(low)
    r_later = rate(high[high.run_position == 3]) / rate(low[low.run_position == 3])
    add("C3.2 high against low complexity, later runs", round(r_later, 3), f"all jobs: {r_all:.3f}")

    # C3.3 gauge change
    bk = d[d.machine_type == "Bending"]
    add("C3.3 brake job after a gauge change", round(rate(bk[bk.after_gauge_change]) / rate(bk[~bk.after_gauge_change]), 3),
        f"bend-angle rate only: {code_rate(bk[bk.after_gauge_change], ['Bend Angle']) / code_rate(bk[~bk.after_gauge_change], ['Bend Angle']):.3f}")
    ls = d[d.machine_type == "Laser Cutting"]
    add("C3.3 laser job after a gauge change", round(rate(ls[ls.after_gauge_change]) / rate(ls[~ls.after_gauge_change]), 3))

    # C3.4 schedule pressure
    add("C3.4 no first-piece record", round(rate(d[~d.has_first_piece]) / rate(d[d.has_first_piece]), 3))
    add("C3.4 first-piece skip rate, rush", round(1 - d.loc[d.rush_flag, "has_first_piece"].mean(), 4))
    add("C3.4 first-piece skip rate, routine", round(1 - d.loc[~d.rush_flag, "has_first_piece"].mean(), 4))
    late = d["hours_into_day"] > 10
    add("C3.4 past the tenth hour", round(rate(d[late]) / rate(d[~late]), 3), f"{int(late.sum()):,} jobs past the tenth hour")
    add("C3.4 jobs past the tenth hour, all", round(late.mean(), 4))
    add("C3.4 jobs past the tenth hour, busy months", round(late[d.month_class == "busy"].mean(), 4))

    # C3.5 experience
    bands = [(0, 50), (50, 150), (150, 300), (300, 10**9)]
    rates = [rate(d[(d.jobs_before >= lo) & (d.jobs_before < hi)]) for lo, hi in bands]
    add("C3.5 under 50 jobs against over 300", round(rates[0] / rates[-1], 3),
        "by band: " + ", ".join(f"{r:.2%}" for r in rates)
        + f"; jobs under 50: {int((d.jobs_before < 50).sum()):,}")
    add("C3.5 experience curve", all(b < a for a, b in zip(rates, rates[1:])))

    # C3.6 lot age
    gs = d[d.gauge_steel & d.lot_age_days.notna()]
    fresh = gs[gs.lot_age_days < 60]
    add("C3.6 gauge steel, 60 to 120 days", round(rate(gs[(gs.lot_age_days >= 60) & (gs.lot_age_days < 120)]) / rate(fresh), 3))
    add("C3.6 gauge steel, past 120 days", round(rate(gs[gs.lot_age_days >= 120]) / rate(fresh), 3),
        f"{int((gs.lot_age_days >= 120).sum()):,} jobs past 120 days")
    ot = d[~d.gauge_steel & d.lot_age_days.notna()]
    add("C3.6 other materials, past 60 days", round(rate(ot[ot.lot_age_days >= 60]) / rate(ot[ot.lot_age_days < 60]), 3))
    share = lambda x: x.loc[x.defect_code_clean.isin(["Porosity", "Surface Contamination"]), "quantity_failed"].sum() / x["quantity_failed"].sum()
    add("C3.6 porosity and contamination share, old against fresh lots", round(share(gs[gs.lot_age_days >= 60]) / share(fresh), 3),
        f"old {share(gs[gs.lot_age_days >= 60]):.1%}, fresh {share(fresh):.1%}")

    # C4 shift
    a, b = d[d["shift"] == "Shift A"], d[d["shift"] == "Shift B"]
    add("C4 Shift B against Shift A, all jobs", round(rate(b) / rate(a), 3))
    add("C4 Shift B against Shift A, operators over 300 jobs",
        round(rate(b[b.jobs_before >= 300]) / rate(a[a.jobs_before >= 300]), 3))

    # C5 to C10 composition
    add("C5 rush share, all", round(d.rush_flag.mean(), 4))
    add("C5 rush share, busy months", round(d.loc[d.month_class == "busy", "rush_flag"].mean(), 4))
    add("C5 rush share, quiet months", round(d.loc[d.month_class == "quiet", "rush_flag"].mean(), 4))
    add("C5 first-piece presence, routine", round(d.loc[~d.rush_flag, "has_first_piece"].mean(), 4))
    add("C5 first-piece presence, rush", round(d.loc[d.rush_flag, "has_first_piece"].mean(), 4))
    days = truth_jobs.assign(day=(truth_jobs["job_start"] - pd.Timedelta(hours=2)).dt.date).groupby("day")["long_day"].first()
    add("C5 long days as a share of working days", round(days.mean(), 4), f"{len(days)} working days")
    add("C6 coverage share of jobs", round(d.coverage.mean(), 4))
    add("C7 revision events", int((revisions["revision"] != "A").sum()))
    add("C7 new parts", int((pc.released_date >= pd.Timestamp(C.START_DATE)).sum()), f"{len(pc)} part numbers in the catalog")
    add("C7 first runs as a share of jobs", round((d.run_position == 1).mean(), 4), f"{int((d.run_position == 1).sum()):,} first runs")
    add("C8 lots with thickness measured", round(lots["measured_thickness_in"].notna().mean(), 4), f"{len(lots):,} lots")
    add("C9 gauge-steel jobs on lots past 60 days", round((gs.lot_age_days >= 60).mean(), 4))
    add("C10 brake jobs following a gauge change", round(bk.after_gauge_change.mean(), 4))

    # C11 record faults
    canon_part = po["part_number_raw"] == po["part_number_clean"]
    measured = {
        "part_number_noncanonical": 1 - canon_part.mean(),
        "erp_operator_as_name": (~po["operator_id_raw"].astype(str).str.match(r"^OP\d+$")).mean(),
        "erp_shift_code_null": po["shift_code"].isna().mean(),
        "erp_lot_id_null": po["lot_id_raw"].isna().mean(),
        # The lot id is keyed twice: by receiving on the lot receipt, and on the
        # floor when the lot is scanned or typed onto the work order.
        "lot_id_noncanonical": (po["lot_id_raw"].dropna() != po.loc[po["lot_id_raw"].notna(), "lot_id_clean"]).mean(),
        "lot_id_noncanonical (lot receipts)": (lots["lot_id_raw"] != lots["lot_id_clean"]).mean(),
        "inspection_duplicate": ins[ins.inspection_type == "final"].duplicated("work_order_id").sum() / len(d),
        "lot_thickness_unmeasured": lots["measured_thickness_in"].isna().mean(),
        "job_log_operator_as_name": (~jl["operator_badge"].astype(str).str.match(r"^OP\d+$")).mean(),
        "job_log_end_before_start": (jl["job_end"] < jl["job_start"]).mean(),
    }
    fin = ins[ins.inspection_type == "final"].merge(jl[["work_order_id", "job_start", "job_end"]], on="work_order_id")
    lo_t = fin[["job_start", "job_end"]].min(axis=1)
    gap = (pd.to_datetime(fin["inspection_date"]) - lo_t).dt.total_seconds() / 3600
    measured["inspection_timestamp_off"] = ((gap < 1.0) | (gap > 6.5)).mean()
    part_formats = po["part_number_raw"].str.replace(r"\d+", "#", regex=True).nunique()
    set_rate = lambda k: C.FAULTS[k.split(" (")[0]]
    worst = max(abs(v - set_rate(k)) for k, v in measured.items())
    add("C11 record-fault rates", worst <= 0.02,
        "; ".join(f"{k} {v:.1%} (set {set_rate(k):.0%})" for k, v in measured.items()) + f"; part number formats {part_formats}")

    # C12 physical sense
    fixed_start = jl[["job_start", "job_end"]].min(axis=1)
    fixed_end = jl[["job_start", "job_end"]].max(axis=1)
    seqs = pd.DataFrame({"m": jl["machine_id"], "s": fixed_start, "e": fixed_end}).sort_values(["m", "s"])
    overlaps = int((seqs.groupby("m")["e"].shift(1) > seqs["s"]).sum())
    negative = int((po["quantity_ordered"] < 0).sum() + (ins[["quantity_inspected", "quantity_passed", "quantity_failed"]] < 0).sum().sum())
    early = int((gap < -10.0).sum())
    add("C12 physical sense violations", overlaps + negative + early + int((fixed_end < fixed_start).sum()),
        f"machine overlaps {overlaps}, negative quantities {negative}, inspections over 10 h before the job {early}")

    table = pd.DataFrame(out)
    C.TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(C.TRUTH_DIR / "checks.csv", index=False, lineterminator="\n")
    with pd.option_context("display.width", 250, "display.max_colwidth", 120, "display.max_rows", 200):
        print(table[["check", "measured", "range", "result"]].to_string(index=False))
    print(f"\n{(table.result == 'pass').sum()} of {len(table)} pass")
    return table


if __name__ == "__main__":
    run()
