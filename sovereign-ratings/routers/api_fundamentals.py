from fastapi import APIRouter, HTTPException
from db import get_db
from services.worldbank import sync_country_fundamentals

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])


@router.get("/{iso2}")
async def get_fundamentals(iso2: str):
    db = get_db()
    country = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not country:
        raise HTTPException(404, "Country not found")
    rows = db.execute(
        "SELECT * FROM fundamentals WHERE country_id=? ORDER BY year DESC",
        (country["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/sync/{iso2}")
async def sync_fundamentals(iso2: str):
    try:
        db = get_db()
        result = await sync_country_fundamentals(db, iso2.upper())
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
