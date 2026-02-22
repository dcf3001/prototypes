import httpx
import os

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


async def fetch_news_for_country(db, iso2: str, country_name: str) -> int:
    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    if not api_key:
        print("[newsapi] NEWS_API_KEY not set — skipping")
        return 0

    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2,)).fetchone()
    if not row:
        raise ValueError(f"Country not found: {iso2}")
    country = dict(row)

    query = f"{country_name} economy"
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 10,
        "apiKey": api_key,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    articles = data.get("articles", [])

    # Remove stale entries older than 7 days
    db.execute(
        "DELETE FROM news_cache WHERE country_id=? AND fetched_at < datetime('now', '-7 days')",
        (country["id"],)
    )

    for a in articles:
        headline = a.get("title") or ""
        if not headline or headline == "[Removed]":
            continue
        db.execute(
            """INSERT OR IGNORE INTO news_cache
               (country_id, headline, source, url, published_at, sentiment)
               VALUES (?,?,?,?,?,?)""",
            (
                country["id"],
                headline,
                a.get("source", {}).get("name"),
                a.get("url"),
                a.get("publishedAt"),
                compute_sentiment(headline),
            )
        )
    db.commit()
    return len(articles)
