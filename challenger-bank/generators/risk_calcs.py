"""
Compute and insert risk metrics:

Credit Risk
  • pd_history          – monthly PD snapshots (60 months per counterparty)

Market Risk
  • var_history          – monthly VaR and ES per desk + portfolio (60 months)
  • pnl_attribution      – monthly P&L per desk (60 months)

Counterparty Credit Risk
  • netting_sets         – one per trading counterparty
  • collateral           – current snapshot per netting set
  • mtm_exposure         – monthly (60 months) per netting set
  • pfe_profiles         – current snapshot per counterparty
  • cva_history          – monthly (60 months) per counterparty
  • sa_ccr               – current snapshot per counterparty

Country Risk
  • country_exposures     – current snapshot per country × exposure type
  • country_limits        – one per country
  • transfer_risk         – current snapshot per country
"""
import json
import math
import random
from datetime import date, timedelta
from generators.counterparties import (
    PD_BY_RATING, RATING_ORDER, RAW
)

RNG = random.Random(55)

# ── Helpers ──────────────────────────────────────────────────────────────────

MONTHS_60 = []
_d = date(2021, 1, 31)
while len(MONTHS_60) < 60:
    MONTHS_60.append(_d.isoformat())
    # next month-end
    if _d.month == 12:
        _d = date(_d.year + 1, 1, 31)
    else:
        import calendar
        last = calendar.monthrange(_d.year, _d.month + 1)[1]
        _d = date(_d.year, _d.month + 1, last)

IG_RATINGS = {"AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-"}
TODAY_STR  = "2025-12-31"

# FX end-2025
FX_END25 = {"USD": 1.0, "GBP": 1/1.27, "CNY": 1/7.15, "BRL": 1/5.10, "ZAR": 1/18.5}

# Daily vol of risk factors (bps or % as appropriate)
RATE_DVOL = {"USD": 6, "GBP": 5.5, "CNY": 2, "BRL": 18, "ZAR": 14}   # bps/day
FX_DVOL   = {"GBP": 0.50, "CNY": 0.20, "BRL": 0.85, "ZAR": 0.70}     # %/day
EQ_DVOL   = {"USD": 1.0, "GBP": 0.90, "CNY": 1.20, "BRL": 1.30, "ZAR": 1.10}  # %/day

# VaR z-score at 99%
Z99 = 2.326


# ─────────────────────────────────────────────────────────────────────────────
# 1. PD HISTORY
# ─────────────────────────────────────────────────────────────────────────────

def _pd_drift(base_pd, month_idx):
    """Small random walk on logit(PD) to simulate time-varying PD."""
    logit = math.log(base_pd / (1 - base_pd))
    logit += RNG.gauss(0, 0.04)   # monthly noise
    pd = 1 / (1 + math.exp(-logit))
    return max(0.00005, min(0.99, pd))


