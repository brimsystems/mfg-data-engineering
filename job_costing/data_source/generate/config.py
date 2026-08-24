"""Central configuration for the job costing and margin analytics platform.

Every choice that decides whether the case works lives here as a named constant:
the observation window and the engagement, the shop's size and mix, the work
centers and their rates, the part families and materials, the scale of every
planted defect, and the share of every review decision. The generators read this
module and nothing else for their calibration, so the whole build can be tuned
from one place.

The company is a precision machining shop: about $55M of revenue, 210 employees,
twenty-eight CNC work centers plus sawing, deburr, inspection and assembly, with
plating, heat treat, coating and grinding sent outside. Roughly 65% of revenue is
repeat contract parts on blanket orders at standing prices, 30% is new quoted
work, and 5% is a small line of the shop's own standard components sold from a
price list.
"""
from datetime import date, timedelta
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data_source" / "raw"
TRUTH_DIR = REPO_ROOT / "data_source" / "truth"
SAMPLES_DIR = REPO_ROOT / "data_source" / "samples"

# ── Reproducibility ─────────────────────────────────────────────────────────
RANDOM_SEED = 4
SAMPLE_SIZE = 200

# ── Observation window ──────────────────────────────────────────────────────
# Thirty-six months of history ending June 30, 2026. The final twelve weeks are
# the engagement. Calendar 2025 is the analysis year for the margin distribution.
START_DATE = date(2023, 7, 1)
END_DATE = date(2026, 6, 30)
ANALYSIS_YEAR = 2025
ENGAGEMENT_START = date(2026, 4, 6)          # Monday of engagement week 1
ENGAGEMENT_WEEKS = 12


