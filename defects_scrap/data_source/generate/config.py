"""
Configuration for the defects and scrap data set: the shop, its five systems,
the factors that drive piece defect probability, the record faults each system
carries, and the range each check in checks.py must land in.

Every rate, multiplier and range is declared here once.
"""
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
MODULE_DIR  = Path(__file__).parent.parent.parent
RAW_DIR     = MODULE_DIR / "data_source" / "raw"
SAMPLES_DIR = MODULE_DIR / "data_source" / "samples"
TRUTH_DIR   = MODULE_DIR / "data_source" / "generate" / "truth"   # git-ignored

RANDOM_SEED = 42
SAMPLE_SIZE = 200

# ── Window and calendar ───────────────────────────────────────────────────
START_DATE = datetime(2023, 1, 2)
END_DATE   = datetime(2026, 3, 31)
SATURDAY_WORK_PROB = 0.20                 # share of Saturdays worked
BUSY_MONTHS  = (3, 4, 10)                 # three busiest months of each year
QUIET_MONTHS = (7, 12)                    # two quietest months of each year
VOLUME_FACTOR = {"busy": 1.25, "normal": 1.00, "quiet": 0.80}

SHIFT_HOURS = {"Shift A": (6, 14), "Shift B": (14, 22)}

# ── The shop ──────────────────────────────────────────────────────────────
TARGET_REVENUE_PER_YEAR = 30_000_000      # unit price x quantity shipped; check range 27M to 33M

# machine_id, machine_name, machine_type, age_years, location
MACHINES_DATA = [
    ("M01", "Laser Cutter 1",    "Laser Cutting", 3,  "Bay A"),
    ("M02", "Laser Cutter 2",    "Laser Cutting", 8,  "Bay A"),
    ("M03", "Press Brake 1",     "Bending",       12, "Bay B"),
    ("M04", "Press Brake 2",     "Bending",       2,  "Bay B"),
    ("M05", "Welding Station 1", "Welding",       6,  "Bay C"),
    ("M06", "Welding Station 2", "Welding",       4,  "Bay C"),
    ("M07", "Punch Press 1",     "Punching",      9,  "Bay A"),
]
MACHINE_TYPES = ["Laser Cutting", "Bending", "Welding", "Punching"]

CUSTOMERS = [f"Customer {chr(65 + i)}" for i in range(25)]
TOP_CUSTOMERS = 5
TOP_CUSTOMER_REVENUE_SHARE = 0.55        # share of revenue held by the five largest customers

# Material, nominal thickness in inches, and whether it is cold-rolled gauge steel.
MATERIALS = {
    "16ga Steel":    {"nominal_thickness_in": 0.0598, "gauge_steel": True},
    "14ga Steel":    {"nominal_thickness_in": 0.0747, "gauge_steel": True},
    "12ga Steel":    {"nominal_thickness_in": 0.1046, "gauge_steel": True},
    '1/4" Plate':    {"nominal_thickness_in": 0.2500, "gauge_steel": False},
    '3/8" Plate':    {"nominal_thickness_in": 0.3750, "gauge_steel": False},
    "Aluminum 5052": {"nominal_thickness_in": 0.0900, "gauge_steel": False},
    "Stainless 304": {"nominal_thickness_in": 0.0750, "gauge_steel": False},
}
MATERIAL_WEIGHTS = [0.22, 0.20, 0.16, 0.10, 0.07, 0.13, 0.12]   # share of parts by material
# Formed parts are mostly gauge steel; plate is rarely run on the brakes.
BRAKE_MATERIAL_WEIGHTS = [0.36, 0.30, 0.16, 0.02, 0.01, 0.08, 0.07]

# ── Job volume ────────────────────────────────────────────────────────────
# Jobs released per working day before the monthly factor.
JOBS_PER_DAY_RANGE = (34, 46)             # about 40 a day, about 35,000 jobs over the window
LOT_SIZE_RANGE     = (5, 25)              # pieces per work order
RUN_MINUTES_PER_PIECE = {                 # run time per piece by machine type (min, max)
    "Laser Cutting": (3, 7), "Bending": (3, 8), "Welding": (4, 8), "Punching": (3, 7),
}
MACHINE_TYPE_PART_SHARE = {"Laser Cutting": 0.29, "Bending": 0.29, "Welding": 0.27, "Punching": 0.15}
PART_DEMAND_SIGMA = 0.9                   # spread of order frequency across part numbers

