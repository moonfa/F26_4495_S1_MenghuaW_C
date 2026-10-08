"""Pure helpers: sector KPI hints for prompts and a rule-based thesis health label."""
from __future__ import annotations

HINTS = [
    (("restaurant", "franchis"), "Restaurants: same-store sales and traffic versus price/mix, franchise versus company-operated mix, unit growth, franchisee profitability, food and labor costs."),
    (("semiconductor",), "Semiconductors: customer capex plans, pricing/ASP and product mix, inventory days, backlog or book-to-bill, capacity additions, competitor share shifts, cyclicality."),
    (("software", "internet", "interactive media", "platform"), "Software/internet: net revenue retention, customer and usage growth, take rate or pricing, gross margin trend, sales efficiency, competitive intensity."),
    (("bank", "insurance", "capital markets", "asset management"), "Financials: net interest margin, credit quality and provisions, capital ratios, deposit or premium growth, combined ratio for insurers."),
    (("reit",), "REITs: occupancy, same-property NOI growth, lease expiries, funds from operations, leverage and debt maturities."),
    (("pharma", "biotech", "drug"), "Pharma/biotech: patent expiries, pipeline stage and readouts, pricing and reimbursement, key-product concentration."),
    (("oil", "gas", "coal", "uranium"), "Energy: commodity price sensitivity, production and reserve replacement, breakeven cost, capital discipline, balance sheet."),
    (("utilit",), "Utilities: allowed returns and rate cases, rate-base growth, regulatory and liability exposure, leverage."),
    (("auto",), "Autos: unit volume and mix, pricing and incentives, gross margin, inventory days, capex needs."),
    (("telecom",), "Telecom: subscriber net adds, ARPU, churn, capex intensity, spectrum and leverage."),
    (("retail", "discount", "apparel", "footwear", "department", "grocery", "household", "beverage", "packaged", "luxury", "cosmetic"),
     "Retail/consumer: same-store sales, traffic versus ticket, gross margin, inventory turns, e-commerce mix, market share."),
]
SUFFIX = " List any of these the supplied data cannot test under missing_evidence."


def sector_hint(company: dict | None) -> str | None:
    co = company or {}
    text = f"{co.get('industry') or ''} {co.get('sector') or ''}".lower()
    for words, hint in HINTS:
        if any(w in text for w in words):
            return hint + SUFFIX
    return None


def health(assumptions: list[dict]) -> tuple[str, str]:
    """Intact / Watch / At risk, from structured fields only (never from model-written scores)."""
    watch = None
    for a in assumptions:
        mat, st, i = a.get("materiality") or "medium", a.get("status"), a.get("id")
        if st == "broken" or (st == "weakened" and mat == "high"):
            return "At risk", f"{i} {st} ({mat} materiality)"
        if watch is None and (st == "weakened" or (st == "unverified" and mat == "high")):
            watch = f"{i} {st}"
    return ("Watch", watch) if watch else ("Intact", "No assumption weakened or untested at high materiality")
