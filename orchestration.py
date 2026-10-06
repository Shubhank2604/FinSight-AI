"""UI-independent application requests, evidence extraction and failure recovery."""

from __future__ import annotations

import re
import time

from calculation_inputs import InputIssue, extract_calculation_inputs
from fallback_answers import local_educational_answer
from financial_evidence import METRICS, extract_facts, select_fact
from router.intent_router import route_query
from schemas import AnswerClaim, Route, StructuredLLMAnswer, VerifiedResponse
from tools import calculate_emi, simulate_portfolio_growth
from tools.research import calculate_document_operation
from verifier.verifi import verify_response


def run_query_tool(query, tool):
    model, provenance = extract_calculation_inputs(query, tool)
    values = model.model_dump()
    if tool == "emi_calculator":
        values.pop("rate_convention")
        result = calculate_emi(**values)
    else:
        result = simulate_portfolio_growth(**values)
    if result.calculation:
        result.calculation.provenance = provenance
    return result


def document_tool(query, tool, hits):
    if tool not in {"emi_calculator", "portfolio_growth_simulator"}:
        return calculate_document_operation(query, tool, hits)
    # Document inputs require an unambiguous labeled complete record. Query overrides
    # are explicit complete scenarios; partial overrides are clarified instead of guessed.
    try:
        query_model, origins = extract_calculation_inputs(query, tool)
    except InputIssue as exc:
        if (
            exc.status == "unsupported"
            or "Conflicting" in str(exc)
            or "Nonfinite" in str(exc)
        ):
            raise
        query_model = None
    if query_model:
        result = run_query_tool(query, tool)
        result.calculation.assumptions.append(
            "Complete explicit query inputs take precedence over document values."
        )
        return result
    # Prevent silently discarding partial query input overrides.
    if re.search(
        r"\d\s*%|\$\s*\d|\b(?:USD|CAD|AUD|EUR|INR)\s*\d|\d+\s*(?:years?|months?)\b",
        query,
        re.I,
    ):
        raise InputIssue(
            "Partial query overrides need clarification. Specify a complete scenario or use only document values."
        )
    candidates = []
    for hit in hits:
        try:
            model, origins = extract_calculation_inputs(hit.chunk.content, tool)
        except InputIssue:
            continue
        for origin in origins.values():
            origin.update(
                source="document",
                chunk_id=hit.chunk.id,
                page=hit.chunk.page,
                source_name=hit.chunk.source_name,
            )
        candidates.append((model, origins))
    # Check every selected loan fragment even when one complete record exists.
    # Otherwise a complete scenario can conceal a conflicting partial override.
    if hits:
        groups = {}
        for hit in hits:
            groups.setdefault(
                (hit.chunk.document_id, hit.chunk.source_name), []
            ).append(hit)
        for group in groups.values():
            group = [
                h
                for h in group
                if re.search(
                    r"principal|loan|mortgage|interest rate|annual rate|duration|tenure|monthly (?:investment|contribution)|initial (?:balance|amount)|annual return|step.up",
                    h.chunk.content,
                    re.I,
                )
            ]
            # Joining is supported within one document and compatible explicit metadata.
            from financial_evidence import _headers
            scopes = [_headers(h.chunk.content, h.chunk.metadata) for h in group]
            if any(len({str(scope[k]).casefold() for scope in scopes if k in scope}) > 1
                   for k in ["entity", "period", "currency"]):
                raise InputIssue("Loan fragments have conflicting company, period or currency; select one complete scenario.", "abstained")
            pieces = [(h, h.chunk.content) for h in group]
            merged = "\n".join(text for _, text in pieces)
            try:
                model, origins = extract_calculation_inputs(merged, tool)
            except InputIssue as exc:
                if "Conflicting" in str(exc) or exc.status == 'unsupported':
                    raise InputIssue(str(exc), "abstained") from exc
                continue
            for origin in origins.values():
                offset = 0
                for h, text in pieces:
                    if offset <= origin["start"] < offset + len(text):
                        if origin['end'] > offset + len(text):
                            raise InputIssue('A calculation field is split across chunks; provide the complete labeled field.', 'abstained')
                        origin.update(
                            source="document",
                            chunk_id=h.chunk.id,
                            page=h.chunk.page,
                            source_name=h.chunk.source_name,
                            combined_evidence=True,
                        )
                        origin["start"] -= offset
                        origin["end"] -= offset
                        break
                    offset += len(text) + 1
            candidates.append((model, origins))
    if not candidates:
        raise InputIssue(
            "No complete labeled calculation inputs were found in the selected evidence.",
            "abstained",
        )
    if len({m.model_dump_json() for m, _ in candidates}) != 1:
        raise InputIssue(
            "Conflicting document calculation inputs; select one document/period.",
            "abstained",
        )
    model, origins = candidates[0]
    values = model.model_dump()
    if tool == "emi_calculator":
        values.pop("rate_convention")
        result = calculate_emi(**values)
    else:
        result = simulate_portfolio_growth(**values)
    if result.calculation:
        result.calculation.provenance = origins
        result.calculation.assumptions.append(
            "Document values are used; partial query overrides require clarification."
        )
    return result


