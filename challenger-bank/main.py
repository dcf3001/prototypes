"""
Challenger Bank — FastAPI application (Phase 2: UI + data API).
Serves Jinja2 HTML pages and JSON endpoints for all risk domains.
Run: uvicorn main:app --reload --port 3003
"""
import os
import json
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from db import get_db, init_db, DB_PATH
from generators.seed_all import seed


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 10_000:
        print("Database empty — running seed …")
        seed()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Challenger Bank Risk Platform",
    description="Synthetic investment bank risk data API",
    version="0.2.0",
    lifespan=lifespan,
)

# Static files (optional — create the directory if you want to serve assets)
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# ── Jinja2 filters ────────────────────────────────────────────────────────────

RATING_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
                "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
                "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"]


def rating_badge(rating: str) -> str:
    if not rating:
        return "badge-blue"
    r = rating.upper().strip()
    if r.startswith("AAA"):
        return "badge-aaa"
    if r.startswith("AA"):
        return "badge-aa"
    if r.startswith("A") and not r.startswith("AM"):
        return "badge-a"
    if r.startswith("BBB"):
        return "badge-bbb"
    if r.startswith("BB"):
        return "badge-bb"
    if r.startswith("B"):
        return "badge-b"
    if r.startswith("CCC") or r.startswith("CC") or r in ("C", "D"):
        return "badge-ccc"
    return "badge-blue"


templates.env.filters["rating_badge"] = rating_badge
templates.env.filters["abs"]   = abs
templates.env.filters["min"]   = min
templates.env.filters["max"]   = max
templates.env.filters["round"] = round


# ── DB helpers ────────────────────────────────────────────────────────────────

def _rows(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _one(conn, sql, params=()):
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


# ── HTML pages ────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard(request: Request):
    conn = get_db()

    # Summary stats for KPI cards
    credit_rwa = conn.execute(
        "SELECT COALESCE(SUM(rwa),0) FROM credit_facilities WHERE status='Active'"
    ).fetchone()[0]
    total_el = conn.execute(
        "SELECT COALESCE(SUM(expected_loss),0) FROM credit_facilities WHERE status='Active'"
    ).fetchone()[0]
    total_drawn = conn.execute("""
        SELECT COALESCE(SUM(f.drawn_amount * CASE c.currency
            WHEN 'USD' THEN 1.0 WHEN 'GBP' THEN 1.27
            WHEN 'CNY' THEN 0.140 WHEN 'BRL' THEN 0.196 WHEN 'ZAR' THEN 0.054
            ELSE 1.0 END), 0)
        FROM credit_facilities f JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status='Active'
    """).fetchone()[0]
    active_fac = conn.execute("SELECT COUNT(*) FROM credit_facilities WHERE status='Active'").fetchone()[0]
    live_trades = conn.execute("SELECT COUNT(*) FROM trades WHERE status='Live'").fetchone()[0]
    cp_count = conn.execute("SELECT COUNT(*) FROM counterparties").fetchone()[0]
    market_var = conn.execute(
        "SELECT var_1d_99 FROM var_history WHERE desk IS NULL ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    market_var = market_var[0] if market_var else 0
    total_cva = conn.execute("""
        SELECT COALESCE(SUM(cva_usd),0) FROM cva_history
        WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM cva_history)
    """).fetchone()[0]
    saccr_rwa = conn.execute("""
        SELECT COALESCE(SUM(rwa_usd),0) FROM sa_ccr
        WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM sa_ccr)
    """).fetchone()[0]

    s = {
        "credit_rwa_usd_bn":          round(credit_rwa, 2),
        "saccr_rwa_usd_bn":           round(saccr_rwa, 2),
        "market_var_1d_99_usd_m":     round(market_var, 1),
        "total_cva_usd_m":            round(total_cva, 2),
        "total_drawn_lending_usd_bn": round(total_drawn, 2),
        "active_facilities":          active_fac,
        "total_expected_loss_usd_bn": round(total_el, 4),
        "counterparty_count":         cp_count,
        "live_trades":                live_trades,
    }

    # EAD by sector (chart)
    sector_data = _rows(conn, """
        SELECT c.sector, SUM(f.ead) AS total_ead
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status='Active' GROUP BY c.sector ORDER BY total_ead DESC
    """)

    # Rating distribution by EAD (chart)
    rating_data = _rows(conn, """
        SELECT c.internal_rating, SUM(f.ead) AS total_ead
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status='Active' GROUP BY c.internal_rating ORDER BY c.internal_rating
    """)

    # VaR by desk (chart)
    latest_var_date = conn.execute("SELECT MAX(snapshot_date) FROM var_history").fetchone()[0]
    desk_var = _rows(conn, """
        SELECT desk, var_1d_99 FROM var_history
        WHERE snapshot_date=? AND desk IS NOT NULL ORDER BY var_1d_99 DESC
    """, (latest_var_date,))

    # Scenario P&L (chart)
    scenario_pnl = _rows(conn, """
        SELECT sc.scenario_name, COALESCE(SUM(sr.pnl_impact_usd),0) AS total_pnl
        FROM scenarios sc
        LEFT JOIN scenario_results sr ON sr.scenario_id=sc.id AND sr.desk IS NULL
        GROUP BY sc.id, sc.scenario_name ORDER BY sc.id
    """)

    # Country utilisation (chart)
    country_util = _rows(conn,
        "SELECT country_iso2, utilisation_pct FROM country_limits ORDER BY country_iso2")

    # Credit events (table)
    events = _rows(conn, """
        SELECT e.*, c.name AS counterparty_name, c.internal_rating
        FROM credit_events e JOIN counterparties c ON c.id=e.counterparty_id
        ORDER BY e.event_date DESC LIMIT 10
    """)

    # Top 15 facilities by EAD (table) — template uses top_facilities
    top_facilities = _rows(conn, """
        SELECT f.counterparty_id, f.ead, f.expected_loss, f.rwa, f.pd,
               c.name AS counterparty_name, c.country_iso2, c.sector, c.internal_rating
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status='Active' ORDER BY f.ead DESC LIMIT 15
    """)

    conn.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active":  "dashboard",
        "s":       s,
        # Charts
        "sector_labels":  [r["sector"] for r in sector_data],
        "sector_values":  [round(r["total_ead"], 2) for r in sector_data],
        "rating_labels":  [r["internal_rating"] for r in rating_data],
        "rating_values":  [round(r["total_ead"], 2) for r in rating_data],
        "var_desks":      [r["desk"] for r in desk_var],
        "var_values":     [round(r["var_1d_99"], 1) for r in desk_var],
        "sc_labels":      [r["scenario_name"] for r in scenario_pnl],
        "sc_values":      [round(r["total_pnl"], 1) for r in scenario_pnl],
        "country_labels": [r["country_iso2"] for r in country_util],
        "country_utils":  [round(r["utilisation_pct"], 1) for r in country_util],
        # Tables
        "events":         events,
        "top_facilities": top_facilities,
    })


