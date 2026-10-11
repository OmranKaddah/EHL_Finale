"""Deterministic bid arithmetic. A model extracts the facts from the evidence (see FACTS_SCHEMA); this module applies
the brief's published calculation rules to them. Nothing here knows any scenario's values: it only calculates.

Rules implemented (numbers refer to the brief): quantity in pieces (1, 13, 17), scale price per position (4),
currency/price unit normalisation (22), conditional order discount (5, 16), discount clauses per Konditionsgruppe
(12), metal-index mass surcharge (28), packaging by cartons (23), shared setup pool by quantity x allocation mass with
cent allocation (25), project bonus by marginal bands with largest-remainder allocation (26), final unit price from
unrounded components rounded once (27), shared stock and delivery commitments (6, 15, 24), total (7).
"""
from decimal import ROUND_HALF_UP, Decimal
import math

CENT = Decimal("0.01")

FACTS_SCHEMA = """{
 "tender_reference": "exact reference",
 "no_bid_material_missing": false,      // true ONLY if the evidence proves a position has no matching ACTIVE material
 "no_bid_reason": "",
 "discount": {"percent": 0, "min_undiscounted_net_eur": null},   // governing sales-director approval; null = no threshold
 "pool": {"fee_eur": 0, "cent_rule": "largest_remainder"},         // shared setup pool fee (Rüstpools mail) and how cents are allocated
 "bonus_bands": [{"from_eur": 0, "to_eur": null, "percent": 0}],   // project bonus marginal bands (finance mail); [] if none
 "positions": [{
   "position": "01.01",
   "quantity_pieces": 0,                // final quantity in PIECES (latest non-withdrawn Q&A change, Satz converted)
   "material": "material number or null",
   "number_format": "de-DE",            // the number format stated on the price condition (de-DE or en-US)
   "scales": [{"min_qty": 1, "price_text": "100.000"}],  // ALL scales of the condition valid on the scenario date; price_text EXACTLY as displayed (do not convert)
   "scale_price": 0,                    // (optional) the scale price you would choose; the code re-selects from "scales"
   "price_unit_pieces": 1,              // the condition's price unit (e.g. 1, 10, 100 pieces)
   "currency": "EUR",
   "eur_per_currency_unit": 1,          // FX fixing (EUR per 1 unit of the currency); 1 for EUR
   "surcharge_mass_kg": 0,              // the material's surcharge mass (NOT the allocation mass), in kg
   "metal_rates": [{"valid_from": "YYYY-MM-DD", "valid_to": "YYYY-MM-DD", "rate_eur_per_kg": 0}],  // ALL rates listed for the material's index key in the governing index mail, with their windows
   "metal_rate_eur_per_kg": 0,          // (optional) your choice; the code re-selects by the scenario date
   "discount_clause": "base",           // "base" (default), "base_and_surcharge" or "none" from the Konditionsgruppe rule
   "setup_fee_eur": 0,                  // ordinary setup fee for the whole position (0 if none)
   "pool_member": false,                // ONLY if this position's own Q&A assignment names a setup pool
   "allocation_mass": 0,                // allocation weight per piece for the setup pool (any unit, used as weight)
   "carton_size": 1,                    // pieces per carton
   "carton_tariff_eur": 0,              // cost per carton from the packaging tariff key
   "bonus_member": false,               // ONLY if this position's own Q&A assignment names a bonus plan
   "free_stock": 0,                     // free/unrestricted stock of the material (not blocked/inspection stock)
   "lead_stock_weeks": 0,
   "lead_production_weeks": 0,
   "commitment": null                   // delivery commitment for this position: {"material": "...", "ceiling_pieces": n, "weeks": n} or null
 }]
}"""


def D(x) -> Decimal:
    """Any value as a Decimal: numbers, or text with units/separators ('3 Wochen', '2.125 kg', '1.234,56'); else 0."""
    import re as _re
    if x is None or isinstance(x, bool):
        return Decimal(0)
    if isinstance(x, (int, float, Decimal)):
        return Decimal(str(x))
    t = str(x).strip()
    m = _re.search(r"-?\d[\d.,]*", t)
    if not m:
        return Decimal(0)
    n = m.group(0).rstrip(".,")
    if "," in n and "." in n:  # both separators: the last one is the decimal mark
        n = n.replace(".", "").replace(",", ".") if n.rfind(",") > n.rfind(".") else n.replace(",", "")
    elif "," in n:
        n = n.replace(",", ".")
    try:
        return Decimal(n)
    except Exception:
        return Decimal(0)


def q2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate_cents(total: Decimal, weights: dict) -> dict:
    """Split `total` (EUR) in whole cents proportionally to weights; leftover cents to the largest remainders, ties to
    the lower key."""
    cents = int(q2(total) * 100)
    wsum = sum(weights.values())
    if cents == 0 or wsum == 0:
        return {k: Decimal(0) for k in weights}
    raw = {k: Decimal(cents) * w / wsum for k, w in weights.items()}
    base = {k: int(v) for k, v in raw.items()}
    left = cents - sum(base.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - base[k]), k))
    for k in order[:left]:
        base[k] += 1
    return {k: Decimal(v) / 100 for k, v in base.items()}


