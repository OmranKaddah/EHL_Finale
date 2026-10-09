# 15-minute challenge setup

1. Copy `.env.example` to `.env`, set `OPENAI_API_KEY`, and load it with `set -a; source .env; set +a`.
2. Define the target output as a JSON Schema object in `examples/schemas/`, or add a Pydantic model to `schemas.py` and register it in `BUILTIN_SCHEMAS`.
3. Pick `--backend llm` for arbitrary nested outputs. For local text entities, install `.[local]`, use `--parser docling --backend gliner`, and keep fields to strings or string lists.
   For CSV/XLSX use `--parser tabular --parse-first`; install `.[office]` for XLSX.
4. Set `JOB_TIMEOUT_SECONDS` and `WINDOW_DURATION_SECONDS`. Create `ProcessingRequest` instances with UTC deadlines. Choose `JobProcessor(policy="edf")` for deadline ordering.
5. Skip retrieval unless the task needs reference documents. To enable it, set `TYPESENSE_API_KEY`, run `docker compose up -d`, then use `hackkit index ...` and `hackkit search ...`.
6. Define a workflow with `Step(name, worker, depends_on=...)` and call `run_workflow`. The worker receives prior step results in a state dictionary.
7. Choose `LocalSubmitter` for local output or `HTTPSubmitter` for a challenge endpoint. Configure its URL and token at runtime; use a stable job ID as the idempotency key.
8. Run `hackkit benchmark --format markdown` to get a measured local baseline. Replace mocked delay and synthetic arrivals with challenge traffic before making performance claims.

Fastest document-to-JSON path:

```bash
hackkit extract examples/documents/technical_spec.txt --schema examples/schemas/simple_technical.json
```

This direct path makes one model call. It sends the document to OpenAI. For confidential documents, use the local Docling and GLiNER path.
