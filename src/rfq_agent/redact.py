"""Process-only secrets and log redaction for credentials, tokens and TANs."""

import re

SECRET_ENV_RE = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)


class Secret:
    """A value that never renders itself; call reveal() only at the point of use."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "[secret]"

    __str__ = __repr__


class Redactor:
    def __init__(self):
        self._secrets: set[str] = set()

    def add(self, secret) -> None:
        value = secret.reveal() if isinstance(secret, Secret) else secret
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if isinstance(value, str) and len(value) >= 4:
            self._secrets.add(value)

    def scrub(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "[redacted]")
        return text

    @classmethod
    def from_runtime(cls, env, sites) -> "Redactor":
        redactor = cls()
        for name, value in env.items():
            if SECRET_ENV_RE.search(name):
                redactor.add(value)
        for site in sites:
            credentials = site.get("_credentials") or site.get("credentials") or {}
            if isinstance(credentials, dict):
                for value in credentials.values():
                    redactor.add(value)
        return redactor


class RedactingStream:
    """Wraps stdout/stderr so every runtime log line is scrubbed before it is written."""

    def __init__(self, stream, redactor: Redactor):
        self._stream, self._redactor = stream, redactor

    def write(self, text):
        return self._stream.write(self._redactor.scrub(text))

    def __getattr__(self, name):
        return getattr(self._stream, name)
