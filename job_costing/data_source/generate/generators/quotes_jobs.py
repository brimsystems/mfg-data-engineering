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


def _rev_at(p, d):
    """The part's revision on a date: the prior one before a change inside the window."""
    ch = p.get("revision_change_date") if hasattr(p, "get") else None
    if ch is not None and not pd.isna(ch) and d < ch:
        return p["prior_revision"]
    return p["revision"]


def _cell_sense(cm, pn, qty, d):
    """The estimator's feel for the cells a part runs through: work that runs on the
    5-axis or the HMC gets priced up for it even though the ERP costs every cell at the
    blended rate. He carries part of the difference, and never prices down for cheap cells."""
    if not C.CELL_SENSE:
        return 1.0
    if not hasattr(cm, "_avg_pool"):
        # the shop's hours-weighted average pool rate: the level the blended rate stands for
        r = pd.concat(cm.routing_by_part.values())
        h = r["std_setup_hours"] + 50 * r["std_run_min_per_piece"] / 60
        rate = r["work_center_id"].map(lambda w: cm.pool_rate(w, C.START_DATE))
        cm._avg_pool = float((h * rate).sum() / h.sum())
    r = cm.routing_by_part[pn]
    h = r["std_setup_hours"] + qty * r["std_run_min_per_piece"] / 60
    part_rate = float((h * r["work_center_id"].map(lambda w: cm.pool_rate(w, C.START_DATE))).sum() / max(h.sum(), 1e-6))
    return max(1.0, part_rate / cm._avg_pool) ** C.CELL_SENSE


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
            estimator = str(rng.choice(estimators, p=est_p))
            basis = "spreadsheet" if rng.random() < C.SPREADSHEET_OVERRIDE_SHARE[estimator] else "ERP"
            est = _line_estimate(rng, cm, pn, qty, d, basis, plan[pn])
            unit_cost = est["est_total_cost"] / qty
            noise = float(np.exp(rng.normal(0, C.ESTIMATE_NOISE))) * _cell_sense(cm, pn, qty, d)
            unit_price = unit_cost * (1 + base_markup) * noise
            q_id += 1
            quotes.append({"quote_id": f"Q-{q_id:06d}", "line": 1, "part_number": pn, "revision": _rev_at(p, d),
                           "customer_id": p["customer_id"], "quantity": qty,
                           "estimator_id": estimator, "quote_date": d, "estimate_basis": basis,
                           **{k: round(v, 2) for k, v in est.items()}, "quoted_price": round(unit_price, 2),
                           "status": "won", "won_job_id": None, "quoted_markup": round(base_markup, 4), "price_noise": noise})
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
                estimator = str(rng.choice(estimators, p=est_p))
                basis = "spreadsheet" if rng.random() < C.SPREADSHEET_OVERRIDE_SHARE[estimator] else "ERP"
                est = _line_estimate(rng, cm, pn, qty, d, basis, plan[pn])
                markup = base_markup - float(rng.uniform(*C.NEW_WORK_DISCOUNT))
                if p["customer_id"] == f"CUST-{C.LOSS_CUSTOMER_RANK:03d}":
                    # won by matching a competitor's bid: priced a little under the shop's own estimate
                    markup = C.LOSS_CUSTOMER_NEW_WORK_MARKUP[0] + (markup - base_markup + 0.20) / 0.16 * (C.LOSS_CUSTOMER_NEW_WORK_MARKUP[1] - C.LOSS_CUSTOMER_NEW_WORK_MARKUP[0])
                noise = float(np.exp(rng.normal(0, C.ESTIMATE_NOISE))) * _cell_sense(cm, pn, qty, d)
                unit_price = est["est_total_cost"] / qty * (1 + markup) * noise
                u = rng.random()
                status = "won" if u < C.NEW_WORK_WIN_RATE else ("lost" if u < 0.85 else "expired")
                q_id += 1
                quotes.append({"quote_id": f"Q-{q_id:06d}", "line": 1, "part_number": pn, "revision": p["revision"],
                               "customer_id": p["customer_id"], "quantity": qty,
                               "estimator_id": estimator, "quote_date": d, "estimate_basis": basis,
                               **{k: round(v, 2) for k, v in est.items()}, "quoted_price": round(unit_price, 2),
                               "status": status, "won_job_id": None, "quoted_markup": round(markup, 4), "price_noise": noise})
    standing = pd.DataFrame(price_rows).set_index("part_number")
    _blanket_renewals(rng, cm, parts, plan, standing)
    return pd.DataFrame(quotes), standing


