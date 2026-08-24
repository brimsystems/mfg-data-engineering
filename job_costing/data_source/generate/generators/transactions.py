"""The transactions every job leaves behind, and the ways people corrupt them.

Every job is scheduled across its operations on the shop calendar. From that
schedule come the machine-monitoring intervals (the truth of CNC run time), the
clock records operators post at the door terminals, the material issues, the
outside-processing purchase orders and the scrap and rework events. The
defects in the specification are laid over those records the way they happen
on the floor: records left open overnight, time on the wrong job, one clock
record while tending three machines, indirect time on whatever job was open,
rework posted as production, scrap thrown in the bin, bar pulled for two jobs
and charged to one, and PO lines coded to the general ledger with no job.

After the engagement's configuration changes the same mechanisms produce clean
records: terminals at the cells, one open operation per employee, auto-close at
shift end, setup / run / rework / indirect codes, a job number on every PO and
a reason on every scrap event. Traveler scans at secondary operations roll out
from week 2 with the coverage the specification describes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .. import config as C

T0 = datetime(C.START_DATE.year, C.START_DATE.month, C.START_DATE.day)
HORIZON_DAYS = (C.END_DATE - C.START_DATE).days + 40


def _ts(hours):
    return T0 + timedelta(hours=float(hours))


def _hours(d):
    """Hours since the window opened for a date or datetime."""
    dt = d if isinstance(d, datetime) else datetime(d.year, d.month, d.day)
    return (dt - T0).total_seconds() / 3600


class Calendar:
    """Working-time arithmetic on a weekly pattern. `windows` lists (weekday, open
    hour, close hour). Working time is mapped to wall time through the cumulative
    open hours at each window start, so the mapping is a vectorized search."""

    def __init__(self, windows):
        starts, ends = [], []
        first_dow = T0.weekday()
        for day in range(HORIZON_DAYS):
            dow = (first_dow + day) % 7
            for wd, o, c in windows:
                if wd == dow:
                    starts.append(day * 24 + o); ends.append(day * 24 + c)
        self.starts = np.array(starts, float); self.ends = np.array(ends, float)
        lengths = self.ends - self.starts
        self.cum = np.concatenate([[0.0], np.cumsum(lengths)])

    def to_work(self, t):
        t = np.asarray(t, float)
        k = np.searchsorted(self.starts, t, side="right") - 1
        k = np.clip(k, 0, len(self.starts) - 1)
        inside = np.clip(t - self.starts[k], 0, self.ends[k] - self.starts[k])
        # before the first window of a day counts as the start of that window
        before = t < self.starts[k]
        w = self.cum[k] + np.where(before, 0, inside)
        return w

    def to_wall(self, w):
        w = np.asarray(w, float)
        k = np.searchsorted(self.cum, w, side="right") - 1
        k = np.clip(k, 0, len(self.starts) - 1)
        return self.starts[k] + (w - self.cum[k])

    def next_open(self, t):
        return float(self.to_wall(self.to_work(t)))

    def pieces(self, w_a, w_b):
        """Wall-time pieces of the working-time span [w_a, w_b], one per calendar window."""
        out = []
        k = int(np.searchsorted(self.cum, w_a, side="right") - 1)
        k = min(max(k, 0), len(self.starts) - 1)
        w = w_a
        while w < w_b - 1e-9 and k < len(self.starts):
            top = min(w_b, self.cum[k + 1])
            if top > w + 1e-9:
                out.append((self.starts[k] + (w - self.cum[k]), self.starts[k] + (top - self.cum[k])))
            w = top
            k += 1
        return out

    def advance(self, t, hours):
        return float(self.to_wall(self.to_work(t) + hours))


TWO_SHIFT = Calendar([(d, 6, 22) for d in range(5)] + [(5, 6, 14)])
CONTINUOUS = Calendar([(0, 6, 24)] + [(d, 0, 24) for d in range(1, 5)] + [(5, 0, 22)])
ATTENDED = Calendar([(d, 6, 22) for d in range(5)] + [(5, 6, 14)])   # when operators are on the floor
SHIFT_ENDS = [14, 22, 6]


def calendars_for(wcs):
    cal = {}
    for _, w in wcs.iterrows():
        cal[w["work_center_id"]] = CONTINUOUS if w["lights_out_share"] >= 0.3 else TWO_SHIFT
    return cal


def employees(rng, wcs):
    """Operators by work-center group, sized to the group's hours."""
    rows = []
    n = 0
    for g, (count, wtype, monitored, lo, labor, burden, att) in C.WORK_CENTER_GROUPS.items():
        crew = max(2, int(round(count * (2.6 if monitored else 3.2))))
        for _ in range(crew):
            n += 1
            rows.append({"employee_id": f"EMP-{n:03d}", "group": g, "shift": int(rng.choice([1, 2, 3], p=[0.5, 0.35, 0.15]))})
    return pd.DataFrame(rows)