def document_fact_answer(query, hits):
    facts = extract_facts(hits)
    metrics = [m for m, pattern in METRICS.items() if re.search(pattern, query, re.I)]
    periods = sorted({int(y) for y in re.findall(r"\b20\d{2}\b", query)})
    entities = {f.entity for f in facts}
    named = [entity for entity in entities if entity.casefold() in query.casefold()]
    if len(named) > 1 or (not named and len(entities) > 1):
        raise InputIssue("Specify one company or select one document.")
    entity = named[0] if named else next(iter(entities), None)
    claims = []
    if metrics:
        for metric in metrics:
            for period in periods or [None]:
                fact = select_fact(facts, metric, period, entity)
                claims.append(
                    AnswerClaim(
                        text=f"{fact.entity} {fact.period} {metric.replace('_', ' ')}: {fact.currency} {fact.value}.",
                        citation_ids=[fact.chunk_id],
                    )
                )
    else:
        keywords = set(re.findall(r"\b\w+\b", query.lower())) - {
            "what",
            "is",
            "are",
            "the",
            "a",
            "an",
            "in",
            "this",
            "report",
            "document",
            "uploaded",
            "explain",
            "summarize",
            "summarise",
            "according",
            "to",
            "of",
            "for",
            "please",
        }
        for hit in hits:
            for line in hit.chunk.content.splitlines():
                overlap = keywords.intersection(re.findall(r"\b\w+\b", line.lower()))
                if keywords and len(overlap) / len(keywords) >= 0.6:
                    claims.append(
                        AnswerClaim(
                            text="Source excerpt: " + line.strip(),
                            citation_ids=[hit.chunk.id],
                        )
                    )
                    break
        if not claims:
            raise InputIssue(
                "The selected evidence does not contain the requested fact.",
                "abstained",
            )
    return StructuredLLMAnswer(
        answer="\n".join(c.text for c in claims),
        claims=claims,
        used_citation_ids=sorted({i for c in claims for i in c.citation_ids}),
        confidence=1.0,
    )


def provider_failure_reason(exc):
    from embeddings import EmbeddingError
    from evaluation.budget import BudgetExceeded
    from openai_client import ProviderError

    if isinstance(exc, BudgetExceeded):
        return str(exc)
    if isinstance(exc, (ProviderError, EmbeddingError)):
        return str(exc)
    message = str(exc).lower()
    if any(word in message for word in ("429", "quota", "resource_exhausted")):
        return "Provider quota exhausted; retry later or use offline document facts/calculators."
    if "timeout" in message or "timed out" in message:
        return "Provider timed out; retry or use offline mode."
    if "json" in message or "validation" in message or "schema" in message:
        return "Provider returned invalid structured output; retry the request."
    if "404" in message or "not_found" in message:
        return "The configured provider model is unavailable; select an available model and retry."
    if "401" in message or "authentication" in message:
        return "Provider authentication failed; verify OPENAI_API_KEY."
    if "403" in message or "permission_denied" in message:
        return "Provider access was denied; verify API permissions and credentials."
    if "400" in message or "invalid_argument" in message:
        return "Provider rejected the model/request settings; verify model and tool compatibility."
    return "Provider request failed; check credentials, connectivity and model settings, then retry."


