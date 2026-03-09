"""
Counterparty master data — 50 fictitious entities.
Distribution: 25 US · 10 UK · 8 China · 5 Brazil · 2 South Africa
"""
import json
import random
from datetime import date

random.seed(42)

# PD (annual) by internal rating — S&P-calibrated
PD_BY_RATING = {
    "AAA": 0.0001, "AA+": 0.0002, "AA": 0.0003, "AA-": 0.0005,
    "A+":  0.0008, "A":   0.0012, "A-": 0.0018,
    "BBB+":0.003,  "BBB": 0.005,  "BBB-":0.008,
    "BB+": 0.015,  "BB":  0.025,  "BB-": 0.040,
    "B+":  0.060,  "B":   0.090,  "B-":  0.140,
    "CCC+":0.220,  "CCC": 0.320,  "CCC-":0.450,
    "CC":  0.550,  "C":   0.700,  "D":   1.000,
}

RATING_ORDER = [
    "AAA","AA+","AA","AA-","A+","A","A-",
    "BBB+","BBB","BBB-","BB+","BB","BB-",
    "B+","B","B-","CCC+","CCC","CCC-","CC","C","D",
]

# Base credit spread (bps) by rating — approximate 5Y CDS spread
SPREAD_BY_RATING = {
    "AAA":5,"AA+":7,"AA":10,"AA-":14,
    "A+":20,"A":28,"A-":38,
    "BBB+":60,"BBB":85,"BBB-":120,
    "BB+":175,"BB":250,"BB-":340,
    "B+":450,"B":550,"B-":700,
    "CCC+":900,"CCC":1100,"CCC-":1400,
    "CC":1700,"C":2000,"D":2500,
}

# Sector-level financial parameters (non-FI)
# revenue_range: local-ccy billions; leverage: Net Debt / EBITDA
SECTOR_PARAMS = {
    "Energy":        dict(rev=(3.0, 40.0),  ebitda_margin=(0.18, 0.32), capex_rev=(0.08, 0.15), leverage=(1.5, 4.0),  int_rate=(0.04, 0.08)),
    "TMT":           dict(rev=(1.0, 60.0),  ebitda_margin=(0.22, 0.45), capex_rev=(0.03, 0.12), leverage=(0.5, 3.0),  int_rate=(0.035,0.065)),
    "Healthcare":    dict(rev=(2.0, 30.0),  ebitda_margin=(0.20, 0.35), capex_rev=(0.04, 0.08), leverage=(0.5, 3.0),  int_rate=(0.035,0.060)),
    "Consumer":      dict(rev=(4.0, 25.0),  ebitda_margin=(0.10, 0.22), capex_rev=(0.03, 0.07), leverage=(1.5, 4.5),  int_rate=(0.04, 0.07)),
    "Industrials":   dict(rev=(2.0, 18.0),  ebitda_margin=(0.10, 0.20), capex_rev=(0.04, 0.10), leverage=(1.5, 4.0),  int_rate=(0.04, 0.07)),
    "Real Estate":   dict(rev=(0.3, 4.0),   ebitda_margin=(0.45, 0.68), capex_rev=(0.10, 0.20), leverage=(4.0, 9.0),  int_rate=(0.04, 0.07)),
    "Mining":        dict(rev=(1.0, 15.0),  ebitda_margin=(0.28, 0.48), capex_rev=(0.10, 0.18), leverage=(0.5, 3.0),  int_rate=(0.05, 0.09)),
    # FI handled separately
    "Financial":     dict(assets=(20.0, 500.0), roe=(0.08, 0.18), equity_ratio=(0.08, 0.14), int_rate=(0.035,0.065)),
}

# FX: average 2023 rates to convert financials to USD for AI metadata
FX_TO_USD = {"USD": 1.0, "GBP": 1.24, "CNY": 1/7.10, "BRL": 1/5.00, "ZAR": 1/18.8}

# Base rate name by currency
BASE_RATE = {"USD": "SOFR", "GBP": "SONIA", "CNY": "SHIBOR", "BRL": "CDI", "ZAR": "JIBAR"}

