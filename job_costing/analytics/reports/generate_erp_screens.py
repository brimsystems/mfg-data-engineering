"""Primary deliverable: the ERP job costing process, three screens and the process document.

Styled as the shop's ERP and its reporting layer, all read from the dbt marts:

  docs/index.html                 Job in progress (reporting layer): actual against estimate by
                                  element as transactions post, each element tagged measured or
                                  estimated with its source, running variance, coverage, flags
  docs/erp/job_closeout.html      Job close-out (reporting layer): final variance by element,
                                  contribution, markup and margin, the drivers in plain words,
                                  coverage, fallback and unrepairable elements
  docs/erp/repricing_queue.html   Repeat-part repricing queue (reporting layer): every repeat
                                  part with standing price, current cost, implied margin, what
                                  moved, the gap to target on annual volume and the decision
  docs/erp/process.html           The one-page process document

Run:  python -m analytics.reports.generate_erp_screens
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
MARTS = REPO / "analytics" / "data" / "marts"
RAW = REPO / "data_source" / "raw"
DOCS = REPO / "docs"
sys.path.insert(0, str(REPO))
from data_source.generate import config as C  # noqa: E402

AS_OF = pd.Timestamp(C.END_DATE)
TARGET = C.TARGET_MARKUP
TARGET_MARGIN = TARGET / (1 + TARGET)
FLAG = 0.15                                   # an element more than this over its estimate is flagged

# ERP chrome (the shop's system) and the reporting layer's accent
BRAND = "#1F3A5F"; NAVBG = "#264A73"; RED = "#C62828"; AMBER = "#E8920A"; GREEN = "#2E7D32"
BLUE = "#381FA1"; BG = "#F3F5F7"; LINE = "#D9DEE5"; MUTED = "#5F6B7A"; ROWRED = "#FDF1F1"; ROWAMB = "#FFFAEF"
MEASURED = "#2E7D32"; ESTIMATED = "#E8920A"; UNREP = "#C62828"

SOURCE_LABEL = {
    "machine": ("Measured", "machine monitoring"), "clock": ("Measured", "cell terminal"),
    "scan": ("Measured", "traveler scan"), "issue": ("Measured", "stock issue"),
    "issue, corrected to part need": ("Measured", "stock issue, corrected to need"),
    "PO": ("Measured", "purchase order"), "PO, attributed": ("Measured", "purchase order, attributed"),
    "GL residual, allocated": ("Estimated", "ledger residual, allocated"),
    "standard-fallback": ("Estimated", "routing standard"), "unrepairable": ("Unrepairable", "clock record, flagged"),
    "erp": ("Recorded", "ERP"),
}
ELEMENT_LABEL = {"material": "Material", "labor": "Labor", "outside": "Outside processing", "scrap": "Scrap"}


def _pq(name):
    """A mart as a frame, with its date columns as timestamps."""
    df = pd.read_parquet(MARTS / f"{name}.parquet")
    for c in df.columns:
        if df[c].dtype == object:
            first = df[c].dropna()
            if len(first) and hasattr(first.iloc[0], "year") and not isinstance(first.iloc[0], str):
                df[c] = pd.to_datetime(df[c])
    return df


def load():
    d = {}
    d["jobs"] = _pq("fct_job_cost")
    d["elements"] = _pq("fct_job_cost_elements")
    d["hours"] = _pq("int_labor_hours_by_job")
    d["est"] = _pq("int_estimate_by_job")
    d["jobs"] = d["jobs"].merge(d["est"][["job_id", "quote_id", "estimate_method"]], on="job_id", how="left")
    d["queue"] = _pq("mart_repricing_queue")
    d["margin"] = _pq("mart_margin_by_job")
    d["parts"] = pd.read_csv(RAW / "erp" / "part_master.csv")
    d["routings"] = pd.read_csv(RAW / "erp" / "routings.csv")
    d["customers"] = pd.read_csv(RAW / "erp" / "customers.csv")
    d["quotes"] = pd.read_csv(RAW / "erp" / "quotes.csv")
    d["pools"] = pd.read_csv(RAW / "remediation" / "rate_pools.csv")
    d["wcs"] = pd.read_csv(RAW / "erp" / "work_centers.csv")
    d["osp"] = _pq("int_osp_by_job")
    d["mat"] = pd.read_csv(RAW / "erp" / "material_transactions.csv")
    d["scrap"] = pd.read_csv(RAW / "erp" / "scrap_rework.csv")
    d["labor"] = pd.read_csv(RAW / "erp" / "labor_transactions.csv", low_memory=False)
    return d


# ── formatting ──────────────────────────────────────────────────────────────
def money(x, d=0):
    if pd.isna(x):
        return "&ndash;"
    return f"&minus;${abs(x):,.{d}f}" if x < 0 else f"${x:,.{d}f}"


def pct(x, d=1):
    if pd.isna(x):
        return "&ndash;"
    v = round(x * 100, d) + 0.0                # no negative zero
    return f"{v:.{d}f}%"


def hrs(x):
    return f"{x:,.1f}" if pd.notna(x) else "&ndash;"


def dt(x):
    return pd.Timestamp(x).strftime("%m/%d/%Y") if pd.notna(x) else "&ndash;"


def tag(kind, note=""):
    color = {"Measured": MEASURED, "Estimated": ESTIMATED, "Unrepairable": UNREP, "Recorded": MUTED}[kind]
    n = f' <span class="tnote">{note}</span>' if note else ""
    return f'<span class="tg" style="background:{color};">{kind}</span>{n}'


def flag(v):
    return f'<span class="flag">&#9650; {pct(v, 0)} over</span>' if pd.notna(v) and v > FLAG else ""


# ── shared chrome ───────────────────────────────────────────────────────────
def css():
    return f"""
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:"Segoe UI", Tahoma, Arial, sans-serif; font-size:12.5px; color:#1F2933; background:#fff; }}
  a {{ color:inherit; text-decoration:none; }}
  .top {{ background:{BRAND}; color:#fff; display:flex; justify-content:space-between; align-items:center; padding:9px 16px; }}
  .top .app {{ font-size:17px; font-weight:700; }}
  .top .who {{ font-size:12px; color:#D6E2F0; }}
  .nav {{ background:{NAVBG}; display:flex; }}
  .nav a {{ color:#E6EEF7; padding:9px 16px; font-size:12.5px; }}
  .nav a.on {{ background:#fff; color:{BRAND}; font-weight:700; }}
  .crumb {{ padding:7px 16px; color:{MUTED}; border-bottom:1px solid {LINE}; background:{BG}; display:flex; justify-content:space-between; }}
  .crumb span {{ color:#2458A6; }}
  .crumb .screens a {{ color:#2458A6; margin-left:14px; }}
  .crumb .screens a.on {{ font-weight:700; color:#1F2933; }}
  .head {{ display:flex; justify-content:space-between; align-items:flex-start; padding:12px 16px 6px; gap:16px; }}
  .head h1 {{ font-size:15px; }}
  .head .sub {{ color:{MUTED}; margin-top:2px; }}
  .bar {{ display:flex; gap:6px; align-items:center; padding:6px 16px; }}
  .btn {{ border:1px solid #AEB8C4; background:#F7F9FB; padding:3px 10px; border-radius:2px; font-size:12px; }}
  .btn.primary {{ background:{BRAND}; color:#fff; border-color:{BRAND}; }}
  .btn.dim {{ color:#9AA5B1; }}
  .sep {{ width:10px; }}
  .filters {{ display:flex; gap:12px; align-items:center; padding:6px 16px 8px; color:{MUTED}; }}
  .sel {{ border:1px solid #AEB8C4; padding:2px 8px; color:#1F2933; background:#fff; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; padding:6px 16px 12px; }}
  .grid3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; padding:6px 16px 12px; }}
  .panel {{ border:1px solid {LINE}; border-radius:3px; }}
  .panel h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:{MUTED}; background:{BG};
    padding:6px 10px; border-bottom:1px solid {LINE}; font-weight:700; }}
  .fields {{ display:grid; grid-template-columns:150px 1fr; row-gap:5px; column-gap:10px; padding:10px; }}
  .fields .k {{ color:{MUTED}; }}
  .fields .v {{ font-weight:600; }}
  .fields .v input, .fields .v .box {{ border:1px solid #AEB8C4; padding:2px 6px; font:inherit; background:#fff; min-width:160px; display:inline-block; }}
  table {{ border-collapse:collapse; width:100%; }}
  th {{ background:#E9EDF2; text-align:left; padding:6px 7px; border:1px solid {LINE}; font-weight:600; white-space:nowrap; }}
  td {{ padding:5px 7px; border:1px solid {LINE}; }}
  td.r, th.r {{ text-align:right; white-space:nowrap; }} td.c {{ text-align:center; }}
  tr.total td {{ font-weight:700; background:{BG}; }}
  tr.sub td {{ color:{MUTED}; }}
  tr.sub td:first-child {{ padding-left:22px; }}
  .mono {{ font-family:Consolas, monospace; }}
  .tg {{ color:#fff; font-weight:700; font-size:10px; padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.3px; }}
  .tnote {{ color:{MUTED}; font-size:11px; }}
  .flag {{ color:{RED}; font-weight:700; font-size:11px; white-space:nowrap; }}
  .badge {{ color:#fff; font-weight:700; font-size:11px; padding:2px 7px; border-radius:3px; white-space:nowrap; }}
  .kpis {{ display:flex; gap:10px; padding:6px 16px 4px; flex-wrap:wrap; }}
  .kpi {{ border:1px solid {LINE}; border-radius:3px; padding:8px 14px; min-width:150px; flex:1; }}
  .kpi .l {{ font-size:11px; color:{MUTED}; text-transform:uppercase; letter-spacing:.4px; }}
  .kpi .v {{ font-size:18px; font-weight:700; margin-top:2px; }}
  .kpi .s {{ font-size:11px; color:{MUTED}; }}
  .cov {{ height:9px; background:#E3E7EC; border-radius:5px; overflow:hidden; margin-top:6px; display:flex; }}
  .cov i {{ display:block; height:100%; }}
  .rl {{ background:{BLUE}; color:#fff; font-size:10px; font-weight:700; padding:1px 5px; border-radius:2px; margin-left:6px; vertical-align:middle; }}
  .note {{ padding:4px 16px 12px; color:{MUTED}; font-size:11.5px; }}
  .drivers {{ padding:10px; }}
  .drivers li {{ margin:0 0 6px 16px; }}
  .legend {{ display:flex; gap:14px; align-items:center; font-size:11px; color:{MUTED}; }}
  th.sortable {{ cursor:pointer; }} th.sortable:hover {{ background:#DCE3EA; }}
  th.sortable::after {{ content:" \\2195"; color:#9AA5B1; }}
  .doc {{ max-width:900px; margin:0 auto; padding:18px 24px 40px; font-size:13.5px; line-height:1.55; }}
  .doc h1 {{ font-size:18px; margin-bottom:4px; }}
  .doc h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.5px; color:{MUTED}; margin:18px 0 6px; border-bottom:1px solid {LINE}; padding-bottom:3px; }}
  .doc p {{ margin-bottom:8px; }}
  .doc table {{ margin:6px 0 10px; font-size:12.5px; }}
  .doc .meta {{ color:{MUTED}; font-size:12px; margin-bottom:10px; }}
"""


SCREENS = [("index.html", "Job in progress", "../index.html"),
           ("erp/job_closeout.html", "Job close-out", "job_closeout.html"), ("erp/repricing_queue.html", "Repricing queue", "repricing_queue.html"),
           ("erp/process.html", "Process document", "process.html")]


def chrome(title, module, crumb, who, current, body, in_erp_dir=True):
    """The ERP frame: top bar, module tabs, breadcrumb with the screen links."""
    mods = ["Dashboard", "Quoting", "Jobs", "Scheduling", "Data Collection", "Purchasing", "Job Cost", "Reporting", "Admin"]
    nav = "".join(f'<a class="{"on" if n == module else ""}">{n}</a>' for n in mods)
    links = ""
    for path, label, rel in SCREENS:
        href = rel if in_erp_dir else (path if path != "index.html" else "index.html")
        links += f'<a class="{"on" if label == current else ""}" href="{href}">{label}</a>'
    day = AS_OF.strftime("%A, %B %d, %Y")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | Enterprise Resource Planning</title>
<style>{css()}</style></head><body>
<div class="top"><div class="app">Enterprise Resource Planning</div>
  <div class="who">{who} &nbsp;&nbsp; {day}</div></div>
<div class="nav">{nav}</div>
<div class="crumb"><div>{crumb}</div><div class="screens">{links}</div></div>
{body}
</body></html>"""


# ── job selection ───────────────────────────────────────────────────────────
def pick_jobs(d):
    j = d["jobs"]
    r = j[j["version"] == "restructured"].copy()
    parts = d["parts"].set_index("part_number")
    r["part_type"] = r["part_number"].map(parts["part_type"]) if "part_type" in parts else np.where(r["job_type"] == "own_product", "own_product", r["job_type"])
    live = pd.Timestamp(C.CONFIG_DATES["monitoring_to_jobs"])
    # job creation: a new part won on quote after the pools went live, with outside processing on it
    cr = r[(r["job_type"] == "new") & (r["release_date"] >= pd.Timestamp(C.CONFIG_DATES["rate_pools_live"])) & (r["est_outside"] > 0)]
    creation = cr.sort_values("release_date").iloc[-1]
    # job in progress: released in the last three weeks, part way through its routing
    ip = r[(r["status"] == "in_process") & (r["release_date"] >= AS_OF - pd.Timedelta(days=21))
           & (r["coverage"].between(0.35, 0.9)) & (r["machine_hours"] > 0) & (r["act_outside"] == 0) & (r["est_total_cost"] > 3000)]
    if ip.empty:
        ip = r[(r["status"] == "in_process") & (r["machine_hours"] > 0)]
    progress = ip.sort_values("coverage").iloc[len(ip) // 2]
    # close-out: a completed small-lot job on a monitored cell whose labor ran over
    co = r[(r["status"] == "completed") & (r["release_date"] >= live) & r["flag_labor"] & (r["quantity"] < C.SMALL_LOT_THRESHOLD)
           & (r["machine_hours"] > 0) & (r["act_outside"] > 0) & (r["coverage"] > 0.9)]
    if co.empty:
        co = r[(r["status"] == "completed") & (r["release_date"] >= live) & r["flag_labor"]]
    closeout = co.sort_values("variance_labor").iloc[-1]
    return creation, progress, closeout


# ── element rows shared by the two reporting-layer screens ──────────────────
def element_rows(d, job, version):
    """Actual against estimate by element, each actual split by its source."""
    el = d["elements"]
    e = el[(el["job_id"] == job["job_id"]) & (el["version"] == version)]
    rows = []
    for element in ["material", "labor", "outside", "scrap"]:
        est = {"material": job["est_material"], "labor": job["est_labor"], "outside": job["est_outside"], "scrap": 0.0}[element]
        sub = e[e["element"] == element].sort_values(["work_center_id", "amount"], ascending=[True, False], na_position="last")
        act = sub["amount"].sum()
        est_h = (job["est_setup_hours"] or 0) + (job["est_run_hours"] or 0) if element == "labor" else None
        act_h = sub["hours"].sum() if element == "labor" else None
        v = act - est if est else (act if act else 0.0)
        share = v / est if est else np.nan
        rows.append({"kind": "main", "label": ELEMENT_LABEL[element], "est": est, "act": act, "est_h": est_h, "act_h": act_h,
                     "var": v, "share": share, "sources": sub})
    return rows


def coverage_bar(job):
    m = job["coverage"] or 0; fb = job["fallback_share"] or 0; un = job["unrepairable_share"] or 0
    return (f'<div class="cov"><i style="width:{m*100:.1f}%;background:{MEASURED};"></i>'
            f'<i style="width:{fb*100:.1f}%;background:{ESTIMATED};"></i>'
            f'<i style="width:{un*100:.1f}%;background:{UNREP};"></i></div>')


def render_elements_table(rows, running=True):
    out = []
    for r in rows:
        f = flag(r["share"]) if r["est"] else ""
        est_c = money(r["est"]) if r["est"] or r["label"] != "Scrap" else "&ndash;"
        var_c = (f'{"+" if r["var"] > 0 else ""}{money(r["var"])}' if (r["est"] or r["act"]) else "&ndash;")
        hrs_c = f'{hrs(r["act_h"])} / {hrs(r["est_h"])}' if r["act_h"] is not None else ""
        out.append(f'<tr><td><b>{r["label"]}</b></td><td class="r">{est_c}</td><td class="r"><b>{money(r["act"])}</b></td>'
                   f'<td class="r">{hrs_c}</td><td class="r">{var_c} {f}</td><td></td></tr>')
        for s in r["sources"].itertuples():
            kind, note = SOURCE_LABEL.get(s.source, ("Measured", s.source))
            label = f'<span class="mono">{s.work_center_id}</span> &middot; {note}' if getattr(s, "work_center_id", None) else note
            h = hrs(s.hours) if pd.notna(s.hours) else ""
            conf = f'{s.confidence:.0%}' if kind == "Measured" and s.confidence < 0.999 else ""
            out.append(f'<tr class="sub"><td>{label}</td><td></td><td class="r">{money(s.amount)}</td><td class="r">{h}</td>'
                       f'<td></td><td>{tag(kind)} <span class="tnote">{("confidence " + conf) if conf else ""}</span></td></tr>')
    return "".join(out)


# ── screen 2: job in progress (reporting layer) ─────────────────────────────
def job_progress(d, job):
    parts = d["parts"].set_index("part_number"); p = parts.loc[job["part_number"]]
    cust = d["customers"].set_index("customer_id")["name"].get(job["customer_id"], "Own product, to stock")
    rows = element_rows(d, job, "restructured")
    h = d["hours"][d["hours"]["job_id"] == job["job_id"]].sort_values(["work_center_id"])
    rt = d["routings"][d["routings"]["part_number"] == job["part_number"]].sort_values("op_seq")
    qty = int(job["quantity"])
    op_rows = []
    for r in rt.itertuples():
        grp = r.work_center_id[:3]
        hh = h[h["work_center_id"].str[:3] == grp]
        est_h = r.std_setup_hours + r.std_run_min_per_piece / 60 * qty
        if len(hh) and (hh["source"] != "standard-fallback").any():
            hh = hh[hh["source"] != "standard-fallback"]
            src = hh["source"].iloc[0]; kind, note = SOURCE_LABEL[src]
            act_h = hh["hours"].sum(); status = "Complete" if act_h >= 0.6 * est_h else "In process"
            conf = hh["confidence"].mean()
            cell = f'{tag(kind, note)}' + (f' <span class="tnote">confidence {conf:.0%}</span>' if kind == "Measured" and conf < 0.999 else "")
            op_rows.append(f'<tr><td class="c">{r.op_seq}</td><td class="mono">{", ".join(sorted(hh["work_center_id"].unique()))}</td>'
                           f'<td class="r">{hrs(est_h)}</td><td class="r"><b>{hrs(act_h)}</b></td><td>{cell}</td><td>{status}</td></tr>')
        else:
            op_rows.append(f'<tr><td class="c">{r.op_seq}</td><td class="mono">{r.work_center_id}</td><td class="r">{hrs(est_h)}</td>'
                           f'<td class="r">{hrs(est_h)}</td><td>{tag("Estimated", "routing standard, not yet run")}</td><td style="color:{MUTED};">Not started</td></tr>')
    posted = job["act_total_cost"]; est = job["est_total_cost"]
    var = posted - est
    body = f"""
<div class="head"><div><h1>Job Cost in Progress: {job['job_id']} <span class="rl">REPORTING LAYER</span></h1>
  <div class="sub">{job['part_number']} &middot; {p['description']} &middot; {cust} &middot; {qty:,} pieces &middot; released {dt(job['release_date'])}</div></div>
  <div class="legend"><span class="badge" style="background:{AMBER};">&bull; IN PROCESS</span>
    <span>{tag('Measured')} machine, terminal, scan, issue, PO</span><span>{tag('Estimated')} routing standard, ledger residual</span><span>{tag('Unrepairable')} flagged record</span></div></div>
<div class="kpis">
  <div class="kpi"><div class="l">Estimated cost</div><div class="v">{money(est)}</div><div class="s">carried from quote {job['quote_id'] or ''}</div></div>
  <div class="kpi"><div class="l">Cost posted to date</div><div class="v">{money(posted)}</div><div class="s">{pct(posted / est, 0)} of estimate, {sum(1 for o in op_rows if 'Not started' not in o)} of {len(op_rows)} operations started</div></div>
  <div class="kpi"><div class="l">Running variance</div><div class="v" style="color:{RED if var > 0 else GREEN};">{'+' if var > 0 else ''}{money(var)}</div><div class="s">includes routing standard for operations not yet run</div></div>
  <div class="kpi"><div class="l">Coverage, measured share of cost</div><div class="v">{pct(job['coverage'], 0)}</div>{coverage_bar(job)}<div class="s">{pct(job['fallback_share'], 0)} estimated &middot; {pct(job['unrepairable_share'], 0)} unrepairable</div></div>
  <div class="kpi"><div class="l">Quoted price</div><div class="v">{money(job['price'])}</div><div class="s">margin at estimate {pct(job['estimated_margin_on_price'], 0)} &middot; running {pct(job['margin_on_price'], 0)}</div></div>
</div>
<div class="grid" style="grid-template-columns:3fr 2fr;">
  <div class="panel"><h2>Actual against estimate by cost element</h2>
    <table><thead><tr><th>Element / source</th><th class="r">Estimate</th><th class="r">Actual to date</th><th class="r">Hours act / est</th><th class="r">Variance</th><th>Basis</th></tr></thead>
    <tbody>{render_elements_table(rows)}
    <tr class="total"><td>Total</td><td class="r">{money(est)}</td><td class="r">{money(posted)}</td><td class="r">{hrs(job['act_labor_hours'])} / {hrs((job['est_setup_hours'] or 0) + (job['est_run_hours'] or 0))}</td><td class="r">{'+' if var > 0 else ''}{money(var)} {flag(var / est)}</td><td></td></tr></tbody></table>
    <div class="note" style="padding:8px 10px 10px;">An element is flagged when it runs more than {FLAG:.0%} over its estimate. A measured element rests on a transaction: a machine-monitoring interval assigned to the job, a clock record at the cell terminal, a traveler scan, a stock issue or a purchase order. An estimated element carries the routing standard until the transaction posts.</div></div>
  <div class="panel"><h2>Operations</h2>
    <table><thead><tr><th>Op</th><th>Work center</th><th class="r">Std hrs</th><th class="r">Hours</th><th>Source</th><th>Status</th></tr></thead>
    <tbody>{''.join(op_rows)}</tbody></table></div>
</div>
<div class="note">Cost as of {AS_OF.strftime('%m/%d/%Y')} from the job cost mart (restructured version): machine hours from the monitoring feed at the work-center pool rate, cell-terminal records where the cell is not monitored, traveler scans at secondary operations, stock issues at actual price and purchase-order lines carrying this job number. Operations not yet run carry the routing standard and are tagged estimated.</div>
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Job Cost</span> &rsaquo; Job in Progress'
    return chrome(f"Job Cost in Progress {job['job_id']}", "Reporting", crumb, "R. Alvarez (Controller)", "Job in progress", body, in_erp_dir=False)


# ── screen 3: job close-out (reporting layer) ───────────────────────────────
def variance_drivers(d, job, rows):
    """The drivers of variance in plain words, from the elements and hours."""
    out = []
    qty = int(job["quantity"])
    est_setup, est_run = job["est_setup_hours"] or 0, job["est_run_hours"] or 0
    act_setup, act_run = job["act_setup_hours"] or 0, job["act_run_hours"] or 0
    if est_setup and act_setup / est_setup > 1.15:
        out.append(f"Setup ran {act_setup / est_setup:.1f}&times; the standard ({hrs(act_setup)} against {hrs(est_setup)} hours)"
                   + (f" on a lot of {qty} pieces: the standard assumes a repeat setup and this was a first-article setup." if qty < C.SMALL_LOT_THRESHOLD else "."))
    elif est_setup and act_setup / est_setup < 0.85:
        out.append(f"Setup came in under the standard ({hrs(act_setup)} against {hrs(est_setup)} hours).")
    if est_run and act_run / est_run > 1.15:
        p = d["parts"].set_index("part_number").loc[job["part_number"]]
        why = " the estimator's speeds and feeds for this material were never validated." if p["material_spec"] in C.ESTIMATOR_BIAS_MATERIALS else " the routing standard is faster than the cycle the machines measured."
        out.append(f"Run time ran {act_run / est_run:.2f}&times; the standard ({hrs(act_run)} against {hrs(est_run)} hours):{why}")
    elif est_run and act_run / est_run < 0.85:
        out.append(f"Run time came in under the standard ({hrs(act_run)} against {hrs(est_run)} hours); the standard is stale on the slow side.")
    r = {x["label"]: x for x in rows}
    m = r["Material"]
    if m["est"] and abs(m["share"]) > 0.05:
        out.append(f"Material {'ran over' if m['share'] > 0 else 'came in under'} the estimate by {pct(abs(m['share']), 0)} ({money(m['act'])} against {money(m['est'])}): issued at the price of the day against the price in the estimate.")
    o = r["Outside processing"]
    if o["est"] and abs(o["share"]) > 0.05:
        out.append(f"Outside processing {'ran over' if o['share'] > 0 else 'came in under'} the estimate by {pct(abs(o['share']), 0)} ({money(o['act'])} against {money(o['est'])}), on the vendor's invoiced price.")
    if (job["act_rework_hours"] or 0) > 0:
        out.append(f"{hrs(job['act_rework_hours'])} hours of rework were recorded against the job.")
    if r["Scrap"]["act"] > 0:
        out.append(f"Scrapped pieces cost {money(r['Scrap']['act'])} in material.")
    if not out:
        out.append("Every element landed within 5% of its estimate.")
    return out


def job_closeout(d, job):
    parts = d["parts"].set_index("part_number"); p = parts.loc[job["part_number"]]
    cust = d["customers"].set_index("customer_id")["name"].get(job["customer_id"], "Own product, to stock")
    rows = element_rows(d, job, "restructured")
    drivers = variance_drivers(d, job, rows)
    est = job["est_total_cost"]; act = job["act_total_cost"]; price = job["price"]; var = act - est
    contrib = price - act; markup = price / act - 1; margin = contrib / price
    mk_color = GREEN if margin >= TARGET_MARGIN - 0.02 else AMBER if margin >= 0.10 else RED
    el = d["elements"]; e = el[(el["job_id"] == job["job_id"]) & (el["version"] == "restructured")]
    fb = e[e["source"].isin(["standard-fallback", "GL residual, allocated", "unrepairable"])]
    fb_rows = "".join(f'<tr><td>{ELEMENT_LABEL[x.element]}</td><td>{SOURCE_LABEL[x.source][1]}</td><td class="r">{money(x.amount)}</td>'
                      f'<td>{tag(SOURCE_LABEL[x.source][0])}</td></tr>' for x in fb.itertuples()) or '<tr><td colspan="4" style="color:#5F6B7A;">None: every element on this job is measured.</td></tr>'
    body = f"""
<div class="head"><div><h1>Job Cost Close-out: {job['job_id']} <span class="rl">REPORTING LAYER</span></h1>
  <div class="sub">{job['part_number']} &middot; {p['description']} &middot; {cust} &middot; {int(job['quantity']):,} pieces &middot; released {dt(job['release_date'])} &middot; completed {dt(job['completed_date'])}</div></div>
  <div class="legend"><span class="badge" style="background:{GREEN};">&bull; COMPLETE</span>
    <span>{tag('Measured')}</span><span>{tag('Estimated')}</span><span>{tag('Unrepairable')}</span></div></div>
<div class="kpis">
  <div class="kpi"><div class="l">Price</div><div class="v">{money(price)}</div><div class="s">{money(price / job['quantity'], 2)} per piece</div></div>
  <div class="kpi"><div class="l">Estimated cost</div><div class="v">{money(est)}</div><div class="s">margin at estimate {pct(job['estimated_margin_on_price'], 0)}</div></div>
  <div class="kpi"><div class="l">Actual cost</div><div class="v">{money(act)}</div><div class="s">variance {'+' if var > 0 else ''}{money(var)} ({'+' if var > 0 else ''}{pct(var / est, 0)})</div></div>
  <div class="kpi"><div class="l">Contribution</div><div class="v" style="color:{mk_color};">{money(contrib)}</div><div class="s">markup on cost {pct(markup, 0)} &middot; margin on price {pct(margin, 0)}</div></div>
  <div class="kpi"><div class="l">Coverage</div><div class="v">{pct(job['coverage'], 0)}</div>{coverage_bar(job)}<div class="s">{pct(job['fallback_share'], 0)} estimated &middot; {pct(job['unrepairable_share'], 0)} unrepairable</div></div>
</div>
<div class="grid" style="grid-template-columns:3fr 2fr;">
  <div class="panel"><h2>Final variance by cost element</h2>
    <table><thead><tr><th>Element / source</th><th class="r">Estimate</th><th class="r">Actual</th><th class="r">Hours act / est</th><th class="r">Variance</th><th>Basis</th></tr></thead>
    <tbody>{render_elements_table(rows, running=False)}
    <tr class="total"><td>Total</td><td class="r">{money(est)}</td><td class="r">{money(act)}</td><td class="r">{hrs(job['act_labor_hours'])} / {hrs((job['est_setup_hours'] or 0) + (job['est_run_hours'] or 0))}</td><td class="r">{'+' if var > 0 else ''}{money(var)} {flag(var / est)}</td><td></td></tr></tbody></table></div>
  <div>
    <div class="panel"><h2>What drove the variance</h2><ul class="drivers">{''.join(f'<li>{x}</li>' for x in drivers)}</ul></div>
    <div class="panel" style="margin-top:14px;"><h2>Estimated and unrepairable elements</h2>
      <table><thead><tr><th>Element</th><th>Basis</th><th class="r">Amount</th><th>Tag</th></tr></thead><tbody>{fb_rows}</tbody></table></div>
  </div>
</div>
<div class="note">Markup on cost is the quoting convention (target {pct(TARGET, 0)}); margin on price is the reporting convention (target {pct(TARGET_MARGIN, 0)}). Both are stated. Hours are setup plus run plus rework; the estimate's hours are setup plus run at the routing standard in force at release.</div>
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Job Cost</span> &rsaquo; Close-out'
    return chrome(f"Job Cost Close-out {job['job_id']}", "Reporting", crumb, "R. Alvarez (Controller)", "Job close-out", body)


# ── screen 4: repricing queue (reporting layer) ─────────────────────────────
def repricing_queue(d):
    q = d["queue"].copy()
    q = q.sort_values("gap_to_target_annual", ascending=False)
    cust = d["customers"].set_index("customer_id")["name"]
    n_below = int(q["below_target"].sum()); n_cost = int(q["below_cost"].sum())
    dec = q["decision"].value_counts()
    gap_total = q.loc[q["below_target"], "gap_to_target_annual"].sum()
    q_dec = q[q["decision"].notna()]
    recovered = (q_dec.loc[q_dec["decision"] == "reprice", "new_price"] - q_dec.loc[q_dec["decision"] == "reprice", "standing_price"]).mul(q_dec.loc[q_dec["decision"] == "reprice", "annual_volume"]).sum()
    badge = {"reprice": GREEN, "hold": AMBER, "exit": RED, "pending": MUTED}
    trs = []
    for r in q.itertuples():
        moved = []
        for k, lab in [("moved_material", "material"), ("moved_rate", "rate"), ("moved_standard", "standard"), ("moved_outside", "outside")]:
            v = getattr(r, k)
            if pd.notna(v) and abs(v) >= 0.01:
                moved.append((abs(v), f'{lab} {"+" if v > 0 else "&minus;"}{money(abs(v), 2)}'))
        moved = ", ".join(t for _, t in sorted(moved, reverse=True)[:3])
        m_color = RED if r.implied_margin_on_price < 0 else AMBER if r.below_target else GREEN
        dcell = (f'<span class="badge" style="background:{badge[r.decision]};">{r.decision.upper()}</span>'
                 f'<span class="tnote"> {money(r.new_price, 2) if pd.notna(r.new_price) else ""} {dt(r.decision_date)}</span>' if pd.notna(r.decision) else
                 '<span class="tnote">not yet reviewed</span>')
        rowbg = ROWRED if r.below_cost else ROWAMB if r.below_target else "#fff"
        trs.append(f'<tr style="background:{rowbg};"><td class="mono">{r.part_number}</td><td>{cust.get(r.customer_id, "")}</td><td>{r.part_family}</td>'
                   f'<td class="r" data-v="{r.annual_volume}">{r.annual_volume:,.0f}</td><td class="r" data-v="{r.standing_price}">{money(r.standing_price, 2)}</td>'
                   f'<td class="r" data-v="{r.current_unit_cost}">{money(r.current_unit_cost, 2)}</td><td class="r" data-v="{r.implied_margin_on_price}" style="color:{m_color};font-weight:700;">{pct(r.implied_margin_on_price, 0)}</td>'
                   f'<td class="r" data-v="{r.markup_on_current_cost}">{pct(r.markup_on_current_cost, 0)}</td><td class="r" data-v="{r.target_price}">{money(r.target_price, 2)}</td>'
                   f'<td class="wrap">{moved}</td><td class="r" data-v="{r.gap_to_target_annual}"><b>{money(r.gap_to_target_annual)}</b></td>'
                   f'<td class="r" data-v="{r.last_quote_date or ""}">{dt(r.last_quote_date)}</td><td title="{r.rationale or ""}">{dcell}</td></tr>')
    body = f"""
<div class="head"><div><h1>Repeat-Part Repricing Queue <span class="rl">REPORTING LAYER</span></h1>
  <div class="sub">Every repeat part against its current cost at today's material prices, work-center pool rates and measured standards &middot; {AS_OF.strftime('%m/%d/%Y')}</div></div>
  <div class="legend"><span class="badge" style="background:{RED};">{n_cost}</span> below cost <span class="badge" style="background:{AMBER};">{n_below - n_cost}</span> below cost plus target
    <span class="badge" style="background:{GREEN};">{len(q) - n_below:,}</span> at or above target</div></div>
<div class="kpis">
  <div class="kpi"><div class="l">Repeat parts</div><div class="v">{len(q):,}</div><div class="s">standing prices set at first quote, moved by annual letters</div></div>
  <div class="kpi"><div class="l">Below cost plus target</div><div class="v">{n_below} <span style="font-size:13px;color:{MUTED};">({n_below / len(q):.0%})</span></div><div class="s">{n_cost} of them below current cost</div></div>
  <div class="kpi"><div class="l">Gap to target on annual volume</div><div class="v">{money(gap_total)}</div><div class="s">across the {n_below} parts below target</div></div>
  <div class="kpi"><div class="l">Review decisions, weeks 7 to 9</div><div class="v">{int(dec.get('reprice', 0))} repriced</div><div class="s">{int(dec.get('hold', 0))} held &middot; {int(dec.get('exit', 0))} exited &middot; {int(dec.get('pending', 0))} pending</div></div>
  <div class="kpi"><div class="l">Annual margin recovered by decisions taken</div><div class="v">{money(recovered)}</div><div class="s">new price less standing price, on annual volume</div></div>
</div>
<div class="bar"><span class="btn primary">Propose Price</span><span class="btn">Hold</span><span class="btn">Exit at Next Release</span><span class="sep"></span><span class="btn">Export</span>
  <span class="tnote" style="margin-left:14px;">Click a column heading to sort. Hover a decision for its rationale.</span></div>
<div class="filters">Customer: <span class="sel">All &#9662;</span> Family: <span class="sel">All &#9662;</span> Status: <span class="sel">All &#9662;</span> Decision: <span class="sel">All &#9662;</span></div>
<style>#rq td {{ white-space:nowrap; font-size:12px; padding:4px 6px; }} #rq td.wrap {{ white-space:normal; max-width:300px; }} #rq th {{ font-size:11.5px; }}</style>
<table id="rq" style="width:calc(100% - 32px);margin:0 16px 16px;"><thead><tr>
<th class="sortable">Part</th><th class="sortable">Customer</th><th class="sortable">Family</th><th class="r sortable">Annual vol</th><th class="r sortable">Standing price</th>
<th class="r sortable">Current cost</th><th class="r sortable">Implied margin</th><th class="r sortable">Markup on cost</th><th class="r sortable">Target price</th><th>What moved since last quote (per piece)</th>
<th class="r sortable">Gap to target, annual</th><th class="r sortable">Last quote</th><th class="sortable">Decision</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
<div class="note">Current cost per piece over the part's typical lot: material need per piece at the last three months' issued price; setup and run at the routing standard (refreshed from machine-measured cycles where the review accepted the measurement) at each work center's pool rate; outside processing at the latest purchase-order price. Target price is current cost plus {pct(TARGET, 0)} markup ({pct(TARGET_MARGIN, 0)} margin on price). Gap to target is the shortfall per piece on the last twelve months' volume. Rows shaded red are below cost; amber below cost plus target.</div>
<script>
(function(){{
  var t=document.getElementById('rq'), ths=t.querySelectorAll('th.sortable');
  ths.forEach(function(th,i){{ th.addEventListener('click',function(){{
    var rows=Array.from(t.tBodies[0].rows), asc=th.dataset.asc!=='1'; th.dataset.asc=asc?'1':'0';
    rows.sort(function(a,b){{ var ca=a.cells[i], cb=b.cells[i];
      var va=ca.dataset.v!==undefined?parseFloat(ca.dataset.v):ca.textContent.trim(), vb=cb.dataset.v!==undefined?parseFloat(cb.dataset.v):cb.textContent.trim();
      if(typeof va==='number'&&typeof vb==='number'){{ if(isNaN(va))va=-1e18; if(isNaN(vb))vb=-1e18; return asc?va-vb:vb-va; }}
      return asc?String(va).localeCompare(String(vb)):String(vb).localeCompare(String(va)); }});
    rows.forEach(function(r){{ t.tBodies[0].appendChild(r); }}); }}); }});
}})();
</script>
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Pricing</span> &rsaquo; Repeat-Part Repricing Queue'
    return chrome("Repricing Queue", "Reporting", crumb, "R. Alvarez (Controller)", "Repricing queue", body), (n_below, n_cost, gap_total, recovered)


# ── the process document ────────────────────────────────────────────────────
def process_doc(d):
    cov = _pq("mart_coverage_weekly")
    last = cov.dropna(subset=["measured_cost_share"]).iloc[-1]
    scan = cov.dropna(subset=["scan_coverage"]).iloc[-1]
    body = f"""
<div class="doc">
<h1>Job Costing Process</h1>
<div class="meta">One page, for whoever runs job cost next. In force since engagement week 6 ({dt(C.CONFIG_DATES['scrap_reason_req'])}). Owner: Controller.</div>

<h2>1. What every job goes through</h2>
<p>A job exists to be compared with its estimate. Every transaction below carries the job number, and the reporting layer builds job cost from the transactions, never from a manual entry.</p>
<table><thead><tr><th>Step</th><th>Transaction</th><th>Who posts it</th><th>What the job cost reads</th><th>Tag</th></tr></thead><tbody>
<tr><td>1</td><td>Job created, with its estimate</td><td>Estimator, in Quoting; the pipeline for repeat parts</td><td>The estimate by element (material, setup, run by work center, outside processing) lands on the job when it is created. A job cannot be released without it. Where it comes from depends on the job type; see below.</td><td>Estimate</td></tr>
<tr><td>2</td><td>Stock issue</td><td>Stockroom lead, or the saw operator at the saw terminal</td><td>Material at the price of the day. Bar is issued to one job; a remnant used on another job is issued to that job, at the same price.</td><td>Measured (issue)</td></tr>
<tr><td>3</td><td>Machine hours</td><td>The monitoring feed, automatically</td><td>Setup, in-cycle, alarm and in-operation idle time on the monitored cells posts to the job the operator opened at the cell terminal. This is the labor figure on every CNC cell; the clock record is a check, not the source.</td><td>Measured (machine)</td></tr>
<tr><td>4</td><td>Clock record at the cell terminal</td><td>Operator</td><td>One open operation per employee; the code says setup, run, rework or indirect. Unmonitored cells cost from the record. Any record still open at shift end auto-closes and is flagged for the cell lead's review the next morning.</td><td>Measured (terminal)</td></tr>
<tr><td>5</td><td>Traveler scan</td><td>Operator at saw, deburr, inspection and assembly</td><td>Start and finish scans on the traveler at every secondary operation. The hours between the scans cost the operation.</td><td>Measured (scan)</td></tr>
<tr><td>6</td><td>Outside-processing purchase order</td><td>Buyer</td><td>The job number is a required field. The PO line and its receipt land on the job; the invoice replaces the PO price when it arrives.</td><td>Measured (PO)</td></tr>
<tr><td>7</td><td>Scrap or rework event</td><td>Operator or inspector, at the cell terminal</td><td>Quantity, operation and a reason code from the list. Scrapped pieces cost the job their material; rework hours post under the rework code.</td><td>Measured (issue, terminal)</td></tr>
<tr><td>8</td><td>Close-out</td><td>Controller, weekly</td><td>The close-out screen: final variance by element, contribution, markup on cost and margin on price, the drivers in plain words, and the list of any element that is estimated or unrepairable.</td><td></td></tr>
</tbody></table>

<p><b>Where the estimate comes from.</b> A quote is priced per part number at several quantity breaks (for example 25, 50, 100 and 250 pieces). <b>New quoted work</b> takes the quote line's estimate at the ordered quantity: the ERP picks the break nearest the ordered quantity and applies its figures per piece, so a quantity between breaks carries a small, known error from setup amortized at the break's quantity. <b>Repeat parts</b> release against a standing price, not a new quote, and take the current-cost estimate the pipeline computes monthly for every repeat part: today's material prices, the work-center rate pools and the measured cycle and setup times on the routing, at the released quantity. <b>Own products</b> take the standard cost on the part, which the controller reviews each quarter against current cost.</p>

<h2>2. When a scan or a record is missing</h2>
<p>Nothing is filled in by hand. If an operation has no scan, no terminal record and no machine hours by the time the next operation starts, the reporting layer costs it at the routing standard and tags the element <b>estimated</b>. The tag stays on the job; it is not cleared by a later correction unless the transaction is found and posted. A clock record that cannot be trusted (left open across a shift with no machine data behind it, or charged to a job whose routing does not fit) is tagged <b>unrepairable</b> and its hours are shown but not relied on.</p>
<p>The cell lead sees the missing scans for the cell each morning on the coverage screen and chases them that day. A missing scan found within the week is posted with its true times; after that it stays estimated.</p>

<h2>3. How coverage is reported</h2>
<p>Coverage is the share of a job's cost that rests on a transaction rather than on a standard. It is reported for every job on its cost screens, and weekly by work center for the production manager. On completed jobs released since the process went live it stands at <b>{pct(last['measured_cost_share'], 0)}</b> measured, {pct(last['fallback_share'], 0)} estimated; scan coverage at the secondary operations reached <b>{pct(scan['scan_coverage'], 0)}</b> in week {int(scan['engagement_week'])} and is expected to plateau near ninety percent. The remainder is named on each job: which operation, which element, and why.</p>
<p>Coverage below 85% on a job holds the job out of the margin reports until the cell lead has reviewed it. Coverage by work center is reviewed weekly; a cell below 85% for two weeks running is raised with the production manager.</p>

<h2>4. The monthly repricing review</h2>
<p>On the first Tuesday of the month the controller opens the repricing queue: every repeat part against its current cost at today's material prices, the work-center pool rates and the measured standards, with the gap to target on annual volume and what moved since the part was last quoted. The controller and the owner take the parts below cost plus target in order of the annual gap and decide each one: <b>reprice</b> to current cost plus the target markup (the customer is notified with the cost basis), <b>hold</b> with a reason and a date, or <b>exit</b> at the next release. The decision, the new price and the rationale are recorded on the queue. A held part comes back the following month until it is repriced or exited.</p>
<p>The standing price on a repeat part changes only through this review. The annual across-the-board letter is retired.</p>

<h2>5. Owners and cadence</h2>
<table><thead><tr><th>Activity</th><th>Owner</th><th>When</th></tr></thead><tbody>
<tr><td>Close-out review of completed jobs; variance drivers on any job more than 15% over estimate</td><td>Controller, with the estimator</td><td>Weekly</td></tr>
<tr><td>Missing-scan and auto-closed record review</td><td>Cell leads</td><td>Daily</td></tr>
<tr><td>Coverage by work center</td><td>Production manager</td><td>Weekly</td></tr>
<tr><td>Repricing review</td><td>Controller and owner</td><td>Monthly</td></tr>
<tr><td>Estimate accuracy by element, against the month's closed jobs</td><td>Estimator and controller</td><td>Monthly</td></tr>
<tr><td>Routing standard refresh from machine-measured cycles; the estimator reviews each change</td><td>Estimator and production manager</td><td>Quarterly</td></tr>
<tr><td>Work-center rate pool refresh from the rate history and machine hours</td><td>Controller</td><td>Quarterly</td></tr>
<tr><td>Scrap reason review</td><td>Quality manager</td><td>Monthly</td></tr>
</tbody></table>
</div>
"""
    crumb = '<span>Reporting</span> &rsaquo; <span>Job Cost</span> &rsaquo; Process Document'
    return chrome("Job Costing Process", "Reporting", crumb, "R. Alvarez (Controller)", "Process document", body)


def run():
    d = load()
    _creation, progress, closeout = pick_jobs(d)
    (DOCS / "erp").mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(job_progress(d, progress), encoding="utf-8")
    (DOCS / "erp" / "job_closeout.html").write_text(job_closeout(d, closeout), encoding="utf-8")
    html, (n_below, n_cost, gap, rec) = repricing_queue(d)
    (DOCS / "erp" / "repricing_queue.html").write_text(html, encoding="utf-8")
    (DOCS / "erp" / "process.html").write_text(process_doc(d), encoding="utf-8")
    print(f"ERP screens written: in progress {progress['job_id']} (coverage {progress['coverage']:.0%}), "
          f"close-out {closeout['job_id']} (variance {closeout['variance_total']:+,.0f}); queue {n_below} below target, {n_cost} below cost, "
          f"gap ${gap:,.0f}, recovered ${rec:,.0f}")


if __name__ == "__main__":
    run()
