from __future__ import annotations

import argparse
import json

from evaluation.citations import evaluate_citations


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate claim/citation linkage and abstention.")
    parser.add_argument("--dataset", default="evals/citation_benchmark.json")
    parser.add_argument("--output")
    parser.add_argument("--min-abstention-recall", type=float, default=0.80)
    args = parser.parse_args()

    report = evaluate_citations(args.dataset)
    print(json.dumps(report, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
    if report["abstention_recall"] < args.min_abstention_recall:
        raise SystemExit(
            f"abstention recall {report['abstention_recall']:.3f} is below "
            f"{args.min_abstention_recall:.3f}"
        )


if __name__ == "__main__":
    main()
