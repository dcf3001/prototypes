"""
Master seed script — run once to build the full synthetic dataset.

Usage (from the challenger-bank/ directory):
    python -m generators.seed_all          # or
    python generators/seed_all.py
"""
import os
import sys
import time

# Allow running as script from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import init_db, get_db, DB_PATH
from generators.counterparties import insert_counterparties, insert_credit_ratings
from generators.market_data import insert_market_data
from generators.financials import insert_financials
from generators.credit_facilities import insert_credit_facilities
from generators.trades import insert_trades
from generators.risk_calcs import (
    insert_pd_history,
    insert_var_history,
    insert_pnl_attribution,
    insert_netting_sets,
    insert_ccr_metrics,
    insert_country_risk,
)
from generators.scenarios import insert_scenarios


def seed(force=False):
    if os.path.exists(DB_PATH) and not force:
        print(f"Database already exists at {DB_PATH}.")
        print("Pass force=True or delete the file to re-seed.")
        return

    if os.path.exists(DB_PATH) and force:
        os.remove(DB_PATH)
        print(f"Removed existing database.")

    t0 = time.time()
    print(f"\n{'='*60}")
    print("  Challenger Bank — Synthetic Dataset Generation")
    print(f"{'='*60}")

    print("\n[1/10] Initialising schema …")
    init_db()

    conn = get_db()

    print("[2/10] Counterparties + credit ratings …")
    cp_rows = insert_counterparties(conn)
    insert_credit_ratings(conn, cp_rows)

    print("[3/10] Market data (5y daily × 31 assets) …")
    insert_market_data(conn)

    print("[4/10] Annual financials (5y × 50 entities) …")
    insert_financials(conn)

    print("[5/10] Credit facilities + credit events …")
    insert_credit_facilities(conn, cp_rows)

    print("[6/10] Trade blotter + positions snapshot …")
    insert_trades(conn, cp_rows)

    print("[7/10] PD history (60 months × 50 counterparties) …")
    insert_pd_history(conn, cp_rows)

    print("[8/10] VaR history + P&L attribution (60 months) …")
    insert_var_history(conn)
    insert_pnl_attribution(conn)

    print("[9/10] CCR: netting sets, collateral, MtM, PFE, CVA, SA-CCR …")
    insert_netting_sets(conn, cp_rows)
    insert_ccr_metrics(conn, cp_rows)

    print("[9b/10] Country risk limits, exposures, transfer risk …")
    insert_country_risk(conn, cp_rows)

    print("[10/10] Scenarios + scenario results …")
    insert_scenarios(conn)

    conn.close()

    elapsed = time.time() - t0
    size_mb = os.path.getsize(DB_PATH) / 1_048_576
    print(f"\n{'='*60}")
    print(f"  Seeding complete in {elapsed:.1f}s")
    print(f"  Database: {DB_PATH}")
    print(f"  Size:     {size_mb:.1f} MB")
    print(f"{'='*60}\n")

    # Print summary row counts
    conn2 = get_db()
    tables = [
        "counterparties", "financials", "credit_ratings",
        "credit_facilities", "credit_events",
        "market_data", "trades", "positions",
        "pd_history", "var_history", "pnl_attribution",
        "netting_sets", "collateral", "mtm_exposure",
        "pfe_profiles", "cva_history", "sa_ccr",
        "country_exposures", "country_limits", "transfer_risk",
        "scenarios", "scenario_results",
    ]
    print(f"  {'Table':<30} {'Rows':>8}")
    print(f"  {'-'*40}")
    total = 0
    for t in tables:
        n = conn2.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        total += n
        print(f"  {t:<30} {n:>8,}")
    print(f"  {'-'*40}")
    print(f"  {'TOTAL':<30} {total:>8,}")
    conn2.close()


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    seed(force=force)