class ResearchAssistant:
    def __init__(self, retriever=None, provider=None, retrieval_mode="hybrid"):
        self.retriever, self.provider = retriever, provider
        self.retrieval_mode = retrieval_mode

    def ask(
        self,
        query: str,
        source_names: list[str] | None = None,
        allow_web=False,
        use_provider=False,
    ) -> VerifiedResponse:
        started = time.perf_counter()
        if self.provider is not None:
            self.provider.last_response = None
            self.provider.last_usage = None
        stages = {}
        hits, tool_results, raw = [], [], []
        available = bool(
            self.retriever
            and any(
                c.source_name in (source_names or []) for c in self.retriever.chunks
            )
        )
        decision = route_query(
            query, has_documents=available, has_images=available, allow_web=allow_web
        )
        try:
            if decision.route == Route.ABSTAIN:
                response = verify_response("", decision)
            elif decision.route in {
                Route.MULTIMODAL_REASONING,
                Route.WEB_GROUNDED_ANSWER,
            }:
                # Metadata preservation is implemented in the provider adapter; visual
                # entailment and external freshness remain outside verified scope.
                if (
                    decision.route == Route.WEB_GROUNDED_ANSWER
                    and allow_web
                    and use_provider
                    and self.provider
                ):
                    t = time.perf_counter()
                    structured, citations = self.provider.generate_web_grounded_answer(
                        query
                    )
                    stages["generation_ms"] = (time.perf_counter() - t) * 1000
                    response = VerifiedResponse(
                        answer=structured.answer,
                        citations=citations,
                        assumptions=structured.assumptions,
                        status="experimental",
                        reasons=[
                            "Experimental web output; citation annotations are preserved, but factual accuracy and freshness are not verified."
                        ],
                    )
                else:
                    response = VerifiedResponse(
                        answer="This capability is experimental and is excluded from verified answers.",
                        status="unsupported",
                        reasons=[decision.reason],
                    )
            else:
                if decision.required_retrieval:
                    t = time.perf_counter()
                    if source_names is None:
                        raise InputIssue(
                            "Select documents explicitly for each document request."
                        )
                    if self.retrieval_mode == "bm25":
                        raw = self.retriever.sparse_search(
                            query, limit=16, source_names=source_names
                        )
                    elif self.retrieval_mode == "dense":
                        raw = self.retriever.dense_search(
                            query, limit=16, source_names=source_names
                        )
                    else:
                        raw = self.retriever.hybrid_search(
                            query, limit=48, dense_limit=24, sparse_limit=24,
                            source_names=source_names
                        )
                    hits = self.retriever.select_context_hits(query, raw, limit=8)
                    stages["retrieval_ms"] = (time.perf_counter() - t) * 1000
                if decision.required_tools:
                    t = time.perf_counter()
                    for tool in decision.required_tools:
                        tool_results.append(
                            document_tool(query, tool, hits)
                            if decision.required_retrieval
                            else run_query_tool(query, tool)
                        )
                    stages["tools_ms"] = (time.perf_counter() - t) * 1000
                    response = verify_response("", decision, hits, tool_results)
                elif decision.required_retrieval:
                    t = time.perf_counter()
                    expected_claims = None
                    if any(
                        re.search(pattern, query, re.I) for pattern in METRICS.values()
                    ):
                        # Detect absent/conflicting typed facts before provider generation.
                        expected_claims = document_fact_answer(query, hits).claims
                    structured = (
                        self.provider.generate_grounded_answer(query, hits, [])
                        if use_provider and self.provider
                        else document_fact_answer(query, hits)
                    )
                    if use_provider and self.provider is None:
                        raise RuntimeError("Provider credentials missing")
                    stages["generation_ms"] = (time.perf_counter() - t) * 1000
                    response = verify_response(
                        "", decision, hits, structured_answer=structured, expected_claims=expected_claims
                    )
                else:
                    if use_provider:
                        if self.provider is None:
                            raise RuntimeError(
                                "OPENAI_API_KEY is required for provider generation."
                            )
                        t = time.perf_counter()
                        structured = self.provider.generate_educational_answer(query)
                        stages["generation_ms"] = (time.perf_counter() - t) * 1000
                        response = verify_response(
                            "", decision, structured_answer=structured
                        )
                        response.assumptions.append(
                            "General financial education generated by OpenAI; factual accuracy is not established by schema validation."
                        )
                    else:
                        response = VerifiedResponse(
                            answer=local_educational_answer(query),
                            status="ok",
                            assumptions=[
                                "General education uses a local template; each query is independent."
                            ],
                        )
        except InputIssue as exc:
            response = VerifiedResponse(
                answer=str(exc), status=exc.status, reasons=[str(exc)], confidence=0.0
            )
        except Exception as exc:
            response = VerifiedResponse(
                answer=provider_failure_reason(exc),
                status="provider_failure",
                reasons=[provider_failure_reason(exc)],
                confidence=0.0,
            )
        response.diagnostics.update(
            route=decision.model_dump(mode="json"),
            stages_ms=stages,
            total_ms=(time.perf_counter() - started) * 1000,
            retrieval_candidate_ids=[h.chunk.id for h in raw],
            selected_chunk_ids=[h.chunk.id for h in hits],
            evidence=[h.model_dump(mode="json") for h in hits],
            query_scope=source_names,
            independent_query=True,
            provider_used=use_provider
            and self.provider is not None
            and self.provider.last_response is not None,
            provider_usage=getattr(self.provider, "last_usage", None),
        )
        telemetry = getattr(self.provider, "last_response", None)
        response.diagnostics["provider_used"] = bool(
            telemetry and telemetry.get("response_id")
        )
        response.diagnostics["provider_request"] = {
            key: value
            for key, value in (telemetry or {}).items()
            if key not in {"text", "output"}
        }
        return response
