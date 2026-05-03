from __future__ import annotations

import re

from schemas import ChunkType, Route, RouterDecision


_MONEY_OR_NUMBER_PATTERN = re.compile(
    r"(\d+(\.\d+)?\s*(lakh|lac|crore|cr|k|m|million|%)?|\brs\.?\b|\binr\b|\$)",
    re.IGNORECASE,
)


def _has_any(query: str, terms: set[str]) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in terms)


def _has_number_or_money(query: str) -> bool:
    return bool(_MONEY_OR_NUMBER_PATTERN.search(query))


def _missing_compute_inputs(query: str, tool: str) -> list[str]:
    lowered = query.lower()
    missing = []

    if tool == "emi_calculator":
        if not _has_number_or_money(query):
            missing.extend(["principal", "annual_rate_pct", "tenure_months"])
        else:
            if not _has_any(lowered, {"year", "years", "month", "months", "tenure"}):
                missing.append("tenure_months")
            if not _has_any(lowered, {"%", "rate", "interest"}):
                missing.append("annual_rate_pct")
        return missing

    if tool == "portfolio_growth_simulator":
        if not _has_number_or_money(query):
            missing.extend(["monthly_investment", "annual_return_pct", "years"])
        else:
            if not _has_any(lowered, {"year", "years", "month", "months"}):
                missing.append("years")
            if not _has_any(lowered, {"%", "return", "rate", "cagr"}):
                missing.append("annual_return_pct")
        return missing

    return missing


def route_query(
    query: str,
    has_documents: bool = False,
    has_images: bool = False,
    allow_web: bool = False,
) -> RouterDecision:
    cleaned = query.strip()
    lowered = cleaned.lower()

    if not cleaned:
        return RouterDecision(
            route=Route.ABSTAIN,
            missing_inputs=["query"],
            reason="Empty query.",
        )

    image_terms = {
        "image",
        "screenshot",
        "chart",
        "graph",
        "shown",
        "visible",
        "picture",
        "diagram",
    }
    emi_terms = {"emi", "loan", "mortgage", "prepay", "prepayment"}
    portfolio_terms = {
        "invest",
        "investment",
        "portfolio",
        "sip",
        "future value",
        "monthly",
        "return",
    }
    educational_terms = {
        "about",
        "filing",
        "filings",
        "how should",
        "retire",
        "retirement",
        "sec",
        "tell me",
        "what is",
    }
    factual_terms = {
        "summarize",
        "summarise",
        "explain",
        "risk",
        "risks",
        "report",
        "statement",
        "annual report",
        "filing",
        "revenue",
        "cash flow",
        "balance sheet",
        "income statement",
    }
    web_terms = {
        "latest",
        "current",
        "today",
        "recent",
        "news",
        "web",
        "search",
        "online",
        "market price",
        "stock price",
        "exchange rate",
        "interest rate",
        "inflation",
    }

    if allow_web and _has_any(lowered, web_terms):
        return RouterDecision(
            route=Route.WEB_GROUNDED_ANSWER,
            required_retrieval=False,
            risk_level="medium",
            reason="Query asks for current or web-grounded information.",
        )

    if _has_any(lowered, web_terms):
        return RouterDecision(
            route=Route.ABSTAIN,
            missing_inputs=["web_grounding_enabled"],
            risk_level="medium",
            reason="Query asks for current information but web grounding is disabled.",
        )

    if _has_any(lowered, image_terms) or has_images:
        return RouterDecision(
            route=Route.MULTIMODAL_REASONING,
            required_retrieval=has_documents,
            required_modalities=[ChunkType.IMAGE, ChunkType.TEXT],
            risk_level="medium",
            reason="Query refers to visual evidence or an uploaded image.",
        )

    required_tools = []
    missing_inputs = []
    if _has_any(lowered, emi_terms):
        required_tools.append("emi_calculator")
        missing_inputs.extend(_missing_compute_inputs(cleaned, "emi_calculator"))
    elif _has_any(lowered, portfolio_terms) and _has_number_or_money(cleaned):
        required_tools.append("portfolio_growth_simulator")
        missing_inputs.extend(
            _missing_compute_inputs(cleaned, "portfolio_growth_simulator")
        )

    needs_retrieval = _has_any(lowered, factual_terms) or has_documents

    if missing_inputs:
        return RouterDecision(
            route=Route.ABSTAIN,
            required_tools=required_tools,
            required_retrieval=needs_retrieval,
            missing_inputs=sorted(set(missing_inputs)),
            risk_level="medium",
            reason="A deterministic calculation is requested but required inputs are missing.",
        )

    if required_tools and needs_retrieval:
        return RouterDecision(
            route=Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER,
            required_tools=required_tools,
            required_retrieval=True,
            risk_level="medium",
            reason="Query needs both document grounding and deterministic calculation.",
        )

    if required_tools:
        return RouterDecision(
            route=Route.COMPUTE_ONLY,
            required_tools=required_tools,
            risk_level="low",
            reason="Query can be answered by deterministic financial tools.",
        )

    if _has_any(lowered, educational_terms):
        return RouterDecision(
            route=Route.EDUCATIONAL_ANSWER,
            required_retrieval=has_documents,
            risk_level="low",
            reason="Query asks for a financial concept, method, or planning framework.",
        )

    if needs_retrieval:
        if not has_documents:
            return RouterDecision(
                route=Route.ABSTAIN,
                required_retrieval=True,
                missing_inputs=["document_context"],
                risk_level="medium",
                reason="Factual document-grounded query has no indexed documents.",
            )
        return RouterDecision(
            route=Route.RETRIEVE_THEN_ANSWER,
            required_retrieval=True,
            risk_level="medium",
            reason="Query asks for document-grounded facts or summarisation.",
        )

    return RouterDecision(
        route=Route.WEB_GROUNDED_ANSWER if allow_web else Route.ABSTAIN,
        missing_inputs=[] if allow_web else ["clear_financial_task_or_document_context"],
        risk_level="medium" if allow_web else "low",
        reason=(
            "No document/tool route matched; using explicit web grounding."
            if allow_web
            else "Query does not map to an MVP-supported route."
        ),
    )
