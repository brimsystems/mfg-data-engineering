"""Quotes, standing prices and jobs.

The quoting module holds every quote line: the first quote on every repeat part
(years before the window), the new-work quotes inside the window with their win,
loss or expiry, and the requotes. Repeat parts run at the standing price set at
first quote, lifted only by the annual across-the-board letter (M4). Own products
sell from a price list set at launch against a standard cost never revised (M8).

Jobs are released against those prices. Each job carries the truth of what it
actually took: hours by operation with the small-lot setups (P2), the estimator's
blind spot on titanium and Inconel (P5) and the change-order customer's unbilled
hours (P3), plus material at the price of the day and outside processing at the
vendor's price of the day. The transactions are built from that truth, and the
defects are laid over the transactions, so the numbers move for reasons the
audit can name.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config as C
from .costing import CostModel, blended_rate


def _letters_between(d0, d1):
    """Cumulative across-the-board increase applied between two dates."""
    f = 1.0
    for yr, pct in C.ANNUAL_INCREASE_LETTER.items():
        eff = date(yr, *C.ANNUAL_INCREASE_DATE)
        if d0 < eff <= d1:
            f *= 1 + pct
    return f


def _last_letter_date(d):
    last = None
    for yr in sorted(C.ANNUAL_INCREASE_LETTER):
        eff = date(yr, *C.ANNUAL_INCREASE_DATE)
        if eff <= d:
            last = eff
    return last


def osp_plan(rng, cm, parts):
    """For every part, the outside services it uses: (service, vendor, base $/piece)."""
    plan = {}
    for pn, p in parts.set_index("part_number").iterrows():
        items = []
        for svc in [s for s in str(p["outside_services"]).split("|") if s and s != "nan"]:
            vend = str(rng.choice(cm.vendor_for_service[svc]))
            lo, hi = C.OUTSIDE_SERVICES[svc][2]
            base = float(np.exp(rng.uniform(np.log(lo), np.log(hi)))) * (p["weight_lb"] ** 0.25)
            items.append((svc, vend, round(base, 3)))
        plan[pn] = items
    return plan


def quotes_and_prices(rng, cm, parts, plan, top_customer=None, industry=None):
    """Quote lines and the price each part runs at."""
    quotes, price_rows = [], []
    industry = industry or {}
    estimators = [f"EST-{i + 1:02d}" for i in range(C.N_ESTIMATORS)]
    est_p = [C.SENIOR_ESTIMATOR_SHARE] + [(1 - C.SENIOR_ESTIMATOR_SHARE) / (C.N_ESTIMATORS - 1)] * (C.N_ESTIMATORS - 1)
    q_id = 0
    for pn, p in parts.set_index("part_number").iterrows():
        kind = p["job_type"]; fam = p["part_family"]
        role = C.PART_FAMILIES[fam][8]
        lot_f = C.FAMILY_LOT_FACTOR.get(fam, 1.0)
        if kind == "own_product":
            continue
        # the markup the estimator actually quoted: target with cushion or a competitive shave
        base_markup = float(rng.normal(*C.QUOTED_MARKUP)) + C.FAMILY_MARKUP_SHIFT.get(role, 0.0)
        if p["customer_id"] == top_customer:
            base_markup += C.TOP_CUSTOMER_MARKUP_SHIFT
        base_markup += C.INDUSTRY_MARKUP_SHIFT.get(industry.get(p["customer_id"]), 0.0)
        base_markup = float(np.clip(base_markup, 0.02, 0.70))
        if kind == "repeat":
            d = p["first_quote_date"]
            qty = int(max(5, rng.lognormal(np.log(C.LOT_SIZE_MEDIAN * lot_f), C.LOT_SIZE_SIGMA)))
            est = cm.estimate(pn, qty, d, osp_base=plan[pn])
            unit_cost = est["est_total_cost"] / qty
            unit_price = unit_cost * (1 + base_markup) * float(np.exp(rng.normal(0, C.ESTIMATE_NOISE)))
            q_id += 1
            quotes.append({"quote_id": f"Q-{q_id:06d}", "line": 1, "part_number": pn, "revision": p["revision"],
                           "customer_id": p["customer_id"], "quantity": qty,
                           "estimator_id": str(rng.choice(estimators, p=est_p)), "quote_date": d,
                           **{k: round(v, 2) for k, v in est.items()}, "quoted_price": round(unit_price, 2),
                           "status": "won", "won_job_id": None, "quoted_markup": round(base_markup, 4)})
            # the price the part ran at when the window opened: before a requote inside the
            # window the part ran at the same real price, less the letters since
            standing = unit_price * _letters_between(d, C.START_DATE) if d < C.START_DATE else unit_price / _letters_between(C.START_DATE, d)
            price_rows.append({"part_number": pn, "standing_price_at_start": standing, "quoted_markup": base_markup,
                               "first_unit_cost": unit_cost, "quoted_lot": qty})
        else:
            # new work: several quote lines over the part's life, each won, lost or expired
            n_lines = 1 + int(rng.poisson(C.NEW_PART_QUOTE_LINES))
            d0 = p["first_quote_date"]
            span_days = max(30, (C.END_DATE - d0).days)
            offsets = np.sort(rng.uniform(0, span_days, n_lines)); offsets[0] = 0
            for k, off in enumerate(offsets):
                d = d0 + timedelta(days=int(off))
                if d > C.END_DATE - timedelta(days=3):
                    continue
                qty = int(max(3, rng.lognormal(np.log(C.LOT_SIZE_MEDIAN * C.NEW_WORK_LOT_FACTOR * lot_f), C.LOT_SIZE_SIGMA)))
                est = cm.estimate(pn, qty, d, osp_base=plan[pn])
                markup = base_markup - float(rng.uniform(*C.NEW_WORK_DISCOUNT))
                unit_price = est["est_total_cost"] / qty * (1 + markup) * float(np.exp(rng.normal(0, C.ESTIMATE_NOISE)))
                u = rng.random()
                status = "won" if u < C.NEW_WORK_WIN_RATE else ("lost" if u < 0.85 else "expired")
                q_id += 1
                quotes.append({"quote_id": f"Q-{q_id:06d}", "line": 1, "part_number": pn, "revision": p["revision"],
                               "customer_id": p["customer_id"], "quantity": qty,
                               "estimator_id": str(rng.choice(estimators, p=est_p)), "quote_date": d,
                               **{k: round(v, 2) for k, v in est.items()}, "quoted_price": round(unit_price, 2),
                               "status": status, "won_job_id": None, "quoted_markup": round(markup, 4)})
    return pd.DataFrame(quotes), pd.DataFrame(price_rows).set_index("part_number")


def own_product_prices(rng, cm, parts, plan):
    """List prices set at launch from a standard cost never revised (M8)."""
    rows = []
    own = parts[parts["own_product_flag"]]
    for i, (_, p) in enumerate(own.iterrows()):
        pn = p["part_number"]; d = p["first_quote_date"]
        est = cm.estimate(pn, 100, d, standards="true", material="actual", osp_base=plan[pn])
        std_unit = est["est_total_cost"] / 100
        rows.append({"part_number": pn, "standard_cost": round(std_unit, 2), "standard_cost_date": d,
                     "list_price": round(std_unit * C.OWN_PRODUCT_LIST_MARKUP, 2)})
    return pd.DataFrame(rows)


def jobs(rng, cm, parts, routings, quotes, standing, own_std, plan):
    """Release jobs across the window and compute each job's truth."""
    p_idx = parts.set_index("part_number")
    fam_role = {f: v[8] for f, v in C.PART_FAMILIES.items()}
    days = (C.END_DATE - C.START_DATE).days + 1
    rows = []
    job_no = 0

    def new_job(pn, qty, release, quote_id, kind):
        nonlocal job_no
        job_no += 1
        p = p_idx.loc[pn]
        r = cm.routing_by_part[pn]
        lead = int(rng.integers(*C.JOB_LEAD_DAYS))
        due = release + timedelta(days=lead)
        late = rng.random() < 0.28
        completed = due + timedelta(days=int(rng.integers(1, 12))) if late else due - timedelta(days=int(rng.integers(0, 4)))
        completed = max(completed, release + timedelta(days=3))
        if completed > C.END_DATE:
            status, completed = "in_process", None
        else:
            status = "completed"
        # price
        if kind == "repeat":
            unit_price = standing.loc[pn, "standing_price_at_start"] * _letters_between(C.START_DATE, release)
        elif kind == "own_product":
            unit_price = float(own_std.set_index("part_number").loc[pn, "list_price"])
        else:
            unit_price = float(quotes.set_index("quote_id").loc[quote_id, "quoted_price"])
        # the truth of what the job took
        ops = []
        small = qty < C.SMALL_LOT_THRESHOLD
        for _, o in r.iterrows():
            grp = o["work_center_group"]
            setup = o["true_setup_hours"] * float(rng.lognormal(0, C.JOB_HOURS_NOISE))
            if small and grp in C.SMALL_LOT_GROUPS:
                setup *= float(rng.uniform(*C.SMALL_LOT_SETUP_MULT))
            run = qty * o["true_run_min_per_piece"] / 60 * float(rng.lognormal(0, C.JOB_HOURS_NOISE))
            if p["estimator_bias_material"] and grp not in C.SECONDARY_GROUPS:
                run *= 1 + float(rng.uniform(*C.ESTIMATOR_RUN_BIAS))
            extra = 0.0
            if p["change_order_customer"] and grp not in C.SECONDARY_GROUPS and rng.random() < C.CHANGE_ORDER_OP_SHARE:
                extra = (setup + run) * float(rng.uniform(*C.CHANGE_ORDER_SHARE_OF_OP))       # programming and first-article time after a revision change
            ops.append({"op_seq": int(o["op_seq"]), "work_center_id": o["work_center_id"], "group": grp,
                        "setup_hours": round(setup, 3), "run_hours": round(run, 3), "change_order_hours": round(extra, 3),
                        "program_number": o["program_number"]})
        return {"job_id": f"J-{job_no:06d}", "part_number": pn, "revision": p["revision"], "customer_id": p["customer_id"],
                "quantity": qty, "job_type": kind, "quote_id": quote_id, "release_date": release, "due_date": due,
                "completed_date": completed, "status": status, "unit_price": round(unit_price, 2),
                "price": round(unit_price * qty, 2), "ops": ops, "part_family": p["part_family"],
                "material_spec": p["material_spec"], "weight_lb": p["weight_lb"]}

    # repeat releases: each repeat part runs a few times a year, more for the big customers
    repeat = parts[parts["job_type"] == "repeat"]
    cust_w = parts.groupby("customer_id").size()
    for _, p in repeat.iterrows():
        n = 1 + int(rng.poisson(C.REPEAT_RELEASES_3Y))
        quoted_lot = int(standing.loc[p["part_number"], "quoted_lot"])
        for _ in range(n):
            d = C.START_DATE + timedelta(days=int(rng.uniform(0, days - 1)))
            # blanket releases run near the quoted lot
            qty = int(max(2, round(quoted_lot * rng.lognormal(0, C.RELEASE_LOT_NOISE))))
            rows.append(new_job(p["part_number"], qty, d, None, "repeat"))
    # new work: every won quote line becomes a job released a couple of weeks after the quote
    won = quotes[(quotes["status"] == "won") & (quotes["quote_date"] >= C.START_DATE)]
    for _, q in won.iterrows():
        d = q["quote_date"] + timedelta(days=int(rng.integers(7, 28)))
        if d > C.END_DATE - timedelta(days=2):
            continue
        rows.append(new_job(q["part_number"], int(q["quantity"]), d, q["quote_id"], "new"))
    # own products: stock orders every month or so
    for _, p in parts[parts["own_product_flag"]].iterrows():
        d = C.START_DATE + timedelta(days=int(rng.integers(0, 30)))
        while d <= C.END_DATE - timedelta(days=2):
            qty = int(max(20, rng.lognormal(np.log(C.OWN_PRODUCT_LOT_MEDIAN), 0.5)))
            rows.append(new_job(p["part_number"], qty, d, None, "own_product"))
            d += timedelta(days=int(rng.integers(20, 45)))
    jobs = pd.DataFrame(rows).sort_values("release_date").reset_index(drop=True)
    # renumber in release order so adjacent job numbers are adjacent in time (T3 needs that)
    jobs["job_id"] = [f"J-{i + 1:06d}" for i in range(len(jobs))]
    won_map = {}
    for _, j in jobs[jobs["quote_id"].notna()].iterrows():
        won_map[j["quote_id"]] = j["job_id"]
    quotes["won_job_id"] = quotes["quote_id"].map(won_map)
    return jobs
