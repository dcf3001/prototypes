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


async def research_country(country_name: str) -> str:
    """
    Use OpenAI Responses API with web search to gather a current, statistics-rich
    research brief on the country across all six credit pillars.
    Returns plain text; falls back to empty string on any error.
    """
    try:
        client = get_openai_client()
        if not hasattr(client, "responses"):
            return ""
        response = await client.responses.create(
            model="gpt-4o",
            tools=[{"type": "web_search_preview"}],
            input=(
                f"You are a sovereign credit analyst preparing a research brief on {country_name}. "
                f"Search for current information and compile specific, up-to-date statistics on:\n"
                f"1. ECONOMY: Latest GDP growth rate, GDP per capita, unemployment rate, "
                f"   major growth drivers, recent economic performance and outlook.\n"
                f"2. FISCAL: Government debt-to-GDP ratio, fiscal deficit/surplus, "
                f"   recent budget developments, IMF assessments of fiscal sustainability.\n"
                f"3. EXTERNAL: Current account balance, foreign exchange reserves (months of import cover), "
                f"   external debt levels, trade balance, main export commodities/partners.\n"
                f"4. MONETARY: Current inflation rate, central bank policy rate, "
                f"   recent monetary policy decisions, exchange rate performance.\n"
                f"5. BANKING: Banking sector capital ratios, NPL ratios, recent stress test results "
                f"   or IMF/World Bank financial stability assessments if available.\n"
                f"6. POLITICAL: Current government, political stability, recent elections or political events, "
                f"   rule of law and corruption perception index scores, geopolitical risks.\n\n"
                f"Return a structured research brief with specific named statistics and data points. "
                f"Include the source year for each statistic where possible."
            ),
        )
        return response.output_text or ""
    except Exception as e:
        print(f"[openai] Web research failed for {country_name}: {e}")
        return ""


async def get_rating(
    country_name: str,
    fundamentals: dict,
    headlines: list,
    memories: list,
    research_brief: str = "",
) -> dict:
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

    research_section = f"\n\n## Web Research Brief\n{research_brief}" if research_brief else ""

    system_prompt = f"""You are a senior sovereign credit analyst producing a full analytical report for a major ratings agency.

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

CRITICAL WRITING RULES FOR PILLAR SUMMARIES:
- Each "summary" field MUST contain AT LEAST 450 words of continuous analytical prose
- Write as a professional analyst report — flowing paragraphs, NO headings, NO labels, NO bullet points
- Each paragraph must be substantive (80-120 words) and develop a distinct analytical point
- Cite specific statistics, percentages, rankings and named data sources (e.g. "IMF data shows debt at 89% of GDP", "the World Bank's 2024 Doing Business index", "Transparency International ranks it 45th")
- Analyse trends, not just snapshots — explain the direction of travel and what is driving it
- Be country-specific: every paragraph must clearly be about this specific country
- Paragraphs must be separated by \\n\\n in the JSON string value

Respond ONLY with valid JSON. No markdown fences, no commentary outside the JSON object.
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
  "rationale": "2-3 sentence overall summary explaining the assigned rating and outlook.",
  "pillar_analysis": {{
    "economic_strength": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's economic strength, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["Concrete strength with specific data point", "Second concrete strength", "Third concrete strength"],
      "risks": ["Concrete risk with specific context", "Second concrete risk", "Third concrete risk"]
    }},
    "fiscal_position": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's fiscal position, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "external_position": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's external position, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "monetary_policy": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's monetary policy framework, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "banking_sector": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's banking sector health, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }},
    "political_governance": {{
      "summary": "REQUIRED: at least 450 words of flowing analytical prose about this country's political and governance environment, with specific statistics. NO paragraph labels. Paragraphs separated by \\n\\n.",
      "strengths": ["...", "...", "..."],
      "risks": ["...", "...", "..."]
    }}
  }}
}}"""

    user_prompt = f"""## Country: {country_name}

## World Bank Fundamentals
{fund_text}

## Recent News Headlines
{head_text}

## Analyst Memory Notes
{mem_text}{research_section}

Produce a full sovereign credit rating and pillar-by-pillar analysis for {country_name}.
Each pillar summary must be at least 450 words of flowing, statistics-rich analytical prose."""

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        temperature=0.3,
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
