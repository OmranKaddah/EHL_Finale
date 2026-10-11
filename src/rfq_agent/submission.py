"""Transactional submission state: nothing is signed or accepted out of order.

The controller holds no browser. The model chooses controls and quotes; code reports
what was observed, and each method checks that observation against the validated draft.
Acceptance and failure wording is recognized in English and German only; a portal in
another language stays unresolved rather than being guessed.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from urllib.parse import urlparse

from .draft import Draft, DraftError, _decimal, _is_number, leaves, names_position, parse_numbers, validate_draft
from .mailcheck import check_signing_mail
from .redact import Secret

OWNER = "tender"
OMISSION_WITHOUT_CONTROL = "omission_without_control"
NOT_ON_FORM = "not_on_form:"
MAX_SEEN = 300_000

POSITIVE_RE = re.compile(
    r"\b(received|accepted|submitted|success\w*|confirmed|confirmation|acknowledg\w*|receipt|signed|"
    r"eingegangen|eingereicht|übermittelt|abgegeben|erfolgreich|angenommen|bestätig\w*|signiert|unterzeichnet|"
    r"quittung|eingangsbestätigung|empfangsbestätigung)\b", re.IGNORECASE)
NEGATIVE_RE = re.compile(
    r"\b(error|errors|fehler|failed|failure|fehlgeschlagen|rejected|abgelehnt|declined|invalid|ungültig\w*|expired|"
    r"abgelaufen|denied|verweigert|unable|unsuccessful|cannot|problem)\b|could not|konnte nicht|"
    r"\bnicht\s+(erfolgreich|eingereicht|übermittelt|angenommen|abgegeben|akzeptiert)|"
    r"\bnot\s+(been\s+)?(submitted|accepted|received|successful|signed)", re.IGNORECASE)
DRAFT_RE = re.compile(
    r"\b(draft|entwurf\w*|zwischengespeichert|zwischenstand|saved|gespeichert)\b|not yet (submitted|signed)|"
    r"noch nicht (eingereicht|signiert|abgegeben)", re.IGNORECASE)


class SubmissionError(ValueError):
    pass


class Phase(Enum):
    BOOT = "boot"
    IDENTIFY = "identify"
    PREPARE = "prepare"
    VALIDATE = "validate"
    FILL = "fill"
    REVIEW = "review"
    REQUEST_TAN = "request_tan"
    READ_TAN = "read_tan"
    SIGN = "sign"
    VERIFY_RECEIPT = "verify_receipt"
    ACCEPTED = "accepted"


UNCERTAIN = "a signing attempt is unresolved: observe a receipt or an explicit validation failure first"
AFTER_REVIEW = (Phase.REVIEW, Phase.REQUEST_TAN, Phase.READ_TAN)


def origin(url: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    return parsed.scheme.lower(), parsed.netloc.lower()


def same_value(expected, observed: str) -> bool:
    """Whether a control's live value shows the draft value (numbers compare as Decimal)."""
    if isinstance(expected, bool):
        return str(observed).strip().lower() == str(expected).lower()
    if _is_number(expected):
        return _decimal(expected) in parse_numbers(str(observed))
    return str(observed).strip() == str(expected)


