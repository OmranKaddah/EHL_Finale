"""Runtime normalization contract. No website-specific values or selectors."""

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class Unresolved(ValueError):
    """Evidence is missing, contradictory, or cannot be safely normalized."""


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise Unresolved('numbers must be integers or decimal strings, never floats')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise Unresolved('invalid decimal') from exc
    if not result.is_finite() or result < 0:
        raise Unresolved('numbers must be finite and nonnegative')
    return result


def integer(value, positive=False):
    number = decimal(value)
    if number != number.to_integral_value() or (positive and number <= 0):
        raise Unresolved('expected a positive integer' if positive else 'expected an integer')
    return int(number)


def date(value):
    if not isinstance(value, str):
        raise Unresolved('date is missing')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise Unresolved('dates must be normalized to ISO 8601') from exc
    # Scenario date is inclusive through the end of that date; record dates
    # without times are compared as dates by eligible(), rather than guessed TZs.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_json(raw):
    start = raw.find('{')
    if start < 0:
        raise Unresolved('model returned no JSON object')
    try:
        value, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise Unresolved('model returned malformed JSON') from exc
    if not isinstance(value, dict):
        raise Unresolved('expected a JSON object')
    return value


KINDS = {'tender', 'spec', 'qa', 'material', 'condition', 'approval', 'tech',
         'fx', 'index', 'tariff', 'delivery', 'pool', 'bonus', 'clause'}
MAIL_AUTHORITY = {
    'tech': ('technik', 'Technikfreigabe'), 'fx': ('finanzen', 'Devisenfixing'),
    'index': ('kalkulation', 'Preisindizes'), 'tariff': ('logistik', 'Verpackungstarife'),
    'delivery': ('logistik', 'Terminfreigabe'), 'pool': ('kalkulation', 'Rüstpools'),
    'bonus': ('finanzen', 'Projektbonus'), 'clause': ('kalkulation', 'Konditionsregeln'),
}

RECORD_CONTRACT = """
Return {scenario: {reference, scenario_date, director_email, bidder_domain,
evidence_ids}, records: [...], coverage: [{key,evidence_ids}], gaps: [text]}.
All scenario facts come from the runtime brief or collected exact evidence.
Evidence IDs are supplied; 'brief' cites the runtime brief. Never invent IDs.
Every record: {id, kind, key, date, reference, sender, subject, evidence_ids, data}.
Dates ISO 8601 (preserve known times/timezones). Non-mail tender/spec/material/condition
records may use date:null if the current source has no record timestamp; never
invent scenario dates as source dates. Numbers decimal strings, no floats.
key identifies the record's business key, not its source document/version.
reference must be the EXACT reference shown on the source, never repaired to the
target. Preserve unrelated/future/inactive/superseded records for resolution.
Sender/subject required on mail records; use null for non-mail sources.
Each record's evidence_ids must support ALL its metadata and data. If a field
is absent, leave the record incomplete and state the gap. Explicit known zero
is '0'; absent is never zero. Null means the source proves not applicable.
Normalized attributes: {bore,stroke,pressure,mounting,certification}; dimensions
as decimal strings in mm/bar; normalize equivalent units from source explicitly.
Mounting/certification canonical exact strings; keep distinct certifications distinct.

Non-mail spec/material/condition sources without a tender reference may use
reference:null; all other records require the exact source reference.
Tech keys normalize to revision + ":" + requirement identifier.
Record data contracts:
tender: {positions:[{id,requirement,quantity,unit:'piece'|'set'}]}
spec: {revision,current:boolean,requirements:[{id,attributes,pieces_per_set,
 stroke_kind:'nominal'|'usable',catalog_group}]}
qa: {number,withdraws:[answer_numbers],quantity_changes:{position_id:quantity},
 assignments:{position_id:{clause_key,tariff_key,commitment_key,pool_key,bonus_key}},
 amendments:[{revision,requirement,changes:{attribute:new_value}}]}
material: {number,group,active:boolean,attributes,stock,stock_weeks,production_weeks,
 carton_size,surcharge_mass,allocation_mass}
condition: {material,valid_from,valid_to,currency,price_unit,
 scales:[{minimum,price}],setup_fee_eur,index_key,fx_key} (index_key null if no surcharge)
approval: {percent,min_goods_eur} (null threshold means unconditional)
tech: {revision,requirement,reserve_per_end}
fx: {eur_per_unit}
index: {windows:[{from,to,eur_per_kg}]}
tariff: {eur_per_carton}
delivery: {material,max_quantity,weeks}
pool: {fee_eur,allocation_rule:'largest_remainder',members:[position_ids]}
bonus: {members:[position_ids],bands:[{up_to,percent}]} ascending marginal upper
 limits; final up_to null means unlimited. No unsupported allocation-rule guessing.
clause: {discount_components:'base'|'base_and_surcharge'|'none'}
If one mail defines several keys, create separate records with the SAME source
record date/authority and each exact key. Same for several condition/material rows.

coverage keys are proof of a completed scoped search/read, NOT mere confidence:
scenario, tender, spec, qa, approval; materials:<catalog_group> for the ENTIRE
model-selected result set (including all pages and active candidate attributes).
For latest selection of mail keys also require <kind>:<key> covering the relevant
inbox AND archive results for the exact reference and subject. Read all applicable
newer candidates. A key is covered only if governing record choice is established.
All global keys scenario/tender/spec/qa/approval/bonus are required. bonus coverage
means the relevant finance project-bonus inbox/archive search is complete, including
absence when no applicable bonus exists. Bonus membership comes from the finance
mail; do not invent Q&A bonus assignments. approval coverage may establish no approval.
Only add coverage with exact evidence IDs showing relevant source/search results.
Return remaining gaps even if other fields are known. Do not compute prices or
select one convenient record over conflicting evidence; deterministic code does
that. Do not browse or request a crawler; you only normalize already selected
source quotes. Cross-site gaps may be investigated at any runtime-provided site.
"""


