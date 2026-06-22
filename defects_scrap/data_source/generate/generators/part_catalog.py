"""
ERP part master: one row per part number, with customer, material, complexity,
primary machine, standard setup and labor, unit price, the date the part number
was released, and the current drawing revision with its date.

The catalog is high mix: part numbers are released through the window and
drawings are revised, more often on complex parts.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from ..config import (
    RANDOM_SEED, START_DATE, END_DATE, CUSTOMERS, TOP_CUSTOMERS, TOP_CUSTOMER_REVENUE_SHARE,
    MATERIALS, MATERIAL_WEIGHTS, BRAKE_MATERIAL_WEIGHTS, MACHINES_DATA, MACHINE_TYPE_PART_SHARE, PARTS_AT_START,
    NEW_PARTS_PER_YEAR, COMPLEXITY_WEIGHTS, REVISIONS_PER_PART_YEAR,
    REVISION_WEIGHT_BY_COMPLEXITY, REVISION_LETTERS, STD_SETUP_MIN, UNIT_PRICE_RANGE,
    RUN_MINUTES_PER_PIECE, PART_DEMAND_SIGMA,
)

CATALOG_COLUMNS = ["part_number", "customer", "material_type", "complexity", "primary_machine",
                   "std_setup_min", "std_labor_hrs", "unit_price", "requires_welding",
                   "released_date", "current_revision", "revision_date"]


def build_part_catalog():
    """Returns (parts, revisions): the part master with working columns the
    scheduler uses, and the revision history (part, revision, effective date)."""
    rng = np.random.default_rng(RANDOM_SEED + 2)
    span_days = (END_DATE - START_DATE).days
    n_new = int(round(NEW_PARTS_PER_YEAR * span_days / 365.25))
    n = PARTS_AT_START + n_new

    # Customer order share: the five largest hold a fixed share of the total.
    rest = len(CUSTOMERS) - TOP_CUSTOMERS
    cust_w = np.array([TOP_CUSTOMER_REVENUE_SHARE / TOP_CUSTOMERS] * TOP_CUSTOMERS
                      + [(1 - TOP_CUSTOMER_REVENUE_SHARE) / rest] * rest)

    machine_by_type = {}
    for mid, _, mtype, _, _ in MACHINES_DATA:
        machine_by_type.setdefault(mtype, []).append(mid)
    types = list(MACHINE_TYPE_PART_SHARE)
    mean_rev_weight = sum(COMPLEXITY_WEIGHTS[c] * REVISION_WEIGHT_BY_COMPLEXITY[c] for c in COMPLEXITY_WEIGHTS)

    released = ([START_DATE.date() - timedelta(days=int(d)) for d in rng.integers(60, 2500, PARTS_AT_START)]
                + sorted(START_DATE.date() + timedelta(days=int(d)) for d in rng.integers(1, span_days - 5, n_new)))
    parts, revisions = [], []
    for i in range(n):
        pn = f"P-{1000 + i}"
        cust_idx = int(rng.choice(len(CUSTOMERS), p=cust_w))
        mtype = str(rng.choice(types, p=list(MACHINE_TYPE_PART_SHARE.values())))
        complexity = str(rng.choice(list(COMPLEXITY_WEIGHTS), p=list(COMPLEXITY_WEIGHTS.values())))
        material = str(rng.choice(list(MATERIALS), p=BRAKE_MATERIAL_WEIGHTS if mtype == "Bending" else MATERIAL_WEIGHTS))
        lo, hi = STD_SETUP_MIN[mtype]
        rlo, rhi = RUN_MINUTES_PER_PIECE[mtype]
        run_min = float(rng.uniform(rlo, rhi))

        # Drawing revisions inside the window, from the later of the window start
        # and the release date. Revision A is the released drawing.
        active_from = max(released[i], START_DATE.date())
        years = (END_DATE.date() - active_from).days / 365.25
        rate = REVISIONS_PER_PART_YEAR * REVISION_WEIGHT_BY_COMPLEXITY[complexity] / mean_rev_weight
        k = min(int(rng.poisson(rate * years)), len(REVISION_LETTERS) - 1)
        offsets = sorted(rng.integers(1, max(2, (END_DATE.date() - active_from).days), k).tolist())
        rev_dates = [active_from + timedelta(days=int(d)) for d in offsets]
        revisions.append({"part_number": pn, "revision": "A", "effective_date": released[i]})
        for j, d in enumerate(rev_dates, start=1):
            revisions.append({"part_number": pn, "revision": REVISION_LETTERS[j], "effective_date": d})

        parts.append({
            "part_number": pn,
            "customer": CUSTOMERS[cust_idx],
            "material_type": material,
            "complexity": complexity,
            "primary_machine": str(rng.choice(machine_by_type[mtype])),
            "std_setup_min": int(rng.integers(lo, hi + 1)),
            "std_labor_hrs": round(run_min * 15 / 60, 2),
            "unit_price": round(float(rng.uniform(*UNIT_PRICE_RANGE)), 2),
            "requires_welding": bool(mtype == "Welding" or rng.random() < 0.30),
            "released_date": released[i],
            "current_revision": REVISION_LETTERS[k],
            "revision_date": rev_dates[-1] if rev_dates else released[i],
            # working columns
            "machine_type": mtype,
            "run_min_per_piece": run_min,
            "demand_weight": float(cust_w[cust_idx] * rng.lognormal(0.0, PART_DEMAND_SIGMA)),
        })
        rng.uniform(size=2)     # holds the stream position for the parts that follow
    return pd.DataFrame(parts), pd.DataFrame(revisions)
