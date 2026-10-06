"""Actual ingestion/retrieval/orchestration evaluation; no oracle answers are injected."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from config import load_settings
from evaluation.budget import EvaluationBudget
from evaluation.metrics import aggregate_metrics, evaluate_ranking, percentile
from evaluation.scoring import VERSION as SCORER_VERSION
from evaluation.scoring import score_outcome
from ingestion import ingest_file
from llm_prompts import PROMPT_VERSION
from openai_client import OpenAIClient
from orchestration import ResearchAssistant, provider_failure_reason
from retrieval import HybridRetriever
from storage_io import atomic_replace

ROOT = Path(__file__).resolve().parents[1]


def provenance(dataset_path, provider):
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    code_files = sorted(
        {
            ROOT / name
            for name in names
            if (ROOT / name).is_file() and not any(
                part.startswith(".") or part in {"data", "__pycache__"}
                for part in Path(name).parts
            )
        }
    )
    digest = hashlib.sha256()
    for p in code_files:
        digest.update(p.relative_to(ROOT).as_posix().encode())
        digest.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty_worktree": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        ),
        "code_digest": digest.hexdigest(),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in [
                "pydantic",
                "qdrant-client",
                "rank-bm25",
                "openai",
                "pdfplumber",
                "PyMuPDF",
                "streamlit",
                "numpy",
            ]
        },
        "embedding_provider": provider.settings.embedding_provider,
        "embedding_model": provider.embedding_model,
        "dimensions": provider.embedding_dimensions,
        "llm_provider": "openai",
        "text_model": provider.settings.openai_model,
        "prompt_version": PROMPT_VERSION,
        "ingestion_version": "financial-lines-v3",
        "cost_usd": None,
        "cost_reason": "Provider invoices/prices are not inferred; token usage is reported where available.",
        "label_review": "agent-authored; not independently human-reviewed",
    }


def answer_correct(case, response):
    return score_outcome(case, response)


def _summarize(records):
    if not records:
        return {
            "cases": 0,
            "answer_correctness": None,
            "reason": "No completed requests in this group.",
        }
    expected_answerable = [r for r in records if r["expected_status"] == "ok"]
    accepted = [r for r in records if r["response"]["status"] == "ok"]
    unsupported = [r for r in records if r["expected_status"] != "ok"]
    abstained = [
        r
        for r in records
        if r["response"]["status"] in {"abstained", "clarification", "unsupported"}
    ]
    tp = sum(r["expected_status"] != "ok" for r in abstained)

    def ratio(n, d):
        return round(n / d, 4) if d else None

    return {
        "cases": len(records),
        "answer_correctness": ratio(sum(r["correct"] for r in records), len(records)),
        "answer_coverage": ratio(len(accepted), len(records)),
        "answerable_coverage": ratio(
            sum(r["response"]["status"] == "ok" for r in expected_answerable),
            len(expected_answerable),
        ),
        "over_abstention": ratio(
            sum(r["response"]["status"] != "ok" for r in expected_answerable),
            len(expected_answerable),
        ),
        "unsupported_answer_rate": ratio(
            sum(r["response"]["status"] == "ok" for r in unsupported), len(unsupported)
        ),
        "abstention_precision": ratio(tp, len(abstained)),
        "abstention_recall": ratio(tp, len(unsupported)),
        "numerical_accuracy_on_accepted": ratio(
            sum(r["correct"] for r in accepted), len(accepted)
        ),
        "citation_correctness_on_accepted": ratio(
            sum(
                r["citation_correct"] for r in accepted if r["case_requires_documents"]
            ),
            sum(r["case_requires_documents"] for r in accepted),
        ),
        "final_context_evidence_coverage": ratio(
            sum(r["context_coverage"] for r in expected_answerable),
            len(expected_answerable),
        ),
        "latency_ms_mean": round(
            statistics.mean(
                r["response"]["diagnostics"].get("total_ms", 0) for r in records
            ),
            3,
        ),
        "retrieval": aggregate_metrics(
            [
                evaluate_ranking(r["retrieved_ids"], set(r["relevant_ids"]), 3)
                for r in expected_answerable
                if r["relevant_ids"]
            ]
        ),
        "claim_support": "Complete canonical fact tuples and authoritative tool labels; general semantic entailment is not measured.",
    }


def summarize(records):
    result = _summarize(records)
    if not records:
        return result
    accepted = [r for r in records if r["response"]["status"] == "ok"]
    facts = [r for r in accepted if r["response"]["claims"]]
    tools = [r for r in accepted if r["response"]["calculations"]]
    result["denominators"] = {
        "completed": len(records),
        "accepted": len(accepted),
        "accepted_fact_answers": len(facts),
        "accepted_calculations": len(tools),
        "expected_answerable": sum(r["expected_status"] == "ok" for r in records),
        "expected_rejections": sum(r["expected_status"] != "ok" for r in records),
    }
    result["supported_claim_accuracy_on_accepted"] = (
        sum(r["correct"] for r in facts) / len(facts) if facts else None
    )
    result["tool_accuracy_on_accepted"] = (
        sum(r["correct"] for r in tools) / len(tools) if tools else None
    )
    result["citation_reference_validity_on_accepted"] = (
        sum(r.get("citation_reference_valid", False) for r in accepted) / len(accepted)
        if accepted
        else None
    )
    result["citation_support_scope"] = (
        "Mandatory bound-record/excerpt guard plus label outcome checks; no independent general prose entailment judge."
    )
    result["ranking_label_scope"] = (
        "Source/page labels: text/table duplicates on a relevant page count as relevant; selected-context coverage is also coarse page coverage."
    )
    result["latency_ms"] = {
        stage: {
            "n": len(values),
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
        }
        for stage in ["total", "retrieval", "tools", "generation"]
        if (
            values := [
                r["response"]["diagnostics"].get("total_ms", 0)
                if stage == "total"
                else r["response"]["diagnostics"]
                .get("stages_ms", {})
                .get(stage + "_ms")
                for r in records
                if stage == "total"
                or stage + "_ms" in r["response"]["diagnostics"].get("stages_ms", {})
            ]
        )
    }
    result["per_route"] = {
        route: {
            "cases": len(group),
            "correct": sum(r["correct"] for r in group),
            "accepted": sum(r["response"]["status"] == "ok" for r in group),
        }
        for route in sorted(
            {r["response"]["diagnostics"]["route"]["route"] for r in records}
        )
        if (
            group := [
                r
                for r in records
                if r["response"]["diagnostics"]["route"]["route"] == route
            ]
        )
    }
    return result


def finalize_report(report):
    """Null scores and missing slots describe unrun work, never zero accuracy."""
    records = report["records"]
    modes = list(dict.fromkeys(p["mode"] for p in report["planned_requests"]))
    attempted = {(r["id"], r["mode"], r["repeat"]) for r in records}
    report["missing_requests"] = [
        dict(p, status="not_run", reason="Evaluation stopped before this request.")
        for p in report["planned_requests"]
        if (p["id"], p["mode"], p["repeat"]) not in attempted
    ]
    report["summary"] = {
        mode: {
            group: summarize(
                [
                    r
                    for r in records
                    if r["mode"] == mode and (group == "all" or r["split"] == group)
                ]
            )
            for group in ["all", "development", "held_out"]
        }
        for mode in modes
    }
    report["completed_cases"] = len(records)
    report["openai_response_count"] = sum(
        bool(r["response"]["diagnostics"].get("provider_used")) for r in records
    )
    report["successful_openai_calls"] = sum(
        r["response"]["diagnostics"].get("provider_request", {}).get("validation")
        == "schema_valid"
        for r in records
    )
    report["complete"] = (
        not report["failures"] and len(records) == report["planned_cases"]
    )
    report["repeat_status"] = {mode: [] for mode in modes}
    for mode in modes:
        for repeat in range(report["repeats"]):
            group = [r for r in records if r["mode"] == mode and r["repeat"] == repeat]
            planned = sum(
                p["mode"] == mode and p["repeat"] == repeat
                for p in report["planned_requests"]
            )
            report["repeat_status"][mode].append(
                {
                    "repeat": repeat,
                    "planned": planned,
                    "completed": len(group),
                    "status": "complete"
                    if len(group) == planned
                    else ("partial" if group else "not_run"),
                    "answer_correctness": summarize(group)["answer_correctness"],
                }
            )
    if report["repeats"] > 1:
        report["observed_variability"] = {
            mode: [g["answer_correctness"] for g in groups]
            for mode, groups in report["repeat_status"].items()
        }


def write_report(report, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pending.json")
    data = json.dumps(report, indent=2).encode("utf-8")
    temporary.write_bytes(
        gzip.compress(data, mtime=0) if destination.suffix == ".gz" else data
    )
    atomic_replace(temporary, destination)


def run(
    dataset_path=ROOT / "evals/application_benchmark.json",
    embedding_provider="local_hash",
    live=False,
    repeats=1,
    split="all",
    limit=None,
    modes=None,
    checkpoint=None,
    budget=None,
):
    dataset_path = Path(dataset_path)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    settings = replace(load_settings(), embedding_provider=embedding_provider)
    if settings.openai_eval_model:
        settings = replace(settings, openai_model=settings.openai_eval_model)
    if budget:
        settings = replace(
            settings,
            openai_max_output_tokens=min(settings.openai_max_output_tokens, 1024),
        )
    provider = OpenAIClient(settings, budget=budget)
    report = {
        "benchmark": "finsight-application-bound-labels-v3",
        "dataset_version": dataset["version"],
        "metadata": provenance(dataset_path, provider),
        "live_generation": live,
        "repeats": repeats,
        "split": split,
        "records": [],
        "failures": [],
    }
    report["metadata"].update(
        scorer_version=SCORER_VERSION,
        code_digest_format="sorted Git-visible POSIX paths + UTF-8 file bytes, CRLF normalized to LF",
        dataset_digest_format="dataset raw bytes; original historical SHA retained",
        dataset_canonical_sha256=hashlib.sha256(
            json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        dataset_path=dataset_path.relative_to(ROOT).as_posix()
        if dataset_path.is_relative_to(ROOT)
        else str(dataset_path),
    )
    cases = [c for c in dataset["cases"] if split == "all" or c["split"] == split]
    if limit:
        cases = cases[:limit]
    selected_modes = modes or ["bm25", "dense", "hybrid"]
    report["planned_requests"] = [
        {"id": c["id"], "mode": m, "repeat": r, "split": c["split"]}
        for m in selected_modes
        for r in range(repeats)
        for c in cases
    ]
    report["planned_cases"] = len(report["planned_requests"])
    if live and not settings.openai_configured:
        report["failures"].append(
            {
                "type": "Configuration",
                "reason": "OPENAI_API_KEY is unavailable; no live OpenAI requests were made.",
            }
        )
        finalize_report(report)
        if checkpoint:
            write_report(report, checkpoint)
        return report
    with tempfile.TemporaryDirectory(prefix="finsight-app-eval-") as directory:
        retriever = HybridRetriever(
            "evaluation", str(Path(directory) / "qdrant"), provider
        )
        try:
            chunks = []
            for doc in dataset["documents"]:
                path = ROOT / doc["path"]
                if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
                    raise ValueError("Fixture digest differs from frozen manifest")
                chunks.extend(ingest_file(path, source_name=doc["source_name"]))
            retriever.index_chunks(chunks)
            provider.embed_queries([c["query"] for c in cases])
            for mode in selected_modes:
                service = ResearchAssistant(retriever, provider, mode)
                for repeat in range(repeats):
                    for case in cases:
                        response = service.ask(
                            case["query"], case["sources"], use_provider=live
                        )
                        selected = response.diagnostics.get("evidence", [])
                        pages = {
                            h["chunk"]["page"]
                            for h in selected
                            if h["chunk"]["source_name"] in case["sources"]
                        }
                        relevant = [
                            c.id
                            for c in chunks
                            if c.source_name in case["sources"]
                            and c.page in case["required_pages"]
                            and c.type.value != "image"
                        ]
                        retrieved = response.diagnostics.get(
                            "retrieval_candidate_ids", []
                        )
                        citation_correct = bool(response.citations) and all(
                            c.source_name in case["sources"]
                            and c.page in case["required_pages"]
                            for c in response.citations
                        )
                        citation_reference_valid = (
                            bool(response.citations)
                            and all(
                                c.chunk_id in {h["chunk"]["id"] for h in selected}
                                for c in response.citations
                            )
                            and all(
                                set(c.citation_ids).issubset(
                                    {ref.chunk_id for ref in response.citations}
                                )
                                and bool(c.citation_ids)
                                for c in response.claims
                            )
                        )
                        report["records"].append(
                            {
                                "id": case["id"],
                                "mode": mode,
                                "repeat": repeat,
                                "split": case["split"],
                                "query": case["query"],
                                "expected_status": case["expected_status"],
                                "expected_value": case["expected_value"],
                                "case_requires_documents": True,
                                "correct": answer_correct(case, response),
                                "citation_correct": citation_correct,
                                "context_coverage": len(
                                    pages.intersection(case["required_pages"])
                                )
                                / len(case["required_pages"]),
                                "retrieved_ids": retrieved,
                                "relevant_ids": relevant,
                                "response": response.model_dump(mode="json"),
                                "provider_raw_output": getattr(
                                    provider, "last_response", None
                                )
                                if live
                                else None,
                            }
                        )
                        report["records"][-1]["citation_reference_valid"] = (
                            citation_reference_valid
                        )
                        if checkpoint:
                            finalize_report(report)
                            write_report(report, checkpoint)
                        if live and len(report["records"]) % 10 == 0:
                            print(
                                f"Completed {len(report['records'])} live cases",
                                flush=True,
                            )
                        if live and response.status == "provider_failure":
                            report["failures"].append(
                                {
                                    "type": "ProviderFailure",
                                    "reason": response.answer,
                                    "last_case": case["id"],
                                    "error_code": response.diagnostics.get(
                                        "provider_request", {}
                                    ).get("error_code"),
                                    "completion": "Live evaluation stopped after provider failure; completed requests are retained.",
                                }
                            )
                            raise RuntimeError("Provider evaluation stopped")
        except (Exception, KeyboardInterrupt) as exc:
            if not report["failures"]:
                report["failures"].append(
                    {
                        "type": type(exc).__name__,
                        "reason": "Evaluation interrupted."
                        if isinstance(exc, KeyboardInterrupt)
                        else provider_failure_reason(exc),
                    }
                )
        finally:
            retriever.close()
    report["embedding_requests"] = provider.embedding_requests
    finalize_report(report)
    if checkpoint:
        write_report(report, checkpoint)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--embedding-provider",
        choices=["local_hash", "minilm", "gemini", "openai"],
        default="local_hash",
    )
    p.add_argument(
        "--dataset", type=Path, default=ROOT / "evals/repair_v3/application.json"
    )
    p.add_argument("--budget-usd", type=float)
    p.add_argument("--budget-ledger", default=".test-tmp/openai-repair-budget.json")
    p.add_argument("--live", action="store_true")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--split", choices=["all", "development", "held_out"], default="all")
    p.add_argument("--limit", type=int)
    p.add_argument("--output", default=None)
    p.add_argument("--quality-gate", action="store_true")
    p.add_argument("--mode", choices=["bm25", "dense", "hybrid"], action="append")
    args = p.parse_args()
    if args.repeats < 1:
        p.error("repeats must be positive")
    if args.output is None:
        args.output = (
            "evals/repair_v3/results/live.json.gz"
            if args.live
            else "evals/repair_v3/results/offline.json.gz"
        )
    if (
        args.live or args.embedding_provider in {"openai", "gemini"}
    ) and args.budget_usd is None:
        p.error(
            "Paid evaluation requires an explicitly authorized --budget-usd cap and ledger."
        )
    budget = (
        EvaluationBudget(args.budget_usd, args.budget_ledger)
        if args.budget_usd is not None
        else None
    )
    report = run(
        dataset_path=args.dataset.resolve(),
        embedding_provider=args.embedding_provider,
        live=args.live,
        repeats=args.repeats,
        split=args.split,
        limit=args.limit,
        modes=args.mode,
        checkpoint=args.output if args.live else None,
        budget=budget,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, output)
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "failures": report["failures"],
                "output": str(output),
            },
            indent=2,
        )
    )
    if args.live and not report["complete"]:
        raise SystemExit(
            "Live OpenAI evaluation incomplete; inspect failures and missing_requests in the report."
        )
    if args.quality_gate:
        summaries = [groups["all"] for groups in report["summary"].values()]
        if (
            not report["complete"]
            or not summaries
            or any(
                (s["answer_correctness"] or 0) < 0.95
                or (s["answerable_coverage"] or 0) < 0.9
                or (s["unsupported_answer_rate"] or 0) > 0
                for s in summaries
            )
        ):
            raise SystemExit("Application quality gate failed")


if __name__ == "__main__":
    main()