# ── scheduling ──────────────────────────────────────────────────────────────
class Resource:
    """A machine or a crew slot: busy intervals in its calendar's working time,
    filled earliest-gap-first so a short job can slip in ahead of a long one."""

    def __init__(self, cal):
        self.cal = cal
        self.busy = []          # sorted (start, end) in working hours

    def place(self, ready_wall, dur):
        w0 = float(self.cal.to_work(ready_wall))
        import bisect
        k = bisect.bisect_left(self.busy, (w0, -1.0))
        # the gap before busy[k] must start after the previous interval ends
        prev_end = self.busy[k - 1][1] if k > 0 else 0.0
        cand = max(w0, prev_end)
        while k < len(self.busy) and self.busy[k][0] - cand < dur:
            cand = max(cand, self.busy[k][1]); k += 1
        self.busy.insert(k, (cand, cand + dur))
        return cand, cand + dur

    def earliest(self, ready_wall, dur):
        w0 = float(self.cal.to_work(ready_wall))
        import bisect
        k = bisect.bisect_left(self.busy, (w0, -1.0))
        prev_end = self.busy[k - 1][1] if k > 0 else 0.0
        cand = max(w0, prev_end)
        while k < len(self.busy) and self.busy[k][0] - cand < dur:
            cand = max(cand, self.busy[k][1]); k += 1
        return cand


def schedule(rng, jobs, wcs, emps):
    """Sequence every operation on its work center. CNC work centers are single
    machines; secondary work centers have a small crew. Each operation goes to
    whichever machine in its group can start it soonest."""
    cal = calendars_for(wcs)
    monitored = wcs.set_index("work_center_id")["monitored_flag"].to_dict()
    group_of = wcs.set_index("work_center_id")["group"].to_dict()
    machines = wcs.groupby("group")["work_center_id"].apply(list).to_dict()
    res = {w: [Resource(cal[w]) for _ in range(1 if monitored[w] else 3)] for w in wcs["work_center_id"]}
    crew = {g: emps.loc[emps["group"] == g, "employee_id"].tolist() for g in emps["group"].unique()}
    rows = []
    completed = {}
    for j in jobs.sort_values("release_date").itertuples():
        t = _hours(j.release_date) + float(rng.uniform(12, 60))
        for o in j.ops:
            grp = group_of[o["work_center_id"]]
            dur = o["setup_hours"] + o["run_hours"] + o["change_order_hours"]
            best = None
            for m in machines[grp]:
                for r in res[m]:
                    w = r.earliest(t, dur)
                    if best is None or w < best[0]:
                        best = (w, m, r)
            w, wc, r = best
            # the oldest machines in a cell run the same program slower
            run_h = o["run_hours"] * C.OLDER_MACHINE_CYCLE.get(wc, 1.0)
            dur = o["setup_hours"] + run_h + o["change_order_hours"]
            ws, we = r.place(t, dur)
            c = cal[wc]
            start = float(c.to_wall(ws)); end = float(c.to_wall(we))
            emp = str(rng.choice(crew[grp]))
            rows.append({"job_id": j.job_id, "op_seq": o["op_seq"], "work_center_id": wc, "group": grp,
                         "monitored": monitored[wc], "start_h": start, "end_h": end, "setup_hours": o["setup_hours"],
                         "run_hours": round(run_h, 3), "change_order_hours": o["change_order_hours"],
                         "employee_id": emp, "program_number": o["program_number"], "quantity": j.quantity,
                         "part_number": j.part_number, "release_date": j.release_date, "customer_id": j.customer_id})
            t = end + float(rng.uniform(2, 14))
        completed[j.job_id] = end
    ops = pd.DataFrame(rows)
    return ops, completed


