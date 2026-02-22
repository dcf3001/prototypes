import os
import json
from openai import AsyncOpenAI

RATINGS_SCALE = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
    "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"
]
OUTLOOKS = ["Stable", "Positive", "Negative", "Watch Positive", "Watch Negative"]

_client = None

def get_openai_client():
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


async def get_rating(country_name: str, fundamentals: dict, headlines: list, memories: list) -> dict:
    def fmt(v, suffix=""):
        return f"{float(v):.1f}{suffix}" if v is not None else "N/A"

    fund_text = f"""GDP Growth: {fmt(fundamentals.get('gdp_growth'), '%')}
GDP per Capita: ${fmt(fundamentals.get('gdp_per_capita'))}
Government Debt/GDP: {fmt(fundamentals.get('debt_gdp'), '%')}
Fiscal Deficit/GDP: {fmt(fundamentals.get('deficit_gdp'), '%')}
Current Account/GDP: {fmt(fundamentals.get('ca_gdp'), '%')}
FX Reserves (import months): {fmt(fundamentals.get('reserves_months'))}
Inflation: {fmt(fundamentals.get('inflation'), '%')}
Data year: {fundamentals.get('year', 'N/A')}""" if fundamentals else "No fundamentals data available."

    head_text = "\n".join(
        f"- [sentiment {h.get('sentiment', 0):.2f}] {h['headline']}" for h in headlines
    ) if headlines else "No recent news."

    mem_text = "\n\n".join(
        f"### {m['title']}\n{m['content']}" for m in memories
    ) if memories else "None."

    system_prompt = f"""You are a senior sovereign credit analyst at a major ratings agency.

RATING SCALE (22 notches): {', '.join(RATINGS_SCALE)}
OUTLOOKS: {', '.join(OUTLOOKS)}

PILLAR SCORING (0 = worst, 100 = best):
- economic_strength:   GDP growth, per-capita income, diversification, labour market, competitiveness
- fiscal_position:     Debt/GDP, deficit, revenue capacity, spending composition, fiscal sustainability
- external_position:   Current account, FX reserves, external debt, trade structure, BOP dynamics
- monetary_policy:     Inflation control, central bank credibility, exchange rate regime, FX stability
- banking_sector:      System stability, capital adequacy, NPL ratios, credit growth, systemic risk
- political_governance:Institutional quality, rule of law, corruption, political stability, regulatory quality

COMPOSITE WEIGHT: Economic 25% + Fiscal 25% + External 20% + Monetary 10% + Banking 10% + Political 10%

Respond ONLY with valid JSON matching this EXACT structure (no extra keys, no markdown):
{{
  "rating": "BBB",
  "outlook": "Stable",
  "pillar_scores": {{
    "economic_strength": 60,
    "fiscal_position": 55,
    "external_position": 50,
    "monetary_policy": 65,
    "banking_sector": 58,
    "political_governance": 52
  }},
  "rationale": "2-3 sentence overall summary explaining the rating.",
  "pillar_analysis": {{
    "economic_strength": {{
      "summary": "3-5 sentences analysing the economic outlook, growth drivers, structural strengths and vulnerabilities.",
      "strengths": ["Specific strength 1", "Specific strength 2", "Specific strength 3"],
      "risks": ["Specific risk 1", "Specific risk 2", "Specific risk 3"]
    }},
    "fiscal_position": {{
      "summary": "3-5 sentences on fiscal dynamics, debt trajectory, deficit path and consolidation prospects.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "external_position": {{
      "summary": "3-5 sentences on current account, reserves, external debt and BoP resilience.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "monetary_policy": {{
      "summary": "3-5 sentences on inflation, monetary framework, exchange rate and CB credibility.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "banking_sector": {{
      "summary": "3-5 sentences on banking system health, stability, credit conditions and systemic risks.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "political_governance": {{
      "summary": "3-5 sentences on institutional quality, political stability, rule of law and governance.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }}
  }}
}}"""

    user_prompt = f"""## Country: {country_name}

## Economic Fundamentals
{fund_text}

## Recent News Headlines
{head_text}

## Analyst Memory Notes
{mem_text}

Rate {country_name} and provide full pillar-by-pillar analysis."""

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )

    result = json.loads(completion.choices[0].message.content)

    if result.get("rating") not in RATINGS_SCALE:
        raise ValueError(f"Invalid rating from AI: {result.get('rating')}")
    if result.get("outlook") not in OUTLOOKS:
        result["outlook"] = "Stable"

    return result
