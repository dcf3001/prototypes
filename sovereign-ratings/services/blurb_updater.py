import json
import re
from datetime import date

from db import get_db
from services.openai_service import get_openai_client, RATINGS_SCALE, OUTLOOKS
from services.rating_engine import compute_composite

# Marker pair the AI wraps around new/changed text. Rendered as gold "track changes"
# highlighting by the render_diff Jinja filter (see main.py). Highlights and the
# daily_changes score deltas are cleared automatically at the start of the next scan.
MARK_OPEN = "[[NEW]]"
MARK_CLOSE = "[[/NEW]]"

# Headlines containing these words (regardless of sentiment score) are treated as
# potentially material and trigger a review, even if the sentiment heuristic misses them.
HIGH_IMPACT_KEYWORDS = [
    "coup", "default", "invasion", "earthquake", "collapse", "resign",
    "sanctions", "downgrade", "upgrade", "ceasefire", "bailout",
    "restructuring", "credit rating", "impeach", "devaluation",
]

EDITABLE_PILLARS = {
    "economic_strength", "fiscal_position", "external_position",
    "monetary_policy", "banking_sector", "political_governance",
}

# Pillar key -> ratings table score column
PILLAR_SCORE_COLUMNS = {
    "economic_strength": "score_economic",
    "fiscal_position": "score_fiscal",
    "external_position": "score_external",
    "monetary_policy": "score_monetary",
    "banking_sector": "score_banking",
    "political_governance": "score_political",
}

MARK_RE = re.compile(re.escape(MARK_OPEN) + r"(.*?)" + re.escape(MARK_CLOSE), re.DOTALL)


def _is_candidate(headlines: list[dict]) -> bool:
    for h in headlines:
        if abs(h.get("sentiment") or 0) >= 0.66:
            return True
        text = (h.get("headline") or "").lower()
        if any(kw in text for kw in HIGH_IMPACT_KEYWORDS):
            return True
    return False


def _strip_markers(text):
    return MARK_RE.sub(r"\1", text) if text else text


def _clear_stale_updates(db):
    """Reset highlights from the previous scan before running today's — gold
    markers and score deltas represent 'what changed today', cleared automatically."""
    rows = db.execute("SELECT * FROM ratings WHERE pending_review=1").fetchall()
    for row in rows:
        rating = dict(row)
        pillar_analysis = json.loads(rating["pillar_analysis"] or "{}")
        for pillar in pillar_analysis.values():
            if isinstance(pillar, dict) and pillar.get("summary"):
                pillar["summary"] = _strip_markers(pillar["summary"])

        db.execute(
            "UPDATE ratings SET ai_rationale=?, default_history=?, pillar_analysis=?, "
            "daily_changes=NULL, pending_review=0 WHERE id=?",
            (
                _strip_markers(rating["ai_rationale"]),
                _strip_markers(rating["default_history"]),
                json.dumps(pillar_analysis),
                rating["id"],
            )
        )
    if rows:
        db.commit()
        print(f"[blurb_updater] Cleared stale highlights for {len(rows)} countries")


