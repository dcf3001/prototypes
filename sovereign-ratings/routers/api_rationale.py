import json
from fastapi import APIRouter, HTTPException
from db import get_db

router = APIRouter(prefix="/api/rationale", tags=["rationale"])


@router.get("")
async def list_rationale():
    db = get_db()
    rows = db.execute("""
        SELECT m.*, c.name as country_name, c.iso2 as country_iso2
        FROM rationale_memory m
        LEFT JOIN countries c ON c.id = m.country_id
        ORDER BY m.created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


@router.get("/{mem_id}")
async def get_rationale(mem_id: int):
    db = get_db()
    row = db.execute("""
        SELECT m.*, c.name as country_name, c.iso2 as country_iso2
        FROM rationale_memory m
        LEFT JOIN countries c ON c.id = m.country_id
        WHERE m.id=?
    """, (mem_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@router.post("")
async def create_rationale(body: dict):
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(400, "title and content required")
    db = get_db()
    tags = body.get("tags", [])
    applicable_ids = body.get("applicable_country_ids", [])
    c = db.execute(
        "INSERT INTO rationale_memory (country_id, title, content, tags, applicable_country_ids) VALUES (?,?,?,?,?)",
        (
            body.get("country_id"),
            title, content,
            json.dumps(tags if isinstance(tags, list) else []),
            json.dumps(applicable_ids if isinstance(applicable_ids, list) else []),
        )
    )
    db.commit()
    return dict(db.execute("SELECT * FROM rationale_memory WHERE id=?", (c.lastrowid,)).fetchone())


@router.put("/{mem_id}")
async def update_rationale(mem_id: int, body: dict):
    db = get_db()
    row = db.execute("SELECT * FROM rationale_memory WHERE id=?", (mem_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    existing = dict(row)
    tags = body.get("tags")
    applicable_ids = body.get("applicable_country_ids")
    db.execute("""
        UPDATE rationale_memory
        SET title=?, content=?, tags=?, applicable_country_ids=?
        WHERE id=?
    """, (
        body.get("title", existing["title"]),
        body.get("content", existing["content"]),
        json.dumps(tags if isinstance(tags, list) else []) if tags is not None else existing["tags"],
        json.dumps(applicable_ids if isinstance(applicable_ids, list) else []) if applicable_ids is not None else existing["applicable_country_ids"],
        mem_id,
    ))
    db.commit()
    return dict(db.execute("SELECT * FROM rationale_memory WHERE id=?", (mem_id,)).fetchone())


@router.delete("/{mem_id}")
async def delete_rationale(mem_id: int):
    db = get_db()
    result = db.execute("DELETE FROM rationale_memory WHERE id=?", (mem_id,))
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Not found")
    return {"deleted": True}