# ── Counterparty definitions ──────────────────────────────────────────────────

RAW = [
    # ── USA (25) ──────────────────────────────────────────────────────────────
    dict(name="Nexus Energy Corp",          short="NEXUS",   country_iso2="US", country_name="United States",  hq_city="Houston",       sector="Energy",      sub_sector="Oil & Gas E&P",         currency="USD", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=28400, founded=1982, rev_scale=22.0, ebitda_m=0.25),
    dict(name="Pinnacle Petroleum Inc",     short="PINNPET", country_iso2="US", country_name="United States",  hq_city="Oklahoma City", sector="Energy",      sub_sector="Integrated Oil",         currency="USD", rating="BBB-", outlook="Negative",  is_fi=0, is_soe=0, employees=14200, founded=1974, rev_scale=9.5,  ebitda_m=0.21),
    dict(name="Meridian Resources Group",   short="MERIDRG", country_iso2="US", country_name="United States",  hq_city="Denver",        sector="Energy",      sub_sector="Mining & Metals",        currency="USD", rating="BB+",  outlook="Stable",   is_fi=0, is_soe=0, employees=8900,  founded=1998, rev_scale=5.8,  ebitda_m=0.28),
    dict(name="Summit Natural Gas LLC",     short="SUMMNG",  country_iso2="US", country_name="United States",  hq_city="Pittsburgh",    sector="Energy",      sub_sector="Gas Distribution",       currency="USD", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=0, employees=6100,  founded=1991, rev_scale=7.2,  ebitda_m=0.22),
    dict(name="Apex Digital Systems Inc",   short="APEXDS", country_iso2="US", country_name="United States",  hq_city="San Jose",      sector="TMT",         sub_sector="Semiconductors",         currency="USD", rating="AA-",  outlook="Stable",   is_fi=0, is_soe=0, employees=62000, founded=1994, rev_scale=48.0, ebitda_m=0.38),
    dict(name="Quantum Networks Corp",      short="QUANTN", country_iso2="US", country_name="United States",  hq_city="San Francisco", sector="TMT",         sub_sector="Cloud Infrastructure",   currency="USD", rating="A",    outlook="Stable",   is_fi=0, is_soe=0, employees=41000, founded=2001, rev_scale=35.0, ebitda_m=0.34),
    dict(name="CoreTech Solutions Inc",     short="CORTS",  country_iso2="US", country_name="United States",  hq_city="Seattle",       sector="TMT",         sub_sector="Enterprise Software",    currency="USD", rating="BBB+", outlook="Positive", is_fi=0, is_soe=0, employees=19000, founded=2008, rev_scale=8.4,  ebitda_m=0.29),
    dict(name="Vertex Software Holdings",   short="VERTXS", country_iso2="US", country_name="United States",  hq_city="New York",      sector="TMT",         sub_sector="Data Analytics",         currency="USD", rating="A-",   outlook="Stable",   is_fi=0, is_soe=0, employees=24500, founded=2003, rev_scale=14.2, ebitda_m=0.31),
    dict(name="Nova Communications Group",  short="NOVACG", country_iso2="US", country_name="United States",  hq_city="Dallas",        sector="TMT",         sub_sector="Telecom Services",       currency="USD", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=38000, founded=1988, rev_scale=26.0, ebitda_m=0.28),
    dict(name="Meridian Health Group",      short="MERIDH", country_iso2="US", country_name="United States",  hq_city="New York",      sector="Healthcare",  sub_sector="Managed Care",           currency="USD", rating="A+",   outlook="Stable",   is_fi=0, is_soe=0, employees=52000, founded=1979, rev_scale=38.0, ebitda_m=0.08),
    dict(name="Pinnacle Pharma Corp",       short="PINNPH", country_iso2="US", country_name="United States",  hq_city="New Jersey",    sector="Healthcare",  sub_sector="Large-Cap Pharma",       currency="USD", rating="AA-",  outlook="Stable",   is_fi=0, is_soe=0, employees=68000, founded=1962, rev_scale=42.0, ebitda_m=0.33),
    dict(name="Summit Medical Devices Inc", short="SUMMMD", country_iso2="US", country_name="United States",  hq_city="Indianapolis",  sector="Healthcare",  sub_sector="Medical Devices",        currency="USD", rating="A",    outlook="Stable",   is_fi=0, is_soe=0, employees=22000, founded=1985, rev_scale=10.5, ebitda_m=0.27),
    dict(name="Cascade Biotech Inc",        short="CASCBT", country_iso2="US", country_name="United States",  hq_city="Boston",        sector="Healthcare",  sub_sector="Biotech",                currency="USD", rating="BB+",  outlook="Negative", is_fi=0, is_soe=0, employees=3400,  founded=2012, rev_scale=1.8,  ebitda_m=0.12),
    dict(name="Horizon Retail Group Inc",   short="HORIZR", country_iso2="US", country_name="United States",  hq_city="Columbus",      sector="Consumer",    sub_sector="Specialty Retail",       currency="USD", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=95000, founded=1970, rev_scale=18.5, ebitda_m=0.11),
    dict(name="Pacific Consumer Brands",    short="PACICB", country_iso2="US", country_name="United States",  hq_city="Los Angeles",   sector="Consumer",    sub_sector="Consumer Staples",       currency="USD", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=0, employees=34000, founded=1965, rev_scale=22.0, ebitda_m=0.17),
    dict(name="Zenith Foods Corp",          short="ZENITHF",country_iso2="US", country_name="United States",  hq_city="Chicago",       sector="Consumer",    sub_sector="Packaged Foods",         currency="USD", rating="A-",   outlook="Stable",   is_fi=0, is_soe=0, employees=41000, founded=1958, rev_scale=28.0, ebitda_m=0.20),
    dict(name="Atlas Beverages Inc",        short="ATLASB", country_iso2="US", country_name="United States",  hq_city="Atlanta",       sector="Consumer",    sub_sector="Beverages",              currency="USD", rating="BBB-", outlook="Stable",   is_fi=0, is_soe=0, employees=18000, founded=1977, rev_scale=12.0, ebitda_m=0.18),
    dict(name="Titan Manufacturing Corp",   short="TITANM", country_iso2="US", country_name="United States",  hq_city="Detroit",       sector="Industrials", sub_sector="Auto Parts",             currency="USD", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=48000, founded=1955, rev_scale=15.0, ebitda_m=0.13),
    dict(name="Sterling Aerospace Group",   short="STERLA", country_iso2="US", country_name="United States",  hq_city="Hartford",      sector="Industrials", sub_sector="Aerospace & Defence",    currency="USD", rating="A-",   outlook="Stable",   is_fi=0, is_soe=0, employees=32000, founded=1949, rev_scale=19.0, ebitda_m=0.17),
    dict(name="Redwood Engineering Inc",    short="REDWDE", country_iso2="US", country_name="United States",  hq_city="Portland",      sector="Industrials", sub_sector="Industrial Equipment",   currency="USD", rating="BBB-", outlook="Negative", is_fi=0, is_soe=0, employees=11000, founded=1988, rev_scale=4.2,  ebitda_m=0.12),
    dict(name="Cascade Industrial Holdings",short="CASCIH", country_iso2="US", country_name="United States",  hq_city="Philadelphia",  sector="Industrials", sub_sector="Diversified Industrials",currency="USD", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=0, employees=27000, founded=1972, rev_scale=10.8, ebitda_m=0.15),
    dict(name="Summit REIT Inc",            short="SUMMRE", country_iso2="US", country_name="United States",  hq_city="New York",      sector="Real Estate", sub_sector="Commercial REIT",        currency="USD", rating="BBB-", outlook="Stable",   is_fi=0, is_soe=0, employees=890,   founded=2004, rev_scale=1.8,  ebitda_m=0.55),
    dict(name="Horizon Property Trust",     short="HORIZPT",country_iso2="US", country_name="United States",  hq_city="Dallas",        sector="Real Estate", sub_sector="Diversified REIT",       currency="USD", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=650,   founded=1999, rev_scale=2.4,  ebitda_m=0.58),
    dict(name="Atlantic Investment Bank",   short="ATLAINV",country_iso2="US", country_name="United States",  hq_city="New York",      sector="Financial",   sub_sector="Investment Banking",     currency="USD", rating="A",    outlook="Stable",   is_fi=1, is_soe=0, employees=42000, founded=1945, rev_scale=None, ebitda_m=None),
    dict(name="Pacific Capital Management", short="PACCAP", country_iso2="US", country_name="United States",  hq_city="San Francisco", sector="Financial",   sub_sector="Asset Management",       currency="USD", rating="A-",   outlook="Stable",   is_fi=1, is_soe=0, employees=8500,  founded=1988, rev_scale=None, ebitda_m=None),

    # ── UK (10) ───────────────────────────────────────────────────────────────
    dict(name="Crown Financial Group plc",  short="CROWNF", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Financial",   sub_sector="Universal Banking",      currency="GBP", rating="A+",   outlook="Stable",   is_fi=1, is_soe=0, employees=88000, founded=1836, rev_scale=None, ebitda_m=None),
    dict(name="Thames Capital Partners plc",short="THAMES", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Financial",   sub_sector="Investment Banking",     currency="GBP", rating="A",    outlook="Stable",   is_fi=1, is_soe=0, employees=12000, founded=1978, rev_scale=None, ebitda_m=None),
    dict(name="Regent Banking Corp plc",    short="REGBNK", country_iso2="GB", country_name="United Kingdom", hq_city="Edinburgh",     sector="Financial",   sub_sector="Retail Banking",         currency="GBP", rating="BBB+", outlook="Stable",   is_fi=1, is_soe=0, employees=28000, founded=1921, rev_scale=None, ebitda_m=None),
    dict(name="Britannia Retail Holdings",  short="BRITRH", country_iso2="GB", country_name="United Kingdom", hq_city="Manchester",    sector="Consumer",    sub_sector="Grocery Retail",         currency="GBP", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=120000,founded=1869, rev_scale=14.0, ebitda_m=0.08),
    dict(name="Albion Consumer Brands plc", short="ALBION", country_iso2="GB", country_name="United Kingdom", hq_city="Birmingham",    sector="Consumer",    sub_sector="Consumer Products",      currency="GBP", rating="BBB-", outlook="Negative", is_fi=0, is_soe=0, employees=18000, founded=1955, rev_scale=5.2,  ebitda_m=0.13),
    dict(name="Royal Foods Group plc",      short="ROYALF", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Consumer",    sub_sector="Food Manufacturing",     currency="GBP", rating="A-",   outlook="Stable",   is_fi=0, is_soe=0, employees=32000, founded=1912, rev_scale=9.8,  ebitda_m=0.18),
    dict(name="North Sea Resources plc",    short="NORTHSR",country_iso2="GB", country_name="United Kingdom", hq_city="Aberdeen",      sector="Energy",      sub_sector="Oil & Gas E&P",         currency="GBP", rating="BBB-", outlook="Negative", is_fi=0, is_soe=0, employees=6800,  founded=1982, rev_scale=6.5,  ebitda_m=0.24),
    dict(name="British Power Holdings plc", short="BRITPH", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Energy",      sub_sector="Power & Utilities",      currency="GBP", rating="BB+",  outlook="Stable",   is_fi=0, is_soe=0, employees=9200,  founded=1998, rev_scale=4.8,  ebitda_m=0.19),
    dict(name="London Property REIT plc",   short="LONPRE", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Real Estate", sub_sector="Commercial REIT",        currency="GBP", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=420,   founded=2002, rev_scale=0.9,  ebitda_m=0.62),
    dict(name="Crown Estates Holdings plc", short="CRWNES", country_iso2="GB", country_name="United Kingdom", hq_city="London",        sector="Real Estate", sub_sector="Mixed-Use Real Estate",  currency="GBP", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=0, employees=580,   founded=1995, rev_scale=1.4,  ebitda_m=0.58),

    # ── China (8) ─────────────────────────────────────────────────────────────
    dict(name="Longhua Steel Corporation",  short="LONGHST",country_iso2="CN", country_name="China",          hq_city="Shanghai",      sector="Industrials", sub_sector="Steel & Metals",         currency="CNY", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=1, employees=82000, founded=1958, rev_scale=95.0, ebitda_m=0.12),
    dict(name="Beihai Infrastructure Group",short="BEIHIG", country_iso2="CN", country_name="China",          hq_city="Beijing",       sector="Industrials", sub_sector="Construction",           currency="CNY", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=1, employees=55000, founded=1965, rev_scale=140.0,ebitda_m=0.10),
    dict(name="Yangtze Industrial Holdings",short="YANGIH", country_iso2="CN", country_name="China",          hq_city="Wuhan",         sector="Industrials", sub_sector="Diversified Industrials",currency="CNY", rating="BB+",  outlook="Stable",   is_fi=0, is_soe=0, employees=28000, founded=2001, rev_scale=42.0, ebitda_m=0.11),
    dict(name="Dongfang Technology Corp",   short="DONGTC", country_iso2="CN", country_name="China",          hq_city="Shenzhen",      sector="TMT",         sub_sector="Consumer Electronics",   currency="CNY", rating="A-",   outlook="Positive", is_fi=0, is_soe=0, employees=95000, founded=1996, rev_scale=220.0,ebitda_m=0.14),
    dict(name="Horizon Digital China Ltd",  short="HORIZDC",country_iso2="CN", country_name="China",          hq_city="Beijing",       sector="TMT",         sub_sector="Internet Services",      currency="CNY", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=0, employees=48000, founded=2004, rev_scale=88.0, ebitda_m=0.22),
    dict(name="Kunlun Tech Holdings",       short="KUNLTH", country_iso2="CN", country_name="China",          hq_city="Hangzhou",      sector="TMT",         sub_sector="E-Commerce",             currency="CNY", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=0, employees=32000, founded=2008, rev_scale=55.0, ebitda_m=0.18),
    dict(name="Huanghe Energy Group",       short="HUANHE", country_iso2="CN", country_name="China",          hq_city="Xi'an",         sector="Energy",      sub_sector="Coal & Power",           currency="CNY", rating="BBB",  outlook="Stable",   is_fi=0, is_soe=1, employees=44000, founded=1972, rev_scale=80.0, ebitda_m=0.16),
    dict(name="Bohai Petroleum Corp",       short="BOHAIP", country_iso2="CN", country_name="China",          hq_city="Tianjin",       sector="Energy",      sub_sector="Integrated Oil",         currency="CNY", rating="BBB+", outlook="Stable",   is_fi=0, is_soe=1, employees=62000, founded=1955, rev_scale=120.0,ebitda_m=0.18),

    # ── Brazil (5) ────────────────────────────────────────────────────────────
    dict(name="Amazônia Energia S.A.",      short="AMAZEN", country_iso2="BR", country_name="Brazil",         hq_city="São Paulo",     sector="Energy",      sub_sector="Power Generation",       currency="BRL", rating="BB+",  outlook="Stable",   is_fi=0, is_soe=0, employees=12000, founded=1994, rev_scale=28.0, ebitda_m=0.34),
    dict(name="Rio Petróleo Corp S.A.",     short="RIOPET", country_iso2="BR", country_name="Brazil",         hq_city="Rio de Janeiro",sector="Energy",      sub_sector="Oil & Gas E&P",         currency="BRL", rating="BB",   outlook="Negative", is_fi=0, is_soe=0, employees=8500,  founded=2001, rev_scale=15.0, ebitda_m=0.28),
    dict(name="Banco Prata S.A.",           short="BPRATA", country_iso2="BR", country_name="Brazil",         hq_city="São Paulo",     sector="Financial",   sub_sector="Commercial Banking",     currency="BRL", rating="BB+",  outlook="Stable",   is_fi=1, is_soe=0, employees=34000, founded=1968, rev_scale=None, ebitda_m=None),
    dict(name="Brasil Varejo Group S.A.",   short="BRVARE", country_iso2="BR", country_name="Brazil",         hq_city="São Paulo",     sector="Consumer",    sub_sector="Retail",                 currency="BRL", rating="BB",   outlook="Stable",   is_fi=0, is_soe=0, employees=42000, founded=1985, rev_scale=22.0, ebitda_m=0.09),
    dict(name="Mercado Sul Holdings S.A.",  short="MERCSUL",country_iso2="BR", country_name="Brazil",         hq_city="Curitiba",      sector="Consumer",    sub_sector="Food & Grocery",         currency="BRL", rating="BB+",  outlook="Positive", is_fi=0, is_soe=0, employees=28000, founded=1992, rev_scale=18.0, ebitda_m=0.11),

    # ── South Africa (2) ──────────────────────────────────────────────────────
    dict(name="Rand Mining Corporation Ltd",short="RANDMC", country_iso2="ZA", country_name="South Africa",   hq_city="Johannesburg",  sector="Mining",      sub_sector="Gold & Platinum",        currency="ZAR", rating="BB+",  outlook="Stable",   is_fi=0, is_soe=0, employees=38000, founded=1946, rev_scale=85.0, ebitda_m=0.38),
    dict(name="Cape Financial Group Ltd",   short="CAPEFG", country_iso2="ZA", country_name="South Africa",   hq_city="Cape Town",     sector="Financial",   sub_sector="Diversified Financial",  currency="ZAR", rating="BB",   outlook="Stable",   is_fi=1, is_soe=0, employees=14000, founded=1974, rev_scale=None, ebitda_m=None),
]


def _lei(seed_str):
    """Generate a deterministic fictitious 20-char LEI."""
    rng = random.Random(seed_str)
    prefix = "9999"  # fictitious registrar code
    body = "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=14))
    check = str(rng.randint(10, 99))
    return prefix + body + check


def _risk_tags(r):
    tags = []
    tags.append(r["sector"].lower().replace(" ", "-"))
    tags.append(r["country_iso2"].lower())
    if r["country_iso2"] in ("US", "GB"):
        tags.append("developed-market")
    else:
        tags.append("emerging-market")
    if r["is_fi"]:
        tags.append("financial-institution")
    if r["is_soe"]:
        tags.append("state-owned-enterprise")
    ri = RATING_ORDER.index(r["rating"])
    if ri <= 6:
        tags.append("investment-grade-high")
    elif ri <= 9:
        tags.append("investment-grade")
    elif ri <= 12:
        tags.append("high-yield")
    else:
        tags.append("distressed")
    if r["outlook"] == "Negative":
        tags.append("negative-outlook")
    if r["outlook"] == "Positive":
        tags.append("positive-outlook")
    if r.get("ebitda_m") and r["ebitda_m"] < 0.10:
        tags.append("thin-margins")
    return tags


def _ai_summary(r):
    sector_desc = r["sub_sector"] or r["sector"]
    domicile = "state-owned " if r["is_soe"] else ""
    fi_note = "financial institution" if r["is_fi"] else f"{sector_desc} company"
    spread = SPREAD_BY_RATING.get(r["rating"], 100)
    return (
        f"{r['name']} is a {domicile}{fi_note} headquartered in {r['hq_city']}, {r['country_name']}. "
        f"It carries an internal credit rating of {r['rating']} ({r['outlook']}) with an implied "
        f"5Y CDS spread of approximately {spread} bps. "
        f"Founded in {r['founded']}, it employs approximately {r['employees']:,} staff."
    )


def _embedding_text(r):
    tags = _risk_tags(r)
    return (
        f"Entity: {r['name']}. Country: {r['country_name']} ({r['country_iso2']}). "
        f"Sector: {r['sector']} / {r['sub_sector']}. "
        f"Functional currency: {r['currency']}. "
        f"Credit rating: {r['rating']}, outlook {r['outlook']}. "
        f"State-owned: {'yes' if r['is_soe'] else 'no'}. "
        f"Financial institution: {'yes' if r['is_fi'] else 'no'}. "
        f"Employees: {r['employees']:,}. Founded: {r['founded']}. "
        f"Risk tags: {', '.join(tags)}."
    )


def build_counterparties():
    today = date.today().isoformat()
    rows = []
    for i, r in enumerate(RAW, start=1):
        rows.append({
            "id":                     i,
            "name":                   r["name"],
            "short_name":             r["short"],
            "country_iso2":           r["country_iso2"],
            "country_name":           r["country_name"],
            "sector":                 r["sector"],
            "sub_sector":             r["sub_sector"],
            "currency":               r["currency"],
            "internal_rating":        r["rating"],
            "external_shadow_rating": r["rating"],
            "rating_outlook":         r["outlook"],
            "is_financial_institution": int(r["is_fi"]),
            "is_soe":                 int(r["is_soe"]),
            "employee_count":         r["employees"],
            "founded_year":           r["founded"],
            "hq_city":                r["hq_city"],
            "lei":                    _lei(r["name"]),
            "ai_summary":             _ai_summary(r),
            "risk_tags":              json.dumps(_risk_tags(r)),
            "embedding_text":         _embedding_text(r),
            "anomaly_score":          0.0,
            "alert_flags":            json.dumps(["negative-outlook"] if r["outlook"] == "Negative" else []),
            "last_updated":           today,
        })
    return rows


def insert_counterparties(conn):
    rows = build_counterparties()
    conn.executemany("""
        INSERT OR REPLACE INTO counterparties
        (id, name, short_name, country_iso2, country_name, sector, sub_sector,
         currency, internal_rating, external_shadow_rating, rating_outlook,
         is_financial_institution, is_soe, employee_count, founded_year,
         hq_city, lei, ai_summary, risk_tags, embedding_text,
         anomaly_score, alert_flags, last_updated)
        VALUES
        (:id,:name,:short_name,:country_iso2,:country_name,:sector,:sub_sector,
         :currency,:internal_rating,:external_shadow_rating,:rating_outlook,
         :is_financial_institution,:is_soe,:employee_count,:founded_year,
         :hq_city,:lei,:ai_summary,:risk_tags,:embedding_text,
         :anomaly_score,:alert_flags,:last_updated)
    """, rows)
    conn.commit()
    print(f"  Inserted {len(rows)} counterparties.")
    return rows


def insert_credit_ratings(conn, cp_rows):
    """Seed a 5-year rating history per counterparty (one entry per year + current)."""
    rng = random.Random(99)
    records = []
    years = [2021, 2022, 2023, 2024, 2025]
    for cp in cp_rows:
        base_idx = RATING_ORDER.index(cp["internal_rating"])
        prev_idx = base_idx
        for yr in years:
            # Small random drift in rating (±1 notch occasionally)
            drift = rng.choices([-1, 0, 0, 0, 1], k=1)[0]
            curr_idx = max(0, min(len(RATING_ORDER)-1, prev_idx + drift))
            rating = RATING_ORDER[curr_idx]
            outlook = cp["rating_outlook"] if yr == 2025 else rng.choice(["Stable", "Stable", "Stable", "Positive", "Negative"])
            records.append({
                "counterparty_id": cp["id"],
                "rating_date":     f"{yr}-12-31",
                "rating":          rating,
                "outlook":         outlook,
                "rating_type":     "Internal",
                "analyst_notes":   f"Annual review {yr}. Rating: {rating}, Outlook: {outlook}.",
            })
            prev_idx = curr_idx
    conn.executemany("""
        INSERT OR IGNORE INTO credit_ratings
        (counterparty_id, rating_date, rating, outlook, rating_type, analyst_notes)
        VALUES (:counterparty_id,:rating_date,:rating,:outlook,:rating_type,:analyst_notes)
    """, records)
    conn.commit()
    print(f"  Inserted {len(records)} credit rating records.")