class SubmissionController:
    def __init__(self, submission_url: str, *, clock=time.monotonic, redactor=None, wall=None):
        self.submission_url = submission_url
        self._clock = clock
        self._wall = wall or (lambda: datetime.now(timezone.utc))
        self._redactor = redactor
        self.phase = Phase.BOOT
        self.history = [Phase.BOOT]
        self.reference: str | None = None
        self.portal_confirmed = False
        self.draft: Draft | None = None
        self.checklist: list | None = None          # cross-position rules, established apart from the draft
        self.capabilities: dict = {}
        self.filled: set[str] = set()
        self.bindings: dict = {}                    # draft path -> descriptor of the control that holds it
        self.entered: dict = {}                     # draft path -> text typed into that control
        self.verified: set[str] = set()             # paths read back from the form since their last change
        self.omission_actions: set[str] = set()
        self.omission_states: dict = {}             # position -> {"descriptor", "state"} after the omit action
        self.stale_controls: dict = {}              # descriptor -> what an earlier draft left in the form
        self.stale_values: dict = {}                # position -> numbers an earlier draft entered for it
        self.pending_restore: set[str] = set()      # positions omitted in the form by an earlier draft
        self.review_hash: str | None = None
        self.sign_attempts = 0
        self.receipt: dict | None = None
        self.held_codes: list[Secret] = []          # every code ever held, for redaction and screenshot checks
        self._seen = ""
        self._seen_at_draft = ""
        self._seen_at_omission: dict = {}
        self._old_states: dict = {}
        self._tan: Secret | None = None
        self._tan_expires_at: float | None = None
        self._burned: set[str] = set()
        self._tan_requested_at: float | None = None
        self._tan_requested_wall: datetime | None = None
        self._sign_started_at: float | None = None
        self._pre_sign_text = ""

    def now(self) -> float:
        return self._clock()

    def _go(self, phase: Phase) -> None:
        self.phase = phase
        self.history.append(phase)

    def _need(self, action: str, *phases: Phase) -> None:
        if self.phase not in phases:
            raise SubmissionError(f"{action} requires phase {' or '.join(p.name for p in phases)}; "
                                  f"current phase is {self.phase.name}")

    def _owner(self, actor: str) -> None:
        if actor != OWNER:
            raise SubmissionError("only the tender owner may change or sign the submission")

    def _burn_tan(self) -> None:
        if self._tan is not None:
            self._burned.add(hashlib.sha256(self._tan.reveal().encode()).hexdigest())
        self._tan, self._tan_expires_at = None, None

    def note_observed(self, text: str) -> None:
        """Remember page text the owner has seen, to tell an omitted state from text that was always there."""
        if text and text not in self._seen:
            self._seen = (self._seen + "\n" + text)[-MAX_SEEN:]

    # --- identify -----------------------------------------------------------
    def identify(self, reference: str, brief: str, evidence: list) -> None:
        self._need("identify", Phase.BOOT)
        if not isinstance(reference, str) or not reference.strip() or not (
                reference in brief or any(reference in item.quote for item in evidence)):
            raise SubmissionError("tender reference is not found verbatim in the run brief or recorded evidence")
        self.reference = reference
        self._go(Phase.IDENTIFY)

    def confirm_on_portal(self, url: str, text: str) -> None:
        """The submission website itself must show the exact reference; nothing is normalized."""
        if self.reference is None:
            raise SubmissionError("identify the tender reference first")
        if origin(url) != origin(self.submission_url):
            raise SubmissionError("the tender must be confirmed on the declared submission portal")
        if self.reference not in text:
            raise SubmissionError("the portal page does not show the exact tender reference")
        self.portal_confirmed = True
        if self.phase == Phase.IDENTIFY:
            self._go(Phase.PREPARE)

    def observe_capability(self, name: str, supported: bool, quote: str, page_text: str) -> None:
        if not isinstance(name, str) or not name or not isinstance(supported, bool):
            raise SubmissionError("capability needs a name and a true/false observation")
        if not isinstance(quote, str) or not quote.strip() or quote not in page_text:
            raise SubmissionError("capability quote must be visible in the current observation")
        self.capabilities[name] = {"supported": supported, "quote": quote[:300]}

    # --- draft --------------------------------------------------------------
    def accept_draft(self, candidate, schema, brief: str, evidence: list) -> Draft:
        self._need("accept_draft", Phase.PREPARE)
        try:
            draft = validate_draft(candidate, schema, brief, evidence, self.capabilities, checklist=self.checklist)
        except DraftError as exc:
            raise SubmissionError(f"draft rejected: {exc}") from exc
        if draft.reference != self.reference:
            raise SubmissionError("draft reference differs from the identified tender reference")
        self.draft = draft
        self._seen_at_draft = self._seen
        for position in list(self.pending_restore):
            if position in draft.omitted:
                # Still omitted in the new draft: the form state left by the earlier draft stands.
                self.omission_states[position] = self._old_states.get(position, {})
                self.omission_actions.add(position)
                self.pending_restore.discard(position)
        self._go(Phase.VALIDATE)
        self._go(Phase.FILL)
        return draft

    def _position_of(self, path: str) -> str | None:
        if self.draft is None:
            return None
        return next((position for position, root in self.draft.priced if path == root or path.startswith(root + ".")), None)

    def reopen_draft(self, actor: str) -> None:
        """Void the draft. What it left in the live form is tracked until it is cleared or re-entered."""
        self._owner(actor)
        self._need("reopen_draft", Phase.FILL, *AFTER_REVIEW)
        self._burn_tan()
        for path, descriptor in self.bindings.items():
            position = self._position_of(path)
            self.stale_controls[descriptor] = {"text": self.entered.get(path, ""), "position": position}
            if position is not None:
                self.stale_values.setdefault(position, set()).update(parse_numbers(str(self.entered.get(path, ""))))
        self._old_states = dict(self.omission_states)
        self.pending_restore |= set(self.omission_actions)
        self.draft, self.review_hash = None, None
        for store in (self.filled, self.bindings, self.entered, self.verified, self.omission_actions,
                      self.omission_states, self._seen_at_omission):
            store.clear()
        self._go(Phase.PREPARE)

    def value_for(self, path: str):
        self._need("value_for", Phase.FILL, *AFTER_REVIEW)
        try:
            return self.draft.value(path)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise SubmissionError("path is not a value of the validated draft") from exc

    def invalidate_review(self, reason: str) -> None:
        """Any change to the form after review voids the review and a held or requested code."""
        if self.phase in AFTER_REVIEW:
            self._burn_tan()
            self.review_hash = None
            self._go(Phase.FILL)

    def note_filled(self, path: str, descriptor=None, shown=None) -> None:
        self.value_for(path)
        if descriptor is not None:
            other = next((p for p, d in self.bindings.items() if d == descriptor and p != path), None)
            if other is not None:
                raise SubmissionError(f"that control already holds the draft value for {other}")
            self.bindings[path] = descriptor
            self.stale_controls.pop(descriptor, None)
        if shown is not None:
            self.entered[path] = shown
        self.filled.add(path)
        self.verified.discard(path)
        self.invalidate_review("a draft value was entered")

    def note_mutated(self, descriptor) -> None:
        """A bound control was changed outside enter_value: its path must be read back again."""
        for path, bound in self.bindings.items():
            if bound == descriptor:
                self.verified.discard(path)
        self.invalidate_review("a form control changed")

    def note_cleared(self, descriptor) -> None:
        self.stale_controls.pop(descriptor, None)
        self.invalidate_review("a superseded value was cleared")

    def note_omission(self, position: str, descriptor=None, state=None) -> None:
        self._need("note_omission", Phase.FILL, *AFTER_REVIEW)
        if position not in self.draft.omitted:
            raise SubmissionError("position is not in the draft's omitted list")
        self.omission_actions.add(position)
        self.omission_states[position] = {"descriptor": descriptor, "state": state}
        self._seen_at_omission[position] = self._seen
        self.pending_restore.discard(position)
        self.invalidate_review("a position was omitted")

    def note_restored(self, position: str) -> None:
        self.pending_restore.discard(position)
        self.invalidate_review("an omission was undone")

    def required_paths(self) -> set[str]:
        """What must be read back from the form: every number of each priced position, every
        top-level number (totals) and every entered value, unless observed as not on the form."""
        roots = [root for _, root in self.draft.priced]
        required = set(self.filled)
        for path, value in leaves(self.draft.answer):
            in_position = any(path.startswith(root + ".") for root in roots)
            top_level = not any(part.isdigit() for part in path.split("."))
            if _is_number(value) and (in_position or top_level):
                required.add(path)
        return {path for path in required
                if (self.capabilities.get(NOT_ON_FORM + path) or {}).get("supported") is not True}

    def _check_readbacks(self, readbacks, page_text, static, descriptors) -> tuple[set, list]:
        good, problems = set(), []
        for path, observed in (readbacks or {}).items():
            try:
                value = self.draft.value(path)
            except (KeyError, IndexError, ValueError, TypeError):
                problems.append(f"{path}: not a value of the draft")
                continue
            bound, read_from = self.bindings.get(path), (descriptors or {}).get(path)
            if bound is not None and read_from is not None and read_from != bound:
                problems.append(f"{path}: the readback came from a different control than the one that was filled")
            elif not same_value(value, observed):
                problems.append(f"{path}: readback differs from the draft")
            else:
                good.add(path)
        for path, quote in (static or {}).items():
            try:
                value = self.draft.value(path)
            except (KeyError, IndexError, ValueError, TypeError):
                problems.append(f"{path}: not a value of the draft")
                continue
            position = self._position_of(path)
            shown = isinstance(quote, str) and (
                _decimal(value) in parse_numbers(quote) if _is_number(value) else str(value) in quote)
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 400 or quote not in page_text:
                problems.append(f"{path}: the static quote is not visible in the current observation")
            elif not shown:
                problems.append(f"{path}: the static quote does not show the draft value")
            elif position is not None and not names_position(quote, position):
                problems.append(f"{path}: the static quote must show the value in text that names position {position}")
            else:
                good.add(path)
        return good, problems

    def collect(self, readbacks: dict, page_text: str, *, static=None, descriptors=None) -> None:
        """Keep verified readbacks of one wizard page; later pages and the final review build on them."""
        self._need("collect", Phase.FILL, Phase.REVIEW)
        good, problems = self._check_readbacks(readbacks, page_text, static, descriptors)
        if problems:
            raise SubmissionError("readback failed: " + "; ".join(problems[:10]))
        self.verified |= good

    def _review_hash(self) -> str:
        blob = json.dumps({"answer": self.draft.answer, "identity": self.draft.identity, "omitted": self.draft.omitted,
                           "verified": sorted(self.verified), "omissions": sorted(self.omission_states)},
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def review(self, readbacks: dict, omission_quotes: dict, page_text: str, *, static=None, descriptors=None,
               omission_live=None, unbound=(), empty_required=()) -> None:
        """Final check before a code is requested: every required value read back, every omission
        shown as an omitted state, nothing unknown or superseded left in the form."""
        self._need("review", Phase.FILL)
        if not self.portal_confirmed:
            raise SubmissionError("the tender reference has not been confirmed on the portal")
        good, problems = self._check_readbacks(readbacks, page_text, static, descriptors)
        for descriptor in self.stale_controls:
            problems.append(f"a superseded value of the earlier draft is still in control {descriptor}; "
                            "clear it or enter the new draft value there")
        for position in sorted(self.pending_restore):
            problems.append(f"position {position} is still omitted in the form from the earlier draft; restore it")
        for path in sorted(self.required_paths() - self.verified - good):
            problems.append(f"{path}: not verified against the form (enter it, then read it back)")
        without_control = (self.capabilities.get(OMISSION_WITHOUT_CONTROL) or {}).get("supported") is True
        for position in self.draft.omitted:
            quote = omission_quotes.get(position)
            state = self.omission_states.get(position)
            live = (omission_live or {}).get(position)
            if state is not None and live is not None and state.get("state") is not None:
                if live != state["state"]:
                    problems.append(f"{position}: its omission control is no longer in the omitted state")
                continue
            if state is None and not without_control:
                problems.append(f"omission of {position} was not performed on an observed control")
            elif not isinstance(quote, str) or not names_position(quote, position):
                problems.append(f"{position}: no review quote naming the omitted position")
            elif quote not in page_text:
                problems.append(f"{position}: omission quote is not visible in the current observation")
            elif quote in (self._seen_at_omission.get(position, self._seen_at_draft)):
                problems.append(f"{position}: that text was already shown before the position was omitted; "
                                "quote text that shows its omitted state")
            elif self.stale_values.get(position, set()) & parse_numbers(quote):
                problems.append(f"{position}: the omission text still shows a superseded value of the earlier draft")
        if set(omission_quotes) - set(self.draft.omitted):
            problems.append("review lists omissions that are not in the draft")
        problems += [f"control '{name}' holds a value that is not bound to a draft path" for name in unbound]
        problems += [f"required field '{name}' is empty" for name in empty_required]
        if problems:
            raise SubmissionError("review failed: " + "; ".join(problems[:10]))
        self.verified |= good
        self.review_hash = self._review_hash()
        self._go(Phase.REVIEW)

    # --- TAN ----------------------------------------------------------------
    def request_tan(self, actor: str, requested_at: float | None = None) -> None:
        """Record a code request that was actually made (call only after the request control worked)."""
        self._owner(actor)
        if self.phase == Phase.SIGN:
            raise SubmissionError(UNCERTAIN)
        self._need("request_tan", *AFTER_REVIEW)
        self._burn_tan()
        now = self._clock()
        self._tan_requested_at = now if requested_at is None else requested_at
        self._tan_requested_wall = self._wall() - timedelta(seconds=now - self._tan_requested_at)
        self._go(Phase.REQUEST_TAN)

    def accept_tan(self, value: str, page_text: str, observed_at: float, *, message=None, sent_at=None,
                   validity=None, timezone=None) -> None:
        """Hold the code of the one opened mail that names this tender and was sent for this request."""
        self._need("accept_tan", Phase.REQUEST_TAN)
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise SubmissionError("TAN must be a short visible code")
        if observed_at <= self._tan_requested_at:
            raise SubmissionError("the mail was observed before the current TAN request")
        if hashlib.sha256(value.encode()).hexdigest() in self._burned:
            raise SubmissionError("this TAN belongs to an earlier request; read the newest signing mail")
        observed_wall = self._wall() - timedelta(seconds=self._clock() - observed_at)
        try:
            expires = check_signing_mail(self.reference, value, page_text, message, sent_at, validity, timezone,
                                         self._tan_requested_wall, observed_wall)
        except ValueError as exc:
            raise SubmissionError(str(exc)) from exc
        expires_at = None
        if expires is not None:
            expires_at = self._clock() + (expires - self._wall()).total_seconds()
            if expires_at <= self._clock():
                raise SubmissionError("by its stated validity this code has expired; request a new one")
        self._tan, self._tan_expires_at = Secret(value), expires_at
        self.held_codes.append(self._tan)
        if self._redactor is not None:
            self._redactor.add(self._tan)
        self._go(Phase.READ_TAN)

    def _live_tan(self) -> Secret:
        if self._tan is None:
            raise SubmissionError("no TAN is held for the current request")
        if self._tan_expires_at is not None and self._clock() >= self._tan_expires_at:
            raise SubmissionError("the held signing code has expired by its stated validity; request a new one")
        return self._tan

    def tan_for_entry(self, actor: str) -> Secret:
        self._owner(actor)
        self._need("tan_for_entry", Phase.READ_TAN, Phase.SIGN)
        return self._live_tan()

    # --- sign and receipt ---------------------------------------------------
    def begin_sign(self, actor: str, pre_sign_text: str) -> None:
        """Record the one signing attempt before the click; a timeout leaves it unresolved."""
        self._owner(actor)
        if self.phase == Phase.SIGN:
            raise SubmissionError(UNCERTAIN)
        self._need("begin_sign", Phase.READ_TAN)
        self._live_tan()
        if self.review_hash is None or self.review_hash != self._review_hash():
            raise SubmissionError("the reviewed form state no longer matches the draft; review again")
        self._pre_sign_text = pre_sign_text or ""
        self._sign_started_at = self._clock()
        self.sign_attempts += 1
        self._go(Phase.SIGN)

    def _after_sign(self, what: str, url: str, observed_at: float) -> None:
        self._need(what, Phase.SIGN)
        if observed_at <= self._sign_started_at:
            raise SubmissionError("the observation was made before the signing attempt")
        if origin(url) != origin(self.submission_url):
            raise SubmissionError("the observation is not on the declared submission portal origin")

    def verify_receipt(self, url: str, text: str, observed_at: float, excerpt: str, receipt_id: str) -> dict:
        """Accept only one visible block that states acceptance and carries both the receipt
        identifier and the exact tender reference, first shown after this signing attempt."""
        self._after_sign("verify_receipt", url, observed_at)
        if (not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 1500
                or not isinstance(receipt_id, str) or len(receipt_id.strip()) < 2):
            raise SubmissionError("quote the acceptance block (at most 1500 characters) and its receipt identifier")
        if excerpt in self._pre_sign_text or receipt_id in self._pre_sign_text:
            raise SubmissionError("that text was already visible before signing; it is not a receipt for this attempt")
        if excerpt not in text:
            raise SubmissionError("the acceptance excerpt is not visible on the observed page")
        if not names_position(excerpt, self.reference):
            raise SubmissionError("the acceptance excerpt must itself show the exact tender reference")
        if receipt_id in self.reference or not names_position(excerpt, receipt_id):
            raise SubmissionError("the acceptance excerpt must itself show a receipt identifier other than the reference")
        if NEGATIVE_RE.search(excerpt) or DRAFT_RE.search(excerpt):
            raise SubmissionError("that text reports an error, a rejection or a saved draft; it is not an acceptance")
        if not POSITIVE_RE.search(excerpt):
            raise SubmissionError("the excerpt does not state that the bid was received or accepted")
        self.receipt = {"receipt_id": receipt_id, "excerpt": excerpt[:500], "url": url, "reference": self.reference,
                        "review_hash": self.review_hash}
        self._go(Phase.VERIFY_RECEIPT)
        self._go(Phase.ACCEPTED)
        return self.receipt

    def validation_failure(self, url: str, text: str, observed_at: float, quote: str) -> None:
        """Only an unmistakable portal rejection after signing reopens filling; it never repeats the click."""
        self._after_sign("validation_failure", url, observed_at)
        if not isinstance(quote, str) or not quote.strip() or quote not in text:
            raise SubmissionError("quote the explicit validation failure visible on the portal")
        if quote in self._pre_sign_text:
            raise SubmissionError("that text was already visible before signing; it does not explain this attempt")
        if not NEGATIVE_RE.search(quote):
            raise SubmissionError("that text does not state an error or rejection; if the bid was received, confirm the receipt")
        self._burn_tan()
        self.review_hash = None
        self._go(Phase.FILL)

    def snapshot(self) -> dict:
        """State for prompts and logs; never contains the TAN."""
        return {
            "phase": self.phase.name,
            "reference": self.reference,
            "portal_confirmed": self.portal_confirmed,
            "capabilities": self.capabilities,
            "entered_paths": sorted(self.filled),
            "verified_paths": sorted(self.verified),
            "still_to_verify": sorted(self.required_paths() - self.verified) if self.draft else [],
            "omissions_done": sorted(self.omission_actions),
            "omitted": list(self.draft.omitted) if self.draft else [],
            "superseded_controls_to_clear": [str(item) for item in self.stale_controls],
            "omissions_to_restore": sorted(self.pending_restore),
            "tan": "held" if self._tan is not None else "none",
            "sign_attempts": self.sign_attempts,
            "receipt": self.receipt,
        }
