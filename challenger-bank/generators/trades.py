"""
Generate the trading book blotter (~600-700 trades across ~40 active counterparties).
Products: IRS, Cross-Currency Swap (XCS), FX Forward, FX Option, CDS,
          Equity Option, Government Bond, Corporate Bond.

MtM is approximated from current market conditions (end-2025 values).
All monetary amounts in USD millions unless stated.
"""
import json
import math
import random
from datetime import date, timedelta
from generators.counterparties import PD_BY_RATING, SPREAD_BY_RATING, RAW

RNG = random.Random(21)

# End-2025 market snapshot (approximate) used for MtM
MKT = {
    "USD_10Y": 4.45,   # %
    "USD_5Y":  4.30,
    "USD_2Y":  4.20,
    "GBP_10Y": 4.70,
    "GBP_5Y":  4.50,
    "GBP_2Y":  4.45,
    "CNY_10Y": 2.10,
    "CNY_5Y":  2.00,
    "BRL_10Y": 13.5,
    "ZAR_10Y": 10.5,
    "GBPUSD":  1.27,
    "USDCNY":  7.15,
    "USDBRL":  5.10,
    "USDZAR":  18.50,
    "US_SPX":  5800,
    "UK_FTSE": 8400,
    "CN_CSI":  3900,
}

# FX end-2025: local ccy per USD (for USD-equivalent notional)
FX_TO_USD = {"USD": 1.0, "GBP": 1/1.27, "CNY": 1/7.15, "BRL": 1/5.10, "ZAR": 1/18.5}

# Which counterparties have trading relationships (most FIs + large corporates)
# Determined by sector + size
TRADING_SECTORS = {"Financial", "Energy", "TMT", "Healthcare", "Industrials", "Consumer"}

# Desks and the products they trade
DESK_PRODUCTS = {
    "Rates":             ["IRS", "XCS", "Swaption"],
    "FX":                ["FX Forward", "FX Option", "NDF"],
    "Credit":            ["CDS", "Corporate Bond"],
    "Equity Derivatives":["Equity Option", "Equity TRS"],
    "Fixed Income":      ["Government Bond", "Corporate Bond"],
    "Commodities":       ["Commodity Forward", "Commodity Option"],
}

CURRENCY_PAIRS = {
    "USD": [("USD", "GBP"), ("USD", "CNY"), ("USD", "BRL"), ("USD", "ZAR")],
    "GBP": [("GBP", "USD"), ("GBP", "EUR")],
    "CNY": [("CNY", "USD")],
    "BRL": [("BRL", "USD")],
    "ZAR": [("ZAR", "USD")],
}

# Floating indices by currency
FLOAT_INDEX = {"USD": "SOFR", "GBP": "SONIA", "CNY": "SHIBOR", "BRL": "CDI", "ZAR": "JIBAR"}

_trade_counter = [0]


def _next_id():
    _trade_counter[0] += 1
    return f"CHB-{_trade_counter[0]:05d}"


def _rand_date(yr1, yr2):
    s = date(yr1, 1, 1)
    e = date(yr2, 12, 31)
    return s + timedelta(days=RNG.randint(0, (e - s).days))


def _mat_from_trade(trade_date, tenor_days):
    return trade_date + timedelta(days=tenor_days)


# ── MtM approximations ────────────────────────────────────────────────────────

def _irs_mtm(direction, notional_m, fixed_rate, ccy, tenor_y):
    """
    IRS: pay fixed vs float.
    MtM ≈ (current_rate - fixed_rate) × DV01
    DV01 (USD per bp per $1M notional) ≈ tenor_y × 100  (very rough)
    If direction = Pay (we pay fixed): profit when rates rise.
    """
    key = f"{ccy}_10Y" if tenor_y >= 7 else (f"{ccy}_5Y" if tenor_y >= 3 else f"{ccy}_2Y")
    curr_rate = MKT.get(key, 4.0)
    dv01 = tenor_y * 90.0   # USD per bp for $1M notional
    # P&L in USD M = rate_diff_bps × DV01_full / 1e6
    # rate_diff_bps = (curr_rate - fixed_rate) * 100;  DV01_full = dv01 * notional_m
    mtm = (curr_rate - fixed_rate) * dv01 * notional_m / 10000
    if direction == "Receive":
        mtm = -mtm
    return round(mtm, 3), round(dv01 * notional_m / 1e6, 4)   # MtM USD M, DV01 USD M/bp


