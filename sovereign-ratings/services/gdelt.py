import asyncio
import httpx
from datetime import datetime

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

POSITIVE_WORDS = ["growth", "surplus", "reform", "upgrade", "recovery", "boom",
                  "expansion", "investment", "strong", "positive", "gdp"]
NEGATIVE_WORDS = ["crisis", "default", "downgrade", "recession", "sanctions", "debt",
                  "collapse", "inflation", "protest", "instability", "war", "conflict",
                  "deficit", "bailout"]


def compute_sentiment(headline: str) -> float:
    text = headline.lower()
    score = 0
    for w in POSITIVE_WORDS:
        if w in text:
            score += 1
    for w in NEGATIVE_WORDS:
        if w in text:
            score -= 1
    return max(-1.0, min(1.0, score / 3.0))


def _parse_seendate(s: str) -> str | None:
    # GDELT format: "20260613T120000Z"
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
    except ValueError:
        return None


async def fetch_news_for_country(db, iso2: str, country_name: str) -> int:
    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2,)).fetchone()
    if not row:
        raise ValueError(f"Country not found: {iso2}")
    country = dict(row)

    query = f'"{country_name}" economy sourcelang:english'
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 10,
        "timespan": "1d",
        "sort": "datedesc",
    }

    data = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(3):
            resp = await client.get(GDELT_URL, params=params)
            if resp.status_code == 429:
                # GDELT rate-limits per-IP; back off and retry a couple of times
                await asyncio.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                # GDELT returns an empty/non-JSON body when there are no results
                data = {}
            break
        else:
            print(f"[gdelt] Rate-limited fetching news for {country_name}, skipping")

    articles = data.get("articles", [])

    # Remove stale entries older than 7 days
    db.execute(
        "DELETE FROM news_cache WHERE country_id=? AND fetched_at < datetime('now', '-7 days')",
        (country["id"],)
    )

    for a in articles:
        headline = a.get("title") or ""
        if not headline:
            continue
        db.execute(
            """INSERT OR IGNORE INTO news_cache
               (country_id, headline, source, url, published_at, sentiment)
               VALUES (?,?,?,?,?,?)""",
            (
                country["id"],
                headline,
                a.get("domain"),
                a.get("url"),
                _parse_seendate(a.get("seendate")),
                compute_sentiment(headline),
            )
        )
    db.commit()
    return len(articles)