def engagement_week(d):
    """Engagement week number for a date (1..12), or None before the engagement.
    The last two days of June fall into week 12."""
    if d < ENGAGEMENT_START:
        return None
    return min((d - ENGAGEMENT_START).days // 7 + 1, ENGAGEMENT_WEEKS)


# Configuration changes go live in weeks 4 to 6. Each date is the first day on
# which the new behavior appears in the data.
CONFIG_DATES = {
    "estimate_to_job":     date(2026, 4, 27),  # quote converts with est_* fields populated
    "po_job_required":     date(2026, 4, 27),  # job number required on outside-processing POs
    "rate_pools_live":     date(2026, 5, 4),   # work-center rate pools replace the blended rate
    "terminals_at_cells":  date(2026, 5, 4),   # clock terminals moved from the door to the cells
    "one_open_operation":  date(2026, 5, 4),   # an employee can hold one open operation
    "auto_close":          date(2026, 5, 4),   # open clock records close at shift end, flagged
    "labor_type_codes":    date(2026, 5, 4),   # setup, run, rework and indirect codes
    "scrap_reason_req":    date(2026, 5, 11),  # a scrap event cannot post without a reason
    "monitoring_to_jobs":  date(2026, 5, 11),  # machine hours post to jobs by program and open job
    "standard_fallback":   date(2026, 5, 11),  # missing scan -> routing standard, tagged estimated
}
SCAN_ROLLOUT_START = date(2026, 4, 13)        # traveler scanning pilot begins, week 2

# ── The shop ────────────────────────────────────────────────────────────────
REVENUE_ANNUAL = 55_000_000
JOBS_PER_YEAR = 3_800
REVENUE_MIX = {"repeat": 0.65, "new": 0.30, "own_product": 0.05}
N_CUSTOMERS = 58
CUSTOMER_TAIL_DECAY = 0.93        # geometric decay of revenue weight below the two named accounts
N_PARTS_REPEAT = 1_600
N_PARTS_NEW = 800                 # new-work parts quoted in the window or the year before it
NEW_PART_QUOTE_LINES = 10.0        # Poisson mean of quote lines per new-work part, plus one
NEW_WORK_LOT_FACTOR = 0.85        # new-work lots run a little smaller than repeat lots
N_OWN_PRODUCTS = 14
N_ESTIMATORS = 3                  # the senior estimator quotes most of the work
SENIOR_ESTIMATOR_SHARE = 0.72
N_OPERATORS = 118
SHIFTS = [(6, 14), (14, 22), (22, 6)]     # three shifts; the third runs the lights-out cells
TARGET_MARKUP = 0.28              # target markup on cost; about 22% margin on price
QUOTED_MARKUP = (0.36, 0.03)      # what the estimator actually quotes: mean and spread of markup on his estimate
FAMILY_MARKUP_SHIFT = {"manual_heavy": -0.10, "fax_heavy": 0.0}
TOP_CUSTOMER_MARKUP_SHIFT = -0.01
TOP_CUSTOMER_REWORK_MULT = 1.6      # the largest account expedites and rejects more than most
INDUSTRY_MARKUP_SHIFT = {"Aerospace": 0.05, "Medical devices": 0.04, "Fluid power": -0.02, "Transportation": -0.03}   # regulated work carries a premium; commodity segments are bid lean
TOP_CUSTOMER_INDUSTRY = "Industrial equipment"
CHANGE_ORDER_CUSTOMER_INDUSTRY = "Aerospace"   # the largest account buys on volume pricing; its margin sits in the bottom third   # P4: lean on "simple" work, cushion on complex work
REPEAT_RELEASES_3Y = 3.7          # Poisson mean of releases per repeat part over the window, plus one
OWN_PRODUCT_LOT_MEDIAN = 250

# Revenue concentration: the top customer carries 18-24% of revenue with margin in
# the bottom third; the second-largest is the change-order customer (P3).
TOP_CUSTOMER_SHARE = 0.23
SECOND_CUSTOMER_SHARE = 0.11
TOP10_SHARE = 0.65
CHANGE_ORDER_CUSTOMER_RANK = 2    # P3: revision changes after release, never billed
LOSS_CUSTOMER_RANK = 40           # a customer won recently by matching a competitor's bid on new work, below the shop's own estimate
LOSS_CUSTOMER_NEW_WORK_MARKUP = (-0.14, -0.06)   # markup on that customer's new-work quotes

# ── Work centers ────────────────────────────────────────────────────────────
# id prefix -> (count, type, monitored, lights-out share of hours, true labor rate,
# true burden rate, attended ratio). Rates are the cost pools the engagement
# builds; the ERP carries one blended rate for all of them (M3).
WORK_CENTER_GROUPS = {
    "VMC": (7, "Vertical mill",      True,  0.00, 34.0,  52.0, 0.90),
    "FAX": (3, "5-axis mill",        True,  0.10, 38.0,  92.0, 0.80),
    "HMC": (4, "Horizontal mill",    True,  0.25, 36.0,  70.0, 0.70),
    "LTH": (5, "CNC lathe",          True,  0.15, 33.0,  56.0, 0.85),
    "MTN": (4, "Mill-turn",          True,  0.20, 37.0,  70.0, 0.75),
    "SWS": (3, "Swiss",              True,  0.55, 35.0,  70.0, 0.35),
    "EDM": (2, "Wire EDM",           True,  0.50, 33.0,  68.0, 0.40),
    "SAW": (2, "Saw",                False, 0.00, 28.0,  24.0, 1.00),
    "MDP": (1, "Manual drill press", False, 0.00, 28.0,  20.0, 1.00),
    "DBR": (3, "Deburr",             False, 0.00, 27.0,  18.0, 1.00),
    "INS": (2, "Inspection",         False, 0.00, 36.0,  28.0, 1.00),
    "ASM": (2, "Assembly",           False, 0.00, 30.0,  22.0, 1.00),
}
SECONDARY_GROUPS = ["SAW", "MDP", "DBR", "INS", "ASM"]
# The blended shop rate (labor plus burden) the ERP applies everywhere, refreshed
# once a year (M3). Calibrated so total labor-and-burden cost matches the pools.
BLENDED_RATE = {2023: 164.0, 2024: 171.0, 2025: 178.0, 2026: 185.0}
RATE_EFFECTIVE_DATES = [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]
POOL_RATE_DRIFT = 0.030           # annual rise in the true pool rates

PRICE_HISTORY_START = date(2019, 1, 1)   # price history reaches back to the oldest standing prices

# ── Materials ───────────────────────────────────────────────────────────────
# spec -> (stock form, $/lb at July 2023, annual price drift, P1 cohort flag).
# Aluminum and stainless bar rise 20-35% over the window; that is the erosion
# behind P1. Titanium and Inconel are the estimator-bias materials (P5).
MATERIALS = {
    "AL 6061-T6 bar":    ("bar",     4.10, 0.078, True),
    "AL 7075-T6 bar":    ("bar",     5.60, 0.075, True),
    "AL 6061 plate":     ("plate",   3.90, 0.050, False),
    "SS 303 bar":        ("bar",     4.80, 0.072, True),
    "SS 304 bar":        ("bar",     4.40, 0.070, True),
    "SS 316 bar":        ("bar",     5.90, 0.074, True),
    "SS 17-4PH bar":     ("bar",     8.20, 0.050, False),
    "1018 steel bar":    ("bar",     1.35, 0.040, False),
    "4140 steel bar":    ("bar",     1.85, 0.045, False),
    "4140 forging":      ("forging", 3.10, 0.050, False),
    "Brass 360 bar":     ("bar",     6.30, 0.060, False),
    "Ti 6Al-4V bar":     ("bar",    28.00, 0.050, False),
    "Inconel 718 bar":   ("bar",    36.00, 0.045, False),
    "Delrin rod":        ("rod",     3.20, 0.030, False),
    "AL 356 casting":    ("casting", 6.50, 0.055, False),
    "SS 316 tube":       ("tube",    7.40, 0.055, False),
}
ESTIMATOR_BIAS_MATERIALS = ["Ti 6Al-4V bar", "Inconel 718 bar"]
ESTIMATOR_RUN_BIAS = (0.30, 0.45)     # P5: run hours over estimate on those materials

# ── Part families ───────────────────────────────────────────────────────────
# family -> (share of parts, primary work-center groups, secondary ops, material
# specs, outside-processing services, run minutes per piece range, setup hours
# range, weight per piece lb range, rate-pool reversal role)
PART_FAMILIES = {
    "Aluminum housings":        (0.16, ["VMC", "VMC", "HMC"],        ["SAW", "DBR", "INS"],        ["AL 6061-T6 bar", "AL 7075-T6 bar", "AL 6061 plate"], ["anodize", "chem film"], (7.34, 40.4),  (1.5, 4.0), (1.56, 15.6),  None),
    "Stainless fittings":       (0.15, ["LTH", "LTH", "MTN"],        ["SAW", "DBR", "INS"],        ["SS 303 bar", "SS 304 bar", "SS 316 bar"],            ["passivate"], (5.51, 25.7),  (1.2, 3.0), (0.52, 6.5),  None),
    "Steel shafts and pins":    (0.12, ["LTH", "SWS"],        ["SAW", "DBR", "INS"],        ["1018 steel bar", "4140 steel bar"],                  ["heat treat", "grind"], (3.67, 16.5),   (1.0, 2.5), (0.78, 10.4),  None),
    "Swiss turned components":  (0.12, ["SWS"],               ["DBR", "INS"],               ["SS 303 bar", "Brass 360 bar", "SS 17-4PH bar"],      ["passivate"], (1.47, 7.34), (1.5, 3.5), (0.052, 0.78), None),
    "Aerospace brackets":       (0.08, ["FAX", "FAX", "VMC"],        ["SAW", "DBR", "INS"],        ["Ti 6Al-4V bar", "AL 7075-T6 bar"],                   ["anodize", "NDT"], (22, 82.6), (2.5, 6.0), (1.04, 7.8),  "fax_heavy"),
    "Turbine components":       (0.05, ["FAX", "MTN", "EDM"], ["DBR", "INS"],               ["Inconel 718 bar", "SS 17-4PH bar"],                  ["heat treat", "coating"], (36.7, 128), (3.0, 7.0), (1.3, 10.4),  "fax_heavy"),
    "Hydraulic manifolds":      (0.09, ["HMC", "VMC", "HMC"],        ["SAW", "DBR", "INS"],        ["AL 6061 plate", "4140 steel bar", "AL 356 casting"], ["anodize", "plating"], (18.4, 73.4), (2.0, 5.0), (3.9, 31.2), None),
    "Fixtures and tooling":     (0.07, ["VMC", "HMC"],        ["SAW", "MDP", "DBR", "INS"], ["4140 steel bar", "1018 steel bar", "AL 6061 plate"], ["heat treat", "grind"], (14.7, 55.1),  (1.5, 4.0), (5.2, 46.8), "manual_heavy"),
    "Weldments and assemblies": (0.06, ["VMC", "LTH", "LTH"],        ["SAW", "DBR", "ASM", "INS"], ["1018 steel bar", "SS 304 bar", "SS 316 tube"],       ["plating", "coating"], (11, 45.9),  (1.5, 3.5), (2.6, 39), "manual_heavy"),
    "Precision EDM parts":      (0.05, ["EDM", "VMC"],        ["DBR", "INS"],               ["4140 forging", "SS 17-4PH bar", "Delrin rod"],        ["grind"], (27.5, 110), (2.0, 5.0), (0.26, 5.2),  None),
    "Standard components":      (0.05, ["LTH", "VMC", "LTH"],        ["SAW", "DBR", "INS"],        ["AL 6061-T6 bar", "SS 304 bar", "Brass 360 bar"],     ["anodize", "passivate"], (5.51, 22),  (1.0, 2.5), (0.52, 7.8),  None),
}
CNC_RUN_SCALE = 0.58              # scales CNC run minutes so the twenty-eight machines run near 80% of capacity
MANUAL_HEAVY_SECONDARY_SHARE = 0.45   # share of routed hours on secondary work centers for those families
DEFAULT_SECONDARY_SHARE = 0.18

# ── Outside processing ──────────────────────────────────────────────────────
# service -> (vendor count, share of jobs in eligible families with the service,
# $ per piece range at July 2023, annual drift). The plating vendor's 25% rise
# over two years is P6.
OUTSIDE_SERVICES = {
    "anodize":    (2, 0.55, (1.8, 10.8),  0.04),
    "chem film":  (1, 0.20, (1.2, 4.8),  0.04),
    "passivate":  (2, 0.50, (0.717, 3.6),  0.04),
    "heat treat": (2, 0.50, (2.4, 16.8),  0.05),
    "grind":      (1, 0.30, (4.8, 26.4),  0.04),
    "plating":    (1, 0.60, (3.6, 19.2),  0.118),   # P6 vendor
    "coating":    (1, 0.40, (6, 30),  0.05),
    "NDT":        (1, 0.35, (3.6, 12),  0.04),
}
OSP_PLATING_VENDOR_RISE_2Y = 0.25
OSP_GL_ACCOUNT = "5240-OUTSIDE"

# ── Jobs and lots ───────────────────────────────────────────────────────────
LOT_SIZE_MEDIAN = 48
FAMILY_LOT_FACTOR = {"Swiss turned components": 5.0, "Steel shafts and pins": 2.0}   # Swiss and shaft work runs in long lots
LOT_SIZE_SIGMA = 1.0              # lognormal spread of quoted lots; about a quarter of jobs under 25 pieces
RELEASE_LOT_NOISE = 0.35          # a blanket release varies this much (lognormal sd) around the quoted lot
# Machine age: the two oldest vertical mills run the same program slower. The floor
# schedule puts a VMC operation on whichever mill frees up first, not always the routed one.
OLDER_MACHINE_CYCLE = {"VMC-01": 1.24, "VMC-02": 1.20}
INSTALL_YEAR = {"VMC-01": 2006, "VMC-02": 2008}   # others are drawn from 2014-2024
# Revision changes inside the window: the first run after a revision carries program
# prove-out and first-article setup; later runs settle back.
REVISION_CHANGE_SHARE = 0.12
FIRST_RUN_AFTER_REVISION_SETUP = (1.8, 2.6)
FIRST_RUN_AFTER_REVISION_RUN = (1.05, 1.15)
SMALL_LOT_THRESHOLD = 25
SMALL_LOT_SETUP_MULT = (1.4, 1.8)
JOB_HOURS_NOISE = 0.10            # lot-to-lot variation in hours around the current cycle
CHANGE_ORDER_OP_SHARE = 0.85      # P3: share of the change-order customer's CNC operations that carry revision work
CHANGE_ORDER_SHARE_OF_OP = (0.30, 0.60)   # revision work adds this share of the operation's hours     # P2: actual setup versus estimate on mill-turn and 5-axis
SMALL_LOT_GROUPS = ["MTN", "FAX"]
JOB_LEAD_DAYS = (5, 21)           # release to due
OWN_PRODUCT_STOCK_ORDER_DAYS = 30

# ── Quoting and pricing ─────────────────────────────────────────────────────
NEW_WORK_WIN_RATE = 0.42
QUOTE_LINES_PER_WON_JOB = 1.0     # each won quote line becomes one job; lost and expired lines add to the volume
REPEAT_FIRST_QUOTE_YEARS_AGO = (0.6, 4.5)   # years before the end of the window that a standing price was set
P1_COHORT_YEARS_AGO = (4.0, 5.5)            # the erosion cohort: aluminum and stainless bar parts priced longest ago
P1_OTHER_YEARS_AGO = (0.6, 2.5)             # the other aluminum and stainless bar parts were repriced more recently
ANNUAL_INCREASE_LETTER = {2020: 0.030, 2021: 0.030, 2022: 0.035, 2023: 0.035, 2024: 0.030, 2025: 0.030, 2026: 0.032}   # M4: across-the-board increases that partly keep pace
ANNUAL_INCREASE_DATE = (2, 1)     # letters take effect February 1
P1_COHORT_SHARE = 0.40            # share of aluminum and stainless bar repeat parts in the erosion cohort
NEW_WORK_DISCOUNT = (0.04, 0.20)  # competitive discount off the quoted markup on new work
BLANKET_RENEWAL_TOP_SHARE = 0.30      # repeat parts in the top quarter by lot value are blanket programs
BLANKET_RENEWAL_SHARE = 0.85          # most of them were repriced at their last blanket renewal
BLANKET_RENEWAL_DAYS_BEFORE_START = (-540, 240)   # negative: renewed inside the window, up to December 2024
CELL_SENSE = 0.55                  # the estimator prices part of what an expensive cell costs over the blended rate (exponent on the ratio, upward only)
ESTIMATE_NOISE = 0.035            # estimator judgment around the spreadsheet result
QUANTITY_BREAKS = (0.5, 1.0, 2.0, 4.0)   # a quote line is priced at these multiples of the quoted lot
BREAK_MARKUP_STEP = 0.02                 # markup falls this much per doubling of the break quantity
ORDER_QTY_NOISE = 0.15                   # the ordered quantity sits near the quoted lot, rarely on a break
# quote lines where the estimator overrode the ERP's material price, vendor price and
# standards with the spreadsheet's figures (stale list prices, the old plating rate,
# judgment on the hours), by estimator; the rest were priced on the ERP's figures
SPREADSHEET_OVERRIDE_SHARE = {"EST-01": 0.55, "EST-02": 0.30, "EST-03": 0.25}
SPREADSHEET_HOURS_NOISE = 0.06
# T10: labor posting was never turned on at these secondary cells, so no clock record
# exists for any operation through them until the terminals moved and scanning began
T10_NO_POSTING_WCS = ["DBR-03", "INS-02", "MDP-01"]
OWN_PRODUCT_LAUNCH_YEARS = (2021, 2022)   # M8: standard cost set at launch, never revised
OWN_PRODUCT_EARLY_LAUNCHES = 3            # the first three products date from 2019 and sit on aluminum and stainless bar
OWN_PRODUCT_LIST_MARKUP = 1.26
OWN_PRODUCTS_BELOW_COST = 3
MATERIAL_PRICE_LIST_LAG_MONTHS = (6, 18)    # M5: the estimator's price list lags actual on 40% of specs
MATERIAL_PRICE_LIST_STALE_SHARE = 0.40

# ── Routing standards (M2) ──────────────────────────────────────────────────
STALE_STANDARD_SHARE = 0.62       # share of repeat parts whose standards are >15% off the current cycle
STALE_STANDARD_DRIFT = (0.16, 0.35)   # size of the gap where the cycle is now faster
STALE_SLOWER_DRIFT = (0.16, 0.19)     # smaller where the cycle is now slower: the estimator noticed the worst
STALE_FASTER_SHARE = 0.70             # share of stale standards where the cycle is now faster than the standard (machines replaced, programs optimized)
STANDARD_NOISE = 0.03             # standards that are not stale still sit within +/-5% of the cycle

# ── Transaction volumes and shapes ─────────────────────────────────────────
CLOCK_RECORD_HOURS = 1.65         # mean length of a clock record: breaks and lunch split the time at the door terminals
MACHINE_INTERVAL_MINUTES = (2, 9)   # length of an in-cycle interval before the state changes
IDLE_SHARE_MONITORED = 0.22       # idle share of machine time between jobs
IN_OP_IDLE_P = 0.38               # chance an in-cycle interval is followed by a short idle (tool change, inspection, loading)
IN_OP_IDLE_MINUTES = (2, 12)
ALARM_SHARE = 0.03
MATERIAL_ISSUES_PER_JOB = (3, 6)
SCRAP_EVENT_RATE = 0.28           # jobs with at least one scrap or rework event
REWORK_HOURS_PER_EVENT = (0.5, 4.0)
SCRAP_REASON_CODES = ["DIM", "FIN", "TOOL", "PROG", "MATL", "SETUP", "HAND"]

# ── Planted defects (transaction level) ─────────────────────────────────────
T1_OPEN_CLOCK_SHARE = 0.035       # base share of clock records left open on attended cells; lights-out cells run several times higher
T1_LIGHTS_OUT_MULT = 7.0
T1_INFLATION_HOURS = {"break": (0.5, 1.5), "shift": (1.5, 3.5), "overnight": (9.0, 13.0)}   # hours added by the open record
T1_KIND_P = {"attended": (0.70, 0.25, 0.05), "lights_out": (0.10, 0.20, 0.70)}
T3_WRONG_JOB_SHARE = 0.026        # time charged to an adjacent job number
T4_MULTI_MACHINE_SHARE = 0.13     # CNC clock records that span two or three machines; Swiss and lights-out heavy
T4_WALL_MULT = (1.2, 1.5)
T5_INDIRECT_SHARE_HOURS = 0.055   # indirect time posted against open jobs
T6_REWORK_AS_RUN_SHARE = 0.68     # rework events posted as run time
T7_SCRAP_UNRECORDED_SHARE = 0.38  # scrap events that never reach the system
T7_SCRAP_NO_REASON_SHARE = 0.50   # recorded events with no reason code
T8_MATERIAL_WRONG_JOB_SHARE = 0.055   # bar pulled for two jobs charged to one; remnants never issued
M6_OSP_NO_JOB_SHARE = 0.78        # PO lines coded to GL with no job number before restructuring
M7_GENERIC_PROGRAM_SHARE = 0.10   # programs named generically or reused across parts
T9_MISSING_SCAN = {2: 0.27, 12: 0.08}  # secondary operations with no traveler scan, week 2 and week 12

# ── The engagement's review decisions ───────────────────────────────────────
LABOR_REPAIRED_SHARE = 0.73       # historic labor records repaired; the rest flagged unrepairable
STANDARD_MEASURED_SHARE = 0.78    # repeat parts with machine-measured standards by week 8
MEASURED_CYCLE_NOISE = 0.10       # measurement over three lots against the underlying cycle
ESTIMATOR_DISPUTE_SHARE = 0.05    # measured values the estimator disputes and wins
# The repricing policy the owner and controller apply in the week 7-9 review.
REPRICING_POLICY = {
    "routine_increase": 0.05,        # up to the size of an annual letter: taken
    "documented_increase": 0.12,     # up to this, taken when the driver is a documented pass-through
    "pass_through_share": 0.40,      # material and outside processing share of what moved
    "small_part_quantile": 0.65,     # a large gap on a part below the median revenue is exited
    "big_program_quantile": 0.90,    # a large gap on a large program is taken in two steps
}
OSP_ATTRIBUTED_SHARE = 0.86       # historic PO lines re-tied to a job; residual stays in GL
ESTIMATE_BACKFILL_SHARE = 0.94    # historic jobs matched to their quote line
POST_CONFIG_PO_JOB_SHARE = 1.0    # the job number is a required field on new POs
COVERAGE_PLATEAU = 0.89           # measured cost share on new jobs, weeks 8-12

# ── Source system -> output subdirectory ────────────────────────────────────
TABLE_SYSTEM_MAP = {
    "quotes": "erp", "part_master": "erp", "routings": "erp", "work_centers": "erp",
    "work_center_rates": "erp", "jobs": "erp", "labor_transactions": "erp",
    "material_transactions": "erp", "outside_processing": "erp", "scrap_rework": "erp",
    "customers": "erp",
    "machine_monitoring": "monitoring", "programs": "monitoring",
}


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def year_fraction(d):
    return (d - START_DATE).days / 365.25
