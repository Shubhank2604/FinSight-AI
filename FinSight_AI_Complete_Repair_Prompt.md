# FinSight-AI — complete repair, cleanup, evaluation, and interview-readiness prompt

Act as a senior applied AI engineer, Python/backend engineer, and rigorous software reviewer. Complete the engineering work on my existing FinSight-AI repository so its supported workflows are correct, understandable, reproducible, and defensible in AI/ML engineering and SWE interviews.

Repository: https://github.com/Shubhank2604/FinSight-AI

Continue the work on `engineering/interview-readiness`. At the previous review, its HEAD was `91d6f459ba5f2db01ee76087822a7008b2e9dc39`; the default branch was `master`, not `main`, and a `dev` branch also existed. Inspect the current remote state before making assumptions.

My machine has 16 GB RAM and no GPU. Keep the local workflow practical on CPU. Active LLM generation must use OpenAI. Keep deterministic financial calculations in Python.

I want implementation, cleanup, testing, evaluation, and documentation completed. Do not stop at another audit, a plan, or a list of recommendations. Fix the underlying contracts and workflows, including adjacent failures discovered during the work. Be honest about what cannot be verified with the available credentials, data, and resources.

## 1. Working rules and boundaries

1. Read applicable `AGENTS.md` instructions, current source, tests, dependencies, documentation, branches, and stored evidence before editing.
2. Check for local uncommitted work. Preserve unrelated changes and existing private configuration. Do not overwrite `.env`, expose secrets, or delete private uploads.
3. Continue the existing engineering branch when safe. If another active checkout requires isolation, create a dedicated worktree or repair branch based on its latest HEAD and explain the relationship.
4. Make focused, reviewable commits. Do not force-push, delete remote branches, merge into the default branch, deploy, or publish releases automatically.
5. Maintain one concise implementation checklist. Map each defect to its fix, regression coverage, and evidence. Avoid producing multiple overlapping planning documents.
6. Prefer small, explicit modules and typed contracts. Introduce a dependency only when it solves a concrete need better than the existing code.
7. Record actual measurements and failures. Never invent human review, API success, coverage, cost, passing CI, or test results.
8. Do not equate mocked provider tests, replay tests, deterministic application requests, embedding calls, and live generation calls. Report them separately.
9. Preserve historical benchmark provenance. New results must identify the code, dataset, prompts, model, and configuration actually evaluated.
10. Finish independent work while handling blockers. Ask for information only when a material implementation choice or inaccessible resource actually blocks progress.
11. Do not optimize acceptance by weakening checks or optimize safety by abstaining on everything. Both useful-answer acceptance and rejection correctness must be tested.
12. Keep scope focused on a credible document research prototype. Authentication, tenant isolation, production deployment, and real tax coverage are optional unless needed for a feature you retain as verified.

## 2. Reproduce the baseline and establish a clean environment

The last reviewed branch had:

- 148 passing tests.
- Passing dependency checks in a fresh locked environment.
- Router: 100/100 controlled cases.
- Offline application: 360/360 correct outcomes across 120 synthetic questions in three retrieval modes; zero generation calls.
- Historical retrieval: BM25 Recall@3 1.000, hash hybrid 0.9444.
- Historical citation guard: decision accuracy 0.9091; abstention precision 1.000; recall 0.8571.
- Stored repeated OpenAI application report: 354/360 scored correct; 138 actual generation responses; 132 accepted generated responses; 164,588 reported generation tokens.
- Separate OpenAI embedding evaluation: dense Recall@3 0.834135, hybrid 0.598558, BM25 0.557692; generation disabled.

Recheck these results against current HEAD. Run the existing suite and offline gates before changing behavior. Capture failures as baseline evidence; do not silently rewrite existing reports.

Use a fresh virtual environment and the lock file. Check supported Python versions and operating systems explicitly. A local Linux Python 3.12 run is not proof of a successful configured Python 3.13 GitHub Actions run.

## 3. Repair calculation input parsing

Replace silent interpretation with explicit amount, currency, scale, rate-period, rate-convention, and duration contracts.

### Confirmed defect: thousand scale

Request:

`Calculate EMI on a loan of 500 thousand dollars at 8% for 20 years`

Current behavior: principal 500, EMI 4.18. Correct supported interpretation: principal 500000, EMI approximately 4182.20.

