"""Master data for the shop: customers, work centers and their rate history, the
material price history, outside-processing vendors, the part master, routings
and the CNC program list.

Everything downstream keys off these tables. Two versions of several numbers
are produced here: what the ERP carries (the routing standards, the blended
rate, the estimator's price list) and what is true on the floor today (the
current cycle time, the work-center cost pools, the actual material price). The
gap between them is the case.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from .. import config as C

INDUSTRIES = ["Aerospace", "Industrial equipment", "Medical devices", "Fluid power", "Defense",
              "Energy", "Automation", "Food equipment", "Instrumentation", "Transportation"]


def customers(rng):
    """Customers with a concentrated revenue mix: the top account carries about a
    fifth of revenue, the second is the change-order customer (P3)."""
    fake = Faker(); Faker.seed(C.RANDOM_SEED)
    n = C.N_CUSTOMERS
    # revenue weights: two named heads, then a geometric tail scaled so the top ten reach ~65%
    tail = C.CUSTOMER_TAIL_DECAY ** np.arange(n - 2)
    tail = tail / tail.sum() * (1 - C.TOP_CUSTOMER_SHARE - C.SECOND_CUSTOMER_SHARE)
    weights = np.concatenate([[C.TOP_CUSTOMER_SHARE, C.SECOND_CUSTOMER_SHARE], tail])
    rows = []
    for i in range(n):
        name = fake.company()
        industry = str(rng.choice(INDUSTRIES, p=[0.20, 0.16, 0.12, 0.12, 0.10, 0.08, 0.08, 0.05, 0.05, 0.04]))
        if i == 0:
            industry = C.TOP_CUSTOMER_INDUSTRY
        if i + 1 == C.CHANGE_ORDER_CUSTOMER_RANK:
            industry = C.CHANGE_ORDER_CUSTOMER_INDUSTRY
        rows.append({
            "customer_id": f"CUST-{i + 1:03d}",
            "name": name,
            "industry": industry,
            "terms": rng.choice(["Net 30", "Net 45", "Net 60", "2/10 Net 30"], p=[0.45, 0.30, 0.15, 0.10]),
            "revenue_weight": float(weights[i]),
            "change_order_customer": i + 1 == C.CHANGE_ORDER_CUSTOMER_RANK,
        })
    df = pd.DataFrame(rows)
    # counts in the last twelve months, written by the ERP's customer service screen
    base_co = rng.poisson(2.0, n); base_ex = rng.poisson(3.0, n)
    df["change_order_count_12m"] = np.where(df["change_order_customer"], rng.integers(38, 52, n), base_co)
    df["expedite_count_12m"] = np.where(df["change_order_customer"], rng.integers(14, 22, n), base_ex)
    return df


def work_centers(rng):
    """The work-center table and its rate history. The ERP carries one blended rate
    for every work center (M3); the true cost pools are kept alongside for the
    engagement to discover."""
    rows, rates = [], []
    for prefix, (count, wtype, monitored, lights_out, labor, burden, attended) in C.WORK_CENTER_GROUPS.items():
        for i in range(1, count + 1):
            wc = f"{prefix}-{i:02d}"
            # the newest machines in a group run a little faster and cost a little more
            age_factor = 1.0 + 0.04 * (i - (count + 1) / 2) / max(count - 1, 1)
            rows.append({"work_center_id": wc, "type": wtype, "group": prefix, "monitored_flag": monitored,
                         "lights_out_share": lights_out, "true_labor_rate": round(labor * age_factor, 2),
                         "true_burden_rate": round(burden * age_factor, 2), "attended_ratio": attended,
                         "machine_id": wc if monitored else None})
            for eff in C.RATE_EFFECTIVE_DATES:
                blended = C.BLENDED_RATE[eff.year]
                rates.append({"work_center_id": wc, "effective_date": eff,
                              # the ERP splits the blended rate into a nominal labor and burden pair
                              "labor_rate": round(blended * 0.36, 2), "burden_rate": round(blended * 0.64, 2),
                              "attended_ratio": 1.0})
    return pd.DataFrame(rows), pd.DataFrame(rates)


def material_prices(rng):
    """Monthly actual price per material spec, and the estimator's price list, which
    lags actual by six to eighteen months on 40% of specs (M5). Prices start
    eighteen months before the window so quotes and standing prices set earlier
    can be reconstructed."""
    months = pd.period_range(C.PRICE_HISTORY_START, C.END_DATE, freq="M")
    rows, stale = [], {}
    specs = list(C.MATERIALS)
    stale_specs = set(rng.choice(specs, size=int(round(C.MATERIAL_PRICE_LIST_STALE_SHARE * len(specs))), replace=False))
    for spec, (form, p0, drift, p1) in C.MATERIALS.items():
        lag = int(rng.integers(*C.MATERIAL_PRICE_LIST_LAG_MONTHS)) if spec in stale_specs else 0
        stale[spec] = lag
        noise = rng.normal(0, 0.012, len(months)).cumsum()
        for i, m in enumerate(months):
            years = (m.to_timestamp().date() - date(2023, 7, 1)).days / 365.25
            actual = p0 * (1 + drift) ** years * (1 + noise[i] * 0.5)
            rows.append({"material_spec": spec, "stock_form": form, "month": m.to_timestamp().date(),
                         "actual_price_per_lb": round(actual, 3)})
    df = pd.DataFrame(rows)
    # the estimator's list: the actual price as of `lag` months earlier
    df = df.sort_values(["material_spec", "month"])
    df["list_price_per_lb"] = df.groupby("material_spec")["actual_price_per_lb"].transform(
        lambda s: s.shift(stale[s.name]).bfill())
    df["list_lag_months"] = df["material_spec"].map(stale)
    return df


def vendors(rng):
    """Outside-processing vendors and their per-piece price history. One plating
    vendor raises prices 25% over two years while the estimator's sheet keeps the
    old rate (P6)."""
    fake = Faker(); Faker.seed(C.RANDOM_SEED + 1)
    rows, prices = [], []
    months = pd.period_range(C.PRICE_HISTORY_START, C.END_DATE, freq="M")
    vid = 0
    for service, (n_vendors, share, (lo, hi), drift) in C.OUTSIDE_SERVICES.items():
        for k in range(n_vendors):
            vid += 1
            v = f"VEND-{vid:03d}"
            name = fake.company().split(",")[0]
            suffix = {"anodize": "Anodizing", "chem film": "Finishing", "passivate": "Finishing",
                      "heat treat": "Heat Treating", "grind": "Grinding", "plating": "Plating",
                      "coating": "Coatings", "NDT": "Testing"}[service]
            rows.append({"vendor_id": v, "name": f"{name} {suffix}", "service_type": service,
                         "p6_vendor": service == "plating"})
            base = float(rng.uniform(lo, hi))
            for m in months:
                years = (m.to_timestamp().date() - date(2023, 7, 1)).days / 365.25
                if service == "plating":
                    # a step rise through 2024 and 2025 that lands 25% above the 2023 price
                    rise = min(max(years, 0) / 2.0, 1.0) * C.OSP_PLATING_VENDOR_RISE_2Y
                    price = base * (1 + rise)
                else:
                    price = base * (1 + drift) ** years
                prices.append({"vendor_id": v, "month": m.to_timestamp().date(), "price_index": round(price / base, 4)})
    return pd.DataFrame(rows), pd.DataFrame(prices)


def _routing_ops(rng, family, fam):
    """Operation sequence for a part in a family: saw first where bar stock is cut,
    then the CNC operations, then deburr and inspection, with assembly for the
    weldment family."""
    share, primary, secondary, mats, services, run_rng, setup_rng, wt_rng, role = fam
    ops = []
    if "SAW" in secondary:
        ops.append("SAW")
    n_cnc = int(rng.integers(1, 4)) if role != "manual_heavy" else int(rng.integers(1, 3))
    for _ in range(n_cnc):
        ops.append(str(rng.choice(primary)))
    if "MDP" in secondary and rng.random() < 0.7:
        ops.append("MDP")
    if "DBR" in secondary:
        ops.append("DBR")
    if "ASM" in secondary and rng.random() < 0.8:
        ops.append("ASM")
    if "INS" in secondary:
        ops.append("INS")
    return ops


def parts_and_routings(rng, cust, wcs):
    """The part master, routings (with the ERP's standards and the true current
    cycle), the program list (with generic names, M7) and own-product standards."""
    fam_names = list(C.PART_FAMILIES)
    fam_share = np.array([C.PART_FAMILIES[f][0] for f in fam_names]); fam_share /= fam_share.sum()
    wc_by_group = wcs.groupby("group")["work_center_id"].apply(list).to_dict()
    cust_w = cust["revenue_weight"].to_numpy(); cust_ids = cust["customer_id"].to_numpy()
    co_cust = cust.loc[cust["change_order_customer"], "customer_id"].iloc[0]

    n_repeat, n_new, n_own = C.N_PARTS_REPEAT, C.N_PARTS_NEW, C.N_OWN_PRODUCTS
    parts, routings, programs, own_std = [], [], [], []
    prog_counter = 0
    generic_names = ["O1000", "O1001", "O9999", "PROG1", "TEST", "MAIN", "O0001", "PART", "NEW", "TEMP"]

    def new_program(part_number, wc, rev):
        nonlocal prog_counter
        prog_counter += 1
        if rng.random() < C.M7_GENERIC_PROGRAM_SHARE:
            name = str(rng.choice(generic_names)); generic = True
        else:
            name = f"O{4000 + prog_counter:05d}"; generic = False
        programs.append({"program_number": name, "part_number": part_number, "revision": rev,
                         "work_center_id": wc, "generic_flag": generic})
        return name

    for kind, n in [("repeat", n_repeat), ("new", n_new), ("own_product", n_own)]:
        for i in range(n):
            if kind == "own_product":
                family = "Standard components"
                early = i < C.OWN_PRODUCT_EARLY_LAUNCHES
            else:
                family = str(rng.choice(fam_names, p=fam_share))
                if family == "Standard components" and kind == "repeat":
                    family = str(rng.choice(fam_names[:-1]))
            fam = C.PART_FAMILIES[family]
            share, primary, secondary, mats, services, run_rng, setup_rng, wt_rng, role = fam
            spec = str(rng.choice(mats))
            if kind == "own_product":
                spec = str(rng.choice(["AL 6061-T6 bar", "SS 304 bar"])) if early else "Brass 360 bar"
            form = C.MATERIALS[spec][0]
            weight = float(np.exp(rng.uniform(np.log(wt_rng[0]), np.log(wt_rng[1]))))
            pn = {"repeat": f"P-{10000 + i}", "new": f"N-{30000 + i}", "own_product": f"BC-{100 + i}"}[kind]
            rev = str(rng.choice(["A", "B", "C", "D"], p=[0.45, 0.30, 0.17, 0.08]))
            customer = None if kind == "own_product" else str(rng.choice(cust_ids, p=cust_w))
            # when the part was first quoted: repeat parts before the window, new parts inside it
            if kind == "repeat":
                p1_material = C.MATERIALS[spec][3]
                p1_cohort = p1_material and rng.random() < C.P1_COHORT_SHARE
                years_ago = float(rng.uniform(*(C.P1_COHORT_YEARS_AGO if p1_cohort else
                                                C.P1_OTHER_YEARS_AGO if p1_material else C.REPEAT_FIRST_QUOTE_YEARS_AGO)))
                first_quote = C.END_DATE - timedelta(days=int(years_ago * 365.25))
            elif kind == "new":
                first_quote = C.START_DATE + timedelta(days=int(rng.uniform(-365, (C.END_DATE - C.START_DATE).days - 30)))
                p1_cohort = False
            else:
                first_quote = date(2019 if early else int(rng.integers(C.OWN_PRODUCT_LAUNCH_YEARS[0], C.OWN_PRODUCT_LAUNCH_YEARS[1] + 1)),
                                   int(rng.integers(1, 13)), 1)
                p1_cohort = False
            ops = _routing_ops(rng, family, fam)
            # true current cycle per CNC op and the standard the ERP carries
            stale = kind == "repeat" and rng.random() < C.STALE_STANDARD_SHARE
            stale_sign = float(rng.choice([-1, 1], p=[C.STALE_FASTER_SHARE, 1 - C.STALE_FASTER_SHARE]))
            stale_size = float(rng.uniform(*C.STALE_STANDARD_DRIFT))
            total_run_true = float(np.exp(rng.uniform(np.log(run_rng[0]), np.log(run_rng[1]))))
            total_setup_true = float(rng.uniform(*setup_rng))
            cnc_ops = [o for o in ops if o not in C.SECONDARY_GROUPS]
            sec_share = C.MANUAL_HEAVY_SECONDARY_SHARE if role == "manual_heavy" else C.DEFAULT_SECONDARY_SHARE
            for seq, grp in enumerate(ops, start=1):
                wc = str(rng.choice(wc_by_group[grp]))
                is_cnc = grp not in C.SECONDARY_GROUPS
                if is_cnc:
                    w = 1.0 / len(cnc_ops)
                    run_true = total_run_true * (1 - sec_share) * w * float(rng.uniform(0.7, 1.3)) * C.CNC_RUN_SCALE
                    setup_true = total_setup_true * w * float(rng.uniform(0.7, 1.3))
                else:
                    n_sec = len(ops) - len(cnc_ops)
                    run_true = total_run_true * sec_share / n_sec * float(rng.uniform(0.6, 1.4))
                    setup_true = {"SAW": 0.25, "MDP": 0.5, "DBR": 0.2, "ASM": 0.6, "INS": 0.4}[grp] * float(rng.uniform(0.7, 1.3))
                if stale and is_cnc:
                    gap = stale_size * stale_sign * float(rng.uniform(0.85, 1.15))
                else:
                    gap = float(rng.normal(0, C.STANDARD_NOISE))
                std_run = run_true / (1 + gap)
                std_setup = setup_true / (1 + float(rng.normal(0, C.STANDARD_NOISE)))
                program = new_program(pn, wc, rev) if is_cnc else None
                routings.append({"part_number": pn, "revision": rev, "op_seq": seq * 10, "work_center_id": wc,
                                 "work_center_group": grp,
                                 "std_setup_hours": round(std_setup, 2), "std_run_min_per_piece": round(std_run, 3),
                                 "program_number": program, "last_updated": first_quote,
                                 "true_setup_hours": round(setup_true, 3), "true_run_min_per_piece": round(run_true, 4),
                                 "standard_stale": stale and is_cnc, "standard_gap": round(gap, 4)})
            n_services = 1 if rng.random() < 0.72 else (2 if rng.random() < 0.5 else 0)
            svc = list(rng.choice(services, size=min(n_services, len(services)), replace=False)) if n_services else []
            parts.append({"part_number": pn, "revision": rev, "description": f"{family[:-1] if family.endswith('s') else family} {pn[-4:]}",
                          "material_spec": spec, "stock_form": form, "part_family": family, "customer_id": customer,
                          "status": "active", "first_quote_date": first_quote, "own_product_flag": kind == "own_product",
                          "job_type": kind, "weight_lb": round(weight, 3), "outside_services": "|".join(svc),
                          "p1_cohort": p1_cohort, "change_order_customer": customer == co_cust,
                          "estimator_bias_material": spec in C.ESTIMATOR_BIAS_MATERIALS})
    parts = pd.DataFrame(parts); routings = pd.DataFrame(routings); programs = pd.DataFrame(programs)
    return parts, routings, programs
