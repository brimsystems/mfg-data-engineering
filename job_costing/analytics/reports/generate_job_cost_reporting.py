"""The reporting layer's standing job cost views, as ERP screens in the style of the
three embedded screens (job in progress, close-out, repricing queue):

  docs/erp/job_cost_dashboard.html    Job Cost dashboard: one screen, no scrolling, opened at
                                      the monthly close and the quarterly pricing review
  docs/erp/job_variance_report.html   Job Variance report: one parameterized, paginated report
                                      whose Group by parameter produces every detail view

Everything is read from the dbt marts (mart_job_variance, mart_job_driver,
mart_job_variance_by_work_center, mart_job_variance_monthly). Everything shown is
measured for the period selected: no projections, annualized figures or totals of
opportunity. The screens represent the reporting layer's configuration, not a specific
vendor's widget set.

Run:  python -m analytics.reports.generate_job_cost_reporting
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_erp_screens as E  # noqa: E402  (the shared ERP chrome, styles and formatting)

REPO = E.REPO
MARTS = E.MARTS
DOCS = E.DOCS
C = E.C
END = pd.Timestamp(C.END_DATE)

# the ERP's default chart series
S1, S2, S3, S4, S5, S6, S7 = "#2E6DB4", "#F2A541", "#6BAA75", "#D1495B", "#8E7DBE", "#4FB0C6", "#9AA5B1"
GREYBAR = "#AEB8C4"
ELEMENTS = [("setup", "Setup"), ("run", "Run"), ("material", "Material"), ("outside", "OSP"), ("scrap_rework", "Scrap and rework")]
BANDS = [("Negative", -9, 0), ("0-10%", 0, 0.10), ("10-20%", 0.10, 0.20), ("20-22%", 0.20, 0.22), ("22-30%", 0.22, 0.30), ("Over 30%", 0.30, 9)]
TYPE = {"repeat": "Repeat", "new": "New", "own_product": "Own product"}


def est_id(x):
    return f"E{int(str(x)[-2:])}" if isinstance(x, str) and x.startswith("EST-") else "n/a"


def _floats(df):
    """Decimal columns (a literal zero in SQL) as floats."""
    from decimal import Decimal
    for c in df.columns:
        if df[c].dtype == object:
            first = df[c].dropna()
            if len(first) and isinstance(first.iloc[0], Decimal):
                df[c] = df[c].astype(float)
    return df


def load():
    v = _floats(E._pq("mart_job_variance"))
    d = E._pq("mart_job_driver")[["job_id", "driver", "driver_variance", "second_driver", "second_variance", "action", "action_status"]]
    v = v.merge(d, on="job_id", how="left")
    v["completed_date"] = pd.to_datetime(v["completed_date"])
    v["cust"] = v["customer_name"].where(v["customer_id"].notna(), "Stock")
    mo = _floats(E._pq("mart_job_variance_monthly"))
    mo["completion_month"] = pd.to_datetime(mo["completion_month"])
    wc = _floats(E._pq("mart_job_variance_by_work_center"))
    wc["completed_date"] = pd.to_datetime(wc["completed_date"])
    closeout_job = None
    try:
        import re
        html = (DOCS / "erp" / "job_closeout.html").read_text(encoding="utf-8")
        m = re.search(r"<h1>Job Cost: (J-\d+)", html)
        closeout_job = m.group(1) if m else None
    except FileNotFoundError:
        pass
    return v, mo, wc, closeout_job


# ── periods ─────────────────────────────────────────────────────────────────
def periods():
    m0 = END.to_period("M")
    q0 = END.to_period("Q")
    return {
        "month": ("Month", m0.strftime("%B %Y"), (m0.start_time, m0.end_time), ((m0 - 1).start_time, (m0 - 1).end_time), (m0 - 1).strftime("%b %Y")),
        "quarter": ("Quarter", f"Q{q0.quarter} {q0.year}", (q0.start_time, q0.end_time), ((q0 - 1).start_time, (q0 - 1).end_time), f"Q{(q0 - 1).quarter} {(q0 - 1).year}"),
        "ttm": ("Trailing 12 months", f"{(m0 - 11).strftime('%b %Y')} to {m0.strftime('%b %Y')}", ((m0 - 11).start_time, m0.end_time),
                ((m0 - 23).start_time, (m0 - 12).end_time), f"{(m0 - 23).strftime('%b %Y')} to {(m0 - 12).strftime('%b %Y')}"),
    }


def in_period(v, rng):
    return v[(v["completed_date"] >= rng[0]) & (v["completed_date"] <= rng[1])]


def tiles(x):
    below = x[x["below_estimate"]]
    return {"margin": x["contribution"].sum() / x["price"].sum(), "below": x["below_estimate"].mean(), "losing": x["losing"].mean(),
            "shortfall": below["shortfall"].sum(), "short_ms": below["measured_cost"].sum() / below["act_total"].sum(),
            "ratio": x["ratio_total"].median(), "measured": x["measured_cost"].sum() / x["act_total"].sum(), "jobs": len(x)}


def arrow(cur, pri, pts=True, d=1):
    # the change between the values as displayed
    k = 100 if pts else 1
    diff = round(cur * k, d) - round(pri * k, d)
    sym = "&#9650;" if diff > 0 else "&#9660;" if diff < 0 else "&#9679;"
    return f'{sym} {abs(diff):.{d}f}{" pts" if pts else ""}'


def tone(cur, pri, up_good, k=100, d=1):
    """A tile figure in the job cost screen's green where it moved the right way against the prior
    period and red where it moved the wrong way, on the values as displayed; unchanged is left plain."""
    diff = round(cur * k, d) - round(pri * k, d)
    if diff == 0:
        return ""
    return f' style="color:{E.GREEN if (diff > 0) == up_good else E.RED};"'


# ── SVG charts: bars, paired bars, stacked bars ─────────────────────────────
def _scale(vmax, ticks=4):
    step = _nice(vmax / ticks)
    return step * ticks


def _axis(w, h, ml, mb, mt, ymax, fmt, ticks=4):
    out = []
    for i in range(ticks + 1):
        val = ymax * i / ticks
        y = h - mb - (h - mb - mt) * i / ticks
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{w - 6}" y2="{y:.1f}" stroke="#E3E7EC"/>'
                   f'<text x="{ml - 5}" y="{y + 3.5:.1f}" text-anchor="end" font-size="9.5" fill="#5F6B7A">{fmt(val)}</text>')
    return "".join(out)


def _nice(v):
    if v <= 0:
        return 1
    mag = 10 ** np.floor(np.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def svg_bands(cur, pri, labels, w=372, h=196):
    ml, mb, mt = 34, 30, 10
    ymax = _scale(max(max(cur), max(pri)) * 1.05)
    n = len(labels); slot = (w - ml - 10) / n; bw = slot * 0.34
    out = [_axis(w, h, ml, mb, mt, ymax, lambda x: f"{x:,.0f}")]
    for i, (c, p, lab) in enumerate(zip(cur, pri, labels)):
        x0 = ml + slot * i + slot * 0.14
        for k, (val, filled) in enumerate([(c, True), (p, False)]):
            bh = (h - mb - mt) * val / ymax; x = x0 + k * (bw + 3)
            style = f'fill="{S1}"' if filled else f'fill="#fff" stroke="{S1}" stroke-width="1.3"'
            out.append(f'<rect x="{x:.1f}" y="{h - mb - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" {style}/>')
        out.append(f'<text x="{ml + slot * i + slot / 2:.1f}" y="{h - mb + 13}" text-anchor="middle" font-size="9.5" fill="#1F2933">{lab}</text>')
    out.append(f'<text x="{ml}" y="{h - 3}" font-size="9.5" fill="#5F6B7A">Jobs by margin on price</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">{"".join(out)}</svg>'


def svg_paired(est, act, labels, w=372, h=196):
    ml, mb, mt = 44, 30, 16
    ymax = _scale(max(max(est), max(act)) * 1.1)
    n = len(labels); slot = (w - ml - 10) / n; bw = slot * 0.33
    out = [_axis(w, h, ml, mb, mt, ymax, lambda x: f"${x / 1e3:,.0f}K" if ymax < 2e6 else f"${x / 1e6:,.1f}M")]
    for i, (e, a, lab) in enumerate(zip(est, act, labels)):
        x0 = ml + slot * i + slot * 0.15
        for k, (val, col) in enumerate([(e, GREYBAR), (a, S1)]):
            bh = (h - mb - mt) * val / ymax
            out.append(f'<rect x="{x0 + k * (bw + 2):.1f}" y="{h - mb - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{col}"/>')
        top = h - mb - (h - mb - mt) * max(e, a) / ymax
        ratio = f"{a / e:.2f}" if e > 0 else "no est."
        out.append(f'<text x="{x0 + bw + 1:.1f}" y="{top - 4:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="#1F2933">{ratio}</text>')
        out.append(f'<text x="{ml + slot * i + slot / 2:.1f}" y="{h - mb + 13}" text-anchor="middle" font-size="9.5" fill="#1F2933">{lab}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">{"".join(out)}</svg>'


def svg_stacked(months, series, w=372, h=196):
    ml, mb, mt = 40, 30, 10
    tot = [sum(s[i] for _, _, s in series) for i in range(len(months))]
    ymax = _scale(max(tot) * 1.05)
    n = len(months); slot = (w - ml - 10) / n; bw = slot * 0.66
    out = [_axis(w, h, ml, mb, mt, ymax, lambda x: f"${x / 1e3:,.0f}K")]
    for i, mth in enumerate(months):
        y = h - mb; x = ml + slot * i + (slot - bw) / 2
        for _, col, s in series:
            bh = (h - mb - mt) * s[i] / ymax
            if bh > 0:
                out.append(f'<rect x="{x:.1f}" y="{y - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{col}"/>')
            y -= bh
        out.append(f'<text x="{x + bw / 2:.1f}" y="{h - mb + 12}" text-anchor="middle" font-size="8.5" fill="#1F2933">{mth.strftime("%b")}</text>')
        if i == 0 or mth.month == 1:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - mb + 22}" text-anchor="middle" font-size="8.5" fill="#5F6B7A">{mth.year}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">{"".join(out)}</svg>'


def legend(items):
    return '<div class="lg">' + "".join(f'<span><i style="{sty}"></i>{lab}</span>' for lab, sty in items) + "</div>"


# ── shared definitions block ─────────────────────────────────────────────────
def definitions(dashboard=False):
    rules = [
        ("Routing standard", "Run-hour ratio over 1.15 and the part's other jobs completed in the trailing 12 months ran over their run estimate too"),
        ("New or infrequent part setup", "Setup ratio over 1.30 on a part new to the shop or not run in the past 12 months"),
        ("Unbilled revision work", "Labor hours over estimate, a revision change after release, and no change-order line on the job"),
        ("Vendor rate", "Outside processing invoice more than 1.10 &times; estimate"),
        ("Scrap and rework", "Scrap plus rework cost more than 5% of estimated cost"),
        ("Material", "Material variance more than 10% of the material estimate"),
        ("Priced below estimated cost", "The job's own estimate showed a loss before it started; sized as that estimated loss, so it competes on dollars with any overrun"),
        ("Not attributable", "None of the above, or the largest firing rule carries under 40% of the job's overrun"),
    ]
    rows = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td></tr>" for a, b in rules)
    sums = ("<p><b>Actual &divide; estimate</b> here is dollars summed over the period's jobs; the margin diagnostic reports the median of job ratios.</p>\n"
            if dashboard else "")
    colors = ("<p><b>Tile colors.</b> A figure is green where it moved the right way against the prior period (margin and cost measured up; jobs below estimate, "
              "jobs losing, shortfall and actual &divide; estimate down), red where it moved the other way, and plain where it did not move.</p>" if dashboard else "")
    return f"""
