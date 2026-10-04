"""Action and evidence are independent; document references take priority over keywords."""
from __future__ import annotations
import re
from schemas import ChunkType, Route, RouterDecision


def research_operation(query: str) -> str | None:
    for pattern, operation in [(r"year.over.year|yoy|growth", "yoy_growth"), (r"current ratio", "current_ratio"), (r"debt.to.equity", "debt_to_equity"), (r"operating margin", "operating_margin"), (r"(?:net|profit) margin", "margin")]:
        if re.search(pattern, query, re.I):
            return operation
    return None


def route_query(query: str, has_documents: bool = False, has_images: bool = False, allow_web: bool = False) -> RouterDecision:
    q = query.strip().lower()
    if not q:
        return RouterDecision(route=Route.ABSTAIN, missing_inputs=["query"], reason="Enter a question.")
    document = bool(re.search(r"\b(?:uploaded|attached|document|report|statement|filing|pdf|according to)\b", q))
    visual = bool(re.search(r"\b(?:image|screenshot|chart|graph|diagram|picture)\b", q))
    compute = bool(re.search(r"\b(?:calculate|compute|project|simulate|estimate|how much|what is (?:the )?emi)\b", q))
    current = bool(re.search(r"\b(?:latest|today|recent|news|online|web|stock price|exchange rate)\b|\bcurrent\b(?!\s+(?:ratio|assets|liabilities))", q))
    if document:
        if not has_documents:
            return RouterDecision(route=Route.ABSTAIN, required_retrieval=True, evidence_source="document", missing_inputs=["document_context"], reason="Select an indexed document for this document question.")
        if visual:
            return RouterDecision(route=Route.MULTIMODAL_REASONING, required_retrieval=True, evidence_source="visual", required_modalities=[ChunkType.IMAGE, ChunkType.TEXT], reason="Visual document analysis is experimental.")
        tool = None
        if compute:
            if re.search(r"\b(?:emi|loan|mortgage)\b", q):
                tool = "emi_calculator"
            elif re.search(r"portfolio|invest|future value", q):
                tool = "portfolio_growth_simulator"
            else:
                tool = research_operation(q)
            if not tool:
                return RouterDecision(route=Route.ABSTAIN, evidence_source="document", action="unsupported", reason="No supported document calculation matches this operation.")
        return RouterDecision(route=Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER if tool else Route.RETRIEVE_THEN_ANSWER, required_tools=[tool] if tool else [], required_retrieval=True, evidence_source="document", action="calculate" if tool else "answer", reason="Document facts require selected document evidence.")
    if current:
        return RouterDecision(route=Route.WEB_GROUNDED_ANSWER if allow_web else Route.ABSTAIN, evidence_source="web", missing_inputs=[] if allow_web else ["web_grounding_enabled"], reason="Current external information requires the visible web setting.")
    if visual:
        return RouterDecision(route=Route.MULTIMODAL_REASONING if has_images else Route.ABSTAIN, evidence_source="visual", required_modalities=[ChunkType.IMAGE], missing_inputs=[] if has_images else ["image"], reason="Visual analysis is experimental; provide a selected image.")
    tool = None
    if compute:
        if re.search(r"\bemi\b|\bloan\b|\bmortgage\b", q):
            tool = "emi_calculator"
        elif re.search(r"portfolio|invest|contribut|sip|future value", q):
            tool = "portfolio_growth_simulator"
        if tool:
            return RouterDecision(route=Route.COMPUTE_ONLY, required_tools=[tool], action="calculate", reason="Explicit deterministic calculation intent.")
    if re.search(r"\b(?:what is|what are|explain|how|about|tell me|retire|retirement|define)\b", q):
        return RouterDecision(route=Route.EDUCATIONAL_ANSWER, reason="General education; uploaded documents are not required by this question.")
    return RouterDecision(route=Route.ABSTAIN, action="unsupported", reason="Specify a supported financial question, document fact, or calculation.")
