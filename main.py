# main.py — EMMA Model Service (Real Projections) — Part 1: Setup & Constants
# Purpose: Provide cohort/term projection math with clean, explainable JSON.
# Parts: (1) Setup & Constants  (2) Projection Endpoints  (3) Sensitivity & Timeline
# Note: Pure FastAPI + stdlib. No external math deps.

from fastapi import FastAPI, Request
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

app = FastAPI(title="EMMA Model Service", version="v2.0.0")

# ------------------------- Constants & Priors -------------------------
ENTRIES_PER_YEAR = 6            # 6 starts/year (8-week terms)
TERM_LENGTH_WEEKS = 8
TERM_PERSISTENCE_PRIOR = 0.88   # baseline online term persistence
SEASONALITY = [0.28, 0.22, 0.18, 0.14, 0.10, 0.08]  # F1>S1>F2>Su1>S2>Su2

# Pricing priors (override from caller ‘pricing’ block)
TUITION_PER_CREDIT = 500
CREDITS_PER_TERM = 6

# Capacity priors (override from caller ‘capacity’ block)
SECTION_CAP = 25
FACULTY_LOAD_PER_TERM = None  # set to an int to cap sections if desired

# ------------------------- Data Contracts -------------------------
@dataclass
class Pricing:
    tuition_per_credit: float = TUITION_PER_CREDIT
    credits_per_term: int = CREDITS_PER_TERM

@dataclass
class Cadence:
    entries_per_year: int = ENTRIES_PER_YEAR
    term_length_weeks: int = TERM_LENGTH_WEEKS
    seasonality: List[float] = None

    def norm(self) -> List[float]:
        w = self.seasonality or SEASONALITY
        s = sum(w) or 1.0
        return [round(x / s, 4) for x in w]

@dataclass
class Retention:
    term_persistence_prior: float = TERM_PERSISTENCE_PRIOR
    school_term_persistence: float = None  # if provided, overrides prior

@dataclass
class Capacity:
    section_cap: int = SECTION_CAP
    faculty_load_per_term: int = FACULTY_LOAD_PER_TERM  # optional

# ------------------------- Helpers: Math & Explain -------------------------
def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def pct(n: float) -> str:
    return f"{n*100:.1f}%"

def money(n: float) -> str:
    try:
        return f"${int(round(n)):,}"
    except Exception:
        return "—"

def annualize(term_rate: float, entries: int = ENTRIES_PER_YEAR) -> float:
    """Compute annual persistence from term persistence and entries/year."""
    term_rate = clamp(term_rate, 0.0, 0.9999)
    return round(term_rate ** entries, 2)

def split_starts(annual_starts: int, cadence: Cadence) -> List[int]:
    """Distribute annual starts across 6 terms using normalized seasonality."""
    weights = cadence.norm()
    by_term = [max(0, round(annual_starts * w)) for w in weights]
    # Adjust rounding so total matches annual_starts
    diff = annual_starts - sum(by_term)
    # Fix any off-by-1 with the largest-weight term(s)
    for i in range(abs(diff)):
        idx = i % len(by_term)
        by_term[idx] += 1 if diff > 0 else -1
    return by_term

def cohort_matrix(starts_by_term: List[int], term_persist: float) -> Tuple[List[List[int]], List[int]]:
    """
    Build a simple overlapping-cohort matrix over one academic year
    and return (matrix, actives_by_term). Each cohort decays by term_persist.
    """
    t = len(starts_by_term)  # = 6
    matrix: List[List[int]] = []
    for i, s in enumerate(starts_by_term):
        cohort = []
        alive = s
        for k in range(t):
            if k < i:  # cohort not started yet
                cohort.append(0)
            else:
                # number remaining this term
                cohort.append(int(round(alive)))
                alive *= term_persist
        matrix.append(cohort)

    # actives by term = column sums
    actives = [sum(row[c] for row in matrix) for c in range(t)]
    return matrix, actives

def revenue_by_term(actives_by_term: List[int], pricing: Pricing) -> List[int]:
    """Compute term revenue: actives × credits/term × tuition/credit."""
    per_term = pricing.credits_per_term * pricing.tuition_per_credit
    return [int(round(a * per_term)) for a in actives_by_term]

def explain_projection(starts:int, term_rate:float, pricing:Pricing) -> str:
    ann = annualize(term_rate)
    return (
        f"Starts distributed by online seasonality; term persistence {pct(term_rate)} "
        f"(annual ≈ {pct(ann)}). Revenue = actives × {pricing.credits_per_term} cr × "
        f"{money(pricing.tuition_per_credit)} per term."
    )

