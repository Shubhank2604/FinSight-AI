# OpenAI provider runbook

OpenAI is the sole generation provider. Retrieval, financial extraction, arithmetic,
provenance and final verification remain independent of generation. Offline
retrieval and calculators work without credentials. Historical migration and repair
measurements are retained in [verification](verification.md) and the
[evidence index](../evals/results/evidence-index.json).

## Configure generation

Use Python 3.13 and install `requirements.lock`. Create a private `.env` from
`.env.example` only if one does not already exist. Keep existing credentials and
uploads. Configuration representations omit keys; provider errors are sanitized.

| Setting | Default / purpose |
|---|---|
| `OPENAI_API_KEY` | Required only for final answer generation |
| `OPENAI_MODEL` | `gpt-5.4-mini-2026-03-17` |
| `OPENAI_VISION_MODEL` | Blank inherits the text model |
| `OPENAI_EVAL_MODEL` | Blank inherits the text model; evaluation honors this override |
| `OPENAI_TIMEOUT` | 30 seconds per attempt; positive, finite, at most 120 |
| `OPENAI_MAX_RETRIES` | 2; supported range 0-3 |
| `OPENAI_MAX_OUTPUT_TOKENS` | 4096; supported range 128-16384 |
| `OPENAI_WEB_ENABLED` | `false`; only literal true/false accepted |
| `EMBEDDING_PROVIDER` | `minilm`; explicit offline `local_hash` |
| `LOCAL_EMBEDDING_CACHE` | `data/models/minilm`; ignored pinned CPU model cache |

The supported alternative generation profile is `gpt-4.1-mini` or its
`gpt-4.1-mini-2025-04-14` snapshot. Its FinSight answer quality is unmeasured.
The default profile sends `reasoning.effort=none`; the alternative omits reasoning.
Neither profile sends temperature. Other models require an explicitly validated
profile. There is no automatic model or provider fallback. Availability and quota
are checked by requests, not inferred from a model listing.

## Adapter and verification

`openai_client.py` is the official SDK Responses boundary. It submits strict JSON
schemas and validates output against both the wire schema and Pydantic contracts.
Missing fields, unexpected fields, empty answers, refusals and incomplete responses
fail explicitly. Schema validity alone does not establish financial correctness.
Document facts must still pass the evidence verifier; calculation routes render
unchanged deterministic results.

Retries cover transient connection, timeout, 408/409/429 and server failures.
SDK generation retries are disabled to prevent nested loops. Authentication,
permission, insufficient quota and invalid requests fail without retrying. Waits
are bounded at four seconds. Diagnostics preserve available usage, total latency,
attempts, requested/actual model and response ID. Failed requests may incur usage
that the provider did not report.

## Select an embedding space

`minilm` is the supported app and index CLI default. It runs
`sentence-transformers/all-MiniLM-L6-v2` locally through ONNX Runtime on CPU,
with 384 dimensions and no embedding API requests. Its pinned model revision,
256-token window limit and weighted window pooling are part of the collection
identity. The first download fetches public model/tokenizer artifacts into
`LOCAL_EMBEDDING_CACHE`; it never uploads document text. Cached inference works
offline. `local_hash` remains a credential-free regression baseline.

OpenAI is used only for final answer generation in the app. Indexing, semantic
retrieval, BM25, fusion and reranking are local. The app rejects cloud embedding
settings. Legacy cloud adapters are retained only for explicitly requested
historical evaluations; their existing collections are preserved and never mixed
with MiniLM vectors.

Changing embedding models creates a separate collection and requires re-indexing.
Upload the documents again to populate the new MiniLM collection; originals and
prior collections are preserved. Do not automatically restore files merely because
an old upload copy exists, since users may previously have removed its indexed
evidence. Stop the app before CLI indexing because local Qdrant has one owner.
Changing the OpenAI generation model does not re-embed documents.

## Experimental vision and web

Vision validates local image bytes and preserves chunk/page identifiers. The
adapter and probe runner support it; ordinary UI visual answers remain unsupported.
Web requires `OPENAI_WEB_ENABLED=true`, request-level opt-in.
It preserves URL annotations, consulted sources and retrieval timestamps.
Retrieval time does not establish publication date or freshness.

Retained historical probes include screenshot/table/chart readings and a web
response. They do not establish representative visual accuracy or claim-to-source
entailment. Both paths remain experimental and excluded from verified-answer
metrics. Tax remains disabled pending reviewed rule packs.

## Verification and cost controls

Use the [README offline commands](../README.md#reproduce-the-evidence) for routine
checks. No paid evaluation is required for startup, the demo or CI. Report outputs
belong in ignored `.test-tmp`; immutable delivery evidence retains its original
source identity.

Live evaluation requires an explicit authorized cap and a shared persisted ledger.
Do not reset the ledger to bypass that cap. Restarting repeats requests rather
than resuming skipped slots. Failed calls retain conservative reservations;
estimates are not invoices. Final historical repair measurements, limitations and
the ledger snapshot are in [verification](verification.md).

For adapter reference, see official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[embeddings](https://developers.openai.com/api/docs/guides/embeddings),
[vision](https://developers.openai.com/api/docs/guides/images-vision) and
[web search](https://developers.openai.com/api/docs/guides/tools-web-search) guidance.
