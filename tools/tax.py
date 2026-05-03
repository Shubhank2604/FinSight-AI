from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schemas import ToolCalculation, ToolResult


def _load_rule_pack(
    jurisdiction: str,
    tax_year: int,
    rule_pack_dir: str | Path = "data/rule_packs",
) -> dict[str, Any] | None:
    directory = Path(rule_pack_dir)
    if not directory.exists():
        return None

    for path in directory.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            str(data.get("jurisdiction", "")).upper() == jurisdiction.upper()
            and int(data.get("tax_year", 0)) == tax_year
        ):
            return data
    return None


def estimate_tax(
    jurisdiction: str,
    tax_year: int,
    gross_income: float,
    deductions: float = 0.0,
    filing_status: str = "single",
    currency: str = "USD",
    rule_pack_dir: str | Path = "data/rule_packs",
) -> ToolResult:
    inputs = {
        "jurisdiction": jurisdiction,
        "tax_year": tax_year,
        "gross_income": gross_income,
        "deductions": deductions,
        "filing_status": filing_status,
        "currency": currency,
    }

    try:
        if gross_income < 0 or deductions < 0:
            raise ValueError("gross_income and deductions cannot be negative")

        rule_pack = _load_rule_pack(jurisdiction, tax_year, rule_pack_dir)
        if not rule_pack:
            return ToolResult(
                success=False,
                error=(
                    "Insufficient data to estimate tax reliably. No versioned rule "
                    f"pack found for jurisdiction={jurisdiction}, tax_year={tax_year}."
                ),
            )
        if bool(rule_pack.get("demo_only", False)):
            return ToolResult(
                success=False,
                error=(
                    "Insufficient data to estimate tax reliably. The matching rule "
                    "pack is marked demo_only and must not be used for real tax estimates."
                ),
            )

        taxable_income = max(0.0, gross_income - deductions)
        brackets = rule_pack.get("brackets", {}).get(filing_status)
        if not brackets:
            return ToolResult(
                success=False,
                error=f"No bracket set found for filing_status={filing_status}.",
            )

        tax = 0.0
        lower = 0.0
        traces = []
        for bracket in brackets:
            upper = bracket.get("up_to")
            rate = float(bracket["rate"])
            upper_value = float("inf") if upper is None else float(upper)
            taxable_at_rate = max(0.0, min(taxable_income, upper_value) - lower)
            if taxable_at_rate > 0:
                tax += taxable_at_rate * rate
                traces.append(
                    f"{currency} {taxable_at_rate:,.2f} taxed at {rate * 100:.2f}%"
                )
            lower = upper_value
            if taxable_income <= upper_value:
                break

        result = {
            "currency": currency,
            "jurisdiction": jurisdiction.upper(),
            "tax_year": tax_year,
            "filing_status": filing_status,
            "gross_income": round(gross_income, 2),
            "deductions": round(deductions, 2),
            "taxable_income": round(taxable_income, 2),
            "estimated_tax": round(tax, 2),
            "effective_rate_pct": round((tax / gross_income * 100) if gross_income else 0, 4),
        }
        calculation = ToolCalculation(
            tool_name="tax_rule_pack_estimator",
            inputs=inputs,
            result=result,
            assumptions=[
                f"Rule pack version: {rule_pack.get('version', 'unknown')}.",
                "Only rules present in the selected rule pack are applied.",
                "Credits, payroll taxes, local taxes, phase-outs, and special cases may be excluded.",
                "Educational estimate only; not tax advice.",
            ],
            trace="; ".join(traces) or "No taxable income after deductions.",
            confidence=0.8,
        )
        return ToolResult(success=True, calculation=calculation)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))
