"""
seed_ratings.py — Pre-populate AI ratings for every country.

Usage:
    python seed_ratings.py            # skip already-rated countries
    python seed_ratings.py --force    # re-rate every country

Expect roughly 5-8 seconds per country (World Bank sync + GPT-4o).
~195 countries ≈ 20-30 minutes total.
"""

import asyncio
import sys
import os
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from db import get_db
from services.worldbank import fetch_countries
from services.rating_engine import run_ai_rating

DELAY_BETWEEN = 1.5   # seconds between API calls
DELAY_ON_ERROR = 10   # extra wait after an error (rate-limit back-off)


def hms(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


async def main():
    force = "--force" in sys.argv
    db = get_db()

    # Ensure countries are seeded
    count = db.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    if count == 0:
        print("No countries found — seeding from World Bank...")
        n = await fetch_countries(db)
        print(f"Seeded {n} countries.\n")

    countries = db.execute("SELECT iso2, name FROM countries ORDER BY name").fetchall()
    total = len(countries)

    # Figure out which need rating
    to_rate = []
    skipped = 0
    for c in countries:
        existing = db.execute(
            "SELECT id FROM ratings WHERE country_id=(SELECT id FROM countries WHERE iso2=?) AND is_current=1",
            (c["iso2"],)
        ).fetchone()
        if existing and not force:
            skipped += 1
        else:
            to_rate.append(dict(c))

    print(f"Countries: {total} total | {skipped} already rated (skipping) | {len(to_rate)} to rate")
    if not to_rate:
        print("Nothing to do. Run with --force to re-rate all countries.")
        return

    est = len(to_rate) * (DELAY_BETWEEN + 6)
    print(f"Estimated time: ~{hms(est)}\n")
    print(f"{'#':<5} {'Country':<35} {'Rating':<8} {'Score':<8} Status")
    print("─" * 70)

    success, errors = 0, 0
    start = time.time()

    for i, c in enumerate(to_rate, 1):
        iso2 = c["iso2"]
        name = c["name"]
        prefix = f"{i}/{len(to_rate)}"
        print(f"[{prefix:<8}] {name:<35}", end="", flush=True)
        t0 = time.time()
        try:
            result = await run_ai_rating(iso2)
            r = result["rating"]
            rating_str  = r["rating"]
            score_str   = f"{r['composite_score']:.1f}" if r.get("composite_score") else "—"
            elapsed     = time.time() - t0
            print(f"  {rating_str:<8} {score_str:<8} ✓  ({elapsed:.1f}s)")
            success += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            await asyncio.sleep(DELAY_ON_ERROR)
            continue

        await asyncio.sleep(DELAY_BETWEEN)

    total_time = time.time() - start
    print("\n" + "─" * 70)
    print(f"Done in {hms(total_time)} — {success} rated, {errors} errors, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(main())
