"""
MES machine register: one row per machine on the floor.
"""
import pandas as pd

from ..config import MACHINES_DATA


def build_machines() -> pd.DataFrame:
    return pd.DataFrame(
        MACHINES_DATA,
        columns=["machine_id", "machine_name", "machine_type", "age_years", "location"],
    )