# ── machine monitoring ──────────────────────────────────────────────────────
def machine_monitoring(rng, ops, wcs):
    """State intervals for every monitored machine. Setup, in-cycle intervals with
    cycle counts, short idles between them, alarms, and the idle and offline
    time between operations."""
    cal = calendars_for(wcs)
    connect_h = _hours(C.CONFIG_DATES["monitoring_to_jobs"])
    parts = []
    mon = ops[ops["monitored"]].sort_values(["work_center_id", "start_h"])
    for wc, g in mon.groupby("work_center_id", sort=False):
        c = cal[wc]
        prev_end = None
        recs = []
        for o in g.itertuples():
            w0 = float(c.to_work(o.start_h))
            # idle or offline gap since the last operation
            if prev_end is not None and o.start_h > prev_end + 0.05:
                gap_work = w0 - float(c.to_work(prev_end))
                if gap_work > 0.05:
                    for s, e in c.pieces(float(c.to_work(prev_end)), w0):
                        recs.append((s, e, "idle", None, 0))
            setup_h = o.setup_hours + o.change_order_hours
            n_setup = 1 if setup_h < 1.5 else 2
            cuts = np.sort(rng.uniform(0.2, 0.8, n_setup - 1)) * setup_h
            bounds = np.concatenate([[0.0], cuts, [setup_h]])
            for a, b in zip(bounds[:-1], bounds[1:]):
                for s, e in c.pieces(w0 + a, w0 + b):
                    recs.append((s, e, "setup", o.program_number, 0))
            # run: in-cycle intervals of 6-30 minutes, each covering whole cycles
            run_h = o.run_hours
            cycle_min = max(run_h * 60 / max(o.quantity, 1), 0.05)
            w = w0 + setup_h; w_end = w0 + setup_h + run_h
            pieces_left = int(o.quantity)
            while w < w_end - 1e-6 and pieces_left > 0:
                cycles = max(1, int(round(float(rng.uniform(*C.MACHINE_INTERVAL_MINUTES)) / cycle_min)))
                cycles = min(cycles, pieces_left)
                length = cycles * cycle_min / 60
                seg = c.pieces(w, w + length)
                for n, (s, e) in enumerate(seg):
                    recs.append((s, e, "in_cycle", o.program_number, cycles if n == 0 else 0))
                w += length; pieces_left -= cycles
                u = rng.random()
                if u < C.ALARM_SHARE:
                    a = min(float(rng.uniform(5, 30)) / 60, w_end - w)
                    if a > 0:
                        for s, e in c.pieces(w, w + a):
                            recs.append((s, e, "alarm", o.program_number, 0))
                        w += a
                elif u < C.ALARM_SHARE + C.IN_OP_IDLE_P:
                    i = min(float(rng.uniform(*C.IN_OP_IDLE_MINUTES)) / 60, max(w_end - w, 0))
                    if i > 0:
                        for s, e in c.pieces(w, w + i):
                            recs.append((s, e, "idle", o.program_number, 0))
                        w += i
            prev_end = o.end_h
            # the feed posts machine hours to jobs once connected
            job = o.job_id if o.start_h >= connect_h else None
            for r in recs:
                # the feed carries the job on every interval inside the operation, idle included
                parts.append((wc, r[0], r[1], r[2], r[3], r[4], job if r[3] is not None else None, o.job_id))
            recs = []
    mm = pd.DataFrame(parts, columns=["machine_id", "start_h", "end_h", "state", "program_number", "cycle_count",
                                      "assigned_job_id", "_true_job_id"])
    # nights and weekends when the machine is off are one offline interval each
    off = []
    for wc in mon["work_center_id"].unique():
        c = cal[wc]
        for s, e in zip(c.ends[:-1], c.starts[1:]):
            if e > s + 0.5 and s < _hours(C.END_DATE) + 24:
                off.append((wc, s, e, "offline", None, 0, None, None))
    mm = pd.concat([mm, pd.DataFrame(off, columns=mm.columns)], ignore_index=True)
    mm = mm[mm["start_h"] < _hours(C.END_DATE) + 24].sort_values(["machine_id", "start_h"]).reset_index(drop=True)
    mm["start_time"] = [_ts(h) for h in mm["start_h"]]
    mm["end_time"] = [_ts(h) for h in mm["end_h"]]
    mm["interval_id"] = [f"MI-{i + 1:08d}" for i in range(len(mm))]
    return mm[["interval_id", "machine_id", "start_time", "end_time", "state", "program_number", "cycle_count",
               "assigned_job_id", "_true_job_id"]]


