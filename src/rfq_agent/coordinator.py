"""Deadline-bounded run: parallel model-directed research, then one submission owner."""

import asyncio
import json
from decimal import Decimal

from . import model, planner
from .documents import InvestigationSession
from .evidence import EvidenceLedger
from .submission import Phase, SubmissionController, SubmissionError, origin
from .submit_agent import SubmissionAgent, read_tan

DRAFT_ATTEMPTS = 3

CHECKLIST_PROMPT = """You read the run brief of one RFQ and list its cross-position rules: every rule
that makes one position's price, discount, cost share, bonus, stock or availability, or lead time
depend on other positions or on the whole order. Return one JSON object only:
{"rules":[{"name":"short_name","quote":"exact text copied from the brief"}]}
Each quote must be copied exactly from the brief. Return {"rules":[]} only when the brief has no
such rule. Do not add rules the brief does not state."""

DRAFT_PROMPT = """You prepare the bid draft for one RFQ from the run brief, the run's answer schema and
the numbered evidence records gathered on the websites. Return one JSON object only:
{"reference": exact tender reference as written in the brief or evidence (never reformatted),
 "answer": object that satisfies answer_schema, containing only values you can source,
 "sources": {"<answer path such as positions.0.unit_price>": one of
     {"kind":"evidence","evidence":[ids]}  the value appears in those quotes,
     {"kind":"rule","quote":"exact text of the run brief that states this number"},
     {"kind":"calculation","expression":"a * b - c","inputs":{"a":{"path":"<answer path>"},
        "b":{"value":"12.5","evidence":[id]},"c":{"value":"3","quote":"exact brief text stating 3"}},
        "round":{"places":2,"mode":"HALF_UP"}}  optional rounding only as the brief prescribes,
     {"kind":"interpretation","evidence":[ids],"reason":"..."}  text or yes/no values only,
     {"kind":"empty_total"}  only for a zero total when no position is priced},
 "identity": {"<name>": {"value":"exact text","evidence":[id]}} registered bidder details the form needs,
 "priced": [{"id":"<position id>","path":"<answer path of that position object>"}],
 "omitted": [{"position":"<position id>","reason":"what is unresolved"}],
 "closure": {"<priced position id>": {"<checklist rule name>": {"status":"resolved" or "not_applicable",
     "evidence":[ids]}}},
 "no_bid": false}
`inventory` lists the tender positions that were observed; each must be priced or omitted and no
other position may appear. `checklist` lists the cross-position rules; every priced position needs
a closure entry with evidence for every one of them. Every value in answer needs a source; a number
is never a guess, a default or a placeholder, and a zero needs evidence or a brief rule that states
it. A calculation uses + - * / min max over sourced inputs; any number other than 0, 1 and 100 must
be an input with its own evidence, and calculations must not refer to each other in a circle.
Price a position only when all of its inputs and every checklist rule are resolved for it;
otherwise list it under omitted and keep it out of answer. Totals must follow from the priced
positions by calculation. Leave optional fields out when they are not established. Do not put every
position under omitted unless capabilities.all_positions_omitted was observed as supported.
Set no_bid true only with "no_bid_basis": {"searches": {"<position id>": [ids of evidence of kind
catalogue_search for that position]}} covering every inventory position; unfinished research is
never a reason for no_bid. Correct every item in previous_errors: fix the source, or omit the
affected position."""


async def derive_checklist(task: dict, clock) -> list | None:
    """Establish the cross-position rules from the brief, apart from any draft. None: not established."""
    brief = str(task.get("brief", ""))
    errors = ""
    for _ in range(2):
        if clock.left() <= 0:
            return None
        try:
            raw = await model.complete_with_retry(
                [{"role": "system", "content": CHECKLIST_PROMPT},
                 {"role": "user", "content": json.dumps({"task_brief": brief, "previous_errors": errors}, ensure_ascii=False)}],
                timeout=max(1, min(150, clock.left())), budget=clock.left)
            rules = _load(raw).get("rules")
            if not isinstance(rules, list):
                raise ValueError("rules must be a list")
            names = [rule.get("name") if isinstance(rule, dict) else None for rule in rules]
            if not all(isinstance(name, str) and name.strip() for name in names) or len(set(names)) != len(names):
                raise ValueError("each rule needs a distinct name")
            if not all(isinstance(rule.get("quote"), str) and rule["quote"].strip() and rule["quote"] in brief for rule in rules):
                raise ValueError("each rule quote must be copied exactly from the brief")
            return [{"name": rule["name"], "quote": rule["quote"]} for rule in rules]
        except Exception as exc:
            errors = f"{type(exc).__name__}: {str(exc)[:200]}"
    return None


def _load(raw: str) -> dict:
    start = raw.find("{")
    if start < 0:
        raise ValueError("draft response contained no JSON object")
    candidate, _ = json.JSONDecoder(parse_float=Decimal).raw_decode(raw[start:])
    if not isinstance(candidate, dict):
        raise ValueError("draft response was not a JSON object")
    return candidate