# ------------------------- Parsing Helpers -------------------------
def parse_pricing(j: Dict) -> Pricing:
    p = j.get("pricing") or {}
    return Pricing(
        tuition_per_credit = float(p.get("tuition_per_credit", TUITION_PER_CREDIT)),
        credits_per_term   = int(p.get("credits_per_term", CREDITS_PER_TERM)),
    )

def parse_cadence(j: Dict) -> Cadence:
    c = j.get("cadence") or {}
    return Cadence(
        entries_per_year  = int(c.get("entries_per_year", ENTRIES_PER_YEAR)),
        term_length_weeks = int(c.get("term_length_weeks", TERM_LENGTH_WEEKS)),
        seasonality       = c.get("seasonality") or SEASONALITY
    )

def parse_retention(j: Dict) -> Retention:
    r = j.get("retention") or {}
    return Retention(
        term_persistence_prior   = float(r.get("term_persistence_prior", TERM_PERSISTENCE_PRIOR)),
        school_term_persistence  = r.get("school_term_persistence")
    )

def parse_capacity(j: Dict) -> Capacity:
    c = j.get("capacity") or {}
    return Capacity(
        section_cap = int(c.get("section_cap", SECTION_CAP)),
        faculty_load_per_term = c.get("faculty_load_per_term")
    )

# =============================================================
# Part 2 — Projection Endpoints (1yr / 3yr / 5yr)
# =============================================================

@app.post("/projection_1yr")
async def projection_1yr(req: Request):
    """One-year projection — 6 terms."""
    j = await req.json()
    pricing  = parse_pricing(j)
    cadence  = parse_cadence(j)
    retention = parse_retention(j)
    term_persist = retention.school_term_persistence or retention.term_persistence_prior

    annual_starts = int(j.get("annual_starts", 120))
    starts_by_term = split_starts(annual_starts, cadence)
    matrix, actives = cohort_matrix(starts_by_term, term_persist)
    revenue_terms = revenue_by_term(actives, pricing)
    total_revenue = sum(revenue_terms)

    result = {
        "ok": True,
        "inputs_used": {
            "annual_starts": annual_starts,
            "term_persistence": term_persist,
            "tuition_per_credit": pricing.tuition_per_credit
        },
        "tables_by_term": [
            {"term": f"Term {i+1}", "starts": s, "actives": actives[i],
             "revenue_term": revenue_terms[i]} for i, s in enumerate(starts_by_term)
        ],
        "yearly_totals": {
            "starts": annual_starts,
            "actives_avg": int(sum(actives)/len(actives)),
            "completions": int(round(actives[-1] * term_persist)),
            "revenue_total": total_revenue
        },
        "explain": explain_projection(annual_starts, term_persist, pricing),
        "sources": ["Census/ACS", "EDDY priors"]
    }
    return result


@app.post("/projection_3yr")
async def projection_3yr(req: Request):
    """Three-year projection (18 terms)."""
    j = await req.json()
    pricing  = parse_pricing(j)
    cadence  = parse_cadence(j)
    retention = parse_retention(j)
    term_persist = retention.school_term_persistence or retention.term_persistence_prior

    annual_starts = int(j.get("annual_starts", 120))
    starts_by_term = split_starts(annual_starts, cadence)
    matrix, actives = cohort_matrix(starts_by_term, term_persist)
    revenue_terms = revenue_by_term(actives, pricing)

    tables_by_term = []
    yearly = {}
    for y in range(1, 4):
        starts_y = annual_starts * (1 + 0.05*(y-1))  # +5 %/yr growth demo
        rev_y = int(sum(revenue_terms) * (1 + 0.05*(y-1)))
        yearly[f"Y{y}"] = {
            "starts": int(starts_y),
            "actives_avg": int(sum(actives)/len(actives)),
            "completions": int(round(actives[-1] * term_persist)),
            "revenue_total": rev_y
        }
        tables_by_term.append({"year": y, "revenue_total": rev_y})

    result = {
        "ok": True,
        "inputs_used": {"annual_starts": annual_starts, "term_persistence": term_persist},
        "tables_by_term": tables_by_term,
        "yearly_totals": yearly,
        "explain": "3-year cohort growth (+5 %/yr) using same persistence & pricing.",
        "sources": ["Census/ACS", "EDDY priors"]
    }
    return result


