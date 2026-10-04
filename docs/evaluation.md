# Evaluation methodology

FinSight separates retrieval evaluation from answer-generation evaluation. This first benchmark measures whether the system retrieves the evidence needed to answer a question; it does not claim that a retrieved passage guarantees a correct final answer.

## Benchmark design

`evals/retrieval_benchmark.json` contains 18 synthetic financial passages and 18 query/relevance labels (independent human review is not established by the retained manifest). The cases span:

- company risk factors, segment results, and liquidity;
- brokerage allocation, fees, and tax lots;
- retirement-account and tax-credit rules;
- investor-presentation growth, margins, and supply constraints;
- mortgage resets, prepayment, and escrow; and
- withdrawal, sequence-of-returns, and inflation concepts.

The corpus is synthetic so the benchmark is small, redistributable, stable, and free of private financial documents. Every relevant ID is validated against the corpus before a run. Chunk IDs must be unique UUIDs, and case IDs must also be unique.

## Compared retrieval modes

The same production `HybridRetriever` is evaluated in three modes:

| Mode | Implementation | Purpose |
| --- | --- | --- |
| Dense | Qdrant cosine search with local hash vectors | Credential-free proxy for vector retrieval |
| Sparse | BM25 keyword retrieval | Exact-term and finance-vocabulary baseline |
| Hybrid | Reciprocal Rank Fusion over dense and sparse results | Current production fusion strategy |

Local hash embeddings are deterministic and useful for CI, but they are not a substitute for a semantic embedding model. A Gemini-embedding benchmark must be reported separately because it requires credentials, incurs cost, and may change across model versions.

## Metrics

- **Precision@K:** relevant chunks divided by K.
- **Recall@K:** labeled relevant chunks recovered in the first K results.
- **Hit rate@K:** fraction of cases with at least one relevant result.
- **MRR@K:** mean reciprocal rank of the first relevant result.
- **nDCG@K:** ranking quality with higher credit for relevant evidence near the top.
- **p50/p95 latency:** local wall-clock retrieval latency. These numbers are environment-specific and should not be treated as production service-level objectives.

## Version 1.0 baseline

The checked-in baseline uses K=3, Python 3.12, local hash embeddings, and no network access.

| Mode | Precision@3 | Recall@3 | Hit rate@3 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense | 0.315 | 0.944 | 0.944 | 0.861 | 0.883 |
| Sparse | 0.333 | 1.000 | 1.000 | 0.972 | 0.979 |
| Hybrid | 0.315 | 0.944 | 0.944 | 0.889 | 0.903 |

BM25 wins this deliberately lexical benchmark. Dense and hybrid retrieval both miss the brokerage-allocation case at K=3. That result is retained rather than hidden: it shows that reciprocal-rank fusion is not automatically better and that a weak local vector representation can lower hybrid recall.

CI requires hybrid Recall@3 of at least 0.90. This is a regression guard, not a claim of production accuracy.

## Reproduce

```bash
python eval_retrieval.py \
  --top-k 3 \
  --output evals/results/latest.json \
  --min-hybrid-recall 0.90
```

The JSON report includes aggregate metrics, per-case rankings, relevance labels, latency, dataset version, runtime, and embedding-provider metadata.

## Claim/citation linkage baseline

`evals/citation_benchmark.json` contains 11 structured-answer cases. It covers correct citations, unknown IDs, missing claim citations, partially cited answers, explicit missing-data signals, extraneous IDs, a wrong numerical citation, and a wrong nonnumeric citation.

| Metric | Baseline |
| --- | ---: |
| Citation precision | 0.692 |
| Citation recall | 0.600 |
| Abstention precision | 1.000 |
| Abstention recall | 0.857 |
| Accept/abstain accuracy | 0.909 |

The verifier rejects claims with missing or unknown citation IDs. For retrieval-only answers, it also rejects a claim when its explicit numbers are absent from the cited evidence. This catches the numerical mismatch case without an LLM or external service.

It still accepts `wrong-valid-nonnumeric-citation` because the cited chunk exists and the claim contains no deterministic numeric contradiction. That failure is retained deliberately: the current layer validates citation linkage and numerical consistency, not semantic entailment.

Reproduce it without credentials:

