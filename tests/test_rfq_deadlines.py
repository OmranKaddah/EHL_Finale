"""Regression coverage for the sandbox's numeric expires_at contract."""
from datetime import datetime, timedelta, timezone

import pytest

from hackathon_toolkit.rfq import runtime


@pytest.fixture
def now(monkeypatch):
    fixed = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(runtime, "datetime", FixedDatetime)
    return fixed


def encode_expiry(value, representation):
    if representation == "iso_z":
        return value.isoformat().replace("+00:00", "Z")
    if representation == "iso_offset":
        return value.astimezone(timezone(timedelta(hours=2))).isoformat()
    scale = 1000 if representation.startswith("milliseconds") else 1
    timestamp = value.timestamp() * scale
    return int(timestamp) if representation.endswith("int") else timestamp


FORMATS = ["iso_z", "iso_offset", "seconds_int", "seconds_float",
           "milliseconds_int", "milliseconds_float"]


@pytest.mark.parametrize("representation", FORMATS)
def test_expiry_formats_preserve_remaining_time_and_reserve(now, representation):
    expiry = encode_expiry(now + timedelta(seconds=30), representation)
    assert runtime.run_seconds({"expires_at": expiry}, 1185) == 25


@pytest.mark.parametrize("representation", FORMATS)
def test_expiry_never_extends_configured_budget(now, representation):
    expiry = encode_expiry(now + timedelta(hours=2), representation)
    assert runtime.run_seconds({"expires_at": expiry}, 1185) == 1185


@pytest.mark.parametrize("representation", FORMATS)
@pytest.mark.parametrize("remaining", [-1, 0, 5])
def test_expired_or_reserved_deadline_is_rejected(now, representation, remaining):
    expiry = encode_expiry(now + timedelta(seconds=remaining), representation)
    with pytest.raises(ValueError, match="already expired"):
        runtime.run_seconds({"expires_at": expiry}, 1185)


@pytest.mark.parametrize("representation", ["seconds_float", "milliseconds_float", "iso_z"])
def test_fractional_timestamps_preserve_subsecond_budget(now, representation):
    expiry = encode_expiry(now + timedelta(seconds=30, microseconds=125000), representation)
    assert runtime.run_seconds({"expires_at": expiry}, 1185) == pytest.approx(25.125)


@pytest.mark.parametrize("run", [{}, {"expires_at": None}])
def test_absent_expiry_uses_configured_budget(now, run):
    assert runtime.run_seconds(run, 1185) == 1185


def test_unix_epoch_zero_is_expired_not_missing(now):
    with pytest.raises(ValueError, match="already expired"):
        runtime.run_seconds({"expires_at": 0}, 1185)


def test_iso_expiry_requires_timezone(now):
    with pytest.raises(ValueError, match="timezone-aware"):
        runtime.run_seconds({"expires_at": "2026-10-10T12:00:30"}, 1185)