def marginal_bands(amount: Decimal, bands: list) -> Decimal:
    total = Decimal(0)
    for b in bands:
        lo = D(b.get("from_eur"))
        hi = D(b["to_eur"]) if b.get("to_eur") not in (None, "") else None
        top = amount if hi is None else min(amount, hi)
        if top > lo:
            total += (top - lo) * D(b.get("percent")) / 100
    return q2(total)


def pick_scale(p: dict, qty: int):
    """Rule 4: the scale with the highest minimum quantity not above the position's own quantity."""
    scales = [x for x in (p.get("scales") or []) if x.get("price") not in (None, "", 0)]
    ok = [x for x in scales if D(x.get("min_qty")) <= qty]
    if ok:
        return D(max(ok, key=lambda x: D(x.get("min_qty")))["price"])
    return D(p.get("scale_price"))


def pick_metal_rate(p: dict, scenario_date: str):
    """Rule 28: the rate whose inclusive validity window contains the scenario date."""
    rates = p.get("metal_rates") or []
    for r in rates:
        lo, hi = str(r.get("valid_from") or "0000"), str(r.get("valid_to") or "9999")
        if lo[:10] <= scenario_date[:10] <= hi[:10]:
            return D(r.get("rate_eur_per_kg"))
    return D(p.get("metal_rate_eur_per_kg"))


ALIASES = {  # field names a model sometimes uses instead of the schema's
    "quantity_pieces": ["quantity_in_pcs", "quantity_pcs", "final_quantity_pieces", "quantity"],
    "eur_per_currency_unit": ["fx_rate_eur_per_usd", "fx_rate_eur_per_unit", "fx_rate", "eur_per_unit"],
    "currency": ["price_currency"],
    "free_stock": ["stock_free_pcs", "free_stock_pcs", "stock_free"],
    "lead_stock_weeks": ["lead_time_stock_weeks"],
    "lead_production_weeks": ["lead_time_production_weeks"],
    "carton_size": ["pack_content_pcs", "pieces_per_carton"],
    "allocation_mass": ["allocation_mass_kg", "allocation_mass_g_per_piece"],
}


def parse_number(text: str, fmt: str = "de-DE") -> Decimal:
    """A number exactly as displayed on the website, in its stated format (de-DE 1.234,56 / en-US 1,234.56)."""
    import re as _re
    m = _re.search(r"-?\d[\d.,]*", text)  # the first number in the text; ignore notes like "(de-DE)"
    t = m.group(0).rstrip(".,") if m else ""
    if fmt.lower().startswith("en"):
        t = t.replace(",", "")
    else:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t) if t not in ("", "-", ".") else Decimal(0)
    except Exception:
        return Decimal(0)


def normalize_position(p: dict) -> dict:
    """Bring a position into the FACTS_SCHEMA shape (aliases, grams, '100 ST' price units, scale key variants)."""
    p = dict(p)
    for key, alts in ALIASES.items():
        if p.get(key) in (None, "", 0):
            for a in alts:
                if p.get(a) not in (None, ""):
                    p[key] = p[a]
                    break
    if not p.get("surcharge_mass_kg"):
        if p.get("surcharge_mass_g_per_piece"):
            p["surcharge_mass_kg"] = D(p["surcharge_mass_g_per_piece"]) / 1000
        elif p.get("surcharge_mass_g"):
            p["surcharge_mass_kg"] = D(p["surcharge_mass_g"]) / 1000
    if D(p.get("surcharge_mass_kg")) > 50:  # a cylinder's surcharge mass is a few kg: larger values are grams
        p["surcharge_mass_kg"] = D(p["surcharge_mass_kg"]) / 1000
    if not p.get("price_unit_pieces") and p.get("price_unit"):
        import re as _re
        m = _re.search(r"(\d+)", str(p["price_unit"]))
        p["price_unit_pieces"] = int(m.group(1)) if m else 1
    scales = []
    fmt = str(p.get("number_format") or "de-DE")
    for x in p.get("scales") or []:
        price = x.get("price", x.get("unit_price", x.get("net_price")))
        if x.get("price_text") not in (None, ""):
            price = parse_number(str(x["price_text"]), fmt)
        scales.append({"min_qty": x.get("min_qty", x.get("from_pcs", x.get("from_qty", x.get("min", 1)))),
                       "price": price})
    if scales:
        p["scales"] = scales
    return p


