"""Runtime RFQ workflow: investigate gaps, resolve, calculate, validate, submit."""

import asyncio
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright
from . import browser, planner, run_contract, mail, missions
from .documents import InvestigationSession
from .evidence import EvidenceLedger
from .investigation import InvestigationState
from .records import Unresolved
from .submission import submit_on_site
from .eligibility import omitted_bid


def write_artifact(name, value):
    path = Path('artifacts', name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def arguments(argv=None):
    parser = argparse.ArgumentParser(description='Investigate RFQ websites with concise action logs.')
    parser.add_argument('--list-sites', action='store_true', help='List runtime site IDs and exit')
    parser.add_argument('--site', help='Investigate only this runtime site; no bid submission')
    parser.add_argument('--steps', type=int, default=120, help='Action limit for --site (default: 120)')
    parser.add_argument('--mission', choices=['tan', 'baseline', 'discount'], help='Explicit non-submitting mailbox mission')
    parser.add_argument('--goal', help='Explicit investigation objective; bypass dispatch')
    parser.add_argument('--after', type=int, help='TAN request baseline captured before requesting a new code')
    parser.add_argument('--timeout', type=int, default=180, help='Explicit mission time budget in seconds')
    parser.add_argument('--parallel', action='store_true', help='Run full-workflow investigators concurrently; default is sequential')
    parser.add_argument('--eligibility', action='store_true', help='Attempt a signed all-omitted bid permitted by the runtime brief; submits a bid')
    options = parser.parse_args(argv)
    if options.steps < 1: parser.error('--steps must be positive')
    if options.site and options.parallel: parser.error('--parallel cannot be combined with --site')
    if options.eligibility and (options.site or options.parallel or options.list_sites):
        parser.error('--eligibility is a separate submitting workflow')
    if (options.mission or options.goal) and not options.site: parser.error('--mission and --goal require --site')
    if options.mission and options.goal: parser.error('Choose --mission or --goal')
    if options.goal is not None and not options.goal.strip(): parser.error('--goal cannot be empty')
    if options.after is not None and (options.mission != 'tan' or options.after < 0): parser.error('--after requires --mission tan and a nonnegative baseline')
    if options.timeout < 1: parser.error('--timeout must be positive')
    return options


async def run_batch(task, sessions, assignments, ledger, parallel=False):
    async def investigate(index, assignment):
        print(f"Investigating {assignment['site_id']}", flush=True)
        try:
            return await planner.run_planner(task, sessions[index].page, assignment, ledger,
                                             max_steps=24, session=sessions[index])
        except Exception as exc:
            return {'site_id': assignment['site_id'], 'status': 'failed', 'reason': type(exc).__name__}
    if parallel:
        return await asyncio.gather(*(investigate(i, a) for i, a in enumerate(assignments)))
    results = []
    for i, assignment in enumerate(assignments):
        results.append(await investigate(i, assignment))
    return results


async def investigate_site(task, site, steps, goal=None):
    """An isolated debug run stops at source evidence; it never submits a bid."""
    task = dict(task, access=[{'siteId': site['site_id'], 'url': site['url'], 'credentials': site['_credentials']}], investigation_reserve=30, single_site_debug=True)
    ledger = EvidenceLedger()
    prefix = 'sites/' + re.sub(r'[^a-zA-Z0-9_-]', '_', site['site_id'])
    phase = 'dispatch'; result = {'status': 'failed'}; failure = None
    try:
        print(f"Investigating only {site['site_id']} (up to {steps} actions)", flush=True)
        assignment = ({'site_id': site['site_id'], 'objective': goal} if goal else
                      (await planner.plan_assignments(task, [site], 1))[0])
        assignment['worker_id'] = site['site_id']
        assignment['review_completion'] = True
        print(f"[{site['site_id']}] objective: {planner._safe_log_excerpt(assignment.get('objective', ''), [site], 200)}", flush=True)
        provider, model_name, _, _ = planner.model.configuration()
        print(f"[{site['site_id']}] model: {provider}/{model_name}", flush=True)
        phase = 'browser attachment'
        async with async_playwright() as pw:
            instance, page, owns = await browser.connect(pw, 0)
            try:
                phase = 'investigation'
                session = planner.InvestigationSession(page, [site])
                try:
                    result = await planner.run_planner(task, page, assignment, ledger, max_steps=steps, session=session)
                except Exception as exc:
                    result = {'site_id': site['site_id'], 'objective': assignment['objective'],
                              'status': 'failed', 'history': session.history,
                              'stop_reason': planner._safe_log_excerpt(str(exc), [site], 700)}
                    raise
            finally:
                if owns: await instance.close()
    except Exception as exc:
        failure = {'phase': phase, 'error_type': type(exc).__name__,
                   'detail': planner._safe_log_excerpt(str(exc), [site], 700)}
        print(f"[{site['site_id']}] failed during {phase}: {type(exc).__name__}", flush=True)
    finally:
        evidence = [item.to_dict() for item in await ledger.snapshot()]
        write_artifact(prefix + '/evidence.json', evidence)
        write_artifact(prefix + '/workflow.json', {'investigations': [result], 'failure': failure, 'submission': {'status': 'not_attempted', 'reason': 'single-site investigation'}})
    print(f"[{site['site_id']}] {result['status']}; evidence={len(evidence)}; artifacts/{prefix}", flush=True)
    return 0 if evidence and result['status'] != 'failed' and failure is None else 1


async def investigate_mission(task, site, options):
    """No submission calls; TAN and approval completion contracts are independent."""
    access = {'siteId': site['site_id'], 'url': site['url'], 'credentials': site['_credentials']}
    prefix = 'sites/' + re.sub(r'[^a-zA-Z0-9_-]', '_', site['site_id']) + '/' + options.mission
    result = {'status': 'failed'}
    print(f"[{site['site_id']}] mission: {options.mission}; steps={options.steps}; timeout={options.timeout}s", flush=True)
    provider, name, _, _ = planner.model.configuration()
    print(f"[{site['site_id']}] model: {provider}/{name}; reasoning={os.environ.get('OPENAI_REASONING_EFFORT', 'low')}", flush=True)
    if options.mission == 'tan' and options.after is None:
        print('No baseline supplied: this checks the highest observed request, not freshness after a new request.', flush=True)
    try:
        async with async_playwright() as pw:
            instance, page, owns = await browser.connect(pw, 0)
            try:
                if options.mission == 'discount':
                    result = await missions.get_discount(page, access, task, timeout_s=options.timeout, max_steps=options.steps)
                else:
                    result = await mail.debug_tan(page, access, after=options.after,
                        baseline=options.mission == 'baseline', timeout_s=options.timeout, max_steps=options.steps)
                # Keep the human-visible source for local comparison, with fields masked.
                shot = await planner._visual_challenge_screenshot(page)
                if shot:
                    import base64
                    path = Path('artifacts', prefix, 'screen.jpg')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(base64.b64decode(shot.split(',', 1)[1]))
            finally:
                if owns: await instance.close()
    except Exception as exc:
        result = {'status': 'failed', 'error_type': type(exc).__name__}
    write_artifact(prefix + '/result.json', result)
    write_artifact(prefix + '/workflow.json', {'mission': options.mission, 'status': result['status'],
                                            'submission': {'status': 'not_attempted'}})
    if options.mission == 'baseline' and result['status'] == 'completed':
        print(f"Baseline request number: {result['result']}", flush=True)
    print(f"[{site['site_id']}] {result['status']}; artifacts/{prefix}", flush=True)
    return 0 if result['status'] == 'completed' else 1


async def main(options=None) -> int:
    options = options or arguments([])
    task, token = run_contract.load_run()
    # One workflow-wide deadline, shared across all rounds and submission. Scouting
    # has no platform deadline; use the scored-run budget rather than run forever.
    task = dict(task)
    task['expires_at'] = min(task.get('expires_at') or float('inf'), (time.time() + 20 * 60) * 1000)
    sites = planner.normalize_sites(task.get('access'))
    if options.list_sites:
        for site in sites: print(site['site_id'])
        return 0
    if options.eligibility:
        return await eligibility_rehearsal(task, sites, options.steps)
    if options.site:
        site = next((s for s in sites if s['site_id'] == options.site), None)
        if site is None:
            print('Unknown site ID. Available: ' + ', '.join(s['site_id'] for s in sites), file=sys.stderr)
            return 2
        if options.mission:
            return await investigate_mission(task, site, options)
        return await investigate_site(task, site, options.steps, options.goal)
    count = min(len(sites), browser.available_count(), 4)
    if count < 1: raise RuntimeError('No runtime investigation sites/browsers')
    ledger = EvidenceLedger(); state = InvestigationState(); results = []
    submission = {'status': 'not_attempted', 'reason': 'no validated answer'}
    connections = []
    phase = "dispatch"
    failure = None
    try:
        print(f"Dispatching {count} investigators ({'parallel' if options.parallel else 'sequential'})", flush=True)
        # Dispatch already reads the full brief. Do not put an extra checklist
        # inference before the first useful browser investigation.
        assignments = await planner.plan_assignments(task, sites, count)
        state.checklist = list(dict.fromkeys(state.checklist + [item["objective"] for item in assignments]))
        state.gaps = state.checklist.copy()
        phase = "browser attachment"
        async with async_playwright() as playwright:
            try:
                for index in range(count):
                    connections.append(await browser.connect(playwright, index))
                sessions = [InvestigationSession(page, sites) for _, page, _ in connections]
                # Short rounds expose missing dependencies to all workers while
                # retaining their browser state; every follow-up is model assigned.
                for round_number in range(1, 9):
                    if run_contract.seconds_left(task) < 540: break
                    phase = f'investigation round {round_number}'
                    print(f'Investigation round {round_number}: {len(assignments)} focused workers', flush=True)
                    task['investigation_state'] = state.snapshot()
                    task['investigation_reserve'] = 480
                    for index, assignment in enumerate(assignments):
                        assignment['worker_id'] = f'worker-{index}'
                    batch = await run_batch(task, sessions, assignments, ledger, options.parallel)
                    for result in batch:
                        summary = result if isinstance(result, dict) else {'status': 'failed', 'reason': type(result).__name__}
                        results.append(summary)
                        print(f'[{summary.get("site_id", "investigator")}] {summary.get("status")}; evidence={summary.get("evidence_count", 0)}', flush=True)
                    phase = "evidence normalization and audit"
                    print(f"Reviewing evidence; remaining time={run_contract.seconds_left(task):.0f}s", flush=True)
                    if await ledger.snapshot():
                        await state.review(task, ledger)
                    else:
                        state.gaps = list(dict.fromkeys(state.gaps + ['No source evidence collected; recover browser access before normalization']))
                    write_artifact('evidence.json', [item.to_dict() for item in await ledger.snapshot()])
                    write_artifact('investigation.json', state.snapshot())
                    if state.bundle: write_artifact('normalized-records.json', state.bundle)
                    if state.answer and not state.calculation['omitted']: break
                    if run_contract.seconds_left(task) < 540: break
                    phase = "follow-up dispatch"
                    try:
                        assignments = await state.assignments(task, sites, count)
                    except Unresolved as exc:
                        print(f'Follow-up dispatch rejected ({type(exc).__name__}); retaining prior model-assigned objectives', flush=True)
                if state.answer is None and await ledger.snapshot() and run_contract.seconds_left(task) > 310:
                    phase = "evidence normalization and audit"
                    await state.review(task, ledger)
                if state.answer:
                    write_artifact('answer.json', state.answer)
                    write_artifact('calculation.json', state.calculation)
                    phase = "submission"
                    target = task.get('submission', {})
                    if target.get('kind') == 'site':
                        submission = await submit_on_site(task, state.answer, state.calculation['omitted'], sessions[0].page, ledger)
                    elif target.get('kind') == 'api':
                        status, body = await asyncio.to_thread(run_contract.submit_answer, task, token, state.answer)
                        submission = {'status': 'submitted' if status == 202 else 'unconfirmed', 'http_status': status}
                    else:
                        raise Unresolved('unsupported runtime submission kind')
            finally:
                for instance, _, owns in connections:
                    if owns: await instance.close()
    except Exception as exc:
        # No raw transport messages, tokens, form values or TANs in diagnostics.
        failure = {"phase": phase, "error_type": type(exc).__name__}
        print(f"Workflow stopped during {phase} ({type(exc).__name__})", flush=True)
        if isinstance(exc, TimeoutError):
            print("Model response or workflow deadline timed out.", flush=True)
        submission['reason'] = f"{phase}: {type(exc).__name__}"
    finally:
        write_artifact('evidence.json', [item.to_dict() for item in await ledger.snapshot()])
        write_artifact('workflow.json', {'investigations': results, 'state': state.snapshot(), 'submission': submission, 'failure': failure})
    print(f'Workflow outcome: {submission["status"]}; source records={len(await ledger.snapshot())}', flush=True)
    return 0 if submission['status'] == 'submitted' else 1


async def eligibility_rehearsal(task, sites, max_steps):
    """Opt-in minimum bid; keeps normal full-quality and site debug flows intact."""
    ledger = EvidenceLedger()
    result = {'status': 'not_attempted'}
    evidence_result = None
    proposal_diagnostics = []
    try:
        target = task.get('submission', {})
        site = planner._site_for_url(target.get('url', ''), sites)
        if target.get('kind') != 'site' or site is None:
            raise Unresolved('eligibility rehearsal requires a runtime site submission target')
        print('Eligibility rehearsal: discover all position identifiers, omit all, then sign once', flush=True)
        provider, model_name, _, _ = planner.model.configuration()
        print(f'[eligibility] model: {provider}/{model_name}; reasoning={os.environ.get("OPENAI_REASONING_EFFORT", "low")}', flush=True)
        async with async_playwright() as pw:
            instance, page, owns = await browser.connect(pw, 0)
            try:
                focused_task = dict(task, investigation_reserve=420)
                assignment = {'site_id': site['site_id'], 'worker_id': 'eligibility',
                              'review_completion': True,
                              'objective': 'Find the tender matching the runtime brief on the submission website. '
                              'Read and quote its COMPLETE position identifier list from an original document. '
                              'This mission is ONLY the position list: the runtime brief supplies the reference, '
                              'and the submission worker will verify it on the live review. Do not try to '
                              'add a reference from a URL to a document quote. Do not require the reference '
                              'and positions in one quote. No pricing, amendments, ERP, discount investigation '
                              'or signing yet. Finish immediately once the complete identifier list is quoted.'}
                evidence_result = await planner.run_planner(focused_task, page, assignment, ledger,
                                                            max_steps=min(40, max_steps))
                print('[eligibility] validating omission permission and complete position coverage', flush=True)
                answer, omitted = await omitted_bid(task, ledger, diagnostics=proposal_diagnostics)
                write_artifact('eligibility/answer.json', {'answer': answer, 'omitted': omitted})
                print(f'[eligibility] minimum bid validated; {len(omitted)} positions to omit', flush=True)
                result = {'status': 'unconfirmed', 'reason': 'submission started; receipt not verified'}
                result = await submit_on_site(task, answer, omitted, page, ledger, max_steps=max_steps)
            finally:
                if owns: await instance.close()
    except Exception as exc:
        result = {'status': 'unconfirmed' if result.get('status') != 'not_attempted' else 'not_attempted',
                  'error_type': type(exc).__name__,
                  'reason': planner._safe_log_excerpt(str(exc), sites, 700)}
    write_artifact('eligibility/evidence.json', [item.to_dict() for item in await ledger.snapshot()])
    write_artifact('eligibility/proposals.json', proposal_diagnostics)
    write_artifact('eligibility/workflow.json', {'investigation': evidence_result, 'submission': result})
    print(f'Eligibility rehearsal: {result["status"]}; artifacts/eligibility', flush=True)
    return 0 if result['status'] == 'submitted' else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main(arguments())))
