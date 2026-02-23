import asyncio
import os
from fastapi import APIRouter
from jobs.scheduler import run_daily_news, run_weekly_wb_sync, run_weekly_rerate

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/health")
async def health():
    sra_key = os.environ.get("SRA_OPENAI_KEY", "")
    oai_key = os.environ.get("OPENAI_API_KEY", "")
    news_key = os.environ.get("NEWS_API_KEY", "")
    return {
        "SRA_OPENAI_KEY": f"set ({len(sra_key)} chars, starts {sra_key[:6]}...)" if sra_key else "NOT SET",
        "OPENAI_API_KEY": f"set ({len(oai_key)} chars, starts {oai_key[:6]}...)" if oai_key else "NOT SET",
        "NEWS_API_KEY": f"set ({len(news_key)} chars)" if news_key else "NOT SET",
        "ADMIN_PASSWORD": "set" if os.environ.get("ADMIN_PASSWORD") else "NOT SET",
    }


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