async def _review_country(country: dict, rating: dict, headlines: list[dict], period_label: str = "today") -> dict | None:
    pillar_analysis = json.loads(rating["pillar_analysis"] or "{}")

    head_text = "\n".join(
        f"- [sentiment {h.get('sentiment', 0):.2f}] {h['headline']} ({h.get('source') or 'unknown source'})"
        for h in headlines
    )

    summaries_text = "\n\n".join(
        f"### pillar_analysis.{key}.summary\n{pillar_analysis.get(key, {}).get('summary', '')}"
        for key in sorted(EDITABLE_PILLARS)
    )

    pillar_scores_text = "\n".join(
        f"- {key}: {rating.get(col)}" for key, col in PILLAR_SCORE_COLUMNS.items()
    )

    rating_idx = RATINGS_SCALE.index(rating["rating"]) if rating["rating"] in RATINGS_SCALE else None
    adjacent = []
    if rating_idx is not None:
        if rating_idx > 0:
            adjacent.append(RATINGS_SCALE[rating_idx - 1])
        adjacent.append(rating["rating"])
        if rating_idx < len(RATINGS_SCALE) - 1:
            adjacent.append(RATINGS_SCALE[rating_idx + 1])

    system_prompt = f"""You are a sovereign credit analyst doing a news review for {country['name']}.

Below are news headlines from {period_label} and the existing analytical text and scores for this country
(six pillar summaries with their 0-100 scores, the overall rating/outlook/composite score, the
overall rationale, and the default history).

Your job: decide whether any of these headlines represent a MATERIAL development that should
be reflected in the existing analysis and scores. Most of the time, NO update is needed. Only flag
genuinely material developments — e.g. a credit rating action, a default or debt restructuring,
a coup or abrupt change of government, a major economic data revision, new sanctions, a natural
disaster with significant economic impact, or a new IMF programme. Routine or minor news should
NOT trigger an update.

If no update is warranted, respond with exactly:
{{"update": false}}

If an update IS warranted:
- Choose the SINGLE most relevant text field to edit: one of
  {', '.join(f'"pillar_analysis.{p}.summary"' for p in sorted(EDITABLE_PILLARS))}, "ai_rationale", or "default_history"
- Make the MINIMAL edit needed to incorporate the new information — add or revise a sentence or
  short passage, preserving the rest of the existing text verbatim (do not rewrite unrelated
  parts, do not shorten or summarise existing content)
- Wrap ONLY the new or changed words in {MARK_OPEN} and {MARK_CLOSE} markers
- Return the FULL updated text for that field (including the markers)

You may ALSO adjust scores if the news justifies it:
- If the edited field is a pillar summary, you may propose "new_pillar_score": an integer 0-100
  for that pillar (omit or repeat the current value if unchanged)
- You may propose "new_rating" and/or "new_outlook" if the development is severe enough to
  warrant a rating action. The current rating is {rating['rating']} ({rating['outlook']}).
  new_rating MUST be one of the CURRENT rating's immediate neighbours on the 22-notch scale:
  {', '.join(adjacent) if adjacent else 'N/A'}. Do NOT skip notches. Omit new_rating/new_outlook
  entirely if no rating action is warranted (the normal case).

Respond ONLY with valid JSON, no markdown fences:
{{"update": true, "field": "<field name>", "updated_text": "<full updated text with markers>",
  "new_pillar_score": <int 0-100, optional>, "new_rating": "<rating, optional>",
  "new_outlook": "<outlook, optional>", "reason": "<one sentence>"}}
"""

    user_prompt = f"""## Headlines for {country['name']} ({period_label})
{head_text}

## Current rating
Rating: {rating['rating']} | Outlook: {rating['outlook']} | Composite score: {rating['composite_score']}

## Current pillar scores (0-100)
{pillar_scores_text}

## Existing overall rationale
{rating['ai_rationale'] or ''}

## Existing default history
{rating['default_history'] or ''}

## Existing pillar summaries
{summaries_text}
"""

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    result = json.loads(completion.choices[0].message.content)
    if not result.get("update"):
        return None

    field = result.get("field", "")
    updated_text = result.get("updated_text", "")
    if not updated_text:
        return None

    edit = {"reason": result.get("reason", ""), "text_field": None, "text_value": None,
            "pillar": None, "new_pillar_score": None, "new_rating": None, "new_outlook": None}

    if field == "ai_rationale":
        edit["text_field"] = "ai_rationale"
        edit["text_value"] = updated_text
    elif field == "default_history":
        edit["text_field"] = "default_history"
        edit["text_value"] = updated_text
    elif field.startswith("pillar_analysis.") and field.endswith(".summary"):
        pillar_key = field[len("pillar_analysis."):-len(".summary")]
        if pillar_key not in EDITABLE_PILLARS:
            return None
        pillar_analysis.setdefault(pillar_key, {})["summary"] = updated_text
        edit["text_field"] = "pillar_analysis"
        edit["text_value"] = json.dumps(pillar_analysis)
        edit["pillar"] = pillar_key

        new_score = result.get("new_pillar_score")
        if isinstance(new_score, (int, float)) and 0 <= new_score <= 100:
            current_score = rating.get(PILLAR_SCORE_COLUMNS[pillar_key])
            if current_score is None or int(new_score) != int(current_score):
                edit["new_pillar_score"] = int(new_score)
    else:
        return None

    new_rating = result.get("new_rating")
    if new_rating and new_rating in RATINGS_SCALE and new_rating in adjacent and new_rating != rating["rating"]:
        edit["new_rating"] = new_rating

    new_outlook = result.get("new_outlook")
    if new_outlook and new_outlook in OUTLOOKS and new_outlook != rating["outlook"]:
        edit["new_outlook"] = new_outlook

    return edit