# ── ERP part catalog ──────────────────────────────────────────────────────
PARTS_AT_START = 300
NEW_PARTS_PER_YEAR = 150                  # released at random dates
COMPLEXITY_WEIGHTS = {"Low": 0.35, "Medium": 0.45, "High": 0.20}
REVISIONS_PER_PART_YEAR = 0.5             # revision changes per part per year, before weighting
# Weighting of revision changes toward complex parts.
REVISION_WEIGHT_BY_COMPLEXITY = {"Low": 0.6, "Medium": 1.0, "High": 2.2}
REVISION_LETTERS = ["A", "B", "C", "D"]
STD_SETUP_MIN = {                         # standard setup minutes by machine type
    "Bending": (25, 45), "Laser Cutting": (10, 20), "Welding": (15, 30), "Punching": (15, 25),
}
UNIT_PRICE_RANGE = (40, 320)              # dollars per piece; set so revenue lands near the target

# ── ERP work orders ───────────────────────────────────────────────────────
RUSH_SHARE = {"busy": 0.20, "normal": 0.089, "quiet": 0.07}   # expedited by the planner
DUE_DAYS_ROUTINE = (5, 15)                # working days from order date to due date
DUE_DAYS_RUSH    = (1, 3)
ERP_START_LAG_SHARE   = 0.30              # orders whose ERP start is entered late
ERP_START_LAG_MINUTES = (0, 90)

# ── MES job log ───────────────────────────────────────────────────────────
SETUP_LOGNORMAL_SIGMA   = 0.25            # spread of setup minutes around the part's standard
RUSH_SETUP_MEDIAN_RATIO = 0.65            # rush jobs: median setup as a share of standard
# Probability the planner keeps the next brake job on the same thickness as the last.
BRAKE_SAME_GAUGE_PROB   = 0.90            # tuned so check C10 lands in range

# ── Operator days and overtime ────────────────────────────────────────────
STANDARD_DAY_HOURS = (8.0, 9.0)
LONG_DAY_HOURS     = (10.0, 12.0)
# Share of working days on which the shop runs long.
LONG_DAY_SHARE = {"busy": 0.38, "normal": 0.08, "quiet": 0.03}   # about 15% of working days overall
LONG_DAY_LAST_JOB_OVERRUN_MIN = 60        # the last job on a long day may finish this far past the planned hours
LONG_DAY_RUSH_WEEK_LIFT = 1.5             # odds lift in weeks with more rush jobs than usual
LONG_DAY_OPERATOR_SHARE = {"Bending": 0.85, "Welding": 0.85, "Laser Cutting": 0.40, "Punching": 0.40}

# ── QMS inspections ───────────────────────────────────────────────────────
FIRST_PIECE_PRESENCE = {"routine": 0.80, "rush": 0.58}
FIRST_PIECE_SHORT_SETUP_RATIO   = 0.60    # setup below this share of standard ...
FIRST_PIECE_SHORT_SETUP_PENALTY = 0.15    # ... lowers presence by this many points
FIRST_PIECE_DELAY_MINUTES = (20, 60)      # after job start
FINAL_INSPECTION_DELAY_HOURS = (1.0, 5.5) # after job start
DISPOSITION_WEIGHTS = {"Scrap": 0.45, "Rework": 0.42, "Use-As-Is": 0.13}

# Defect code mix by machine type when a job has failed pieces.
DEFECT_MIX = {
    "Laser Cutting": {"Surface Scratch": 0.38, "Dimensional": 0.30, "Burr": 0.20, "Incorrect Material": 0.08, "Surface Contamination": 0.04},
    "Bending":       {"Bend Angle": 0.42, "Dimensional": 0.31, "Burr": 0.13, "Surface Scratch": 0.10, "Surface Contamination": 0.04},
    "Welding":       {"Weld Defect": 0.42, "Porosity": 0.24, "Dimensional": 0.20, "Surface Scratch": 0.10, "Surface Contamination": 0.04},
    "Punching":      {"Burr": 0.43, "Dimensional": 0.30, "Surface Scratch": 0.14, "Bend Angle": 0.09, "Surface Contamination": 0.04},
}

