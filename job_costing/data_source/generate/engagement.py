"""The twelve-week engagement, as the records it leaves behind.

Interviews, the configuration gap list, the program crosswalk that connects the
machine-monitoring feed to parts, the work-center rate pools and attended
ratios, the estimate backfill onto historic jobs, the outside-processing
attribution, the configuration change log, the routing standard refresh with
the estimator's review of each measured value, and the repricing decisions the
controller and owner made part by part.

Review decisions carry judgment: the estimator disputes some measured cycle
times and wins a few; the owner declines to reprice two large-customer parts
for relationship reasons and says so; some PO lines cannot be attributed and
stay in the general ledger. The mechanical corrections (labor cleanup rules,
machine-hours-to-job assignment, coverage) are the pipeline's work and are not
produced here.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C
from .generators.costing import CostModel
from .generators import quotes_jobs as QJ

BREAKS = [None]          # the quantity breaks on every quote line, set by the generator

ROLES = ["Owner", "Controller", "Estimator", "Production manager", "Quality manager", "ERP administrator",
         "CNC cell lead, mills", "CNC cell lead, Swiss and lathes", "Stockroom lead"]


def _week_date(week, day=0):
    return C.ENGAGEMENT_START + timedelta(days=7 * (week - 1) + day)


def build(rng, cm, parts, routings, wcs, jobs, ops, lab, shadow, mat, unissued, osp, scrap, mm, quotes, standing,
          own_std, plan, cust, emps):
    art = {}
    p_idx = parts.set_index("part_number")

    # ── week 1: interviews ────────────────────────────────────────────────
    topics = {
        "Owner": ("Margin by job and customer; the annual letter and how larger increases land with customers", "repricing decisions"),
        "Controller": ("Job cost module never configured; POs coded to GL; one blended rate; which increases customers accept", "rate pools; estimate backfill; repricing policy"),
        "Estimator": ("Quoting from the spreadsheet; standards set at first quote; has never seen a job's actuals", "standard refresh; material price list"),
        "Production manager": ("Door terminals; operators clocking whole shifts to one job; lights-out cells", "labor cleanup rules; terminal move"),
        "Quality manager": ("Scrap thrown in the bin; rework posted as run time", "scrap reason codes; rework code"),
        "ERP administrator": ("Data collection module installed, never configured; quote-to-job conversion", "configuration changes"),
        "CNC cell lead, mills": ("Multi-machine tending; program naming; setups on small lots", "program crosswalk; attended ratios"),
        "CNC cell lead, Swiss and lathes": ("Overnight runs left clocked in; generic programs on the Swiss cells", "program crosswalk; attended ratios"),
        "Stockroom lead": ("Bar pulled for two jobs and charged to one; remnants never issued", "material corrections"),
    }
    art["interview_log"] = pd.DataFrame([{"role": r, "interview_date": _week_date(1, i % 5), "topic": topics[r][0],
                                          "consulted_on": topics[r][1]} for i, r in enumerate(ROLES)])

    # ── weeks 1-2: configuration gap list ─────────────────────────────────
    art["config_gap_list"] = pd.DataFrame([
        {"module": "Quoting", "setting": "Carry estimate to job on conversion", "as_found": "Off", "gap": "No job carries an estimate by element", "resolved_by": "Configuration change, week 4"},
        {"module": "Job costing", "setting": "Job cost by element", "as_found": "Never configured", "gap": "Module installed, no cost elements defined", "resolved_by": "Configuration change, week 4"},
        {"module": "Work centers", "setting": "Rate per work center", "as_found": "One blended rate on every record", "gap": "Manual and 5-axis time costed alike", "resolved_by": "Rate pools, week 5"},
        {"module": "Data collection", "setting": "Terminal location", "as_found": "Two terminals at the shop door", "gap": "Clock records span breaks and shifts", "resolved_by": "Terminals moved to cells, week 5"},
        {"module": "Data collection", "setting": "Labor type codes", "as_found": "Run only", "gap": "Setup, rework and indirect indistinguishable", "resolved_by": "Codes enabled, week 5"},
        {"module": "Data collection", "setting": "Open operations per employee", "as_found": "Unlimited", "gap": "One record covers two or three machines", "resolved_by": "One open operation rule, week 5"},
        {"module": "Data collection", "setting": "Auto-close at shift end", "as_found": "Off", "gap": "Records left open overnight", "resolved_by": "Auto-close with review flag, week 5"},
        {"module": "Purchasing", "setting": "Job number required on outside-processing POs", "as_found": "Optional", "gap": "78% of lines coded to GL with no job", "resolved_by": "Required field, week 4"},
        {"module": "Quality", "setting": "Reason code required on scrap", "as_found": "Optional", "gap": "Half of recorded scrap carries no reason", "resolved_by": "Required field, week 6"},
        {"module": "Machine monitoring", "setting": "Feed to ERP", "as_found": "Not connected", "gap": "Machine hours never reach a job", "resolved_by": "Program crosswalk and feed, weeks 2-6"},
        {"module": "Routings", "setting": "Standard refresh", "as_found": "Manual, never run", "gap": "Standards set at first quote", "resolved_by": "Measured refresh, weeks 6-8"},
    ])

    # ── weeks 2-3: program crosswalk ──────────────────────────────────────
    prog = routings[routings["program_number"].notna()][["program_number", "part_number", "revision", "work_center_id"]].drop_duplicates()
    counts = prog.groupby("program_number")["part_number"].nunique()
    rows = []
    leads = {"VMC": "CNC cell lead, mills", "FAX": "CNC cell lead, mills", "HMC": "CNC cell lead, mills",
             "LTH": "CNC cell lead, Swiss and lathes", "MTN": "CNC cell lead, Swiss and lathes",
             "SWS": "CNC cell lead, Swiss and lathes", "EDM": "CNC cell lead, mills"}
    unresolved_pairs = set()
    for r in prog.itertuples():
        generic = counts[r.program_number] > 1 or not str(r.program_number).startswith("O0") and not str(r.program_number).startswith("O4")
        if not generic:
            rows.append({"program_number": r.program_number, "machine_id": None, "part_number": r.part_number,
                         "revision": r.revision, "method": "routing match", "resolved_by": "ERP administrator",
                         "confidence": 0.98, "status": "resolved"})
        else:
            # the cell lead confirms the part runs under this program; which job is
            # settled by the jobs open on the day, so the confidence is lower
            rows.append({"program_number": r.program_number, "machine_id": None, "part_number": r.part_number,
                         "revision": r.revision, "method": f"cell lead review, program shared by {counts[r.program_number]} parts",
                         "resolved_by": leads[r.work_center_id[:3]], "confidence": round(float(rng.uniform(0.70, 0.85)), 2),
                         "status": "resolved"})
    # the program-machine pairs the leads could not place at all
    generic_pairs = prog[prog["program_number"].map(counts) > 1][["program_number", "work_center_id"]].drop_duplicates()
    for r in generic_pairs.itertuples():
        if rng.random() < 0.20:
            rows.append({"program_number": r.program_number, "machine_id": r.work_center_id, "part_number": None,
                         "revision": None, "method": "unresolved: generic name, no part confirmed on this machine",
                         "resolved_by": leads[r.work_center_id[:3]], "confidence": 0.0, "status": "unresolved"})
    art["program_crosswalk"] = pd.DataFrame(rows)

    # ── weeks 3-4: rate pools and attended ratios ─────────────────────────
    eff = C.CONFIG_DATES["rate_pools_live"]
    drift = (1 + C.POOL_RATE_DRIFT) ** ((eff - C.START_DATE).days / 365.25)
    pools, att = [], []
    notes = {"SWS": "one operator runs three machines; attended about a third of cycle time",
             "EDM": "unattended burns overnight; operator loads and checks",
             "HMC": "pallet changers; operator covers two machines on the day shift",
             "MTN": "operator present most of the cycle; bar feeder on two machines",
             "FAX": "attended through the program; first-article checks each setup",
             "LTH": "attended, with bar feeder on the long runs",
             "VMC": "attended", "SAW": "attended", "MDP": "attended", "DBR": "attended", "INS": "attended", "ASM": "attended"}
    for w in wcs.itertuples():
        pools.append({"work_center_id": w.work_center_id, "effective_date": eff,
                      "labor_rate": round(w.true_labor_rate * drift, 2), "burden_rate": round(w.true_burden_rate * drift, 2),
                      "attended_ratio": w.attended_ratio, "basis": "rate history, machine hours and headcount by cell"})
        att.append({"work_center_id": w.work_center_id, "attended_ratio": w.attended_ratio,
                    "observation_note": notes[w.group], "observed_by": "Production manager", "observation_week": 4})
    art["rate_pools"] = pd.DataFrame(pools)
    art["attended_ratios"] = pd.DataFrame(att)

    # ── weeks 3-5: estimate backfill onto historic jobs ───────────────────
    q_idx = quotes.set_index("quote_id")
    first_q = quotes.sort_values("quote_date").drop_duplicates("part_number").set_index("part_number")
    rows = []
    hist = jobs[jobs["release_date"] < C.CONFIG_DATES["estimate_to_job"]]
    for j in hist.itertuples():
        if j.job_type == "own_product":
            std = own_std.set_index("part_number").loc[j.part_number]
            rows.append({"job_id": j.job_id, "quote_id": None, "method": "own-product standard cost", "match_confidence": 1.0,
                         "est_material": round(std["standard_cost"] * 0.35 * j.quantity, 2), "est_setup_hours": None,
                         "est_run_hours": None, "est_outside": round(std["standard_cost"] * 0.10 * j.quantity, 2),
                         "est_total_cost": round(std["standard_cost"] * j.quantity, 2), "material_price_date": std["standard_cost_date"]})
            continue
        if rng.random() > C.ESTIMATE_BACKFILL_SHARE:
            rows.append({"job_id": j.job_id, "quote_id": None, "method": "no quote line found", "match_confidence": 0.0,
                         "est_material": None, "est_setup_hours": None, "est_run_hours": None, "est_outside": None,
                         "est_total_cost": None, "material_price_date": None})
            continue
        if j.quote_id is not None and j.quote_id in q_idx.index:
            q = q_idx.loc[j.quote_id]; qid = j.quote_id; method, conf = "won quote line on the job", 1.0
        else:
            q = first_q.loc[j.part_number]; qid = q["quote_id"]; method, conf = "standing price quote, nearest break scaled to job quantity", round(float(rng.uniform(0.85, 0.97)), 2)
        # the nearest quantity break, per piece, times the job quantity: the way the ERP now does it on conversion
        e, _ = QJ.break_estimate(BREAKS[0], qid, j.quantity)
        rows.append({"job_id": j.job_id, "quote_id": qid, "method": method, "match_confidence": conf,
                     "est_material": e["est_material"], "est_setup_hours": e["est_setup_hours"],
                     "est_run_hours": e["est_run_hours"], "est_outside": e["est_outside"],
                     "est_total_cost": e["est_total_cost"], "material_price_date": q["quote_date"]})
    bf = pd.DataFrame(rows)
    art["estimate_backfill"] = bf

    # ── weeks 3-5: outside processing attribution ─────────────────────────
    rows = []
    hist_osp = osp[osp["job_id"].isna() & (osp["order_date"] < C.CONFIG_DATES["po_job_required"])]
    for r in hist_osp.to_dict("records"):
        pn_on_line = next((t for t in str(r["description"] or "").split(" ") if t.startswith(("P-", "N-", "BC-"))), None)
        by_part = pn_on_line is not None
        u = rng.random()
        if u < C.OSP_ATTRIBUTED_SHARE:
            wrong = rng.random() < 0.02
            job = r["_true_job_id"]
            if wrong:
                # a near miss: another open job of the same part (or, without a part number, the same
                # customer) released in the weeks before the order, the way a person matching by hand errs
                od = pd.Timestamp(r["order_date"])
                rel = pd.to_datetime(jobs["release_date"])
                same = jobs[((jobs["part_number"] == pn_on_line) if by_part else (jobs["customer_id"] == r["_customer_id"]))
                            & (rel <= od) & (rel >= od - pd.Timedelta(days=60)) & (jobs["job_id"] != job)]
                if len(same) >= 1:
                    job = str(same["job_id"].iloc[int(rng.integers(len(same)))])
            rows.append({"po_id": r["po_id"], "job_id": job,
                         "method": "part number and date on the PO line" if by_part else "vendor, service, quantity and receipt window",
                         "confidence": round(float(rng.uniform(0.88, 0.99) if by_part else rng.uniform(0.62, 0.85)), 2),
                         "confirmed_by": "Controller" if by_part else "Production manager", "status": "attributed"})
        else:
            rows.append({"po_id": r["po_id"], "job_id": None, "method": "no match: generic description, several open jobs",
                         "confidence": 0.0, "confirmed_by": None, "status": "residual in GL"})
    art["po_attribution"] = pd.DataFrame(rows)

    # ── weeks 4-6: configuration change log ───────────────────────────────
    labels = {
        "estimate_to_job": ("Quoting", "Estimate carries to the job on conversion, by element"),
        "po_job_required": ("Purchasing", "Job number required on outside-processing purchase orders"),
        "rate_pools_live": ("Work centers", "Work-center rate pools replace the blended shop rate"),
        "terminals_at_cells": ("Data collection", "Clock terminals moved from the door to the cells"),
        "one_open_operation": ("Data collection", "One open operation per employee"),
        "auto_close": ("Data collection", "Open clock records close at shift end with a review flag"),
        "labor_type_codes": ("Data collection", "Setup, run, rework and indirect codes"),
        "scrap_reason_req": ("Quality", "Reason code required on every scrap event"),
        "monitoring_to_jobs": ("Machine monitoring", "Feed posts machine hours to jobs by program and open job"),
        "standard_fallback": ("Job costing", "Missing scan costs the operation at the routing standard, tagged estimated"),
    }
    art["config_change_log"] = pd.DataFrame([{"change": labels[k][1], "module": labels[k][0], "effective_date": d,
                                              "changed_by": "ERP administrator", "engagement_week": C.engagement_week(d)}
                                             for k, d in C.CONFIG_DATES.items()]).sort_values("effective_date")

    # ── weeks 6-8: routing standard refresh ───────────────────────────────
    rep_parts = parts.loc[parts["job_type"] == "repeat", "part_number"]
    # every repeat part that ran on a monitored cell in the window has cycles to measure
    ran = set(jobs.loc[jobs["job_id"].isin(ops.loc[ops["monitored"], "job_id"]), "part_number"])
    measured = set(rep_parts) & ran
    rows = []
    routings_after = routings.copy()
    std_effective = {}
    cnc = routings[~routings["work_center_group"].isin(C.SECONDARY_GROUPS)]
    # the three lots measured for a part share their conditions, so the measurement
    # error is drawn once per part
    part_factor = {pn: (float(rng.normal(1, C.MEASURED_CYCLE_NOISE)), float(rng.normal(1, C.MEASURED_CYCLE_NOISE * 1.5)))
                   for pn in sorted(measured)}
    for r in cnc.itertuples():
        if r.part_number not in measured:
            continue
        eff = _week_date(6) + timedelta(days=int(rng.integers(0, 21)))
        f_run, f_setup = part_factor[r.part_number]
        meas_run = r.true_run_min_per_piece * f_run * float(rng.normal(1, 0.02))
        meas_setup = r.true_setup_hours * f_setup * float(rng.normal(1, 0.03))
        u = rng.random()
        if u < C.ESTIMATOR_DISPUTE_SHARE:
            decision, new_run, new_setup = "disputed, standard kept", r.std_run_min_per_piece, r.std_setup_hours
            note = "Estimator disputes the measured cycle: sample lots ran with a worn tool"
        elif u < C.ESTIMATOR_DISPUTE_SHARE + 0.04:
            decision = "disputed, adjusted"; new_run = (meas_run + r.std_run_min_per_piece) / 2; new_setup = meas_setup
            note = "Estimator and production manager split the difference pending the next lot"
        else:
            decision, new_run, new_setup, note = "accepted", meas_run, meas_setup, "Measured over the last three lots"
        rows.append({"part_number": r.part_number, "op_seq": r.op_seq, "work_center_id": r.work_center_id,
                     "old_std_run_min": r.std_run_min_per_piece, "measured_run_min": round(meas_run, 3),
                     "new_std_run_min": round(new_run, 3), "old_std_setup_hours": r.std_setup_hours,
                     "measured_setup_hours": round(meas_setup, 2), "new_std_setup_hours": round(new_setup, 2),
                     "reviewer_decision": decision, "reviewed_by": "Estimator", "note": note, "effective_date": eff})
        routings_after.loc[r.Index, ["std_run_min_per_piece", "std_setup_hours", "last_updated"]] = [round(new_run, 3), round(new_setup, 2), eff]
        std_effective[r.part_number] = max(std_effective.get(r.part_number, eff), eff)
    art["standard_update_log"] = pd.DataFrame(rows)

    # ── weeks 7-9: repricing review ───────────────────────────────────────
    # current cost at today's material prices, the rate pools and the refreshed standards
    cm_after = CostModel(parts, routings_after, wcs, cm_mat(cm), cm_vend(cm), cm_vp(cm))
    rows = []
    rep_jobs = jobs[jobs["job_type"] == "repeat"]
    years = (C.END_DATE - C.START_DATE).days / 365.25
    vol = (rep_jobs.groupby("part_number")["quantity"].sum() / years).round()
    typical_lot = rep_jobs.groupby("part_number")["quantity"].median()
    fam_lot = rep_jobs.groupby("part_family")["quantity"].median()
    for pn in rep_parts:
        p = p_idx.loc[pn]
        annual = int(vol.get(pn, 0))
        lot = int(typical_lot.get(pn, fam_lot.get(p["part_family"], C.LOT_SIZE_MEDIAN)))
        est = cm_after.estimate(pn, lot, C.END_DATE, standards="erp", rates="pool", material="actual", osp_base=plan[pn])
        cur = est["est_total_cost"] / lot
        price = standing.loc[pn, "standing_price_at_start"] * QJ._letters_between(C.START_DATE, C.END_DATE)
        rows.append({"part_number": pn, "customer_id": p["customer_id"], "part_family": p["part_family"], "annual_volume": annual,
                     "standing_price": round(price, 2), "current_unit_cost": round(cur, 2),
                     "margin_on_price": round((price - cur) / price, 4), "target_price": round(cur * (1 + C.TARGET_MARKUP), 2)})
    rp = pd.DataFrame(rows)
    rp["gap_to_target_annual"] = ((rp["target_price"] - rp["standing_price"]).clip(lower=0) * rp["annual_volume"]).round(2)
    # the decisions themselves are taken from the pipeline's queue: see repricing_review.py

    # own products: standard cost at launch against today's cost (M8)
    rows = []
    for r in own_std.itertuples():
        est = cm_after.estimate(r.part_number, 100, C.END_DATE, standards="erp", rates="pool", material="actual", osp_base=plan[r.part_number])
        cur = est["est_total_cost"] / 100
        rows.append({"part_number": r.part_number, "standard_cost": r.standard_cost, "standard_cost_date": r.standard_cost_date,
                     "list_price": r.list_price, "current_unit_cost": round(cur, 2), "below_cost": r.list_price < cur,
                     "margin_on_price": round((r.list_price - cur) / r.list_price, 4), "reviewed_by": "Controller",
                     "review_week": 8})
    own_review = pd.DataFrame(rows)
    art["own_product_review"] = own_review[["part_number", "reviewed_by", "review_week"]]

    # ── weeks 8-11: the actions the owner decided, taken and not taken ────
    # the record the close-out meeting leaves: each action on the diagnostic's findings,
    # who decided it, when, and for the ones not taken, why
    co = parts.loc[parts["change_order_customer"], "customer_id"].dropna()
    co = str(co.iloc[0]) if len(co) else None
    acts = [
        ("A1", "Routing standards refreshed from the measured cycles", "taken", "Estimator", 8, "Repeat parts that ran on a monitored cell", ""),
        ("A2", "Repeat parts repriced through the monthly review", "taken", "Controller, owner", 9, "Repeat parts below current cost plus target", ""),
        ("A3", "Low-volume parts with no path to target exited at the next release", "taken", "Owner", 9, "Repeat parts below target, below median volume", ""),
        ("A4", "Plating vendor's current price carried in the quoting module", "taken", "Estimator", 5, "Every quote with plating", ""),
        ("A5", "Titanium and Inconel speeds and feeds validated against the measured cycles", "taken", "Estimator, CNC cell leads", 10, "Quotes in the two alloys", ""),
        ("A6", "Lots under 25 pieces on mill-turn and 5-axis quoted at the measured first-article setup", "taken", "Estimator", 10, "Small-lot quotes", ""),
        ("A7", "Change-order line on every revision issued after release", "taken", "Owner", 9, f"Jobs for {co}", ""),
        ("A8", "Long-cycle parts routed to the newer vertical mills when they have capacity", "taken", "Production manager", 11, "Jobs on VMC-01 and VMC-02", ""),
        ("A9", "Own-product list prices moved to current cost plus target at the next price list", "taken", "Controller", 8, "The fourteen own products", ""),
        ("D1", "Repeat parts held at the current price", "deferred", "Controller, owner", 9, "Repeat parts below target",
         "A reason recorded per part: volume commitment, blanket price fixed until renewal, or margin acceptable on the full program; each part returns at the next monthly review"),
        ("D3", "Back-billing the revision work of the last twelve months", "declined", "Owner", 9, f"Jobs for {co}",
         "The contract allows it; the owner judged the relationship cost higher than the recovery and chose to bill new revisions only"),
        ("D4", "Replacing the two oldest vertical mills", "deferred", "Owner", 11, "VMC-01 and VMC-02",
         "Goes to the capital plan review in the fourth quarter; routing long-cycle parts to the newer mills costs nothing in the meantime"),
        ("D5", "Dropping the own product that sells below cost at list", "declined", "Owner", 8, "One own product",
         "Customers buy it with the rest of the line; repriced with the others instead"),
    ]
    art["engagement_actions"] = pd.DataFrame([{"action_id": a, "action": t, "decision": dcn, "decided_by": by,
                                               "engagement_week": wk, "decision_date": _week_date(wk, 3), "scope": sc, "reason": why or None}
                                              for a, t, dcn, by, wk, sc, why in acts])

    return {"artifacts": art, "routings_after": routings_after, "std_effective": std_effective,
            "current_cost_review": rp, "own_product_review": own_review}


def cm_mat(cm):
    rows = [{"material_spec": s, "month": m.to_timestamp().date(), "actual_price_per_lb": v,
             "list_price_per_lb": cm.mat_list[(s, m)]} for (s, m), v in cm.mat_actual.items()]
    return pd.DataFrame(rows)


def cm_vend(cm):
    return cm.vendors.reset_index()


def cm_vp(cm):
    return pd.DataFrame([{"vendor_id": v, "month": m.to_timestamp().date(), "price_index": x} for (v, m), x in cm.vendor_index.items()])
