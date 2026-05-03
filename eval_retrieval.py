from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import load_settings
from gemini_client import GeminiClient
from retrieval import HybridRetriever


def run_eval(path: Path, top_k: int) -> tuple[int, int]:
    settings = load_settings()
    gemini = GeminiClient(settings)
    retriever = HybridRetriever(
        collection_name=settings.qdrant_collection,
        qdrant_path=settings.qdrant_path,
        gemini=gemini,
    )

    cases = json.loads(path.read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        hits = retriever.hybrid_search(case["query"], limit=top_k)
        sources = [hit.chunk.source_name for hit in hits]
        ok = case["expected_source"] in sources
        passed += int(ok)
        status = "PASS" if ok else "FAIL"
        print(f"{status} | {case['query']}")
        print(f"  expected: {case['expected_source']}")
        print(f"  got:      {sources}")

    retriever.client.close()
    return passed, len(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FinSight retrieval checks.")
    parser.add_argument("--cases", default="evals/retrieval_eval.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    passed, total = run_eval(Path(args.cases), args.top_k)
    print(f"Retrieval eval: {passed}/{total} passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