async def _run_blurb_scan(scope: str, news_sql: str, period_label: str, iso2_filter: set | None = None):
    print(f"[blurb_updater] Starting {scope} blurb scan...")
    db = get_db()

    _clear_stale_updates(db)

    countries = db.execute("SELECT * FROM countries").fetchall()
    if iso2_filter is not None:
        countries = [c for c in countries if c["iso2"] in iso2_filter]
    with_news, candidates, updated, errors = 0, 0, 0, 0

    for c in countries:
        country = dict(c)
        news_rows = db.execute(news_sql, (country["id"],)).fetchall()
        headlines = [dict(r) for r in news_rows]
        if not headlines:
            continue
        with_news += 1
        if not _is_candidate(headlines):
            continue

        rating_row = db.execute(
            "SELECT * FROM ratings WHERE country_id=? AND is_current=1",
            (country["id"],)
        ).fetchone()
        if not rating_row:
            continue
        rating = dict(rating_row)

        candidates += 1
        try:
            edit = await _review_country(country, rating, headlines, period_label)
            if not edit:
                continue

            daily_changes = {"date": date.today().isoformat(), "reason": edit["reason"]}
            set_clauses = [f"{edit['text_field']}=?"]
            params = [edit["text_value"]]

            if edit["pillar"] and edit["new_pillar_score"] is not None:
                col = PILLAR_SCORE_COLUMNS[edit["pillar"]]
                old_score = rating.get(col)
                scores = {
                    key: (edit["new_pillar_score"] if key == edit["pillar"] else rating.get(c2))
                    for key, c2 in PILLAR_SCORE_COLUMNS.items()
                }
                new_composite = compute_composite(scores)
                set_clauses += [f"{col}=?", "composite_score=?"]
                params += [edit["new_pillar_score"], new_composite]
                daily_changes.update({
                    "pillar": edit["pillar"],
                    "score_old": old_score, "score_new": edit["new_pillar_score"],
                    "composite_old": rating["composite_score"], "composite_new": new_composite,
                })

            if edit["new_rating"]:
                set_clauses.append("rating=?")
                params.append(edit["new_rating"])
                daily_changes.update({"rating_old": rating["rating"], "rating_new": edit["new_rating"]})

            if edit["new_outlook"]:
                set_clauses.append("outlook=?")
                params.append(edit["new_outlook"])
                daily_changes.update({"outlook_old": rating["outlook"], "outlook_new": edit["new_outlook"]})

            set_clauses.append("daily_changes=?")
            params.append(json.dumps(daily_changes))
            set_clauses.append("pending_review=1")
            params.append(rating["id"])

            db.execute(f"UPDATE ratings SET {', '.join(set_clauses)} WHERE id=?", params)
            db.execute(
                "INSERT INTO update_log (country_id, reason, field, pillar, score_old, score_new, "
                "composite_old, composite_new, rating_old, rating_new, outlook_old, outlook_new) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    country["id"], edit["reason"], edit["text_field"], daily_changes.get("pillar"),
                    daily_changes.get("score_old"), daily_changes.get("score_new"),
                    daily_changes.get("composite_old"), daily_changes.get("composite_new"),
                    daily_changes.get("rating_old"), daily_changes.get("rating_new"),
                    daily_changes.get("outlook_old"), daily_changes.get("outlook_new"),
                )
            )
            db.commit()
            updated += 1
            print(f"[blurb_updater] Updated {country['name']} ({edit['text_field']}): {edit['reason']}")
        except Exception as e:
            print(f"[blurb_updater] Failed for {country['iso2']}: {e}")
            errors += 1

    db.execute(
        "INSERT INTO scan_log (scope, countries_total, with_news, candidates, updated, errors) VALUES (?,?,?,?,?,?)",
        (scope, len(countries), with_news, candidates, updated, errors)
    )
    db.commit()

    print(f"[blurb_updater] Done ({scope}): {with_news}/{len(countries)} had news, "
          f"{candidates} candidates, {updated} updated, {errors} errors")


async def run_daily_blurb_scan(iso2_filter: set | None = None):
    await _run_blurb_scan(
        scope="daily",
        news_sql="SELECT * FROM news_cache WHERE country_id=? AND date(fetched_at)=date('now')",
        period_label="today",
        iso2_filter=iso2_filter,
    )


async def run_weekly_blurb_scan(iso2_filter: set | None = None):
    await _run_blurb_scan(
        scope="weekly",
        news_sql="SELECT * FROM news_cache WHERE country_id=? AND fetched_at >= datetime('now', '-7 days')",
        period_label="the last 7 days",
        iso2_filter=iso2_filter,
    )
