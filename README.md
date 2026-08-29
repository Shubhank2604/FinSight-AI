# FinSight AI

[![CI](https://github.com/Shubhank2604/FinSight-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Shubhank2604/FinSight-AI/actions/workflows/ci.yml)

FinSight is an experimental financial RAG application with query routing, document ingestion, dense and BM25 retrieval, reciprocal-rank fusion, finance calculators, and structured Gemini responses. Its evaluation suite runs locally without API credentials and reports retrieval quality instead of assuming hybrid retrieval is better.

It supports analysis and education. It does not execute trades or provide licensed financial advice.

## Measured retrieval baseline

The versioned benchmark contains 18 labeled queries over 18 synthetic finance chunks. It exercises the same Qdrant, BM25, and fusion paths used by the application with deterministic local embeddings.

| Mode | Recall@3 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: |
| Dense local hash | 0.944 | 0.861 | 0.883 |
| BM25 | 1.000 | 0.972 | 0.979 |
| Hybrid RRF | 0.944 | 0.889 | 0.903 |

BM25 wins on this small, lexical corpus. The benchmark is a reproducible baseline, not evidence that the application is accurate on arbitrary financial questions. See [the evaluation methodology](docs/evaluation.md) for definitions, per-query failures, and limitations.

## Request flow

```text
Query -> intent router -> retrieval / calculator / multimodal / web path
      -> structured Gemini response -> citation and confidence checks -> answer
```

The router selects among compute-only, educational, document retrieval, retrieval plus calculation, multimodal, web-grounded, and abstention paths.

### Retrieval

- Qdrant dense search captures semantic similarity.
- BM25 preserves exact financial terms and identifiers.
- Reciprocal-rank fusion combines both rankings.
- Context packing removes duplicate chunks and prioritizes tables for numerical queries.

### Validation boundary

The `VeriFi` component checks citation IDs, retrieved-context presence, tool use, missing-data signals, and confidence thresholds. It validates the grounding infrastructure; it does **not** yet prove claim-level semantic entailment. Claim-level citation precision/recall and answer-faithfulness evaluation remain planned work.

## Run locally

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate                 # macOS/Linux
# .\.venv\Scripts\Activate.ps1          # Windows PowerShell
python -m pip install -r requirements.txt
```

Create `.env` for Gemini-backed application paths:

```env
GEMINI_API_KEY=your_key_here
GEMINI_TEXT_MODEL=gemini-3-flash-preview
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_WEB_GROUNDING_MODEL=gemini-2.5-flash
```

Start the Streamlit app:

```bash
streamlit run app.py
```

Index local documents with deterministic embeddings:

```bash
python index_uploads.py --folder data/uploads/originals --embedding-provider local_hash
```

## Evaluation and tests

```bash
python eval_retrieval.py \
  --top-k 3 \
  --output evals/results/latest.json \
  --min-hybrid-recall 0.90

python -m pytest -q
```

GitHub Actions runs the test suite and credential-free retrieval quality gate for every pull request.

## Repository map

```text
app.py                  Streamlit application
router/                 Intent classification
ingestion/              PDF extraction and chunking
retrieval/              Qdrant, BM25, and RRF
tools/                  Finance calculators
verifier/               Citation and confidence checks
evaluation/             Benchmark runner and metrics
evals/                  Labeled cases and versioned results
docs/evaluation.md      Methodology, failures, and limitations
```

## Current limitations

- The retrieval benchmark is deliberately small and synthetic.
- Retrieval metrics do not measure final-answer correctness or claim support.
- Web-grounded and Gemini-backed paths require external services and are not deterministic.
- Financial outputs require independent verification before use in a real decision.
