"""
QMS scrap and rework events: one row per final inspection with failed pieces
dispositioned as scrap or rework. Reason codes mix QA's structured codes with
operators' free text, and the cost fields are the technician's estimate, not a
job costing.
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
    rng = np.random.default_rng(C.RANDOM_SEED + 7)
    rows = []
    counter = 1
    for j in jobs:
        failed = j["quantity_failed"]
        if failed <= 0 or j["disposition"] not in ("Scrap", "Rework"):
            continue
        p = j["part"]
        reason = SCRAP_REASONS[int(rng.choice(len(SCRAP_REASONS), p=_REASON_BY_DEFECT[j["defect_code"]]))]
        noise = lambda: float(rng.uniform(1 - C.COST_ESTIMATE_NOISE, 1 + C.COST_ESTIMATE_NOISE))
        material = round(p["material_cost_per_piece"] * noise(), 2)
        labor = round(p["rework_labor_per_piece"] * noise(), 2)
        if j["disposition"] == "Scrap":
            # The piece is lost: its material and half the labor already in it.
            scrapped, reworked = failed, 0
            total = round(scrapped * (material + 0.5 * labor), 2)
        else:
            scrapped, reworked = 0, failed
            total = round(reworked * labor, 2)
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
