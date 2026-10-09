from __future__ import annotations

import asyncio
import hashlib
from typing import Sequence

from .cache import SQLiteCache, cache_key


class EmbeddingService:
    def __init__(self, *, model: str = "text-embedding-3-small", dimensions: int = 1536,
                 client=None, cache: SQLiteCache | None = None, concurrency: int = 4,
                 preprocessing_version: str = "v1", timeout: float = 60, max_retries: int = 2):
        if dimensions <= 0 or concurrency <= 0 or timeout <= 0 or max_retries < 0:
            raise ValueError("invalid embedding dimensions, concurrency, timeout, or retries")
        self.client, self.model, self.dimensions = client, model, dimensions
        self.cache, self.preprocessing_version = cache, preprocessing_version
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout, self.max_retries = timeout, max_retries
        self.tokens = 0
        self.requests = 0

    async def embed(self, texts: Sequence[str], *, batch_size: int = 64) -> list[list[float]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not texts:
            return []
        keys = [cache_key("embedding", text_hash=hashlib.sha256(t.encode()).hexdigest(), model=self.model, dimensions=self.dimensions,
                          preprocessing=self.preprocessing_version) for t in texts]
        results: list[list[float] | None] = [self.cache.get(k) if self.cache else None for k in keys]
        missing = {key: texts[i] for i, key in enumerate(keys) if results[i] is None}
        if missing and self.client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI()
        items = list(missing.items())

        async def fetch(batch: list[tuple[str, str]]) -> list[tuple[str, list[float]]]:
            async with self.semaphore:
                for attempt in range(self.max_retries + 1):
                    try:
                        self.requests += 1
                        response = await asyncio.wait_for(self.client.embeddings.create(
                            model=self.model, dimensions=self.dimensions,
                            input=[value for _, value in batch]), self.timeout)
                        break
                    except Exception as exc:
                        status = getattr(exc, "status_code", None)
                        retryable = isinstance(exc, TimeoutError) or status == 429 or isinstance(status, int) and status >= 500
                        if attempt >= self.max_retries or not retryable:
                            raise
                        await asyncio.sleep(min(0.25 * 2 ** attempt, 2))
            self.tokens += getattr(getattr(response, "usage", None), "total_tokens", 0)
            vectors: list[list[float] | None] = [None] * len(batch)
            for item in response.data:
                if not isinstance(item.index, int) or not 0 <= item.index < len(batch):
                    raise ValueError("embedding response contains invalid index")
                vector = list(item.embedding)
                if len(vector) != self.dimensions:
                    raise ValueError("embedding dimensions do not match configuration")
                vectors[item.index] = vector
            if any(vector is None for vector in vectors):
                raise ValueError("embedding response is incomplete")
            return [(batch[i][0], vector) for i, vector in enumerate(vectors) if vector is not None]

        batches = [items[offset:offset + batch_size] for offset in range(0, len(items), batch_size)]
        fetched = await asyncio.gather(*(fetch(batch) for batch in batches))
        by_key = {key: vector for batch in fetched for key, vector in batch}
        for i, key in enumerate(keys):
            if results[i] is None:
                results[i] = by_key[key]
                if self.cache: self.cache.set(key, by_key[key])
        if any(value is None or len(value) != self.dimensions for value in results):
            raise ValueError("cached or returned embedding has wrong dimensions")
        return [value for value in results if value is not None]