def _blanket_renewals(rng, cm, parts, plan, standing):
    """The biggest programs are repriced when the blanket order renews: the estimator
    reworks the price at that day's cost and the customer signs the new blanket. The
    quote on file stays the original one; the part simply runs at the renewed price,
    and the annual letters apply from there."""
    lot_value = standing["quoted_lot"] * standing["standing_price_at_start"]
    big = lot_value[lot_value >= lot_value.quantile(1 - C.BLANKET_RENEWAL_TOP_SHARE)].index
    p_idx = parts.set_index("part_number")
    for pn in big:
        if rng.random() >= C.BLANKET_RENEWAL_SHARE:
            continue
        d = C.START_DATE - timedelta(days=int(rng.uniform(*C.BLANKET_RENEWAL_DAYS_BEFORE_START)))
        if d <= p_idx.loc[pn, "first_quote_date"]:
            continue
        qty = int(standing.loc[pn, "quoted_lot"])
        est = cm.estimate(pn, qty, d, material="actual", osp_base=plan[pn])
        noise = float(np.exp(rng.normal(0, C.ESTIMATE_NOISE))) * _cell_sense(cm, pn, qty, d)
        price = est["est_total_cost"] / qty * (1 + standing.loc[pn, "quoted_markup"]) * noise
        standing.loc[pn, "standing_price_at_start"] = price * _letters_between(d, C.START_DATE)


def _line_estimate(rng, cm, pn, qty, d, basis, osp_base):
    """The estimate on a quote line. On the ERP basis the material is the ERP's issued
    price, the vendor price is the last purchase order's and the hours are the routing
    standards. On the spreadsheet basis the estimator's sheet supplies the list price
    (refreshed irregularly, M5), the old plating rate (P6) and his own judgment on the
    hours."""
    if basis == "ERP":
        return cm.estimate(pn, qty, d, material="actual", osp_base=osp_base)
    est = cm.estimate(pn, qty, d, material="list", osp_base=osp_base)
    f = float(rng.normal(1, C.SPREADSHEET_HOURS_NOISE))
    rate = est["est_labor"] / max(est["est_setup_hours"] + est["est_run_hours"], 1e-6)
    est["est_setup_hours"] *= f; est["est_run_hours"] *= f
    est["est_labor"] = (est["est_setup_hours"] + est["est_run_hours"]) * rate
    est["est_total_cost"] = est["est_material"] + est["est_labor"] + est["est_outside"]
    return est


def _nice(q):
    """A quantity break the way a quote shows it: 25, 50, 100, 250."""
    q = max(1, int(round(q)))
    step = 5 if q < 60 else 10 if q < 200 else 25 if q < 600 else 50
    return max(step, int(round(q / step)) * step)


def quote_breaks(rng, cm, quotes, plan):
    """The quantity breaks on every quote line: the estimate and the unit price at each.
    Smaller breaks carry a little more markup, larger ones a little less, and the
    line's own judgment noise runs through all of them."""
    rows = []
    for q in quotes.to_dict("records"):
        seen = set()
        seq = 0
        for f in C.QUANTITY_BREAKS:
            bq = _nice(q["quantity"] * f)
            if bq in seen:
                continue
            seen.add(bq); seq += 1
            est = _line_estimate(rng, cm, q["part_number"], bq, q["quote_date"], q["estimate_basis"], plan[q["part_number"]])
            markup = q["quoted_markup"] - C.BREAK_MARKUP_STEP * np.log2(bq / q["quantity"])
            unit_price = est["est_total_cost"] / bq * (1 + markup) * q["price_noise"]
            rows.append({"quote_id": q["quote_id"], "line": q["line"], "break_seq": seq, "quantity": bq,
                         **{k: round(v, 2) for k, v in est.items()}, "quoted_price": round(unit_price, 2)})
    return pd.DataFrame(rows)


