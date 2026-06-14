import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import get_db
from services.gdelt import fetch_news_for_country
from services.worldbank import sync_country_fundamentals
from services.rating_engine import run_ai_rating
from services.blurb_updater import run_daily_blurb_scan

_scheduler = None


async def run_daily_news():
    print("[scheduler] Starting daily news fetch...")
    db = get_db()
    countries = db.execute("SELECT iso2, name FROM countries").fetchall()
    success, errors = 0, 0
    for c in countries:
        try:
            await fetch_news_for_country(db, c["iso2"], c["name"])
            success += 1
        except Exception as e:
            print(f"[scheduler] News failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(6.0)  # GDELT rate limit: ~1 request every 5 seconds
    print(f"[scheduler] News done: {success} ok, {errors} errors")


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


async def run_monthly_rerate():
    print("[scheduler] Starting monthly full AI re-rate...")
    db = get_db()
    countries = db.execute("SELECT iso2 FROM countries").fetchall()
    success, errors = 0, 0
    for c in countries:
        try:
            await run_ai_rating(c["iso2"])
            success += 1
        except Exception as e:
            print(f"[scheduler] Re-rate failed for {c['iso2']}: {e}")
            errors += 1
        await asyncio.sleep(3.0)
    print(f"[scheduler] AI re-rate done: {success} ok, {errors} errors")


def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_daily_news,    "cron", hour=6)
    _scheduler.add_job(run_daily_blurb_scan, "cron", hour=6, minute=30)
    _scheduler.add_job(run_weekly_wb_sync, "cron", day_of_week="mon", hour=4)
    _scheduler.add_job(run_monthly_rerate, "cron", day=1, hour=3)
    _scheduler.start()
    print("[scheduler] Cron jobs scheduled (news: daily 06:00 | blurb scan: daily 06:30 | WB: Mon 04:00 | full re-rate: 1st of month 03:00)")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
