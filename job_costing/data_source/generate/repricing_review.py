"""The monthly repricing review, as the records it leaves: the controller and the owner
work down the repricing queue and decide every repeat part whose standing price sits
below current cost plus the target markup. They read the same current cost the
pipeline computes (int_current_cost), so every part below target carries a decision
and none is left pending.

Decisions carry judgment: most parts are repriced to current cost plus target; some
are held at the current price with the reason recorded (the owner declines to touch
two large-customer parts before contract renewal and says so); a few low-volume parts
with no path to target are exited at the next release.

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
    cc = con.execute("""select part_number, customer_id, standing_price, target_price, annual_volume, gap_to_target_annual
                        from int_current_cost where part_type = 'repeat' and standing_price < target_price
                        order by gap_to_target_annual desc, part_number""").df()
    # the largest account by revenue, from the job cost mart (a table, so no source files are read)
    top_cust = con.execute("""select customer_id from fct_job_cost where version = 'raw' and customer_id is not null
                              group by 1 order by sum(price) desc limit 1""").fetchone()[0]
    con.close()

    rng = np.random.default_rng(C.RANDOM_SEED + 707)
    rows, held_relationship = [], 0
    for r in cc.itertuples():
        u = rng.random()
        if r.customer_id == top_cust and held_relationship < 2 and r.gap_to_target_annual > 20000:
            d = ("hold", None, "Owner declines: relationship account, revisit at contract renewal", "Owner"); held_relationship += 1
        elif u < C.REPRICING["reprice"]:
            d = ("reprice", round(r.target_price * float(rng.uniform(0.97, 1.02)), 2),
                 "Repriced to current cost plus target; customer notified with the cost basis", "Controller")
        elif u < C.REPRICING["reprice"] + C.REPRICING["hold"]:
            d = ("hold", None, str(rng.choice(HOLD_REASONS)), "Controller")
        else:
            d = ("exit", None, "Decline the next release unless repriced; low volume, no path to target", "Owner")
        rows.append({"part_number": r.part_number, "customer_id": r.customer_id, "decision": d[0], "new_price": d[1],
                     "rationale": d[2], "decided_by": d[3], "decision_date": _week_date(7) + timedelta(days=int(rng.integers(0, 21)))})
    out = repo / "data_source" / "raw" / "remediation" / "repricing_decisions.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    dec = pd.DataFrame(rows)["decision"].value_counts().to_dict()
    print(f"Repricing review: {len(rows)} parts below target decided: {dec}")


if __name__ == "__main__":
    run()
