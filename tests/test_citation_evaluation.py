from evaluation.citations import evaluate_citations


def test_citation_benchmark_reports_known_validation_boundary() -> None:
    report = evaluate_citations("evals/citation_benchmark.json")

    assert report["cases"] == 11
    assert report["abstention_precision"] == 1.0
    assert report["abstention_recall"] == 0.8571
    assert report["decision_accuracy"] == 0.9091

    semantic_failure = next(
        result for result in report["results"]
        if result["id"] == "wrong-valid-nonnumeric-citation"
    )
    assert semantic_failure["expected_abstain"] is True
    assert semantic_failure["predicted_abstain"] is False

    numeric_mismatch = next(
        result for result in report["results"]
        if result["id"] == "wrong-valid-numeric-citation"
    )
    assert numeric_mismatch["predicted_abstain"] is True