@app.get("/credit", include_in_schema=False)
def credit_page(request: Request):
    conn = get_db()

    port = {
        "total_ead": round(conn.execute("SELECT COALESCE(SUM(ead),0) FROM credit_facilities WHERE status='Active'").fetchone()[0], 1),
        "total_el":  round(conn.execute("SELECT COALESCE(SUM(expected_loss),0) FROM credit_facilities WHERE status='Active'").fetchone()[0], 4),
        "total_rwa": round(conn.execute("SELECT COALESCE(SUM(rwa),0) FROM credit_facilities WHERE status='Active'").fetchone()[0], 1),
        "avg_pd":    round(conn.execute("SELECT AVG(pd) FROM credit_facilities WHERE status='Active'").fetchone()[0] or 0, 5),
        "fac_count": conn.execute("SELECT COUNT(*) FROM credit_facilities WHERE status='Active'").fetchone()[0],
        "watchlist": conn.execute("SELECT COUNT(*) FROM credit_facilities WHERE status='Watchlist'").fetchone()[0],
    }

    sector_data = _rows(conn, """
        SELECT c.sector, SUM(f.ead) AS total_ead
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status='Active' GROUP BY c.sector ORDER BY total_ead DESC
    """)
    rating_data = _rows(conn, """
        SELECT c.internal_rating, SUM(f.ead) AS total_ead
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status='Active' GROUP BY c.internal_rating ORDER BY c.internal_rating
    """)
    facilities = _rows(conn, """
        SELECT f.*, c.name AS counterparty_name, c.country_iso2,
               c.internal_rating, c.sector
        FROM credit_facilities f JOIN counterparties c ON c.id=f.counterparty_id
        WHERE f.status IN ('Active','Watchlist') ORDER BY f.ead DESC
    """)
    countries = [r["country_iso2"] for r in _rows(conn, "SELECT DISTINCT country_iso2 FROM counterparties ORDER BY country_iso2")]
    sectors   = [r["sector"]       for r in _rows(conn, "SELECT DISTINCT sector FROM counterparties ORDER BY sector")]

    conn.close()
    return templates.TemplateResponse("credit.html", {
        "request": request,
        "active":  "credit",
        "port":    port,
        "sector_labels": [r["sector"]           for r in sector_data],
        "sector_values": [round(r["total_ead"],2) for r in sector_data],
        "rating_labels": [r["internal_rating"]  for r in rating_data],
        "rating_values": [round(r["total_ead"],2) for r in rating_data],
        "facilities": facilities,
        "countries":  countries,
        "sectors":    sectors,
    })


