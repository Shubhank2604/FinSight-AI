# OpenAI LLM migration

Generation is migrated to the official OpenAI Python SDK and Responses API. There is no Gemini generation fallback. Financial extraction, arithmetic, citations, numerical checks, input provenance and authoritative tool rendering remain deterministic. Historical evaluation records are preserved.

## Configuration and model decision

Use Python 3.13 and install `requirements.lock`. Copy `.env.example` to `.env` only when creating a new environment; keep an existing `.env` and add the OpenAI settings locally. Store credentials in `OPENAI_API_KEY`, never in source control. Settings representations omit credentials and provider exception bodies are never displayed or recorded.

| Setting | Default / purpose |
|---|---|
| `OPENAI_API_KEY` | Required for live generation; offline retrieval/tools work without it |
| `OPENAI_MODEL` | `gpt-5.4-mini-2026-03-17` |
| `OPENAI_VISION_MODEL` | Blank inherits the text model |
| `OPENAI_EVAL_MODEL` | Blank inherits the text model; evaluation runners honor this override |
| `OPENAI_TIMEOUT` | 30 seconds per attempt; finite, positive, at most 120 |
| `OPENAI_MAX_RETRIES` | 2 retries; supported range 0â€“3 |
| `OPENAI_MAX_OUTPUT_TOKENS` | 4096; supported range 128â€“16384 |
| `OPENAI_WEB_ENABLED` | `false`; only literal true/false accepted |
| `EMBEDDING_PROVIDER` | Existing `local_hash` default is preserved |

The default is pinned for repeatable evaluation. GPT-5.4 mini is documented as a faster, more efficient small model with text/image input, Responses, Structured Outputs and web search. Standard text pricing is $0.75 per million input tokens, $0.075 cached input and $4.50 output. A hypothetical 5,000 input / 500 output request costs about $0.006 before images or tool fees; this is an estimate, not measured spend. `reasoning.effort=none` keeps development overhead low; no temperature parameter is sent. These capabilities and the snapshot were checked against [official model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini) on 2026-10-04. Latency and FinSight answer quality must still be measured live.

