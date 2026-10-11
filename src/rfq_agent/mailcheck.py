"""Structural checks on the one signing mail the mail owner selected.

The model picks the message and quotes its send time and validity; code parses the
stated units, date and time zone and refuses a message that is older than the
current request, names another tender, or shows more than one code.
"""

import re
from datetime import datetime, timedelta, timezone

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "mär": 3, "mrz": 3, "apr": 4, "may": 5, "mai": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12}
ZONES = {"utc": 0, "gmt": 0, "wet": 0, "cet": 1, "mez": 1, "bst": 1, "west": 1, "cest": 2, "mesz": 2, "eet": 2, "eest": 3}
UNITS = (("s", r"seconds?|secs?|sekunden?|sek"), ("m", r"minutes?|mins?|minuten?"), ("h", r"hours?|hrs?|stunden?|std"))
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}
VALIDITY_HINT = re.compile(r"\b(valid|validity|expires?|expiry|gültig\w*|gueltig\w*|läuft ab|ablauf\w*|verfällt)\b", re.IGNORECASE)
ABSOLUTE_SKEW = 60       # tolerated clock difference between the mail server and this process
FUTURE_SLACK = 120
RELATIVE_SLACK = 5
_TIME = r"(\d{1,2}):(\d{2})(?::(\d{2}))?"
_MERIDIEM = r"(?:\s*([AaPp])\.?[Mm]\.?)?"


def token(text: str, needle: str) -> bool:
    """needle occurs in text as a whole token, not inside a longer word or number."""
    return bool(needle) and re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", text or "") is not None


def _unit(word: str) -> str | None:
    return next((key for key, pattern in UNITS if re.fullmatch(pattern, word, re.IGNORECASE)), None)


def _clock(hour, minute, second, meridiem=None):
    hour = int(hour)
    if meridiem:
        hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
    return hour, int(minute), int(second or 0), 0 if second else 59


def _zones(rest: str, hint: str | None) -> list:
    for source in (rest, hint or ""):
        match = re.search(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", source, re.IGNORECASE) \
            or re.search(r"(?<![\w.:])([+-])(\d{2}):?(\d{2})(?!\d)", source)
        if match:
            sign = 1 if match.group(1) == "+" else -1
            return [timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3) or 0)))]
        match = re.search(r"\b([A-Z][A-Za-z_]+/[A-Za-z_]+)\b", source)
        if match:
            try:
                from zoneinfo import ZoneInfo
                return [ZoneInfo(match.group(1))]
            except Exception:
                pass
        for word in re.findall(r"[A-Za-z]{2,4}", source):
            if word.lower() in ZONES and (word.isupper() or word.lower() in {"utc", "gmt"}):
                return [timezone(timedelta(hours=ZONES[word.lower()]))]
    # No zone is stated anywhere. Refusing every such mail would make signing impossible on a mailbox
    # that never shows its zone, so whole-hour offsets are tried: a mail still has to land inside the
    # short request window under one of them. Known gap: a mail sent a whole number of hours before
    # the request is not told apart here; the earlier-code check and the portal itself remain.
    return [timezone(timedelta(hours=hours)) for hours in range(-12, 15)]