@app.get("/market", include_in_schema=False)
def market_page(request: Request):
    conn = get_db()

    latest_date = conn.execute("SELECT MAX(snapshot_date) FROM var_history").fetchone()[0]

    pv = _one(conn, "SELECT * FROM var_history WHERE desk IS NULL AND snapshot_date=?", (latest_date,))
    portfolio_var = {
        "var_1d_99":   round(pv["var_1d_99"],   1) if pv else 0,
        "es_1d_97_5":  round(pv["es_1d_97_5"],  1) if pv else 0,
        "var_10d_99":  round(pv["var_10d_99"],  1) if pv else 0,
        "stressed_var": round(pv["stressed_var"], 1) if pv else 0,
    }

    desk_vars = _rows(conn, """
        SELECT desk, var_1d_99, es_1d_97_5, var_10d_99, stressed_var
        FROM var_history WHERE snapshot_date=? AND desk IS NOT NULL
        ORDER BY var_1d_99 DESC
    """, (latest_date,))

    var_trend = list(reversed(_rows(conn, """
        SELECT snapshot_date, var_1d_99 FROM var_history
        WHERE desk IS NULL ORDER BY snapshot_date DESC LIMIT 24
    """)))

    # Monthly P&L by desk for stacked chart
    monthly_pnl = _rows(conn, """
        SELECT pnl_date, desk, daily_pnl FROM pnl_attribution
        ORDER BY pnl_date, desk
    """)
    desk_names = sorted(set(r["desk"] for r in monthly_pnl))
    dates_set  = sorted(set(r["pnl_date"] for r in monthly_pnl))[-12:]
    pnl_map    = {(r["pnl_date"], r["desk"]): r["daily_pnl"] for r in monthly_pnl}
    pnl_desk_data = {
        "dates": dates_set,
        "desks": desk_names,
        "values": [[round(pnl_map.get((d, dk), 0), 1) for d in dates_set] for dk in desk_names],
    }

    # Factor attribution totals (last 12 months)
    fa = _one(conn, """
        SELECT SUM(rates_pnl) AS rates, SUM(fx_pnl) AS fx,
               SUM(credit_pnl) AS credit, SUM(equity_pnl) AS equity,
               SUM(theta_pnl) AS theta, SUM(other_pnl) AS other
        FROM pnl_attribution
        WHERE pnl_date >= (SELECT DATE(MAX(pnl_date),'-12 months') FROM pnl_attribution)
    """)
    factor_data = {
        "labels": ["Rates", "FX", "Credit", "Equity", "Theta", "Other"],
        "values": [round((fa or {}).get(k) or 0, 1) for k in ["rates","fx","credit","equity","theta","other"]],
    }

    positions = _rows(conn, "SELECT * FROM positions ORDER BY desk, net_notional_usd DESC")
    trades    = _rows(conn, """
        SELECT t.*, c.name AS counterparty_name
        FROM trades t JOIN counterparties c ON c.id=t.counterparty_id
        WHERE t.status='Live' ORDER BY ABS(t.mark_to_market) DESC LIMIT 30
    """)

    conn.close()
    return templates.TemplateResponse("market.html", {
        "request": request,
        "active":        "market",
        "portfolio_var": portfolio_var,
        "latest_date":   latest_date,
        "desk_vars":     desk_vars,
        "desk_labels":      [r["desk"]         for r in desk_vars],
        "desk_var_values":  [round(r["var_1d_99"],1) for r in desk_vars],
        "var_trend_dates":  [r["snapshot_date"][:7] for r in var_trend],
        "var_trend_values": [round(r["var_1d_99"],1) for r in var_trend],
        "pnl_desk_data": pnl_desk_data,
        "factor_data":   factor_data,
        "positions":     positions,
        "trades":        trades,
    })


