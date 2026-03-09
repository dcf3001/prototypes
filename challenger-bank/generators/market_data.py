"""
Generate 5 years of daily market data (2021-01-04 → 2025-12-31).

Assets generated
────────────────
FX (USD per 1 unit, or units per USD where noted):
  GBPUSD   GBP/USD rate
  USDCNY   USD/CNY (CNY per USD)
  USDBRL   USD/BRL (BRL per USD)
  USDZAR   USD/ZAR (ZAR per USD)

Yield curves (% annualised spot rate):
  USD_2Y  USD_5Y  USD_10Y
  GBP_2Y  GBP_5Y  GBP_10Y
  CNY_2Y  CNY_5Y  CNY_10Y
  BRL_2Y  BRL_5Y  BRL_10Y
  ZAR_2Y  ZAR_5Y  ZAR_10Y

Equity indices (price level):
  US_SPX   S&P 500
  UK_FTSE  FTSE 100
  CN_CSI   CSI 300
  BR_IBOV  Ibovespa
  ZA_JSE   JSE Top 40

Credit spreads over risk-free (bps):
  CS_AA   CS_A   CS_BBB   CS_BB   CS_B   CS_CCC  (generic IG/HY market spreads)
"""
import numpy as np
from datetime import date, timedelta

RNG = np.random.default_rng(42)


# ── Trading calendar ─────────────────────────────────────────────────────────

