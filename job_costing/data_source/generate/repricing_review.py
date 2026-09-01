"""The monthly repricing review, as the records it leaves: the controller and the owner
work down the repricing queue and decide every repeat part whose standing price sits
below current cost plus the target markup. They read the same current cost the
pipeline computes (int_current_cost), so every part below target carries a decision
and none is left pending.

Decisions follow the shop's pricing policy, set by the owner and the controller in the
interviews: a routine increase (up to the size of an annual letter) is taken; a larger
one is taken where the driver is material or outside processing documented part by part,
and held otherwise; a large gap on a small part is exited, and on a large program taken
in two steps. Every held part carries its reason.

Runs between the two dbt passes:  dbt build (all but the queue) -> this -> dbt build
of the decisions and the queue.  python -m data_source.generate.repricing_review
"""
from __future__ import annotations

from datetime import timedelta

import duckdb
import numpy as np
import pandas as pd

from . import config as C

HOLD_REASONS = ["Volume commitment through year end", "Price fixed in the current blanket order; revisit at renewal",
                "Margin acceptable on the full program"]


def _week_date(week, day=0):
    return C.ENGAGEMENT_START + timedelta(days=7 * (week - 1) + day)


def run():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    con = duckdb.connect(str(repo / "data_source" / "job_costing.duckdb"), read_only=True)
    cc = con.execute("""select part_number, customer_id, standing_price, target_price, annual_volume, gap_to_target_annual,
                               moved_material, moved_standard, moved_rate, moved_outside
                        from int_current_cost where part_type = 'repeat' and standing_price < target_price
                        order by gap_to_target_annual desc, part_number""").df()
    con.close()

    cc["annual_revenue"] = cc["standing_price"] * cc["annual_volume"]
    cc["gap"] = cc["target_price"] / cc["standing_price"] - 1
    # the share of what moved since the last quote that is material or outside processing: the
    # drivers a customer accepts as a pass-through when they are documented part by part
    moved = cc[["moved_material", "moved_standard", "moved_rate", "moved_outside"]].clip(lower=0)
    cc["pass_through"] = (moved["moved_material"] + moved["moved_outside"]) / moved.sum(axis=1).replace(0, np.nan)
    big_program = cc["annual_revenue"].quantile(C.REPRICING_POLICY["big_program_quantile"])
    small_part = cc["annual_revenue"].quantile(C.REPRICING_POLICY["small_part_quantile"])
    P = C.REPRICING_POLICY
    full = lambda r, why, by="Controller": ("reprice", round(r.target_price * float(rng.uniform(1.00, 1.02)), 2), why, by)
    half = lambda r: ("reprice", round(r.standing_price + (r.target_price - r.standing_price) / 2, 2),
                      "Repriced halfway now, with the cost drivers documented; the balance at the blanket renewal", "Owner")
    rows = []
    for r in cc.itertuples():
        rng = np.random.default_rng([C.RANDOM_SEED, 707, int(r.part_number.split("-")[1])])      # one stream per part
        pt = r.pass_through if pd.notna(r.pass_through) else 0.0
        if r.gap <= P["routine_increase"]:
            d = full(r, "Within the routine range; repriced to current cost plus target with the cost basis")
        elif r.gap <= P["documented_increase"]:
            if pt >= P["pass_through_share"]:
                d = full(r, "Material and outside-processing pass-through, documented part by part")
            elif r.annual_revenue >= big_program:
                d = half(r)
            else:
                d = ("hold", None, str(rng.choice(HOLD_REASONS)), "Controller")
        elif r.annual_revenue <= small_part:
            d = ("exit", None, "Decline the next release unless repriced; low volume, no path to target", "Owner")
        elif r.annual_revenue >= big_program or pt >= P["pass_through_share"]:
            d = half(r)
        else:
            d = ("hold", None, str(rng.choice(HOLD_REASONS)), "Owner")
        rows.append({"part_number": r.part_number, "customer_id": r.customer_id, "decision": d[0], "new_price": d[1],
                     "rationale": d[2], "decided_by": d[3], "decision_date": _week_date(7) + timedelta(days=int(rng.integers(0, 21)))})
    out = repo / "data_source" / "raw" / "remediation" / "repricing_decisions.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    dec = pd.DataFrame(rows)["decision"].value_counts().to_dict()
    print(f"Repricing review: {len(rows)} parts below target decided: {dec}")


if __name__ == "__main__":
    run()
