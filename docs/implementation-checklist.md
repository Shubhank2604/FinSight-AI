# Engineering completion checklist

Baseline: `e8b7e0a17e7e84d8ec4165d65edeb1e28616b115`. On 2026-10-04 the clean local checkout matched GitHub master; dev was merged. Baseline: 32 tests; 18-query retrieval Recall@3 BM25 1.000, hash/hybrid 0.944; 11-case abstention recall 0.8571. Historical artifacts remain identifiable. Work is on `engineering/interview-readiness`; the initial core commit is `6009ee2`.

## Implemented and verified offline

- [x] Sections 1-2: inspect repository, reproduce failures/baseline, dedicated branch.
- [x] Section 3: typed money/rate/duration inputs, provenance, clarification, currency specificity, supported conventions, nonfinite/unsupported-feature rejection.
- [x] Section 4: action/evidence separation, explicit web permission, document grounding, 100-case router confusion matrix.
- [x] Sections 5-6: authoritative claims/tool display; mandatory gates; all references; full evidence; currency/scale/sign/rate/rounding/metric/company/period checks and regressions. General entailment is unproven.
- [x] Section 7: document EMI, current ratio, net/operating margin, debt-to-equity and year-over-year revenue growth; formulas and chunk/page/unit provenance; precedence/conflicts.
- [x] Section 8: scope before ranking, isolated vector spaces/catalogs, atomic writes, journal recovery, Qdrant reconstruction, duplicate/replacement/delete/rebuild/lock tests.
- [x] Section 9: typed recoverable failures, independent deterministic calculations, no fabricated grounded fallback, UI pending cleanup.
- [x] Section 10: reachable forms, readable citations, inputs/results/assumptions, selection/removal, expandable diagnostics; queries explicitly independent.
- [x] Section 11 implementation: PDF-page rendering, stable image IDs, validated bytes, preserved web annotations/source metadata. UI vision remains unsupported experimental; web output is experimental.
- [x] Sections 12-13 offline: 12 authored redistributable PDFs, 120 questions, company-level held-out split frozen before tuning, correctness/coverage/abstention/context/ranking/latency reporting and useful-answer CI gates.
- [x] Section 14: modular orchestration, closed-form options math, dependency lock, upload sanitation, five-scenario demo and documentation. Python 3.13.9 Windows is locally verified; Linux CI is configured, not claimed executed.
- [x] Section 15 artifacts: architecture explanation, two-minute walkthrough, interview Q&A, claim/evidence table; no finalized resume bullets.
- [x] OpenAI verification: main `.venv` repaired using lock; 148 tests in the clean locked environment and `pip check` pass; all three live acceptance probes pass. Reporting years, ratio suffixes and quoted inputs pass; wrong periods, ratios, amounts and currencies fail.

## Live evidence and remaining work

- [x] OpenAI screenshot/chart/table and explicit web probes returned outputs; annotations retained. These small adapter probes are excluded from verified performance and do not establish general support or freshness.
- [x] Completed repeated OpenAI application evaluation (360/360 cases, 354 correct; 138 schema-valid API responses, no quota failures): `python -m evaluation.application --live --mode hybrid --repeats 3 --output evals/results/application-openai-live-verified.json`. Records, missing requests and repeat variability are checkpointed.
- [x] Genuine semantic comparison completed with optional OpenAI text-embedding-3-small, 768 dimensions in a separate index. BM25/dense/hybrid Recall@3: 0.558/0.834/0.599; all supplied sufficient final context for deterministic answers. Default hash retrieval remains unchanged. Historical Gemini quota failures are retained.
- [ ] Independent label review and representative real filings are needed for broad accuracy claims. Fixtures/labels are agent-authored; human review cannot be manufactured.

## Irrelevant, misleading or qualified requirements

- The tax demo pack is excluded from real estimates. Jurisdiction/year rules need a supplied, reviewed pack; general real-world tax coverage is outside the verified document core.
- Conversation memory is not implemented: the allowed independent-request alternative is explicit in the interface.
- Dataset counts and perfect synthetic scores do not demonstrate production accuracy. Repeated templates and deterministic calculations make this benchmark easier than arbitrary filings.
- Matching citations/numbers does not prove arbitrary prose entailment. A wrong-but-valid nonnumeric historical citation remains a documented limitation.
- No GPU, large local model, deployment, trading execution, invented costs or fabricated review is necessary for this task.
- Configured remote CI is not evidence of a successful remote run. No deployment or GitHub publication is claimed.

The implementation is reviewable for interviews under these boundaries. Full completion of evaluation/review requirements remains conditional on unchecked items; do not claim unrestricted interview readiness or production verification.
