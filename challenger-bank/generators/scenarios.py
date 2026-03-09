"""
Seed 8 stress scenarios and compute approximate P&L impacts.
Scenario P&L is computed from desk-level aggregate positions
(net DV01, net notional, etc.) against the scenario shocks.
"""
import json
import math

SCENARIOS = [
    dict(
        scenario_name="2008 Global Financial Crisis",
        scenario_type="Historical",
        description="Replication of Oct 2008 Lehman collapse shock: severe equity drawdown, credit crunch, flight to quality in rates.",
        reference_date="2008-10-10",
        usd_rates_shock_bps=-150,  gbp_rates_shock_bps=-100,
        cny_rates_shock_bps=-50,   brl_rates_shock_bps=+200,  zar_rates_shock_bps=+300,
        gbpusd_shock_pct=-20,      usdcny_shock_pct=+2,
        usdbrl_shock_pct=+40,      usdzar_shock_pct=+30,
        us_equity_shock_pct=-40,   uk_equity_shock_pct=-35,
        cn_equity_shock_pct=-55,   br_equity_shock_pct=-45,   za_equity_shock_pct=-40,
        ig_spread_shock_bps=+300,  hy_spread_shock_bps=+800,
    ),
    dict(
        scenario_name="2020 COVID-19 Shock",
        scenario_type="Historical",
        description="March 2020 pandemic shock: sharp equity sell-off, rates fall, credit widens.",
        reference_date="2020-03-23",
        usd_rates_shock_bps=-100,  gbp_rates_shock_bps=-75,
        cny_rates_shock_bps=-40,   brl_rates_shock_bps=+150,  zar_rates_shock_bps=+200,
        gbpusd_shock_pct=-8,       usdcny_shock_pct=+1,
        usdbrl_shock_pct=+25,      usdzar_shock_pct=+20,
        us_equity_shock_pct=-32,   uk_equity_shock_pct=-34,
        cn_equity_shock_pct=-12,   br_equity_shock_pct=-45,   za_equity_shock_pct=-38,
        ig_spread_shock_bps=+200,  hy_spread_shock_bps=+600,
    ),
    dict(
        scenario_name="2022 Russia-Ukraine Energy Crisis",
        scenario_type="Historical",
        description="Feb-Mar 2022 invasion shock: energy spike, European recession fears, EM stress.",
        reference_date="2022-03-08",
        usd_rates_shock_bps=+50,   gbp_rates_shock_bps=+60,
        cny_rates_shock_bps=-10,   brl_rates_shock_bps=+80,   zar_rates_shock_bps=+100,
        gbpusd_shock_pct=-5,       usdcny_shock_pct=+1,
        usdbrl_shock_pct=+8,       usdzar_shock_pct=+10,
        us_equity_shock_pct=-12,   uk_equity_shock_pct=-18,
        cn_equity_shock_pct=-8,    br_equity_shock_pct=-10,   za_equity_shock_pct=-12,
        ig_spread_shock_bps=+80,   hy_spread_shock_bps=+220,
    ),
    dict(
        scenario_name="Fed Rate Shock +200bps",
        scenario_type="Hypothetical",
        description="Instantaneous parallel shift up of USD yield curve by 200bps, triggering risk-off across asset classes.",
        reference_date=None,
        usd_rates_shock_bps=+200,  gbp_rates_shock_bps=+150,
        cny_rates_shock_bps=+30,   brl_rates_shock_bps=+100,  zar_rates_shock_bps=+120,
        gbpusd_shock_pct=-4,       usdcny_shock_pct=+2,
        usdbrl_shock_pct=+10,      usdzar_shock_pct=+8,
        us_equity_shock_pct=-20,   uk_equity_shock_pct=-15,
        cn_equity_shock_pct=-10,   br_equity_shock_pct=-12,   za_equity_shock_pct=-10,
        ig_spread_shock_bps=+80,   hy_spread_shock_bps=+200,
    ),
    dict(
        scenario_name="China Hard Landing",
        scenario_type="Hypothetical",
        description="Sharp Chinese growth slowdown: CSI -30%, CNY devaluation, commodity price collapse, EM contagion.",
        reference_date=None,
        usd_rates_shock_bps=-30,   gbp_rates_shock_bps=-20,
        cny_rates_shock_bps=-80,   brl_rates_shock_bps=+150,  zar_rates_shock_bps=+200,
        gbpusd_shock_pct=-3,       usdcny_shock_pct=+8,
        usdbrl_shock_pct=+15,      usdzar_shock_pct=+12,
        us_equity_shock_pct=-12,   uk_equity_shock_pct=-10,
        cn_equity_shock_pct=-30,   br_equity_shock_pct=-20,   za_equity_shock_pct=-18,
        ig_spread_shock_bps=+60,   hy_spread_shock_bps=+180,
    ),
    dict(
        scenario_name="EM Currency Crisis",
        scenario_type="Hypothetical",
        description="Sudden EM capital outflow: BRL and ZAR depreciate 25-30%, local rates spike sharply.",
        reference_date=None,
        usd_rates_shock_bps=+20,   gbp_rates_shock_bps=+10,
        cny_rates_shock_bps=+20,   brl_rates_shock_bps=+300,  zar_rates_shock_bps=+250,
        gbpusd_shock_pct=-1,       usdcny_shock_pct=+3,
        usdbrl_shock_pct=+30,      usdzar_shock_pct=+25,
        us_equity_shock_pct=-6,    uk_equity_shock_pct=-5,
        cn_equity_shock_pct=-8,    br_equity_shock_pct=-25,   za_equity_shock_pct=-20,
        ig_spread_shock_bps=+40,   hy_spread_shock_bps=+120,
    ),
    dict(
        scenario_name="Stagflation Shock",
        scenario_type="Hypothetical",
        description="Persistent inflation forces aggressive rate hikes while growth stalls; equities re-price lower.",
        reference_date=None,
        usd_rates_shock_bps=+150,  gbp_rates_shock_bps=+140,
        cny_rates_shock_bps=+40,   brl_rates_shock_bps=+200,  zar_rates_shock_bps=+180,
        gbpusd_shock_pct=-6,       usdcny_shock_pct=+2,
        usdbrl_shock_pct=+15,      usdzar_shock_pct=+12,
        us_equity_shock_pct=-25,   uk_equity_shock_pct=-22,
        cn_equity_shock_pct=-15,   br_equity_shock_pct=-18,   za_equity_shock_pct=-16,
        ig_spread_shock_bps=+100,  hy_spread_shock_bps=+250,
    ),
    dict(
        scenario_name="Credit Crunch",
        scenario_type="Hypothetical",
        description="Systemic credit event causes spreads to gap wider; government bonds rally as flight-to-quality ensues.",
        reference_date=None,
        usd_rates_shock_bps=-100,  gbp_rates_shock_bps=-80,
        cny_rates_shock_bps=-20,   brl_rates_shock_bps=+100,  zar_rates_shock_bps=+120,
        gbpusd_shock_pct=-8,       usdcny_shock_pct=+2,
        usdbrl_shock_pct=+20,      usdzar_shock_pct=+15,
        us_equity_shock_pct=-30,   uk_equity_shock_pct=-28,
        cn_equity_shock_pct=-20,   br_equity_shock_pct=-30,   za_equity_shock_pct=-25,
        ig_spread_shock_bps=+300,  hy_spread_shock_bps=+700,
    ),
]


