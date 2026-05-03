from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy_financial as npf

from schemas import ToolCalculation, ToolResult


def _normalise_prepayments(
    prepayments: Iterable[dict[str, Any]] | None,
) -> dict[int, float]:
    normalised: dict[int, float] = {}
    for item in prepayments or []:
        month = int(item.get("month", 0))
        amount = float(item.get("amount", 0))
        if month > 0 and amount > 0:
            normalised[month] = normalised.get(month, 0.0) + amount
    return normalised


def _amortise(
    principal: float,
    annual_rate_pct: float,
    tenure_months: int,
    prepayments: dict[int, float] | None = None,
) -> dict[str, Any]:
    monthly_rate = annual_rate_pct / 100 / 12
    emi = float(-npf.pmt(monthly_rate, tenure_months, principal))
    balance = principal
    total_interest = 0.0
    total_prepayment = 0.0
    schedule = []
    prepayments = prepayments or {}

    for month in range(1, tenure_months + 1):
        if balance <= 0:
            break

        interest = balance * monthly_rate
        principal_component = min(emi - interest, balance)

        if principal_component < 0:
            raise ValueError("EMI does not cover monthly interest at this rate.")

        balance -= principal_component
        prepayment = min(prepayments.get(month, 0.0), balance)
        balance -= prepayment

        total_interest += interest
        total_prepayment += prepayment

        schedule.append(
            {
                "month": month,
                "emi": round(emi, 2),
                "interest": round(interest, 2),
                "principal": round(principal_component, 2),
                "prepayment": round(prepayment, 2),
                "remaining_balance": round(max(balance, 0), 2),
            }
        )

    return {
        "emi": round(emi, 2),
        "months_to_close": len(schedule),
        "total_interest": round(total_interest, 2),
        "total_prepayment": round(total_prepayment, 2),
        "final_balance": round(max(balance, 0), 2),
        "schedule_preview": schedule[:12],
    }


def calculate_emi(
    principal: float,
    annual_rate_pct: float,
    tenure_months: int,
    currency: str = "INR",
    prepayments: Iterable[dict[str, Any]] | None = None,
) -> ToolResult:
    inputs = {
        "principal": principal,
        "annual_rate_pct": annual_rate_pct,
        "tenure_months": tenure_months,
        "currency": currency,
        "prepayments": list(prepayments or []),
    }

    try:
        if principal <= 0:
            raise ValueError("principal must be positive")
        if annual_rate_pct < 0:
            raise ValueError("annual_rate_pct cannot be negative")
        if tenure_months <= 0:
            raise ValueError("tenure_months must be positive")

        normalised_prepayments = _normalise_prepayments(prepayments)
        base = _amortise(principal, annual_rate_pct, tenure_months)
        with_prepayments = _amortise(
            principal, annual_rate_pct, tenure_months, normalised_prepayments
        )
        interest_saved = base["total_interest"] - with_prepayments["total_interest"]

        result = {
            "currency": currency,
            "monthly_emi": with_prepayments["emi"],
            "months_to_close": with_prepayments["months_to_close"],
            "total_interest": with_prepayments["total_interest"],
            "total_prepayment": with_prepayments["total_prepayment"],
            "interest_saved_vs_no_prepayment": round(max(interest_saved, 0), 2),
            "schedule_preview": with_prepayments["schedule_preview"],
        }

        calculation = ToolCalculation(
            tool_name="emi_calculator",
            inputs=inputs,
            result=result,
            assumptions=[
                "Fixed annual interest rate for the full tenure.",
                "Monthly compounding and monthly payments.",
                "Prepayments reduce outstanding principal immediately in the stated month.",
                "Fees, taxes, floating-rate resets, and penalties are excluded.",
            ],
            trace=(
                "Computed EMI using numpy_financial.pmt, then generated an "
                "amortisation schedule month by month."
            ),
            confidence=1.0,
        )
        return ToolResult(success=True, calculation=calculation)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))
