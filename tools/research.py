from __future__ import annotations

import re

from calculation_inputs import InputIssue
from financial_evidence import METRICS, extract_facts, select_fact
from schemas import RequestedOperation, RetrievalHit, ToolCalculation, ToolResult


def calculate_document_operation(
    query: str, operation: str, hits: list[RetrievalHit]
) -> ToolResult:
    if re.search(
        r"\b(?:inflation|adjusted|fees?|tax|forecast|projected)\b", query, re.I
    ):
        raise InputIssue(
            "Adjustments, forecasts and extra costs are unsupported in document research calculations.",
            "unsupported",
        )
    facts = extract_facts(hits)
    periods = sorted(set(int(y) for y in re.findall(r"\b20\d{2}\b", query)))
    entities = {f.entity for f in facts}
    named = [e for e in entities if e.casefold() in query.casefold()]
    if len(named) > 1 or (not named and len(entities) > 1):
        raise InputIssue("Specify one company for the calculation.")
    entity = named[0] if named else next(iter(entities), None)
    if operation == "yoy_growth":
        requested_metrics = [m for m, p in METRICS.items() if re.search(p, query, re.I)]
        if len(requested_metrics) != 1:
            raise InputIssue(
                "Specify one supported metric for year-over-year growth.", "unsupported"
            )
        growth_metric = requested_metrics[0]
        if len(periods) == 1:
            periods = [periods[0] - 1, periods[0]]
        if not periods:
            periods = sorted({f.period for f in facts if f.metric == growth_metric})
        if len(periods) != 2 or periods[1] - periods[0] != 1:
            raise InputIssue(
                "Year-over-year growth requires two consecutive reporting years."
            )
        a = select_fact(facts, growth_metric, periods[0], entity)
        b = select_fact(facts, growth_metric, periods[1], entity)
        formula = f"(current_{growth_metric} - prior_{growth_metric}) / prior_{growth_metric} * 100"
        inputs = {
            f"prior_{growth_metric}": float(a.value),
            f"current_{growth_metric}": float(b.value),
        }
        value = (b.value - a.value) / a.value * 100 if a.value else None
        key = "growth_pct"
        provenance = {
            f"prior_{growth_metric}": a.provenance(),
            f"current_{growth_metric}": b.provenance(),
        }
    else:
        if len(periods) > 1:
            raise InputIssue("Select one reporting period for a ratio calculation.")
        period = periods[0] if periods else None
        metrics = {
            "margin": ("net_income", "revenue"),
            "operating_margin": ("operating_income", "revenue"),
            "current_ratio": ("current_assets", "current_liabilities"),
            "debt_to_equity": ("debt", "equity"),
        }
        if operation not in metrics:
            raise InputIssue(f"Unsupported calculation {operation}", "unsupported")
        numerator, denominator = metrics[operation]
        a, b = (
            select_fact(facts, numerator, period, entity),
            select_fact(facts, denominator, period, entity),
        )
        inputs = {numerator: float(a.value), denominator: float(b.value)}
        formula = f"{numerator} / {denominator}" + (
            " * 100" if operation in {"margin", "operating_margin"} else ""
        )
        value = (
            a.value
            / b.value
            * (100 if operation in {"margin", "operating_margin"} else 1)
            if b.value
            else None
        )
        key = "margin_pct" if operation in {"margin", "operating_margin"} else "ratio"
        provenance = {numerator: a.provenance(), denominator: b.provenance()}
        if a.period != b.period:
            raise InputIssue("Inputs have conflicting reporting periods.", "abstained")
    if a.currency != b.currency:
        raise InputIssue("Inputs have conflicting currencies.", "abstained")
    if value is None:
        raise InputIssue(
            "The denominator is zero; this calculation is undefined.", "abstained"
        )
    bound = RequestedOperation(
        tool=operation,
        metric=growth_metric if operation == "yoy_growth" else operation,
        entity=a.entity,
        periods=periods or [a.period],
        evidence_source="document",
    )
    return ToolResult(
        success=True,
        calculation=ToolCalculation(
            tool_name=operation,
            operation=bound,
            inputs=inputs,
            result={
                key: round(float(value), 4),
                "entity": a.entity,
                "periods": periods or [a.period],
                "currency": a.currency,
                "metric": bound.metric,
            },
            provenance=provenance,
            assumptions=[
                "Inputs use the same currency; reported values are treated as exact.",
                "Results are rounded to four decimal places.",
                "Margin means net income divided by revenue."
                if operation == "margin"
                else "No adjustment for restatements or inflation.",
            ],
            trace=formula,
        ),
    )