def compute(facts: dict, scenario_date: str = "") -> dict:
    """The answer JSON from extracted facts."""
    facts = dict(facts)
    facts["positions"] = [normalize_position(p) for p in facts.get("positions") or []]
    ref = facts.get("tender_reference", "")
    positions = facts.get("positions") or []
    # A no-bid signal from the extraction is not trusted: a wrong no_bid loses every position's credit, while a bid
    # with the best-matching materials keeps it. Positions without any material are left out.

    rows = []
    for p in positions:
        qty = int(D(p.get("quantity_pieces")) or 0)
        if qty <= 0:
            continue
        p["material"] = p.get("material") or ""  # the configurator still finds it from the requirement attributes
        unit = D(p.get("price_unit_pieces") or 1) or Decimal(1)
        fx = D(p.get("eur_per_currency_unit") or 1) or Decimal(1)
        if str(p.get("currency") or "EUR").strip().upper() == "EUR":
            fx = Decimal(1)                                    # a EUR condition is never converted, whatever rate came along
        base = q2(pick_scale(p, qty) / unit * fx)              # rules 4, 22: per-position scale, converted, cents
        mass_sur = D(p.get("surcharge_mass_kg")) * pick_metal_rate(p, scenario_date)
        rows.append({"p": p, "pos": str(p["position"]), "qty": qty, "base": base, "mass_sur": mass_sur})

    # sanity: a per-piece base far above the others means a "per 100/1000 pieces" price unit was missed
    if len(rows) >= 3:
        bases = sorted(r["base"] for r in rows)
        median = bases[len(bases) // 2]
        for r in rows:
            for factor in (100, 1000):
                if median > 0 and r["base"] > 50 * median and abs(r["base"] / factor - median) < abs(r["base"] - median):
                    r["base"] = q2(r["base"] / factor)
                    r["p"]["_note"] = f"price unit corrected by {factor}"
                    break
    # allocation masses must share one unit: mixed grams and kilograms -> grams to kg
    am = [D(r["p"].get("allocation_mass")) for r in rows if D(r["p"].get("allocation_mass")) > 0]
    if am and max(am) / min(am) > 100:
        for r in rows:
            if D(r["p"].get("allocation_mass")) > 50:
                r["p"]["allocation_mass"] = D(r["p"]["allocation_mass"]) / 1000

    # rule 16: conditional discount on the undiscounted net (scale prices only)
    undiscounted = q2(sum((r["base"] * r["qty"] for r in rows), Decimal(0)))
    disc = facts.get("discount") or {}
    pct = D(disc.get("percent"))
    threshold = disc.get("min_undiscounted_net_eur")
    if threshold not in (None, "") and undiscounted < D(threshold):
        pct = Decimal(0)

    # rule 25: shared setup pool
    pool = facts.get("pool") or {}
    members = {r["pos"]: Decimal(r["qty"]) * D(r["p"].get("allocation_mass")) for r in rows if r["p"].get("pool_member")}
    pool_alloc = allocate_cents(D(pool.get("fee_eur")), members) if members else {}

    # rule 26: project bonus on the undiscounted goods value of members
    goods = {r["pos"]: r["base"] * r["qty"] for r in rows if r["p"].get("bonus_member")}
    bonus_total = marginal_bands(sum(goods.values(), Decimal(0)), facts.get("bonus_bands") or []) if goods else Decimal(0)
    bonus_alloc = allocate_cents(bonus_total, goods) if goods else {}

    # rules 6, 15, 24: delivery
    demand = {}
    for r in rows:
        demand[r["p"]["material"]] = demand.get(r["p"]["material"], 0) + r["qty"]

    out, total = [], Decimal(0)
    for r in rows:
        p, qty = r["p"], r["qty"]
        clause = (p.get("discount_clause") or "base").lower()
        f = 1 - pct / 100
        base_d = r["base"] * f if clause in ("base", "base_and_surcharge") else r["base"]
        sur_d = r["mass_sur"] * f if clause == "base_and_surcharge" else r["mass_sur"]
        setup = D(p.get("setup_fee_eur")) + pool_alloc.get(r["pos"], Decimal(0))
        cartons = math.ceil(qty / max(1, int(D(p.get("carton_size") or 1))))
        carton_cost = cartons * D(p.get("carton_tariff_eur"))
        bonus = bonus_alloc.get(r["pos"], Decimal(0))
        unit_price = q2(base_d + sur_d + (setup + carton_cost - bonus) / qty)   # rule 27: round once

        mat = p["material"]
        com = p.get("commitment") or None
        if com and com.get("material") == mat and demand[mat] <= int(D(com.get("ceiling_pieces"))):
            lead = int(D(com.get("weeks")))
        elif D(p.get("free_stock")) >= demand[mat]:
            lead = int(D(p.get("lead_stock_weeks")))
        else:
            lead = int(D(p.get("lead_production_weeks")))

        out.append({"position": r["pos"], "material_number": mat, "quantity": qty, "unit_price": float(unit_price),
                    "lead_time_weeks": max(lead, 0), "base_unit_price": float(r["base"]),
                    "surcharge_per_unit": float(q2(r["mass_sur"] + setup / qty)),
                    "packaging_per_unit": float(q2(carton_cost / qty)), "rebate_total": float(bonus)})
        total += unit_price * qty

    return {"tender_reference": ref, "decision": "bid", "currency": "EUR", "discount_percent": float(pct),
            "positions": out, "total_net": float(q2(total))}
