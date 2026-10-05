"""Mandatory validation precedes diagnostic scores; claims/tools are authoritative."""
from __future__ import annotations
import re
from decimal import Decimal
from financial_evidence import extract_facts, quantities, supported_numbers, supported_claim
from schemas import Citation, RetrievalHit, Route, RouterDecision, StructuredLLMAnswer, ToolResult, VerifiedResponse


def build_citations(hits: list[RetrievalHit], limit: int | None = None) -> list[Citation]:
    return [Citation(chunk_id=h.chunk.id, source_name=h.chunk.source_name, page=h.chunk.page, section=h.chunk.section, snippet=h.chunk.content[:350].strip()) for h in (hits if limit is None else hits[:limit])]


def claim_has_unsupported_numbers(claim, evidence_by_id: dict[str, str]) -> bool:
    return not supported_numbers(claim.text, '\n'.join(evidence_by_id[i] for i in claim.citation_ids if i in evidence_by_id))


def render_calculations(calculations) -> str:
    blocks = []
    for c in calculations:
        refs = sorted({p['chunk_id'] for p in c.provenance.values() if isinstance(p, dict) and p.get('chunk_id')})
        suffix = ' ' + ' '.join(f'[{i}]' for i in refs) if refs else ''
        lines = [f"{c.tool_name.replace('_', ' ').capitalize()}{suffix}"]
        for key, value in c.result.items():
            if not isinstance(value, (dict, list)):
                lines.append(f"{key.replace('_', ' ')}: {value}")
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def verify_response(draft_answer: str, decision: RouterDecision, retrieval_hits: list[RetrievalHit] | None = None, tool_results: list[ToolResult] | None = None, structured_answer: StructuredLLMAnswer | None = None, web_citations: list[Citation] | None = None) -> VerifiedResponse:
    hits, results = retrieval_hits or [], tool_results or []
    citations = build_citations(hits) + (web_citations or [])
    available = {c.chunk_id for c in citations if c.chunk_id}
    evidence = {h.chunk.id: h.chunk.content for h in hits}
    # Web snippets cannot overwrite full document evidence.
    evidence.update({c.chunk_id: c.snippet for c in (web_citations or []) if c.chunk_id and c.chunk_id not in evidence})
    for f in extract_facts(hits):
        evidence[f.chunk_id] += f"\n{f.entity} {f.period} {f.metric.replace('_', ' ')}: {f.currency} {f.value}."
    calculations = [r.calculation for r in results if r.success and r.calculation]
    needs_evidence = decision.required_retrieval or decision.evidence_source != 'none' or decision.route in {Route.RETRIEVE_THEN_ANSWER, Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER, Route.MULTIMODAL_REASONING, Route.WEB_GROUNDED_ANSWER}
    needs_tools = bool(decision.required_tools) or decision.route in {Route.COMPUTE_ONLY, Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER}
    reasons = []
    status = 'abstained'
    if decision.missing_inputs:
        reasons.append('Missing required inputs: ' + ', '.join(decision.missing_inputs))
        status = 'clarification'
    if decision.route == Route.ABSTAIN:
        reasons.append(decision.reason)
        if decision.action == 'unsupported':
            status = 'unsupported'
    if needs_evidence and not citations:
        reasons.append('Required evidence is missing.')
    by_tool = {c.tool_name: c for c in calculations}
    if needs_tools:
        if not decision.required_tools:
            reasons.append('Requested operation has no explicit tool contract.')
        for name in decision.required_tools:
            matching = [r for r in results if r.calculation and r.calculation.tool_name == name]
            if len(matching) != 1 or not matching[0].success:
                reasons.append(f'Required tool {name} did not succeed exactly once.')
        if any(not r.success for r in results):
            reasons.append('A required tool failed.')
        if set(by_tool) != set(decision.required_tools):
            reasons.append('Executed tools do not match the requested operations.')
        for requested in decision.operations:
            c=by_tool.get(requested.tool)
            if c and requested.evidence_source=='document' and requested.tool not in {'emi_calculator','portfolio_growth_simulator'}:
                actual=c.operation
                if actual is None or actual.metric!=requested.metric or (requested.entity and actual.entity.casefold()!=requested.entity.casefold()) or (requested.periods and (actual.periods[-len(requested.periods):]!=requested.periods)):
                    reasons.append('Calculated metric, entity or period does not match the user operation.')
        for c in calculations:
            if needs_evidence and not c.provenance:
                reasons.append('Document calculation lacks input provenance.')
            for p in c.provenance.values():
                if isinstance(p, dict) and p.get('source') == 'document' and p.get('chunk_id') not in available:
                    reasons.append('Calculation input references missing document evidence.')
            for key,p in c.provenance.items():
                if isinstance(p,dict) and p.get('metric'):
                    facts=[f for f in extract_facts(hits) if f.chunk_id==p.get('chunk_id') and f.metric==p['metric'] and f.period==p.get('period') and f.entity==p.get('entity') and f.currency==p.get('unit')]
                    if not facts or not all(abs(f.value-Decimal(str(c.inputs.get(key))))<=Decimal('.000001') for f in facts):
                        reasons.append('Calculation input value does not resolve to its bound evidence record.')
    claims = structured_answer.claims if structured_answer else []
    used = set()
    if needs_evidence and not needs_tools and structured_answer is None:
        reasons.append('Evidence-dependent output requires valid structured claims.')
    if structured_answer:
        displayed_refs = set(re.findall(r'\[([^\[\]]+)\]', structured_answer.answer))
        all_refs = displayed_refs | set(structured_answer.used_citation_ids)
        all_refs.update(i for claim in claims for i in claim.citation_ids)
        all_refs.update(i for claim in claims for i in re.findall(r'\[([^\[\]]+)\]', claim.text))
        if all_refs - available:
            reasons.append('An answer or claim references unknown citation IDs.')
        if structured_answer.needs_more_data:
            reasons.append('The generated response requests more evidence.')
        if needs_evidence and not needs_tools:
            if not claims:
                reasons.append('Factual output has no claim coverage.')
            for claim in claims:
                claimed_pages = {int(p) for p in re.findall(r'\bpage\s+(\d+)', claim.text, re.I)}
                actual_pages = {c.page for c in citations if c.chunk_id in claim.citation_ids}
                if claimed_pages - actual_pages:
                    reasons.append('Claim page references disagree with source metadata.')
                if not claim.text.strip() or not claim.citation_ids:
                    reasons.append('Every factual claim requires supporting evidence.')
                elif not supported_claim(claim,hits):
                    reasons.append('Claim numbers, units, metric, period or direction disagree with evidence.')
                used.update(claim.citation_ids)
            answer_without_refs = re.sub(r'\[[^\[\]]+\]', '', structured_answer.answer)
            claim_quantities = [n for c in claims for n in quantities(c.text)]
            if any(not any(n.unit == a.unit and abs(n.value-a.value) <= n.tolerance for a in claim_quantities) for n in quantities(answer_without_refs)):
                reasons.append('Generated answer numbers disagree with authoritative claims.')
        if needs_tools:
            authoritative = []
            periods = set()
            for c in calculations:
                periods.update(Decimal(str(v)) for v in c.result.get('periods', []) if isinstance(v, int))
                # Document-derived monetary inputs may be quoted in an explanation;
                # their units come from the extraction provenance, not the model.
                for key, value in c.inputs.items():
                    origin = c.provenance.get(key, {})
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(origin, dict) and origin.get('unit') in {'USD', 'CAD', 'AUD', 'EUR', 'GBP', 'INR'}:
                        authoritative.append((Decimal(str(value)), origin['unit']))
                for key, value in c.result.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        amount = Decimal(str(value))
                        authoritative.append((amount, 'number'))
                        if key.endswith('_pct'):
                            authoritative.append((amount / 100, 'fraction'))
            prose = re.sub(r'\[[^\[\]]+\]', '', structured_answer.answer + '\n' + '\n'.join(c.text for c in claims))
            # Ratio suffixes must be parsed, and years must match the tool's
            # reporting periods rather than being compared to its arithmetic.
            prose = re.sub(r'(?<=\d)x\b', ' ', prose, flags=re.I)
            if any(not (n.unit == 'number' and n.value in periods) and not any(n.unit == unit and abs(n.value-a) <= Decimal('0.00005') for a, unit in authoritative) for n in quantities(prose)):
                reasons.append('Generated numerical results disagree with authoritative tool outputs (rounding: four decimals).')
    if needs_tools:
        used.update(p['chunk_id'] for c in calculations for p in c.provenance.values() if isinstance(p, dict) and p.get('chunk_id'))
    if reasons:
        return VerifiedResponse(answer='Insufficient data to answer reliably.', status=status, reasons=list(dict.fromkeys(reasons)), confidence=0.0, diagnostics={'mandatory_checks_passed': False})
    if needs_tools:
        answer = render_calculations(calculations)
    elif needs_evidence:
        # Never display unchecked narrative. The validated claim list is the output contract.
        answer = '\n'.join(c.text.strip() + ' ' + ' '.join(f'[{i}]' for i in dict.fromkeys(c.citation_ids)) for c in claims)
    else:
        answer = structured_answer.answer.strip() if structured_answer else draft_answer.strip()
    if not answer:
        return VerifiedResponse(answer='Insufficient data to answer reliably.', status='abstained', reasons=['Empty output.'], confidence=0.0)
    return VerifiedResponse(answer=answer, status='ok', citations=[c for c in citations if c.chunk_id in used], calculations=calculations, claims=claims, assumptions=sorted({a for c in calculations for a in c.assumptions}|set(structured_answer.assumptions if structured_answer else [])), confidence=1.0, diagnostics={'mandatory_checks_passed': True, 'confidence_meaning':'Binary mandatory-check indicator; not calibrated accuracy.', 'support_contract':'canonical bound financial records or faithful source excerpts', 'semantic_entailment_proven': False})
