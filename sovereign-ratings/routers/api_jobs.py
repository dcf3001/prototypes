import asyncio
from fastapi import APIRouter
from jobs.scheduler import run_daily_news, run_weekly_wb_sync, run_weekly_rerate

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/sync-news")
async def sync_news():
    asyncio.create_task(run_daily_news())
    return {"message": "News sync started in background"}


@router.post("/sync-wb")
async def sync_wb():
    asyncio.create_task(run_weekly_wb_sync())
    return {"message": "World Bank sync started in background"}


@router.post("/rerate-all")
async def rerate_all():
    asyncio.create_task(run_weekly_rerate())
    return {"message": "AI re-rate started in background"}
