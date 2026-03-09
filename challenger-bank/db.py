import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bank.db")

SCHEMA = """
-- ── Master ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS counterparties (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    short_name              TEXT,
    country_iso2            TEXT NOT NULL,   -- US, GB, CN, BR, ZA
    country_name            TEXT NOT NULL,
    sector                  TEXT NOT NULL,
    sub_sector              TEXT,
    currency                TEXT NOT NULL,   -- functional currency: USD/GBP/CNY/BRL/ZAR
    internal_rating         TEXT NOT NULL,   -- AAA … D
    external_shadow_rating  TEXT,
    rating_outlook          TEXT DEFAULT 'Stable',
    is_financial_institution INTEGER DEFAULT 0,
    is_soe                  INTEGER DEFAULT 0,
    employee_count          INTEGER,
    founded_year            INTEGER,
    hq_city                 TEXT,
    lei                     TEXT,            -- fictitious 20-char LEI
    -- AI-analytics metadata
    ai_summary              TEXT,
    risk_tags               TEXT,            -- JSON array
    embedding_text          TEXT,
    anomaly_score           REAL DEFAULT 0.0,
    alert_flags             TEXT DEFAULT '[]',
    last_updated            TEXT
);

CREATE TABLE IF NOT EXISTS financials (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    fiscal_year             INTEGER NOT NULL,
    currency                TEXT NOT NULL,
    -- P&L (in billions of local currency)
    revenue                 REAL,
    ebitda                  REAL,
    ebit                    REAL,
    net_interest_expense    REAL,
    net_income              REAL,
    -- Balance sheet
    total_assets            REAL,
    total_debt              REAL,
    cash                    REAL,
    net_debt                REAL,
    total_equity            REAL,
    capex                   REAL,
    fcf                     REAL,
    -- Key ratios
    ebitda_margin           REAL,
    net_debt_ebitda         REAL,
    interest_coverage       REAL,
    roe                     REAL,
    roa                     REAL,
    -- AI metadata
    ai_summary              TEXT,
    risk_tags               TEXT,
    anomaly_score           REAL DEFAULT 0.0,
    UNIQUE(counterparty_id, fiscal_year)
);

CREATE TABLE IF NOT EXISTS credit_ratings (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    rating_date             TEXT NOT NULL,
    rating                  TEXT NOT NULL,
    outlook                 TEXT NOT NULL,
    rating_type             TEXT NOT NULL,   -- Internal, External
    analyst_notes           TEXT,
    UNIQUE(counterparty_id, rating_date, rating_type)
);

-- ── Credit Risk ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_facilities (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    facility_name           TEXT NOT NULL,
    facility_type           TEXT NOT NULL,   -- Term Loan A/B, RCF, Trade Finance
    currency                TEXT NOT NULL,
    limit_amount            REAL NOT NULL,   -- billions local ccy
    drawn_amount            REAL NOT NULL,
    undrawn_amount          REAL NOT NULL,
    base_rate               TEXT NOT NULL,   -- SOFR, SONIA, SHIBOR, CDI, JIBAR
    credit_spread_bps       REAL NOT NULL,
    origination_date        TEXT NOT NULL,
    maturity_date           TEXT NOT NULL,
    seniority               TEXT NOT NULL,   -- Senior Secured, Senior Unsecured, Sub, Mezz
    collateral_type         TEXT,
    covenant_leverage_max   REAL,
    covenant_coverage_min   REAL,
    status                  TEXT DEFAULT 'Active',
    -- Risk parameters
    pd                      REAL,
    lgd                     REAL,
    ead                     REAL,            -- USD billions
    expected_loss           REAL,            -- USD billions
    rwa                     REAL,            -- USD billions
    risk_weight             REAL,
    -- AI metadata
    ai_summary              TEXT,
    risk_tags               TEXT,
    anomaly_score           REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS credit_events (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    facility_id             INTEGER REFERENCES credit_facilities(id),
    event_date              TEXT NOT NULL,
    event_type              TEXT NOT NULL,   -- Covenant Breach, Watchlist, Default, Downgrade
    description             TEXT,
    resolution              TEXT,
    resolved_date           TEXT
);

CREATE TABLE IF NOT EXISTS pd_history (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    snapshot_date           TEXT NOT NULL,
    pd_1y                   REAL NOT NULL,
    pd_3y                   REAL,
    pd_5y                   REAL,
    rating                  TEXT,
    credit_spread_bps       REAL,
    UNIQUE(counterparty_id, snapshot_date)
);

-- ── Market Data ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_data (
    id                      INTEGER PRIMARY KEY,
    asset_id                TEXT NOT NULL,   -- e.g. USD_10Y, GBPUSD, US_SPX
    asset_type              TEXT NOT NULL,   -- Rate, FX, Equity, CreditSpread
    currency                TEXT,
    price_date              TEXT NOT NULL,
    value                   REAL NOT NULL,
    UNIQUE(asset_id, price_date)
);

CREATE TABLE IF NOT EXISTS trades (
    id                      INTEGER PRIMARY KEY,
    trade_id                TEXT NOT NULL UNIQUE,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    desk                    TEXT NOT NULL,
    product                 TEXT NOT NULL,   -- IRS, XCS, FX Forward, FX Option, CDS, Equity Option, Bond
    direction               TEXT NOT NULL,   -- Pay/Receive (rates) or Long/Short
    currency                TEXT NOT NULL,
    notional                REAL NOT NULL,   -- millions local ccy
    notional_usd            REAL NOT NULL,
    trade_date              TEXT NOT NULL,
    maturity_date           TEXT NOT NULL,
    fixed_rate              REAL,
    floating_index          TEXT,
    strike                  REAL,
    delta                   REAL,
    mark_to_market          REAL NOT NULL,   -- USD millions
    dv01                    REAL,            -- USD per bp
    cs01                    REAL,            -- USD per bp
    status                  TEXT DEFAULT 'Live',
    -- AI metadata
    ai_summary              TEXT,
    risk_tags               TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id                      INTEGER PRIMARY KEY,
    snapshot_date           TEXT NOT NULL,
    desk                    TEXT NOT NULL,
    product                 TEXT NOT NULL,
    currency                TEXT NOT NULL,
    net_notional_usd        REAL,
    net_mtm_usd             REAL,
    net_dv01                REAL,
    net_cs01                REAL,
    trade_count             INTEGER,
    UNIQUE(snapshot_date, desk, product, currency)
);

CREATE TABLE IF NOT EXISTS var_history (
    id                      INTEGER PRIMARY KEY,
    snapshot_date           TEXT NOT NULL,
    desk                    TEXT,            -- NULL = total portfolio
    var_1d_99               REAL NOT NULL,   -- USD millions, 1-day 99%
    es_1d_97_5              REAL NOT NULL,   -- Expected Shortfall
    var_10d_99              REAL NOT NULL,   -- sqrt(10) scaled
    stressed_var            REAL,            -- approx 2× VaR
    UNIQUE(snapshot_date, desk)
);

CREATE TABLE IF NOT EXISTS pnl_attribution (
    id                      INTEGER PRIMARY KEY,
    pnl_date                TEXT NOT NULL,
    desk                    TEXT NOT NULL,
    daily_pnl               REAL NOT NULL,   -- USD millions
    rates_pnl               REAL DEFAULT 0,
    fx_pnl                  REAL DEFAULT 0,
    credit_pnl              REAL DEFAULT 0,
    equity_pnl              REAL DEFAULT 0,
    theta_pnl               REAL DEFAULT 0,
    other_pnl               REAL DEFAULT 0,
    UNIQUE(pnl_date, desk)
);

-- ── Counterparty Risk ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS netting_sets (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    netting_set_id          TEXT NOT NULL UNIQUE,
    agreement_type          TEXT NOT NULL,   -- ISDA 2002, ISDA 1992, None
    csa_in_place            INTEGER DEFAULT 0,
    threshold_received_usd  REAL,
    threshold_posted_usd    REAL,
    mta_usd                 REAL            -- minimum transfer amount
);

CREATE TABLE IF NOT EXISTS collateral (
    id                      INTEGER PRIMARY KEY,
    netting_set_id          INTEGER NOT NULL REFERENCES netting_sets(id),
    snapshot_date           TEXT NOT NULL,
    collateral_type         TEXT NOT NULL,   -- Cash, Gov Bond, IG Bond
    currency                TEXT NOT NULL,
    notional_usd            REAL NOT NULL,
    haircut                 REAL NOT NULL,
    eligible_value_usd      REAL NOT NULL,
    direction               TEXT NOT NULL,   -- Posted, Received
    UNIQUE(netting_set_id, snapshot_date, collateral_type, direction)
);

CREATE TABLE IF NOT EXISTS mtm_exposure (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    netting_set_id          INTEGER NOT NULL REFERENCES netting_sets(id),
    snapshot_date           TEXT NOT NULL,
    gross_positive_mtm_usd  REAL NOT NULL,
    gross_negative_mtm_usd  REAL NOT NULL,
    net_mtm_usd             REAL NOT NULL,
    collateral_held_usd     REAL NOT NULL,
    current_exposure_usd    REAL NOT NULL,   -- max(net_mtm - collateral, 0)
    UNIQUE(netting_set_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS pfe_profiles (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    snapshot_date           TEXT NOT NULL,
    pfe_1m                  REAL, pfe_3m REAL, pfe_6m REAL,
    pfe_1y                  REAL, pfe_2y REAL, pfe_3y REAL,
    pfe_5y                  REAL, pfe_7y REAL, pfe_10y REAL,
    pfe_peak                REAL,
    pfe_peak_tenor          TEXT,
    expected_exposure_avg   REAL,
    UNIQUE(counterparty_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS cva_history (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    snapshot_date           TEXT NOT NULL,
    cva_usd                 REAL NOT NULL,   -- USD millions (negative)
    dva_usd                 REAL,
    bilateral_cva_usd       REAL,
    pd_market_implied       REAL,
    lgd_assumption          REAL,
    UNIQUE(counterparty_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS sa_ccr (
    id                      INTEGER PRIMARY KEY,
    counterparty_id         INTEGER NOT NULL REFERENCES counterparties(id),
    snapshot_date           TEXT NOT NULL,
    replacement_cost_usd    REAL NOT NULL,
    pfe_addon_usd           REAL NOT NULL,
    ead_usd                 REAL NOT NULL,   -- 1.4 × (RC + PFE)
    risk_weight             REAL NOT NULL,
    rwa_usd                 REAL NOT NULL,
    UNIQUE(counterparty_id, snapshot_date)
);

-- ── Country Risk ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS country_exposures (
    id                      INTEGER PRIMARY KEY,
    country_iso2            TEXT NOT NULL,
    country_name            TEXT NOT NULL,
    snapshot_date           TEXT NOT NULL,
    exposure_type           TEXT NOT NULL,   -- Lending, Trading, Settlement, Issuer
    currency                TEXT NOT NULL,
    gross_exposure_usd      REAL NOT NULL,
    net_exposure_usd        REAL NOT NULL,
    collateral_usd          REAL DEFAULT 0,
    UNIQUE(country_iso2, snapshot_date, exposure_type)
);

CREATE TABLE IF NOT EXISTS country_limits (
    id                      INTEGER PRIMARY KEY,
    country_iso2            TEXT NOT NULL UNIQUE,
    country_name            TEXT NOT NULL,
    approved_limit_usd      REAL NOT NULL,
    current_exposure_usd    REAL,
    utilisation_pct         REAL,
    limit_status            TEXT,            -- Green, Amber, Red, Breach
    sovereign_rating        TEXT,
    last_review_date        TEXT
);

CREATE TABLE IF NOT EXISTS transfer_risk (
    id                      INTEGER PRIMARY KEY,
    country_iso2            TEXT NOT NULL UNIQUE,
    snapshot_date           TEXT NOT NULL,
    transfer_risk_score     REAL,            -- 0-10, higher = riskier
    convertibility_risk     TEXT,            -- Low, Medium, High
    political_risk_score    REAL,
    capital_controls        INTEGER DEFAULT 0
);

-- ── Scenarios ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scenarios (
    id                      INTEGER PRIMARY KEY,
    scenario_name           TEXT NOT NULL UNIQUE,
    scenario_type           TEXT NOT NULL,   -- Historical, Hypothetical, Regulatory
    description             TEXT,
    reference_date          TEXT,
    -- Rate shocks (bps)
    usd_rates_shock_bps     REAL DEFAULT 0,
    gbp_rates_shock_bps     REAL DEFAULT 0,
    cny_rates_shock_bps     REAL DEFAULT 0,
    brl_rates_shock_bps     REAL DEFAULT 0,
    zar_rates_shock_bps     REAL DEFAULT 0,
    -- FX shocks (%, + means local ccy weakens vs USD)
    gbpusd_shock_pct        REAL DEFAULT 0,
    usdcny_shock_pct        REAL DEFAULT 0,
    usdbrl_shock_pct        REAL DEFAULT 0,
    usdzar_shock_pct        REAL DEFAULT 0,
    -- Equity shocks (%)
    us_equity_shock_pct     REAL DEFAULT 0,
    uk_equity_shock_pct     REAL DEFAULT 0,
    cn_equity_shock_pct     REAL DEFAULT 0,
    br_equity_shock_pct     REAL DEFAULT 0,
    za_equity_shock_pct     REAL DEFAULT 0,
    -- Credit spread shocks (bps)
    ig_spread_shock_bps     REAL DEFAULT 0,
    hy_spread_shock_bps     REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id                      INTEGER PRIMARY KEY,
    scenario_id             INTEGER NOT NULL REFERENCES scenarios(id),
    desk                    TEXT,
    product                 TEXT,
    pnl_impact_usd          REAL NOT NULL,   -- USD millions
    credit_loss_usd         REAL DEFAULT 0,
    var_breached            INTEGER DEFAULT 0,
    notes                   TEXT,
    UNIQUE(scenario_id, desk, product)
);
"""


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print("Database schema initialised.")
