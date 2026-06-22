"""
The shop floor, day by day: work orders released by the planner, jobs sequenced
on each machine and shift, operators assigned, material lots received and
pulled, and the probability that a piece fails final inspection on each job.

Produces the ERP work orders, the MES job log, the Materials lot receipts and a
per-job working table that the inspection and scrap modules read.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .. import config as C
from ..faults.transformations import part_as_entered, lot_as_entered

_TYPE_OF = {m[0]: m[2] for m in C.MACHINES_DATA}
_MACHINES_OF = {}
for _mid, _, _mtype, _, _ in C.MACHINES_DATA:
    _MACHINES_OF.setdefault(_mtype, []).append(_mid)
_MAX_EXTENSION_HOURS = 3.75       # a long Shift B plans to finish by 01:45


def _stream(*key):
    """A random stream of its own for one purpose, or for one record."""
    return np.random.default_rng([C.RANDOM_SEED, *key])


def month_class(d) -> str:
    return "busy" if d.month in C.BUSY_MONTHS else "quiet" if d.month in C.QUIET_MONTHS else "normal"


def _band(table, value):
    """Factor from a list of (upper bound, factor) pairs; None is open-ended."""
    for upper, factor in table:
        if upper is None or value < upper:
            return factor
    return table[-1][1]


class _Lots:
    """Receiving and stock by material: lots arrive when cover falls below the
    reorder point and are pulled first-in-first-out or from the newest lot."""

    def __init__(self):
        self.rng = _stream(32)          # receiving decisions
        self.pull_rng = _stream(33)     # which lot is pulled
        self.rows = []
        self.stock = {m: [] for m in C.MATERIALS}          # indices into rows, oldest first
        self.weekly_use = {m: 215.0 * w for m, w in zip(C.MATERIALS, C.MATERIAL_WEIGHTS)}
        self.used_this_week = {m: 0 for m in C.MATERIALS}
        self.counter = 1000

    def _receive(self, material, receipt_date):
        rng = _stream(31, self.counter)
        supplier = str(rng.choice(C.SUPPLIERS, p=C.SUPPLIER_WEIGHTS))
        mix = C.CERT_MIX.get(supplier, C.CERT_MIX["default"])
        cert = str(rng.choice(list(mix), p=list(mix.values())))
        sd = C.THICKNESS_DEVIATION_SD_PCT[supplier] * (1.0 if cert == "Certified" else C.UNCERTIFIED_SD_FACTOR)
        nominal = C.MATERIALS[material]["nominal_thickness_in"]
        measured = round(nominal * (1 + rng.normal(0.0, sd) / 100.0), 4)
        lot_id = f"LOT-{self.counter}"
        self.counter += 1
        self.rows.append({
            "lot_id_clean": lot_id,
            "lot_id_raw": lot_as_entered(rng, lot_id) if rng.random() < C.FAULTS["lot_id_noncanonical"] else lot_id,
            "supplier": supplier,
            "material_type": material,
            "receipt_date": receipt_date,
            "cert_status": cert,
            "quantity_lbs": int(rng.integers(500, 6001)),
            "unit_cost_per_lb": round(float(rng.uniform(1.5, 5.0)), 3),
            "nominal_thickness_in": nominal,
            "measured_thickness_in": measured,
            "deviation_pct": round(100.0 * (measured - nominal) / nominal, 2),
            "measured": bool(rng.random() < C.THICKNESS_MEASURED_SHARE),
            "remaining": int(rng.integers(C.LOT_JOBS_CAPACITY[0], C.LOT_JOBS_CAPACITY[1] + 1)),
        })
        self.stock[material].append(len(self.rows) - 1)

    def open_stock(self, start_date):
        for m in C.MATERIALS:
            while self._cover(m) < C.LOT_REORDER_WEEKS * self.weekly_use[m]:
                self._receive(m, start_date - timedelta(days=int(self.rng.integers(2, 50))))
            self.stock[m].sort(key=lambda i: self.rows[i]["receipt_date"])

    def _cover(self, material):
        return sum(self.rows[i]["remaining"] for i in self.stock[material])

    def weekly_receipts(self, monday):
        for m in C.MATERIALS:
            self.weekly_use[m] = 0.75 * self.weekly_use[m] + 0.25 * self.used_this_week[m]
            self.used_this_week[m] = 0
            # Purchasing buys well ahead now and then, when a mill price is good.
            ahead = C.BULK_BUY_WEEKS if self.rng.random() < C.BULK_BUY_WEEKLY_PROB else 0.0
            while self._cover(m) < (C.LOT_REORDER_WEEKS + ahead) * self.weekly_use[m]:
                self._receive(m, monday + timedelta(days=int(self.rng.integers(0, 5))))

    def pull(self, material, day):
        rows = self.rows
        self.stock[material] = [i for i in self.stock[material] if rows[i]["remaining"] > 0]
        on_hand = [i for i in self.stock[material] if rows[i]["receipt_date"] <= day]
        if not on_hand:
            self._receive(material, day)
            on_hand = [self.stock[material][-1]]
        if self.pull_rng.random() < C.LOT_PULL_FIFO_SHARE:
            i = min(on_hand, key=lambda j: (rows[j]["receipt_date"], j))
        else:
            i = max(on_hand, key=lambda j: (rows[j]["receipt_date"], j))
        rows[i]["remaining"] -= 1
        self.used_this_week[material] += 1
        return rows[i]


def run_shop_floor(parts: pd.DataFrame, revisions: pd.DataFrame, operators: pd.DataFrame):
    """Returns (jobs, lots): one row per work order with everything the ERP,
    MES and QMS record about it, and the lot receipts."""
    # Separate random streams, so a change to one part of the shop's behavior
    # leaves the draws of the others as they were.
    rng = _stream(34)               # calendar, order release
    long_rng = _stream(35)          # long days
    ops_rng = _stream(36)           # attendance and assignment
    seq_rng = _stream(38)           # sequencing and idle time
    start_day, end_day = C.START_DATE.date(), C.END_DATE.date()

    P = parts.to_dict("records")
    released = np.array([p["released_date"].toordinal() for p in P])
    demand = np.array([p["demand_weight"] for p in P])
    rev_by_part = {}
    for r in revisions.sort_values(["part_number", "effective_date"]).to_dict("records"):
        rev_by_part.setdefault(r["part_number"], []).append((r["effective_date"], r["revision"]))

    ops = operators.to_dict("records")
    op_by_id = {o["operator_id"]: o for o in ops}
    experience = {}
    for o in ops:
        if o["first_day"] == start_day:
            tenure = (start_day - o["hire_date"]).days / 365.25
            experience[(o["operator_id"], o["primary_machine_type"])] = tenure * C.PRIOR_JOBS_PER_TENURE_YEAR
            experience[(o["operator_id"], o["secondary_machine_type"])] = (
                tenure * C.PRIOR_JOBS_PER_TENURE_YEAR * C.SECONDARY_PRIOR_SHARE)

    lots = _Lots()
    lots.open_stock(start_day)

    runs_on_revision = {}           # (part, revision) -> work orders run so far
    last_thickness = {}             # machine -> thickness of the job before
    machine_free_at = {m[0]: datetime.min for m in C.MACHINES_DATA}
    carried = []
    jobs = []
    wo = 10000

    day = start_day
    while day <= end_day:
        if day.weekday() == 0:
            lots.weekly_receipts(day)
        works = day.weekday() < 5 or (day.weekday() == 5 and rng.random() < C.SATURDAY_WORK_PROB)
        if not works:
            day += timedelta(days=1)
            continue
        mclass = month_class(day)
        midnight = datetime(day.year, day.month, day.day)

        # ── Work orders released today ──────────────────────────────────────
        n = int(round(rng.integers(C.JOBS_PER_DAY_RANGE[0], C.JOBS_PER_DAY_RANGE[1] + 1) * C.VOLUME_FACTOR[mclass]))
        active = released <= day.toordinal()
        w = np.where(active, demand, 0.0)
        picks = rng.choice(len(P), size=n, p=w / w.sum())
        rush_draw = rng.random(n) < C.RUSH_SHARE[mclass]
        new = []
        for k in range(n):
            p = P[int(picks[k])]
            rush = bool(rush_draw[k])
            lead = rng.integers(*C.DUE_DAYS_RUSH, endpoint=True) if rush else rng.integers(*C.DUE_DAYS_ROUTINE, endpoint=True)
            new.append({"work_order_id": f"WO-{wo}", "part": p, "order_date": day, "rush": rush,
                        "quantity": int(rng.integers(C.LOT_SIZE_RANGE[0], C.LOT_SIZE_RANGE[1] + 1)),
                        "due_date": day + timedelta(days=int(round(int(lead) * 1.4)))})
            wo += 1
        queue = carried + new
        carried = []

        # The shop runs long on a share of days, more often when rush work is up.
        p_long = C.LONG_DAY_SHARE[mclass]
        lift = C.LONG_DAY_RUSH_WEEK_LIFT if rush_draw.mean() > C.RUSH_SHARE[mclass] else 1.0 / C.LONG_DAY_RUSH_WEEK_LIFT
        odds = p_long / (1 - p_long) * lift
        p_long = odds / (1 + odds)
        long_day = bool(long_rng.random() < p_long)

        # ── Who is in today ─────────────────────────────────────────────────
        present = [o for o in ops if o["first_day"] <= day <= o["last_day"] and ops_rng.random() >= C.ABSENCE_RATE]
        todays = []
        busy_until = {}
        first_start = {}
        for mtype in C.MACHINE_TYPES:
            type_jobs = [j for j in queue if j["part"]["machine_type"] == mtype]
            if not type_jobs:
                continue
            for j in type_jobs:
                if "setup_minutes" in j:
                    continue            # held over from an earlier day
                jr = _stream(37, int(j["work_order_id"][3:]))
                std = j["part"]["std_setup_min"]
                median = std * (C.RUSH_SETUP_MEDIAN_RATIO if j["rush"] else 1.0)
                j["setup_minutes"] = round(float(median * jr.lognormal(0.0, C.SETUP_LOGNORMAL_SIGMA)), 1)
                j["run_minutes"] = round(float(j["quantity"] * j["part"]["run_min_per_piece"] * jr.uniform(0.9, 1.15)), 1)
                j["thickness"] = C.MATERIALS[j["part"]["material_type"]]["nominal_thickness_in"]
            # Machine and shift slots for the day, with the lead operator on each.
            slots = []
            leads_taken = set()
            for machine in _MACHINES_OF[mtype]:
                a_runs_until = None
                for shift, (h0, h1) in C.SHIFT_HOURS.items():
                    on_shift = [o for o in present if o["shift"] == shift]
                    t0, t1 = midnight + timedelta(hours=h0), midnight + timedelta(hours=h1)
                    is_long = long_day and long_rng.random() < C.LONG_DAY_OPERATOR_SHARE[mtype]
                    if shift == "Shift B" and a_runs_until is not None:
                        t0 = a_runs_until           # Shift A is running long on this machine
                    if is_long:
                        # A long day runs on past the end of the shift. The last job
                        # is started before the operator leaves and finished after
                        # the hours planned.
                        extra = float(min(_MAX_EXTENSION_HOURS, long_rng.uniform(C.LONG_DAY_HOURS[0], C.LONG_DAY_HOURS[1]) - 8.0))
                        t1 += timedelta(hours=extra)
                        if shift == "Shift A":
                            a_runs_until = t1
                        t1 += timedelta(minutes=C.LONG_DAY_LAST_JOB_OVERRUN_MIN)
                    primaries = [o for o in on_shift if o["primary_machine_type"] == mtype and o["operator_id"] not in leads_taken]
                    cover = [o for o in on_shift if o["secondary_machine_type"] == mtype and o["operator_id"] not in leads_taken]
                    pool = primaries or cover or [o for o in on_shift if o["operator_id"] not in leads_taken] or on_shift \
                        or [o for o in ops if o["first_day"] <= day <= o["last_day"] and o["shift"] == shift]
                    lead = pool[int(ops_rng.integers(len(pool)))]
                    leads_taken.add(lead["operator_id"])
                    slots.append({"machine": machine, "shift": shift, "start": t0, "end": t1, "long": is_long,
                                  "lead": lead, "on_shift": on_shift, "jobs": [],
                                  "minutes": (t1 - t0).total_seconds() / 60.0})

            # The planner holds routine work over when the day is full.
            capacity = 0.90 * sum(s["minutes"] for s in slots)
            type_jobs.sort(key=lambda x: (not x["rush"], x["order_date"], x["work_order_id"]))
            load, kept = 0.0, []
            for x in type_jobs:
                d = x["setup_minutes"] + x["run_minutes"]
                if load + d <= capacity:
                    kept.append(x); load += d
                else:
                    carried.append(x)

            # Sequence: brakes are batched by material thickness, most of the time,
            # picking up from the thickness each brake last ran; other machines run
            # in no particular order.
            keys = seq_rng.random(len(kept))
            if mtype == "Bending":
                held = last_thickness.get(_MACHINES_OF[mtype][0])
                batched = seq_rng.random(len(kept)) < C.BRAKE_SAME_GAUGE_PROB
                thick = sorted({x["thickness"] for x in kept}, key=lambda t: (t != held, t))
                rank = {t: i for i, t in enumerate(thick)}
                keys = [rank[x["thickness"]] + 0.5 * keys[i] if batched[i] else len(thick) * keys[i] for i, x in enumerate(kept)]
            kept = [x for _, x in sorted(zip(keys, kept), key=lambda kv: kv[0])]

            # Deal the sequence across the slots in proportion to their hours.
            total_minutes = sum(s["minutes"] for s in slots)
            k = 0
            for si, slot in enumerate(slots):
                share = load * slot["minutes"] / total_minutes
                filled = 0.0
                while k < len(kept):
                    d = kept[k]["setup_minutes"] + kept[k]["run_minutes"]
                    last_slot = si == len(slots) - 1
                    if filled + d > slot["minutes"] or (not last_slot and filled + d / 2 > share):
                        break
                    slot["jobs"].append(kept[k]); filled += d; k += 1
                slot["load"] = filled
            carried.extend(kept[k:])

            # Clock times: the first job starts at the top of the slot and the idle
            # time is spread between the jobs that follow.
            last_start = midnight + timedelta(hours=25, minutes=55)
            for slot in slots:
                if not slot["jobs"]:
                    continue
                t = max(slot["start"], machine_free_at[slot["machine"]] + timedelta(minutes=3)) \
                    + timedelta(minutes=float(seq_rng.uniform(0, 12)))
                idle = max(0.0, (slot["end"] - t).total_seconds() / 60.0 - slot["load"])
                gaps = idle * seq_rng.dirichlet(np.ones(len(slot["jobs"]))) if len(slot["jobs"]) > 1 else np.zeros(1)
                for n_job, x in enumerate(slot["jobs"]):
                    if n_job > 0:
                        t += timedelta(minutes=float(gaps[n_job - 1]))
                    if t >= last_start:
                        # Nothing is started after 02:00; the rest waits for tomorrow.
                        carried.extend(slot["jobs"][n_job:])
                        del slot["jobs"][n_job:]
                        break
                    x["machine_id"], x["shift"] = slot["machine"], slot["shift"]
                    x["job_start"] = t
                    x["job_end"] = t + timedelta(minutes=x["setup_minutes"] + x["run_minutes"])
                    t = x["job_end"] + timedelta(minutes=float(seq_rng.uniform(1, 4)))
                    machine_free_at[slot["machine"]] = x["job_end"]
                    x["_slot"] = slot

            # Operators: the lead runs the machine; another operator of the same
            # machine type or a covering operator takes a share of the jobs.
            for x in sorted((x for slot in slots for x in slot["jobs"]), key=lambda x: (x["job_start"], x["work_order_id"])):
                slot = x.pop("_slot")
                op = slot["lead"]
                if not slot["long"]:
                    r = ops_rng.random()
                    others = [o for o in slot["on_shift"] if o["operator_id"] != op["operator_id"]]
                    free = [o for o in others if busy_until.get(o["operator_id"], datetime.min) <= x["job_start"]]
                    cand = []
                    if r >= C.PRIMARY_MACHINE_JOB_SHARE:
                        covers = lambda group: [o for o in group if o["secondary_machine_type"] == mtype and o["primary_machine_type"] != mtype]
                        cand = covers(free) or covers(others)
                    elif r >= C.PRIMARY_MACHINE_JOB_SHARE - 0.15:
                        cand = [o for o in free if o["primary_machine_type"] == mtype]
                    if cand:
                        op = cand[int(ops_rng.integers(len(cand)))]
                x["operator_id"] = op["operator_id"]
                busy_until[op["operator_id"]] = x["job_end"]
                first_start[op["operator_id"]] = min(first_start.get(op["operator_id"], x["job_start"]), x["job_start"])
                todays.append(x)

        # ── Each job in start order: lot, history and failure probability ──
        todays.sort(key=lambda j: (j["job_start"], j["work_order_id"]))
        for j in todays:
            p = j["part"]
            mtype = p["machine_type"]
            lot = lots.pull(p["material_type"], day)
            revision = [r for d, r in rev_by_part[p["part_number"]] if d <= j["order_date"]][-1]
            key = (p["part_number"], revision)
            seen = runs_on_revision.get(key, 0)
            runs_on_revision[key] = seen + 1
            existing_drawing = revision == "A" and p["released_date"] < start_day
            run_position = 3 if existing_drawing else min(seen + 1, 3)       # 1 first run, 2 second, 3 later

            exp_key = (j["operator_id"], mtype)
            jobs_before = experience.get(exp_key, 0.0)
            experience[exp_key] = jobs_before + 1
            hours_in = (j["job_start"] - first_start[j["operator_id"]]).total_seconds() / 3600.0
            previous = last_thickness.get(j["machine_id"])
            after_change = previous is not None and previous != j["thickness"]
            last_thickness[j["machine_id"]] = j["thickness"]
            lot_age = (j["job_start"].date() - lot["receipt_date"]).days
            gauge_steel = C.MATERIALS[p["material_type"]]["gauge_steel"]

            presence = C.FIRST_PIECE_PRESENCE["rush" if j["rush"] else "routine"]
            if j["setup_minutes"] < C.FIRST_PIECE_SHORT_SETUP_RATIO * p["std_setup_min"]:
                presence -= C.FIRST_PIECE_SHORT_SETUP_PENALTY
            has_first_piece = bool(_stream(39, int(j["work_order_id"][3:])).random() < presence)

            dev_rule = C.GAUGE_DEVIATION[mtype]
            f_dev = min(dev_rule["cap"], 1 + dev_rule["slope"] * abs(lot["deviation_pct"])) if dev_rule else 1.0
            f_run = {1: C.FIRST_RUN["first"], 2: C.FIRST_RUN["second"], 3: 1.0}[run_position]
            f_change = C.BRAKE_GAUGE_CHANGE["factor"] if (mtype == "Bending" and after_change) else 1.0
            f_piece = 1.0 if has_first_piece else C.NO_FIRST_PIECE
            f_hour = C.PAST_TENTH_HOUR if hours_in > 10.0 else 1.0
            f_exp = _band(C.EXPERIENCE, jobs_before)
            f_age = _band(C.LOT_AGE_GAUGE_STEEL, lot_age) if gauge_steel else 1.0
            f_cx = C.COMPLEXITY[p["complexity"]]
            prob = min(C.DEFECT_PROBABILITY_CAP,
                       C.BASE_DEFECT_RATE * f_dev * f_run * f_change * f_piece * f_hour * f_exp * f_age * f_cx)

            # Defect code mix for the job: the machine's mix, shifted toward the
            # codes that the applicable factors produce.
            mix = dict(C.DEFECT_MIX[mtype])
            shifts = []
            if dev_rule and f_dev > 1:
                shifts.append((f_dev, dev_rule["codes"], C.BIASED_CODE_SHARE))
            if f_run > 1:
                shifts.append((f_run, [c for c in C.FIRST_RUN["codes"] if c in mix] or C.FIRST_RUN["codes"][:1], C.BIASED_CODE_SHARE))
            if f_change > 1:
                shifts.append((f_change, C.BRAKE_GAUGE_CHANGE["codes"], C.BIASED_CODE_SHARE))
            if f_age > 1:
                shifts.append((f_age, [C.LOT_AGE_CODES["Welding" if mtype == "Welding" else "other"]], C.LOT_AGE_CODE_SHARE))
            spread = 1.0 + sum((f - 1) * (1 - share) for f, _, share in shifts)
            mix = {c: v * spread for c, v in mix.items()}
            for f, codes, share in shifts:
                for c in codes:
                    mix[c] = mix.get(c, 0.0) + (f - 1) * share / len(codes)

            j.update({
                "part_number": p["part_number"], "part_revision": revision, "lot": lot,
                "run_position": run_position, "jobs_before": jobs_before, "hours_into_day": hours_in,
                "after_gauge_change": bool(after_change), "lot_age_days": lot_age,
                "has_first_piece": has_first_piece, "defect_probability": prob, "code_mix": mix,
                "f_deviation": f_dev, "f_first_run": f_run, "f_gauge_change": f_change,
                "f_no_first_piece": f_piece, "f_past_tenth_hour": f_hour, "f_experience": f_exp,
                "f_lot_age": f_age, "f_complexity": f_cx, "long_day": long_day,
            })
            jobs.append(j)
        day += timedelta(days=1)

    lots_df = pd.DataFrame(lots.rows)
    # The micrometer check is recorded on a fixed share of the lots received.
    recorded = np.zeros(len(lots_df), dtype=bool)
    recorded[_stream(40).permutation(len(lots_df))[:int(round(C.THICKNESS_MEASURED_SHARE * len(lots_df)))]] = True
    lots_df["measured"] = recorded
    return jobs, lots_df


def erp_work_orders(jobs, operators: pd.DataFrame) -> pd.DataFrame:
    """ERP work orders as the planner and supervisors keyed them."""
    rng = np.random.default_rng(C.RANDOM_SEED + 4)
    name = operators.set_index("operator_id")["operator_name"].to_dict()
    rows = []
    for j in jobs:
        p, lot = j["part"], j["lot"]
        lag = timedelta(minutes=int(rng.integers(C.ERP_START_LAG_MINUTES[0], C.ERP_START_LAG_MINUTES[1] + 1))) \
            if rng.random() < C.ERP_START_LAG_SHARE else timedelta(0)
        start = j["job_start"].replace(second=0, microsecond=0) + lag
        end = j["job_end"].replace(second=0, microsecond=0) + lag
        lot_entered = lot_as_entered(rng, lot["lot_id_clean"]) if rng.random() < C.FAULTS["lot_id_noncanonical"] else lot["lot_id_clean"]
        rows.append({
            "work_order_id": j["work_order_id"],
            "part_number_raw": part_as_entered(rng, p["part_number"]),
            "part_number_clean": p["part_number"],
            "part_revision": j["part_revision"],
            "customer": p["customer"],
            "quantity_ordered": j["quantity"],
            "machine_id": j["machine_id"],
            "operator_id_raw": name[j["operator_id"]] if rng.random() < C.FAULTS["erp_operator_as_name"] else j["operator_id"],
            "operator_id_clean": j["operator_id"],
            "shift_code": None if rng.random() < C.FAULTS["erp_shift_code_null"] else j["shift"],
            "lot_id_raw": None if rng.random() < C.FAULTS["erp_lot_id_null"] else lot_entered,
            "lot_id_clean": lot["lot_id_clean"],
            "order_date": str(j["order_date"]),
            "due_date": str(j["due_date"]),
            "rush_flag": j["rush"],
            "scheduled_start": str(j["job_start"].replace(second=0, microsecond=0) - timedelta(minutes=int(rng.integers(0, 91)))),
            "actual_start": str(start),
            "actual_end": str(end),
            "complexity": p["complexity"],
            "material_type": p["material_type"],
            "requires_welding": p["requires_welding"],
            "std_labor_hrs": p["std_labor_hrs"],
        })
    return pd.DataFrame(rows)


def mes_job_log(jobs, operators: pd.DataFrame) -> pd.DataFrame:
    """MES job log: one row per work order as clocked at the machine."""
    rng = np.random.default_rng(C.RANDOM_SEED + 5)
    name = operators.set_index("operator_id")["operator_name"].to_dict()
    rows = []
    for j in jobs:
        p = j["part"]
        mtype = p["machine_type"]
        if mtype == "Bending":
            tool = f"TS-{int(round(j['thickness'] * 10000)):04d}"
        elif mtype == "Welding":
            tool = None
        else:
            tool = f"NC-{p['part_number'].replace('-', '')}-{j['part_revision']}"
        start, end = j["job_start"].replace(microsecond=0), j["job_end"].replace(microsecond=0)
        if rng.random() < C.FAULTS["job_log_end_before_start"]:
            start, end = end, start             # the two clock entries keyed the wrong way round
        rows.append({
            "work_order_id": j["work_order_id"],
            "machine_id": j["machine_id"],
            "operator_badge": name[j["operator_id"]] if rng.random() < C.FAULTS["job_log_operator_as_name"] else j["operator_id"],
            "job_start": str(start),
            "job_end": str(end),
            "setup_minutes": j["setup_minutes"],
            "run_minutes": j["run_minutes"],
            "program_or_tool_set_id": tool,
        })
    return pd.DataFrame(rows)


LOT_COLUMNS = ["lot_id_clean", "lot_id_raw", "supplier", "material_type", "receipt_date", "cert_status",
               "quantity_lbs", "unit_cost_per_lb", "nominal_thickness_in", "measured_thickness_in",
               "thickness_deviation_pct"]


def material_lots(lots_df: pd.DataFrame) -> pd.DataFrame:
    """Materials lot receipts; the micrometer check is not recorded on every lot."""
    out = lots_df.sort_values(["receipt_date", "lot_id_clean"]).copy()
    out["thickness_deviation_pct"] = out["deviation_pct"].where(out["measured"])
    out["measured_thickness_in"] = out["measured_thickness_in"].where(out["measured"])
    out["receipt_date"] = out["receipt_date"].astype(str)
    return out[LOT_COLUMNS].reset_index(drop=True)