# ── Materials receiving ───────────────────────────────────────────────────
SUPPLIERS        = ["Supplier A", "Supplier B", "Supplier C", "Supplier D"]
SUPPLIER_WEIGHTS = [0.35, 0.30, 0.25, 0.10]
CERT_MIX = {
    "Supplier C": {"Certified": 0.55, "Conditional": 0.30, "Missing": 0.15},
    "default":    {"Certified": 0.80, "Conditional": 0.14, "Missing": 0.06},
}
THICKNESS_MEASURED_SHARE = 0.70           # lots with a micrometer check at receiving
THICKNESS_DEVIATION_SD_PCT = {"Supplier A": 1.5, "Supplier B": 1.5, "Supplier C": 3.5, "Supplier D": 1.5}
UNCERTIFIED_SD_FACTOR = 1.5               # Conditional or Missing cert: sd times this
LOT_PULL_FIFO_SHARE = 0.70                # first-in-first-out; otherwise the most recent lot
LOT_JOBS_CAPACITY = (25, 50)              # jobs a lot serves before it is used up
LOT_REORDER_WEEKS = 5.6                   # a material is reordered when stock falls below this many weeks of use
BULK_BUY_WEEKLY_PROB = 0.02               # chance in a week that purchasing buys a material well ahead
BULK_BUY_WEEKS = 10.0                     # extra weeks of cover bought on those occasions

# ── HR operators ──────────────────────────────────────────────────────────
ROSTER_SIZE     = 20                      # on the floor at any time
LEAVERS_IN_WINDOW = 6                     # each replaced by a hire within two weeks
NEW_HIRE_SHIFT_B_SHARE = 0.70             # operators under two years at the shop
PRIMARY_TYPE_HEADCOUNT = {"Laser Cutting": 6, "Bending": 6, "Welding": 5, "Punching": 3}
# Jobs the supervisor gives to an operator of the machine's own type. Cover is not
# always on shift, so the share measured in the job log sits a little higher.
PRIMARY_MACHINE_JOB_SHARE = 0.81
ABSENCE_RATE = 0.04                       # operator-days absent; coverage rises on these days
# Jobs already run on the primary machine type by operators on the roster at the
# window start, per year of tenure: the rate of jobs per operator-year on the
# primary machine type inside the window. The secondary type starts at a quarter.
PRIOR_JOBS_PER_TENURE_YEAR = 480
SECONDARY_PRIOR_SHARE = 0.25

# ── Piece defect probability ──────────────────────────────────────────────
# Probability a piece fails final inspection: the base rate times every factor
# below that applies to the job. Factors compound. Shift, supplier name and
# certification level carry no factor of their own.
BASE_DEFECT_RATE = 0.03
DEFECT_PROBABILITY_CAP = 0.60

GAUGE_DEVIATION = {                       # per percentage point of absolute thickness deviation
    "Bending":       {"slope": 0.25, "cap": 2.5, "codes": ["Bend Angle"]},
    "Laser Cutting": {"slope": 0.08, "cap": 2.5, "codes": ["Dimensional"]},
    "Punching":      {"slope": 0.08, "cap": 2.5, "codes": ["Dimensional"]},
    "Welding":       None,
}
FIRST_RUN = {"first": 2.0, "second": 1.3, "codes": ["Dimensional", "Bend Angle"]}
BRAKE_GAUGE_CHANGE = {"factor": 1.6, "codes": ["Bend Angle"]}   # preceding brake job ran another thickness
NO_FIRST_PIECE = 2.0                      # no first-piece record on the job
PAST_TENTH_HOUR = 1.5                     # job starts after the tenth hour of the operator's day
EXPERIENCE = [(50, 2.0), (150, 1.4), (300, 1.15), (None, 1.0)]  # cumulative jobs on the machine type
LOT_AGE_GAUGE_STEEL = [(60, 1.0), (120, 1.4), (None, 1.8)]      # days since receipt
LOT_AGE_CODES = {"Welding": "Porosity", "other": "Surface Contamination"}
COMPLEXITY = {"Low": 1.0, "Medium": 1.1, "High": 1.3}
LOT_AGE_CODE_SHARE = 0.33                 # the same share for the lot-age codes
BIASED_CODE_SHARE = 0.50                  # share of the added defects that take the factor's codes

