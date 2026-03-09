"""
Generate 5 years (2021-2025) of annual financial statements per counterparty.
Amounts in LOCAL CURRENCY BILLIONS unless stated.
Financial Institutions (banks) use an asset-based model.
"""
import json
import random
from generators.counterparties import SECTOR_PARAMS, RAW

RNG = random.Random(7)

# Year-average FX rate (local ccy units per 1 USD, or USD per GBP)
# Used only to compute USD equivalents stored in ai_summary / embedding_text
AVG_FX = {
    # year: {ccy: local-per-USD}  (USD itself = 1.0)
    2021: {"USD": 1.0, "GBP": 1/1.38, "CNY": 6.45, "BRL": 5.40, "ZAR": 15.5},
    2022: {"USD": 1.0, "GBP": 1/1.24, "CNY": 6.73, "BRL": 5.16, "ZAR": 16.4},
    2023: {"USD": 1.0, "GBP": 1/1.24, "CNY": 7.10, "BRL": 5.00, "ZAR": 18.8},
    2024: {"USD": 1.0, "GBP": 1/1.28, "CNY": 7.20, "BRL": 5.20, "ZAR": 18.5},
    2025: {"USD": 1.0, "GBP": 1/1.27, "CNY": 7.15, "BRL": 5.10, "ZAR": 18.5},
}

YEARS = [2021, 2022, 2023, 2024, 2025]

# Revenue growth by sector per year (rough macro overlay)
# Index 0 = growth from base to 2021 set, 1-4 = YoY 2022-2025
SECTOR_GROWTH = {
    "Energy":      [0.10, 0.30, -0.05,  0.04, 0.02],   # oil price surge 2022
    "TMT":         [0.15, 0.12,  0.08,  0.10, 0.12],
    "Healthcare":  [0.08, 0.06,  0.07,  0.06, 0.07],
    "Consumer":    [0.06, 0.08,  0.03,  0.04, 0.05],
    "Industrials": [0.05, 0.10,  0.02,  0.05, 0.04],
    "Real Estate": [0.04, 0.05, -0.03,  0.02, 0.03],
    "Mining":      [0.08, 0.18, -0.10,  0.05, 0.06],
    "Financial":   [0.08, 0.12,  0.06,  0.05, 0.04],
}


def _jitter(base, lo, hi, rng):
    """Return base + uniform noise bounded to [lo, hi]."""
    return max(lo, min(hi, base + rng.uniform(-0.5, 0.5) * (hi - lo) * 0.15))


def _gen_non_fi(cp_raw, cp_id):
    """Generate financials for a non-FI entity."""
    sp = SECTOR_PARAMS[cp_raw["sector"]]
    rows = []
    rev_base = cp_raw["rev_scale"]
    em_base  = cp_raw["ebitda_m"]

    for yr_i, yr in enumerate(YEARS):
        # Apply sector growth (compound from base)
        g = SECTOR_GROWTH[cp_raw["sector"]][yr_i]
        noise_g = RNG.uniform(-0.03, 0.03)
        rev = rev_base * (1 + g + noise_g)
        rev_base = rev   # carry forward

        # EBITDA margin
        em = _jitter(em_base, sp["ebitda_margin"][0], sp["ebitda_margin"][1], RNG)
        ebitda = rev * em

        # D&A ≈ 5–9% of revenue
        da_pct = RNG.uniform(0.05, 0.09)
        da     = rev * da_pct
        ebit   = ebitda - da

        # Leverage → total debt; capex
        leverage = _jitter(
            (sp["leverage"][0] + sp["leverage"][1]) / 2,
            sp["leverage"][0], sp["leverage"][1], RNG
        )
        total_debt = max(0.01, leverage * ebitda)
        cash       = total_debt * RNG.uniform(0.05, 0.20)
        net_debt   = total_debt - cash

        # Interest expense
        int_rate = _jitter(
            (sp["int_rate"][0] + sp["int_rate"][1]) / 2,
            sp["int_rate"][0], sp["int_rate"][1], RNG
        )
        int_exp  = total_debt * int_rate

        ebt      = ebit - int_exp
        tax_rate = 0.21 if cp_raw["country_iso2"] == "US" else 0.20
        net_inc  = ebt * (1 - tax_rate) if ebt > 0 else ebt * 0.75

        capex_pct = _jitter(
            (sp["capex_rev"][0] + sp["capex_rev"][1]) / 2,
            sp["capex_rev"][0], sp["capex_rev"][1], RNG
        )
        capex = rev * capex_pct
        fcf   = net_inc + da - capex

        assets   = total_debt / 0.45 + cash   # rough: debt ≈ 45% of assets
        equity   = assets - total_debt

        rows.append({
            "counterparty_id":    cp_id,
            "fiscal_year":        yr,
            "currency":           cp_raw["currency"],
            "revenue":            round(rev,      4),
            "ebitda":             round(ebitda,   4),
            "ebit":               round(ebit,     4),
            "net_interest_expense": round(int_exp, 4),
            "net_income":         round(net_inc,  4),
            "total_assets":       round(assets,   4),
            "total_debt":         round(total_debt,4),
            "cash":               round(cash,     4),
            "net_debt":           round(net_debt, 4),
            "total_equity":       round(equity,   4),
            "capex":              round(capex,    4),
            "fcf":                round(fcf,      4),
            "ebitda_margin":      round(em,       4),
            "net_debt_ebitda":    round(net_debt / ebitda if ebitda > 0 else 0, 4),
            "interest_coverage":  round(ebitda / int_exp if int_exp > 0 else 99, 4),
            "roe":                round(net_inc / equity if equity > 0 else 0, 4),
            "roa":                round(net_inc / assets if assets > 0 else 0, 4),
            "ai_summary":         _fin_summary(cp_raw, yr, rev, ebitda, net_debt, net_inc),
            "risk_tags":          json.dumps(_fin_tags(net_debt, ebitda, em, ebit, int_exp)),
            "anomaly_score":      0.0,
        })
    return rows


