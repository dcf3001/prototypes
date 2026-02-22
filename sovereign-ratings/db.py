import sqlite3
import os

_db = None

def get_db():
    global _db
    if _db is None:
        data_dir = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), 'data'))
        os.makedirs(data_dir, exist_ok=True)
        _db = sqlite3.connect(
            os.path.join(data_dir, 'ratings.db'),
            check_same_thread=False
        )
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("PRAGMA foreign_keys=ON")
        _create_schema(_db)
    return _db


def _create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iso2 TEXT NOT NULL UNIQUE,
            iso3 TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            region TEXT,
            income_group TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fundamentals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
            year INTEGER NOT NULL,
            gdp_growth REAL,
            gdp_per_capita REAL,
            debt_gdp REAL,
            deficit_gdp REAL,
            ca_gdp REAL,
            reserves_months REAL,
            inflation REAL,
            fx_volatility REAL,
            governance_index REAL,
            political_stability REAL,
            UNIQUE(country_id, year)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
            rating TEXT NOT NULL,
            outlook TEXT NOT NULL,
            score_economic REAL,
            score_fiscal REAL,
            score_external REAL,
            score_monetary REAL,
            score_banking REAL,
            score_political REAL,
            composite_score REAL,
            ai_rationale TEXT,
            source TEXT NOT NULL CHECK(source IN ('ai','override')),
            override_rationale TEXT,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rationale_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER REFERENCES countries(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            applicable_country_ids TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
            headline TEXT NOT NULL,
            source TEXT,
            url TEXT,
            published_at TEXT,
            sentiment REAL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ratings_country_current ON ratings(country_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_fundamentals_country_year ON fundamentals(country_id, year DESC);
        CREATE INDEX IF NOT EXISTS idx_news_country_date ON news_cache(country_id, published_at DESC);
    """)
    conn.commit()
    # Migrations — safe to run on every startup
    for sql in [
        "ALTER TABLE ratings ADD COLUMN pillar_analysis TEXT",
    ]:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # column already exists