# ── Scrap and rework cost ─────────────────────────────────────────────────
MATERIAL_COST_PER_PIECE = (5, 30)         # dollars, by part
REWORK_LABOR_PER_PIECE  = (6, 24)         # dollars, by part
COST_ESTIMATE_NOISE     = 0.15            # costs are estimated by the technician, not costed

# ── Record faults ─────────────────────────────────────────────────────────
FAULTS = {
    "part_number_noncanonical": 0.45,     # five formats; 55% canonical
    "erp_operator_as_name":     0.05,
    "erp_shift_code_null":      0.10,
    "erp_lot_id_null":          0.15,
    "lot_id_noncanonical":      0.40,
    "inspection_duplicate":     0.08,     # final inspections entered twice
    "inspection_timestamp_off": 0.03,
    "lot_thickness_unmeasured": 0.30,
    "job_log_operator_as_name": 0.05,
    "job_log_end_before_start": 0.04,     # clock entry error, corrected in staging
}

# ── Check ranges (checks.py reports measured, range, pass or fail) ────────
MONOTONIC_MIN_JOBS = 30                   # deviation bands with fewer jobs are left out and listed
CHECKS = {
    "C1 overall defect rate":                         (0.050, 0.070),
    "C2 scrap and rework cost a year":                (150_000, 220_000),
    "Revenue a year":                                 (27_000_000, 33_000_000),
    "C3.1 bend-angle rate rises across deviation bands, Supplier C and the others pooled": "monotonic",
    "C3.1 Supplier C against others, brake jobs":     (1.3, 1.6),
    "C3.1 Supplier C against others, within band":    (0.9, 1.1),
    "C3.2 first run against later runs":              (1.7, 2.4),
    "C3.2 first runs as a share of high-complexity jobs": (0.03, 0.06),
    "C3.2 high against low complexity, later runs":   (1.2, 1.4),
    "C3.3 brake job after a gauge change":            (1.4, 1.8),
    "C3.3 laser job after a gauge change":            (0.9, 1.1),
    "C3.4 no first-piece record":                     (1.7, 2.3),
    "C3.4 first-piece skip rate, rush":               (0.40, 0.50),
    "C3.4 first-piece skip rate, routine":            (0.15, 0.25),
    "C3.4 past the tenth hour":                       (1.3, 1.7),
    "C3.4 jobs past the tenth hour, all":             (0.004, 0.009),
    "C3.4 jobs past the tenth hour, busy months":     (0.010, 0.025),
    "C3.5 under 50 jobs against over 300":            (1.7, 2.3),
    "C3.5 experience curve":                          "monotonic",
    "C3.6 gauge steel, 60 to 120 days":               (1.3, 1.6),
    "C3.6 gauge steel, past 120 days":                (1.6, 2.1),
    "C3.6 other materials, past 60 days":             (0.9, 1.1),
    "C3.6 porosity and contamination share, old against fresh lots": (1.8, 2.4),
    "C4 Shift B against Shift A, all jobs":           (1.0, 1.3),
    "C4 Shift B against Shift A, operators over 300 jobs": (0.9, 1.1),
    "C5 rush share, all":                             (0.11, 0.13),
    "C5 rush share, busy months":                     (0.18, 0.22),
    "C5 rush share, quiet months":                    (0.06, 0.08),
    "C5 first-piece presence, routine":               (0.75, 0.85),
    "C5 first-piece presence, rush":                  (0.50, 0.60),
    "C5 long days as a share of working days":        (0.13, 0.17),
    "C6 coverage share of jobs":                      (0.12, 0.18),
    "C7 revision events":                             (700, 900),
    "C7 new parts":                                   (450, 530),
    "C7 first runs as a share of jobs":               (0.025, 0.035),
    "C8 lots with thickness measured":                (0.65, 0.75),
    "C9 gauge-steel jobs on lots past 60 days":       (0.15, 0.25),
    "C10 brake jobs following a gauge change":        (0.30, 0.45),
    "C11 record-fault rates":                         "within 2 points of FAULTS",
    "C12 physical sense violations":                  (0, 0),
}

# ── Source system for each table (drives the output folders) ──────────────
TABLE_SYSTEM_MAP = {
    "machines":           "mes",
    "job_log":            "mes",
    "operators":          "hr",
    "material_lots":      "materials",
    "part_catalog":       "erp",
    "production_orders":  "erp",
    "inspection_records": "qms",
    "scrap_events":       "qms",
}