def _fx_fwd_mtm(direction, notional_m, forward_rate, spot_ccy, quote_ccy):
    """
    FX Forward MtM in USD millions.
    notional_m: notional in millions of the local (non-USD) currency.
    Returns P&L in USD millions.
    """
    if quote_ccy == "USD":
        # e.g. GBPUSD: fwd 1.30, now 1.27; notional in GBP millions
        spot_key = f"{spot_ccy}USD"
        curr = MKT.get(spot_key, 1.0)
        # P&L = (curr - fwd) × GBP notional → already in USD
        pnl = (curr - forward_rate) * notional_m / 1000
    else:
        # e.g. USDBRL: fwd 5.20, now 5.10; notional in local-ccy millions
        pair_key = f"USD{quote_ccy}"
        curr = MKT.get(pair_key, 1.0)
        # local notional / local_rate = USD millions; P&L = Δrate × usd_notional
        usd_notional = notional_m / curr
        pnl = (curr - forward_rate) / curr * usd_notional / 1000
    if direction == "Short":
        pnl = -pnl
    return round(pnl, 3)


def _cds_mtm(direction, notional_m, initial_spread_bps, curr_spread_bps):
    """
    CDS protection buyer: profit when spreads widen.
    CS01 ≈ 4.5 (duration-ish, roughly 5y)
    MtM ≈ (curr - initial) * CS01 per bp
    """
    cs01 = 4.5 * notional_m / 100   # USD M per bp
    mtm  = (curr_spread_bps - initial_spread_bps) * cs01 / 100
    if direction == "Sell":   # protection seller profits when spreads tighten
        mtm = -mtm
    return round(mtm, 3), round(cs01 / 100, 3)


def _equity_opt_mtm(direction, notional_m, delta, spot_return_pct):
    """Equity option: approximate P&L via delta approximation."""
    pnl = delta * spot_return_pct / 100 * notional_m
    if direction == "Short":
        pnl = -pnl
    return round(pnl, 3)


def _bond_mtm(direction, notional_m, purchase_yield, curr_yield, duration_y):
    """Bond: P&L ≈ -duration × Δyield × notional."""
    dy = (curr_yield - purchase_yield) / 100
    mtm = -duration_y * dy * notional_m
    dv01 = duration_y * notional_m / 1e4
    if direction == "Short":
        mtm = -mtm; dv01 = -dv01
    return round(mtm, 3), round(dv01, 2)


# ── Trade generators per product ─────────────────────────────────────────────

