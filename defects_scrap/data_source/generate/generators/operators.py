"""
HR operator roster: one row per operator employed at any point in the window,
with hire date, shift, the machine type each operator is trained on first
(primary) and the one they cover (secondary), and certification level.

The roster holds twenty on the floor. Operators who leave are replaced within
two weeks by a hire on the same shift and machine type.
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from faker import Faker

from ..config import (
    RANDOM_SEED, START_DATE, END_DATE, MACHINE_TYPES, PRIMARY_TYPE_HEADCOUNT,
    LEAVERS_IN_WINDOW, NEW_HIRE_SHIFT_B_SHARE,
)

# Shift A headcount by primary machine type; the remainder work Shift B.
_SHIFT_A_HEADCOUNT = {"Laser Cutting": 3, "Bending": 3, "Welding": 2, "Punching": 2}
# Leavers by primary machine type and shift.
_LEAVERS = [("Laser Cutting", "Shift B"), ("Bending", "Shift B"), ("Welding", "Shift B"),
            ("Bending", "Shift A"), ("Laser Cutting", "Shift B"), ("Punching", "Shift A")]


def build_operators() -> pd.DataFrame:
    """Returns the HR table plus two working columns (first_day, last_day) that
    the scheduler uses and the HR export does not carry."""
    rng = np.random.default_rng(RANDOM_SEED + 1)
    fake = Faker(); Faker.seed(RANDOM_SEED + 1)

    rows = []
    n = 0
    for mtype in MACHINE_TYPES:
        count = PRIMARY_TYPE_HEADCOUNT[mtype]
        tenure = np.round(rng.uniform(0.5, 12.0, count), 2)
        # Operators with under two years at the shop are placed on Shift B first.
        want_b = np.where(tenure < 2.0, NEW_HIRE_SHIFT_B_SHARE, 1.0 - NEW_HIRE_SHIFT_B_SHARE)
        order = np.argsort(-(want_b + rng.uniform(0, 0.25, count)))
        n_b = count - _SHIFT_A_HEADCOUNT[mtype]
        on_b = set(order[:n_b].tolist())
        for i in range(count):
            n += 1
            rows.append({
                "operator_id": f"OP{n:03d}",
                "operator_name": f"{fake.first_name()} {fake.last_name()}",
                "hire_date": (START_DATE - timedelta(days=int(tenure[i] * 365.25))).date(),
                "primary_machine_type": mtype,
                "secondary_machine_type": str(rng.choice([t for t in MACHINE_TYPES if t != mtype])),
                "shift": "Shift B" if i in on_b else "Shift A",
                "cert_level": str(rng.choice(["Level 1", "Level 2", "Level 3"], p=[0.35, 0.45, 0.20])),
                "first_day": START_DATE.date(),
                "last_day": END_DATE.date(),
            })
    ops = pd.DataFrame(rows)

    # Leavers at dates spread across the window, each replaced by a new hire.
    span = (END_DATE - START_DATE).days
    assert len(_LEAVERS) == LEAVERS_IN_WINDOW
    for k, (mtype, shift) in enumerate(_LEAVERS):
        pool = ops[(ops["primary_machine_type"] == mtype) & (ops["shift"] == shift)
                   & (ops["last_day"] == END_DATE.date()) & (ops["first_day"] == START_DATE.date())]
        leaver = pool.iloc[int(rng.integers(len(pool)))]
        seg = span / (LEAVERS_IN_WINDOW + 1)
        leave = (START_DATE + timedelta(days=int(seg * (k + 0.6) + rng.integers(0, int(seg * 0.6))))).date()
        hire = leave + timedelta(days=int(rng.integers(3, 15)))
        ops.loc[ops["operator_id"] == leaver["operator_id"], "last_day"] = leave
        n += 1
        ops.loc[len(ops)] = {
            "operator_id": f"OP{n:03d}",
            "operator_name": f"{fake.first_name()} {fake.last_name()}",
            "hire_date": hire,
            "primary_machine_type": mtype,
            "secondary_machine_type": str(rng.choice([t for t in MACHINE_TYPES if t != mtype])),
            "shift": shift,
            "cert_level": "Level 1",
            "first_day": hire,
            "last_day": END_DATE.date(),
        }
    return ops


HR_COLUMNS = ["operator_id", "operator_name", "hire_date", "primary_machine_type",
              "secondary_machine_type", "shift", "cert_level"]
