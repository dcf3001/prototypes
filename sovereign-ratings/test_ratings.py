"""
test_ratings.py — Rate a small set of countries for testing the prompt output.

Usage:
    python test_ratings.py                  # rates the default 5 countries
    python test_ratings.py US DE JP         # rate specific countries by ISO2 code
    python test_ratings.py --force          # re-rate even if already rated

Shows a word-count breakdown per pillar so you can verify the prompt is
generating sufficiently long analysis.
"""

import asyncio
import sys
import os
import json
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from db import get_db
from services.worldbank import fetch_countries
from services.rating_engine import run_ai_rating

DEFAULT_COUNTRIES = ["BR", "CN", "AR", "GB", "IN"]  # Brazil, China, Argentina, UK, India

PILLAR_KEYS = [
    "economic_strength",
    "fiscal_position",
    "external_position",
    "monetary_policy",
    "banking_sector",
    "political_governance",
]

PILLAR_LABELS = {
    "economic_strength":   "Economy ",
    "fiscal_position":     "Fiscal  ",
    "external_position":   "External",
    "monetary_policy":     "Monetary",
    "banking_sector":      "Banking ",
    "political_governance":"Politics",
}


def word_count(text: str) -> int:
    return len(text.split()) if text else 0


def print_pillar_wordcounts(pillar_analysis: dict):
    print(f"  {'Pillar':<12} {'Words':>6}  {'Bar'}")
    print(f"  {'─'*12} {'─'*6}  {'─'*40}")
    for key in PILLAR_KEYS:
        pa = pillar_analysis.get(key, {})
        summary = pa.get("summary", "")
        wc = word_count(summary)
        bar_len = min(40, wc // 10)
        bar = "█" * bar_len
        flag = " ✓" if wc >= 400 else " ✗ TOO SHORT"
        print(f"  {PILLAR_LABELS[key]:<12} {wc:>6}  {bar}{flag}")


async def main():
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    iso2_list = [a.upper() for a in args] if args else DEFAULT_COUNTRIES

    db = get_db()

    # Ensure countries are seeded
    count = db.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    if count == 0:
        print("Seeding countries from World Bank…")
        await fetch_countries(db)

    print(f"\nTest rating: {', '.join(iso2_list)}\n")
    print("=" * 70)

    total_start = time.time()

    for iso2 in iso2_list:
        row = db.execute("SELECT name FROM countries WHERE iso2=?", (iso2,)).fetchone()
        if not row:
            print(f"[{iso2}] ✗ Country not found — skipping\n")
            continue

        name = row["name"]

        # Check if already rated
        existing = db.execute(
            "SELECT id FROM ratings WHERE country_id=(SELECT id FROM countries WHERE iso2=?) AND is_current=1",
            (iso2,)
        ).fetchone()
        if existing and not force:
            print(f"[{iso2}] {name} — already rated (use --force to re-rate)\n")
            continue

        print(f"[{iso2}] {name}")
        print(f"  Fetching web research + generating rating…")
        t0 = time.time()

        try:
            result = await run_ai_rating(iso2)
            elapsed = time.time() - t0

            r = result["rating"]
            rating_str = r["rating"]
            outlook_str = r["outlook"]
            score_str = f"{r['composite_score']:.1f}" if r.get("composite_score") else "—"

            print(f"  Rating: {rating_str}  |  Outlook: {outlook_str}  |  Score: {score_str}  ({elapsed:.0f}s)")
            print(f"  Rationale: {r.get('ai_rationale', '')[:120]}…")

            # Word count breakdown
            pillar_analysis = json.loads(r.get("pillar_analysis") or "{}")
            print_pillar_wordcounts(pillar_analysis)

            # Print first paragraph of economy tab as a quality check
            econ_summary = pillar_analysis.get("economic_strength", {}).get("summary", "")
            if econ_summary:
                first_para = econ_summary.split("\n\n")[0].strip()
                print(f"\n  Economy (first paragraph preview):")
                # Wrap at 70 chars
                words = first_para.split()
                line = "  "
                for w in words:
                    if len(line) + len(w) + 1 > 72:
                        print(line)
                        line = "  " + w
                    else:
                        line += (" " if line != "  " else "") + w
                if line.strip():
                    print(line)

        except Exception as e:
            print(f"  ✗ ERROR: {e}")

        print()

    total_elapsed = time.time() - total_start
    m, s = divmod(int(total_elapsed), 60)
    print("=" * 70)
    print(f"Done in {m:02d}:{s:02d}")


if __name__ == "__main__":
    asyncio.run(main())
