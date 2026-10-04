from __future__ import annotations

from schemas import ToolCalculation, ToolResult
from tools.validation import finite_values, valid_currency


def simulate_portfolio_growth(
    monthly_investment: float,
    annual_return_pct: float,
    years: float,
    initial_amount: float = 0.0,
    annual_step_up_pct: float = 0.0,
    currency: str = "INR",
    contribution_timing: str = "end",
    rate_convention: str = "nominal_annual",
) -> ToolResult:
    inputs = {
        "monthly_investment": monthly_investment,
        "annual_return_pct": annual_return_pct,
        "years": years,
        "initial_amount": initial_amount,
        "annual_step_up_pct": annual_step_up_pct,
        "currency": currency,
        "contribution_timing": contribution_timing,
        "rate_convention": rate_convention,
    }

    try:
        finite_values(monthly_investment=monthly_investment, annual_return_pct=annual_return_pct, years=years, initial_amount=initial_amount, annual_step_up_pct=annual_step_up_pct)
        valid_currency(currency)
        if years > 100 or not -100 < annual_return_pct <= 100 or not 0 <= annual_step_up_pct <= 100:
            raise ValueError("Unsupported duration, return, or step-up")
        if contribution_timing not in {"beginning", "end"} or rate_convention not in {"nominal_annual", "effective_annual"}:
            raise ValueError("Invalid contribution timing or rate convention")
        if abs(years * 12 - round(years * 12)) > 1e-8:
            raise ValueError("Duration must be whole months")
        if monthly_investment < 0:
            raise ValueError("monthly_investment cannot be negative")
        if initial_amount < 0:
            raise ValueError("initial_amount cannot be negative")
        if years <= 0:
            raise ValueError("years must be positive")

        months = int(round(years * 12))
        monthly_rate = annual_return_pct / 100 / 12 if rate_convention == "nominal_annual" else (1 + annual_return_pct / 100) ** (1/12) - 1
        balance = initial_amount
        total_invested = initial_amount
        current_monthly_investment = monthly_investment
        yearly_snapshots = []

        for month in range(1, months + 1):
            if contribution_timing == "beginning":
                balance += current_monthly_investment
            balance *= 1 + monthly_rate
            if contribution_timing == "end":
                balance += current_monthly_investment
            total_invested += current_monthly_investment

            if month % 12 == 0:
                yearly_snapshots.append(
                    {
                        "year": month // 12,
                        "monthly_investment": round(current_monthly_investment, 2),
                        "portfolio_value": round(balance, 2),
                    }
                )
                current_monthly_investment *= 1 + annual_step_up_pct / 100

        result = {
            "currency": currency,
            "future_value": round(balance, 2),
            "total_invested": round(total_invested, 2),
            "estimated_gain": round(balance - total_invested, 2),
            "months": months,
            "yearly_snapshots": yearly_snapshots,
        }
        finite_values(future_value=balance, total_invested=total_invested)

        calculation = ToolCalculation(
            tool_name="portfolio_growth_simulator",
            inputs=inputs,
            result=result,
            assumptions=[
                f"Rate convention: {rate_convention}; monthly compounding at a constant return.",
                f"Monthly contributions occur at the {contribution_timing} of each month.",
                "Taxes, fees, inflation, and market volatility are excluded.",
                "This is a deterministic projection, not a guarantee.",
            ],
            trace=(
                "Applied monthly compounding to the starting balance and added "
                "monthly contributions for each simulated month."
            ),
            confidence=1.0,
        )
        return ToolResult(success=True, calculation=calculation)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))