Requirements:

- Normalize `500k`, `500 thousand`, and `500000` identically.
- Handle supported scale words and variants consistently across query parsing and document extraction.
- Reject unconsumed amount modifiers or ambiguous conventions rather than interpreting a shortened number.
- Preserve exact input spans and normalized units in provenance.

### Confirmed defect: monthly rate treated as annual

Request:

`Calculate EMI on a $500000 loan at 1% per month for 20 years`

Current behavior: annual rate 1%, EMI 2299.47. A supported 1% monthly rate corresponds to nominal annual 12% in this monthly-amortization calculator and EMI approximately 5505.43.

Requirements:

- Bind the percentage to its stated period and convention.
- Support monthly rates through an explicit, documented conversion or reject them with an understandable unsupported/clarification response.
- Never relabel monthly, daily, weekly, effective, or nominal rates without checking their meaning.
- Preserve the original rate and any normalization in provenance.
- Distinguish contribution timing from rate timing.

Retain regressions for reordered input, missing principal, missing contribution, ambiguous initial balance, conflicting values/currencies, nonfinite values, negative inputs, fractional durations, basis points, and unsupported fees/prepayments/variable rates.

Equivalent supported requests must yield identical normalized inputs and results. Clarification must explain which field needs correction.

## 4. Bind routing to the requested operation and metric

### Confirmed defect: net-income growth becomes revenue growth

Using the checked-in Cedar fixture:

`Compute year-over-year net income growth for Cedar in the report for 2025`

Current behavior: accepted revenue growth of 20%. Cedar's net income is unchanged, so the requested net-income growth is 0%. Current-assets growth likewise incorrectly returns revenue growth.

Requirements:

- Carry action, metric, entity, reporting period, and evidence source in the operation contract.
- A generic `yoy_growth` tool name must not erase the requested metric.
- Either implement supported metric-specific growth or explicitly reject metrics outside the supported set.
- Use fixtures where revenue, net income, assets, margins, and debt move independently.
- Check operation agreement at the final boundary, not only agreement between internally selected tool names.
- Separate document facts, education, external current information, visual analysis, and deterministic calculations.
- Preserve document grounding even when the question uses common educational wording.
- Avoid treating “current ratio” or “current assets” as requests for current web information.
- Distinguish an explanation of a mortgage clause from a mortgage calculation.
- For multiple requested operations, execute the supported explicit set or clarify; never silently answer only one operation.

Expand the router evaluation with adversarial paraphrases and report per-route performance, not only aggregate accuracy.

## 5. Repair financial evidence extraction and unit inheritance

### Confirmed defect: explicit currency cancels scale

Evidence:

```text
Company: Cedar
Period: 2025
Currency: USD
Units: million
Revenue: $120
```

Current accepted answer: USD 120. Expected under the header: USD 120 million.

Requirements:

- Treat currency and scale as independent fields.
- A local currency symbol must not discard inherited document/table units.
- Explicit local scale can override an inherited scale according to a documented precedence rule.
- Preserve header, cell, page, and chunk provenance for each normalized input.
- Reject unresolved mixed units and conflicting headers.
- Test currency-prefixed table cells, bare cells, million/billion/thousand headers, explicit overrides, percentages, basis points, decimal fractions, negatives, and accounting parentheses.

### Confirmed defect: monetary values mistaken for years

`Revenue: $2025` and `Revenue: $2024.50` can produce no fact because year-like strings are removed from money.

Requirements:

- Identify years using context and token type, rather than removing every four-digit value in a year-like range.
- Separate dates, reporting periods, amounts, and counts.
- Test monetary values around 1900–2099, scaled values in that range, and true period labels.

Handle conservative financial label aliases and common table layouts. If extraction cannot establish a fact reliably, produce an explicit limitation or abstention; never guess units or periods.

## 6. Strengthen numerical and factual validation

### Confirmed defect: wrong year paired with an existing amount

Evidence:

```text
Company: Cedar
Currency: USD
Revenue in 2024 was USD 100 million and revenue in 2025 was USD 120 million.
```

Incorrect claim that currently passes:

`Cedar 2025 revenue: USD 100 million.`

Requirements:

- Validate supported financial claims against bound records such as `(entity, metric, period, value, currency, scale)` or equivalent aligned evidence spans.
- Do not accept a claim merely because all its numbers occur somewhere in a matching line/chunk.
- Test same-line multi-year statements, joined sentences, semicolon variants, multi-company statements, and swapped table columns.
- Rewording punctuation must not change the truth of an otherwise identical claim.
- If a relationship cannot be established, abstain or display a faithful source excerpt with a clearly limited interpretation.

Preserve all earlier mandatory rules:

- Required inputs are present and valid.
- Required tools succeed exactly as specified.
- Generated values cannot replace authoritative tool values.
- Tool provenance resolves to selected evidence.
- Citation IDs, pages, and claim-level references are valid.
- Full evidence is retained separately from shortened display snippets.
- Evidence-dependent answers have complete authoritative claim coverage.
- Empty factual claim lists cannot pass.
- Rounding has documented, tested tolerances.
- Missing support cannot be overridden by confidence or a diagnostic score.

General nonnumeric entailment remains a separate boundary. A claim such as `Cedar is insolvent.` currently passes against revenue-only evidence. For verified factual output, support a bounded set of reliable claim types or faithful excerpts and reject unsupported assertions. Do not add an LLM judge and describe it as a proof of truth. If broader prose support is retained, evaluate and describe its limitations separately.

Remove or clarify misleading confidence/threshold behavior. A value of 1.0 for passed mandatory checks must not be presented as calibrated accuracy. Propagate material generation assumptions consistently.

## 7. Fix evaluation correctness before producing new headline metrics

### Confirmed defect: expected-number membership scores wrong statements as correct

For a case asking Cedar's 2025 revenue, expected USD 120 million, the scorer currently accepts constructed responses containing:

- `Cedar 2024 revenue: USD 120000000.`
- `Harbor 2025 revenue: USD 120000000.`
- `Cedar 2025 revenue: USD 120000000; also USD 999000000.`

These examples are scorer probes, not evidence of new successful provider calls.

Requirements:

- Define expected entity/metric/period/value/unit tuples and expected operations explicitly.
- Check all reported factual values and associations, not only whether an expected number appears somewhere.
- Reject wrong periods, companies, metrics, currencies, signs, directions, denominators, tools, and extra unsupported assertions.
- Require complete answers when multiple facts are requested.
- Separate outcome correctness, citation-reference validity, citation support, extraction accuracy, tool accuracy, and prose support.
- Score expected abstention, clarification, unsupported operation, and provider failure according to their actual contracts.
- Add mutation tests for the scorer itself. A deliberately corrupted answer must receive an incorrect score.
- Do not use the application verifier as the sole ground-truth oracle. Evaluation labels and reference arithmetic must be independent of the implementation being assessed.
- Never inject expected answers or dataset labels into the request workflow.

Keep historical 98.33% results labeled as historical performance under the old scorer. Re-evaluate retained raw responses where possible with the stronger scorer; identify cases that cannot be retrospectively assessed. Publish new results separately.

## 8. Complete and verify document workflows

Ensure the actual application supports a coherent primary set of operations:

1. Grounded document facts.
2. Document-derived calculation inputs.
3. Ratios/margins and supported growth calculations.
4. Period comparisons.
5. Missing/conflicting evidence handling.

The workflow must be:

`retrieve → select evidence → extract typed facts/inputs → validate provenance and compatibility → deterministic calculation when needed → authoritative output → supporting evidence`

Document-backed EMI must not require the user to restate document inputs. Check whether complete inputs spanning multiple chunks need support; implement this within a clear contract or document and enforce the limitation.

Make query-versus-document precedence explicit. Reject ambiguous partial overrides. Check entity, period, currency, metric, denominator, and requested adjustments before calculating.

Validate calculators with independent reference values and invariants. Retain finite-input checks, option-type validation, prepayment iterator safety, and contribution/rate convention tests.

## 9. Verify retrieval and index lifecycle

Retain and strengthen the existing repairs:

- Filter document scope before result limits.
- Keep embedding spaces isolated by provider/model/dimensions/configuration.
- Use Qdrant/catalog identities consistently.
- Report storage locks explicitly; never substitute an empty index silently.
- Recover interrupted indexing and deletion without false completion.
- Preserve prior compatible evidence on failures.
- Handle duplicates, replacement, deletion, restart, rebuild, catalog corruption, and count/vector validation.