@app.get("/counterparty", include_in_schema=False)
def counterparty_page(request: Request):
    conn = get_db()

    latest_cva = conn.execute("SELECT MAX(snapshot_date) FROM cva_history").fetchone()[0]
    latest_sa  = "2025-12-31"
    latest_pfe = "2025-12-31"
    latest_me  = conn.execute("SELECT MAX(snapshot_date) FROM mtm_exposure").fetchone()[0]

    totals = {
        "total_cva":    round(conn.execute("SELECT COALESCE(SUM(cva_usd),0) FROM cva_history WHERE snapshot_date=?", (latest_cva,)).fetchone()[0], 2),
        "saccr_rwa":    round(conn.execute("SELECT COALESCE(SUM(rwa_usd),0) FROM sa_ccr WHERE snapshot_date=?", (latest_sa,)).fetchone()[0], 2),
        "gross_pos_mtm": round(conn.execute("SELECT COALESCE(SUM(gross_positive_mtm_usd),0) FROM mtm_exposure WHERE snapshot_date=?", (latest_me,)).fetchone()[0], 1),
        "net_exposure": round(conn.execute("SELECT COALESCE(SUM(current_exposure_usd),0) FROM mtm_exposure WHERE snapshot_date=?", (latest_me,)).fetchone()[0], 1),
    }

    top_cva = _rows(conn, """
        SELECT c.name, cv.cva_usd
        FROM cva_history cv JOIN counterparties c ON c.id=cv.counterparty_id
        WHERE cv.snapshot_date=? ORDER BY cv.cva_usd ASC LIMIT 15
    """, (latest_cva,))

    pfe_rows = _rows(conn, """
        SELECT c.id, c.name, c.internal_rating,
               p.pfe_1m, p.pfe_3m, p.pfe_6m, p.pfe_1y, p.pfe_2y,
               p.pfe_3y, p.pfe_5y, p.pfe_7y, p.pfe_10y
        FROM pfe_profiles p JOIN counterparties c ON c.id=p.counterparty_id
        WHERE p.snapshot_date=? ORDER BY p.pfe_peak DESC LIMIT 10
    """, (latest_pfe,))

    pfe_cps  = [{"name": r["name"], "rating": r["internal_rating"]} for r in pfe_rows]
    pfe_data = [[round(r.get(k) or 0, 1) for k in ["pfe_1m","pfe_3m","pfe_6m","pfe_1y","pfe_2y","pfe_3y","pfe_5y","pfe_7y","pfe_10y"]] for r in pfe_rows]

    ccr_rows = _rows(conn, """
        SELECT c.id, c.name, c.internal_rating, c.country_iso2,
               cv.cva_usd, cv.dva_usd,
               me.gross_positive_mtm_usd, me.net_mtm_usd,
               me.collateral_held_usd, me.current_exposure_usd,
               sa.ead_usd, sa.rwa_usd, pf.pfe_peak,
               ns.agreement_type, ns.csa_in_place
        FROM counterparties c
        LEFT JOIN cva_history cv  ON cv.counterparty_id=c.id AND cv.snapshot_date=?
        LEFT JOIN mtm_exposure me ON me.counterparty_id=c.id AND me.snapshot_date=?
        LEFT JOIN sa_ccr sa       ON sa.counterparty_id=c.id AND sa.snapshot_date=?
        LEFT JOIN pfe_profiles pf ON pf.counterparty_id=c.id AND pf.snapshot_date=?
        LEFT JOIN netting_sets ns ON ns.counterparty_id=c.id
        WHERE cv.cva_usd IS NOT NULL
        ORDER BY cv.cva_usd ASC
    """, (latest_cva, latest_me, latest_sa, latest_pfe))

    conn.close()
    return templates.TemplateResponse("counterparty.html", {
        "request":  request,
        "active":   "counterparty",
        "totals":   totals,
        "cva_labels": [r["name"]             for r in top_cva],
        "cva_values": [round(r["cva_usd"],2) for r in top_cva],
        "pfe_cps":    pfe_cps,
        "pfe_data":   pfe_data,
        "ccr_rows":   ccr_rows,
    })


@app.get("/country", include_in_schema=False)
def country_page(request: Request):
    conn = get_db()

    # Raw limits (all fields)
    raw_limits = _rows(conn, "SELECT * FROM country_limits ORDER BY utilisation_pct DESC")

    # Exposure aggregation by country+type
    exposures = _rows(conn, """
        SELECT country_iso2, exposure_type, SUM(gross_exposure_usd) AS total
        FROM country_exposures WHERE snapshot_date='2025-12-31'
        GROUP BY country_iso2, exposure_type
    """)
    exp_map: dict = {}
    for e in exposures:
        c = e["country_iso2"]
        if c not in exp_map:
            exp_map[c] = {}
        exp_map[c][e["exposure_type"]] = round(e["total"] or 0, 1)

    # Enrich limits with lending_exp + trading_exp
    for lim in raw_limits:
        iso = lim["country_iso2"]
        lim["lending_exp"] = exp_map.get(iso, {}).get("Lending", 0)
        lim["trading_exp"] = exp_map.get(iso, {}).get("Trading", 0)

    # KPI strip — one card per country
    kpi_countries = [{
        "country_name":        lim["country_name"],
        "utilisation_pct":     lim["utilisation_pct"],
        "current_exposure_usd": lim["current_exposure_usd"],
        "approved_limit_usd":  lim["approved_limit_usd"],
        "status":              lim["limit_status"].lower(),
    } for lim in raw_limits]

    # Transfer risk table (with country_name)
    transfer = _rows(conn, """
        SELECT tr.*, cl.country_name
        FROM transfer_risk tr
        JOIN country_limits cl ON cl.country_iso2=tr.country_iso2
        WHERE tr.snapshot_date=(SELECT MAX(snapshot_date) FROM transfer_risk)
        ORDER BY tr.transfer_risk_score DESC
    """)

    # Counterparty exposure table
    cp_exposures = _rows(conn, """
        SELECT c.id, c.name, c.country_iso2, c.sector, c.internal_rating,
               COALESCE(SUM(f.ead)*1000, 0) AS lending_ead_m,
               COALESCE((SELECT SUM(t2.notional_usd)
                         FROM trades t2
                         WHERE t2.counterparty_id=c.id AND t2.status='Live'), 0) AS trade_notional_m
        FROM counterparties c
        LEFT JOIN credit_facilities f ON f.counterparty_id=c.id AND f.status='Active'
        GROUP BY c.id ORDER BY c.country_iso2, lending_ead_m DESC
    """)

    # Chart data — ordered by country_iso2 alphabetically
    ctry_order = sorted(exp_map.keys())
    conn.close()
    return templates.TemplateResponse("country.html", {
        "request":       request,
        "active":        "country",
        "kpi_countries": kpi_countries,
        "limits":        raw_limits,
        "transfer":      transfer,
        "cp_exposures":  cp_exposures,
        "ctry_labels":   ctry_order,
        "ctry_lending":  [exp_map.get(c, {}).get("Lending", 0) for c in ctry_order],
        "ctry_trading":  [exp_map.get(c, {}).get("Trading", 0) for c in ctry_order],
        "ctry_utils":    [round(next((l["utilisation_pct"] for l in raw_limits if l["country_iso2"]==c), 0), 1) for c in ctry_order],
    })