def insert_pd_history(conn, cp_rows):
    rows = []
    for cp in cp_rows:
        rating   = cp["internal_rating"]
        base_pd  = PD_BY_RATING.get(rating, 0.01)
        base_cs  = 100 * base_pd * 4   # rough CDS spread proxy
        # Cumulative PDs (Markov chain approximation)
        pd1 = base_pd
        for i, snap_date in enumerate(MONTHS_60):
            pd1 = _pd_drift(pd1, i)
            pd3 = 1 - (1 - pd1) ** 3
            pd5 = 1 - (1 - pd1) ** 5
            cs  = max(1, base_cs * (pd1 / base_pd) + RNG.uniform(-5, 5))
            rows.append({
                "counterparty_id": cp["id"],
                "snapshot_date":   snap_date,
                "pd_1y":           round(pd1, 6),
                "pd_3y":           round(pd3, 6),
                "pd_5y":           round(pd5, 6),
                "rating":          rating,
                "credit_spread_bps": round(cs, 1),
            })
    conn.executemany("""
        INSERT OR IGNORE INTO pd_history
        (counterparty_id, snapshot_date, pd_1y, pd_3y, pd_5y, rating, credit_spread_bps)
        VALUES (:counterparty_id,:snapshot_date,:pd_1y,:pd_3y,:pd_5y,:rating,:credit_spread_bps)
    """, rows)
    conn.commit()
    print(f"  Inserted {len(rows):,} PD history rows.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. VAR HISTORY + PNL ATTRIBUTION
# ─────────────────────────────────────────────────────────────────────────────

DESKS = ["Rates", "FX", "Credit", "Equity Derivatives",
         "Fixed Income", "Commodities", "Structured Products"]

# Base 1-day 99% VaR (USD millions) per desk
BASE_VAR = {
    "Rates":              42.0,
    "FX":                 28.0,
    "Credit":             22.0,
    "Equity Derivatives": 32.0,
    "Fixed Income":       38.0,
    "Commodities":        18.0,
    "Structured Products":12.0,
}
# Market stress index: 1.0 = calm, higher in crisis periods
# Driven by approximate equity vol regime
STRESS_IDX = [
    # 2021 (months 1-12): calm
    *[1.0] * 6, *[1.1] * 6,
    # 2022 (months 13-24): rising rates, Ukraine
    *[1.3] * 3, *[1.5] * 3, *[1.4] * 3, *[1.3] * 3,
    # 2023 (months 25-36): SVB, normalising
    *[1.4] * 3, *[1.2] * 3, *[1.1] * 6,
    # 2024 (months 37-48): calm
    *[1.1] * 12,
    # 2025 (months 49-60): slight uptick
    *[1.1] * 6, *[1.2] * 6,
]


def _var_for_desk_month(desk, stress):
    base = BASE_VAR[desk]
    noise = RNG.uniform(0.85, 1.15)
    v1 = base * stress * noise
    es  = v1 * 1.25        # ES ≈ 1.25 × VaR (Normal approx)
    v10 = v1 * math.sqrt(10)
    sv  = v1 * 2.0
    return round(v1, 2), round(es, 2), round(v10, 2), round(sv, 2)


def insert_var_history(conn):
    rows = []
    for i, snap_date in enumerate(MONTHS_60):
        stress = STRESS_IDX[i] if i < len(STRESS_IDX) else 1.1
        desk_vars = {}
        for desk in DESKS:
            v1, es, v10, sv = _var_for_desk_month(desk, stress)
            desk_vars[desk] = v1
            rows.append({
                "snapshot_date": snap_date,
                "desk":          desk,
                "var_1d_99":     v1,
                "es_1d_97_5":    es,
                "var_10d_99":    v10,
                "stressed_var":  sv,
            })
        # Portfolio VaR (diversified — approx 70% of sum)
        portfolio_var = sum(desk_vars.values()) * 0.68
        rows.append({
            "snapshot_date": snap_date,
            "desk":          None,
            "var_1d_99":     round(portfolio_var, 2),
            "es_1d_97_5":    round(portfolio_var * 1.25, 2),
            "var_10d_99":    round(portfolio_var * math.sqrt(10), 2),
            "stressed_var":  round(portfolio_var * 2.0, 2),
        })

    conn.executemany("""
        INSERT OR IGNORE INTO var_history
        (snapshot_date, desk, var_1d_99, es_1d_97_5, var_10d_99, stressed_var)
        VALUES (:snapshot_date,:desk,:var_1d_99,:es_1d_97_5,:var_10d_99,:stressed_var)
    """, rows)
    conn.commit()
    print(f"  Inserted {len(rows):,} VaR history rows.")


def insert_pnl_attribution(conn):
    """Monthly P&L split by risk factor per desk."""
    rows = []
    # Desk P&L std dev (M USD/month) — roughly VaR / 2.326 × sqrt(21)
    DESK_STD = {d: BASE_VAR[d] / Z99 * math.sqrt(21) for d in DESKS}

    for i, snap_date in enumerate(MONTHS_60):
        stress = STRESS_IDX[i] if i < len(STRESS_IDX) else 1.1
        for desk in DESKS:
            std = DESK_STD[desk] * stress
            # Positive drift: bank makes money on avg (small Sharpe ~0.3)
            drift = std * 0.08
            total = RNG.gauss(drift, std)
            # Split total into risk-factor components
            if desk == "Rates":
                r_pnl = total * 0.6; fx_pnl = total * 0.1; cr_pnl = total * 0.1; eq_pnl = 0; th = total * 0.15; ot = total * 0.05
            elif desk == "FX":
                r_pnl = 0; fx_pnl = total * 0.75; cr_pnl = 0; eq_pnl = 0; th = total * 0.10; ot = total * 0.15
            elif desk == "Credit":
                r_pnl = total * 0.1; fx_pnl = 0; cr_pnl = total * 0.75; eq_pnl = 0; th = total * 0.10; ot = total * 0.05
            elif desk == "Equity Derivatives":
                r_pnl = 0; fx_pnl = 0; cr_pnl = 0; eq_pnl = total * 0.70; th = total * 0.20; ot = total * 0.10
            elif desk == "Fixed Income":
                r_pnl = total * 0.70; fx_pnl = 0; cr_pnl = total * 0.15; eq_pnl = 0; th = total * 0.10; ot = total * 0.05
            elif desk == "Commodities":
                r_pnl = 0; fx_pnl = total * 0.15; cr_pnl = 0; eq_pnl = 0; th = total * 0.05; ot = total * 0.80
            else:
                r_pnl = total * 0.2; fx_pnl = total * 0.1; cr_pnl = total * 0.4; eq_pnl = total * 0.2; th = 0; ot = total * 0.1

            rows.append({
                "pnl_date":   snap_date,
                "desk":       desk,
                "daily_pnl":  round(total, 3),
                "rates_pnl":  round(r_pnl, 3),
                "fx_pnl":     round(fx_pnl, 3),
                "credit_pnl": round(cr_pnl, 3),
                "equity_pnl": round(eq_pnl, 3),
                "theta_pnl":  round(th, 3),
                "other_pnl":  round(ot, 3),
            })

    conn.executemany("""
        INSERT OR IGNORE INTO pnl_attribution
        (pnl_date, desk, daily_pnl, rates_pnl, fx_pnl, credit_pnl,
         equity_pnl, theta_pnl, other_pnl)
        VALUES
        (:pnl_date,:desk,:daily_pnl,:rates_pnl,:fx_pnl,:credit_pnl,
         :equity_pnl,:theta_pnl,:other_pnl)
    """, rows)
    conn.commit()
    print(f"  Inserted {len(rows):,} P&L attribution rows.")


# ─────────────────────────────────────────────────────────────────────────────
# 3. NETTING SETS + COLLATERAL
# ─────────────────────────────────────────────────────────────────────────────

def _has_trading(cp_id):
    """Mirror logic from trades.py."""
    raw = RAW[cp_id - 1]
    return (raw["is_fi"] or raw["sector"] in
            {"Financial","Energy","TMT","Healthcare","Industrials","Consumer"})


def insert_netting_sets(conn, cp_rows):
    ns_rows = []
    for cp in cp_rows:
        if not _has_trading(cp["id"]):
            continue
        is_fi  = cp["is_financial_institution"]
        rating = cp["internal_rating"]
        ns_id  = f"NS-{cp['id']:03d}"
        has_csa = 1 if (is_fi or rating in IG_RATINGS) else 0
        threshold = round(RNG.uniform(5, 50), 1) if has_csa else None   # M USD
        mta       = round(RNG.uniform(0.5, 5.0), 2) if has_csa else None
        ns_rows.append({
            "counterparty_id":      cp["id"],
            "netting_set_id":       ns_id,
            "agreement_type":       "ISDA 2002" if is_fi else RNG.choice(["ISDA 2002","ISDA 1992"]),
            "csa_in_place":         has_csa,
            "threshold_received_usd": threshold,
            "threshold_posted_usd":   threshold,
            "mta_usd":              mta,
        })

    conn.executemany("""
        INSERT OR IGNORE INTO netting_sets
        (counterparty_id, netting_set_id, agreement_type, csa_in_place,
         threshold_received_usd, threshold_posted_usd, mta_usd)
        VALUES
        (:counterparty_id,:netting_set_id,:agreement_type,:csa_in_place,
         :threshold_received_usd,:threshold_posted_usd,:mta_usd)
    """, ns_rows)
    conn.commit()

    # Collateral — current snapshot
    ns_db = {r["counterparty_id"]: r["id"]
             for r in conn.execute("SELECT id, counterparty_id FROM netting_sets").fetchall()}
    coll_rows = []
    for cp in cp_rows:
        ns_db_id = ns_db.get(cp["id"])
        if not ns_db_id:
            continue
        if not _has_trading(cp["id"]):
            continue
        # Posted collateral
        coll_usd = round(RNG.uniform(0.5, 20.0), 2)
        coll_rows.append({
            "netting_set_id":  ns_db_id,
            "snapshot_date":   TODAY_STR,
            "collateral_type": RNG.choice(["Cash", "Government Bond"]),
            "currency":        "USD",
            "notional_usd":    coll_usd,
            "haircut":         0.0 if True else 0.02,
            "eligible_value_usd": coll_usd,
            "direction":       "Received",
        })

    if coll_rows:
        conn.executemany("""
            INSERT OR IGNORE INTO collateral
            (netting_set_id, snapshot_date, collateral_type, currency,
             notional_usd, haircut, eligible_value_usd, direction)
            VALUES
            (:netting_set_id,:snapshot_date,:collateral_type,:currency,
             :notional_usd,:haircut,:eligible_value_usd,:direction)
        """, coll_rows)
        conn.commit()
    print(f"  Inserted {len(ns_rows)} netting sets, {len(coll_rows)} collateral rows.")


# ─────────────────────────────────────────────────────────────────────────────
# 4. MTM EXPOSURE + PFE PROFILES + CVA + SA-CCR
# ─────────────────────────────────────────────────────────────────────────────

def _pfe_tenor(gross_notional_usd, sigma_rate=0.007, tenor_y=1.0):
    """
    Simplified PFE estimate for a mixed portfolio:
    PFE ≈ sigma × sqrt(tenor) × notional × percentile_factor
    """
    return gross_notional_usd * sigma_rate * math.sqrt(tenor_y) * Z99


def insert_ccr_metrics(conn, cp_rows):
    """Insert mtm_exposure (monthly), pfe_profiles, cva_history, sa_ccr."""
    # Get netting set DB ids
    ns_map = {r["counterparty_id"]: {"ns_id": r["id"], "ns_str": r["netting_set_id"]}
              for r in conn.execute("SELECT id, counterparty_id, netting_set_id FROM netting_sets").fetchall()}

    # Sum of trade MtM per counterparty
    mtm_by_cp = {}
    for row in conn.execute("""
        SELECT counterparty_id,
               SUM(CASE WHEN mark_to_market > 0 THEN mark_to_market ELSE 0 END) AS pos_mtm,
               SUM(CASE WHEN mark_to_market < 0 THEN mark_to_market ELSE 0 END) AS neg_mtm,
               SUM(ABS(notional_usd)) AS gross_notional
        FROM trades GROUP BY counterparty_id
    """).fetchall():
        mtm_by_cp[row["counterparty_id"]] = {
            "pos": row["pos_mtm"] or 0,
            "neg": row["neg_mtm"] or 0,
            "notional": row["gross_notional"] or 0,
        }

    # Collateral by netting set
    coll_by_ns = {r["netting_set_id"]: r["total_coll"]
                  for r in conn.execute("""
        SELECT netting_set_id, SUM(eligible_value_usd) AS total_coll
        FROM collateral GROUP BY netting_set_id
    """).fetchall()}

    mtm_exp_rows = []
    pfe_rows     = []
    cva_rows     = []
    saccr_rows   = []

    for cp in cp_rows:
        cp_id  = cp["id"]
        if cp_id not in ns_map:
            continue
        ns_db_id = ns_map[cp_id]["ns_id"]
        rating   = cp["internal_rating"]
        pd_1y    = PD_BY_RATING.get(rating, 0.02)
        lgd      = 0.40 if rating in IG_RATINGS else 0.55

        m = mtm_by_cp.get(cp_id, {"pos": 5.0, "neg": -2.0, "notional": 100.0})
        coll = coll_by_ns.get(ns_db_id, 0)
        gross_notional = m["notional"]  # USD millions

        # Monthly snapshots of exposure
        pos_base = abs(m["pos"])
        neg_base = abs(m["neg"])
        for i, snap_date in enumerate(MONTHS_60):
            noise = RNG.uniform(0.8, 1.25)
            pos_mtm = round(pos_base * noise, 3)
            neg_mtm = round(neg_base * noise, 3)
            net_mtm = round(pos_mtm - neg_mtm, 3)
            ce      = round(max(net_mtm - coll, 0), 3)
            mtm_exp_rows.append({
                "counterparty_id":       cp_id,
                "netting_set_id":        ns_db_id,
                "snapshot_date":         snap_date,
                "gross_positive_mtm_usd":pos_mtm,
                "gross_negative_mtm_usd":-neg_mtm,
                "net_mtm_usd":           net_mtm,
                "collateral_held_usd":   coll,
                "current_exposure_usd":  ce,
            })

            # CVA = LGD × PD × EE × discount_factor (simplified)
            ee   = max(ce * 0.7 + pos_mtm * 0.3, 0.1)
            cva  = -lgd * pd_1y * ee   # negative (cost)
            cva_rows.append({
                "counterparty_id":    cp_id,
                "snapshot_date":      snap_date,
                "cva_usd":            round(cva, 4),
                "dva_usd":            round(-cva * 0.3, 4),
                "bilateral_cva_usd":  round(cva * 0.7, 4),
                "pd_market_implied":  round(pd_1y * (0.9 + RNG.uniform(0, 0.2)), 6),
                "lgd_assumption":     lgd,
            })

        # PFE profile (current snapshot)
        n_usd = gross_notional
        pfe_rows.append({
            "counterparty_id":    cp_id,
            "snapshot_date":      TODAY_STR,
            "pfe_1m":    round(_pfe_tenor(n_usd, 0.007, 1/12), 3),
            "pfe_3m":    round(_pfe_tenor(n_usd, 0.007, 3/12), 3),
            "pfe_6m":    round(_pfe_tenor(n_usd, 0.007, 0.5),  3),
            "pfe_1y":    round(_pfe_tenor(n_usd, 0.007, 1.0),  3),
            "pfe_2y":    round(_pfe_tenor(n_usd, 0.007, 2.0),  3),
            "pfe_3y":    round(_pfe_tenor(n_usd, 0.007, 3.0),  3),
            "pfe_5y":    round(_pfe_tenor(n_usd, 0.007, 5.0),  3),
            "pfe_7y":    round(_pfe_tenor(n_usd, 0.007, 7.0),  3),
            "pfe_10y":   round(_pfe_tenor(n_usd, 0.007, 10.0), 3),
            "pfe_peak":  round(_pfe_tenor(n_usd, 0.007, 5.0),  3),
            "pfe_peak_tenor": "5Y",
            "expected_exposure_avg": round(_pfe_tenor(n_usd, 0.007, 2.0) * 0.6, 3),
        })

        # SA-CCR (current snapshot)
        # RC = max(net MtM, 0) / 1000 (convert M to B for consistency)
        net_mtm_curr = mtm_by_cp.get(cp_id, {"pos":0,"neg":0})
        rc   = max((net_mtm_curr["pos"] + net_mtm_curr["neg"]) / 1000, 0)
        # PFE add-on ≈ 10% of gross notional (simplified)
        pfe_addon = gross_notional * 0.10 / 1000
        ead  = 1.4 * (rc + pfe_addon)
        rw   = 0.50 if rating in IG_RATINGS else 1.00
        rwa  = ead * rw
        saccr_rows.append({
            "counterparty_id":   cp_id,
            "snapshot_date":     TODAY_STR,
            "replacement_cost_usd": round(rc, 6),
            "pfe_addon_usd":     round(pfe_addon, 6),
            "ead_usd":           round(ead, 6),
            "risk_weight":       rw,
            "rwa_usd":           round(rwa, 6),
        })

    conn.executemany("""
        INSERT OR IGNORE INTO mtm_exposure
        (counterparty_id, netting_set_id, snapshot_date,
         gross_positive_mtm_usd, gross_negative_mtm_usd, net_mtm_usd,
         collateral_held_usd, current_exposure_usd)
        VALUES
        (:counterparty_id,:netting_set_id,:snapshot_date,
         :gross_positive_mtm_usd,:gross_negative_mtm_usd,:net_mtm_usd,
         :collateral_held_usd,:current_exposure_usd)
    """, mtm_exp_rows)

    conn.executemany("""
        INSERT OR IGNORE INTO pfe_profiles
        (counterparty_id, snapshot_date,
         pfe_1m, pfe_3m, pfe_6m, pfe_1y, pfe_2y, pfe_3y,
         pfe_5y, pfe_7y, pfe_10y, pfe_peak, pfe_peak_tenor,
         expected_exposure_avg)
        VALUES
        (:counterparty_id,:snapshot_date,
         :pfe_1m,:pfe_3m,:pfe_6m,:pfe_1y,:pfe_2y,:pfe_3y,
         :pfe_5y,:pfe_7y,:pfe_10y,:pfe_peak,:pfe_peak_tenor,
         :expected_exposure_avg)
    """, pfe_rows)

    conn.executemany("""
        INSERT OR IGNORE INTO cva_history
        (counterparty_id, snapshot_date, cva_usd, dva_usd,
         bilateral_cva_usd, pd_market_implied, lgd_assumption)
        VALUES
        (:counterparty_id,:snapshot_date,:cva_usd,:dva_usd,
         :bilateral_cva_usd,:pd_market_implied,:lgd_assumption)
    """, cva_rows)

    conn.executemany("""
        INSERT OR IGNORE INTO sa_ccr
        (counterparty_id, snapshot_date, replacement_cost_usd,
         pfe_addon_usd, ead_usd, risk_weight, rwa_usd)
        VALUES
        (:counterparty_id,:snapshot_date,:replacement_cost_usd,
         :pfe_addon_usd,:ead_usd,:risk_weight,:rwa_usd)
    """, saccr_rows)

    conn.commit()
    print(f"  Inserted {len(mtm_exp_rows):,} MtM exposure, {len(pfe_rows)} PFE, "
          f"{len(cva_rows):,} CVA, {len(saccr_rows)} SA-CCR rows.")


# ─────────────────────────────────────────────────────────────────────────────
# 5. COUNTRY RISK
# ─────────────────────────────────────────────────────────────────────────────

COUNTRIES = [
    dict(iso2="US", name="United States",  ccy="USD", limit_usd=100000, sov_rating="AA+",
         transfer_risk=1.0, conv_risk="Low",  pol_risk=1.5, cap_ctrl=0),
    dict(iso2="GB", name="United Kingdom", ccy="GBP", limit_usd=30000,  sov_rating="AA",
         transfer_risk=1.5, conv_risk="Low",  pol_risk=2.0, cap_ctrl=0),
    dict(iso2="CN", name="China",          ccy="CNY", limit_usd=25000,  sov_rating="A+",
         transfer_risk=5.5, conv_risk="High", pol_risk=5.0, cap_ctrl=1),
    dict(iso2="BR", name="Brazil",         ccy="BRL", limit_usd=12000,  sov_rating="BB",
         transfer_risk=6.0, conv_risk="Medium", pol_risk=5.5, cap_ctrl=0),
    dict(iso2="ZA", name="South Africa",   ccy="ZAR", limit_usd=5000,   sov_rating="BB-",
         transfer_risk=7.0, conv_risk="Medium", pol_risk=6.0, cap_ctrl=0),
]


def insert_country_risk(conn, cp_rows):
    # Aggregate exposures from credit facilities + trades
    fac_by_country = {}
    for row in conn.execute("""
        SELECT c.country_iso2, c.country_name, c.currency,
               SUM(f.drawn_amount) AS drawn, SUM(f.ead) AS ead_usd
        FROM credit_facilities f
        JOIN counterparties c ON c.id = f.counterparty_id
        WHERE f.status = 'Active'
        GROUP BY c.country_iso2
    """).fetchall():
        fac_by_country[row["country_iso2"]] = {
            "name": row["country_name"],
            "drawn_usd": row["ead_usd"] or 0,
        }

    trade_by_country = {}
    for row in conn.execute("""
        SELECT c.country_iso2,
               SUM(ABS(t.notional_usd)) AS notional_usd
        FROM trades t
        JOIN counterparties c ON c.id = t.counterparty_id
        WHERE t.status = 'Live'
        GROUP BY c.country_iso2
    """).fetchall():
        trade_by_country[row["country_iso2"]] = row["notional_usd"] or 0

    exp_rows   = []
    limit_rows = []
    tr_rows    = []

    for country in COUNTRIES:
        iso2 = country["iso2"]
        lending  = fac_by_country.get(iso2, {}).get("drawn_usd", 0) * 1000  # B→M USD
        trading  = trade_by_country.get(iso2, 0)
        total    = lending + trading
        utilisation = round(total / country["limit_usd"] * 100, 1) if country["limit_usd"] else 0
        status = "Green" if utilisation < 60 else ("Amber" if utilisation < 85 else "Red")

        exp_rows.append({
            "country_iso2":       iso2,
            "country_name":       country["name"],
            "snapshot_date":      TODAY_STR,
            "exposure_type":      "Lending",
            "currency":           country["ccy"],
            "gross_exposure_usd": round(lending, 2),
            "net_exposure_usd":   round(lending * 0.85, 2),
            "collateral_usd":     round(lending * 0.15, 2),
        })
        exp_rows.append({
            "country_iso2":       iso2,
            "country_name":       country["name"],
            "snapshot_date":      TODAY_STR,
            "exposure_type":      "Trading",
            "currency":           "USD",
            "gross_exposure_usd": round(trading, 2),
            "net_exposure_usd":   round(trading * 0.60, 2),
            "collateral_usd":     round(trading * 0.40, 2),
        })

        limit_rows.append({
            "country_iso2":        iso2,
            "country_name":        country["name"],
            "approved_limit_usd":  country["limit_usd"],
            "current_exposure_usd":round(total, 2),
            "utilisation_pct":     utilisation,
            "limit_status":        status,
            "sovereign_rating":    country["sov_rating"],
            "last_review_date":    "2025-06-30",
        })

        tr_rows.append({
            "country_iso2":        iso2,
            "snapshot_date":       TODAY_STR,
            "transfer_risk_score": country["transfer_risk"],
            "convertibility_risk": country["conv_risk"],
            "political_risk_score":country["pol_risk"],
            "capital_controls":    country["cap_ctrl"],
        })

    conn.executemany("""
        INSERT OR IGNORE INTO country_exposures
        (country_iso2, country_name, snapshot_date, exposure_type, currency,
         gross_exposure_usd, net_exposure_usd, collateral_usd)
        VALUES
        (:country_iso2,:country_name,:snapshot_date,:exposure_type,:currency,
         :gross_exposure_usd,:net_exposure_usd,:collateral_usd)
    """, exp_rows)

    conn.executemany("""
        INSERT OR REPLACE INTO country_limits
        (country_iso2, country_name, approved_limit_usd, current_exposure_usd,
         utilisation_pct, limit_status, sovereign_rating, last_review_date)
        VALUES
        (:country_iso2,:country_name,:approved_limit_usd,:current_exposure_usd,
         :utilisation_pct,:limit_status,:sovereign_rating,:last_review_date)
    """, limit_rows)

    conn.executemany("""
        INSERT OR REPLACE INTO transfer_risk
        (country_iso2, snapshot_date, transfer_risk_score, convertibility_risk,
         political_risk_score, capital_controls)
        VALUES
        (:country_iso2,:snapshot_date,:transfer_risk_score,:convertibility_risk,
         :political_risk_score,:capital_controls)
    """, tr_rows)

    conn.commit()
    print(f"  Inserted {len(exp_rows)} country exposure, {len(limit_rows)} limit, {len(tr_rows)} transfer risk rows.")
