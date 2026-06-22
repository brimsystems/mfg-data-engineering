"""
QMS scrap, rework and use-as-is events: one row per final inspection with failed
pieces. Reason codes mix QA's structured codes with operators' free text, and
the cost fields are the technician's estimate, not a job costing.

  Scrap       the piece is lost: its material and the labor to the operation
              where it failed, a share of the part's unit price
  Rework      labor to bring the piece back into tolerance
  Use-As-Is   no piece cost; a quarter hour of engineering review per event
"""
import numpy as np
import pandas as pd

from .. import config as C
from ..faults.transformations import scrap_reason_as_entered

SCRAP_REASONS = ["OPERATOR_ERROR", "MATERIAL_DEFECT", "MACHINE_ISSUE", "SETUP_ERROR", "DESIGN_ISSUE", "UNKNOWN"]

# Reason the technician most often records for each defect code.
_REASON_BY_DEFECT = {
    "Dimensional":           [0.20, 0.10, 0.20, 0.35, 0.05, 0.10],
    "Surface Scratch":       [0.10, 0.45, 0.30, 0.05, 0.00, 0.10],
    "Burr":                  [0.15, 0.10, 0.45, 0.20, 0.00, 0.10],
    "Weld Defect":           [0.45, 0.15, 0.25, 0.10, 0.00, 0.05],
    "Porosity":              [0.60, 0.10, 0.20, 0.05, 0.00, 0.05],
    "Incorrect Material":    [0.05, 0.75, 0.00, 0.05, 0.05, 0.10],
    "Bend Angle":            [0.20, 0.05, 0.30, 0.35, 0.05, 0.05],
    "Surface Contamination": [0.10, 0.60, 0.10, 0.05, 0.00, 0.15],
}

SCRAP_COLUMNS = ["scrap_id", "work_order_id", "inspection_id", "scrap_date", "machine_id", "operator_id",
                 "shift_code", "material_type", "lot_id", "defect_code_clean", "disposition",
                 "quantity_scrapped", "quantity_reworked", "scrap_reason_raw", "scrap_reason_clean",
                 "material_cost_per_unit", "labor_cost_per_unit", "total_scrap_cost"]


def build_scrap_events(jobs) -> pd.DataFrame:
    rows = []
    counter = 1
    part_share = {}
    for j in jobs:
        failed = j["quantity_failed"]
        if failed <= 0:
            continue
        p = j["part"]
        # A random stream per work order, and one per part for the part's cost share.
        rng = np.random.default_rng([C.RANDOM_SEED, 7, int(j["work_order_id"][3:])])
        if p["part_number"] not in part_share:
            part_share[p["part_number"]] = float(np.random.default_rng(
                [C.RANDOM_SEED, 8, int(p["part_number"][2:])]).uniform(*C.SCRAP_COST_SHARE_OF_PRICE))
        reason = SCRAP_REASONS[int(rng.choice(len(SCRAP_REASONS), p=_REASON_BY_DEFECT[j["defect_code"]]))]
        noise = float(rng.uniform(1 - C.COST_ESTIMATE_NOISE, 1 + C.COST_ESTIMATE_NOISE))
        material = labor = 0.0
        scrapped = reworked = 0
        if j["disposition"] == "Scrap":
            scrapped = failed
            material = round(p["unit_price"] * part_share[p["part_number"]] * noise, 2)
            total = round(scrapped * material, 2)
        elif j["disposition"] == "Rework":
            reworked = failed
            labor = round(float(rng.uniform(*C.REWORK_HOURS_PER_PIECE)) * C.LABOR_RATE_PER_HOUR * noise, 2)
            total = round(reworked * labor, 2)
        else:
            total = round(C.USE_AS_IS_REVIEW_HOURS * C.LABOR_RATE_PER_HOUR * noise, 2)
        rows.append({
            "scrap_id": f"SCRAP-{counter}",
            "work_order_id": j["work_order_id"],
            "inspection_id": j["final_inspection_id"],
            "scrap_date": str(j["inspection_time"]),
            "machine_id": j["machine_id"],
            "operator_id": j["operator_id"],
            "shift_code": j["shift"],
            "material_type": p["material_type"],
            "lot_id": j["lot"]["lot_id_clean"],
            "defect_code_clean": j["defect_code"],
            "disposition": j["disposition"],
            "quantity_scrapped": scrapped,
            "quantity_reworked": reworked,
            "scrap_reason_raw": scrap_reason_as_entered(rng, reason),
            "scrap_reason_clean": reason,
            "material_cost_per_unit": material,
            "labor_cost_per_unit": labor,
            "total_scrap_cost": total,
        })
        counter += 1
    return pd.DataFrame(rows)[SCRAP_COLUMNS]
