# Evaluation method

The application runner ingests frozen PDFs, retrieves scoped evidence, invokes the
actual orchestrator and verifier, and evaluates the displayed output. Expected
labels never enter the request pipeline. The independent scorer imports no
application financial parser or verifier. Its version is `bound-label-scorer-v3`.
Canonical tuples bind entity, metric, period, currency and normalized value;
tools require complete labeled inputs/results and authoritative display. Additional
claims/prose/results fail. Non-OK outcomes require their exact labeled status.
Money tolerance is half a cent, derived tool outputs use 0.00005, and integer
periods remain exact. Mutations exercise entity/year/metric/value/sign/unit,
input denominator, tool identity, extra assertions and small ratio changes.

The frozen v3 manifest has 130 cases on 12 PDFs: 108 accepted, 18 abstained,
two unsupported and two clarification. Development has 84 cases and held-out
46, grouped by issuer. Ten synthetic reports vary values, currencies, scales,
metric vocabulary, split loans and conflicts. Two government CFO excerpts are
real, but only two positive real facts are tested. Agent-authored labels are
not independently human-reviewed; the engineer can inspect the held-out labels.
This is an internal regression split, not a blind estimate of generalization.

Report accuracy, answerable coverage, unsupported acceptance, false abstention,
accepted fact/tool accuracy, reference validity and stage latency together.
Missing repeats have explicit planned/missing slots and null metrics, never
fabricated zero-length success. Application slots are not generation calls:
deterministic tools and early rejections bypass the provider. Failed generation
attempts, schema-valid responses and accepted answers are different quantities.

BM25, dense and hybrid are compared on identical sources, cases and context
selection. Hash vectors are deterministic CI inputs, not semantic embeddings.
Real semantic comparison requires actual OpenAI embedding calls. Ranking at
three candidates and final selected-context coverage have different denominators.
Required-page labels include duplicate text/table chunks and are coarse;
page coverage does not prove every required financial field was retrieved.
Queries are embedded and cached before request timing. Embedding preparation
calls/tokens/latency are reported separately from cached retrieval latency.

Final measurements should start from committed clean code and frozen data.
Reports record revision, a canonical SHA-256 of sorted Git-visible Python paths
and bytes with CRLF normalized to LF, raw and canonical dataset hashes, fixture
hashes, dependencies, provider/model/dimensions, prompt and ingestion identity,
raw outputs and per-request traces. Later documentation/report commits do not
retroactively change the measured revision. Dataset raw JSON hashes can differ
with Git line-ending conversion; the canonical JSON hash is the comparison key.

Paid evaluation uses one sequential persisted ledger shared across generation and
embedding calls. Reservation bounds use UTF-8 input bytes plus framing allowance
and output limits. Missing/failed usage retains the reservation. Bounded hidden
embedding retries retain an allowance. Standard list-price estimates are not
invoice costs; cached discounts are not assumed. Unknown model prices fail closed.
Current source profiles: [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
and [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small).
Budgeted web/vision calls are excluded because their additional pricing is not modeled.

Baseline `91d6f45` was archived and reproduced separately: 148 tests and all four
old offline gates pass. Its 354/360 historical live headline uses the weaker
original scorer and hash retrieval. Offline historical rescoring reports 54
complete-status assessments (48 correct), 174 partially labeled tool assessments
(174 correct), and 132 unassessable noncanonical factual outputs, with zero new
calls. These scopes cannot be combined into a comparable replacement accuracy.
The old semantic run had generation disabled; it was not a combined live pipeline.

Historical raw reports are preserved byte-for-byte after gzip decompression.
The evidence index retains source paths and original SHA-256 values; five exact
copies were eliminated only after equality checks. No Git history was rewritten.
Old quota-limited Gemini runs and OpenAI failures remain dated historical evidence.
See [verification](verification.md) for exact final commands and outcomes.
