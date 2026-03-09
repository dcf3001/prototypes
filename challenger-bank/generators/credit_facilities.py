"""
Generate the loan book (credit_facilities) and credit_events.
~90-100 facilities across 50 counterparties.
Risk parameters: PD, LGD, EAD, EL, RWA (Basel III Standardised Approach).
"""
import json
import random
from datetime import date, timedelta
from generators.counterparties import PD_BY_RATING, SPREAD_BY_RATING, RAW, BASE_RATE

RNG = random.Random(13)

# LGD by seniority
LGD_MAP = {
    "Senior Secured":   0.30,
    "Senior Unsecured": 0.55,
    "Subordinated":     0.75,
    "Mezzanine":        0.85,
}

# Basel III SA credit risk weights for corporates by rating bucket
RW_CORP = {
    "AAA": 0.20, "AA+": 0.20, "AA": 0.20, "AA-": 0.20,
    "A+":  0.50, "A":   0.50, "A-": 0.50,
    "BBB+":0.75, "BBB": 0.75, "BBB-":0.75,
    "BB+": 1.00, "BB":  1.00, "BB-": 1.00,
    "B+":  1.50, "B":   1.50, "B-":  1.50,
    "CCC+":1.50, "CCC": 1.50, "CCC-":1.50,
    "CC":  1.50, "C":   1.50, "D":   1.50,
}
# FI risk weight is 40% (IG) or 75% (non-IG)
RW_FI_IG  = 0.40
RW_FI_HIG = 0.75

# FX rate end-2025 (local per USD) for converting to USD
FX_END25 = {"USD": 1.0, "GBP": 1/1.27, "CNY": 7.15, "BRL": 5.10, "ZAR": 18.5}

FACILITY_TYPES = ["Term Loan A", "Term Loan B", "RCF", "Trade Finance"]
SENIORITIES    = ["Senior Secured", "Senior Unsecured"]
COLLATERAL     = ["None", "Real Estate", "Equipment", "Receivables", "Pledge over Shares"]

IG_RATINGS = {"AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-"}


def _rand_date(start_yr, end_yr):
    start = date(start_yr, 1, 1)
    end   = date(end_yr, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=RNG.randint(0, delta))


def _facility_count(cp_raw):
    """Larger / more active counterparties get more facilities."""
    if cp_raw["is_fi"]:
        return RNG.randint(1, 2)
    rev = cp_raw.get("rev_scale", 5) or 5
    if rev > 30:
        return RNG.randint(2, 3)
    elif rev > 10:
        return RNG.randint(1, 3)
    else:
        return RNG.randint(1, 2)


def _credit_event(cp_id, facility_id, rating, outlook):
    """Occasionally generate a credit event for watchlist / covenant breach entities."""
    if outlook == "Negative" and RNG.random() < 0.5:
        event_date = _rand_date(2022, 2025)
        etype = RNG.choice(["Covenant Breach", "Watchlist Add", "Rating Downgrade"])
        return {
            "counterparty_id": cp_id,
            "facility_id":     facility_id,
            "event_date":      event_date.isoformat(),
            "event_type":      etype,
            "description":     f"{etype} triggered following adverse financial developments.",
            "resolution":      None,
            "resolved_date":   None,
        }
    return None