The optional supported alternative is `gpt-4.1-mini` or its `gpt-4.1-mini-2025-04-14` snapshot. It offers lower text prices ($0.40 input, $0.10 cached, $1.60 output per million tokens), image input and Structured Outputs without a reasoning step. Its quality for these financial prompts is unmeasured. The adapter omits reasoning parameters for this profile. [Official model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

Only these verified profiles are accepted. Other models require adding a profile after checking current capabilities and running the same acceptance checks. Documentation listing a model does not establish your project's access or quota. Authentication, permission, model availability and unsupported request errors are explicit. There is no automatic provider or model fallback.

## Adapter and validation

`openai_client.py` builds Responses requests behind one SDK boundary. Pydantic schemas become strict JSON schemas: all fields are required, object extras are forbidden, and schema defaults are removed. Responses are locally validated against both the submitted strict JSON schema and the existing Pydantic contracts; missing fields and unexpected fields are rejected even when Pydantic defaults could accept them. Grounded generation, educational generation, generic structured extraction, vision and web all use this adapter. [Official Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

Refusals, incomplete/failed responses, empty output and schema failures are separate failure codes. The adapter retries timeouts, connection errors, 408/409/429 and server errors with bounded exponential backoff. SDK retries are disabled to prevent nested retry loops. Insufficient quota, authentication, permission and invalid settings are not retried. Retry waits are at most four seconds. Token usage and latency include available response usage and all attempt/wait time; timed-out responses may have incurred unreported provider usage.

Schema validity is recorded separately from financial validity. Generated document claims still pass citation, number/unit/period/entity, page metadata and answer/claim consistency checks before display. General semantic entailment remains unproven. Production calculation routes directly render deterministic tool outputs; an LLM cannot supply replacement arithmetic. The small acceptance runner separately checks generated calculation explanations against unchanged results.

## Vision and web

Vision sends validated local image bytes as `input_image` data URLs. Each image carries its existing document chunk/page identifier when available, otherwise a stable SHA-256 identifier. Missing, corrupt, unsupported or oversized images fail before submission. Selected PDF pages can be rendered using the existing ingestion utility. [Official vision guidance](https://developers.openai.com/api/docs/guides/images-vision).

Web uses the Responses `web_search` tool with required tool use, explicit external access, a bounded tool-call budget and `web_search_call.action.sources` inclusion. URL/title/annotation spans, consulted source metadata and retrieval timestamps are preserved. Retrieval time is never treated as publication time. Annotated response text and source links are visible in the UI. Web needs both environment enablement and request-level opt-in plus OpenAI generation selection. Uploaded-document routes never silently use web evidence. [Official web-search guidance](https://developers.openai.com/api/docs/guides/tools-web-search).

Both capabilities are **experimental**. The UI returns an explicit experimental status for web output, excluded from verified-answer metrics. Visual generation is available through the adapter/probe runner; the ordinary UI visual-answer route still reports unsupported experimental capability. Remaining work: run image screenshot/table/chart probes with credentials, review numerical readings against visible evidence, assess representative PDF pages, run web probes and inspect source dates/claim-to-source support, then define acceptance gates before enabling verified vision/web answers. Annotation preservation is not factual or freshness verification.

Web search costs $10 per thousand calls plus search-content tokens at the selected model's rates. GPT-4.1 mini search-content tokens have an 8,000-token minimum block per call. Prices are documentation-based estimates; reports record actual tokens and keep invoice cost unknown. [Official pricing](https://developers.openai.com/api/docs/pricing).

## Embeddings remain separate

`embeddings.py` keeps the local hash algorithm, dimensions and index identity unchanged. Existing semantic indexes still use `gemini-embedding-001`, configured through `GEMINI_EMBEDDING_MODEL` and `GEMINI_API_KEY`. To retain them, install `requirements-embeddings.txt` in addition to the default lock. Google libraries are imported only for embedding requests; no Gemini generation code remains.

The default `.env.example` and active `.env` contain only OpenAI generation and local retrieval settings. Previous local Gemini settings are preserved in the ignored `.env.gemini-embeddings` backup, which is never loaded automatically. To explicitly retain a Gemini embedding index, restore the two embedding-related variables to `.env` and set `EMBEDDING_PROVIDER=gemini`; the historical text/web model settings are obsolete.

An embedding migration must select and evaluate an embedding model, create a new provider/model/dimension/ingestion identity and separate compatible collection, re-ingest/re-embed every document, and run dense/hybrid retrieval evaluation against the same split labels. Compare ranking, evidence coverage and downstream answers before switching active retrieval. Retain the old collection for rollback. Never insert new-space vectors into a Gemini or hash collection; changing dimensions alone does not make spaces compatible. The generation migration initially introduced no embedding model; the verification follow-up adds an optional OpenAI space as described below.

## Exact verification commands

Offline checks need no API key:

```powershell
python -m pip install -r requirements.lock
python -m pip check
python -m pytest -q -p no:cacheprovider --basetemp=.test-tmp/openai-check
python -m evaluation.application --quality-gate --output evals/results/application-openai-offline.json.gz
python -m evaluation.experimental --output evals/results/experimental-openai-offline.json.gz
```

Configure `OPENAI_API_KEY` privately. Current bounded live commands and shared-ledger
rules are in the README. Paid vision/web are outside the repair budget and remain
experimental. Historical measurements below retain their original scorer and date.

## Delivery status and live follow-up

The initial migration passed 132 offline tests and recorded missing-key live reports. Those artifacts remain historical. After local credentials became available, the main `.venv` was repaired using the lock and the clean locked environment passed **148 tests** (`evals/results/openai-final-clean-tests.xml`). Both environments pass `pip check`; final router/offline application gates pass. The default verification environment has no Google SDK.

`provider-openai-final.json.gz` records all three live acceptance probes passing. The first probes revealed a local verifier bug: a correct reporting year was compared to numerical tool results, and quoted document inputs were treated as replacement arithmetic. The verifier now recognizes exact tool periods, parses ratio suffixes and permits provenance-backed monetary inputs. Regression tests reject incorrect years, ratios, amounts and currencies. Production tool values remain unchanged.

`application-openai-live-verified.json.gz` completed all 360 cases across three repeats: 354 correct (98.33%), 98.08% answerable coverage, zero unsupported acceptance under synthetic labels, six false abstentions, no quota failures. There were 138 schema-valid API responses; remaining routes were deterministic or abstained before generation. Repeats scored 96.67%, 100%, 98.33%. The held-out subset completed 120 repeat slots, all correct. No independent human review or general accuracy claim is implied.

`experimental-openai-web-verified.json.gz` preserves three actual image responses and an explicitly enabled web response with source annotations. The image fixtures show screenshot/chart/table revenue of USD 120 million in 2025; all returned that amount. These are small adapter probes, not representative financial-PDF validation. The web probe preserves its dated Federal Reserve source; general latest-source coverage, publication-date verification and claim entailment remain unproven. Both paths remain experimental.

## Optional OpenAI semantic embeddings

The follow-up adds `EMBEDDING_PROVIDER=openai` and `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`. Default local hash retrieval and the active `.env` are unchanged. OpenAI's third-generation embeddings support an explicit `dimensions` parameter; FinSight requests 768 dimensions through the official SDK. See [official embedding guidance](https://developers.openai.com/api/docs/guides/embeddings).

This provider uses a separate collection identity containing openai/model/dimensions/ingestion version. Re-ingest every document into that collection; never copy old-space vectors. Existing hash and Gemini collections remain for rollback. A generation model change does not change this identity. Embedding calls preserve usage/latency separately from generation, sanitize provider errors and use the SDK's bounded retries; generation retains its own retry policy.

```powershell
python -m evaluation.application --embedding-provider openai --quality-gate --output evals/results/application-openai-semantic.json.gz
python index_uploads.py --folder evals/fixtures --embedding-provider openai
```

The comparison completed 120 questions in each BM25/dense/hybrid mode with deterministic downstream answers: all correct with full final evidence coverage. Recall@3 was 0.558/0.834/0.599. Dense outperformed hybrid on relevant-chunk recall; these results do not justify claiming hybrid always improves retrieval. Eight embedding requests consumed 6,081 reported tokens; no invoice cost is inferred. Default retrieval remains hash until explicitly selected. Full OpenAI generation with semantic embeddings is a separate evaluation configuration; the repeated live report used hash embeddings.

See [evaluation](evaluation.md), [verification summary](verification.md) and [completion checklist](implementation-checklist.md) for exact measurements and remaining independent-review limitations.


## Complete-repair verification

The repair evaluation uses `evals/repair_v3/application.json`, the independent bound-label scorer, and a persisted $2 estimated spend ledger shared by application and acceptance runs. Budgeted calls exclude vision and web. Failed calls retain their conservative reservations; estimates are not provider invoices. See [verification](verification.md) for final measurements. Historical OpenAI results above retain their original scorer and date.

```powershell
python -m evaluation.application --live --embedding-provider openai --mode hybrid --repeats 3 --budget-usd 2 --budget-ledger .test-tmp/openai-repair-budget.json --output .test-tmp/repair-live.json.gz --quality-gate
python -m evaluation.provider_checks --live --budget-usd 2 --budget-ledger .test-tmp/openai-repair-budget.json --output .test-tmp/repair-provider.json
```

Keep the same ledger on restart. A restart reruns requests; it does not resume checkpoints. Inspect missing slots and remaining reservations first. Do not delete/reset the ledger to bypass the authorized cap.

Final repair evidence (2026-10-05): the combined semantic-plus-generation run
completed 390 slots, with 381 correct under the frozen stronger scorer, 120
schema-valid generation responses and eight embedding requests. The source was
clean `02d6ea4`, prompt `bound-records-openai-v4`. Three final acceptance probes
passed. Earlier probe and repeated-run failures are preserved beside the final
reports; they are included in the shared $2 ledger. See verification.md for
exact costs, false abstentions, alias-format failure and CI evidence.