def _gen_fi(cp_raw, cp_id):
    """Generate financials for a Financial Institution."""
    sp = SECTOR_PARAMS["Financial"]
    rows = []
    assets_base = _jitter(
        (sp["assets"][0] + sp["assets"][1]) / 2,
        sp["assets"][0], sp["assets"][1], RNG
    )

    for yr_i, yr in enumerate(YEARS):
        g = SECTOR_GROWTH["Financial"][yr_i]
        assets_base = assets_base * (1 + g + RNG.uniform(-0.02, 0.02))
        assets      = assets_base

        eq_ratio    = _jitter(
            (sp["equity_ratio"][0] + sp["equity_ratio"][1]) / 2,
            sp["equity_ratio"][0], sp["equity_ratio"][1], RNG
        )
        equity = assets * eq_ratio
        total_debt = assets - equity

        roe = _jitter(
            (sp["roe"][0] + sp["roe"][1]) / 2,
            sp["roe"][0], sp["roe"][1], RNG
        )
        net_inc = equity * roe
        # Revenue proxy = Net Interest Income + Non-Interest Income
        nim     = assets * RNG.uniform(0.012, 0.025)
        fees    = net_inc * RNG.uniform(0.3, 0.6)
        revenue = nim + fees
        ebitda  = revenue * 0.35  # cost-income ratio ~65%
        ebit    = ebitda * 0.92
        int_exp = total_debt * _jitter(
            (sp["int_rate"][0] + sp["int_rate"][1]) / 2,
            sp["int_rate"][0], sp["int_rate"][1], RNG
        )
        cash    = assets * RNG.uniform(0.05, 0.15)
        capex   = revenue * RNG.uniform(0.02, 0.05)
        fcf     = net_inc - capex

        rows.append({
            "counterparty_id":    cp_id,
            "fiscal_year":        yr,
            "currency":           cp_raw["currency"],
            "revenue":            round(revenue,   4),
            "ebitda":             round(ebitda,    4),
            "ebit":               round(ebit,      4),
            "net_interest_expense": round(int_exp, 4),
            "net_income":         round(net_inc,   4),
            "total_assets":       round(assets,    4),
            "total_debt":         round(total_debt,4),
            "cash":               round(cash,      4),
            "net_debt":           round(total_debt - cash, 4),
            "total_equity":       round(equity,    4),
            "capex":              round(capex,     4),
            "fcf":                round(fcf,       4),
            "ebitda_margin":      round(ebitda / revenue if revenue > 0 else 0, 4),
            "net_debt_ebitda":    round((total_debt - cash) / ebitda if ebitda > 0 else 0, 4),
            "interest_coverage":  round(ebitda / int_exp if int_exp > 0 else 99, 4),
            "roe":                round(roe, 4),
            "roa":                round(net_inc / assets if assets > 0 else 0, 4),
            "ai_summary":         _fin_summary(cp_raw, yr, revenue, ebitda, total_debt - cash, net_inc),
            "risk_tags":          json.dumps(["financial-institution", f"roe-{int(roe*100)}pct"]),
            "anomaly_score":      0.0,
        })
    return rows


def _fin_summary(cp_raw, yr, rev, ebitda, net_debt, net_inc):
    nd_ebitda = net_debt / ebitda if ebitda > 0 else 0
    ccy = cp_raw["currency"]
    return (
        f"FY{yr}: Revenue {rev:.1f}B {ccy}, EBITDA {ebitda:.1f}B {ccy} "
        f"(margin {ebitda/rev*100:.1f}%), Net Debt/EBITDA {nd_ebitda:.1f}x, "
        f"Net Income {net_inc:.1f}B {ccy}."
    )


def _fin_tags(net_debt, ebitda, em, ebit, int_exp):
    tags = []
    lev = net_debt / ebitda if ebitda > 0 else 0
    if lev > 5.0:
        tags.append("highly-leveraged")
    elif lev > 3.5:
        tags.append("leveraged")
    cov = ebitda / int_exp if int_exp > 0 else 99
    if cov < 2.0:
        tags.append("weak-interest-coverage")
    elif cov > 8.0:
        tags.append("strong-coverage")
    if em < 0.10:
        tags.append("thin-margin")
    elif em > 0.35:
        tags.append("high-margin")
    return tags


def insert_financials(conn):
    raw_by_id = {i+1: r for i, r in enumerate(RAW)}
    all_rows = []
    for cp_id, cp_raw in raw_by_id.items():
        if cp_raw["is_fi"]:
            rows = _gen_fi(cp_raw, cp_id)
        else:
            rows = _gen_non_fi(cp_raw, cp_id)
        all_rows.extend(rows)

    conn.executemany("""
        INSERT OR IGNORE INTO financials
        (counterparty_id, fiscal_year, currency, revenue, ebitda, ebit,
         net_interest_expense, net_income, total_assets, total_debt, cash,
         net_debt, total_equity, capex, fcf, ebitda_margin, net_debt_ebitda,
         interest_coverage, roe, roa, ai_summary, risk_tags, anomaly_score)
        VALUES
        (:counterparty_id,:fiscal_year,:currency,:revenue,:ebitda,:ebit,
         :net_interest_expense,:net_income,:total_assets,:total_debt,:cash,
         :net_debt,:total_equity,:capex,:fcf,:ebitda_margin,:net_debt_ebitda,
         :interest_coverage,:roe,:roa,:ai_summary,:risk_tags,:anomaly_score)
    """, all_rows)
    conn.commit()
    print(f"  Inserted {len(all_rows)} financial records.")
