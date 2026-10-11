from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    sandbox: bool
    cdp_urls: tuple[str, ...]
    provider: str
    model: str
    model_url: str
    model_key: str
    budget: float = 1200
    reserve: float = 180
    clef_url: str | None = None
    clef_key: str | None = None
    clef_model: str = "clef"
    qwen_model: str = "qwen"
    qwen_url: str | None = None
    qwen_key: str | None = None
    openai_model: str | None = None
    openai_url: str | None = None
    openai_key: str | None = None
    role_routing: tuple[tuple[str, str], ...] = ()

    def for_role(self, role: str) -> "Config":
        """Select a configured provider for one bounded responsibility."""
        if self.provider != "hybrid":
            return self
        selected = dict(self.role_routing).get(role, "qwen")
        if selected == "qwen":
            return replace(self, provider="qwen", model=self.qwen_model,
                           model_url=self.qwen_url or "", model_key=self.qwen_key or "")
        if selected == "openai":
            return replace(self, provider="openai", model=self.openai_model or "",
                           model_url=self.openai_url or "", model_key=self.openai_key or "")
        raise ValueError(f"Unsupported routed provider {selected!r}")

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        sandbox = bool(env.get("CHALLENGE_RUN_TOKEN"))
        raw = env.get("CDP_URLS")
        if raw:
            urls = json.loads(raw)
            if not isinstance(urls, list) or not urls or not all(isinstance(x, str) for x in urls):
                raise ValueError("CDP_URLS must be a nonempty JSON array of URLs")
        else:
            urls = [env["CDP_URL"]] if env.get("CDP_URL") else []
        if sandbox and not urls:
            raise ValueError("Sandbox requires a supplied CDP connection; launching Chromium is forbidden")
        if len(urls) > 4:
            raise ValueError("Atira provides at most four browsers")
        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https", "ws", "wss"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("CDP must connect to a supplied local browser")
        provider = env.get("ATIRA_MODEL_PROVIDER", "qwen")
        if provider not in {"qwen", "openai", "hybrid"}:
            raise ValueError("Supported providers: qwen, openai, hybrid")
        if provider != "qwen" and env.get("ATIRA_ALLOW_PAID") != "1":
            raise ValueError("Paid provider disabled; explicit ATIRA_ALLOW_PAID=1 is required")
        qwen_base, qwen_key = env.get("QWEN_BASE_URL", ""), env.get("QWEN_API_KEY", "")
        openai_base, openai_key = env.get("OPENAI_BASE_URL", ""), env.get("OPENAI_API_KEY", "")
        qwen_model = env.get("ATIRA_QWEN_MODEL", env.get("QWEN_MODEL", "qwen"))
        openai_model = env.get("ATIRA_OPENAI_MODEL", env.get("OPENAI_MODEL", ""))

        def validate_endpoint(name: str, base: str, key: str):
            if not base or not key:
                raise ValueError(f"Missing {name}_BASE_URL/{name}_API_KEY. Start the Atira model proxy and load its environment")
            parsed = urlsplit(base)
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Invalid model proxy URL")
            if sandbox:
                proxy = env.get("LLM_PROXY_URL", "").rstrip("/")
                if not proxy or not base.startswith(proxy + "/"):
                    raise ValueError("Model endpoint must be inside the supplied Atira run proxy")
            elif parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Local mode uses the Atira localhost model proxy")

        if provider in {"qwen", "hybrid"}:
            validate_endpoint("QWEN", qwen_base, qwen_key)
        if provider in {"openai", "hybrid"}:
            validate_endpoint("OPENAI", openai_base, openai_key)
            if not openai_model:
                raise ValueError("An OpenAI provider requires explicit ATIRA_OPENAI_MODEL or OPENAI_MODEL")
        if provider == "qwen":
            model, base, key = qwen_model, qwen_base, qwen_key
        elif provider == "openai":
            model, base, key = openai_model, openai_base, openai_key
        else:
            # Qwen remains the default for the cheap dispatch call.  Critical
            # roles are routed explicitly below, never via a silent fallback.
            model, base, key = qwen_model, qwen_base, qwen_key
        raw_routing = env.get("ATIRA_MODEL_ROLE_ROUTING", "")
        defaults = {"tender": "openai", "specifications": "openai", "erp": "qwen", "mail": "qwen", "submission": "openai"}
        if raw_routing:
            try:
                routing = json.loads(raw_routing)
            except json.JSONDecodeError as exc:
                raise ValueError("ATIRA_MODEL_ROLE_ROUTING must be a JSON object") from exc
            if not isinstance(routing, dict) or any(role not in defaults or choice not in {"qwen", "openai"}
                                                   for role, choice in routing.items()):
                raise ValueError("ATIRA_MODEL_ROLE_ROUTING may map tender/specifications/erp/mail/submission to qwen or openai")
            defaults.update(routing)
        budget = min(1200, float(env.get("ATIRA_BUDGET_SECONDS", 1200)))
        reserve = float(env.get("ATIRA_SUBMISSION_RESERVE", 180))
        if budget <= 0 or not 0 < reserve < budget:
            raise ValueError("Require 0 < submission reserve < budget <= 1200 seconds")
        clef_url, clef_key = env.get("CLEF_BASE_URL"), env.get("CLEF_API_KEY")
        if bool(clef_url) != bool(clef_key):
            raise ValueError("CLEF_BASE_URL and CLEF_API_KEY must be supplied together")
        if clef_url:
            clef = urlsplit(clef_url)
            if not clef.hostname or clef.username or clef.password:
                raise ValueError("Invalid Clef proxy URL")
            if sandbox:
                proxy = env.get("LLM_PROXY_URL", "").rstrip("/")
                if not proxy or not clef_url.startswith(proxy + "/"):
                    raise ValueError("Clef endpoint must be inside the supplied Atira run proxy")
            elif clef.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Local mode uses the Atira localhost Clef proxy")
        return cls(sandbox, tuple(urls), provider, model, base, key, budget, reserve, clef_url, clef_key,
                   env.get("ATIRA_CLEF_MODEL", "clef"), qwen_model, qwen_base, qwen_key,
                   openai_model or None, openai_base or None, openai_key or None, tuple(defaults.items()))