```bash
python eval_citations.py \
  --min-abstention-recall 0.85 \
  --output evals/results/citation_baseline.json
```

## Next evaluation layers

1. Add a licensed or authored real-document corpus with independently reviewed labels.
2. Compare local hash, Gemini embeddings, and additional embedding models under the same cases.
3. Add claim-level entailment scoring and independently reviewed support labels.
4. Track token usage, provider cost, end-to-end latency, and model/version metadata.
5. Split benchmark development and held-out test cases before tuning retrieval parameters.

## OpenAI migration evidence

New reports contain `openai` provider identity and the actual response model, prompt version, latency, token usage, schema validation and application validation separately. Files named `application-openai-*`, `experimental-openai-*` and `provider-openai-*` belong to this migration. Existing Gemini live, semantic retrieval, experimental and replay reports remain historical and are not relabeled. Offline SDK transport tests are not live calls.

The application runner checkpoints each finished request before checking provider failure. `missing_requests` lists every unrun case/mode/repeat; `repeat_status` distinguishes complete, partial and not-run repeats. Missing repeat scores are null. `completed_cases` includes finished requests with failures; successful OpenAI calls are counted separately. A missing key produces zero requests, explicit blocked configuration and a nonzero live CLI exit. Provider failure stops the run, retains the failed request and all earlier records, and exits nonzero. No provider failure can silently turn an incomplete run into a successful quality gate.

The production calculation routes use deterministic Python without LLM calls. `evaluation.provider_checks` additionally tests document-backed calculation explanations against immutable tool values; that isolated probe is not evidence that production arithmetic uses a model. See [the migration guide](openai-migration.md) for exact live commands and remaining experimental work.

## Completed application and semantic evaluations (2026-10-04)

The actual PDF application dataset contains 12 agent-authored CC0 fixtures and 120 questions: eight development companies (80 cases), four held-out companies (40 cases), frozen before tuning. Synthetic labels are not independently human-reviewed. Answer correctness checks expected supported currency/value or expected abstention; it does not score general nonnumeric truth.

`application-final-offline.json`: 120 cases in each BM25/hash dense/hybrid mode, all correct, answerable coverage 1.0, unsupported acceptance 0.0. Deterministic typed extraction and calculation bypass generation.

`application-openai-live-verified.json`: 360 requests across three repeats, all completed; 138 schema-valid OpenAI responses, 164,588 reported generation tokens. Correctness 354/360 (98.33%); answerable coverage 306/312 (98.08%); unsupported acceptance 0/48. All 120 held-out repeat slots were correct. Repeat correctness: 96.67%, 100%, 98.33%. Six false abstentions are retained: incomplete units, malformed references, multi-period narrative checks and answer/claim disagreement. Schema-valid output is not automatically financially accepted. Provider response latency p50 1,109.362 ms, empirical p95 1,470.239 ms; mean across all application cases was 450.673 ms, including cheap deterministic routes. Costs remain unknown.

`application-openai-semantic.json`: genuine text-embedding-3-small embeddings, 768 dimensions, same PDFs/questions/source scope, BM25/dense/hybrid comparison. Eight embedding requests, 6,081 reported embedding tokens, 8,389.986 ms total embedding-call wall time. Generation is disabled for this comparison; downstream answers are deterministic. Recall@3: 0.557692/0.834135/0.598558; MRR@3: 0.926282/0.980769/0.995192; nDCG@3: 0.650074/0.869522/0.723012. Dense retrieves more labeled relevant chunks than hybrid on this corpus; fusion is not assumed better. All modes have final required-page context coverage and downstream correctness 1.0. Query vectors are precomputed and cached; reported retrieval/request latency excludes embedding preparation. Context selection uses more than the three ranking positions scored, so final coverage can exceed Recall@3.

Relevance labels treat all text/table chunks on required pages as relevant, including duplicate representations. Page coverage is coarse; it is not claim entailment. The lexical, templated corpus cannot establish ranking gains on arbitrary filings. Independently reviewed support labels and real documents remain outstanding.

Reports record dataset/code digests, revisions, dependencies, provider/model/index/prompt identity, raw generation output, traces and decisions. The live report precedes the optional semantic adapter addition; its own code digest identifies the tested state. Historical Gemini quota runs and missing-key OpenAI reports are retained as historical failures rather than overwritten.