def insert_scenarios(conn):
    conn.executemany("""
        INSERT OR IGNORE INTO scenarios
        (scenario_name, scenario_type, description, reference_date,
         usd_rates_shock_bps, gbp_rates_shock_bps, cny_rates_shock_bps,
         brl_rates_shock_bps, zar_rates_shock_bps,
         gbpusd_shock_pct, usdcny_shock_pct, usdbrl_shock_pct, usdzar_shock_pct,
         us_equity_shock_pct, uk_equity_shock_pct, cn_equity_shock_pct,
         br_equity_shock_pct, za_equity_shock_pct,
         ig_spread_shock_bps, hy_spread_shock_bps)
        VALUES
        (:scenario_name,:scenario_type,:description,:reference_date,
         :usd_rates_shock_bps,:gbp_rates_shock_bps,:cny_rates_shock_bps,
         :brl_rates_shock_bps,:zar_rates_shock_bps,
         :gbpusd_shock_pct,:usdcny_shock_pct,:usdbrl_shock_pct,:usdzar_shock_pct,
         :us_equity_shock_pct,:uk_equity_shock_pct,:cn_equity_shock_pct,
         :br_equity_shock_pct,:za_equity_shock_pct,
         :ig_spread_shock_bps,:hy_spread_shock_bps)
    """, SCENARIOS)
    conn.commit()

    # ── Compute scenario results from positions ────────────────────────────────
    scenario_ids = {row["scenario_name"]: row["id"]
                    for row in conn.execute("SELECT id, scenario_name FROM scenarios").fetchall()}

    positions = conn.execute("SELECT * FROM positions WHERE snapshot_date='2025-12-31'").fetchall()

    results = []
    for sc in SCENARIOS:
        sc_id = scenario_ids[sc["scenario_name"]]

        # Aggregate desk-level P&L
        desk_pnl = {}
        for pos in positions:
            desk = pos["desk"]
            pnl  = 0.0

            # Rates shock impact via DV01
            dv01 = pos["net_dv01"] or 0
            if desk == "Rates" or pos["product"] in ("IRS","XCS","Government Bond"):
                shock = sc["usd_rates_shock_bps"]   # simplified: use USD shock
                pnl += -dv01 * shock   # DV01 is price-change per bp upward move (negative for long)

            # Credit spread impact via CS01
            cs01 = pos["net_cs01"] or 0
            ig_shock = sc["ig_spread_shock_bps"]
            hy_shock = sc["hy_spread_shock_bps"]
            avg_shock = (ig_shock + hy_shock) / 2
            if desk in ("Credit",):
                pnl += -cs01 * avg_shock

            # Equity impact via notional × delta approximation
            if desk in ("Equity Derivatives",):
                eq_shock = sc["us_equity_shock_pct"] / 100
                notional = pos["net_notional_usd"] or 0
                pnl += notional * eq_shock * 0.5  # average delta

            # FX desk: net notional × FX shock
            if desk == "FX":
                # Mixed exposure, use average FX shock
                avg_fx = (abs(sc["gbpusd_shock_pct"]) + abs(sc["usdbrl_shock_pct"]) +
                          abs(sc["usdzar_shock_pct"])) / 3 / 100
                notional = abs(pos["net_notional_usd"] or 0)
                pnl -= notional * avg_fx * 0.3  # hedged, so partial impact

            # Fixed income
            if desk == "Fixed Income":
                shock = sc["usd_rates_shock_bps"]
                pnl += -dv01 * shock

            # Commodity
            if desk == "Commodities":
                # Commodity prices tend to fall in risk-off except stagflation
                comm_shock = -0.15 if sc["us_equity_shock_pct"] < -20 else -0.05
                notional = pos["net_notional_usd"] or 0
                pnl += notional * comm_shock * 0.2

            desk_pnl[desk] = desk_pnl.get(desk, 0.0) + pnl

        for desk, pnl in desk_pnl.items():
            results.append({
                "scenario_id":       sc_id,
                "desk":              desk,
                "product":           None,
                "pnl_impact_usd":    round(pnl / 1000, 2),   # convert to M USD
                "credit_loss_usd":   0.0,
                "var_breached":      1 if abs(pnl / 1000) > 50 else 0,
                "notes":             None,
            })

        # Portfolio total
        total_pnl = sum(desk_pnl.values())
        results.append({
            "scenario_id":    sc_id,
            "desk":           None,
            "product":        None,
            "pnl_impact_usd": round(total_pnl / 1000, 2),
            "credit_loss_usd":0.0,
            "var_breached":   1 if abs(total_pnl / 1000) > 200 else 0,
            "notes":          f"Portfolio total stressed P&L: {total_pnl/1000:.1f}M USD",
        })

    conn.executemany("""
        INSERT OR IGNORE INTO scenario_results
        (scenario_id, desk, product, pnl_impact_usd, credit_loss_usd, var_breached, notes)
        VALUES
        (:scenario_id,:desk,:product,:pnl_impact_usd,:credit_loss_usd,:var_breached,:notes)
    """, results)
    conn.commit()
    print(f"  Inserted {len(SCENARIOS)} scenarios, {len(results)} scenario result rows.")