def _make_irs(cp, n=1):
    trades = []
    ccy  = cp["currency"] if cp["currency"] in ("USD","GBP") else "USD"
    for _ in range(n):
        trade_date = _rand_date(2021, 2024)
        tenor_y    = RNG.choice([2, 3, 5, 7, 10])
        mat_date   = _mat_from_trade(trade_date, tenor_y * 365)
        notional_m = round(RNG.uniform(50, 400), 0)
        # Fixed rate near prevailing rate at trade date (rough)
        base_rate  = {"2021": 1.2, "2022": 2.8, "2023": 4.5, "2024": 4.2}.get(str(trade_date.year), 2.5)
        fixed_rate = round(base_rate + RNG.uniform(-0.3, 0.5), 3)
        direction  = RNG.choice(["Pay", "Receive"])
        mtm, dv01  = _irs_mtm(direction, notional_m, fixed_rate, ccy, tenor_y)
        notional_usd = notional_m * FX_TO_USD.get(ccy, 1)
        live = mat_date > date(2026, 1, 1)
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          "Rates",
            "product":       "IRS",
            "direction":     direction,
            "currency":      ccy,
            "notional":      notional_m,
            "notional_usd":  round(notional_usd, 2),
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    fixed_rate,
            "floating_index":FLOAT_INDEX.get(ccy, "SOFR"),
            "strike":        None,
            "delta":         None,
            "mark_to_market": mtm,
            "dv01":          dv01,
            "cs01":          None,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"IRS {direction} fixed {fixed_rate}% vs {FLOAT_INDEX.get(ccy,'SOFR')}, {notional_m:.0f}M {ccy}, {tenor_y}Y tenor.",
            "risk_tags":     json.dumps(["irs", "rates", direction.lower(), ccy.lower()]),
        })
    return trades


def _make_fx_fwd(cp, n=1):
    trades = []
    ccy  = cp["currency"]
    # Pair: local vs USD (or GBP vs USD for UK)
    for _ in range(n):
        trade_date  = _rand_date(2022, 2025)
        tenor_days  = RNG.randint(30, 360)
        mat_date    = _mat_from_trade(trade_date, tenor_days)
        notional_m  = round(RNG.uniform(10, 150), 0)   # millions
        direction   = RNG.choice(["Long", "Short"])
        product     = "NDF" if ccy in ("CNY", "BRL", "ZAR") else "FX Forward"

        # Approximate forward rate at trade date
        if ccy == "GBP":
            fwd_key = "GBPUSD"
            fwd     = round(MKT["GBPUSD"] + RNG.uniform(-0.08, 0.08), 4)
            quote_ccy = "USD"
        elif ccy == "CNY":
            fwd_key = "USDCNY"
            fwd     = round(MKT["USDCNY"] + RNG.uniform(-0.30, 0.30), 4)
            quote_ccy = "CNY"
            notional_m = notional_m * MKT["USDCNY"]   # CNY notional
        elif ccy == "BRL":
            fwd_key = "USDBRL"
            fwd     = round(MKT["USDBRL"] + RNG.uniform(-0.50, 0.50), 4)
            quote_ccy = "BRL"
            notional_m = notional_m * MKT["USDBRL"]
        elif ccy == "ZAR":
            fwd_key = "USDZAR"
            fwd     = round(MKT["USDZAR"] + RNG.uniform(-1.5, 1.5), 4)
            quote_ccy = "ZAR"
            notional_m = notional_m * MKT["USDZAR"]
        else:
            fwd_key = "GBPUSD"
            fwd     = round(MKT["GBPUSD"] + RNG.uniform(-0.05, 0.05), 4)
            quote_ccy = "USD"

        mtm = _fx_fwd_mtm(direction, notional_m,
                           fwd,
                           "GBP" if ccy=="GBP" else "USD",
                           quote_ccy)
        notional_usd = notional_m * FX_TO_USD.get(ccy, 1)
        live = mat_date > date(2026, 1, 1)
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          "FX",
            "product":       product,
            "direction":     direction,
            "currency":      ccy,
            "notional":      round(notional_m, 0),
            "notional_usd":  round(notional_usd, 2),
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    round(fwd, 4),
            "floating_index":None,
            "strike":        None,
            "delta":         None,
            "mark_to_market": mtm,
            "dv01":          None,
            "cs01":          None,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"{product} {direction} {notional_m:.0f}M {ccy} at rate {fwd}, {tenor_days}d tenor.",
            "risk_tags":     json.dumps([product.lower().replace(" ", "-"), "fx", ccy.lower()]),
        })
    return trades