Check duplicate-content uploads under different filenames, filename collisions, failed rebuild batches, recovery interruptions, and settings changes. Define the supported behavior rather than relying on incidental IDs.

Measure final selected-context coverage as well as ranking. Avoid treating every chunk on a relevant page as equally useful without explaining that coarse labeling. Distinguish duplicate text/table content from independent evidence.

Compare BM25, actual semantic dense retrieval, and hybrid under equivalent conditions. Keep hash embeddings as a credential-free regression option and label them accurately. Choose a default from measured behavior; do not assume hybrid is always best.

## 10. Keep the OpenAI integration correct and testable

- Use the official Python SDK and Responses API with compatible structured schemas.
- Keep credentials in environment/private configuration.
- Verify model identifiers and supported request parameters against current official OpenAI documentation.
- Make model choice configurable without weakening capability checks.
- Preserve explicit refusal, incomplete response, empty output, schema failure, authentication, quota, rate-limit, timeout, and server-error handling.
- Keep retries bounded and observable.
- Avoid generic prose fallback labeled as grounded success.
- Preserve successful deterministic results where independently appropriate.
- Track requested/actual model, prompt version, response ID, token usage, attempts, latency, and validation status without exposing secrets.
- Keep embedding migration separate; generation-model changes do not require mixing or rebuilding vector spaces.

With available credentials and an existing authorized spend budget, run the planned live checks. If spend authorization or credentials are absent, complete offline work and provide an exact bounded live-run plan with call counts and estimated costs where current pricing supports them. Do not issue unlimited paid runs or fabricate their completion.

## 11. Finish the interface and make scope honest

- Align UI controls, parser support, and calculator defaults.
- Resolve USD/INR default inconsistencies; make currency visible.
- Expose supported portfolio timing/rate options, or explain their narrower form support.
- Label unsupported prepayment, tax, options, vision, and web behavior accurately.
- Present citations with source name, page, useful supporting text, and units where relevant.
- Show interpreted inputs, authoritative results, assumptions, and formula/provenance.
- Make clarification and abstention reasons useful.
- Keep diagnostics expandable; keep implementation details out of ordinary user flows.
- Handle indexing/removal/request exceptions without permanently pending state.
- Continue explicitly independent questions unless implementing tested scoped conversation state.

Either complete and verify an advertised feature or remove/disable its misleading entry point. A broken tax calculator is not a verified feature because an engine file exists. Preserve experimental adapters only when they have a clear purpose and honest label.

Vision/web can remain experimental if support and freshness are unverified. Do not include them in core accuracy metrics. Do not spend the entire repair budget expanding these paths while numerical correctness remains unresolved.

## 12. Build stronger evidence with representative documents

Retain the synthetic suite for fast regression CI, but improve its diversity. The current ten templates and repeated constant ratios/margins/growth values are insufficient to expose wrong-operation behavior.

Add representative public financial filings or clearly redistributable financial documents. Aim for approximately 10–20 diverse documents and 100–150 questions if practical; quality, traceable labels, and task diversity matter more than hitting a count.

Include:

- Different layouts and financial label aliases.
- Annual/quarterly and multi-period tables.
- Currency symbols with inherited scales.
- Negative values, accounting parentheses, and restatements.
- Multiple entities and irrelevant periods.
- Multi-chunk evidence and conflicting facts.
- Missing answers and unsupported calculations.
- Independently varying ratios, margins, and growth values.
- Natural user phrasing and adversarial paraphrases.

Freeze development and held-out splits before tuning. Record label provenance and reviewer identity honestly. Agent-authored labels are not independently human-reviewed. If human review is unavailable, prepare the reviewable labels and mark that step outstanding without blocking independent engineering work.

Measure answer/outcome correctness, supported-claim accuracy, numerical accuracy, citation support, answerable coverage, unsupported acceptance, over-abstention, abstention precision/recall, retrieval Recall@K/MRR/nDCG, final-context coverage, and stage latency. Report route-specific outcomes and denominators.

Run semantic retrieval plus OpenAI generation together on the final supported set. Repeat stochastic runs sufficiently to show observed variation, within the authorized budget. Distinguish warm/cached retrieval from query-embedding network latency and end-to-end latency.

## 13. Make provenance, reporting, and CI reproducible