# ── labor ───────────────────────────────────────────────────────────────────
def _attended_segments(start, end, cal=None):
    """Wall-time segments inside [start, end] when someone is clocked to the
    operation: the day shifts on attended cells, the whole run on lights-out
    cells where the night operator covers the cell."""
    cal = cal or ATTENDED
    segs = []
    k = np.searchsorted(cal.starts, start, side="right") - 1
    k = max(k, 0)
    while k < len(cal.starts) and cal.starts[k] < end:
        a = max(start, cal.starts[k]); b = min(end, cal.ends[k])
        if b > a + 0.02:
            segs.append((a, b))
        k += 1
    return segs


def _split_records(rng, a, b, mean_len=C.CLOCK_RECORD_HOURS):
    """Break a segment into clock records at breaks and lunch."""
    out = []
    t = a
    while t < b - 0.05:
        length = min(float(rng.uniform(mean_len - 0.9, mean_len + 0.9)), b - t)
        out.append((t, t + length)); t += length + float(rng.uniform(0.05, 0.15))
    return out


def labor(rng, ops, jobs, wcs, scrap_events):
    """Clock records for every operation, then the defects laid over them."""
    lo_share = wcs.set_index("work_center_id")["lights_out_share"].to_dict()
    types_h = _hours(C.CONFIG_DATES["labor_type_codes"])
    cells_h = _hours(C.CONFIG_DATES["terminals_at_cells"])
    scan_h = _hours(C.SCAN_ROLLOUT_START)
    rows = []
    job_release = jobs.set_index("job_id")["release_date"].to_dict()
    for o in ops.itertuples():
        post = o.start_h >= types_h
        secondary = o.group in C.SECONDARY_GROUPS
        setup_h = o.setup_hours + o.change_order_hours
        # T10: no posting at these cells until the terminals moved and scanning began
        if o.work_center_id in C.T10_NO_POSTING_WCS and o.start_h < scan_h:
            continue
        if secondary and o.start_h >= scan_h:
            # traveler scan at a secondary operation: one record per operation, missing with the rollout share
            week = C.engagement_week(_ts(o.start_h).date()) or 2
            p_missing = np.interp(week, [2, 12], [C.T9_MISSING_SCAN[2], C.T9_MISSING_SCAN[12]])
            if rng.random() < p_missing:
                continue
            hours = setup_h + o.run_hours
            rows.append((o.job_id, o.op_seq, o.work_center_id, o.employee_id, o.start_h, o.end_h,
                         "run" if not post else "run", "traveler_scan", hours, o.group, False, 0.0, None, False, False, False, hours))
            continue
        segs = _attended_segments(o.start_h, o.end_h, CONTINUOUS if lo_share.get(o.work_center_id, 0.0) >= 0.3 else ATTENDED)
        cum = 0.0
        for a, b in segs:
            for r0, r1 in _split_records(rng, a, b):
                hours = r1 - r0
                # setup first, then run, on the post-configuration codes
                if post:
                    typ = "setup" if cum < setup_h else "run"
                else:
                    typ = "run"
                cum += hours
                rows.append((o.job_id, o.op_seq, o.work_center_id, o.employee_id, r0, r1, typ, "terminal",
                             hours, o.group, o.monitored, lo_share.get(o.work_center_id, 0.0), None, False, False, False, hours))
    lab = pd.DataFrame(rows, columns=["job_id", "op_seq", "work_center_id", "employee_id", "clock_on_h", "clock_off_h",
                                      "type", "source", "hours", "group", "monitored", "lights_out", "_t1_added",
                                      "_t3", "_t4", "_t5", "_true_hours"])
    lab["_true_job_id"] = lab["job_id"]
    lab["_t1_added"] = 0.0
    pre = lab["clock_on_h"] < types_h

    # T1: records left open across a break, a shift or overnight; lights-out cells worst
    p = np.where(pre, C.T1_OPEN_CLOCK_SHARE * (1 + C.T1_LIGHTS_OUT_MULT * lab["lights_out"]), 0.0)
    t1 = rng.random(len(lab)) < p
    # what the open record spans: a break, a shift boundary or the night
    kinds = ["break", "shift", "overnight"]
    lo = (lab["lights_out"] >= 0.3).to_numpy()      # the cells that run through the night
    kind = np.where(lo, rng.choice(kinds, size=len(lab), p=C.T1_KIND_P["lights_out"]),
                    rng.choice(kinds, size=len(lab), p=C.T1_KIND_P["attended"]))
    add = np.zeros(len(lab))
    for k in kinds:
        m = kind == k
        add[m] = rng.uniform(*C.T1_INFLATION_HOURS[k], m.sum())
    lab.loc[t1, "_t1_added"] = add[t1]
    lab.loc[t1, "clock_off_h"] += add[t1]
    lab.loc[t1, "hours"] += add[t1]

    # T4: one clock record while tending two or three machines (multi-machine cells)
    cnc_pre = pre & lab["monitored"]
    p4 = np.where(cnc_pre, C.T4_MULTI_MACHINE_SHARE * (0.25 + 3.0 * lab["lights_out"]), 0.0)
    t4 = rng.random(len(lab)) < np.clip(p4, 0, 0.6)
    mult = rng.uniform(*C.T4_WALL_MULT, len(lab))
    lab.loc[t4, "_t4"] = True
    lab.loc[t4, "hours"] *= mult[t4]
    lab.loc[t4, "clock_off_h"] = lab.loc[t4, "clock_on_h"] + lab.loc[t4, "hours"]
    # the machines the operator was also tending lose their records for that time
    shadow = []
    by_group_day = {}
    for i, r in lab[cnc_pre & ~t4].iterrows():
        by_group_day.setdefault((r["group"], int(r["clock_on_h"] // 24)), []).append(i)
    trimmed = set()
    for i, r in lab[t4].iterrows():
        cands = by_group_day.get((r["group"], int(r["clock_on_h"] // 24)), [])
        cands = [c for c in cands if c not in trimmed and lab.at[c, "job_id"] != r["job_id"]]
        if cands:
            # the machine the operator was also tending loses the time to this record
            victim = cands[int(rng.integers(len(cands)))]
            excess = r["hours"] * (1 - 1 / mult[i])
            cut = min(lab.at[victim, "hours"] * 0.7, excess)
            lab.at[victim, "hours"] -= cut; lab.at[victim, "clock_off_h"] -= cut
            trimmed.add(victim); shadow.append((r.name, lab.at[victim, "job_id"], cut))
    pre = lab["clock_on_h"] < types_h

    # T3: time charged to an adjacent job number
    t3 = (rng.random(len(lab)) < np.where(pre, C.T3_WRONG_JOB_SHARE, 0.004))
    job_ids = jobs["job_id"].tolist(); pos = {j: i for i, j in enumerate(job_ids)}
    wrong = []
    for jid in lab.loc[t3, "job_id"]:
        k = pos[jid] + int(rng.choice([-3, -2, -1, 1, 2, 3]))
        wrong.append(job_ids[min(max(k, 0), len(job_ids) - 1)])
    lab.loc[t3, "job_id"] = wrong
    lab.loc[t3, "_t3"] = True

    # T5: indirect time posted against whatever job was open
    target = C.T5_INDIRECT_SHARE_HOURS * lab.loc[pre, "hours"].sum()
    n5 = int(target / 1.3)
    src = lab[pre].sample(n=min(n5, int(pre.sum())), random_state=int(rng.integers(1e9)))
    ind = src.copy()
    ind["hours"] = rng.uniform(0.5, 2.2, len(ind))
    ind["clock_on_h"] = ind["clock_off_h"] + rng.uniform(0.1, 1.0, len(ind))
    ind["clock_off_h"] = ind["clock_on_h"] + ind["hours"]
    ind["_t5"] = True; ind["_t1_added"] = 0.0; ind["_t3"] = False; ind["_t4"] = False; ind["_true_hours"] = 0.0
    ind["type"] = "run"
    # after the codes went live, indirect time posts as indirect with no job
    post_src = lab[~pre].sample(n=int(n5 * (~pre).sum() / max(pre.sum(), 1) * 0.6), random_state=int(rng.integers(1e9)))
    ind2 = post_src.copy()
    ind2["hours"] = rng.uniform(0.5, 2.2, len(ind2)); ind2["clock_on_h"] = ind2["clock_off_h"] + 0.2
    ind2["clock_off_h"] = ind2["clock_on_h"] + ind2["hours"]; ind2["type"] = "indirect"; ind2["job_id"] = None
    ind2["_t5"] = False; ind2["_true_hours"] = 0.0; ind2["_t1_added"] = 0.0; ind2["_t3"] = False; ind2["_t4"] = False
    lab = pd.concat([lab, ind, ind2], ignore_index=True)

    # T6: rework hours post as run time on the operation, or on a catch-all op 999
    rw = []
    for e in scrap_events.to_dict("records"):
        if e["type"] != "rework" or e["_hours"] <= 0:
            continue
        post = _hours(e["event_date"]) >= types_h
        as_run = (not post) and rng.random() < C.T6_REWORK_AS_RUN_SHARE
        rw.append((e["_true_job_id"], e["op_seq"] if (as_run or post) else 999, e["work_center_id"], e["employee_id"],
                   _hours(e["event_date"]) + 8, _hours(e["event_date"]) + 8 + e["_hours"],
                   "rework" if post else "run", "terminal", e["_hours"], e["group"], e["monitored"], 0.0, 0.0, False, False, False,
                   e["_hours"], e["_true_job_id"], as_run))
    rwdf = pd.DataFrame(rw, columns=list(lab.columns) + ["_t6_as_run"])
    lab["_t6_as_run"] = False; lab["_rework"] = False; rwdf["_rework"] = True
    lab = pd.concat([lab, rwdf], ignore_index=True)

    # auto-close after the configuration change: a record that would have run over
    # closes at shift end and carries the auto_close source
    post_mask = lab["clock_on_h"] >= _hours(C.CONFIG_DATES["auto_close"])
    ac = post_mask & (rng.random(len(lab)) < 0.05)
    lab.loc[ac, "source"] = "auto_close"
    lab = lab.sort_values("clock_on_h").reset_index(drop=True)
    lab["txn_id"] = [f"LT-{i + 1:07d}" for i in range(len(lab))]
    lab["clock_on"] = [_ts(h) for h in lab["clock_on_h"]]
    lab["clock_off"] = [_ts(h) for h in lab["clock_off_h"]]
    lab["hours"] = lab["hours"].round(2)
    shadow_df = pd.DataFrame(shadow, columns=["t4_index", "shadow_job_id", "shadow_hours"])
    return lab, shadow_df


# ── material ────────────────────────────────────────────────────────────────
def material(rng, jobs, ops, cm, scrap_events):
    """Issues and returns per job at the price of the day, then T8."""
    rows = []
    first_op = ops.groupby("job_id")["start_h"].min().to_dict()
    scrap_qty = scrap_events[scrap_events["type"] == "scrap"].groupby("job_id")["quantity"].sum().to_dict()
    for j in jobs.itertuples():
        spec = j.material_spec; form = C.MATERIALS[spec][0]
        lbs = j.quantity * j.weight_lb * 1.08
        extra = scrap_qty.get(j.job_id, 0) * j.weight_lb * 1.08
        n = int(rng.integers(*C.MATERIAL_ISSUES_PER_JOB))
        shares = rng.dirichlet(np.ones(n) * 2.0)
        t0 = first_op.get(j.job_id, _hours(j.release_date)) - float(rng.uniform(4, 30))
        source = {"bar": "saw", "plate": "stockroom", "forging": "stockroom", "casting": "stockroom",
                  "rod": "saw", "tube": "saw"}[form]
        if j.part_family == "Swiss turned components":
            source = "backflush"
        uom = "lb" if form in ("bar", "plate", "rod", "tube") else "ea"
        for k, sh in enumerate(shares):
            d = _ts(t0 + k * float(rng.uniform(6, 48))).date()
            price = cm.material_price(spec, d) * float(rng.normal(1, 0.025))
            qty = lbs * sh if uom == "lb" else round(j.quantity * sh)
            unit_cost = price if uom == "lb" else price * j.weight_lb * 1.08
            if qty <= 0:
                continue
            rows.append((j.job_id, spec, round(qty, 3), uom, round(unit_cost, 3), d, source, j.job_id, False))
        if extra > 0:
            d = _ts(first_op.get(j.job_id, 0) + 30).date()
            price = cm.material_price(spec, d)
            rows.append((j.job_id, spec, round(extra if uom == "lb" else scrap_qty.get(j.job_id, 0), 3), uom,
                         round(price if uom == "lb" else price * j.weight_lb * 1.08, 3), d, source, j.job_id, False))
        if rng.random() < 0.15:
            d = _ts(first_op.get(j.job_id, 0) + 70).date()
            rows.append((j.job_id, spec, -round(lbs * float(rng.uniform(0.03, 0.10)), 3), uom, round(price, 3), d, "stockroom", j.job_id, False))
    mt = pd.DataFrame(rows, columns=["job_id", "material_spec", "quantity", "uom", "unit_cost", "issue_date", "source",
                                     "_true_job_id", "_t8"])
    # T8: bar pulled for two jobs and charged to one; remnants never issued
    issues = mt[(mt["quantity"] > 0) & (mt["source"] != "backflush")]
    n8 = int(C.T8_MATERIAL_WRONG_JOB_SHARE * len(mt))
    picked = issues.sample(n=n8, random_state=int(rng.integers(1e9))).index
    by_spec_date = mt.groupby("material_spec")
    drop = []
    for i in picked:
        r = mt.loc[i]
        if rng.random() < 0.6:
            # charged to another job of the same material issued within a week
            same = mt[(mt["material_spec"] == r["material_spec"]) & (mt["job_id"] != r["job_id"]) &
                      (abs(pd.to_datetime(mt["issue_date"]) - pd.to_datetime(r["issue_date"])).dt.days <= 7)]
            if len(same):
                other = same.iloc[int(rng.integers(len(same)))]
                mt.at[i, "job_id"] = other["job_id"]; mt.at[i, "_t8"] = True
        else:
            drop.append(i)      # the remnant was used and never issued
    mt.loc[drop, "_t8"] = True
    unissued = mt.loc[drop].copy()
    mt = mt.drop(index=drop).sort_values("issue_date").reset_index(drop=True)
    mt["txn_id"] = [f"MT-{i + 1:06d}" for i in range(len(mt))]
    return mt, unissued


# ── outside processing ──────────────────────────────────────────────────────
def outside_processing(rng, jobs, ops, cm, plan):
    rows = []
    last_cnc = ops[~ops["group"].isin(C.SECONDARY_GROUPS)].groupby("job_id")["end_h"].max().to_dict()
    req_h = _hours(C.CONFIG_DATES["po_job_required"])
    po = 0
    for j in jobs.itertuples():
        for svc, vend, base in plan[j.part_number]:
            po += 1
            order_h = last_cnc.get(j.job_id, _hours(j.release_date) + 100) + float(rng.uniform(4, 48))
            order_d = _ts(order_h).date()
            receipt_d = order_d + timedelta(days=int(rng.integers(4, 16)))
            if order_d > C.END_DATE:
                continue
            price = cm.vendor_price(vend, base, order_d) * float(rng.normal(1, 0.03))
            qty = j.quantity
            invoice = qty * price + (float(rng.uniform(25, 90)) if rng.random() < 0.3 else 0.0)
            has_job = rng.random() < (C.POST_CONFIG_PO_JOB_SHARE if order_h >= req_h else 1 - C.M6_OSP_NO_JOB_SHARE)
            desc_part = rng.random() < 0.72
            desc = f"{svc} {j.part_number} rev {j.revision}, {qty} pcs" if desc_part else f"{svc} per quote, {qty} pcs"
            rows.append({"po_id": f"PO-{po:06d}", "line": 1, "vendor_id": vend, "service_type": svc,
                         "job_id": j.job_id if has_job else None, "gl_account": C.OSP_GL_ACCOUNT,
                         "description": desc, "quantity": qty, "unit_price": round(price, 3), "order_date": order_d,
                         "receipt_date": receipt_d if receipt_d <= C.END_DATE else None,
                         "invoice_amount": round(invoice, 2) if receipt_d <= C.END_DATE else None,
                         "_true_job_id": j.job_id, "_customer_id": j.customer_id})
    return pd.DataFrame(rows)


# ── scrap and rework ────────────────────────────────────────────────────────
def scrap_rework(rng, jobs, ops):
    """Events on the floor, then what actually got written down (T7)."""
    rows = []
    cnc = ops[~ops["group"].isin(C.SECONDARY_GROUPS)]
    by_job = {j: g for j, g in cnc.groupby("job_id")}
    req_h = _hours(C.CONFIG_DATES["scrap_reason_req"])
    reporters = ["QC-01", "QC-02", "LEAD-01", "LEAD-02", "LEAD-03", "OP"]
    ev = 0
    for j in jobs.itertuples():
        g = by_job.get(j.job_id)
        if g is None:
            continue
        rate = C.SCRAP_EVENT_RATE * (1.6 if j.customer_id and j.customer_id == CHANGE_ORDER_CUSTOMER[0] else
                                     C.TOP_CUSTOMER_REWORK_MULT if j.customer_id and j.customer_id == TOP_CUSTOMER[0] else 1.0)
        n_ev = rng.poisson(rate)
        for _ in range(n_ev):
            o = g.iloc[int(rng.integers(len(g)))]
            typ = "rework" if rng.random() < 0.42 else "scrap"
            qty = max(1, int(round(j.quantity * float(rng.uniform(0.01, 0.06)))))
            d = _ts(o["start_h"] + float(rng.uniform(1, max(o["end_h"] - o["start_h"], 2)))).date()
            hours = float(rng.uniform(*C.REWORK_HOURS_PER_EVENT)) if typ == "rework" else 0.0
            post = _hours(d) >= req_h
            unrecorded = rng.random() < (0.10 if post else C.T7_SCRAP_UNRECORDED_SHARE)
            no_reason = (not post) and rng.random() < C.T7_SCRAP_NO_REASON_SHARE
            no_job = (not post) and rng.random() < 0.10
            ev += 1
            rows.append({"event_id": f"SR-{ev:06d}", "job_id": None if no_job else j.job_id, "op_seq": int(o["op_seq"]),
                         "type": typ, "quantity": qty, "reason_code": None if no_reason else str(rng.choice(C.SCRAP_REASON_CODES)),
                         "reported_by": str(rng.choice(reporters)), "event_date": d, "work_center_id": o["work_center_id"],
                         "employee_id": o["employee_id"], "group": o["group"], "monitored": bool(o["monitored"]),
                         "_hours": round(hours, 2), "_true_job_id": j.job_id, "_unrecorded": unrecorded})
    return pd.DataFrame(rows)


CHANGE_ORDER_CUSTOMER = [None]
TOP_CUSTOMER = [None]
