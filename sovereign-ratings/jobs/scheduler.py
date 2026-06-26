import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import get_db
from services.newsdata import fetch_news_for_country
from services.worldbank import sync_country_fundamentals
from services.rating_engine import run_ai_rating
from services.blurb_updater import run_daily_blurb_scan, run_weekly_blurb_scan

_scheduler = None

# Tier 1 — largest, riskiest, most prominent; daily blurb scan + weekly re-rate
TIER1_ISO2 = {
    "US", "CN", "DE", "JP", "GB", "FR", "IN", "BR", "RU", "IT",
    "CA", "KR", "AU", "ES", "MX", "ID", "TR", "SA", "AR", "ZA",
}

# Tier 2 — important regional economies and elevated-risk sovereigns; daily blurb + monthly re-rate
TIER2_ISO2 = {
    "NL", "CH", "PL", "SE", "BE", "NO", "AE", "IL", "EG", "NG",
    "UA", "PK", "BD", "VN", "TH", "MY", "PH", "CO", "CL", "PE",
    "GR", "PT", "CZ", "HU", "RO", "KE", "ET", "GH", "VE", "QA",
}

# Tier 3 — all others; weekly blurb scan + monthly re-rate (computed at runtime from DB)

TIER1_AND_2 = TIER1_ISO2 | TIER2_ISO2


async def _fetch_news_for_countries(db, countries: list) -> tuple[int, int]:
    success, errors = 0, 0
    for c in countries:
        try:
            await fetch_news_for_country(db, c["iso2"], c["name"])
            success += 1
        except Exception as e:
            print(f"[scheduler] News failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(2.0)
    return success, errors


async def run_daily_news():
    """Fetch news for Tier 1 + 2 countries (runs daily)."""
    print("[scheduler] Starting daily news fetch (Tier 1+2)...")
    db = get_db()
    countries = db.execute("SELECT iso2, name FROM countries ORDER BY id").fetchall()
    tier12 = [c for c in countries if c["iso2"] in TIER1_AND_2]
    success, errors = await _fetch_news_for_countries(db, tier12)
    print(f"[scheduler] Daily news done: {success} ok, {errors} errors ({len(tier12)} countries)")


async def run_tier3_news():
    """Fetch news for Tier 3 countries (runs weekly on Saturday)."""
    print("[scheduler] Starting weekly news fetch (Tier 3)...")
    db = get_db()
    countries = db.execute("SELECT iso2, name FROM countries ORDER BY id").fetchall()
    tier3 = [c for c in countries if c["iso2"] not in TIER1_AND_2]
    success, errors = await _fetch_news_for_countries(db, tier3)
    print(f"[scheduler] Tier 3 news done: {success} ok, {errors} errors ({len(tier3)} countries)")


async def run_daily_blurb():
    """Daily blurb scan for Tier 1 + 2."""
    await run_daily_blurb_scan(iso2_filter=TIER1_AND_2)


async def run_weekly_blurb():
    """Weekly blurb scan for Tier 3 (all countries not in Tier 1 or 2)."""
    db = get_db()
    all_iso2 = {row["iso2"] for row in db.execute("SELECT iso2 FROM countries").fetchall()}
    tier3 = all_iso2 - TIER1_AND_2
    await run_weekly_blurb_scan(iso2_filter=tier3)


async def run_weekly_wb_sync():
    print("[scheduler] Starting World Bank sync...")
    db = get_db()
    countries = db.execute("SELECT iso2 FROM countries").fetchall()
    success, errors = 0, 0
    for c in countries:
        try:
            await sync_country_fundamentals(db, c["iso2"])
            success += 1
        except Exception as e:
            print(f"[scheduler] WB failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(2.0)
    print(f"[scheduler] WB sync done: {success} ok, {errors} errors")


async def run_weekly_rerate():
    """Weekly re-rate for Tier 1 countries (runs every Monday)."""
    print("[scheduler] Starting weekly Tier 1 AI re-rate...")
    db = get_db()
    countries = db.execute("SELECT iso2 FROM countries").fetchall()
    tier1 = [c for c in countries if c["iso2"] in TIER1_ISO2]
    success, errors = 0, 0
    for c in tier1:
        try:
            await run_ai_rating(c["iso2"])
            success += 1
        except Exception as e:
            print(f"[scheduler] Re-rate failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(3.0)
    print(f"[scheduler] Tier 1 re-rate done: {success} ok, {errors} errors")


async def run_monthly_rerate():
    """Monthly re-rate for Tier 2 + 3 countries (runs 1st of each month)."""
    print("[scheduler] Starting monthly Tier 2+3 AI re-rate...")
    db = get_db()
    countries = db.execute("SELECT iso2 FROM countries").fetchall()
    tier23 = [c for c in countries if c["iso2"] not in TIER1_ISO2]
    success, errors = 0, 0
    for c in tier23:
        try:
            await run_ai_rating(c["iso2"])
            success += 1
        except Exception as e:
            print(f"[scheduler] Re-rate failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(3.0)
    print(f"[scheduler] Tier 2+3 re-rate done: {success} ok, {errors} errors")


def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()

    # News fetching
    _scheduler.add_job(run_daily_news,   "cron", hour=6)                              # Tier 1+2: daily
    _scheduler.add_job(run_tier3_news,   "cron", day_of_week="sat", hour=5)           # Tier 3: Saturday

    # Blurb scans
    _scheduler.add_job(run_daily_blurb,  "cron", hour=6, minute=30)                   # Tier 1+2: daily
    _scheduler.add_job(run_weekly_blurb, "cron", day_of_week="sun", hour=7)           # Tier 3: Sunday

    # World Bank data
    _scheduler.add_job(run_weekly_wb_sync, "cron", day_of_week="mon", hour=4)

    # AI re-rates
    _scheduler.add_job(run_weekly_rerate,  "cron", day_of_week="mon", hour=3)         # Tier 1: weekly
    _scheduler.add_job(run_monthly_rerate, "cron", day=1, hour=4)                     # Tier 2+3: monthly

    _scheduler.start()
    print(
        "[scheduler] Cron jobs scheduled:\n"
        "  News:     Tier 1+2 daily 06:00 | Tier 3 Saturday 05:00\n"
        "  Blurbs:   Tier 1+2 daily 06:30 | Tier 3 Sunday 07:00\n"
        "  WB sync:  Monday 04:00\n"
        "  Re-rates: Tier 1 weekly Mon 03:00 | Tier 2+3 monthly 1st 04:00"
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
