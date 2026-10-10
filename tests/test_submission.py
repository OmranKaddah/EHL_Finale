from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from atira_agent.contracts import Observation, PricingResult, RunContext, SubmissionState
from atira_agent.submit import Submission, validate_answer


def context():
    return RunContext(challenge_id="rfq", brief="fixture", access=[],
                      submission={"kind": "site", "url": "http://synthetic.test"}, answer_schema={})


def answer():
    return {"tender_reference": "SYN-R", "decision": "bid", "currency": "EUR", "discount_percent": 0,
            "positions": [{"position": "A", "material_number": "SYN-M", "quantity": 3,
                           "unit_price": Decimal("1.01"), "lead_time_weeks": 2}], "total_net": Decimal("3.03")}


def test_exact_decimal_serialization_and_total():
    assert b'1.01' in validate_answer(answer(), {})
    with pytest.raises(ValueError, match="Total"):
        validate_answer(answer() | {"total_net": Decimal("3.02")}, {})
    with pytest.raises(ValueError, match="Duplicate"):
        data = answer()
        data["positions"] *= 2
        validate_answer(data, {})


async def test_tan_replacement_invalidates_previous(telemetry):
    browser = MagicMock(act=AsyncMock(), latest_tan="old", tan_captured_at=1, observation_number=8)
    submission = Submission(context(), browser, telemetry)
    submission.prepare(PricingResult(answer=answer()))
    await submission.request_tan({"ref": "observed"})
    assert browser.latest_tan is None and browser.tan_captured_at is None
    assert browser.tan_request_observation == 8
    assert submission.state == SubmissionState.TAN_REQUESTED


async def test_uncertain_signing_stays_attempted(telemetry):
    import time
    browser = MagicMock(act=AsyncMock(side_effect=TimeoutError("uncertain click")),
                        latest_tan="synthetic", tan_captured_at=time.monotonic())
    submission = Submission(context(), browser, telemetry)
    submission.prepare(PricingResult(answer=answer()))
    submission.state = SubmissionState.TAN_REQUESTED
    with pytest.raises(TimeoutError):
        await submission.sign({"ref": "button", "reviewed": True, "omissions_confirmed": True})
    assert submission.state == SubmissionState.SIGNING_ATTEMPTED
    with pytest.raises(ValueError):
        await submission.sign({"ref": "button", "reviewed": True, "omissions_confirmed": True})


def test_draft_or_wrong_tender_is_not_receipt(telemetry):
    submission = Submission(context(), MagicMock(), telemetry)
    submission.prepare(PricingResult(answer=answer()))
    obs = Observation(id="o1", action_id=1, tab=0, url="http://synthetic.test", title="receipt",
                      text="OTHER-TENDER received confirmation C-1")
    args = {"receipt_id": "C-1", "excerpt": "received confirmation C-1"}
    with pytest.raises(ValueError, match="No signing"):
        submission.accept_receipt(obs, args)
    submission.state = SubmissionState.SIGNING_ATTEMPTED
    with pytest.raises(ValueError, match="identify"):
        submission.accept_receipt(obs, args)


async def test_site_submission_cannot_use_api(telemetry):
    submission = Submission(context(), MagicMock(), telemetry)
    submission.prepare(PricingResult(answer=answer()))
    with pytest.raises(ValueError, match="website"):
        await submission.api_submit("synthetic-token")


async def test_receipt_requires_fresh_portal_observation_and_uncertain_retry_is_blocked(telemetry):
    import time
    from datetime import timedelta
    browser = MagicMock(act=AsyncMock(), latest_tan="synthetic", tan_captured_at=time.monotonic())
    submission = Submission(context(), browser, telemetry)
    submission.prepare(PricingResult(answer=answer()))
    old = Observation(id="o1", action_id=1, tab=0, url="http://synthetic.test", title="Receipt",
                      text="SYN-R accepted receipt C-1")
    submission.state = SubmissionState.TAN_REQUESTED
    await submission.sign({"ref": "send", "reviewed": True, "omissions_confirmed": True})
    args = {"receipt_id": "C-1", "excerpt": "accepted receipt C-1"}
    with pytest.raises(ValueError, match="predates"):
        submission.accept_receipt(old, args)
    foreign = Observation(id="o2", action_id=2, tab=0, url="http://mail.test", title="Forwarded receipt", text=old.text)
    with pytest.raises(ValueError, match="declared submission"):
        submission.accept_receipt(foreign, args)
    browser.last_observation = old
    with pytest.raises(ValueError, match="Inspect the portal"):
        await submission.request_tan({"ref": "request"})
    browser.last_observation = Observation(id="o3", action_id=3, tab=0, url="http://synthetic.test", title="Error",
                                           text="SYN-R: TAN invalid", observed_at=submission.signing_started_at + timedelta(seconds=1))
    await submission.request_tan({"ref": "request"})
    assert submission.state == SubmissionState.TAN_REQUESTED
    assert browser.latest_tan is None
