import json
from fastapi import APIRouter, HTTPException
from db import get_db
from services.rating_engine import run_ai_rating
from services.openai_service import RATINGS_SCALE, OUTLOOKS

router = APIRouter(prefix="/api/ratings", tags=["ratings"])


@router.get("/{iso2}/history")
async def get_history(iso2: str):
    db = get_db()
    country = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not country:
        raise HTTPException(404, "Country not found")
    rows = db.execute(
        "SELECT * FROM ratings WHERE country_id=? ORDER BY created_at DESC LIMIT 50",
        (country["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/{iso2}/ai")
async def trigger_ai_rating(iso2: str):
    try:
        result = await run_ai_rating(iso2.upper())
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{iso2}/override")
async def create_override(iso2: str, body: dict):
    rating = body.get("rating")
    outlook = body.get("outlook")
    rationale = (body.get("rationale") or "").strip()
    title = (body.get("title") or "").strip()
    tags = body.get("tags", [])
    applicable_ids = body.get("applicable_country_ids", [])

    if rating not in RATINGS_SCALE:
        raise HTTPException(400, f"Invalid rating")
    if outlook not in OUTLOOKS:
        raise HTTPException(400, "Invalid outlook")
    if not rationale:
        raise HTTPException(400, "Rationale is required")

    db = get_db()
    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "Country not found")
    country = dict(row)

    memory_title = title or f"Override: {country['name']} — {rating} {outlook}"

    db.execute(
        "UPDATE ratings SET is_current=0 WHERE country_id=? AND is_current=1",
        (country["id"],)
    )
    rc = db.execute(
        "INSERT INTO ratings (country_id, rating, outlook, source, override_rationale) VALUES (?,?,?,'override',?)",
        (country["id"], rating, outlook, rationale)
    )
    mc = db.execute(
        "INSERT INTO rationale_memory (country_id, title, content, tags, applicable_country_ids) VALUES (?,?,?,?,?)",
        (
            country["id"], memory_title, rationale,
            json.dumps(tags if isinstance(tags, list) else []),
            json.dumps(applicable_ids if isinstance(applicable_ids, list) else []),
        )
    )
    db.commit()

    new_rating = dict(db.execute("SELECT * FROM ratings WHERE id=?", (rc.lastrowid,)).fetchone())
    new_memory = dict(db.execute("SELECT * FROM rationale_memory WHERE id=?", (mc.lastrowid,)).fetchone())
    return {"rating": new_rating, "memory": new_memory}
