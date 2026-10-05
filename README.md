# FinSight AI

FinSight is a financial document research assistant with explicit evidence
contracts and deterministic calculations. Select documents, ask an independent
question, and inspect citations or calculation inputs. The local core runs on CPU.

Supported verified output consists of canonical financial facts binding company,
metric, year, currency and normalized value; faithful source excerpts; or
validated deterministic tool results. Arbitrary narrative entailment and arbitrary
PDF layouts are outside that contract. Unsupported or conflicting inputs cause
clarification or abstention. Confidence diagnostics are binary gates, not probabilities.

PDF ingestion preserves source/page/company/period/currency/unit metadata. EMI,
portfolio projection, current ratio, debt/equity, net/operating margin and
metric-specific year-over-year growth use typed inputs and recorded provenance.
Complete query inputs override document scenarios; partial overrides clarify.
Split loan fields must belong to the same document and compatible company/period/
currency. Conflicts remain visible even when another chunk contains a complete loan.

The generation provider is the official OpenAI Responses SDK with configurable
validated model profiles; the default is `gpt-5.4-mini-2026-03-17`. Generation
is optional. The UI default retrieval is BM25 with credential-free local hash vectors.
Optional semantic embeddings use `text-embedding-3-small`, 768 dimensions, in
separate collections. Legacy Gemini embeddings remain optional; Gemini generation
is removed. Collection identities include provider/model/dimensions/ingestion version.
The v3 ingestion change requires re-indexing; preserve existing uploads and `.env`.

Streamlit shows source evidence, interpreted inputs, authoritative results,
assumptions and optional diagnostics. USD is the default calculation currency.
Portfolio timing and rate conventions are selectable. Tax is disabled until reviewed
rule packs exist. Web and vision are experimental. Queries are independent;
displayed history is not conversation memory. Index recovery uses a journal and
Qdrant as authority; duplicate-content aliases are rejected with the existing name.
A rebuild validates each batch and preserves compatible evidence on failure,
but is not a globally atomic transaction.

## Setup

Python 3.13 is supported. A fresh locked Windows 3.13.9 environment passed 223 tests
and dependency consistency checks during repair. Linux CI status and final
measurements are recorded in [verification](docs/verification.md).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip check
# Only if you do not already have a private configuration:
Copy-Item .env.example .env
python -m streamlit run app.py
```

On Linux/macOS use `source .venv/bin/activate` and `cp`.
Set `OPENAI_API_KEY` privately for generation or semantic embeddings. The UI
starts with generation off. Index selected documents after uploading them.

## Reproduce the evidence

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=.test-tmp/check-unique
python eval_retrieval.py --min-hybrid-recall 0.90 --output .test-tmp/retrieval.json
python eval_citations.py --min-abstention-recall 0.85 --output .test-tmp/citations.json
python -m evaluation.router --quality-gate --output .test-tmp/router.json
python -m evaluation.application --quality-gate --output .test-tmp/application.json.gz
python -m evaluation.replay --output .test-tmp/historical-rescore.json.gz
python demo.py
```

Use a new pytest temporary directory for each run. Paid checks require credentials
and an explicit authorized cap. Share a persisted ledger between sequential runs;
do not reset it to bypass the cap. A rerun repeats requests rather than resuming a
checkpoint. Paid runs are excluded from CI.

```powershell
python -m evaluation.application --embedding-provider openai --budget-usd 2 --output .test-tmp/semantic.json.gz --quality-gate
python -m evaluation.application --live --embedding-provider openai --mode hybrid --repeats 3 --budget-usd 2 --output .test-tmp/live.json.gz --quality-gate
python -m evaluation.provider_checks --live --budget-usd 2 --output .test-tmp/provider.json
```

The new frozen [v3 dataset](evals/repair_v3/README.md) has 12 documents and 130
questions: ten synthetic issuers and two real government CFO excerpts from one
issuer. There are 84 development and 46 internal held-out questions. Labels are
agent-authored and not independently human-reviewed. The independent v3 scorer
checks complete fact tuples, full labeled tool inputs/results, exact rejection
statuses and the displayed answer. Mutations reject swapped company/year/metric,
wrong values/units, tiny ratio errors and extra unsupported assertions.

Final repair measurements on clean source `02d6ea4`: 223 tests; router 120/120;
offline application 390/390; combined OpenAI semantic/hybrid retrieval and generation
381/390 (97.69%) across three repeats. There were 120 generation calls and eight
embedding requests in that final application run. It had eight false abstentions
and one valid net-sales alias that fails strict canonical-metric scoring; all 204
calculations passed and no expected-rejection case was accepted (0/66).
The semantic comparison and three acceptance probes also passed. Remote Ubuntu
CI [passed on the measured revision](https://github.com/Shubhank2604/FinSight-AI/actions/runs/37265605624).
All new paid checks together accounted for an estimated $0.3558943 of the authorized
$2 cap, including prior attempts and retry allowance; invoice cost is unknown.

Historical 354/360 live correctness (98.33%) used weaker labels and hash retrieval;
it is not the current repaired-system accuracy. Retained raw reports are losslessly
compressed with original hashes and duplicate mappings in the [evidence index](evals/results/evidence-index.json).

See [verification](docs/verification.md), [evaluation methodology](docs/evaluation.md),
[implementation checklist](docs/implementation-checklist.md), [architecture](docs/architecture.md),
[demo](docs/demo.md), and [interview walkthrough and Q&A](docs/interview-preparation.md).