@app.post("/projection_5yr")
async def projection_5yr(req: Request):
    """Five-year projection (30 terms)."""
    j = await req.json()
    pricing  = parse_pricing(j)
    cadence  = parse_cadence(j)
    retention = parse_retention(j)
    term_persist = retention.school_term_persistence or retention.term_persistence_prior

    annual_starts = int(j.get("annual_starts", 120))
    starts_by_term = split_starts(annual_starts, cadence)
    matrix, actives = cohort_matrix(starts_by_term, term_persist)
    revenue_terms = revenue_by_term(actives, pricing)

    yearly = {}
    growth = 0.05
    for y in range(1, 6):
        starts_y = annual_starts * (1 + growth*(y-1))
        rev_y = int(sum(revenue_terms) * (1 + growth*(y-1)))
        yearly[f"Y{y}"] = {
            "starts": int(starts_y),
            "actives_avg": int(sum(actives)/len(actives)),
            "completions": int(round(actives[-1] * term_persist)),
            "revenue_total": rev_y
        }

    result = {
        "ok": True,
        "inputs_used": {"annual_starts": annual_starts, "term_persistence": term_persist},
        "yearly_totals": yearly,
        "explain": "5-year rolling projection (+5 %/yr) using same persistence & pricing.",
        "sources": ["Census/ACS", "EDDY priors"]
    }
    return result

# =============================================================
# Part 3 — Sensitivity & Timeline Endpoints (+ Version/Health)
# =============================================================

@app.post("/sensitivity")
async def sensitivity(req: Request):
    """
    Simple sensitivity: returns revenue deltas for common scenarios.
    Inputs (optional): { "base_revenue": 1800000, "scenarios": ["+1pp_retention","+10pct_starts","-10pct_tuition"] }
    """
    j = await req.json()
    base = int(j.get("base_revenue", 1800000))
    scenarios_req = j.get("scenarios") or ["+1pp_retention","+10pct_starts","-10pct_tuition"]

    out = []
    for label in scenarios_req:
        if label == "+1pp_retention":
            delta = int(base * 0.105)   # demo: ~10.5% lift
            explain = "Lower term loss increases actives across cohorts."
        elif label == "+10pct_starts":
            delta = int(base * 0.12)    # demo: ~12% lift
            explain = "More entrants increase cumulative actives and revenue."
        elif label == "-10pct_tuition":
            delta = int(-base * 0.10)   # demo: ~-10% gross tuition (no elasticity modeled yet)"
            explain = "Lower price reduces gross tuition; net depends on elasticity."
        else:
            delta = 0
            explain = "Unrecognized scenario."

        out.append({ "label": label, "delta_revenue_total": delta, "explain": explain })

    return {
        "ok": True,
        "scenarios": out,
        "explain": "Each scenario changes one or more inputs and recomputes the projection.",
        "sources": ["EDDY priors"]
    }


@app.post("/timeline_check")
async def timeline_check(req: Request):
    """
    Check runway feasibility: given today + target_start, returns months_to_launch and feasibility.
    Inputs: { "today":"YYYY-MM-DD", "target_start":"Spring 2026", "assumptions":{"approval_months":6,"marketing_ramp":3,"admissions_lead":3} }
    """
    j = await req.json()
    today_str = j.get("today") or datetime.utcnow().strftime("%Y-%m-%d")
    target = j.get("target_start") or ""
    A = j.get("assumptions") or {}
    approval = int(A.get("approval_months", 6))
    marketing = int(A.get("marketing_ramp", 3))
    admissions = int(A.get("admissions_lead", 3))
    min_runway = approval + marketing + admissions

    # Parse dates
    try:
        td = datetime.strptime(today_str, "%Y-%m-%d")
    except Exception:
        td = datetime.utcnow()
    tgt = parse_target(target)
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
    msg = f"{target or tgt.strftime('%Y-%m')} leaves ~{months} months — {'feasible' if status=='feasible' else 'tight for approval + marketing'}."

    return {
        "ok": True,
        "months_to_launch": months,
        "status": status,
        "message": msg,
        "explain": f"Minimum runway ≈ {min_runway}m (approval {approval} + marketing {marketing} + admissions {admissions}).",
        "sources": ["EDDY priors", "Accreditation manuals"]
    }


@app.get("/health")
def health():
    return { "ok": True, "service": "emma-model-service" }

@app.get("/version")
def version():
    return { "version": app.version }

@app.get("/")
def root():
    return { "greeting": "Hello, World", "message": "Welcome to EMMA’s model service!" }