@app.get("/scenarios", include_in_schema=False)
def scenarios_page(request: Request):
    conn = get_db()

    scenarios = _rows(conn, "SELECT * FROM scenarios ORDER BY id")

    # Portfolio P&L per scenario — dict keyed by scenario_id (template uses sc_pnl.get())
    port_rows = _rows(conn, "SELECT scenario_id, pnl_impact_usd FROM scenario_results WHERE desk IS NULL ORDER BY scenario_id")
    sc_pnl = {r["scenario_id"]: round(r["pnl_impact_usd"], 1) for r in port_rows}

    # All desk-level results
    desk_rows = _rows(conn, """
        SELECT scenario_id, desk, pnl_impact_usd, var_breached, notes
        FROM scenario_results WHERE desk IS NOT NULL ORDER BY scenario_id, desk
    """)

    # Group by scenario_id for template (sc_results.get(sc.id, []))
    sc_results: dict = {}
    for r in desk_rows:
        sc_results.setdefault(r["scenario_id"], []).append(r)

    # JS chart data
    sc_names    = [s["scenario_name"] for s in scenarios]
    sc_port_pnl = [sc_pnl.get(s["id"], 0) for s in scenarios]
    sc_desk_data = []
    for s in scenarios:
        rows = sc_results.get(s["id"], [])
        sc_desk_data.append({
            "desks": [r["desk"] for r in rows],
            "pnl":   [round(r["pnl_impact_usd"], 1) for r in rows],
        })

    conn.close()
    return templates.TemplateResponse("scenarios.html", {
        "request":    request,
        "active":     "scenarios",
        "scenarios":  scenarios,
        "sc_pnl":     sc_pnl,
        "sc_results": sc_results,
        "sc_names":     sc_names,
        "sc_port_pnl":  sc_port_pnl,
        "sc_desk_data": sc_desk_data,
    })


@app.get("/counterparty/{cp_id}", include_in_schema=False)
def counterparty_detail(request: Request, cp_id: int):
    conn = get_db()

    cp = _one(conn, """
        SELECT cp.*, c.name AS country_name
        FROM counterparties cp
        LEFT JOIN (
            SELECT DISTINCT country_iso2,
                CASE country_iso2
                    WHEN 'US' THEN 'United States'
                    WHEN 'GB' THEN 'United Kingdom'
                    WHEN 'CN' THEN 'China'
                    WHEN 'BR' THEN 'Brazil'
                    WHEN 'ZA' THEN 'South Africa'
                    ELSE country_iso2
                END AS name
            FROM counterparties
        ) c ON c.country_iso2 = cp.country_iso2
        WHERE cp.id=?
    """, (cp_id,))

    if not cp:
        raise HTTPException(404, "Counterparty not found")

    cp["risk_tags"] = json.loads(cp.get("risk_tags") or "[]")

    # Financials
    financials = _rows(conn,
        "SELECT * FROM financials WHERE counterparty_id=? ORDER BY fiscal_year", (cp_id,))

    # Latest financials
    latest_fin = financials[-1] if financials else {}

    # Rating history
    rating_history = _rows(conn,
        "SELECT * FROM credit_ratings WHERE counterparty_id=? ORDER BY rating_date DESC", (cp_id,))

    # Facilities
    facilities = _rows(conn,
        "SELECT * FROM credit_facilities WHERE counterparty_id=? ORDER BY ead DESC", (cp_id,))

    # Live trades
    trades = _rows(conn,
        "SELECT * FROM trades WHERE counterparty_id=? AND status='Live' ORDER BY ABS(mark_to_market) DESC",
        (cp_id,))

    # Latest PD
    latest_pd_row = _one(conn,
        "SELECT pd_1y FROM pd_history WHERE counterparty_id=? ORDER BY snapshot_date DESC LIMIT 1",
        (cp_id,))
    latest_pd = latest_pd_row["pd_1y"] if latest_pd_row else 0.01

    # Latest CVA
    latest_cva = _one(conn,
        "SELECT * FROM cva_history WHERE counterparty_id=? ORDER BY snapshot_date DESC LIMIT 1",
        (cp_id,))

    # PFE profile
    pfe_row = _one(conn,
        "SELECT * FROM pfe_profiles WHERE counterparty_id=? AND snapshot_date='2025-12-31'",
        (cp_id,))
    pfe_profile = pfe_row
    pfe_values = []
    if pfe_row:
        pfe_values = [
            round(pfe_row.get(k) or 0, 2)
            for k in ["pfe_1m","pfe_3m","pfe_6m","pfe_1y","pfe_2y","pfe_3y","pfe_5y","pfe_7y","pfe_10y"]
        ]

    # PD trend (all history)
    pd_hist = _rows(conn,
        "SELECT snapshot_date, pd_1y FROM pd_history WHERE counterparty_id=? ORDER BY snapshot_date",
        (cp_id,))

    # Chart data
    fin_years   = [f["fiscal_year"] for f in financials]
    fin_rev     = [round(f.get("revenue") or 0, 2) for f in financials]
    fin_ebitda  = [round(f.get("ebitda")  or 0, 2) for f in financials]
    fin_leverage = [round(f.get("net_debt_ebitda") or 0, 2) for f in financials]
    pd_dates    = [r["snapshot_date"][:7] for r in pd_hist]
    pd_values   = [round(r["pd_1y"], 5) for r in pd_hist]

    conn.close()
    return templates.TemplateResponse("counterparty_detail.html", {
        "request": request,
        "active": "credit",
        "cp":            cp,
        "financials":    financials,
        "latest_fin":    latest_fin,
        "rating_history": rating_history,
        "facilities":    facilities,
        "trades":        trades,
        "latest_pd":     latest_pd,
        "latest_cva":    latest_cva,
        "pfe_profile":   pfe_profile,
        "pfe_values":    pfe_values,
        "fin_years":     fin_years,
        "fin_rev":       fin_rev,
        "fin_ebitda":    fin_ebitda,
        "fin_leverage":  fin_leverage,
        "pd_dates":      pd_dates,
        "pd_values":     pd_values,
    })