def validate_bundle(bundle, evidence):
    known = {item.evidence_id for item in evidence} | {'brief'}
    if not isinstance(bundle.get('records'), list) or not isinstance(bundle.get('coverage'), list):
        raise Unresolved('records and coverage lists are required')
    scenario = bundle.get('scenario')
    if not isinstance(scenario, dict):
        raise Unresolved('scenario is missing')
    def citations(item):
        refs = item.get('evidence_ids')
        if not isinstance(refs, list) or not refs or any(ref not in known for ref in refs):
            raise Unresolved('source citations are missing or unknown')
    citations(scenario)
    seen = set()
    for record in bundle['records']:
        if not isinstance(record, dict) or record.get('kind') not in KINDS:
            raise Unresolved('unknown record kind')
        for key in ('id', 'key'):
            if not isinstance(record.get(key), str) or not record[key]:
                raise Unresolved(f'record {key} must be nonempty')
        if not isinstance(record.get('reference'), str) and not (record['kind'] in {'spec', 'material', 'condition'} and record.get('reference') is None):
            raise Unresolved('exact source reference is required')
        if record['id'] in seen:
            raise Unresolved('duplicate normalized record id')
        seen.add(record['id'])
        if record.get('date') is None:
            if record['kind'] not in {'tender', 'spec', 'material', 'condition'}:
                raise Unresolved('dated source record required')
        else:
            date(record['date'])
        if not isinstance(record.get('data'), dict):
            raise Unresolved('record data is missing')
        citations(record)
        if record["evidence_ids"] == ["brief"]:
            raise Unresolved("business records require observed website/document evidence")
    for item in bundle['coverage']:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str):
            raise Unresolved('invalid coverage key')
        citations(item)
        if item["key"] != "scenario" and not any(ref != "brief" for ref in item["evidence_ids"]):
            raise Unresolved("source coverage cannot be established by the brief alone")
    if not isinstance(bundle.get('gaps', []), list):
        raise Unresolved('gaps must be a list')
    return bundle
