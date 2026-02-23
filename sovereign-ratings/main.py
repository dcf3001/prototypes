import os
import base64
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
# Load .env from parent dir (local dev) — on Railway env vars are injected directly
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware


# ── HTTP Basic Auth (optional — set ADMIN_PASSWORD env var to enable) ────────

class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            return await call_next(request)   # no auth in local dev
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                credentials = base64.b64decode(auth[6:]).decode()
                _, _, provided = credentials.partition(":")
                if secrets.compare_digest(provided, password):
                    return await call_next(request)
            except Exception:
                pass
        return Response(
            "Unauthorized", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Sovereign Ratings"'},
        )


from db import get_db
from services.worldbank import fetch_countries
from services.openai_service import RATINGS_SCALE, OUTLOOKS
from jobs.scheduler import start_scheduler, stop_scheduler
from routers import api_countries, api_ratings, api_fundamentals, api_news, api_rationale, api_jobs


# ── Jinja2 filters ──────────────────────────────────────────────────────────

RATING_ORDER = ["AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-",
                "BB+","BB","BB-","B+","B","B-","CCC+","CCC","CCC-","CC","C","D"]

def rating_color(rating):
    if not rating:
        return "#9e9e9e"
    idx = RATING_ORDER.index(rating) if rating in RATING_ORDER else -1
    if idx < 0:   return "#9e9e9e"
    if idx <= 3:  return "#1b5e20"   # AAA–AA-
    if idx <= 6:  return "#2e7d32"   # A+–A-
    if idx <= 9:  return "#f57f17"   # BBB+–BBB-
    if idx <= 12: return "#e65100"   # BB+–BB-
    if idx <= 15: return "#c62828"   # B+–B-
    return "#6a1b9a"                 # CCC and below

def rating_category(rating):
    if not rating or rating not in RATING_ORDER:
        return "Unrated"
    idx = RATING_ORDER.index(rating)
    if idx <= 9:  return "Investment Grade"
    if idx <= 15: return "Sub-Investment Grade"
    return "Distressed"

def outlook_style(outlook):
    styles = {
        "Stable":         "background:#e3f2fd;color:#1565c0",
        "Positive":       "background:#e8f5e9;color:#2e7d32",
        "Negative":       "background:#fce4ec;color:#c62828",
        "Watch Positive": "background:#fff8e1;color:#f57f17",
        "Watch Negative": "background:#fbe9e7;color:#bf360c",
    }
    return styles.get(outlook or "", "background:#f5f5f5;color:#757575")

def fmt_num(v, decimals=1, suffix="", prefix=""):
    if v is None:
        return "—"
    try:
        return f"{prefix}{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"

def fmt_date(s):
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return str(s)[:10]

def parse_json_tags(s):
    import json
    try:
        return json.loads(s or "[]")
    except Exception:
        return []

def parse_json(s):
    import json
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}

def score_label(v):
    if v is None:
        return ("—", "#9e9e9e")
    v = float(v)
    if v >= 80: return ("Strong",    "#2e7d32")
    if v >= 60: return ("Moderate",  "#f57f17")
    if v >= 40: return ("Weak",      "#e65100")
    return             ("Very Weak", "#c62828")


# ── App lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    key = os.environ.get("OPENAI_API_KEY", "")
    print(f"[startup] OPENAI_API_KEY: {'SET (' + str(len(key)) + ' chars, starts ' + key[:6] + '...)' if key else 'NOT SET'}")
    db = get_db()  # initialises schema
    count = db.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    if count == 0:
        print("[startup] No countries found — seeding from World Bank...")
        try:
            await fetch_countries(db)
        except Exception as e:
            print(f"[startup] Seed failed: {e}")
    start_scheduler()
    yield
    stop_scheduler()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan, title="Sovereign Ratings Agency")
app.add_middleware(BasicAuthMiddleware)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.filters["rating_color"] = rating_color
templates.env.filters["rating_category"] = rating_category
templates.env.filters["outlook_style"] = outlook_style
templates.env.filters["fmt_num"] = fmt_num
templates.env.filters["fmt_date"] = fmt_date
templates.env.filters["parse_json_tags"] = parse_json_tags
templates.env.filters["parse_json"] = parse_json
templates.env.globals["score_label"] = score_label

# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(api_countries.router)
app.include_router(api_ratings.router)
app.include_router(api_fundamentals.router)
app.include_router(api_news.router)
app.include_router(api_rationale.router)
app.include_router(api_jobs.router)


# ── Page routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = get_db()
    rows = db.execute("""
        SELECT c.id, c.iso2, c.iso3, c.name, c.region, c.income_group,
               r.rating, r.outlook, r.composite_score, r.source
        FROM countries c
        LEFT JOIN ratings r ON r.country_id = c.id AND r.is_current = 1
        ORDER BY c.name
    """).fetchall()
    countries = [dict(r) for r in rows]

    rated = sum(1 for c in countries if c["rating"])
    ig = sum(1 for c in countries if c["rating"] and RATING_ORDER.index(c["rating"]) <= 9
             if c["rating"] in RATING_ORDER)

    regions = sorted({c["region"] for c in countries if c["region"]})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "countries": countries,
        "total": len(countries),
        "rated": rated,
        "ig": ig,
        "below_ig": rated - ig,
        "regions": regions,
        "active": "dashboard",
    })


@app.get("/country/{iso2}", response_class=HTMLResponse)
async def country_page(request: Request, iso2: str):
    import json
    db = get_db()
    iso2 = iso2.upper()

    row = db.execute("""
        SELECT c.id, c.iso2, c.iso3, c.name, c.region, c.income_group,
               r.rating, r.outlook, r.composite_score, r.source,
               r.score_economic, r.score_fiscal, r.score_external,
               r.score_monetary, r.score_banking, r.score_political,
               r.ai_rationale, r.override_rationale, r.pillar_analysis,
               r.default_history, r.created_at as rated_at
        FROM countries c
        LEFT JOIN ratings r ON r.country_id = c.id AND r.is_current = 1
        WHERE c.iso2=?
    """, (iso2,)).fetchone()

    if not row:
        return HTMLResponse("<h1>Country not found</h1>", status_code=404)

    country = dict(row)

    fundamentals = [dict(r) for r in db.execute(
        "SELECT * FROM fundamentals WHERE country_id=? ORDER BY year DESC",
        (country["id"],)
    ).fetchall()]

    history = [dict(r) for r in db.execute(
        "SELECT * FROM ratings WHERE country_id=? ORDER BY created_at DESC LIMIT 50",
        (country["id"],)
    ).fetchall()]

    news = [dict(r) for r in db.execute(
        "SELECT * FROM news_cache WHERE country_id=? ORDER BY published_at DESC LIMIT 30",
        (country["id"],)
    ).fetchall()]

    all_countries = [dict(r) for r in db.execute(
        "SELECT id, iso2, name FROM countries WHERE iso2!=? ORDER BY name",
        (iso2,)
    ).fetchall()]

    return templates.TemplateResponse("country.html", {
        "request": request,
        "country": country,
        "fundamentals": fundamentals,
        "history": history,
        "news": news,
        "all_countries": all_countries,
        "ratings_scale": RATINGS_SCALE,
        "outlooks": OUTLOOKS,
        "active": "",
    })


@app.get("/memories", response_class=HTMLResponse)
async def memories_page(request: Request):
    import json
    db = get_db()
    rows = db.execute("""
        SELECT m.*, c.name as country_name, c.iso2 as country_iso2
        FROM rationale_memory m
        LEFT JOIN countries c ON c.id = m.country_id
        ORDER BY m.created_at DESC
    """).fetchall()
    memories = [dict(r) for r in rows]

    all_countries = [dict(r) for r in db.execute(
        "SELECT id, iso2, name FROM countries ORDER BY name"
    ).fetchall()]

    return templates.TemplateResponse("memories.html", {
        "request": request,
        "memories": memories,
        "all_countries": all_countries,
        "active": "memories",
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 3002))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
