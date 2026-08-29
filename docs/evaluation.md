# Evaluation methodology

FinSight separates retrieval evaluation from answer-generation evaluation. This first benchmark measures whether the system retrieves the evidence needed to answer a question; it does not claim that a retrieved passage guarantees a correct final answer.

## Benchmark design

`evals/retrieval_benchmark.json` contains 18 synthetic financial passages and 18 human-authored query/relevance labels. The cases span:

- company risk factors, segment results, and liquidity;
- brokerage allocation, fees, and tax lots;
- retirement-account and tax-credit rules;
- investor-presentation growth, margins, and supply constraints;
- mortgage resets, prepayment, and escrow; and
- withdrawal, sequence-of-returns, and inflation concepts.

The corpus is synthetic so the benchmark is small, redistributable, stable, and free of private financial documents. Every relevant ID is validated against the corpus before a run. Chunk IDs must be unique UUIDs, and case IDs must also be unique.

## Compared retrieval modes

The same production `HybridRetriever` is evaluated in three modes:

| Mode | Implementation | Purpose |
| --- | --- | --- |
| Dense | Qdrant cosine search with local hash vectors | Credential-free proxy for vector retrieval |
| Sparse | BM25 keyword retrieval | Exact-term and finance-vocabulary baseline |
| Hybrid | Reciprocal Rank Fusion over dense and sparse results | Current production fusion strategy |

Local hash embeddings are deterministic and useful for CI, but they are not a substitute for a semantic embedding model. A Gemini-embedding benchmark must be reported separately because it requires credentials, incurs cost, and may change across model versions.

## Metrics

- **Precision@K:** relevant chunks divided by K.
- **Recall@K:** labeled relevant chunks recovered in the first K results.
- **Hit rate@K:** fraction of cases with at least one relevant result.
- **MRR@K:** mean reciprocal rank of the first relevant result.
- **nDCG@K:** ranking quality with higher credit for relevant evidence near the top.
- **p50/p95 latency:** local wall-clock retrieval latency. These numbers are environment-specific and should not be treated as production service-level objectives.

## Version 1.0 baseline

The checked-in baseline uses K=3, Python 3.12, local hash embeddings, and no network access.

| Mode | Precision@3 | Recall@3 | Hit rate@3 | MRR@3 | nDCG@3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense | 0.315 | 0.944 | 0.944 | 0.861 | 0.883 |
| Sparse | 0.333 | 1.000 | 1.000 | 0.972 | 0.979 |
| Hybrid | 0.315 | 0.944 | 0.944 | 0.889 | 0.903 |

BM25 wins this deliberately lexical benchmark. Dense and hybrid retrieval both miss the brokerage-allocation case at K=3. That result is retained rather than hidden: it shows that reciprocal-rank fusion is not automatically better and that a weak local vector representation can lower hybrid recall.

CI requires hybrid Recall@3 of at least 0.90. This is a regression guard, not a claim of production accuracy.

## Reproduce

```bash
python eval_retrieval.py \
  --top-k 3 \
  --output evals/results/latest.json \
  --min-hybrid-recall 0.90
```

The JSON report includes aggregate metrics, per-case rankings, relevance labels, latency, dataset version, runtime, and embedding-provider metadata.

## Claim/citation linkage baseline

`evals/citation_benchmark.json` contains ten structured-answer cases. It covers correct citations, unknown IDs, missing claim citations, partially cited answers, explicit missing-data signals, extraneous IDs, and one intentionally wrong-but-valid citation.

| Metric | Baseline |
| --- | ---: |
| Citation precision | 0.750 |
| Citation recall | 0.643 |
| Abstention precision | 1.000 |
| Abstention recall | 0.833 |
| Accept/abstain accuracy | 0.900 |

The verifier now rejects claims with missing or unknown citation IDs. It still accepts the `wrong-valid-citation` case because the cited chunk exists even though the label says it does not support the claim. That failure is retained deliberately: the current layer validates citation linkage, not semantic entailment.

Reproduce it without credentials:

```bash
python eval_citations.py \
  --min-abstention-recall 0.80 \
  --output evals/results/citation_baseline.json
```

## Next evaluation layers

1. Add a licensed or authored real-document corpus with independently reviewed labels.
2. Compare local hash, Gemini embeddings, and additional embedding models under the same cases.
3. Add claim-level entailment scoring and independently reviewed support labels.
4. Track token usage, provider cost, end-to-end latency, and model/version metadata.
5. Split benchmark development and held-out test cases before tuning retrieval parameters.