def nearest_break(breaks, quote_id, qty):
    """The break on the line closest to the ordered quantity, as the ERP picks it."""
    b = breaks[breaks["quote_id"] == quote_id]
    i = (np.log(b["quantity"] / qty)).abs().idxmin()
    return b.loc[i]


def break_estimate(breaks, quote_id, qty):
    """The estimate a job gets from its quote line: the nearest break's figures per
    piece, times the ordered quantity. Setup is amortized at the break's quantity, so
    a quantity between breaks carries a small, honest error."""
    b = nearest_break(breaks, quote_id, qty)
    f = qty / b["quantity"]
    return {k: round(float(b[k]) * f, 2) for k in ["est_material", "est_setup_hours", "est_run_hours", "est_outside", "est_labor", "est_total_cost"]}, b


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


def jobs(rng, cm, parts, routings, quotes, standing, own_std, plan, breaks):
    """Release jobs across the window and compute each job's truth."""
    p_idx = parts.set_index("part_number")
    fam_role = {f: v[8] for f, v in C.PART_FAMILIES.items()}
    days = (C.END_DATE - C.START_DATE).days + 1
    rows = []
    job_no = 0

    def new_job(pn, qty, release, quote_id, kind, first_after_rev=False):
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
            unit_price = float(nearest_break(breaks, quote_id, qty)["quoted_price"])
        # the truth of what the job took
        ops = []
        small = qty < C.SMALL_LOT_THRESHOLD
        for _, o in r.iterrows():
            grp = o["work_center_group"]
            setup = o["true_setup_hours"] * float(rng.lognormal(0, C.JOB_HOURS_NOISE))
            if small and grp in C.SMALL_LOT_GROUPS:
                setup *= float(rng.uniform(*C.SMALL_LOT_SETUP_MULT))
            run = qty * o["true_run_min_per_piece"] / 60 * float(rng.lognormal(0, C.JOB_HOURS_NOISE))
            wc = o["work_center_id"]      # the floor schedule puts the operation on whichever machine in the cell frees up first
            if first_after_rev and grp not in C.SECONDARY_GROUPS:
                setup *= float(rng.uniform(*C.FIRST_RUN_AFTER_REVISION_SETUP))
                run *= float(rng.uniform(*C.FIRST_RUN_AFTER_REVISION_RUN))
            if p["estimator_bias_material"] and grp not in C.SECONDARY_GROUPS:
                run *= 1 + float(rng.uniform(*C.ESTIMATOR_RUN_BIAS))
            extra = 0.0
            if p["change_order_customer"] and grp not in C.SECONDARY_GROUPS and rng.random() < C.CHANGE_ORDER_OP_SHARE:
                extra = (setup + run) * float(rng.uniform(*C.CHANGE_ORDER_SHARE_OF_OP))       # programming and first-article time after a revision change
            ops.append({"op_seq": int(o["op_seq"]), "work_center_id": wc, "group": grp,
                        "setup_hours": round(setup, 3), "run_hours": round(run, 3), "change_order_hours": round(extra, 3),
                        "program_number": o["program_number"]})
        return {"job_id": f"J-{job_no:06d}", "part_number": pn, "revision": _rev_at(p, release), "customer_id": p["customer_id"],
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
        dates = sorted(C.START_DATE + timedelta(days=int(rng.uniform(0, days - 1))) for _ in range(n))
        ch = p["revision_change_date"]
        first_after = next((d for d in dates if ch is not None and not pd.isna(ch) and d >= ch), None)
        for d in dates:
            # blanket releases run near the quoted lot
            qty = int(max(2, round(quoted_lot * rng.lognormal(0, C.RELEASE_LOT_NOISE))))
            rows.append(new_job(p["part_number"], qty, d, None, "repeat", first_after_rev=(d == first_after)))
    # new work: every won quote line becomes a job released a couple of weeks after the quote
    won = quotes[(quotes["status"] == "won") & (quotes["quote_date"] >= C.START_DATE)]
    for _, q in won.iterrows():
        d = q["quote_date"] + timedelta(days=int(rng.integers(7, 28)))
        if d > C.END_DATE - timedelta(days=2):
            continue
        qty = int(max(2, round(q["quantity"] * rng.lognormal(0, C.ORDER_QTY_NOISE))))
        rows.append(new_job(q["part_number"], qty, d, q["quote_id"], "new"))
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
