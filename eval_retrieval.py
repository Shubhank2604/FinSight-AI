from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.benchmark import markdown_summary, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic FinSight retrieval benchmark."
    )
    parser.add_argument("--dataset", default="evals/retrieval_benchmark.json")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--min-hybrid-recall",
        type=float,
        default=None,
        help="Exit non-zero when hybrid Recall@K is below this threshold.",
    )
    args = parser.parse_args()

    report = run_benchmark(Path(args.dataset), top_k=args.top_k)
    print(markdown_summary(report))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote detailed report to {output_path}")

    hybrid_recall = report["summary"]["hybrid"]["recall_at_k"]
    if args.min_hybrid_recall is not None and hybrid_recall < args.min_hybrid_recall:
        raise SystemExit(
            f"Hybrid Recall@{args.top_k} {hybrid_recall:.3f} is below "
            f"required threshold {args.min_hybrid_recall:.3f}"
        )


if __name__ == "__main__":
    main()
