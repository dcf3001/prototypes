from fastapi import APIRouter, HTTPException
from db import get_db

router = APIRouter(prefix="/api/countries", tags=["countries"])


@router.get("")
async def list_countries():
    db = get_db()
    rows = db.execute("""
        SELECT c.id, c.iso2, c.iso3, c.name, c.region, c.income_group,
               r.rating, r.outlook, r.composite_score, r.source,
               r.created_at as rated_at
        FROM countries c
        LEFT JOIN ratings r ON r.country_id = c.id AND r.is_current = 1
        ORDER BY c.name
    """).fetchall()
    return [dict(r) for r in rows]


@router.get("/{iso2}")
async def get_country(iso2: str):
    db = get_db()
    row = db.execute("""
        SELECT c.id, c.iso2, c.iso3, c.name, c.region, c.income_group,
               r.rating, r.outlook, r.composite_score, r.source,
               r.ai_rationale, r.override_rationale, r.created_at as rated_at
        FROM countries c
        LEFT JOIN ratings r ON r.country_id = c.id AND r.is_current = 1
        WHERE c.iso2 = ?
    """, (iso2.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "Country not found")
    return dict(row)
