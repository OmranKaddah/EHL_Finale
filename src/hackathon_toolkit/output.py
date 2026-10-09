from __future__ import annotations

import csv
import io
import json
import asyncio
import random
from pathlib import Path
from typing import Any, Callable

import httpx


def export_results(records: list[dict[str, Any]], format: str) -> str:
    if format == "json": return json.dumps(records, indent=2, default=str)
    if format == "jsonl": return "\n".join(json.dumps(row, default=str) for row in records)
    if format == "csv":
        output = io.StringIO()
        fields = sorted({key for row in records for key in row})
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: json.dumps(value) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in records)
        return output.getvalue()
    if format == "markdown":
        return "# Processing results\n\n" + "\n".join(f"- `{row.get('job_id', '?')}`: {row.get('status', '?')}" for row in records)
    raise ValueError("unsupported output format")


class LocalSubmitter:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    async def submit(self, key: str, result: dict, *, dry_run: bool = False) -> str:
        if dry_run: return "dry-run"
        safe = "".join(c for c in key if c.isalnum() or c in "-_" )
        if not safe or safe != key: raise ValueError("unsafe output key")
        target = self.directory / f"{safe}.json"
        temp = self.directory / f".{safe}.tmp"
        temp.write_text(json.dumps(result, indent=2, default=str))
        temp.replace(target)
        return str(target)


class HTTPSubmitter:
    def __init__(self, url: str, *, token: str | None = None, timeout: float = 10,
                 client: httpx.AsyncClient | None = None, retries: int = 2,
                 response_validator: Callable[[httpx.Response], bool] | None = None):
        if not url.startswith("https://") and not url.startswith("http://localhost"):
            raise ValueError("submission URL must use HTTPS or localhost")
        self.url, self.token, self.timeout, self.client, self.retries = url, token, timeout, client, retries
        self.response_validator = response_validator

    async def submit(self, key: str, result: dict, *, dry_run: bool = False) -> str:
        if dry_run: return "dry-run"
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        try:
            headers = {"Idempotency-Key": key}
            if self.token: headers["Authorization"] = f"Bearer {self.token}"
            for attempt in range(self.retries + 1):
                try:
                    response = await client.post(self.url, json=result, headers=headers, timeout=self.timeout)
                    response.raise_for_status()
                    if self.response_validator and not self.response_validator(response):
                        raise ValueError("submission response failed validation")
                    return response.headers.get("X-Submission-ID", key)
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {429, 500, 502, 503, 504}
                    if not retryable or attempt == self.retries:
                        raise
                    await asyncio.sleep(min(.25 * 2 ** attempt + random.uniform(0, .1), 2))
        finally:
            if self.client is None: await client.aclose()