<div id="defs" class="modal" onclick="if(event.target===this)this.style.display='none'"><div class="modal-in">
<div class="mh"><b>Definitions</b><span class="btn" onclick="document.getElementById('defs').style.display='none'">Close</span></div>
<p><b>Below estimate.</b> A job is below estimate when its margin on price came in under the margin its estimate carried, and losing when its margin is under zero.</p>
<p><b>Periods</b> run by completion date. Only completed jobs are shown; jobs in process are on the job in progress screen.</p>
{colors}
<p><b>Estimate and actual by element.</b> The estimate is the one on the job. Setup and run are hours at the job's work-center pool rate; material is the job's material estimate against the material issued; outside processing is the estimate against the invoice; scrap and rework are the scrapped material and the rework hours, which the estimate does not carry. <b>Measured</b> cost rests on a transaction (machine, scan, issue, purchase order); the rest is at the routing standard. CNC hours on monitored cells come from machine monitoring.</p>
<p><b>Shortfall decomposition.</b> A below-estimate job's shortfall, (estimated margin &minus; actual margin) &times; price, is its actual cost less its estimated cost. It is allocated to cost elements in proportion to each element's positive variance (actual minus estimate where actual exceeds estimate). Where none of them carries half of the overrun, the shortfall is not attributable.</p>
<p><b>Driver assignment.</b> Thresholds are parameters in the reporting layer. Where several rules fire, the driver is the one with the largest dollar variance and the next is the second driver.</p>
<table><thead><tr><th>Driver</th><th>Rule</th></tr></thead><tbody>{rows}</tbody></table>
<p><b>Ratios</b> are actual &divide; estimate; 1.00 is exact.</p>
{sums}<p><b>Outside processing</b> includes cost allocated from the ledger on jobs released before every PO carried a job number (May 2026); from then on the allocation is nil.</p>
<p><b>Material</b> is set against the estimate as carried, at the quote's prices.</p>
</div></div>"""


EXTRA_CSS = f"""
  .dash {{ padding:4px 16px 0; }}
  .dash .kpis {{ padding:4px 0 6px; flex-wrap:nowrap; }}
  .dash .kpi {{ padding:6px 12px; min-width:0; }}
  .dash .kpi .v {{ font-size:19px; }}
  .dash .kpi .p {{ font-size:11px; color:{E.MUTED}; margin-top:1px; }}
  .dash .grid3 {{ padding:0 0 8px; gap:12px; }}
  .dash .panel h2 {{ padding:5px 9px; font-size:11px; }}
  .dash .pbody {{ padding:4px 8px 2px; }}
  .lg {{ display:flex; flex-wrap:wrap; gap:4px 10px; font-size:10px; color:{E.MUTED}; padding:0 2px 4px; }}
  .lg i {{ display:inline-block; width:9px; height:9px; margin-right:4px; vertical-align:-1px; }}
  .tight td, .tight th {{ padding:3px 6px; font-size:11.5px; white-space:nowrap; }}
  .loss {{ background:{E.RED}; color:#fff; font-size:9.5px; font-weight:700; padding:0 4px; border-radius:2px; margin-left:4px; }}
  .lnk {{ color:#2458A6; cursor:pointer; }}
  .modal {{ display:none; position:fixed; inset:0; background:rgba(20,30,45,.35); z-index:10; }}
  .modal-in {{ background:#fff; width:760px; max-height:84vh; overflow:auto; margin:50px auto; padding:14px 18px; border-radius:3px; font-size:12.5px; line-height:1.5; }}
  .modal-in p {{ margin:6px 0; }} .modal-in table {{ margin:6px 0; }}
  .mh {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; font-size:14px; }}
  .params {{ display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; padding:8px 16px; border-bottom:1px solid {E.LINE}; background:#FAFBFC; }}
  .params label {{ color:{E.MUTED}; font-size:11.5px; }}
  .params select, .params input {{ border:1px solid #AEB8C4; padding:2px 5px; font:inherit; font-size:12px; background:#fff; }}
  .rep {{ padding:8px 16px 4px; overflow-x:auto; }}
  .rep table td, .rep table th {{ font-size:11.5px; padding:4px 6px; white-space:nowrap; }}
  .rep tr.child td {{ background:#F7F9FB; color:#33404D; }}
  .pager {{ display:flex; gap:6px; align-items:center; padding:6px 16px 10px; color:{E.MUTED}; }}
  .foot {{ padding:4px 16px 12px; color:{E.MUTED}; font-size:11px; }}
  @media print {{ .top,.nav,.crumb,.params,.bar,.pager {{ display:none; }} }}
"""


def page(title, crumb, current, body):
    html = E.chrome(title, "Reporting", crumb, "R. Alvarez (Controller)", current, body)
    return html.replace("</style>", EXTRA_CSS + "</style>", 1)


# ── screen 1: the Job Cost dashboard ─────────────────────────────────────────
def largest_element(r):
    best, lab, ratio = 0, None, None
    for key, label in ELEMENTS:
        var = r[f"var_{key}"]
        if var > best:
            best, lab = var, label
            est = r[f"est_{key}"]
            ratio = r[f"act_{key}"] / est if est else None
    if lab is None:
        return "n/a"
    return f"{lab} ({ratio:.2f})" if ratio is not None else f"{lab} (no est.)"


def grid_rows(x, n, closeout_job, full=False):
    top = x[x["below_estimate"]].sort_values("shortfall", ascending=False).head(n)
    rows = []
    for r in top.itertuples():
        rd = r._asdict()
        jid = f'<a class="lnk" href="job_closeout.html">{r.job_id}</a>' if r.job_id == closeout_job else f'<span class="mono">{r.job_id}</span>'
        loss = '<span class="loss">LOSS</span>' if r.losing else ""
        rows.append(f"<tr><td>{jid}{loss}</td><td class='mono'>{r.part_number}</td><td>{r.cust}</td><td>{TYPE[r.job_type]}</td>"
                    f"<td class='r'>{int(r.quantity):,}</td><td class='r'>{E.money(r.price)}</td><td class='r'>{E.pct(r.est_margin, 1)}</td>"
                    f"<td class='r'>{E.pct(r.act_margin, 1)}</td><td class='r'><b>{E.money(r.shortfall)}</b></td><td>{largest_element(rd)}</td>"
                    f"<td>{r.driver}</td><td>{r.action_status}</td></tr>")
    return "".join(rows)


def dashboard(v, mo, closeout_job):
    P = periods()
    blocks = []
    for key, (lab, name, cur_rng, pri_rng, pri_name) in P.items():
        cur, pri = in_period(v, cur_rng), in_period(v, pri_rng)
        t, tp = tiles(cur), tiles(pri)
        band_c = [int(((cur["act_margin"] >= lo) & (cur["act_margin"] < hi)).sum()) for _, lo, hi in BANDS]
        band_p = [int(((pri["act_margin"] >= lo) & (pri["act_margin"] < hi)).sum()) for _, lo, hi in BANDS]
        est = [cur[f"est_{k}"].sum() for k, _ in ELEMENTS]; act = [cur[f"act_{k}"].sum() for k, _ in ELEMENTS]
        kp = f"""
<div class="kpis">
  <div class="kpi"><div class="l">Margin on price</div><div class="v"{tone(t['margin'], tp['margin'], True)}>{E.pct(t['margin'], 1)}</div><div class="p">prior {E.pct(tp['margin'], 1)} &nbsp; {arrow(t['margin'], tp['margin'])}</div></div>
  <div class="kpi"><div class="l">Below estimate &middot; losing</div><div class="v"><span{tone(t['below'], tp['below'], False, d=0)}>{E.pct(t['below'], 0)}</span> &middot; <span{tone(t['losing'], tp['losing'], False, d=0)}>{E.pct(t['losing'], 0)}</span></div><div class="p">prior {E.pct(tp['below'], 0)} &middot; {E.pct(tp['losing'], 0)} &nbsp; of {t['jobs']:,} jobs</div></div>
  <div class="kpi"><div class="l">Shortfall on below-estimate jobs</div><div class="v"{tone(t['shortfall'], tp['shortfall'], False, k=1, d=0)}>{E.money(t['shortfall'])}</div><div class="p">prior {E.money(tp['shortfall'])} &nbsp; {E.pct(t['short_ms'], 0)} of its cost measured</div></div>
  <div class="kpi"><div class="l">Actual / estimate</div><div class="v"{tone(t['ratio'], tp['ratio'], False, k=1, d=2)}>{t['ratio']:.2f}</div><div class="p">prior {tp['ratio']:.2f} &nbsp; {arrow(t['ratio'], tp['ratio'], pts=False, d=2)}</div></div>
  <div class="kpi"><div class="l">Cost measured</div><div class="v"{tone(t['measured'], tp['measured'], True, d=0)}>{E.pct(t['measured'], 0)}</div><div class="p">prior {E.pct(tp['measured'], 0)} &nbsp; {arrow(t['measured'], tp['measured'], d=0)}</div></div>
</div>"""
        charts = f"""
  <div class="panel"><h2>Jobs by margin band</h2><div class="pbody">{legend([(f"{name}", f"background:{S1}"), (pri_name, f"background:#fff;border:1.3px solid {S1}")])}{svg_bands(band_c, band_p, [b[0] for b in BANDS])}</div></div>
  <div class="panel"><h2>Estimated vs actual cost by element, all jobs</h2><div class="pbody">{legend([("Estimated", f"background:{GREYBAR}"), ("Actual", f"background:{S1}"), ("label: actual &divide; estimate", "display:none")])}{svg_paired(est, act, ["Setup", "Run", "Material", "OSP", "Scrap, rework"])}</div></div>"""
        grid = f"""
<div class="panel"><h2 style="display:flex;justify-content:space-between;"><span>Below-estimate jobs, top 10 by gap &middot; {name}</span><a class="lnk" style="text-transform:none;letter-spacing:0;font-weight:600;" href="job_variance_report.html?period={key}&amp;group=job">Open full report &rarr;</a></h2>
<table class="tight"><thead><tr><th>Job</th><th>Part</th><th>Customer</th><th>Type</th><th class="r">Lot</th><th class="r">Revenue</th><th class="r">Est %</th><th class="r">Act %</th><th class="r">Gap $</th><th>Element (ratio)</th><th>Driver</th><th>Action status</th></tr></thead>
<tbody>{grid_rows(cur, 10, closeout_job)}</tbody></table></div>"""
        blocks.append((key, kp, charts, grid))

    months = list(mo.sort_values("completion_month")["completion_month"].tail(13))
    m13 = mo.set_index("completion_month").loc[months]
    series = [("Setup", S1, m13["shortfall_setup"].tolist()), ("Run", S2, m13["shortfall_run"].tolist()), ("Material", S3, m13["shortfall_material"].tolist()),
              ("Outside processing", S4, m13["shortfall_outside"].tolist()), ("Scrap and rework", S5, m13["shortfall_scrap_rework"].tolist()),
              ("Not attributable", S7, m13["shortfall_not_attributable"].tolist())]
    stacked = f"""<div class="panel"><h2>Shortfall by cost element, 13 months</h2><div class="pbody">{legend([(n, f"background:{c}") for n, c, _ in series])}{svg_stacked(months, series, h=176)}</div></div>"""

    opts = "".join(f'<option value="{k}"{" selected" if k == "month" else ""}>{P[k][0]}: {P[k][1]}</option>' for k in P)
    parts = []
    for key, kp, charts, grid in blocks:
        parts.append(f'<div class="per" data-p="{key}" style="display:{"block" if key == "month" else "none"};">{kp}'
                     f'<div class="grid3">{charts}{"__STACKED__"}</div>{grid}</div>')
    body = f"""
<div class="head" style="padding:8px 16px 2px;"><div><h1>Job Cost Dashboard</h1></div>
  <div class="legend">Period: <select id="per" class="sel" onchange="document.querySelectorAll('.per').forEach(function(e){{e.style.display=e.dataset.p===this.value?'block':'none'}},this)">{opts}</select>
  <span class="lnk" onclick="document.getElementById('defs').style.display='block'">Definitions</span></div></div>
<div class="dash">{''.join(parts).replace('__STACKED__', stacked)}</div>
{definitions(dashboard=True)}
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Job Cost</span> &rsaquo; Job Cost Dashboard'
    return page("Job Cost Dashboard", crumb, "Job Cost dashboard", body)


# ── screen 2: the Job Variance report ────────────────────────────────────────
def report_data(v, wc):
    lo = (END.to_period("M") - 12).start_time
    x = v[v["completed_date"] >= lo].copy()
    jobs = []
    for r in x.itertuples():
        jobs.append([r.job_id, r.part_number, r.cust, r.customer_id or "", TYPE[r.job_type], r.material_group, int(r.quantity), r.lot_band_setup,
                     r.primary_work_center_group or "", est_id(r.estimator_id), r.completed_date.strftime("%Y-%m-%d"), round(r.price, 2),
                     round(r.contribution, 2), round(r.est_total, 2), round(r.act_total, 2), round(r.est_margin, 4), round(r.act_margin, 4),
                     int(bool(r.below_estimate)), int(bool(r.losing)), round(r.shortfall, 2), round(r.measured_cost, 2),
                     round(r.est_setup, 2), round(r.act_setup, 2), round(r.est_run, 2), round(r.act_run, 2), round(r.est_material, 2), round(r.act_material, 2),
                     round(r.est_outside, 2), round(r.act_outside, 2), round(r.act_scrap_rework, 2),
                     r.driver, r.second_driver or "", r.action_status, round(r.est_setup_hours or 0, 2), round(r.act_setup_hours or 0, 2),
                     round(r.est_run_hours or 0, 2), round(r.act_run_hours or 0, 2), r.part_family])
    cols = ["id", "part", "cust", "custId", "type", "mat", "qty", "lot", "wc", "est", "done", "price", "contr", "estTot", "actTot", "estM", "actM",
            "below", "losing", "short", "meas", "eSet", "aSet", "eRun", "aRun", "eMat", "aMat", "eOsp", "aOsp", "aSr", "drv", "drv2", "status",
            "eSetH", "aSetH", "eRunH", "aRunH", "fam"]
    w = wc[wc["completed_date"] >= lo]
    wrows = [[r.job_id, r.work_center_id, r.work_center_type, int(bool(r.monitored_flag)), round(r.est_setup_hours or 0, 3), round(r.act_setup_hours or 0, 3),
              round(r.est_run_hours or 0, 3), round(r.act_run_hours or 0, 3)] for r in w.itertuples()]
    P = periods()
    per = {k: [P[k][2][0].strftime("%Y-%m-%d"), P[k][2][1].strftime("%Y-%m-%d"), P[k][1]] for k in P}
    months = [(END.to_period("M") - i).strftime("%Y-%m") for i in range(12, -1, -1)]
    return {"cols": cols, "jobs": jobs, "wc": wrows, "periods": per, "months": months}


REPORT_JS = r"""
var D = __DATA__;
var C = {}; D.cols.forEach(function(c, i){ C[c] = i; });
var PAGE = 25, page = 1, rows = [], head = [], sortKey = null, sortAsc = false, expanded = {};
function $(id){ return document.getElementById(id); }
function money(x){ if (x === null || x === undefined || isNaN(x)) return 'n/a'; var r = Math.round(x); var s = '$' + Math.abs(r).toLocaleString('en-US'); return r < 0 ? '&minus;' + s : s; }
function pct(x, d){ if (x === null || isNaN(x)) return 'n/a'; return (Math.round(x * Math.pow(10, 2 + (d||0))) / Math.pow(10, d||0)).toFixed(d||0) + '%'; }
function rat(a, e){ return e > 0 ? (a / e).toFixed(2) : 'n/a'; }
function median(a){ a = a.filter(function(v){ return v !== null && !isNaN(v); }).sort(function(x, y){ return x - y; }); if (!a.length) return NaN; var m = Math.floor(a.length / 2); return a.length % 2 ? a[m] : (a[m-1] + a[m]) / 2; }
function bands(ratios){ var n = ratios.length || 1, b = [0,0,0,0]; ratios.forEach(function(r){ if (r < 0.9) b[0]++; else if (r <= 1.1) b[1]++; else if (r <= 1.3) b[2]++; else b[3]++; }); return b.map(function(v){ return v / n; }); }
function bandCells(ratios){ var b = bands(ratios); return '<td class="r">' + ratios.length.toLocaleString() + '</td><td class="r">' + (ratios.length ? median(ratios).toFixed(2) : 'n/a') + '</td>' + b.map(function(v){ return '<td class="r">' + (ratios.length ? pct(v) : 'n/a') + '</td>'; }).join(''); }
var BAND_H = ['Jobs', 'Median ratio', 'Under 0.90', '0.90 to 1.10', '1.10 to 1.30', 'Over 1.30'];

function period(){
  var p = $('period').value;
  if (p === 'custom') return [$('from').value + '-01', lastDay($('to').value), 'Custom range'];
  return D.periods[p];
}
function lastDay(ym){ var y = +ym.slice(0,4), m = +ym.slice(5,7); var d = new Date(Date.UTC(y, m, 0)); return d.toISOString().slice(0,10); }
function filtered(allMonths){
  var p = period(), t = $('ftype').value, cu = $('fcust').value, w = $('fwc').value, dr = $('fdrv').value, b = $('fbelow').checked;
  return D.jobs.filter(function(j){
    if (!allMonths && (j[C.done] < p[0] || j[C.done] > p[1])) return false;
    if (t && j[C.type] !== t) return false; if (cu && j[C.custId] !== cu) return false;
    if (w && j[C.wc] !== w) return false; if (dr && j[C.drv] !== dr) return false;
    if (b && !j[C.below]) return false; return true; });
}
function elCell(a, e){ var v = Math.round(a - e); return (v > 0 ? '+' : '') + money(v) + ' (' + rat(a, e) + ')'; }

var G = {
 job: function(){
  head = ['Job','Part','Customer','Type','Lot','Revenue','Est cost','Act cost','Ratio','Est margin','Act margin','Gap $','Setup $ (ratio)','Run $ (ratio)','Material $ (ratio)','OSP $ (ratio)','Scrap/rework $','Driver','Second driver','Action status'];
  var js = filtered(false).slice().sort(function(a, b){ return b[C.short] - a[C.short] || (a[C.actM] - b[C.actM]); });
  return js.map(function(j){ return [
    '<span class="mono">' + j[C.id] + '</span>' + (j[C.losing] ? '<span class="loss">LOSS</span>' : ''), '<span class="mono">' + j[C.part] + '</span>', j[C.cust], j[C.type],
    [j[C.qty].toLocaleString(), j[C.qty]], [money(j[C.price]), j[C.price]], [money(j[C.estTot]), j[C.estTot]], [money(j[C.actTot]), j[C.actTot]],
    [rat(j[C.actTot], j[C.estTot]), j[C.actTot] / j[C.estTot]], [pct(j[C.estM], 1), j[C.estM]], [pct(j[C.actM], 1), j[C.actM]], ['<b>' + money(j[C.short]) + '</b>', j[C.short]],
    [elCell(j[C.aSet], j[C.eSet]), j[C.aSet] - j[C.eSet]], [elCell(j[C.aRun], j[C.eRun]), j[C.aRun] - j[C.eRun]], [elCell(j[C.aMat], j[C.eMat]), j[C.aMat] - j[C.eMat]],
    [elCell(j[C.aOsp], j[C.eOsp]), j[C.aOsp] - j[C.eOsp]], [money(j[C.aSr]), j[C.aSr]], j[C.drv], j[C.drv2] || 'n/a', j[C.status]]; });
 },
 part: function(){
  head = ['Part','Family','Customer','Jobs','Margin high','Margin low','Spread','Element that varies most','Driver of the low job','Revenue in period'];
  var by = {}; filtered(false).forEach(function(j){ if (j[C.type] !== 'Repeat') return; (by[j[C.part]] = by[j[C.part]] || []).push(j); });
  var out = [];
  Object.keys(by).forEach(function(p){ var js = by[p]; if (js.length < 3) return;
    var hi = Math.max.apply(null, js.map(function(j){ return j[C.actM]; })), lo = Math.min.apply(null, js.map(function(j){ return j[C.actM]; }));
    var low = js.filter(function(j){ return j[C.actM] === lo; })[0];
    var els = [['Setup', C.aSet, C.eSet], ['Run', C.aRun, C.eRun], ['Material', C.aMat, C.eMat], ['OSP', C.aOsp, C.eOsp]], best = 'n/a', bs = 0;
    els.forEach(function(e){ var r = js.filter(function(j){ return j[e[2]] > 0; }).map(function(j){ return j[e[1]] / j[e[2]]; }); if (r.length >= 2) { var s = Math.max.apply(null, r) - Math.min.apply(null, r); if (s > bs) { bs = s; best = e[0] + ' (' + Math.min.apply(null, r).toFixed(2) + ' to ' + Math.max.apply(null, r).toFixed(2) + ')'; } } });
    var rev = js.reduce(function(s, j){ return s + j[C.price]; }, 0);
    var tog = '<span class="lnk" onclick="expanded[\'' + p + '\']=!expanded[\'' + p + '\'];render()">' + (expanded[p] ? '&#9662; ' : '&#9656; ') + p + '</span>';
    out.push([tog, js[0][C.fam], js[0][C.cust], [js.length, js.length], [pct(hi, 1), hi], [pct(lo, 1), lo], ['<b>' + ((hi - lo) * 100).toFixed(1) + ' pts</b>', hi - lo], best, low[C.drv], [money(rev), rev]]);
    if (expanded[p]) js.slice().sort(function(a, b){ return a[C.done] < b[C.done] ? -1 : 1; }).forEach(function(j){
      out.push({child: true, cells: ['<span class="mono">' + j[C.id] + '</span> ' + j[C.done], j[C.qty].toLocaleString() + ' pieces', '', '', pct(j[C.actM], 1), '', '', 'setup ' + rat(j[C.aSet], j[C.eSet]) + ' &middot; run ' + rat(j[C.aRun], j[C.eRun]) + ' &middot; material ' + rat(j[C.aMat], j[C.eMat]), j[C.drv], money(j[C.price])]}); });
  });
  var parents = out.filter(function(r){ return !r.child; });
  // keep children under their parent while sorting by spread
  var groups = []; out.forEach(function(r){ if (!r.child) groups.push([r]); else groups[groups.length - 1].push(r); });
  groups.sort(function(a, b){ return b[0][6][1] - a[0][6][1]; });
  return [].concat.apply([], groups);
 },
 element: function(){
  head = ['Cost element'].concat(['Jobs with an estimate', 'Median ratio', 'Under 0.90', '0.90 to 1.10', '1.10 to 1.30', 'Over 1.30']).concat(['Variance $ (actual &minus; estimate)']);
  var js = filtered(false), out = [];
  [['Setup hours', C.aSet, C.eSet], ['Run hours', C.aRun, C.eRun], ['Material', C.aMat, C.eMat], ['Outside processing', C.aOsp, C.eOsp]].forEach(function(e){
    var w = js.filter(function(j){ return j[e[2]] > 0; }), r = w.map(function(j){ return j[e[1]] / j[e[2]]; });
    var v = js.reduce(function(s, j){ return s + j[e[1]] - j[e[2]]; }, 0);
    out.push({raw: '<td>' + e[0] + '</td>' + bandCells(r) + '<td class="r">' + money(v) + '</td>'}); });
  var sr = js.reduce(function(s, j){ return s + j[C.aSr]; }, 0);
  out.push({raw: '<td>Scrap and rework</td><td class="r">0</td><td class="r" colspan="5" style="text-align:left;color:#5F6B7A;">not carried in the estimate</td><td class="r">' + money(sr) + '</td>'});
  return out;
 },
 wc: function(){
  head = ['Work center','Type','Monitored','Run: jobs','Median','Under 0.90','0.90 to 1.10','1.10 to 1.30','Over 1.30','Setup: jobs','Median','Under 0.90','0.90 to 1.10','1.10 to 1.30','Over 1.30'];
  var keep = {}; filtered(false).forEach(function(j){ keep[j[C.id]] = 1; });
  var by = {};
  // the secondary cells record an operation's setup and run together on the traveler scan, so their
  // run columns compare the two combined and setup is not shown separately
  D.wc.forEach(function(w){ if (!keep[w[0]]) return; var k = w[1]; by[k] = by[k] || {type: w[2], mon: w[3], run: [], set: []};
    if (w[3]) { if (w[6] > 0.05) by[k].run.push(w[7] / w[6]); if (w[4] > 0.05) by[k].set.push(w[5] / w[4]); }
    else if (w[4] + w[6] > 0.05) by[k].run.push((w[5] + w[7]) / (w[4] + w[6])); });
  return Object.keys(by).sort().map(function(k){ var b = by[k];
    var setup = b.mon ? bandCells(b.set) : '<td colspan="6" style="color:#5F6B7A;">recorded with run on the traveler scan</td>';
    return {raw: '<td class="mono">' + k + '</td><td>' + b.type + '</td><td class="c">' + (b.mon ? '&#9679;' : '') + '</td>' + bandCells(b.run) + setup}; });
 },
 material: function(){
  head = ['Material group'].concat(BAND_H.map(function(h, i){ return i === 0 ? 'Jobs with run hours' : h; }));
  var js = filtered(false);
  return ['Aluminum','Steel','Stainless','Titanium','Inconel','Brass and plastics'].map(function(g){
    var r = js.filter(function(j){ return j[C.mat] === g && j[C.eRun] > 0; }).map(function(j){ return j[C.aRun] / j[C.eRun]; });
    return {raw: '<td>' + g + '</td>' + bandCells(r)}; });
 },
 lot: function(){
  head = ['Lot size'].concat(BAND_H.map(function(h, i){ return i === 0 ? 'Jobs with setup' : h; }));
  var js = filtered(false);
  return [['Under 25','under 25 pieces'],['25-100','25 to 100 pieces'],['100-500','100 to 500 pieces'],['Over 500','over 500 pieces']].map(function(l){
    var r = js.filter(function(j){ return j[C.lot] === l[0] && j[C.eSet] > 0; }).map(function(j){ return j[C.aSet] / j[C.eSet]; });
    return {raw: '<td>' + l[1] + '</td>' + bandCells(r)}; });
 },
 estimator: function(){
  head = ['Estimator'].concat(BAND_H.map(function(h, i){ return i === 0 ? 'Jobs quoted' : h; })).concat(['Total cost ratio, all jobs']);
  var js = filtered(false);
  return ['E1','E2','E3'].map(function(e){
    var w = js.filter(function(j){ return j[C.est] === e && j[C.estTot] > 0; }), r = w.map(function(j){ return j[C.actTot] / j[C.estTot]; });
    var tot = w.reduce(function(s, j){ return s + j[C.actTot]; }, 0) / w.reduce(function(s, j){ return s + j[C.estTot]; }, 0);
    return {raw: '<td>' + e + '</td>' + bandCells(r) + '<td class="r">' + (w.length ? tot.toFixed(2) : 'n/a') + '</td>'}; });
 },
 month: function(){
  head = ['Month','Jobs completed','Pieces shipped','Revenue','Margin on price','Below estimate','Losing','Shortfall $','Actual / estimate, median','Cost measured'];
  var js = filtered(true), out = [];
  function line(label, w, bold){ var rev = w.reduce(function(s, j){ return s + j[C.price]; }, 0), c = w.reduce(function(s, j){ return s + j[C.contr]; }, 0);
    var act = w.reduce(function(s, j){ return s + j[C.actTot]; }, 0), meas = w.reduce(function(s, j){ return s + j[C.meas]; }, 0);
    var cells = [label, w.length.toLocaleString(), w.reduce(function(s, j){ return s + j[C.qty]; }, 0).toLocaleString(), money(rev), pct(c / rev, 1),
      pct(w.filter(function(j){ return j[C.below]; }).length / (w.length || 1)), pct(w.filter(function(j){ return j[C.losing]; }).length / (w.length || 1)),
      money(w.reduce(function(s, j){ return s + j[C.short]; }, 0)), median(w.map(function(j){ return j[C.actTot] / j[C.estTot]; })).toFixed(2), pct(meas / act)];
    return {raw: cells.map(function(v, i){ return '<td class="' + (i ? 'r' : '') + '">' + (bold ? '<b>' + v + '</b>' : v) + '</td>'; }).join(''), total: bold}; }
  D.months.forEach(function(m){ out.push(line(new Date(m + '-15').toLocaleString('en-US', {month: 'short', year: 'numeric'}), js.filter(function(j){ return j[C.done].slice(0, 7) === m; }))); });
  out.push(line('Total, 13 months', js.filter(function(j){ return j[C.done].slice(0, 7) >= D.months[0]; }), true));
  return out;
 }
};

function render(){
  var g = $('group').value;
  rows = G[g]();
  if (sortKey !== null) rows = sortRows(rows);
  var pages = Math.max(1, Math.ceil(rows.length / PAGE)); if (page > pages) page = pages;
  var paged = (g === 'job' || g === 'part'), start = (page - 1) * PAGE, slice = paged ? rows.slice(start, start + PAGE) : rows;
  var th = head.map(function(h, i){ return '<th class="' + (i > 0 && g === 'job' && i > 3 && i < 17 ? 'r ' : '') + 'sortable" onclick="sortBy(' + i + ')">' + h + '</th>'; }).join('');
  var body = slice.map(function(r){
    if (r.raw !== undefined) return '<tr' + (r.total ? ' class="total"' : '') + '>' + r.raw + '</tr>';
    if (r.child) return '<tr class="child">' + r.cells.map(function(c, i){ return '<td class="' + ([3,4,5,6,9].indexOf(i) >= 0 ? 'r' : '') + '">' + c + '</td>'; }).join('') + '</tr>';
    return '<tr>' + r.map(function(c){ var v = Array.isArray(c) ? c[0] : c; return '<td' + (Array.isArray(c) ? ' class="r"' : '') + '>' + v + '</td>'; }).join('') + '</tr>'; }).join('');
  $('out').innerHTML = '<table><thead><tr>' + th + '</tr></thead><tbody>' + (body || '<tr><td colspan="' + head.length + '" style="color:#5F6B7A;">No jobs in the period and filters selected.</td></tr>') + '</tbody></table>';
  var p = period();
  $('pinfo').innerHTML = (paged ? ('Page ' + page + ' of ' + pages + ' &middot; ') : '') + rows.filter(function(r){ return !r.child; }).length.toLocaleString() + ' rows &middot; ' + (g === 'month' ? 'the 13 months to June 2026' : p[2]) + ' &middot; by completion date';
  $('prev').style.visibility = (paged && page > 1) ? 'visible' : 'hidden'; $('next').style.visibility = (paged && page < pages) ? 'visible' : 'hidden';
  var u = new URL(location.href); u.searchParams.set('period', $('period').value); u.searchParams.set('group', g); history.replaceState(null, '', u);
}
function sortBy(i){ if (sortKey === i) sortAsc = !sortAsc; else { sortKey = i; sortAsc = false; } render(); }
function sortRows(rs){ if ($('group').value !== 'job') return rs; var i = sortKey;
  return rs.slice().sort(function(a, b){ var x = Array.isArray(a[i]) ? a[i][1] : String(a[i]), y = Array.isArray(b[i]) ? b[i][1] : String(b[i]);
    if (typeof x === 'number') return sortAsc ? x - y : y - x; return sortAsc ? x.localeCompare(y) : y.localeCompare(x); }); }
function exportCsv(){
  var t = $('out').querySelector('table'), lines = [];
  var all = G[$('group').value](); var keep = rows; var html = $('out').innerHTML; PAGE = 1e9; render();
  $('out').querySelectorAll('tr').forEach(function(tr){ lines.push(Array.from(tr.children).map(function(td){ return '"' + td.textContent.replace(/"/g, '""').trim() + '"'; }).join(',')); });
  PAGE = 25; render();
  var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([lines.join('\r\n')], {type: 'text/csv'}));
  a.download = 'job_variance_' + $('group').value + '_' + $('period').value + '.csv'; a.click();
}
function setGroup(){ var g = $('group').value; if (!setGroup.touched) $('fbelow').checked = (g === 'job'); page = 1; sortKey = null; render(); }
(function init(){
  var q = new URLSearchParams(location.search);
  if (q.get('period')) $('period').value = q.get('period');
  if (q.get('group')) $('group').value = q.get('group');
  $('fbelow').checked = $('group').value === 'job';
  if (q.get('expand') && q.get('expand') !== 'first') q.get('expand').split(',').forEach(function(p){ expanded[p] = true; });
  $('period').onchange = function(){ $('custom').style.display = this.value === 'custom' ? 'inline' : 'none'; page = 1; render(); };
  ['from','to','ftype','fcust','fwc','fdrv'].forEach(function(id){ $(id).onchange = function(){ page = 1; render(); }; });
  $('fbelow').onchange = function(){ setGroup.touched = true; page = 1; render(); };
  $('group').onchange = setGroup;
  $('prev').onclick = function(){ page--; render(); }; $('next').onclick = function(){ page++; render(); };
  render();
  if (q.get('expand') === 'first' && $('group').value === 'part' && rows.length) { var m = rows[0][0].match(/([PN]-[0-9]{5})/); if (m) { expanded[m[1]] = true; render(); } }
})();
"""


def report(v, wc):
    data = report_data(v, wc)
    P = periods()
    popts = "".join(f'<option value="{k}">{P[k][0]}: {P[k][1]}</option>' for k in P) + '<option value="custom">Custom range</option>'
    months = data["months"]
    mopts = lambda sel: "".join(f'<option value="{m}"{" selected" if m == sel else ""}>{pd.Period(m).strftime("%b %Y")}</option>' for m in months)
    custs = v[v["customer_id"].notna()].groupby(["customer_id", "cust"]).size().reset_index().sort_values("cust")
    copts = '<option value="">All</option>' + "".join(f'<option value="{r.customer_id}">{r.cust}</option>' for r in custs.itertuples())
    wcs = sorted(v["primary_work_center_group"].dropna().unique())
    cells = {"SWS": "Swiss", "EDM": "Wire EDM", "LTH": "Lathe", "HMC": "Horizontal mill", "VMC": "Vertical mill", "MTN": "Mill-turn", "FAX": "5-axis",
             "SAW": "Saw", "MDP": "Manual drill", "DBR": "Deburr", "INS": "Inspection", "ASM": "Assembly"}
    wopts = '<option value="">All</option>' + "".join(f'<option value="{w}">{w} &middot; {cells.get(w, w)}</option>' for w in wcs)
    dopts = '<option value="">All</option>' + "".join(f"<option>{d}</option>" for d in ["Routing standard", "New or infrequent part setup", "Unbilled revision work", "Vendor rate",
                                                                                        "Scrap and rework", "Material", "Priced below estimated cost", "Not attributable"])
    topts = '<option value="">All</option>' + "".join(f"<option>{t}</option>" for t in ["Repeat", "New", "Own product"])
    gopts = "".join(f'<option value="{k}">{lab}</option>' for k, lab in [("job", "Job"), ("part", "Part"), ("element", "Cost element"), ("wc", "Work center"),
                                                                         ("material", "Material group"), ("lot", "Lot-size band"), ("estimator", "Estimator"), ("month", "Month")])
    body = f"""
<div class="head" style="padding:8px 16px 4px;"><div><h1>Job Variance Report</h1></div>
  <div class="legend"><span class="btn" onclick="exportCsv()">Export to Excel</span><span class="btn" onclick="window.print()">Export to PDF</span>
  <span class="lnk" onclick="document.getElementById('defs').style.display='block'">Definitions</span></div></div>
<div class="params">
  <label>Period</label><select id="period">{popts}</select>
  <span id="custom" style="display:none;"><select id="from">{mopts(months[0])}</select> to <select id="to">{mopts(months[-1])}</select></span>
  <label>Group by</label><select id="group">{gopts}</select>
  <label>Job type</label><select id="ftype">{topts}</select>
  <label>Customer</label><select id="fcust">{copts}</select>
  <label>Work center</label><select id="fwc">{wopts}</select>
  <label>Driver</label><select id="fdrv">{dopts}</select>
  <label><input type="checkbox" id="fbelow"> Below estimate only</label>
</div>
<div class="rep" id="out"></div>
<div class="pager"><span class="btn" id="prev">&lsaquo; Previous</span><span id="pinfo"></span><span class="btn" id="next">Next &rsaquo;</span></div>
<div class="foot">The estimate is the one on the job. Setup and run at the job's work-center pool rate; material as issued; outside processing at the invoice; scrap and rework are not carried in the estimate. Ratios are actual &divide; estimate, and 1.00 is exact. The driver is assigned by rule; see Definitions. The Work center grouping counts an operation where it ran on one machine; at the secondary cells, which record setup and run together, the run columns compare the two combined.</div>
{definitions()}
<script>{REPORT_JS.replace("__DATA__", json.dumps(data, separators=(",", ":")))}</script>
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Job Cost</span> &rsaquo; Job Variance Report'
    return page("Job Variance Report", crumb, "Job Variance report", body)


def run():
    v, mo, wc, closeout_job = load()
    (DOCS / "erp").mkdir(parents=True, exist_ok=True)
    (DOCS / "erp" / "job_cost_dashboard.html").write_text(dashboard(v, mo, closeout_job), encoding="utf-8", newline="\n")
    html = report(v, wc)
    (DOCS / "erp" / "job_variance_report.html").write_text(html, encoding="utf-8", newline="\n")
    print(f"Job cost dashboard and variance report written ({len(html) // 1024} KB report)")


if __name__ == "__main__":
    run()
