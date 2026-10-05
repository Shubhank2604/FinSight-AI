# Complete repair checklist

Brief: `FinSight_AI_Complete_Repair_Prompt.md`. Initial audit found local `0fb98d5`
and substantial relevant uncommitted work beyond remote `91d6f45`; 202 tests passed.
That work was preserved and completed. The archived baseline independently passed
148 tests and four old gates. Final source `02d6ea4` has 223 passing tests.
Branch: `engineering/interview-readiness`; remote default and PR target: `master`.
Report names below refer to `evals/repair_v3/results/`; test names refer to `tests/`.

| Prompt work | Fix/disposition | Test/evidence | State |
|---|---|---|---|
| 1-2: inspect/preserve/baseline | Remote fetched; private configuration/uploads preserved; archive source distinguished from ambient Git metadata | baseline-reproduction.json, baseline XML and four reports | done |
| 3: amounts/rates | Shared thousand/million/billion units; monthly rate annualized explicitly; original duration spans preserved | test_repair_contracts.py normalization positives/negatives | done |
| 4: requested metric | Operation survives routing, extraction, tool and verifier; true but unrequested facts rejected | growth regressions; test_repair_completion.py wrong metric/year/extra facts | done |
| 5: units/periods | Currency/scale inherited independently; contextual years; local header conflicts rejected | money/header/table/year-like-money tests | done |
| 6: support | Bound entity/metric/period/currency/value records; canonical facts or faithful excerpts; unsupported insolvency rejected | exact adversarial support tests; full evidence retained | done |
| 7: scorer | Independent complete labels and mutations, exact rejection statuses; historical unknowns explicit | scorer tests; historical rescore: 54 full / 174 partial / 132 unassessable | done; strict alias-format mismatch recorded |
| 8: document calculations | Compatible same-document joins, conflicts checked even beside complete scenarios; span/value provenance resolved; complete query priority | split/conflict/provenance tests; demo EMI | done |
| 9: lifecycle/retrieval | Alias policy, collisions/replacement, count/dimension/finite vector checks, journal recovery, settings isolation | lifecycle tests; interrupted deletion; semantic comparison | done; rebuild not globally atomic |
| 10: OpenAI | Official Responses SDK, strict schema, bounded observable failures/retries, shared conservative spend ledger | mock transport tests; final 3/3 acceptance; 390 combined slots | done; stochastic false abstentions remain |
| 11: UI | USD defaults, portfolio conventions, unsupported tax removed, half-prepayment/fractional duration clarify, pending clears on unexpected failures | Streamlit regressions and readable citation tests | done |
| 12: representative data | 12 frozen PDFs, 130 questions; varied synthetic values and two real CFO excerpts; checked against originals | v3 manifest, provenance README, real cases 30/30 repeat slots | counts done; broader real coverage and human review outstanding |
| 13: provenance/CI | Clean committed source before measurement, canonical hashes, separate report commit; PR #7 targeting master | remote-ci.json: 223 tests/all gates passed on Ubuntu | done |
| 14: cleanup/setup | Dead tax form removed; 36 historical identities preserved, five exact copies deduplicated; 27,164,280 bytes saved; lock installed fresh | evidence index hash roundtrips; pip check; 223 tests | done; no history rewrite |
| 15: interview demo/docs | Six scenarios including real Mint fact; architecture, two-minute walkthrough/Q&A and claim table | demo.json.gz, docs/demo.md, docs/interview-preparation.md | done; no resume bullets |
| 16: readiness | Supported core meets offline/live quality gates; current CI known; limitations retained | verification.md and evidence manifest | ready for a bounded interview demo |

Remaining work is independent human label review, a larger real-document corpus,
and measured expansion of arbitrary tables/prose. Tax rule packs and verified
vision/web remain outside the supported core. These cannot be represented as
completed simply by adding labels or code. The target count and a perfect synthetic
score would not establish general financial reliability. There is no claim of
production readiness or complete semantic entailment.
