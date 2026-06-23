"""
QMS inspection records. Every job has a final inspection of the whole lot.
Most jobs also have a first-piece inspection: one piece checked 20 to 60
minutes after the job starts, with a failed piece reworked before the run
continues.

The QMS carries its own faults: final inspections entered twice after a session
timeout, inspection times filled in after the fact, and defect codes typed in
place of the dropdown value.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from .. import config as C
from ..faults.transformations import defect_as_entered, timestamp_entered_late

# Notes as inspectors write them, by what was found. {a}, {n} and {d} are filled
# with an angle, a feature or weld number and a deviation in inches.
_NOTES = {
    "pass": ["OK", "all dims in tol", "checked per traveler, OK", "no issues", "visual OK", "sampled 5, all good"],
    "first_piece_pass": ["first piece checked, OK", "FP OK, run released", "first piece in tol", "FP good, proceed"],
    "first_piece_fail": ["first piece out, setup adjusted", "FP rejected, offset corrected and rechecked",
                         "first piece reworked, second piece OK"],
    "Bend Angle": ["angle {a} at bend {n}, depth reset", "bend {n} over by {a2} deg, back gauge adjusted",
                   "springback on bend {n}, reformed", "angle out on flange {n}, held for MRB"],
    "Dimensional": ["dim B {d} over, held for MRB", "hole {n} location off {d}", "length short {d}, scrapped",
                    "dim A {d} under, reworked", "flange height {d} over"],
    "Burr": ["burr on edge, deburred", "heavy burr at hole {n}, deburred", "sharp edge, broke edges and released"],
    "Surface Scratch": ["scratch on face A, buffed out", "handling marks, reworked", "scratch through to base metal, scrapped",
                        "light scratches, customer use-as-is"],
    "Weld Defect": ["undercut at weld {n}, repaired", "incomplete fusion weld {n}, ground and rewelded",
                    "spatter on face, cleaned", "weld {n} undersize, added pass"],
    "Porosity": ["porosity at weld {n}, ground and rewelded", "pinholes weld {n}, repaired", "gas pocket at weld {n}, cut out and rewelded"],
    "Surface Contamination": ["light rust on blank, wiped", "oil under finish, stripped and recoated",
                              "rust bloom on sheet, cleaned before forming", "contamination under paint, reworked"],
    "Incorrect Material": ["wrong gauge pulled, scrapped", "material cert does not match, held", "wrong alloy on traveler, quarantined"],
}


def _note(stream, key: str) -> str:
    """One note for what was found, with its numbers filled in."""
    options = _NOTES[key]
    text = options[int(stream.integers(len(options)))]
    return text.format(a=f"{90 + stream.uniform(0.8, 2.5) * (1 if stream.random() < 0.5 else -1):.1f}",
                       a2=f"{stream.uniform(0.8, 2.5):.1f}", n=int(stream.integers(1, 7)),
                       d=f"{stream.uniform(0.006, 0.030):.3f}")


INSPECTION_COLUMNS = ["inspection_id", "work_order_id", "inspection_type", "inspection_date", "inspector_id",
                      "quantity_inspected", "quantity_passed", "quantity_failed", "defect_code_raw",
                      "defect_code_clean", "disposition", "notes"]


def build_inspections(jobs, operators: pd.DataFrame) -> pd.DataFrame:
    inspectors = operators["operator_id"].tolist()[:C.ROSTER_SIZE]
    dispositions, disp_w = list(C.DISPOSITION_WEIGHTS), list(C.DISPOSITION_WEIGHTS.values())

    rows = []
    counter = 1
    for j in jobs:
        # A random stream per work order, so one job's draws do not move another's.
        rng = np.random.default_rng([C.RANDOM_SEED, 6, int(j["work_order_id"][3:])])
        # Notes are drawn on a stream of their own.
        notes = np.random.default_rng([C.RANDOM_SEED, 9, int(j["work_order_id"][3:])])
        qty = j["quantity"]
        codes, weights = list(j["code_mix"]), np.array(list(j["code_mix"].values()))
        weights = weights / weights.sum()

        # First-piece inspection, where one was recorded.
        if j["has_first_piece"]:
            failed = int(rng.random() < min(0.5, 3.0 * j["defect_probability"]))
            code = str(rng.choice(codes, p=weights)) if failed else "None"
            rows.append({
                "inspection_id": f"INSP-{counter}", "work_order_id": j["work_order_id"],
                "inspection_type": "first_piece",
                "inspection_date": str(j["job_start"] + timedelta(minutes=float(rng.uniform(*C.FIRST_PIECE_DELAY_MINUTES)))),
                "inspector_id": inspectors[int(rng.integers(len(inspectors)))],
                "quantity_inspected": 1, "quantity_passed": 1 - failed, "quantity_failed": failed,
                "defect_code_raw": defect_as_entered(rng, code), "defect_code_clean": code,
                "disposition": "Rework" if failed else "Pass",
                "notes": _note(notes, "first_piece_fail" if failed else "first_piece_pass")
                         if notes.random() < C.INSPECTION_NOTE_SHARE else None,
            })
            counter += 1

        # Final inspection of the lot.
        failed = int(rng.binomial(qty, j["defect_probability"]))
        code = str(rng.choice(codes, p=weights)) if failed else "None"
        when = j["job_start"] + timedelta(hours=float(rng.uniform(*C.FINAL_INSPECTION_DELAY_HOURS)))
        if rng.random() < C.FAULTS["inspection_timestamp_off"]:
            when = timestamp_entered_late(rng, when)
        record = {
            "inspection_id": f"INSP-{counter}", "work_order_id": j["work_order_id"],
            "inspection_type": "final", "inspection_date": str(when),
            "inspector_id": inspectors[int(rng.integers(len(inspectors)))],
            "quantity_inspected": qty, "quantity_passed": qty - failed, "quantity_failed": failed,
            "defect_code_raw": defect_as_entered(rng, code), "defect_code_clean": code,
            "disposition": dispositions[int(rng.choice(len(dispositions), p=disp_w))] if failed else "Pass",
            "notes": _note(notes, code if failed else "pass") if rng.random() < C.INSPECTION_NOTE_SHARE else None,
        }
        rows.append(record)
        counter += 1
        j["final_inspection_id"] = record["inspection_id"]
        j["quantity_failed"] = failed
        j["defect_code"] = code
        j["disposition"] = record["disposition"]
        j["inspection_time"] = when

        # A session timeout makes the inspector enter the final inspection again.
        if rng.random() < C.FAULTS["inspection_duplicate"]:
            again = dict(record)
            again["inspection_id"] = f"INSP-{counter}"
            again["inspection_date"] = str(when + timedelta(minutes=int(rng.integers(2, 46))))
            if rng.random() < 0.30:
                again["quantity_failed"] = int(min(qty, max(0, failed + rng.integers(-2, 3))))
                again["quantity_passed"] = qty - again["quantity_failed"]
            rows.append(again)
            counter += 1
    return pd.DataFrame(rows)[INSPECTION_COLUMNS]
