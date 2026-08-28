# FinSight AI

[![CI](https://github.com/Shubhank2604/FinSight-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Shubhank2604/FinSight-AI/actions/workflows/ci.yml)

## Overview

**FinSight AI** is a local-first **financial decision engine** built using a Streamlit interface.

It is not a simple chatbot. Instead, it intelligently routes user queries through:

* Hybrid document retrieval (RAG)
* Multimodal reasoning (text + images)
* Structured LLM reasoning (Gemini)
* Automatic web grounding (for live data)
* A verification layer (**VeriFi**) to ensure reliability

The system is designed for **analysis and understanding**, not for executing trades or providing licensed financial advice.

---

## Core Idea

Instead of answering directly using an LLM, FinSight AI follows a structured pipeline:

```text
User Query
→ Router (classify intent)
→ Retrieval / Multimodal / Web / Educational path
→ Gemini reasoning
→ VeriFi verification
→ Final Answer
```

This ensures that answers are:

* grounded in data
* logically structured
* verifiable

---

## Key Capabilities

### 1. Intelligent Query Routing

Every user query is classified into a specific type before processing:

* `compute_only`
* `educational_answer`
* `retrieve_then_answer`
* `retrieve_then_compute_then_answer`
* `multimodal_reasoning`
* `web_grounded_answer`
* `abstain`

This prevents generic LLM responses and improves accuracy.

---

### 2. Hybrid RAG (Retrieval-Augmented Generation)

FinSight AI uses **two retrieval systems together**:

#### Dense Retrieval

* Uses embeddings
* Powered by Qdrant
* Captures semantic meaning

#### Sparse Retrieval (BM25)

* Captures exact keywords
* Handles finance-specific terminology

#### Fusion (RRF)

* Combines both results into a final ranked set

---

### 3. Context Packing

Before sending data to Gemini:

* duplicate chunks are removed
* relevant chunks are prioritized
* table data is boosted for numerical queries
* irrelevant content is filtered

This improves answer precision.

---

### 4. Multimodal Reasoning

The system supports:

* PDFs
* Tables
* Images
* Charts
* Screenshots

For image-based queries:

```text
Image + Query + Context → Gemini → Explanation
```

Example:

* “Explain this portfolio screenshot”
* “What trend is visible in this chart?”

---

### 5. Automatic Web Grounding

For live or current queries, the system automatically uses Gemini search grounding.

Triggered when query contains:

* current / latest / today / recent
* stock prices
* exchange rates
* market conditions
* interest rates

Example:

```text
"What is the current USD to INR rate?"
```

---

### 6. Structured Gemini Output

Gemini does not return free-form text.

Instead, it returns structured JSON:

```json
{
  "answer": "...",
  "used_citation_ids": ["chunk-id"],
  "claims": [],
  "assumptions": [],
  "confidence": 0.0,
  "needs_more_data": false
}
```

This allows downstream validation.

---

### 7. VeriFi (Verification Layer)

VeriFi ensures answer quality by checking:

* claims are supported by retrieved context
* citations are valid
* missing data is handled properly
* confidence level is sufficient

If verification fails:

```text
"Insufficient data to answer reliably."
```

---

## System Architecture

```text
         User
          ↓
      Streamlit UI
          ↓
        Router
          ↓
----------------------------------------------
| Retrieval | Multimodal | Web | Educational |
----------------------------------------------
          ↓
Gemini Structured Answer
          ↓
        VeriFi
          ↓
      Final Answer
```

---

## Data Ingestion Pipeline

```text
PDF / Image
→ Extract (text, tables, images)
→ Chunking
→ Embedding
→ Store in Qdrant
→ Build BM25 index
```

Each chunk includes:

* content
* type (text / table / image)
* page number
* section metadata

---

## Repository Structure

```text
app.py                  Main Streamlit app
config.py               Configuration
schemas.py              Data schemas

ingestion/
  extractor.py          Document parsing
  chunker.py            Chunk creation

retrieval/
  hybrid.py             Hybrid RAG implementation

router/
  intent_router.py      Query classification

verifier/
  verifi.py             Validation layer

data/
  uploads/originals/    Uploaded documents
  index/qdrant/         Vector DB
  index/chunks.json     Retrieval catalog
```

---

## Example Queries

### Educational

```text
Tell me about SEC filings
How do I calculate retirement corpus?
```

### Document-Based

```text
What risks are discussed in the Apple filing?
Summarize the brokerage statement
```

### Multimodal

```text
Explain this portfolio screenshot
What does this chart show?
```

### Web Grounded

```text
What is the latest Fed interest rate?
```

---

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```env
GEMINI_API_KEY=your_key_here
GEMINI_TEXT_MODEL=gemini-3-flash-preview
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_WEB_GROUNDING_MODEL=gemini-2.5-flash
```

---

## Run

```bash
streamlit run app.py
```

App runs at:

```text
http://localhost:8510
```

---

## Index Documents

```bash
python index_uploads.py --folder data/uploads/originals --embedding-provider local_hash
```

---

## Evaluation

FinSight includes a deterministic, credential-free retrieval benchmark that exercises the production Qdrant, BM25, and reciprocal-rank-fusion paths over 18 synthetic finance chunks and 18 human-labeled queries.

```bash
python eval_retrieval.py \
  --top-k 3 \
  --output evals/results/latest.json \
  --min-hybrid-recall 0.90
```

Current version 1.0 baseline:

| Mode | Recall@3 | Hit rate@3 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: |
| Dense local hash | 0.944 | 0.944 | 0.861 | 0.883 |
| BM25 | 1.000 | 1.000 | 0.972 | 0.979 |
| Hybrid RRF | 0.944 | 0.944 | 0.889 | 0.903 |

BM25 performs best on this small lexical benchmark. The result is reported as-is rather than presenting hybrid retrieval as universally superior. See [the evaluation methodology](docs/evaluation.md) for metric definitions, limitations, per-case failure analysis, and the next evaluation layers.

---

## Technical Highlights

* Router-first architecture
* Hybrid RAG (Qdrant + BM25)
* RRF fusion strategy
* Context-aware chunk selection
* Structured LLM output
* Multimodal reasoning
* Automatic web grounding
* Verification layer (VeriFi)
* Quota-resilient design

---
