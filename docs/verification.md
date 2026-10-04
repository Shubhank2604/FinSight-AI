# Verification and delivery evidence

Verified locally on 2026-10-04, Windows x64, Python 3.13.9. Branch: `engineering/interview-readiness`. Baseline commit `e8b7e0a`; initial repaired core `6009ee2`. Later migration and evaluation changes include the user's OpenAI migration, preserved and checked rather than replaced. Reports made before delivery commits record dirty state and SHA-256 code/dataset digests; those fields identify the state actually measured.

## Local and live results

| Check | Evidence | Result |
|---|---|---|
| Locked clean environment tests | `evals/results/openai-final-clean-tests.xml` | 148 passed in 11.73 seconds; provider tests use mock HTTP and are explicitly offline |
| Dependency consistency | `python -m pip check`, both `.venv` and `.venv-verify` | No broken requirements |
| Historical retrieval guard | `evals/results/retrieval-final.json` | Hybrid Recall@3 0.944; BM25 1.000; 18 synthetic queries |
| Historical citation guard | `evals/results/citations-final.json` | Abstention precision 1.000, recall 0.8571; known nonnumeric entailment failure retained |
| Router | `evals/results/router-final.json` | 100/100, confusion matrix and split/per-route scores |
| Offline actual PDF application | `evals/results/application-final-offline.json` | 360/360 correct across 120 questions in three modes; full answerable coverage; zero unsupported acceptance |
| Live OpenAI acceptance | `evals/results/provider-openai-final.json` | Grounded answer, structured extraction and calculation explanation all pass |
| Three repeated live application runs | `evals/results/application-openai-live-verified.json` | 360/360 finished; 354 correct (98.33%); 306/312 answerable accepted (98.08%); unsupported accepted 0/48 |
| Genuine semantic comparison | `evals/results/application-openai-semantic.json` | OpenAI text-embedding-3-small, 768 dimensions; BM25/dense/hybrid Recall@3 0.558/0.834/0.599; full deterministic answer/context coverage |
| Experimental adapters | `evals/results/experimental-openai-web-verified.json` | Three actual image outputs and explicit web output, source annotations retained; excluded from verified answer metrics |
| Five-scenario demo | `evals/results/demo-v2.json` | Fact, document EMI, period comparison, contradiction abstention, injected timeout |

The repeated live report used local hash retrieval: 138 schema-valid OpenAI Responses calls, 164,588 reported generation tokens. Correctness across repeats: 96.67%, 100%, 98.33%. All 120 held-out repeat slots were correct. Six answerable cases falsely abstained: incomplete units, malformed citation IDs, multi-period narrative validation and answer/claim disagreement. No quota failure occurred. Completed application slots are not all API calls, and schema validity does not imply financial acceptance.

The separate semantic run made eight embedding requests (6,081 reported tokens), with generation disabled. It uses identical PDFs, source scope and questions for all three retrieval modes. Dense had the best relevant-chunk recall; hybrid is not universally superior. Context selection considers more candidates than the scored top three, and relevance labels include text/table duplicates on required pages. Page-level coverage is a coarse metric. Embedding preparation/cache latency is reported separately from retrieval. API invoice cost remains unknown.

## Repairs found while checking the migration

The main `.venv` lacked the migrated SDK; installing `requirements.lock` repaired it. A live correct calculation explanation exposed a local verifier error: reporting years were compared to arithmetic results. The verifier now distinguishes tool periods, parses ratio suffixes, normalizes percent results, and accepts quoted monetary inputs only with recorded currency provenance. Regression cases reject wrong years, ratios, amounts and currencies. Tool values and display remain authoritative. The indexing CLI also closes storage when extraction fails so a malformed PDF cannot leave a lock behind.

An optional OpenAI embedding adapter closes the previous Gemini-quota comparison blocker. It validates count/order/dimensions/finite vectors, preserves usage/latency and sanitized provider errors, and creates isolated collection identities. The active `.env` and default hash index were preserved. Re-ingestion is required before selecting semantic retrieval; old collections remain available.

## Remaining boundaries

All new labels and fixtures are agent-authored, not independently human-reviewed. Repeated templates and controlled financial records limit generalization. Independent review and representative real filings remain outstanding for broad accuracy claims; they cannot be completed by fabricating review. General prose entailment, arbitrary tables and unconstrained financial advice are outside the verified contract. Web freshness/support and vision on representative PDF pages need stronger acceptance gates and remain experimental. Real tax rules need reviewed jurisdiction/year packs; the demo pack is excluded. Conversation queries use the allowed independent-request alternative.

Linux CI is configured; no remote run, push, deployment or production certification is claimed. Resume bullets are not finalized. See [completion checklist](implementation-checklist.md), [interview preparation](interview-preparation.md) and [provider migration](openai-migration.md).
