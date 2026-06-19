"""
Record faults as each system carries them: the formats different entry points
use for the same identifier, free-text variants of coded fields, and timestamps
entered after the fact. Each function takes the canonical value and a random
generator and returns the value as it would be keyed in.
"""
from datetime import timedelta

# Part number formats by entry point: the ERP uses P-1234, the shop floor
# tablet drops the hyphen, older travelers spell out PART.
_PART_FORMATS = [
    lambda p: p,                              # P-1234
    lambda p: p.replace("-", ""),             # P1234
    lambda p: p.lower(),                      # p-1234
    lambda p: "PART-" + p.split("-")[1],      # PART-1234
    lambda p: p.replace("-", " "),            # P 1234
]
_PART_WEIGHTS = [0.55, 0.20, 0.10, 0.10, 0.05]

# Defect codes: the QMS has a dropdown, but inspectors also type the code.
DEFECT_VARIANTS = {
    "Dimensional":           ["Dimensional", "DIMENSIONAL", "Dim", "dimensional",
                              "dim.", "Dimentional", "Dimension Error"],
    "Surface Scratch":       ["Surface Scratch", "Scratch", "SCRATCH", "surface scratch",
                              "scrach", "Scr", "surface scr"],
    "Burr":                  ["Burr", "BURR", "burr", "Bur",
                              "Sharp Edge", "sharp edge", "Sharp Burr"],
    "Weld Defect":           ["Weld Defect", "WELD", "weld defect", "Weld",
                              "weld def.", "Welding Issue", "Weld Reject"],
    "Incorrect Material":    ["Incorrect Material", "Wrong Material", "Mat Error",
                              "incorrect material", "MATERIAL", "Wrong Mat"],
    "Bend Angle":            ["Bend Angle", "BEND", "bend angle", "Angle Error",
                              "angle err", "Bend", "Out of Angle"],
    "Porosity":              ["Porosity", "POROSITY", "porosity", "Poros.",
                              "Void", "void", "Gas Pocket"],
    "Surface Contamination": ["Surface Contamination", "CONTAMINATION", "surface contamination",
                              "Rust", "rust under finish", "Oil", "Contam."],
    "None":                  ["None", "NONE", "none", "No Defect",
                              "OK", "Pass", "", "PASS"],
}

# Scrap reasons: structured codes from QA, free text from operators.
SCRAP_REASON_VARIANTS = {
    "OPERATOR_ERROR":  ["OPERATOR_ERROR", "Operator Error", "Op Error",
                        "operator error", "op err", "human error", "Operator"],
    "MATERIAL_DEFECT": ["MATERIAL_DEFECT", "Material Defect", "Mat Defect",
                        "material defect", "bad material", "Incoming Defect"],
    "MACHINE_ISSUE":   ["MACHINE_ISSUE", "Machine Issue", "Mach Issue",
                        "machine issue", "equipment failure", "Machine"],
    "SETUP_ERROR":     ["SETUP_ERROR", "Setup Error", "set up error",
                        "setup err", "Setup", "First Article Fail"],
    "DESIGN_ISSUE":    ["DESIGN_ISSUE", "Design Issue", "print error",
                        "design issue", "drawing error", "Print Rev Error"],
    "UNKNOWN":         ["UNKNOWN", "Unknown", "unknown", "N/A",
                        "TBD", "", "Not Recorded", "See Notes"],
}

# Lot id formats other than the receiving system's LOT-1234: the floor drops or
# shortens the prefix.
_LOT_FORMATS = [
    lambda l: l.replace("-", ""),             # LOT1234
    lambda l: l.split("-")[1],                # 1234
    lambda l: l.replace("LOT-", "L-"),        # L-1234
]
_LOT_WEIGHTS = [0.50, 0.375, 0.125]


def _pick(rng, options, weights=None):
    return options[int(rng.choice(len(options), p=weights))]


def part_as_entered(rng, part: str) -> str:
    return _pick(rng, _PART_FORMATS, _PART_WEIGHTS)(part)


def defect_as_entered(rng, code: str) -> str:
    return _pick(rng, DEFECT_VARIANTS.get(code, [code]))


def scrap_reason_as_entered(rng, code: str) -> str:
    return _pick(rng, SCRAP_REASON_VARIANTS.get(code, [code]))


def lot_as_entered(rng, lot_id: str) -> str:
    return _pick(rng, _LOT_FORMATS, _LOT_WEIGHTS)(lot_id)


def timestamp_entered_late(rng, ts, max_minutes: int = 600):
    """An inspection time filled in from memory, hours away from the event."""
    shift = int(rng.integers(180, max_minutes)) * (1 if rng.random() < 0.5 else -1)
    return ts + timedelta(minutes=shift)
