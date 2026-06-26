import asyncio
import json
from db import get_db
from services.worldbank import sync_country_fundamentals
from services.openai_service import get_rating, research_country, get_pillar_scores_agent


def compute_composite(scores: dict) -> float:
    return (
        0.25 * scores.get("economic_strength", 0) +
        0.25 * scores.get("fiscal_position", 0) +
        0.20 * scores.get("external_position", 0) +
        0.10 * scores.get("monetary_policy", 0) +
        0.10 * scores.get("banking_sector", 0) +
        0.10 * scores.get("political_governance", 0)
    )


def aggregate_agent_scores(agent_scores: list[dict]) -> dict:
    """Trim the highest and lowest score per pillar across agents, average the rest."""
    pillars = [
        "economic_strength", "fiscal_position", "external_position",
        "monetary_policy", "banking_sector", "political_governance",
    ]
    result = {}
    for pillar in pillars:
        values = sorted(s[pillar] for s in agent_scores if isinstance(s.get(pillar), (int, float)))
        trimmed = values[1:-1] if len(values) >= 4 else values
        result[pillar] = round(sum(trimmed) / len(trimmed)) if trimmed else 50
    return result


async def run_ai_rating(iso2: str, web_research: bool = True) -> dict:
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

    # 5. Web research brief (best-effort)
    research_brief = await research_country(country["name"]) if web_research else ""

    # 6. Run six scoring agents + main blurb call concurrently
    tasks = [
        get_pillar_scores_agent(country["name"], fundamentals, headlines, applicable, research_brief)
        for _ in range(6)
    ] + [
        get_rating(
            country_name=country["name"],
            fundamentals=fundamentals,
            headlines=headlines,
            memories=applicable,
            research_brief=research_brief,
        )
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    agent_results = results[:6]
    blurb_result = results[6]

    if isinstance(blurb_result, Exception):
        raise blurb_result
    ai_result = blurb_result

    # Aggregate agent scores (trim top + bottom per pillar, average middle 4)
    valid_agents = [r for r in agent_results if isinstance(r, dict)]
    print(f"[rating_engine] {country['name']}: {len(valid_agents)}/6 scoring agents succeeded")

    pillars = [
        "economic_strength", "fiscal_position", "external_position",
        "monetary_policy", "banking_sector", "political_governance",
    ]
    raw_agent_scores = {
        p: sorted(s[p] for s in valid_agents if isinstance(s.get(p), (int, float)))
        for p in pillars
    }

    if len(valid_agents) >= 4:
        ai_result["pillar_scores"] = aggregate_agent_scores(valid_agents)
    else:
        print(f"[rating_engine] Falling back to main-call scores for {country['name']}")

    rating = ai_result["rating"]
    outlook = ai_result["outlook"]
    pillar_scores = ai_result["pillar_scores"]
    rationale = ai_result["rationale"]
    composite = compute_composite(pillar_scores)

    # 7. Write to DB
    db.execute(
        "UPDATE ratings SET is_current=0 WHERE country_id=? AND is_current=1",
        (country["id"],)
    )
    pillar_analysis_json = json.dumps(ai_result.get("pillar_analysis", {}))
    default_history = ai_result.get("default_history", "")

    cursor = db.execute("""
        INSERT INTO ratings
            (country_id, rating, outlook,
             score_economic, score_fiscal, score_external,
             score_monetary, score_banking, score_political,
             composite_score, ai_rationale, pillar_analysis, default_history, agent_scores, source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ai')
    """, (
        country["id"], rating, outlook,
        pillar_scores.get("economic_strength"),
        pillar_scores.get("fiscal_position"),
        pillar_scores.get("external_position"),
        pillar_scores.get("monetary_policy"),
        pillar_scores.get("banking_sector"),
        pillar_scores.get("political_governance"),
        composite, rationale, pillar_analysis_json, default_history,
        json.dumps(raw_agent_scores) if raw_agent_scores else None,
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
