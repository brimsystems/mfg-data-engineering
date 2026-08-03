"""How a job's cost builds, in the shop's own terms.

Estimate = material + setup hours x rate + run hours x rate + outside processing,
at the work-center rates in effect at the quote date. Actual = material issued at
actual cost + labor hours x rate + outside processing invoiced + scrap material +
rework hours. Overhead applies through the burden rate.

Two rate views are kept: the blended shop rate the ERP applies to every work
center (M3), and the work-center cost pools the engagement builds (labor rate x
attended ratio + burden rate, drifting a few percent a year).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .. import config as C

# The blended rate before the window, for standing prices set years ago.
_BLENDED_HISTORY = {2019: 143.0, 2020: 148.0, 2021: 153.0, 2022: 158.0, **C.BLENDED_RATE}


def blended_rate(d):
    return _BLENDED_HISTORY[min(max(d.year, 2019), 2026)]


class CostModel:
    """Lookups over the master tables for costing a part at a date."""

    def __init__(self, parts, routings, wcs, mat_prices, vendors, vendor_prices):
        self.parts = parts.set_index("part_number")
        self.routing_by_part = {pn: g for pn, g in routings.groupby("part_number")}
        self.wc = wcs.set_index("work_center_id")
        mp = mat_prices.copy(); mp["month"] = pd.to_datetime(mp["month"]).dt.to_period("M")
        self.mat_actual = mp.set_index(["material_spec", "month"])["actual_price_per_lb"].to_dict()
        self.mat_list = mp.set_index(["material_spec", "month"])["list_price_per_lb"].to_dict()
        self.mat_months = (mp["month"].min(), mp["month"].max())
        vp = vendor_prices.copy(); vp["month"] = pd.to_datetime(vp["month"]).dt.to_period("M")
        self.vendor_index = vp.set_index(["vendor_id", "month"])["price_index"].to_dict()
        self.vendors = vendors.set_index("vendor_id")
        # one primary vendor per service; the base price per piece is set per part
        self.vendor_for_service = {}
        for v, r in self.vendors.iterrows():
            self.vendor_for_service.setdefault(r["service_type"], []).append(v)

    # ── prices ──────────────────────────────────────────────────────────────
    def _clip_month(self, d):
        m = pd.Period(d, freq="M")
        return min(max(m, self.mat_months[0]), self.mat_months[1])

    def material_price(self, spec, d, which="actual"):
        m = self._clip_month(d)
        table = self.mat_actual if which == "actual" else self.mat_list
        return table[(spec, m)]

    def pool_rate(self, wc, d):
        r = self.wc.loc[wc]
        years = (d - C.START_DATE).days / 365.25
        drift = (1 + C.POOL_RATE_DRIFT) ** years
        return (r["true_labor_rate"] * r["attended_ratio"] + r["true_burden_rate"]) * drift

    def vendor_price(self, vendor_id, base_per_piece, d, which="actual"):
        """Per-piece price from a vendor at a date. The estimator's sheet carries the
        plating vendor's price as it stood in mid-2023 (P6); other services it
        refreshes about once a year."""
        m = self._clip_month(d)
        if which == "actual":
            return base_per_piece * self.vendor_index[(vendor_id, m)]
        if self.vendors.loc[vendor_id, "p6_vendor"] and d >= date(2023, 7, 1):
            m = self._clip_month(date(2023, 7, 1))
        else:
            m = self._clip_month(date(d.year - 1, 12, 1))
        return base_per_piece * self.vendor_index[(vendor_id, m)]

    # ── the estimate for a part and quantity at a quote date ────────────────
    def estimate(self, pn, qty, d, standards="erp", rates="blended", material="list", osp_base=None):
        """Cost elements the way the estimator builds them. `standards` picks the
        ERP standards or the true current cycle; `rates` the blended rate or the
        pools; `material` the price list or the actual price."""
        p = self.parts.loc[pn]
        r = self.routing_by_part[pn]
        setup_col = "std_setup_hours" if standards == "erp" else "true_setup_hours"
        run_col = "std_run_min_per_piece" if standards == "erp" else "true_run_min_per_piece"
        setup_h = float(r[setup_col].sum())
        run_h = float(qty * r[run_col].sum() / 60)
        if rates == "blended":
            labor = (setup_h + run_h) * blended_rate(d)
        else:
            labor = float(sum((r[setup_col] + qty * r[run_col] / 60) * [self.pool_rate(w, d) for w in r["work_center_id"]]))
        mat = qty * p["weight_lb"] * 1.08 * self.material_price(p["material_spec"], d, material)
        osp = 0.0
        for svc, vend, base in (osp_base or []):
            osp += qty * self.vendor_price(vend, base, d, "actual" if material == "actual" else "estimator")
        return {"est_material": mat, "est_setup_hours": setup_h, "est_run_hours": run_h,
                "est_labor": labor, "est_outside": osp, "est_total_cost": mat + labor + osp}
