# Two-minute walkthrough

“FinSight is a financial document research assistant with deterministic calculations. I built it around explicit evidence contracts because a plausible answer can still have the wrong currency, reporting period or input amount.

The user selects documents and asks a question. The router separates the requested action from the evidence source. Document questions always require document evidence; a phrase such as current ratio does not trigger a web search. Retrieval combines BM25 and dense search through reciprocal-rank fusion, then selects context with deduplication and table priority. Local hash vectors provide a cheap CI baseline, and OpenAI semantic embeddings are evaluated separately.

For a current-ratio question, the application extracts assets and liabilities with their company, currency, year and chunk/page references, validates them, and runs a deterministic formula. For factual answers, validated claims are the authoritative displayed representation. Mandatory conditions cannot be outweighed by a confidence score.

I also made index identities explicit and added recovery for interrupted indexing, replacements, deletions and storage locks. The Streamlit interface shows citations, normalized tool inputs, results and assumptions. The core runs on CPU without a GPU.

The evaluation separates fast offline regression from actual provider calls. There are 100 routing cases, 12 synthetic PDF fixtures and 120 application questions with company-level held-out cases. I report coverage and unsupported-answer rate together so abstaining on everything cannot pass. These labels are agent-authored, not independently human-reviewed; arbitrary-document semantic accuracy and experimental web/visual behavior remain outside the verified claim.”

# Questions and concise answers

| Question | Answer |
|---|---|
| Why not let the LLM calculate? | Arithmetic should be reproducible. Typed extraction and deterministic tools preserve exact inputs, formulas and provenance. |
| Why separate action from evidence? | A report can contain a loan clause without asking for EMI. Routing by topic alone selected the wrong tool or external source. |
| How do you stop positional-number errors? | Money, rates, dates and duration have separate extraction rules and schemas. Ambiguous/conflicting fields produce clarification. |
| What makes citations enforceable? | Every supplied reference is checked, claims are mandatory for factual output, and the UI displays only validated claims or authoritative tool output. |
| Does that eliminate hallucinations? | No. Numerical and metadata checks are narrower than semantic entailment; arbitrary nonnumeric paraphrases remain a documented boundary. |
| Why hybrid retrieval? | BM25 handles exact financial vocabulary; semantic vectors can handle paraphrases. Fusion is measured, not assumed superior. |
| Are hash embeddings semantic? | No. They are a deterministic regression baseline. Genuine semantic measurements use actual OpenAI embeddings and are reported separately. |
| What happens on storage lock? | An actionable failure. No silent fallback to an empty memory index. |
| How do you handle a crashed upload? | A journal allows startup rollback of partial new points or completion of a ready replacement. Qdrant reconstructs the catalog. |
| How are different models isolated? | The collection identity incorporates provider/model/dimensions/ingestion version. Incompatible spaces cannot silently share a collection. |
| How do you handle provider failure? | Typed provider-failure responses, no fabricated grounded answer, cleared UI pending state, and independent deterministic calculations remain available. |
| What is held out? | Four companies and their questions are isolated from eight development companies. The corpus remains synthetic and needs independent review. |
| What prevents abstain-everything from passing CI? | CI requires supported-answer coverage and answer correctness as well as zero unsupported acceptance. |
| What is the biggest limitation? | Conservative labeled-record extraction and small synthetic data do not establish arbitrary-document accuracy. The repeated OpenAI evaluation completed; six of 360 cases falsely abstained. |
| What would you do next? | Independently review labels, add licensed real filings and difficult tables, measure representative real-document performance, then expand extraction under measured quality gates. |
| Can it run on my machine? | The offline core uses small PDF/Qdrant/BM25/hash workloads and no GPU or local transformer. Live OpenAI generation needs credentials and quota; optional Gemini embeddings retain their own credentials. |

# Claim-to-evidence mapping (not finalized resume bullets)

| Statement | Evidence | Safe scope |
|---|---|---|
| Implemented deterministic EMI, portfolio projection and Black–Scholes tools | `tools/`, independent reference/invariant tests in `tests/test_engineering.py` | Implemented and tested offline; tax coverage requires real reviewed rule packs. |
| Implemented document-backed financial ratios and growth | `tools/research.py`, input provenance tests, `demo.py` | Current ratio, net/operating margin, debt-to-equity and revenue year-over-year growth under supported extraction contracts. |
| Added hybrid retrieval with explicit document scope | `retrieval/hybrid.py`, source-filter tests and retrieval reports | Implemented; do not claim hybrid always wins or that hash vectors are semantic. |
| Added enforceable factual output and recovery | verifier, storage lifecycle/provider/UI tests | Mandatory mechanical/numerical validation, not proof of all natural-language entailment. |
| Built reproducible application evaluation | versioned PDFs, split manifests and `evaluation/application.py` | 120 synthetic cases, agent-authored labels; no independent human review claim. |
| Benchmarked routing | `evals/results/router-v2.json` | 100 controlled cases; not broad production intent accuracy. |
| Tested live providers | OpenAI acceptance/live/semantic reports | Three acceptance probes passed; 360 repeated cases completed, 138 schema-valid API responses, 98.33% correctness under synthetic labels. |
| Built a financial AI assistant | working UI, demo and tests | Research/calculation prototype; not investment advice, trading execution, general verified financial advice, or production certification. |

Do not convert these rows into final resume bullets until the verification report and remaining live/review limitations have been assessed.