- Record committed revision, clean/dirty state, dataset version/digest, code digest, dependencies, prompts, actual models, embedding identity, raw outputs, traces, and validation decisions.
- Canonicalize code/dataset hashes for path separators and line endings, or explicitly document platform-specific byte digests.
- Do not describe reports from dirty pre-delivery state as measurements made directly on final clean HEAD.
- Finalize code and freeze datasets before final measurement. Record a subsequent evidence commit separately if adding reports changes HEAD.
- Retain completed requests when evaluation fails; list missing slots explicitly and use null scores for unrun groups.
- Make incomplete required runs fail clearly.
- Prefer resumable runs if adding continuation is straightforward; otherwise provide a safe bounded restart procedure.
- Keep paid evaluation outside fast CI.
- Require correctness, useful-answer coverage, and unsupported-acceptance gates together.
- Run remote CI through an authorized branch trigger or a reviewable pull request targeting the actual default branch. Inspect failures and fix them; do not claim a remote pass based on workflow configuration.
- If remote execution is unavailable, state the exact blocker and retain local evidence.

## 14. Clean the repository without deleting useful evidence

Audit the final tree and remove genuinely dead helpers, unreachable forms, obsolete provider-generation code, duplicated adapters, unused imports, accidental generated files, and stale instructions.

Keep useful architecture, evaluation methodology, verification, demo, and interview documentation. Do not delete every Markdown file just to make the repository look small.

For the large evaluation artifacts:

- Preserve historical identity and raw evidence needed for reproducibility.
- Use clearly versioned directories and compact summaries or an evidence index.
- Remove exact redundant copies only after verifying and documenting equivalence.
- Consider compression/artifact storage where appropriate, preserving discoverability and authorized access.
- Do not rewrite Git history to shrink the repository.

Keep private uploads, credentials, environments, caches, and transient reports out of Git. Check upload path sanitation and filename collision behavior. Validate chunker parameters and actual limits; distinguish whitespace lengths from model tokenizer counts.

Verify the lock and supported setup in a clean environment. Update README and documentation around actual final behavior. Reconcile outdated statements about quota-blocked evaluations with completed historical runs while preserving dates and provenance.

## 15. Prepare the final interview demonstration

Deliver a reproducible demonstration with:

1. A document fact with readable support.
2. A document-backed calculation with typed inputs and provenance.
3. A period comparison with correct entity/value/period binding.
4. Missing or contradictory evidence causing a useful abstention.
5. A provider failure handled without unsupported output.

Use at least one representative real-document scenario when rights and extraction support permit. State which scenarios are deterministic and which call OpenAI. Provide expected outputs and exact commands.

Update a beginner-friendly architecture explanation, a two-minute walkthrough, and interview Q&A covering the final implementation, trade-offs, discovered failures, retrieval comparison, validation boundary, and evaluation methodology. Keep answers simple and concrete, generally around 3–5 lines when appropriate.

Produce a claim-to-evidence table with exact scope, denominators, evidence paths, and limitations. Do not finalize resume bullets yet.

## 16. Completion gates and final deliverables

Declare the supported core interview-ready only when:

- All confirmed silent calculation and numerical-support defects are fixed or the affected operation is explicitly rejected.
- The exact examples in this prompt have meaningful regression coverage.
- Supported positive cases remain usable.
- Scorer mutation tests reject wrong entity/period/metric/value/unit and additional unsupported facts.
- Document-to-calculation provenance and visible evidence work through the actual application.
- Fresh tests, dependency checks, and offline gates pass.
- Final metrics use the repaired scorer and match the claimed workflow.
- Live and real-document results are accurately verified or explicitly listed as outstanding.
- Documentation matches the final code and experimental scope.
- Remote CI status is known and reported honestly.

Do not claim perfect financial reliability, arbitrary-PDF support, production readiness, or complete semantic entailment.

Your final response must include:

1. What was fixed and cleaned, with commit/branch information.
2. A defect-to-fix-to-test table.
3. Exact verification commands and actual results.
4. New versus historical benchmark results, with datasets, denominators, generated-call counts, and provenance.
5. Remaining limitations, concrete blockers, and exact next commands.
6. Demo instructions and interview artifacts.
7. A concise readiness decision for the supported core.

Complete the authorized implementation work autonomously. Finish with a reviewable result; leave merging, branch deletion, deployment, and publishing for a separate explicit instruction.
