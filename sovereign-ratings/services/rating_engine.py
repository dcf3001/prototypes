import json
from db import get_db
from services.worldbank import sync_country_fundamentals
from services.openai_service import get_rating, research_country


def compute_composite(scores: dict) -> float:
    return (
        0.25 * scores.get("economic_strength", 0) +
        0.25 * scores.get("fiscal_position", 0) +
        0.20 * scores.get("external_position", 0) +
        0.10 * scores.get("monetary_policy", 0) +
        0.10 * scores.get("banking_sector", 0) +
        0.10 * scores.get("political_governance", 0)
    )


async def run_ai_rating(iso2: str) -> dict:
    db = get_db()

    # 1. Look up country
    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2.upper(),)).fetchone()
    if not row:
        raise LookupError(f"Country not found: {iso2}")
    country = dict(row)

    # 2. Get latest fundamentals — auto-sync if missing
    fund_row = db.execute(
        "SELECT * FROM fundamentals WHERE country_id=? ORDER BY year DESC LIMIT 1",
        (country["id"],)
    ).fetchone()

    if not fund_row:
        try:
            await sync_country_fundamentals(db, iso2)
            fund_row = db.execute(
                "SELECT * FROM fundamentals WHERE country_id=? ORDER BY year DESC LIMIT 1",
                (country["id"],)
            ).fetchone()
        except Exception as e:
            print(f"[rating_engine] Could not sync fundamentals for {iso2}: {e}")

    fundamentals = dict(fund_row) if fund_row else None

    # 3. Get last 10 cached news items
    news_rows = db.execute(
        "SELECT * FROM news_cache WHERE country_id=? ORDER BY published_at DESC LIMIT 10",
        (country["id"],)
    ).fetchall()
    headlines = [dict(r) for r in news_rows]

    # 4. Filter applicable rationale memories
    all_memories = db.execute("SELECT * FROM rationale_memory").fetchall()
    applicable = []
    for m in all_memories:
        m = dict(m)
        if m["country_id"] == country["id"]:
            applicable.append(m)
            continue
        try:
            ids = json.loads(m["applicable_country_ids"] or "[]")
            if country["id"] in ids:
                applicable.append(m)
        except Exception:
            pass

    # 5. Web research brief (best-effort — skipped if API unavailable)
    research_brief = await research_country(country["name"])

    # 6. Call GPT-4o
    ai_result = await get_rating(
        country_name=country["name"],
        fundamentals=fundamentals,
        headlines=headlines,
        memories=applicable,
        research_brief=research_brief,
    )

    rating = ai_result["rating"]
    outlook = ai_result["outlook"]
    pillar_scores = ai_result["pillar_scores"]
    rationale = ai_result["rationale"]
    composite = compute_composite(pillar_scores)

    # 6. Write to DB
    db.execute(
        "UPDATE ratings SET is_current=0 WHERE country_id=? AND is_current=1",
        (country["id"],)
    )
    pillar_analysis_json = json.dumps(ai_result.get("pillar_analysis", {}))

    cursor = db.execute("""
        INSERT INTO ratings
            (country_id, rating, outlook,
             score_economic, score_fiscal, score_external,
             score_monetary, score_banking, score_political,
             composite_score, ai_rationale, pillar_analysis, source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ai')
    """, (
        country["id"], rating, outlook,
        pillar_scores.get("economic_strength"),
        pillar_scores.get("fiscal_position"),
        pillar_scores.get("external_position"),
        pillar_scores.get("monetary_policy"),
        pillar_scores.get("banking_sector"),
        pillar_scores.get("political_governance"),
        composite, rationale, pillar_analysis_json,
    ))
    db.commit()

    new_rating = dict(db.execute(
        "SELECT * FROM ratings WHERE id=?", (cursor.lastrowid,)
    ).fetchone())

    return {
        "country": country,
        "rating": new_rating,
        "applicable_memories": len(applicable),
    }