def _make_cds(cp, n=1):
    trades = []
    for _ in range(n):
        trade_date  = _rand_date(2021, 2024)
        tenor_y     = RNG.choice([3, 5])
        mat_date    = _mat_from_trade(trade_date, tenor_y * 365)
        notional_m  = round(RNG.uniform(10, 100), 0)
        direction   = RNG.choice(["Buy", "Sell"])
        rating      = cp["internal_rating"]
        init_spread = SPREAD_BY_RATING.get(rating, 200) + RNG.uniform(-20, 20)
        curr_spread = SPREAD_BY_RATING.get(rating, 200) + RNG.uniform(-30, 30)
        mtm, cs01   = _cds_mtm(direction, notional_m, init_spread, curr_spread)
        live = mat_date > date(2026, 1, 1)
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          "Credit",
            "product":       "CDS",
            "direction":     direction,
            "currency":      "USD",
            "notional":      notional_m,
            "notional_usd":  notional_m,
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    round(init_spread, 1),
            "floating_index":None,
            "strike":        None,
            "delta":         None,
            "mark_to_market": mtm,
            "dv01":          None,
            "cs01":          cs01,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"CDS {direction} protection {notional_m:.0f}M USD on {cp['name']}, {tenor_y}Y at {init_spread:.0f}bps.",
            "risk_tags":     json.dumps(["cds", "credit", direction.lower()]),
        })
    return trades


def _make_bond(cp, n=1):
    trades = []
    ccy  = cp["currency"] if cp["currency"] in ("USD","GBP") else "USD"
    for _ in range(n):
        is_gov = RNG.random() < 0.4
        desk   = "Fixed Income"
        product= "Government Bond" if is_gov else "Corporate Bond"
        trade_date = _rand_date(2020, 2024)
        mat_date   = _mat_from_trade(trade_date, RNG.randint(3*365, 10*365))
        notional_m = round(RNG.uniform(10, 200), 0)
        direction  = RNG.choice(["Long", "Short"])
        purch_yld  = MKT[f"{ccy}_10Y"] + RNG.uniform(-1.5, 1.5) if not is_gov else MKT.get(f"{ccy}_10Y", 4.0) + RNG.uniform(-0.5, 0.5)
        curr_yld   = MKT.get(f"{ccy}_10Y", 4.0)
        duration_y = RNG.uniform(3.0, 8.5)
        mtm, dv01  = _bond_mtm(direction, notional_m, purch_yld, curr_yld, duration_y)
        notional_usd = notional_m * FX_TO_USD.get(ccy, 1)
        live = mat_date > date(2026, 1, 1)
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          desk,
            "product":       product,
            "direction":     direction,
            "currency":      ccy,
            "notional":      notional_m,
            "notional_usd":  round(notional_usd, 2),
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    round(purch_yld, 3),
            "floating_index":None,
            "strike":        None,
            "delta":         None,
            "mark_to_market": mtm,
            "dv01":          dv01,
            "cs01":          None,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"{product} {direction} {notional_m:.0f}M {ccy}, purchase yield {purch_yld:.2f}%, duration {duration_y:.1f}y.",
            "risk_tags":     json.dumps([product.lower().replace(" ", "-"), direction.lower(), ccy.lower()]),
        })
    return trades