# ── JSON API ──────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def get_summary():
    conn = get_db()
    credit_rwa = conn.execute(
        "SELECT COALESCE(SUM(rwa),0) FROM credit_facilities WHERE status='Active'"
    ).fetchone()[0]
    total_el = conn.execute(
        "SELECT COALESCE(SUM(expected_loss),0) FROM credit_facilities WHERE status='Active'"
    ).fetchone()[0]
    total_drawn_usd = conn.execute("""
        SELECT COALESCE(SUM(f.drawn_amount * CASE c.currency
            WHEN 'USD' THEN 1.0 WHEN 'GBP' THEN 1.27
            WHEN 'CNY' THEN 0.140 WHEN 'BRL' THEN 0.196 WHEN 'ZAR' THEN 0.054
            ELSE 1.0 END), 0)
        FROM credit_facilities f
        JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status = 'Active'
    """).fetchone()[0]
    market_var = conn.execute("""
        SELECT var_1d_99 FROM var_history WHERE desk IS NULL
        ORDER BY snapshot_date DESC LIMIT 1
    """).fetchone()
    market_var = market_var[0] if market_var else 0
    total_cva = conn.execute("""
        SELECT COALESCE(SUM(cva_usd),0) FROM cva_history
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM cva_history)
    """).fetchone()[0]
    saccr_rwa = conn.execute("""
        SELECT COALESCE(SUM(rwa_usd),0) FROM sa_ccr
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM sa_ccr)
    """).fetchone()[0]
    fac_count  = conn.execute("SELECT COUNT(*) FROM credit_facilities WHERE status='Active'").fetchone()[0]
    trade_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='Live'").fetchone()[0]
    cp_count   = conn.execute("SELECT COUNT(*) FROM counterparties").fetchone()[0]
    conn.close()
    return {
        "counterparty_count":         cp_count,
        "active_facilities":          fac_count,
        "live_trades":                trade_count,
        "total_drawn_lending_usd_bn": round(total_drawn_usd, 3),
        "credit_rwa_usd_bn":          round(credit_rwa, 3),
        "total_expected_loss_usd_bn": round(total_el, 6),
        "market_var_1d_99_usd_m":     round(market_var, 2),
        "total_cva_usd_m":            round(total_cva, 3),
        "saccr_rwa_usd_bn":           round(saccr_rwa, 3),
    }


@app.get("/api/counterparties")
def get_counterparties(
    country: str = Query(None),
    sector:  str = Query(None),
    rating:  str = Query(None),
):
    conn = get_db()
    sql    = "SELECT * FROM counterparties WHERE 1=1"
    params = []
    if country: sql += " AND country_iso2 = ?"; params.append(country.upper())
    if sector:  sql += " AND sector = ?";        params.append(sector)
    if rating:  sql += " AND internal_rating = ?"; params.append(rating)
    sql += " ORDER BY country_iso2, name"
    rows = _rows(conn, sql, params)
    for r in rows:
        r["risk_tags"]   = json.loads(r.get("risk_tags") or "[]")
        r["alert_flags"] = json.loads(r.get("alert_flags") or "[]")
    conn.close()
    return rows


