import os
import httpx
from datetime import datetime

NEWSDATA_URL = "https://newsdata.io/api/1/news"

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


def _parse_pubdate(s: str) -> str | None:
    # NewsData format: "2026-06-14 10:00:00"
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").isoformat() + "Z"
    except ValueError:
        return None


async def fetch_news_for_country(db, iso2: str, country_name: str) -> int:
    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2,)).fetchone()
    if not row:
        raise ValueError(f"Country not found: {iso2}")
    country = dict(row)

    api_key = os.environ.get("NEWSDATA_API_KEY", "")
    if not api_key:
        print("[newsdata] NEWSDATA_API_KEY not set, skipping")
        return 0

    params = {
        "apikey": api_key,
        "country": iso2.lower(),
        "language": "en",
        "category": "business,politics,world",
    }

    articles = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(NEWSDATA_URL, params=params)
        if resp.status_code == 429:
            print(f"[newsdata] Rate-limited fetching news for {country_name}, skipping")
        else:
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("results", [])

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
                a.get("source_id"),
                a.get("link"),
                _parse_pubdate(a.get("pubDate")),
                compute_sentiment(headline),
            )
        )
    db.commit()
    return len(articles)