def _make_eq_option(cp, n=1):
    trades = []
    ccy = cp["currency"] if cp["currency"] in ("USD","GBP","CNY") else "USD"
    eq_idx = {"USD":"US_SPX","GBP":"UK_FTSE","CNY":"CN_CSI"}.get(ccy,"US_SPX")
    for _ in range(n):
        trade_date  = _rand_date(2022, 2025)
        tenor_d     = RNG.randint(30, 365)
        mat_date    = _mat_from_trade(trade_date, tenor_d)
        notional_m  = round(RNG.uniform(5, 60), 0)
        direction   = RNG.choice(["Long", "Short"])
        delta       = round(RNG.uniform(0.20, 0.80), 2) * (1 if direction=="Long" else -1)
        # Spot return from trade date to now (approx)
        spot_ret    = RNG.uniform(-15, 25)   # %
        mtm         = _equity_opt_mtm(direction, notional_m, delta, spot_ret)
        notional_usd = notional_m * FX_TO_USD.get(ccy, 1)
        live = mat_date > date(2026, 1, 1)
        opt_type    = RNG.choice(["Call", "Put"])
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          "Equity Derivatives",
            "product":       "Equity Option",
            "direction":     direction,
            "currency":      ccy,
            "notional":      notional_m,
            "notional_usd":  round(notional_usd, 2),
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    None,
            "floating_index":eq_idx,
            "strike":        round(MKT.get(eq_idx, 5000) * RNG.uniform(0.90, 1.10), 1),
            "delta":         delta,
            "mark_to_market": mtm,
            "dv01":          None,
            "cs01":          None,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"Equity {opt_type} option ({direction}) on {eq_idx}, {notional_m:.0f}M {ccy}, delta {delta:.2f}.",
            "risk_tags":     json.dumps(["equity-option", opt_type.lower(), direction.lower(), eq_idx.lower()]),
        })
    return trades


def _make_commodity_fwd(cp, n=1):
    trades = []
    commodities = [("Oil", 75.0, 12.0), ("Gold", 2050.0, 180.0), ("Natural Gas", 3.5, 0.8)]
    for _ in range(n):
        comm, base_price, vol = RNG.choice(commodities)
        trade_date  = _rand_date(2022, 2025)
        tenor_d     = RNG.randint(30, 365)
        mat_date    = _mat_from_trade(trade_date, tenor_d)
        notional_m  = round(RNG.uniform(5, 80), 0)
        direction   = RNG.choice(["Long", "Short"])
        fwd_price   = round(base_price + RNG.uniform(-vol, vol), 2)
        curr_price  = round(base_price + RNG.uniform(-vol, vol), 2)
        mtm = (curr_price - fwd_price) / fwd_price * notional_m
        if direction == "Short":
            mtm = -mtm
        mtm = round(mtm, 3)
        live = mat_date > date(2026, 1, 1)
        trades.append({
            "trade_id":      _next_id(),
            "counterparty_id": cp["id"],
            "desk":          "Commodities",
            "product":       "Commodity Forward",
            "direction":     direction,
            "currency":      "USD",
            "notional":      notional_m,
            "notional_usd":  notional_m,
            "trade_date":    trade_date.isoformat(),
            "maturity_date": mat_date.isoformat(),
            "fixed_rate":    fwd_price,
            "floating_index":comm,
            "strike":        None,
            "delta":         None,
            "mark_to_market": mtm,
            "dv01":          None,
            "cs01":          None,
            "status":        "Live" if live else "Matured",
            "ai_summary":    f"{comm} Forward {direction} {notional_m:.0f}M USD at {fwd_price:.2f} $/unit.",
            "risk_tags":     json.dumps(["commodity-forward", comm.lower().replace(" ", "-"), direction.lower()]),
        })
    return trades


# ── Main generation ───────────────────────────────────────────────────────────

def _should_trade(raw):
    """Does this counterparty have a trading relationship with the bank?"""
    if raw["is_fi"]:
        return True
    if raw["sector"] in TRADING_SECTORS and (raw.get("rev_scale") or 0) > 3:
        return True
    # EM smaller names: FX only
    return raw["country_iso2"] in ("BR", "ZA", "CN")