def _bdays(start: str, end: str):
    """Return list of weekday date strings between start and end inclusive."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    days = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:  # Mon-Fri
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


# ── Vasicek mean-reverting rate simulation ────────────────────────────────────

def _vasicek(r0, kappa, theta_path, sigma, n, rng):
    """
    Simulate n daily steps with mean-reverting process.
    theta_path: array of length n giving the daily target (allows regime shifts).
    """
    dt = 1 / 252
    r = np.empty(n)
    r[0] = r0
    noise = rng.standard_normal(n)
    for i in range(1, n):
        r[i] = r[i-1] + kappa * (theta_path[i-1] - r[i-1]) * dt + sigma * np.sqrt(dt) * noise[i]
        r[i] = max(r[i], 0.001)   # floor at 0.1%
    return r


def _theta_path(n, waypoints):
    """
    Linearly interpolate between (day_index, target_rate) waypoints.
    waypoints: list of (idx, rate) sorted by idx.
    """
    path = np.empty(n)
    for j in range(len(waypoints) - 1):
        i0, r0 = waypoints[j]
        i1, r1 = waypoints[j + 1]
        path[i0:i1] = np.linspace(r0, r1, i1 - i0)
    # fill any trailing
    path[waypoints[-1][0]:] = waypoints[-1][1]
    return path


# ── GBM for equity / FX ───────────────────────────────────────────────────────

def _gbm(s0, mu_annual, sigma_annual, n, rng):
    """Standard GBM, returns n prices."""
    dt = 1 / 252
    z = rng.standard_normal(n)
    log_r = (mu_annual - 0.5 * sigma_annual ** 2) * dt + sigma_annual * np.sqrt(dt) * z
    prices = s0 * np.exp(np.cumsum(log_r))
    return prices


# ── Credit spreads (mean-reverting) ──────────────────────────────────────────

def _spread_path(base_bps, kappa, sigma_bps, n, rng):
    theta = np.full(n, base_bps / 100)   # convert to % for Vasicek
    path = _vasicek(base_bps / 100, kappa, theta, sigma_bps / 100, n, rng) * 100
    return np.maximum(path, 1.0)          # floor at 1 bp


# ── Main generation function ──────────────────────────────────────────────────

def generate_market_data():
    """Return list of dicts ready for bulk insert into market_data."""
    days = _bdays("2021-01-04", "2025-12-31")
    n = len(days)
    rows = []

    def _add(asset_id, asset_type, currency, values):
        for i, d in enumerate(days):
            rows.append({
                "asset_id":   asset_id,
                "asset_type": asset_type,
                "currency":   currency,
                "price_date": d,
                "value":      round(float(values[i]), 6),
            })

    # ── Interest rate target paths (% annualised) ─────────────────────────────
    # USD 10Y: pandemic low → Fed hiking → plateau
    _wp_usd10 = [(0, 0.015), (250, 0.018), (500, 0.039), (670, 0.050), (750, 0.043), (n-1, 0.045)]
    # USD 2Y (tracks Fed Funds more closely)
    _wp_usd2  = [(0, 0.013), (250, 0.010), (500, 0.046), (670, 0.054), (750, 0.044), (n-1, 0.042)]
    # USD 5Y
    _wp_usd5  = [(0, 0.014), (250, 0.014), (500, 0.042), (670, 0.048), (750, 0.043), (n-1, 0.044)]
    # GBP (BoE followed similar path, slightly higher)
    _wp_gbp10 = [(0, 0.010), (250, 0.012), (500, 0.040), (670, 0.048), (750, 0.040), (n-1, 0.047)]
    _wp_gbp2  = [(0, 0.008), (250, 0.008), (500, 0.045), (670, 0.054), (750, 0.043), (n-1, 0.045)]
    _wp_gbp5  = [(0, 0.009), (250, 0.010), (500, 0.043), (670, 0.050), (750, 0.041), (n-1, 0.046)]
    # CNY (PBOC easing: gentle decline)
    _wp_cny10 = [(0, 0.031), (500, 0.025), (n-1, 0.021)]
    _wp_cny5  = [(0, 0.030), (500, 0.023), (n-1, 0.019)]
    _wp_cny2  = [(0, 0.028), (500, 0.021), (n-1, 0.016)]
    # BRL (Selic: high, volatile, some easing late)
    _wp_brl10 = [(0, 0.110), (200, 0.130), (500, 0.140), (750, 0.125), (n-1, 0.135)]
    _wp_brl5  = [(0, 0.108), (200, 0.128), (500, 0.136), (750, 0.120), (n-1, 0.130)]
    _wp_brl2  = [(0, 0.105), (200, 0.125), (500, 0.132), (750, 0.115), (n-1, 0.125)]
    # ZAR (SARB: moderately high, stable-ish)
    _wp_zar10 = [(0, 0.095), (300, 0.110), (600, 0.100), (n-1, 0.105)]
    _wp_zar5  = [(0, 0.090), (300, 0.105), (600, 0.095), (n-1, 0.100)]
    _wp_zar2  = [(0, 0.085), (300, 0.100), (600, 0.090), (n-1, 0.093)]

    def _rate(r0, wp, kappa, sigma):
        tp = _theta_path(n, wp)
        return _vasicek(r0, kappa, tp, sigma, n, RNG)

    # USD rates
    usd10 = _rate(0.015, _wp_usd10, kappa=0.35, sigma=0.007)
    usd5  = _rate(0.014, _wp_usd5,  kappa=0.35, sigma=0.007)
    usd2  = _rate(0.013, _wp_usd2,  kappa=0.45, sigma=0.008)
    _add("USD_10Y", "Rate", "USD", usd10 * 100)
    _add("USD_5Y",  "Rate", "USD", usd5  * 100)
    _add("USD_2Y",  "Rate", "USD", usd2  * 100)

    # GBP rates
    gbp10 = _rate(0.010, _wp_gbp10, kappa=0.35, sigma=0.006)
    gbp5  = _rate(0.009, _wp_gbp5,  kappa=0.35, sigma=0.006)
    gbp2  = _rate(0.008, _wp_gbp2,  kappa=0.45, sigma=0.007)
    _add("GBP_10Y", "Rate", "GBP", gbp10 * 100)
    _add("GBP_5Y",  "Rate", "GBP", gbp5  * 100)
    _add("GBP_2Y",  "Rate", "GBP", gbp2  * 100)

    # CNY rates
    cny10 = _rate(0.031, _wp_cny10, kappa=0.40, sigma=0.003)
    cny5  = _rate(0.030, _wp_cny5,  kappa=0.40, sigma=0.003)
    cny2  = _rate(0.028, _wp_cny2,  kappa=0.40, sigma=0.003)
    _add("CNY_10Y", "Rate", "CNY", cny10 * 100)
    _add("CNY_5Y",  "Rate", "CNY", cny5  * 100)
    _add("CNY_2Y",  "Rate", "CNY", cny2  * 100)

    # BRL rates (higher vol)
    brl10 = _rate(0.110, _wp_brl10, kappa=0.25, sigma=0.015)
    brl5  = _rate(0.108, _wp_brl5,  kappa=0.25, sigma=0.015)
    brl2  = _rate(0.105, _wp_brl2,  kappa=0.30, sigma=0.016)
    _add("BRL_10Y", "Rate", "BRL", brl10 * 100)
    _add("BRL_5Y",  "Rate", "BRL", brl5  * 100)
    _add("BRL_2Y",  "Rate", "BRL", brl2  * 100)

    # ZAR rates
    zar10 = _rate(0.095, _wp_zar10, kappa=0.30, sigma=0.010)
    zar5  = _rate(0.090, _wp_zar5,  kappa=0.30, sigma=0.010)
    zar2  = _rate(0.085, _wp_zar2,  kappa=0.30, sigma=0.010)
    _add("ZAR_10Y", "Rate", "ZAR", zar10 * 100)
    _add("ZAR_5Y",  "Rate", "ZAR", zar5  * 100)
    _add("ZAR_2Y",  "Rate", "ZAR", zar2  * 100)

    # ── FX rates ──────────────────────────────────────────────────────────────
    # GBP/USD: GBP weakens from 1.37 to ~1.27
    gbpusd = _gbm(1.367, -0.008, 0.075, n, RNG)
    # USD/CNY: CNY weakens; USDCNY rises 6.47 → ~7.15
    usdcny = _gbm(6.47,  0.018,  0.040, n, RNG)
    # USD/BRL: BRL volatile, slight appreciation
    usdbrl = _gbm(5.40, -0.008,  0.140, n, RNG)
    # USD/ZAR: ZAR weakens 15.5 → ~18.5
    usdzar = _gbm(15.50,  0.025,  0.110, n, RNG)

    _add("GBPUSD", "FX", "USD", gbpusd)
    _add("USDCNY", "FX", "CNY", usdcny)
    _add("USDBRL", "FX", "BRL", usdbrl)
    _add("USDZAR", "FX", "ZAR", usdzar)

    # ── Equity indices ────────────────────────────────────────────────────────
    spx  = _gbm(3756,   0.115, 0.180, n, RNG)   # S&P 500
    ftse = _gbm(6720,   0.045, 0.140, n, RNG)   # FTSE 100
    csi  = _gbm(5211,   0.015, 0.200, n, RNG)   # CSI 300
    ibov = _gbm(119345, 0.055, 0.210, n, RNG)   # Ibovespa
    jse  = _gbm(58967,  0.075, 0.175, n, RNG)   # JSE Top 40

    _add("US_SPX",  "Equity", "USD", spx)
    _add("UK_FTSE", "Equity", "GBP", ftse)
    _add("CN_CSI",  "Equity", "CNY", csi)
    _add("BR_IBOV", "Equity", "BRL", ibov)
    _add("ZA_JSE",  "Equity", "ZAR", jse)

    # ── Credit spreads (bps, generic market) ──────────────────────────────────
    # Base spreads post-pandemic: tighten in 2021, widen 2022 (Fed hike), normalise
    cs_aa  = _spread_path(15,   kappa=1.5, sigma_bps=2,   n=n, rng=RNG)
    cs_a   = _spread_path(35,   kappa=1.2, sigma_bps=4,   n=n, rng=RNG)
    cs_bbb = _spread_path(90,   kappa=1.0, sigma_bps=8,   n=n, rng=RNG)
    cs_bb  = _spread_path(220,  kappa=0.8, sigma_bps=18,  n=n, rng=RNG)
    cs_b   = _spread_path(420,  kappa=0.7, sigma_bps=35,  n=n, rng=RNG)
    cs_ccc = _spread_path(900,  kappa=0.5, sigma_bps=80,  n=n, rng=RNG)

    _add("CS_AA",  "CreditSpread", "USD", cs_aa)
    _add("CS_A",   "CreditSpread", "USD", cs_a)
    _add("CS_BBB", "CreditSpread", "USD", cs_bbb)
    _add("CS_BB",  "CreditSpread", "USD", cs_bb)
    _add("CS_B",   "CreditSpread", "USD", cs_b)
    _add("CS_CCC", "CreditSpread", "USD", cs_ccc)

    return rows


def insert_market_data(conn):
    rows = generate_market_data()
    conn.executemany("""
        INSERT OR IGNORE INTO market_data (asset_id, asset_type, currency, price_date, value)
        VALUES (:asset_id, :asset_type, :currency, :price_date, :value)
    """, rows)
    conn.commit()
    print(f"  Inserted {len(rows):,} market data rows ({len(rows) // 31} days × 31 assets approx).")
    return rows


def latest_market(conn):
    """Return dict of asset_id → latest value (used by other generators)."""
    cur = conn.execute("""
        SELECT asset_id, value FROM market_data
        WHERE price_date = (SELECT MAX(price_date) FROM market_data)
    """)
    return {row["asset_id"]: row["value"] for row in cur.fetchall()}
