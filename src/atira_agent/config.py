from __future__ import annotations

import json
import os
from dataclasses import dataclass
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
        if provider not in {"qwen", "openai"}:
            raise ValueError("Supported providers: qwen, openai")
        if provider != "qwen" and env.get("ATIRA_ALLOW_PAID") != "1":
            raise ValueError("Paid provider disabled; explicit ATIRA_ALLOW_PAID=1 is required")
        prefix = provider.upper()
        base, key = env.get(f"{prefix}_BASE_URL", ""), env.get(f"{prefix}_API_KEY", "")
        if not base or not key:
            raise ValueError(f"Missing {prefix}_BASE_URL/{prefix}_API_KEY. Start atira models proxy and load scout --env")
        parsed = urlsplit(base)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid model proxy URL")
        if sandbox:
            proxy = env.get("LLM_PROXY_URL", "").rstrip("/")
            if not proxy or not base.startswith(proxy + "/"):
                raise ValueError("Model endpoint must be inside the supplied Atira run proxy")
        elif parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local mode uses the Atira localhost model proxy")
        model = env.get("ATIRA_MODEL", "qwen" if provider == "qwen" else "")
        if not model:
            raise ValueError("A paid provider requires an explicit ATIRA_MODEL")
        budget = min(1200, float(env.get("ATIRA_BUDGET_SECONDS", 1200)))
        reserve = float(env.get("ATIRA_SUBMISSION_RESERVE", 180))
        if budget <= 0 or not 0 < reserve < budget:
            raise ValueError("Require 0 < submission reserve < budget <= 1200 seconds")
        return cls(sandbox, tuple(urls), provider, model, base, key, budget, reserve)
