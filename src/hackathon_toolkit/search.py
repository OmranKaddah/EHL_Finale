from __future__ import annotations

import json
from typing import Any, Literal
from urllib.parse import quote

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
from pydantic import BaseModel

from .models import DocumentChunk


class SearchHit(BaseModel):
    chunk: DocumentChunk
    score: float | None = None


class TypesenseSearch:
    def __init__(self, *, host: str = "localhost", port: int = 8108, protocol: str = "http",
                 api_key: str, collection: str = "document_chunks_v1", dimensions: int = 1536,
                 embedding_model: str = "text-embedding-3-small", client: httpx.AsyncClient | None = None,
                 embedder=None):
        self.url = f"{protocol}://{host}:{port}"
        self.key, self.collection = api_key, collection
        self.dimensions, self.embedding_model = dimensions, embedding_model
        self.client, self.embedder = client, embedder

    def schema(self) -> dict[str, Any]:
        return {"name": self.collection, "fields": [
            {"name": "id", "type": "string"}, {"name": "document_id", "type": "string", "facet": True},
            {"name": "text", "type": "string"}, {"name": "filename", "type": "string"},
            {"name": "document_type", "type": "string", "facet": True},
            {"name": "title", "type": "string", "optional": True},
            {"name": "section", "type": "string", "optional": True, "facet": True},
            {"name": "page", "type": "int32", "optional": True},
            {"name": "embedding", "type": "float[]", "num_dim": self.dimensions, "optional": True},
            {"name": "embedding_model", "type": "string", "optional": True},
            {"name": "embedding_dimensions", "type": "int32", "optional": True},
        ]}

    async def health(self) -> bool:
        import httpx
        try:
            return bool((await self._request("GET", "/health")).json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        import httpx
        if not self.key: raise ValueError("TYPESENSE_API_KEY is required")
        client = self.client or httpx.AsyncClient(timeout=30)
        try:
            headers = {"X-TYPESENSE-API-KEY": self.key, **kwargs.pop("headers", {})}
            response = await client.request(method, self.url + path, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        finally:
            if self.client is None: await client.aclose()

    async def ensure_collection(self) -> None:
        import httpx
        path = f"/collections/{quote(self.collection)}"
        try:
            existing = (await self._request("GET", path)).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404: raise
            await self._request("POST", "/collections", json=self.schema())
            return
        expected = {f["name"]: f for f in self.schema()["fields"]}
        fields = {f["name"]: f for f in existing["fields"]}
        if fields.get("embedding", {}).get("num_dim") != self.dimensions or any(name not in fields for name in expected):
            raise ValueError("Typesense schema mismatch; create a versioned collection and reindex")

    async def index(self, chunks: list[DocumentChunk], *, vectors: list[list[float]] | None = None) -> None:
        if vectors is not None and len(vectors) != len(chunks): raise ValueError("vector count mismatch")
        lines = []
        for i, chunk in enumerate(chunks):
            record = chunk.model_dump(exclude={"metadata"}, exclude_none=True)
            if vectors is not None:
                if len(vectors[i]) != self.dimensions: raise ValueError("embedding dimension mismatch")
                record.update(embedding=vectors[i], embedding_model=self.embedding_model,
                              embedding_dimensions=self.dimensions)
            lines.append(json.dumps(record))
        if not lines: return
        response = await self._request("POST", f"/collections/{quote(self.collection)}/documents/import",
            params={"action": "upsert"}, content="\n".join(lines),
            headers={"content-type": "text/plain"})
        failures = [row for row in response.text.splitlines() if not json.loads(row).get("success")]
        if failures: raise RuntimeError(f"Typesense rejected {len(failures)} documents: {failures[0][:200]}")

    async def delete(self, chunk_id: str) -> None:
        await self._request("DELETE", f"/collections/{quote(self.collection)}/documents/{quote(chunk_id)}")

    async def search(self, query: str, *, mode: Literal["keyword", "vector", "hybrid"] = "hybrid",
                     filters: dict[str, str] | None = None, top_k: int = 5, alpha: float = 0.3) -> list[SearchHit]:
        if mode not in {"keyword", "vector", "hybrid"}: raise ValueError("invalid search mode")
        params: dict[str, Any] = {"q": query if mode != "vector" else "*", "query_by": "text,title,filename",
                                  "per_page": top_k}
        if mode != "keyword":
            if self.embedder is None: raise ValueError("vector search requires an embedding service")
            if (self.embedder.model, self.embedder.dimensions) != (self.embedding_model, self.dimensions):
                raise ValueError("query embedding configuration differs from index")
            vector = (await self.embedder.embed([query]))[0]
            params["vector_query"] = f"embedding:([{','.join(map(str, vector))}], k:{top_k}, alpha:{alpha})"
            if mode == "hybrid": params["drop_tokens_threshold"] = 0
        if filters:
            allowed = {"document_type", "document_id", "section", "filename"}
            if set(filters) - allowed: raise ValueError("unsupported filter field")
            params["filter_by"] = " && ".join(f"{key}:={json.dumps(value)}" for key, value in filters.items())
        result = (await self._request("GET", f"/collections/{quote(self.collection)}/documents/search", params=params)).json()
        return [SearchHit(chunk=DocumentChunk.model_validate({k: v for k, v in hit["document"].items()
                           if k not in {"embedding", "embedding_model", "embedding_dimensions"}}),
                           score=hit.get("hybrid_search_info", {}).get("rank_fusion_score") or hit.get("text_match"))
                for hit in result.get("hits", [])]
