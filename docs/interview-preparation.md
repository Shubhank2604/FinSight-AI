# Two-minute walkthrough

FinSight helps a user ask independent questions about selected financial documents.
The first decision is what action is requested and where its evidence must come
from. A document question stays within document evidence. General education
can use a local explanation. Explicit web access remains experimental.

The application retrieves evidence within the selected sources and extracts
company, year, currency, scale and metric together. For calculations it turns
those records into typed inputs with original spans, checks compatibility, and
runs deterministic formulas. The UI displays those exact results and provenance.
The model can explain, but it cannot replace the authoritative arithmetic.

Factual output has a deliberately bounded contract: complete canonical financial
facts or faithful source excerpts. A matching number somewhere in a citation is
insufficient. Wrong years, swapped companies, extra assertions and unsupported
insolvency statements are rejected. The mandatory-check indicator is not a
calibrated probability or a proof of arbitrary narrative entailment.

The offline CPU evaluation and local MiniLM embeddings need no model key. The
app calls OpenAI for final generation after local retrieval prepares the context.
Embedding spaces have separate identities and observability. Index journals support
restart/replacement/deletion recovery; conflicting uploads and storage locks
produce actionable errors. USD defaults and portfolio conventions are visible.

Evaluation checks actual displayed answers, coverage and rejection behavior on
frozen PDFs. The new 130-case set has varied synthetic inputs and two real Mint
CFO pages. It remains small and agent-reviewed. Paid calls are separate from CI,
and reported application counts are separate from generation requests. The
verification report gives exact measured revisions and remote CI status.

# Interview questions

**Why deterministic arithmetic?**
Typed inputs and formulas are reviewable. Loan principal, annualized rate and
whole-month duration retain their origins. Independent reference values and
invariants catch mathematical errors. The provider cannot change tool values.

**How did the old verifier fail?**
A number could match somewhere in evidence while its company or year was wrong.
Nonnumeric assertions could also pass narrow numerical checks. The new contract
requires bound records and canonical output or a faithful excerpt. It rejects
unsupported narrative instead of pretending to establish broad entailment.

**What did you find during the repair?**
A complete loan hid conflicting partial fields in another chunk. Split fields
could also join across companies. The repair validates all relevant fragments,
checks context compatibility and resolves provenance spans at the final boundary.
Focused regressions reproduce these failures and supported positive cases.

**Why use an independent scorer?**
Reusing the production extractor would reproduce its errors. The scorer reads
explicit expected tuples and full independent tool labels. Mutation tests require
wrong binding, units, denominators, extra facts and small ratio changes to fail.
Historical outputs with incomplete labels remain partial or unassessable.

**Why keep BM25, dense and hybrid?**
Exact financial terms suit BM25. Actual semantic vectors may help paraphrases.
Fusion is an implemented option, not an assumed improvement. Compare equivalent
conditions and keep hash vectors labeled as a deterministic CI baseline.

**What happens after a crash or failed provider call?**
A journal allows startup rollback or completion of interrupted index operations.
Qdrant reconstructs the catalog. Provider failures have typed outcomes and bounded
retries; successful deterministic work remains available. UI pending state clears.

**What does held-out mean here?**
Synthetic issuers are split by company and the real excerpts are held out.
The manifest was frozen before delivery measurement, but the engineer can inspect
it and authored the labels. Independent human review and a larger real corpus
are still needed before making broad generalization claims.

**What is outside the supported scope?**
Arbitrary financial PDFs, complex restatements and general prose entailment.
Tax lacks reviewed rules and is disabled. Vision/web are experimental. A rebuild
preserves compatible evidence but is not an all-batches atomic transaction.
No claim of production readiness or perfect financial reliability is supported.

# Claim-to-evidence mapping

| Claim | Evidence and denominator | Limitation |
|---|---|---|
| Bound financial claims and deterministic tools | `tests/test_repair_contracts.py`, `test_repair_workflows.py`, `test_repair_completion.py`; final suite counts in verification | Explicit supported contracts |
| Useful answers and safe rejection | 130-case frozen manifest; final mode/repeat reports in verification | Agent labels, narrow real pages |
| Scoped retrieval and recovery | `retrieval/hybrid.py`, lifecycle regressions, semantic comparison | Page labels are coarse; fusion may lose |
| Official OpenAI integration | Mock SDK failure tests plus final acceptance/live reports | Schema validity differs from acceptance |
| Reviewable demonstration | `python demo.py`, six outcomes | Credential-free; injected timeout |
| Reproducible delivery | Code/data hashes, locked environment, remote CI linked in verification | No independent human label audit |

Do not turn these rows into final resume bullets yet.