@app.get("/api/counterparties/{cp_id}")
def get_counterparty(cp_id: int):
    conn = get_db()
    rows = _rows(conn, "SELECT * FROM counterparties WHERE id=?", (cp_id,))
    if not rows:
        raise HTTPException(404, "Counterparty not found")
    cp = rows[0]
    cp["risk_tags"]   = json.loads(cp.get("risk_tags") or "[]")
    cp["alert_flags"] = json.loads(cp.get("alert_flags") or "[]")
    cp["financials"]  = _rows(conn, "SELECT * FROM financials WHERE counterparty_id=? ORDER BY fiscal_year", (cp_id,))
    cp["rating_history"] = _rows(conn, "SELECT * FROM credit_ratings WHERE counterparty_id=? ORDER BY rating_date", (cp_id,))
    cp["facilities"]  = _rows(conn, "SELECT * FROM credit_facilities WHERE counterparty_id=?", (cp_id,))
    cp["trades"]      = _rows(conn, "SELECT * FROM trades WHERE counterparty_id=? AND status='Live'", (cp_id,))
    cp["pd_history"]  = _rows(conn, "SELECT * FROM pd_history WHERE counterparty_id=? ORDER BY snapshot_date DESC LIMIT 12", (cp_id,))
    cva = _rows(conn, "SELECT * FROM cva_history WHERE counterparty_id=? ORDER BY snapshot_date DESC LIMIT 1", (cp_id,))
    cp["latest_cva"]  = cva[0] if cva else None
    pfe = _rows(conn, "SELECT * FROM pfe_profiles WHERE counterparty_id=? ORDER BY snapshot_date DESC LIMIT 1", (cp_id,))
    cp["pfe_profile"] = pfe[0] if pfe else None
    conn.close()
    return cp


@app.get("/api/credit/facilities")
def get_facilities(status: str = Query("Active")):
    conn = get_db()
    rows = _rows(conn, """
        SELECT f.*, c.name AS counterparty_name, c.country_iso2,
               c.internal_rating, c.sector
        FROM credit_facilities f
        JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status = ? ORDER BY f.ead DESC
    """, (status,))
    conn.close()
    return rows


@app.get("/api/credit/portfolio")
def get_credit_portfolio():
    conn = get_db()
    by_sector  = _rows(conn, """
        SELECT c.sector, COUNT(f.id) AS facility_count,
               SUM(f.ead) AS total_ead_usd, SUM(f.expected_loss) AS total_el_usd,
               SUM(f.rwa) AS total_rwa_usd, AVG(f.pd) AS avg_pd
        FROM credit_facilities f JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status='Active' GROUP BY c.sector ORDER BY total_ead_usd DESC
    """)
    by_country = _rows(conn, """
        SELECT c.country_iso2, c.country_name,
               COUNT(f.id) AS facility_count,
               SUM(f.ead) AS total_ead_usd, SUM(f.rwa) AS total_rwa_usd
        FROM credit_facilities f JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status='Active' GROUP BY c.country_iso2 ORDER BY total_ead_usd DESC
    """)
    by_rating  = _rows(conn, """
        SELECT c.internal_rating, COUNT(f.id) AS facility_count,
               SUM(f.ead) AS total_ead_usd, SUM(f.expected_loss) AS total_el_usd,
               AVG(f.pd) AS avg_pd
        FROM credit_facilities f JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status='Active' GROUP BY c.internal_rating ORDER BY c.internal_rating
    """)
    conn.close()
    return {"by_sector": by_sector, "by_country": by_country, "by_rating": by_rating}


@app.get("/api/credit/events")
def get_credit_events():
    conn = get_db()
    rows = _rows(conn, """
        SELECT e.*, c.name AS counterparty_name, c.internal_rating
        FROM credit_events e JOIN counterparties c ON c.id = e.counterparty_id
        ORDER BY e.event_date DESC
    """)
    conn.close()
    return rows


@app.get("/api/market/var")
def get_var_history(desk: str = Query(None), months: int = Query(12)):
    conn = get_db()
    if desk:
        rows = _rows(conn, "SELECT * FROM var_history WHERE desk=? ORDER BY snapshot_date DESC LIMIT ?", (desk, months))
    else:
        rows = _rows(conn, "SELECT * FROM var_history WHERE desk IS NULL ORDER BY snapshot_date DESC LIMIT ?", (months,))
    conn.close()
    return rows


@app.get("/api/market/var/latest")
def get_var_latest():
    conn = get_db()
    rows = _rows(conn, """
        SELECT * FROM var_history
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM var_history)
        ORDER BY COALESCE(desk,'ZZZZ')
    """)
    conn.close()
    return rows


@app.get("/api/market/pnl")
def get_pnl(desk: str = Query(None), months: int = Query(12)):
    conn = get_db()
    if desk:
        rows = _rows(conn, "SELECT * FROM pnl_attribution WHERE desk=? ORDER BY pnl_date DESC LIMIT ?", (desk, months))
    else:
        rows = _rows(conn, """
            SELECT pnl_date, SUM(daily_pnl) AS daily_pnl,
                   SUM(rates_pnl) AS rates_pnl, SUM(fx_pnl) AS fx_pnl,
                   SUM(credit_pnl) AS credit_pnl, SUM(equity_pnl) AS equity_pnl,
                   SUM(theta_pnl) AS theta_pnl, SUM(other_pnl) AS other_pnl
            FROM pnl_attribution GROUP BY pnl_date ORDER BY pnl_date DESC LIMIT ?
        """, (months,))
    conn.close()
    return rows