async def prepare_draft(task: dict, ledger: EvidenceLedger, controller: SubmissionController, clock,
                        feedback: str) -> str:
    """Ask the model for a draft until it validates; returns feedback for the submission owner."""
    brief, schema = str(task.get("brief", "")), task.get("answer_schema")
    if controller.checklist is None:
        controller.checklist = await derive_checklist(task, clock)
    evidence = await ledger.snapshot()
    errors = feedback
    for _ in range(DRAFT_ATTEMPTS):
        if clock.left() <= 0:
            break
        payload = {
            "task_brief": brief,
            "answer_schema": schema,
            "evidence": [{"id": index, "claim": item.claim, "quote": item.quote, "site_id": item.site_id, "url": item.url,
                          "kind": item.kind, "subject": item.subject}
                         for index, item in enumerate(evidence)],
            "inventory": list(dict.fromkeys(item.subject for item in evidence if item.kind == "position" and item.subject)),
            "checklist": controller.checklist,
            "capabilities": controller.capabilities,
            "identified_reference": controller.reference,
            "previous_errors": errors,
        }
        try:
            raw = await model.complete_with_retry(
                [{"role": "system", "content": DRAFT_PROMPT},
                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                timeout=max(1, min(150, clock.left())), budget=clock.left)
        except Exception as exc:
            return f"draft not validated: model request failed ({type(exc).__name__})"
        try:
            candidate = _load(raw)
            if controller.phase == Phase.BOOT:
                controller.identify(candidate.get("reference"), brief, evidence)
            if controller.phase == Phase.IDENTIFY:
                for item in evidence:
                    try:
                        controller.confirm_on_portal(item.url, item.quote)
                        break
                    except SubmissionError:
                        continue
            if controller.phase == Phase.IDENTIFY:
                return ("tender reference identified, but the submission website has not shown it yet: "
                        "open that tender there, then prepare_draft")
            draft = controller.accept_draft(candidate, schema, brief, evidence)
            return (f"draft validated: {len(draft.priced)} priced, {len(draft.omitted)} explicitly omitted"
                    f"{', no_bid' if draft.no_bid else ''}")
        except ValueError as exc:
            errors = str(exc)[:1800]
    return "draft not validated: " + errors


def _blocked(reason: str) -> dict:
    return {"status": "blocked", "phase": Phase.BOOT.name, "receipt": None, "sign_attempts": 0, "reason": reason, "steps": 0}


def exit_code(result: dict) -> int:
    """Zero only for a receipt verified after signing; eligibility itself is the platform's verdict."""
    return 0 if result.get("status") == "accepted" and result.get("receipt") else 1


async def run(task: dict, connect, worker_count: int, clock, redactor) -> dict:
    """`connect(index)` returns the page of a provided browser; no browser is started here."""
    submission = task.get("submission") if isinstance(task.get("submission"), dict) else {}
    if submission.get("kind") != "site" or not isinstance(submission.get("url"), str):
        return _blocked("this runtime signs on the run's submission website; another submission kind is not supported")
    sites = planner.normalize_sites(task.get("access"))
    if not sites or worker_count < 1:
        return _blocked("the run provides no usable website or browser")
    ledger = EvidenceLedger()
    controller = SubmissionController(submission["url"], redactor=redactor)
    try:
        assignments = await clock.bounded(planner.plan_assignments(task, sites, worker_count), research=True)
    except Exception as exc:
        return _blocked(f"investigations could not be dispatched ({type(exc).__name__})")
    checklist = asyncio.create_task(derive_checklist(task, clock))
    pages = [await connect(index) for index in range(len(assignments))]
    print(f"Starting {len(pages)} model-directed investigations; research budget {int(clock.research_left())}s, "
          f"run budget {int(clock.left())}s", flush=True)
    workers = [asyncio.create_task(planner.run_planner(task, page, assignment, ledger, budget=clock.research_left))
               for page, assignment in zip(pages, assignments)]
    if clock.research_left() > 0:
        _, pending = await asyncio.wait(workers, timeout=clock.research_left())
    else:
        pending = set(workers)
    for worker in pending:
        worker.cancel()
    for assignment, outcome in zip(assignments, await asyncio.gather(*workers, return_exceptions=True)):
        if isinstance(outcome, dict):
            print(f"[{outcome['site_id']}] {outcome['status']} after {outcome['steps']} steps; "
                  f"evidence records={outcome['evidence_count']}; reason={outcome['stop_reason']}", flush=True)
        else:
            print(f"[{assignment['site_id']}] investigation stopped ({type(outcome).__name__})", flush=True)

    try:
        controller.checklist = await clock.bounded(checklist)
    except Exception:
        controller.checklist = None
    print("Dependency checklist: " + ("not established; no position can be priced" if controller.checklist is None
                                      else f"{len(controller.checklist)} cross-position rules"), flush=True)
    by_id = {site["site_id"]: site for site in sites}
    owner = next((index for index, assignment in enumerate(assignments)
                  if origin(by_id[assignment["site_id"]]["url"]) == origin(submission["url"])), 0)
    mail_sessions = [InvestigationSession(page, sites) for index, page in enumerate(pages) if index != owner]
    if not mail_sessions:
        # A single provided browser: the mail owner works in its own tab of that browser.
        mail_sessions = [InvestigationSession(await pages[owner].context.new_page(), sites)]
    agent = SubmissionAgent(
        task, InvestigationSession(pages[owner], sites), controller, ledger, clock, redactor,
        prepare=lambda feedback: prepare_draft(task, ledger, controller, clock, feedback),
        read_tan=lambda: read_tan(task, mail_sessions, controller, clock, redactor))
    print(f"Research closed with {len(await ledger.snapshot())} evidence records; submission budget {int(clock.left())}s", flush=True)
    return await agent.run()
