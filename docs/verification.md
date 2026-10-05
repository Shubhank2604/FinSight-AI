# Verified repair delivery - 2026-10-05

The supported core is ready for a bounded interview demonstration. It meets the
local and remote quality gates. Broader real-document accuracy, independent human
label review, arbitrary PDF layouts and general narrative entailment remain
outstanding. Tax is disabled; vision/web are experimental. This is not production
certification or a perfect-financial-reliability claim.

## Source and reproducibility

Branch: `engineering/interview-readiness`; draft [PR #7](https://github.com/Shubhank2604/FinSight-AI/pull/7)
targets the actual default branch `master`. Relevant user work in `0fb98d5` and
uncommitted repairs was preserved. Delivery source commits:

- `f48ae5f`: complete typed financial contracts, loan provenance, lifecycle/UI regressions and safe shared API budgets.
- `496c5ae`: frozen v3 fixtures, acquisition provenance and lossless historical artifact cleanup.
- `dcf3531`: separate unitless tool explanations from document fact prompts after a retained failed live probe.
- `02d6ea4`: bind returned facts to requested metrics/years, preserve source magnitudes in prompting, and handle unexpected UI request exceptions.

Final measurements began with clean committed source
`02d6ea415c9351879c9d7c18fb84027907b4b7fd` and frozen dataset v3.0.0.
Reports delivered in `c4478e4` retain that measured source identity. The later
cleanup has a separate code digest and offline verification recorded below.

- Canonical Python code SHA-256: `d2f24a7bfa51e8c34cdc567446a7e409582ab587727993e2bf31e039d6ad48b0`.
- Canonical dataset JSON SHA-256: `510151d78ba36501b767ab2a79c6711754a8489ba87bcc6f11d11336a1c60803`.
- Dataset raw SHA-256 in these runs: `98f31b650755c251fdaa442dc49c5b93d20333b2733f89697198c02290c3a0c3`.
- Scorer: `bound-label-scorer-v3`; prompt: `bound-records-openai-v4`; ingestion: `financial-lines-v3`.
- Generation: `gpt-5.4-mini-2026-03-17`; semantic embedding: `text-embedding-3-small`, 768 dimensions.

Code hashing sorts Git-visible Python POSIX paths and hashes their names plus
UTF-8 bytes with CRLF normalized to LF. Frozen PDFs/gzip reports are binary;
manifest line endings are pinned. The evidence manifest indexes artifact hashes.
Actual dependency versions, raw outputs, citations and request telemetry are in
[the versioned reports](../evals/repair_v3/results/evidence-manifest.json).

## Actual outcomes

| Check | Result | Evidence under `evals/repair_v3/results/` |
|---|---|---|
| Archived baseline `91d6f45` | 148 tests; four old gates pass; old offline 360/360 | baseline-reproduction.json, baseline-tests.xml, baseline-*.json.gz |
| Fresh locked Windows Python 3.13.9 | 223 passed in 12.18s; pip check passes | fresh-tests.xml |
| Router v3 | 120/120 | router.json.gz |
| Historical retrieval guard | 18 cases; hybrid Recall@3 0.944444, BM25 1.0 | retrieval-guard.json.gz |
| Repaired citation guard | 11/11 decisions; abstention recall 1.0 | citation-guard.json.gz |
| Final offline application | 390/390 across 130 cases x BM25/hash dense/hybrid | application-offline.json.gz |
| Actual semantic comparison, generation off | 390/390; eight embedding requests | semantic-comparison.json.gz |
| Final live acceptance | 3/3: grounded fact, extraction, unchanged tool explanation | acceptance.json.gz |
| Combined semantic/hybrid + OpenAI generation | 381/390 (97.69%), all slots completed | application-live.json.gz |
| Final deterministic calculations | 204/204 full input/result-label matches | application-live.json.gz |
| Six-scenario demo | Four OK, one conflict abstention, one injected provider failure | demo.json.gz |
| Actual Ubuntu Python 3.13 CI | 223 passed in 7.32s; all gates and artifact publication passed | remote-ci.json |

CI was inspected, including its job steps and test log:
[successful measured-source run](https://github.com/Shubhank2604/FinSight-AI/actions/runs/37265605624).
This is an actual remote pass, not inference from a workflow file.

The old citation precision/recall labels are not a general claim-support measure:
this repaired 11-case guard reports reference precision 0.6923 and recall 0.6
while all acceptance/rejection decisions are correct. Its labels retain historical
reference-selection assumptions. Application citation/reference metrics below
use separately defined denominators.

## Final live denominators and limitations

The new manifest has 12 PDFs and 130 questions: ten varied synthetic reports plus
two government CFO excerpts from one issuer. Development has 84 cases; the
internal held-out split has 46. Labels are agent-authored/transcribed. The split
was frozen before this delivery's measurement but exposed during engineering
feedback; it is not a blind or independently human-reviewed study.

Three repeats completed 390 application slots. Only 120 were OpenAI generation
responses, all schema-valid, with 120 observed generation attempts and no provider
failure. Eight separate embedding requests reported 5,431 tokens. Generation
reported 123,777 input and 17,618 output tokens (141,395 total). The 204 accepted
calculations and early rejections bypass generation.

There were 324 expected-answerable and 66 expected-rejection slots. Accepted:
316/324 (97.53% answerable coverage), with eight false abstentions. No expected
rejection was accepted (0/66). Strict accepted fact accuracy was 111/112; tool
accuracy was 204/204. All 316 accepted outcomes had valid references and required
page citations under the coarse labels. Final required-page context coverage
was 324/324, which is not proof of complete field-level relevance.

The ninth incorrect outcome is an accepted, financially correct Harbor comparison
using the source alias `net sales` instead of the scorer's canonical `revenue`.
Its years, currency and values match. The production synonym parser permits this
alias; the frozen independent scorer does not. It remains counted incorrect,
with raw output retained. The scorer was not loosened after seeing the run.
`numerical_accuracy_on_accepted` is a legacy field name derived from the whole
outcome score (315/316), so format failures can reduce it; it is not an isolated
arithmetic test. Both this mismatch and the false abstentions remain limitations.

Repeat correctness: 128/130, 128/130, 125/130 (98.46%, 98.46%, 96.15%). Internal
held-out correctness: 135/138 (97.83%); coverage 90/93. Real excerpt cases: 30/30
repeat slots, comprising only six positive real fact responses and 24 rejection
slots. Do not describe that as 30 successful real-document generations.

Generation-stage latency p50/p95: 1,157.94/1,757.17 ms over 120 calls. All-slot
latency p50/p95: 10.11/1,465.58 ms over 390 slots. Cached retrieval p50/p95:
3.85/5.14 ms over 378 retrieval stages. Query/index embedding preparation is
outside these timings and retained separately in embedding telemetry.

## Retrieval comparison and historical results

| Mode with actual semantic embeddings | Recall@3 | MRR@3 | nDCG@3 |
|---|---:|---:|---:|
| BM25 | 0.995370 | 0.981481 | 0.976637 |
| Dense | 0.995370 | 1.000000 | 0.995675 |
| Hybrid | 1.000000 | 1.000000 | 0.998513 |

Sources, cases, top-k and context selection are identical. Required-page labels
include duplicate text/table chunks. The UI defaults to BM25 for the inexpensive
local workflow; hybrid was selected for the combined semantic run from its
best development-set recall. This small corpus does not establish that fusion
wins elsewhere. Hash vectors are not semantic embeddings.

Historical live output at `91d6f45` had 354/360 (98.33%), 138 schema-valid generation
responses, local hash retrieval and weaker labels. It is not directly comparable
with the new 381/390 result. The earlier historical semantic run disabled
generation and therefore did not verify a combined workflow.

Offline historical rescoring made zero API calls: 54 complete assessments with
48 correct; 174 partially labeled tool assessments with 174 correct; 132
noncanonical factual outputs unassessable. Those scopes do not yield a comparable
replacement headline. Retained baseline archive runners discovered the parent
repository for Git metadata; baseline-reproduction.json explicitly records the
actual archive source and flags that ambient revision rather than mislabeling it.

The new pre-final prompt-v3 combined run is also retained: 374/390 (95.90%), 16
false abstentions. A failed acceptance probe returned a unitless ratio as USD and
altered a citation ID; the verifier rejected it. After prompt corrections the
next two acceptance runs passed. All earlier raw evidence remains alongside final
results and is included in the budget, not hidden as unsuccessful experiments.

## Budget and cleanup

The user authorized $2 total. The one persisted ledger accounted for
**$0.3558943**, including all 249 generation-attempt reservations and 40 embedding
request reservations across this repair session. All entries have reported usage;
embedding entries retain bounded hidden-retry allowances. This is a conservative
standard-list-price estimate, not an invoice or proof of actual charges.
Source profiles were checked against current official
[GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) and
[embedding](https://developers.openai.com/api/docs/models/text-embedding-3-small) documentation.
The active ledger remains `.test-tmp/openai-repair-budget.json`; its final evidence
snapshot is budget-ledger.json. No ledger reset or new cap was used.

The [historical evidence index](../evals/results/evidence-index.json) preserves 36
source identities and original SHA-256 values. Gzip roundtrip equality was checked
for each retained identity. Five exact copies share indexed artifacts;
27,164,280 bytes were removed from the current working tree. Private dependency
installation output remained ignored. No Git history was rewritten. Dead tax UI
was removed, and private configuration/uploads were preserved.

## Exact commands and next steps

A fresh `.venv-repair` was created and installed from `requirements.lock`.
The final local commands below were run from the repository root; each exited 0.
The unit command measured the code bytes subsequently committed as `02d6ea4`.

```powershell
.\.venv-repair\Scripts\python.exe -m pip check
.\.venv-repair\Scripts\python.exe -m pytest -q -p no:cacheprovider --junitxml=.test-tmp/repair-final-223-tests.xml --basetemp=.test-tmp/repair-final-223-pytest
.\.venv-repair\Scripts\python.exe eval_retrieval.py --min-hybrid-recall 0.90 --output .test-tmp/repair-retrieval-final.json
.\.venv-repair\Scripts\python.exe eval_citations.py --min-abstention-recall 0.85 --output .test-tmp/repair-citations-final.json
.\.venv-repair\Scripts\python.exe -m evaluation.router --quality-gate --output .test-tmp/repair-router-final-v4.json
.\.venv-repair\Scripts\python.exe -m evaluation.application --quality-gate --output .test-tmp/repair-offline-final-v4.json.gz
.\.venv-repair\Scripts\python.exe -m evaluation.application --embedding-provider openai --budget-usd 2 --budget-ledger .test-tmp/openai-repair-budget.json --output .test-tmp/repair-semantic-final-v4.json.gz --quality-gate
.\.venv-repair\Scripts\python.exe -m evaluation.provider_checks --live --budget-usd 2 --budget-ledger .test-tmp/openai-repair-budget.json --output .test-tmp/repair-provider-final-v4.json
.\.venv-repair\Scripts\python.exe -m evaluation.application --live --embedding-provider openai --mode hybrid --repeats 3 --budget-usd 2 --budget-ledger .test-tmp/openai-repair-budget.json --output .test-tmp/repair-live-final-v4.json.gz --quality-gate
.\.venv-repair\Scripts\python.exe -m evaluation.replay --output .test-tmp/repair-historical-final.json.gz
```

Baseline reproduction used `git archive --format=zip --output=.test-tmp/baseline-91d6f45.zip 91d6f45`,
Python ZipFile extraction, and the fresh interpreter against the archived directory:
`-m pytest -q`, `eval_retrieval.py --min-hybrid-recall 0.90`,
`eval_citations.py --min-abstention-recall 0.85`,
`-m evaluation.router --quality-gate`, and `-m evaluation.application --quality-gate`.
The source wrapper and four outputs preserve the actual baseline evidence.

For the demo run `python demo.py`; its six expected outputs are in docs/demo.md.
For an interactive walkthrough run `python -m streamlit run app.py` and use the
listed PDFs. The two-minute walkthrough, Q&A and scoped claim table are in
[interview preparation](interview-preparation.md). No resume bullets are finalized.

Independent human review is the concrete remaining dependency: review v3 labels
against the linked originals/formulas, mark reviewer identity and corrections in
a new dataset version, and add broader licensed real filings/table layouts before
expanding the reliability claim. There is no command that substitutes for that
review. Re-run the offline commands with a fresh pytest temporary directory after
any future code change. Paid reruns must share the existing authorized ledger or
receive a new authorization; checkpoints do not resume skipped slots automatically.

## Final cleanup verification - 2026-10-05

The final cleanup removes four unreferenced helper paths, unused test imports,
the abandoned sample retrieval list and the completed root repair brief. The
brief remains available in Git history. Pandas remains a required Streamlit
dependency in the lock; its redundant direct declaration was removed. Actual
SDK schema/failure tests, required CI checks and thresholds remain intact.

README setup, architecture, upload/index instructions and the provider runbook
now describe the supported application. Demo and historical rescore outputs
default to ignored scratch paths rather than overwriting retained evidence.
Generation remains OpenAI-only; legacy Gemini embeddings remain optional.

The following checks ran once against the cleaned Python source. Its canonical
code SHA-256 is `1787fb2ec0fcf2563b96c7d8d642f4717297f5ff3db4b7ba5dcc02c41fb88ee8`.
The local report records the pre-commit HEAD plus this digest; it is not a new
live measurement or a relabeling of historical repair results.

| Check | Result |
|---|---|
| Locked environment `pip check` | No broken requirements |
| Existing pytest suite | 223 passed |
| Retrieval gate | Hybrid recall@3 0.944, required 0.90 |
| Citation/abstention gate | Abstention recall 1.0, required 0.85; decision accuracy 11/11; diagnostic citation precision 0.6923 and recall 0.6 |
| Router gate | 120/120 |
| Offline application gate | 390/390 across BM25, hash dense and hybrid |
| Streamlit startup | HTTP 200 / `ok`; isolated scratch index, generation disabled |
| Six-scenario demo | Four supported answers, one conflict abstention, one injected provider failure, all as expected |
| Historical rescore CLI | 54 complete, 174 partial, 132 unassessable; zero new provider calls |

Reports are retained locally under `.test-tmp/cleanup-wrapup`; the rescore CLI's
default report is `.test-tmp/historical-rescore.json.gz`. Historical artifact
hashes/manifests, frozen fixtures, original PDFs, private configuration, the active
budget ledger, uploads and indexes were preserved. All 299 protected file hashes
were unchanged, and all 36 historical evidence-index identities passed gzip/hash
verification. Twenty unique earlier scratch reports were deliberately retained.
No paid API calls were made for cleanup.

Local cleanup removed 552,403,153 bytes of inspected artifacts, including an
obsolete task-specific environment, an unpacked archive backed by its retained
ZIP, caches, 28 exact report copies and four console logs. Root environments
were preserved. Eighteen earlier pytest directories remain inaccessible because
of Windows ACLs; elevated execution and ownership recovery both returned access
denied. Their exact paths are recorded in the local
`.test-tmp/cleanup-wrapup/cleanup-result.json`. Removing these directories requires
Windows administrator access and remains the sole local cleanup blocker.

Tracked cleanup is delivered through `engineering/interview-readiness` and
draft PR #7. It reaches `master` when that PR is merged; no merge, branch deletion
or history rewrite is part of this wrap-up.