def generate_trades(cp_rows):
    all_trades = []
    for cp in cp_rows:
        raw = RAW[cp["id"] - 1]
        if not _should_trade(raw):
            continue

        ccy    = cp["currency"]
        is_fi  = cp["is_financial_institution"]
        sector = cp["sector"]

        # IRS: rates-active counterparties
        if is_fi or sector in ("Financial", "Energy", "Real Estate"):
            n_irs = RNG.randint(2, 5)
            all_trades.extend(_make_irs(cp, n_irs))

        # FX forwards: nearly all (hedging)
        n_fx = RNG.randint(1, 4)
        all_trades.extend(_make_fx_fwd(cp, n_fx))

        # CDS: FIs and credit desk clients
        if is_fi or sector in ("Financial", "Energy", "TMT"):
            n_cds = RNG.randint(1, 3)
            all_trades.extend(_make_cds(cp, n_cds))

        # Bonds: FIs, TMT, Healthcare, Industrials
        if is_fi or sector in ("Financial", "TMT", "Healthcare", "Industrials", "Consumer"):
            n_bond = RNG.randint(1, 4)
            all_trades.extend(_make_bond(cp, n_bond))

        # Equity options: FIs and large US/UK names
        if (is_fi or sector in ("Financial","TMT","Healthcare")) and ccy in ("USD","GBP","CNY"):
            n_eq = RNG.randint(1, 3)
            all_trades.extend(_make_eq_option(cp, n_eq))

        # Commodity forwards: Energy, Mining, Consumer (hedging)
        if sector in ("Energy", "Mining", "Consumer", "Industrials"):
            n_comm = RNG.randint(1, 2)
            all_trades.extend(_make_commodity_fwd(cp, n_comm))

    return all_trades


def insert_trades(conn, cp_rows):
    trades = generate_trades(cp_rows)
    conn.executemany("""
        INSERT OR IGNORE INTO trades
        (trade_id, counterparty_id, desk, product, direction, currency,
         notional, notional_usd, trade_date, maturity_date,
         fixed_rate, floating_index, strike, delta,
         mark_to_market, dv01, cs01, status, ai_summary, risk_tags)
        VALUES
        (:trade_id,:counterparty_id,:desk,:product,:direction,:currency,
         :notional,:notional_usd,:trade_date,:maturity_date,
         :fixed_rate,:floating_index,:strike,:delta,
         :mark_to_market,:dv01,:cs01,:status,:ai_summary,:risk_tags)
    """, trades)

    # Build positions snapshot (aggregate by desk/product/currency)
    live = [t for t in trades if t["status"] == "Live"]
    pos_map = {}
    for t in live:
        key = (t["desk"], t["product"], t["currency"])
        if key not in pos_map:
            pos_map[key] = dict(net_notional_usd=0, net_mtm_usd=0,
                                net_dv01=0.0, net_cs01=0.0, trade_count=0)
        p = pos_map[key]
        sign = 1 if t["direction"] in ("Long","Pay","Buy") else -1
        p["net_notional_usd"] += t["notional_usd"] * sign
        p["net_mtm_usd"]      += t["mark_to_market"]
        p["net_dv01"]         += (t["dv01"] or 0) * sign
        p["net_cs01"]         += (t["cs01"] or 0) * sign
        p["trade_count"]      += 1

    today = "2025-12-31"
    pos_rows = []
    for (desk, product, ccy), p in pos_map.items():
        pos_rows.append({
            "snapshot_date":   today,
            "desk":            desk,
            "product":         product,
            "currency":        ccy,
            "net_notional_usd": round(p["net_notional_usd"], 2),
            "net_mtm_usd":     round(p["net_mtm_usd"], 3),
            "net_dv01":        round(p["net_dv01"], 2),
            "net_cs01":        round(p["net_cs01"], 4),
            "trade_count":     p["trade_count"],
        })

    conn.executemany("""
        INSERT OR IGNORE INTO positions
        (snapshot_date, desk, product, currency, net_notional_usd,
         net_mtm_usd, net_dv01, net_cs01, trade_count)
        VALUES
        (:snapshot_date,:desk,:product,:currency,:net_notional_usd,
         :net_mtm_usd,:net_dv01,:net_cs01,:trade_count)
    """, pos_rows)

    conn.commit()
    print(f"  Inserted {len(trades)} trades, {len(pos_rows)} position rows.")
    return trades
