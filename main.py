# main.py — EMMA Model Service (Demo Projections)
# Purpose: Provide stable, numeric demo payloads so the app can summarize results now.
# No external dependencies other than FastAPI itself.

from fastapi import FastAPI, Request
from datetime import datetime

app = FastAPI()

# -------- helpers --------
def make_projection(years:int=3):
    """
    Returns a compact projection suitable for EMMA's current chat summary.
    - yearly_totals.* fields are the ones chat.js reads today
    - by_year is included for future UI charts; safe to ignore
    """
    # Demo baselines
    starts   = 121 if years >= 1 else 40
    actives  = 95  if years >= 1 else 30
    compl    = 18  if years >= 1 else 6
    revenue  = 1_800_000 if years == 3 else (620_000 if years == 1 else 3_200_000)

    by_year = {}
    if years == 1:
        by_year = {
            "Y1": {"starts": starts, "actives_avg": actives, "completions": compl, "revenue_total": revenue}
        }
    elif years == 3:
        by_year = {
            "Y1": {"starts": 121, "actives_avg": 95, "completions": 18, "revenue_total": 1_800_000//3},
            "Y2": {"starts": 127, "actives_avg": 104,"completions": 22, "revenue_total": 1_800_000//3},
            "Y3": {"starts": 133, "actives_avg": 111,"completions": 25, "revenue_total": 1_800_000//3},
        }
    else:  # 5 year demo
        by_year = {
            "Y1": {"starts": 121, "actives_avg": 95,  "completions": 18, "revenue_total": 620_000},
            "Y2": {"starts": 127, "actives_avg": 104, "completions": 22, "revenue_total": 650_000},
            "Y3": {"starts": 133, "actives_avg": 111, "completions": 25, "revenue_total": 690_000},
            "Y4": {"starts": 138, "actives_avg": 118, "completions": 27, "revenue_total": 720_000},
            "Y5": {"starts": 142, "actives_avg": 125, "completions": 29, "revenue_total": 740_000},
        }
        revenue = sum(y["revenue_total"] for y in by_year.values())

    return {
        "ok": True,
        "yearly_totals": {
            "starts": starts,
            "actives_avg": actives,
            "completions": compl,
            "revenue_total": revenue,
            "by_year": by_year
        },
        "explain": "Demo projection: starts distributed by online seasonality; term persistence ~0.88 per 8-week term.",
        "sources": ["Census/ACS (guardrails)", "EDDY priors"]
    }

def parse_target(label: str):
    """Parse season labels like 'Spring 2026' → datetime (approx mid-season)."""
    if not label:
        return None
    t = label.lower().strip()
    # YYYY-MM
    try:
        if len(t) == 7 and t[4] == "-":
            return datetime(int(t[:4]), int(t[-2:]), 1)
    except:
        pass
    # seasons
    m = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 1}
    for k,v in m.items():
        if t.startswith(k) and len(t.split()) == 2:
            y = int(t.split()[1])
            return datetime(y, v, 1)
    return None

def months_diff(a: datetime, b: datetime) -> int:
    """Whole months from a to b (floor)."""
    y = b.year - a.year
    m = b.month - a.month
    total = y*12 + m
    if b.day < a.day:
        total -= 1
    return max(0, total)

# -------- base routes --------
@app.get("/")
def root():
    return {"greeting":"Hello, World","message":"Welcome to EMMA’s model service!"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": "v1.0.1-demo"}

# -------- projections --------
@app.post("/projection_1yr")
async def projection_1yr():
    return make_projection(1)

@app.post("/projection_3yr")
async def projection_3yr():
    return make_projection(3)

@app.post("/projection_5yr")
async def projection_5yr():
    return make_projection(5)

# -------- sensitivity (demo) --------
@app.post("/sensitivity")
async def sensitivity():
    return {
        "ok": True,
        "scenarios": [
            {"label": "+1pp_retention", "delta_revenue_total": 190000, "explain": "Lower term loss lifts actives across cohorts."},
            {"label": "+10pct_starts",   "delta_revenue_total": 210000, "explain": "More starts increase cumulative actives."},
            {"label": "-10pct_tuition",  "delta_revenue_total": -180000,"explain": "Lower price reduces gross tuition (no elasticity modeled yet)."}
        ],
        "explain": "Demo sensitivity deltas. Replace with real matrix outputs in Phase 3."
    }

# -------- timeline check (demo) --------
@app.post("/timeline_check")
async def timeline_check(req: Request):
    j = await req.json()
    today = j.get("today") or datetime.utcnow().strftime("%Y-%m-%d")
    target_start = j.get("target_start") or ""
    assumptions = j.get("assumptions") or {}
    approval = int(assumptions.get("approval_months", 6))
    marketing = int(assumptions.get("marketing_ramp", 3))
    admissions = int(assumptions.get("admissions_lead", 3))
    min_runway = approval + marketing + admissions

    try:
        td = datetime.strptime(today, "%Y-%m-%d")
    except:
        td = datetime.utcnow()
    tgt = parse_target(target_start)
    if not tgt:
        return {
            "ok": True,
            "months_to_launch": None,
            "status": "unknown",
            "message": "Timeline unknown (unrecognized target).",
            "explain": f"Minimum runway ≈ {min_runway}m (approval {approval} + marketing {marketing} + admissions {admissions}).",
            "sources": ["EDDY priors", "Accreditation manuals"]
        }

    months = months_diff(td, tgt)
    status = "feasible" if months >= min_runway else "tight"
    season = target_start or f"{tgt.year}-{tgt.month:02d}"
    msg = f"{season} leaves ~{months} months — {'feasible' if status=='feasible' else 'tight for approval + marketing'}."

    return {
        "ok": True,
        "months_to_launch": months,
        "status": status,
        "message": msg,
        "explain": f"Minimum runway ≈ {min_runway}m (approval {approval} + marketing {marketing} + admissions {admissions}).",
        "sources": ["EDDY priors", "Accreditation manuals"]
    }