@app.get("/api/market/positions")
def get_positions():
    conn = get_db()
    rows = _rows(conn, "SELECT * FROM positions ORDER BY desk, product")
    conn.close()
    return rows


@app.get("/api/market/trades")
def get_trades(desk: str = Query(None), status: str = Query("Live")):
    conn = get_db()
    if desk:
        rows = _rows(conn, """
            SELECT t.*, c.name AS counterparty_name, c.internal_rating
            FROM trades t JOIN counterparties c ON c.id = t.counterparty_id
            WHERE t.desk=? AND t.status=? ORDER BY ABS(t.mark_to_market) DESC
        """, (desk, status))
    else:
        rows = _rows(conn, """
            SELECT t.*, c.name AS counterparty_name, c.internal_rating
            FROM trades t JOIN counterparties c ON c.id = t.counterparty_id
            WHERE t.status=? ORDER BY ABS(t.mark_to_market) DESC LIMIT 200
        """, (status,))
    conn.close()
    return rows


@app.get("/api/market/data/{asset_id}")
def get_market_data(asset_id: str, days: int = Query(252)):
    conn = get_db()
    rows = _rows(conn, """
        SELECT price_date, value FROM market_data WHERE asset_id=?
        ORDER BY price_date DESC LIMIT ?
    """, (asset_id.upper(), days))
    conn.close()
    return {"asset_id": asset_id.upper(), "data": list(reversed(rows))}


@app.get("/api/ccr/summary")
def get_ccr_summary():
    conn = get_db()
    latest = conn.execute("SELECT MAX(snapshot_date) FROM cva_history").fetchone()[0]
    rows = _rows(conn, """
        SELECT c.id, c.name, c.internal_rating, c.country_iso2,
               cv.cva_usd, cv.dva_usd, cv.bilateral_cva_usd,
               sa.ead_usd, sa.rwa_usd, pf.pfe_peak
        FROM counterparties c
        LEFT JOIN cva_history cv  ON cv.counterparty_id=c.id AND cv.snapshot_date=?
        LEFT JOIN sa_ccr sa       ON sa.counterparty_id=c.id AND sa.snapshot_date=?
        LEFT JOIN pfe_profiles pf ON pf.counterparty_id=c.id AND pf.snapshot_date=?
        WHERE cv.cva_usd IS NOT NULL ORDER BY cv.cva_usd ASC
    """, (latest, "2025-12-31", "2025-12-31"))
    conn.close()
    return rows


@app.get("/api/ccr/cva/{cp_id}")
def get_cva_history(cp_id: int, months: int = Query(12)):
    conn = get_db()
    rows = _rows(conn, """
        SELECT * FROM cva_history WHERE counterparty_id=?
        ORDER BY snapshot_date DESC LIMIT ?
    """, (cp_id, months))
    conn.close()
    return rows


@app.get("/api/ccr/exposure")
def get_mtm_exposure():
    conn = get_db()
    latest = conn.execute("SELECT MAX(snapshot_date) FROM mtm_exposure").fetchone()[0]
    rows = _rows(conn, """
        SELECT c.name AS counterparty_name, c.internal_rating,
               e.net_mtm_usd, e.collateral_held_usd,
               e.current_exposure_usd, e.gross_positive_mtm_usd
        FROM mtm_exposure e JOIN counterparties c ON c.id = e.counterparty_id
        WHERE e.snapshot_date=? ORDER BY e.current_exposure_usd DESC
    """, (latest,))
    conn.close()
    return rows


@app.get("/api/country/limits")
def get_country_limits():
    conn = get_db()
    rows = _rows(conn, """
        SELECT cl.*, tr.transfer_risk_score, tr.convertibility_risk,
               tr.political_risk_score, tr.capital_controls
        FROM country_limits cl
        LEFT JOIN transfer_risk tr ON tr.country_iso2=cl.country_iso2
        ORDER BY cl.utilisation_pct DESC
    """)
    conn.close()
    return rows


@app.get("/api/country/exposures")
def get_country_exposures():
    conn = get_db()
    rows = _rows(conn, """
        SELECT * FROM country_exposures WHERE snapshot_date='2025-12-31'
        ORDER BY country_iso2, exposure_type
    """)
    conn.close()
    return rows


@app.get("/api/scenarios")
def get_scenarios():
    conn = get_db()
    rows = _rows(conn, "SELECT * FROM scenarios ORDER BY id")
    conn.close()
    return rows


@app.get("/api/scenarios/{scenario_id}/results")
def get_scenario_results(scenario_id: int):
    conn = get_db()
    sc = _rows(conn, "SELECT * FROM scenarios WHERE id=?", (scenario_id,))
    if not sc:
        raise HTTPException(404, "Scenario not found")
    results = _rows(conn, """
        SELECT * FROM scenario_results WHERE scenario_id=? ORDER BY COALESCE(desk,'ZZZZ')
    """, (scenario_id,))
    conn.close()
    return {"scenario": sc[0], "results": results}


@app.get("/health")
def health():
    return {"status": "ok", "db": DB_PATH}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3003, reload=True)
