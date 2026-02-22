from fastapi import APIRouter, HTTPException
from db import get_db
from services.newsapi import fetch_news_for_country

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/{iso2}")
async def get_news(iso2: str):
    db = get_db()
    country = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not country:
        raise HTTPException(404, "Country not found")
    rows = db.execute(
        "SELECT * FROM news_cache WHERE country_id=? ORDER BY published_at DESC LIMIT 30",
        (country["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/fetch/{iso2}")
async def fetch_news(iso2: str):
    db = get_db()
    country = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not country:
        raise HTTPException(404, "Country not found")
    count = await fetch_news_for_country(db, iso2.upper(), country["name"])
    return {"fetched": count}
