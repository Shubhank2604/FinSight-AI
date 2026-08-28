from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import mean


@dataclass(frozen=True)
class RankingMetrics:
    precision_at_k: float
    recall_at_k: float
    hit_rate_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float

    def as_dict(self) -> dict[str, float]:
        return {key: round(value, 6) for key, value in asdict(self).items()}


def evaluate_ranking(
    retrieved_ids: list[str], relevant_ids: set[str], top_k: int
) -> RankingMetrics:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")

    ranked = retrieved_ids[:top_k]
    relevant_ranks = [
        rank for rank, chunk_id in enumerate(ranked, start=1) if chunk_id in relevant_ids
    ]
    hit_count = len(relevant_ranks)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_hits = min(len(relevant_ids), top_k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

    return RankingMetrics(
        precision_at_k=hit_count / top_k,
        recall_at_k=hit_count / len(relevant_ids),
        hit_rate_at_k=float(hit_count > 0),
        reciprocal_rank=(1.0 / relevant_ranks[0]) if relevant_ranks else 0.0,
        ndcg_at_k=(dcg / ideal_dcg) if ideal_dcg else 0.0,
    )


def aggregate_metrics(metrics: list[RankingMetrics]) -> dict[str, float]:
    if not metrics:
        raise ValueError("metrics must not be empty")

    fields = RankingMetrics.__dataclass_fields__
    return {
        field: round(mean(getattr(item, field) for item in metrics), 6)
        for field in fields
    }


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= percentile_value <= 100.0:
        raise ValueError("percentile must be between 0 and 100")

    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
