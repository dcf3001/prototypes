import httpx

WB_BASE = "https://api.worldbank.org/v2"

INDICATORS = {
    "gdp_growth":      "NY.GDP.MKTP.KD.ZG",
    "gdp_per_capita":  "NY.GDP.PCAP.CD",
    "inflation":       "FP.CPI.TOTL.ZG",
    "debt_gdp":        "GC.DOD.TOTL.GD.ZS",
    "ca_gdp":          "BN.CAB.XOKA.GD.ZS",
    "reserves_months": "FI.RES.TOTL.MO",
}


async def fetch_countries(db):
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{WB_BASE}/country?format=json&per_page=300")
        resp.raise_for_status()
        _meta, data = resp.json()

    countries = [
        c for c in data
        if c.get("region") and c["region"].get("id") != "NA"
        and c.get("iso2Code", "").strip()
        and c.get("id", "").strip()
    ]

    for c in countries:
        db.execute(
            "INSERT OR IGNORE INTO countries (iso2, iso3, name, region, income_group) VALUES (?,?,?,?,?)",
            (
                c["iso2Code"].strip(),
                c["id"].strip(),
                c["name"],
                c.get("region", {}).get("value"),
                c.get("incomeLevel", {}).get("value"),
            )
        )
    db.commit()
    print(f"[worldbank] Seeded {len(countries)} countries")
    return len(countries)


async def sync_country_fundamentals(db, iso2):
    row = db.execute("SELECT * FROM countries WHERE iso2=?", (iso2,)).fetchone()
    if not row:
        raise ValueError(f"Country not found: {iso2}")
    country = dict(row)

    values = {"country_id": country["id"], "year": None}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for field, code in INDICATORS.items():
            try:
                resp = await client.get(
                    f"{WB_BASE}/country/{iso2}/indicator/{code}?format=json&mrv=5"
                )
                if not resp.is_success:
                    continue
                body = resp.json()
                if not isinstance(body, list) or len(body) < 2 or not body[1]:
                    continue
                rows = body[1]
                for r in rows:
                    if r.get("value") is not None:
                        values[field] = r["value"]
                        if values["year"] is None and r.get("date"):
                            try:
                                values["year"] = int(r["date"])
                            except (ValueError, TypeError):
                                pass
                        break
            except Exception as e:
                print(f"[worldbank] Failed {code} for {iso2}: {e}")

    if values["year"] is None:
        from datetime import datetime
        values["year"] = datetime.now().year - 1

    db.execute("""
        INSERT OR REPLACE INTO fundamentals
            (country_id, year, gdp_growth, gdp_per_capita, debt_gdp, deficit_gdp,
             ca_gdp, reserves_months, inflation)
        VALUES (:country_id, :year, :gdp_growth, :gdp_per_capita, :debt_gdp, :deficit_gdp,
                :ca_gdp, :reserves_months, :inflation)
    """, {
        "country_id": values["country_id"],
        "year": values["year"],
        "gdp_growth": values.get("gdp_growth"),
        "gdp_per_capita": values.get("gdp_per_capita"),
        "debt_gdp": values.get("debt_gdp"),
        "deficit_gdp": values.get("deficit_gdp"),
        "ca_gdp": values.get("ca_gdp"),
        "reserves_months": values.get("reserves_months"),
        "inflation": values.get("inflation"),
    })
    db.commit()

    result = db.execute(
        "SELECT * FROM fundamentals WHERE country_id=? ORDER BY year DESC LIMIT 1",
        (country["id"],)
    ).fetchone()
    return dict(result) if result else {}