def build_facilities(cp_rows):
    facilities = []
    events     = []

    for cp in cp_rows:
        cp_id      = cp["id"]
        rating     = cp["internal_rating"]
        outlook    = cp["rating_outlook"]
        ccy        = cp["currency"]
        is_fi      = cp["is_financial_institution"]
        raw        = RAW[cp_id - 1]
        rev_scale  = raw.get("rev_scale") or 5.0

        n_fac = _facility_count(raw)

        for f_num in range(n_fac):
            ftype = RNG.choice(FACILITY_TYPES)
            if is_fi:
                ftype = RNG.choice(["RCF", "Term Loan A"])

            # Limit sizing: roughly 8-25% of revenue (for non-FI), smaller for EM
            em_factor = 0.8 if cp["country_iso2"] in ("BR", "ZA") else 1.0
            limit_frac = RNG.uniform(0.08, 0.25) * em_factor
            limit_lcl  = round(rev_scale * limit_frac, 3)  # local ccy billions
            limit_lcl  = max(limit_lcl, 0.05)

            # Drawn amount
            if ftype == "RCF":
                draw_pct = RNG.uniform(0.20, 0.75)
            elif ftype == "Trade Finance":
                draw_pct = RNG.uniform(0.60, 1.00)
            else:
                draw_pct = RNG.uniform(0.90, 1.00)
            drawn    = round(limit_lcl * draw_pct, 3)
            undrawn  = round(limit_lcl - drawn, 3)

            # Tenor
            orig_date = _rand_date(2019, 2024)
            if ftype == "Trade Finance":
                mat_date = orig_date + timedelta(days=RNG.randint(90, 365))
            elif ftype == "Term Loan B":
                mat_date = orig_date + timedelta(days=RNG.randint(5*365, 7*365))
            else:
                mat_date = orig_date + timedelta(days=RNG.randint(3*365, 5*365))

            # Seniority and collateral
            seniority = RNG.choice(SENIORITIES)
            if seniority == "Senior Secured":
                collateral = RNG.choice(COLLATERAL[1:])
            else:
                collateral = "None"

            # Covenants (mostly for leveraged names)
            cov_lev = None
            cov_cov = None
            if rating not in IG_RATINGS or RNG.random() < 0.3:
                cov_lev = round(RNG.uniform(4.0, 7.5), 1)
                cov_cov = round(RNG.uniform(1.5, 2.5), 1)

            # Risk parameters
            pd   = PD_BY_RATING[rating]
            lgd  = LGD_MAP[seniority]
            # EAD in USD billions
            ead_usd = drawn / FX_END25[ccy]
            el_usd  = pd * lgd * ead_usd
            if is_fi:
                rw = RW_FI_IG if rating in IG_RATINGS else RW_FI_HIG
            else:
                rw = RW_CORP.get(rating, 1.00)
            rwa_usd = ead_usd * rw

            # Spread over base rate
            base_spread = SPREAD_BY_RATING.get(rating, 200)
            spread_bps  = base_spread + RNG.uniform(-15, 40)

            # Status
            today = date(2026, 1, 1)
            if mat_date < today:
                status = "Repaid"
            elif outlook == "Negative" and RNG.random() < 0.15:
                status = "Watchlist"
            else:
                status = "Active"

            fac = {
                "counterparty_id":     cp_id,
                "facility_name":       f"{cp['short_name']} {ftype} {f_num+1}",
                "facility_type":       ftype,
                "currency":            ccy,
                "limit_amount":        limit_lcl,
                "drawn_amount":        drawn,
                "undrawn_amount":      undrawn,
                "base_rate":           BASE_RATE[ccy],
                "credit_spread_bps":   round(spread_bps, 1),
                "origination_date":    orig_date.isoformat(),
                "maturity_date":       mat_date.isoformat(),
                "seniority":           seniority,
                "collateral_type":     collateral,
                "covenant_leverage_max":  cov_lev,
                "covenant_coverage_min":  cov_cov,
                "status":              status,
                "pd":                  round(pd, 6),
                "lgd":                 round(lgd, 4),
                "ead":                 round(ead_usd, 6),
                "expected_loss":       round(el_usd, 6),
                "rwa":                 round(rwa_usd, 6),
                "risk_weight":         round(rw, 2),
                "ai_summary":          (
                    f"{ftype} to {cp['name']} ({rating}): limit {limit_lcl:.2f}B {ccy}, "
                    f"drawn {drawn:.2f}B {ccy}, {spread_bps:.0f}bps over {BASE_RATE[ccy]}, "
                    f"maturing {mat_date.strftime('%b %Y')}. "
                    f"EL {el_usd*1000:.1f}M USD, RWA {rwa_usd*1000:.1f}M USD."
                ),
                "risk_tags": json.dumps(
                    [ftype.lower().replace(" ", "-"), seniority.lower().replace(" ", "-"),
                     ("ig" if rating in IG_RATINGS else "hy"), status.lower()]
                ),
                "anomaly_score": 0.0,
            }
            facilities.append(fac)

            # Possibly add a credit event
            ev = _credit_event(cp_id, None, rating, outlook)
            if ev:
                events.append(ev)

    return facilities, events


def insert_credit_facilities(conn, cp_rows):
    facilities, events = build_facilities(cp_rows)

    conn.executemany("""
        INSERT INTO credit_facilities
        (counterparty_id, facility_name, facility_type, currency,
         limit_amount, drawn_amount, undrawn_amount,
         base_rate, credit_spread_bps, origination_date, maturity_date,
         seniority, collateral_type, covenant_leverage_max, covenant_coverage_min,
         status, pd, lgd, ead, expected_loss, rwa, risk_weight,
         ai_summary, risk_tags, anomaly_score)
        VALUES
        (:counterparty_id,:facility_name,:facility_type,:currency,
         :limit_amount,:drawn_amount,:undrawn_amount,
         :base_rate,:credit_spread_bps,:origination_date,:maturity_date,
         :seniority,:collateral_type,:covenant_leverage_max,:covenant_coverage_min,
         :status,:pd,:lgd,:ead,:expected_loss,:rwa,:risk_weight,
         :ai_summary,:risk_tags,:anomaly_score)
    """, facilities)

    if events:
        conn.executemany("""
            INSERT INTO credit_events
            (counterparty_id, facility_id, event_date, event_type, description,
             resolution, resolved_date)
            VALUES (:counterparty_id, :facility_id, :event_date, :event_type,
                    :description, :resolution, :resolved_date)
        """, events)

    conn.commit()
    print(f"  Inserted {len(facilities)} facilities, {len(events)} credit events.")
    return facilities