def parse_when(text: str, now: datetime, zone_hint: str | None = None) -> list[tuple[datetime, datetime]]:
    """Possible (earliest, latest) send instants a visible time statement can mean."""
    text = text or ""
    lowered = text.lower()
    if re.search(r"\b(just now|gerade eben|soeben)\b", lowered):
        return [(now - timedelta(seconds=60), now)]
    relative = re.search(r"\bvor\s+(\d+)\s*([a-zä]+)", lowered) or re.search(r"(\d+)\s*([a-z]+)\s+ago\b", lowered)
    if relative and _unit(relative.group(2)):
        size = UNIT_SECONDS[_unit(relative.group(2))]
        count = int(relative.group(1))
        return [(now - timedelta(seconds=(count + 1) * size), now - timedelta(seconds=count * size))]

    readings, span = [], None
    match = re.search(rf"(\d{{4}})-(\d{{2}})-(\d{{2}})[T ,]+{_TIME}(Z)?", text)
    if match:
        readings.append((int(match[1]), int(match[2]), int(match[3]), _clock(match[4], match[5], match[6])))
        span = match.span()
        if match[7]:
            zone_hint = "UTC"
    if not readings:
        match = re.search(rf"(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}}),?\s+(?:um\s+)?{_TIME}", text)
        if match:
            readings.append((int(match[3]), int(match[2]), int(match[1]), _clock(match[4], match[5], match[6])))
            span = match.span()
    if not readings:
        match = re.search(rf"(\d{{1,2}})/(\d{{1,2}})/(\d{{4}}),?\s+{_TIME}{_MERIDIEM}", text)
        if match:
            clock = _clock(match[4], match[5], match[6], match[7])
            readings += [(int(match[3]), int(match[2]), int(match[1]), clock), (int(match[3]), int(match[1]), int(match[2]), clock)]
            span = match.span()
    if not readings:
        match = re.search(rf"(\d{{1,2}})\.?\s+([A-Za-zä]{{3,9}})\.?,?\s+(\d{{4}}),?\s+(?:at\s+|um\s+)?{_TIME}{_MERIDIEM}", text)
        if match and match[2][:3].lower() in MONTHS:
            readings.append((int(match[3]), MONTHS[match[2][:3].lower()], int(match[1]), _clock(match[4], match[5], match[6], match[7])))
            span = match.span()
    if not readings:
        match = re.search(rf"([A-Za-zä]{{3,9}})\.?\s+(\d{{1,2}}),?\s+(\d{{4}}),?\s+(?:at\s+)?{_TIME}{_MERIDIEM}", text)
        if match and match[1][:3].lower() in MONTHS:
            readings.append((int(match[3]), MONTHS[match[1][:3].lower()], int(match[2]), _clock(match[4], match[5], match[6], match[7])))
            span = match.span()
    time_only = None
    if not readings:
        match = re.search(rf"(?<![\d:]){_TIME}{_MERIDIEM}", text)
        if not match:
            return []
        time_only, span = _clock(match[1], match[2], match[3], match[4]), match.span()
    zones = _zones(text[:span[0]] + " " + text[span[1]:], zone_hint)
    found = []
    for zone in zones:
        dated = readings or [(local.year, local.month, local.day, time_only) for local in [now.astimezone(zone)]]
        for year, month, day, (hour, minute, second, slack) in dated:
            try:
                start = datetime(year, month, day, hour, minute, second, tzinfo=zone)
            except ValueError:
                continue
            found.append((start, start + timedelta(seconds=slack)))
    return found


def check_signing_mail(reference: str, value: str, page_text: str, message, sent_at, validity, zone_hint,
                       requested: datetime, observed: datetime) -> datetime | None:
    """Raise ValueError unless this is one fresh mail for the tender with one code; return its expiry if stated."""
    if not isinstance(message, str) or not message.strip() or len(message) > 3000 or message not in (page_text or ""):
        raise ValueError("quote the opened signing mail (at most 3000 characters) exactly as shown")
    if not token(message, reference):
        raise ValueError("the selected mail does not name the exact tender reference")
    if message.count(value) != 1:
        raise ValueError("the code must appear exactly one time in the selected mail")
    if not isinstance(sent_at, str) or not sent_at.strip() or sent_at not in message:
        raise ValueError("quote the mail's own send time from the opened mail")
    rest = message.replace(sent_at, " ")
    if isinstance(validity, str) and validity.strip():
        if validity not in message:
            raise ValueError("the validity statement must be quoted from the opened mail")
        rest = rest.replace(validity, " ")
    rest = rest.replace(reference, " ")
    shaped = re.findall(rf"(?<![\w-])[A-Za-z0-9]{{{len(value)}}}(?![\w-])", rest)
    others = [item for item in shaped if item != value and (item.isdigit() if value.isdigit() else any(c.isdigit() for c in item))]
    if others:
        raise ValueError("the quoted text shows more than one code; open the one newest mail for this tender and quote only it")
    relative = bool(re.search(r"\bago\b|\bvor\s+\d|just now|gerade eben|soeben", sent_at.lower()))
    skew = RELATIVE_SLACK if relative else ABSOLUTE_SKEW
    candidates = parse_when(sent_at, observed, zone_hint)
    if not candidates:
        raise ValueError("the send time could not be read; quote its date, time and time zone as shown")
    fresh = [(earliest, latest) for earliest, latest in candidates
             if (earliest if relative else latest) >= requested - timedelta(seconds=skew)
             and earliest <= observed + timedelta(seconds=FUTURE_SLACK)]
    if not fresh:
        raise ValueError("the mail was sent before the current code request (or its time zone is unclear: pass the "
                         "zone shown by the mailbox as timezone); wait for the newest mail of this request")
    if not (isinstance(validity, str) and validity.strip()):
        if VALIDITY_HINT.search(rest):
            raise ValueError("the mail states a validity; quote that validity statement as validity")
        return None
    duration = re.search(r"(\d+)\s*([A-Za-zä]+)", validity)
    if duration and _unit(duration.group(2)):
        return fresh[0][0] + timedelta(seconds=int(duration.group(1)) * UNIT_SECONDS[_unit(duration.group(2))])
    until = parse_when(validity, observed, zone_hint or sent_at)
    if not until:
        raise ValueError("the validity statement could not be interpreted (units, date or time zone)")
    return min(latest for _, latest in until)
