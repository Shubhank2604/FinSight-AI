"""Conservative, field-specific query parsing. Never infer money from arbitrary numbers."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InputIssue(ValueError):
    def __init__(self, reason: str, status: str = "clarification"):
        super().__init__(reason)
        self.status = status


class InputOrigin(BaseModel):
    text: str
    start: int
    end: int
    source: str = "query"
    chunk_id: str | None = None
    page: int | None = None
    unit: str | None = None
    raw_value: float | None = None
    normalized_value: float | None = None
    scale: str | None = None
    rate_period: str | None = None
    normalization: str | None = None


class EMIInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    principal: float = Field(gt=0)
    annual_rate_pct: float = Field(ge=0, le=100)
    tenure_months: int = Field(gt=0, le=1200)
    currency: str
    rate_convention: Literal["nominal_annual"] = "nominal_annual"


class PortfolioInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    monthly_investment: float = Field(ge=0)
    annual_return_pct: float = Field(gt=-100, le=100)
    years: float = Field(gt=0, le=100)
    currency: str
    initial_amount: float = Field(default=0, ge=0)
    annual_step_up_pct: float = Field(default=0, ge=0, le=100)
    contribution_timing: Literal["beginning", "end"] = "end"
    rate_convention: Literal["nominal_annual", "effective_annual"] = "nominal_annual"


NUMBER = r"[+-]?\d[\d,]*(?:\.\d+)?"
SCALE_PATTERN = r"thousands?|millions?|billions?|crores?|lakhs?|lacs?|cr|[kmb]"
SCALES = {
    "k": 1e3,
    "thousand": 1e3,
    "thousands": 1e3,
    "m": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "b": 1e9,
    "billion": 1e9,
    "billions": 1e9,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "cr": 1e7,
    "crore": 1e7,
    "crores": 1e7,
}
MONEY = re.compile(
    rf"(?P<currency>CAD|AUD|USD|INR|EUR|GBP|JPY|SGD|AED|C\$|A\$|US\$|\$|€|£|₹)?\s*(?P<number>{NUMBER})\s*(?P<scale>{SCALE_PATTERN})?\b",
    re.I,
)


def currency_from_text(text: str) -> str:
    codes = set(
        re.findall(r"\b(?:USD|CAD|AUD|EUR|GBP|INR|JPY|SGD|AED)\b", text.upper())
    )
    for pattern, code in [
        (r"Canadian dollars?|C\$", "CAD"),
        (r"Australian dollars?|A\$", "AUD"),
        (r"US\$|US dollars?", "USD"),
        (r"€|euros?", "EUR"),
        (r"£|pounds?", "GBP"),
        (r"₹|rupees?|\brs\.?\b", "INR"),
        (r"¥|yen", "JPY"),
    ]:
        if re.search(pattern, text, re.I):
            codes.add(code)
    if len(codes) > 1:
        raise InputIssue(
            "Conflicting currencies; specify one currency. Currency conversion is unsupported."
        )
    return next(iter(codes), "USD")


def _single(candidates: list[tuple[float, InputOrigin]], field: str):
    if not candidates:
        raise InputIssue(f"Missing {field}; specify it explicitly.")
    if len({value for value, _ in candidates}) > 1:
        raise InputIssue(f"Conflicting or ambiguous {field} values.")
    return candidates[0]


def extract_calculation_inputs(query: str, tool: str):
    if re.search(r"\b(?:nan|inf|infinity)\b", query, re.I):
        raise InputIssue("Nonfinite inputs are invalid.")
    unsupported = re.search(
        r"\b(?:prepay\w*|fees?|tax(?:es)?|inflation|variable|floating|daily|weekly|dividends?|withdraw\w*|balloon|interest.only|continuous)\b",
        query,
        re.I,
    )
    if unsupported:
        raise InputIssue(
            f"Requested feature '{unsupported.group()}' is unsupported in query calculations. Use a supported form or remove it.",
            "unsupported",
        )
    currency = currency_from_text(query)
    money: dict[str, list] = {
        "principal": [],
        "monthly_investment": [],
        "initial_amount": [],
    }
    for match in MONEY.finditer(query):
        start, end = match.span()
        before, after = (
            query[max(0, start - 30) : start].lower(),
            query[end : end + 30].lower(),
        )
        if re.match(
            r"\s*(?:%|basis points?\b|bps\b|years?\b|yrs?\b|months?\b|days?\b)", after
        ):
            continue
        if re.match(r"\s*(?:%|percent)", after):
            continue
        is_money = bool(match.group("currency") or match.group("scale"))
        initial = bool(
            re.search(
                r"(?:initial (?:balance|amount)|starting (?:balance|amount)|initially)\s*(?:of|=|:)?\s*$",
                before,
            )
        )
        contribution = bool(
            re.match(r"\s*(?:per month|/month|monthly|each month)", after)
            or re.search(
                r"(?:monthly (?:contribution|investment)|contribution)\s*(?:of|=|:)?\s*$",
                before,
            )
        )
        principal = bool(
            re.search(r"(?:principal|loan(?: of| amount)?)\s*(?:of|=|:)?\s*$", before)
            or re.match(r"\s*(?:loan|principal|mortgage)\b", after)
        )
        if not (is_money or initial or contribution or principal):
            continue
        if tool == "emi_calculator":
            field = "principal"
        else:
            field = "initial_amount" if initial else "monthly_investment"
            if (
                not initial
                and not contribution
                and not re.search(r"(?:invest|contribut)\w*\s*$", before)
            ):
                raise InputIssue(
                    "Specify whether each money amount is an initial balance or monthly contribution."
                )
        value = float(match.group("number").replace(",", "")) * SCALES.get(
            (match.group("scale") or "").lower(), 1
        )
        if re.match(
            r"\s*(?:hundreds?|trillions?|mn|bn|hundred\w*|thousand\w+|million\w+|billion\w+)\b",
            after,
        ):
            raise InputIssue(
                f"Unsupported amount modifier for {field}; use a supported explicit scale."
            )
        money[field].append(
            (
                value,
                InputOrigin(
                    text=match.group(),
                    start=start,
                    end=end,
                    unit=currency,
                    raw_value=float(match.group("number").replace(",", "")),
                    normalized_value=value,
                    scale=match.group("scale") or "ones",
                ),
            )
        )
    rates = []
    steps = []
    for match in re.finditer(
        rf"(?P<n>{NUMBER})\s*(?P<u>%|percent|basis points?|bps)", query, re.I
    ):
        value = float(match.group("n").replace(",", "")) / (
            100
            if match.group("u").lower() in {"bps", "basis point", "basis points"}
            else 1
        )
        raw_rate = value
        suffix = query[match.end() : match.end() + 35]
        period_match = re.match(
            r"\s*(?:(?:per|a|each|/)\s*)?(month(?:ly)?|year(?:ly)?|annum|annual(?:ly)?|day|daily|week|weekly|quarter(?:ly)?)\b",
            suffix,
            re.I,
        )
        period = period_match.group(1).lower() if period_match else "year"
        nearby_prefix = query[max(0, match.start() - 35) : match.start()].lower()
        if period_match is None and re.search(
            r"monthly\s+(?:interest|return|rate)(?:\s+rate)?\s*[:=]?\s*$", nearby_prefix
        ):
            period = "month"
        if period not in {
            "month",
            "monthly",
            "year",
            "yearly",
            "annum",
            "annual",
            "annually",
        }:
            raise InputIssue(
                f"Unsupported rate period '{period}'; use annual or nominal monthly rates.",
                "unsupported",
            )
        if period.startswith("month"):
            if re.search(r"effective|annual", nearby_prefix) or (
                tool == "portfolio_growth_simulator"
                and re.search(r"effective", query, re.I)
            ):
                raise InputIssue(
                    "Effective or conflicting monthly rate conventions are unsupported; specify a nominal monthly or annual rate.",
                    "unsupported",
                )
            value *= 12
        rate_end = match.end() + (period_match.end() if period_match else 0)
        origin = InputOrigin(
            text=query[match.start() : rate_end],
            start=match.start(),
            end=rate_end,
            unit="percent/year",
            raw_value=raw_rate,
            normalized_value=value,
            rate_period="month" if period.startswith("month") else "year",
            normalization="monthly percentage × 12 = nominal annual percentage"
            if period.startswith("month")
            else "annual percentage (assumed nominal unless effective is explicit)",
        )
        nearby = query[max(0, match.start() - 25) : match.end() + 25].lower()
        (
            steps if re.search(r"step.up|increase contributions", nearby) else rates
        ).append((value, origin))
    duration = []
    for match in re.finditer(
        rf"(?P<n>{NUMBER})\s*(?P<u>years?|yrs?|months?)\b", query, re.I
    ):
        value = float(match.group("n").replace(",", "")) * (
            12 if match.group("u").lower().startswith(("y",)) else 1
        )
        duration.append(
            (
                value,
                InputOrigin(
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    unit="months",
                    raw_value=float(match.group("n").replace(",", "")),
                    normalized_value=value,
                    normalization="years multiplied by 12" if match.group("u").lower().startswith("y") else "whole months",
                ),
            )
        )
    rate, rate_origin = _single(rates, "annual rate")
    months, duration_origin = _single(duration, "duration")
    if months != int(months):
        raise InputIssue("Duration must be a whole number of months.")
    field = "principal" if tool == "emi_calculator" else "monthly_investment"
    amount, amount_origin = _single(money[field], field)
    provenance = {
        field: amount_origin.model_dump(),
        "annual_rate_pct"
        if tool == "emi_calculator"
        else "annual_return_pct": rate_origin.model_dump(),
        "tenure_months"
        if tool == "emi_calculator"
        else "years": duration_origin.model_dump(),
    }
    values = {field: amount, "currency": currency}
    try:
        if tool == "emi_calculator":
            if re.search(r"effective|beginning", query, re.I):
                raise InputIssue(
                    "EMI supports nominal annual rate and end-of-month payments only.",
                    "unsupported",
                )
            model = EMIInputs(**values, annual_rate_pct=rate, tenure_months=int(months))
        elif tool == "portfolio_growth_simulator":
            for optional, candidates in [
                ("initial_amount", money["initial_amount"]),
                ("annual_step_up_pct", steps),
            ]:
                if candidates:
                    value, origin = _single(candidates, optional)
                    values[optional] = value
                    provenance[optional] = origin.model_dump()
            model = PortfolioInputs(
                **values,
                annual_return_pct=rate,
                years=months / 12,
                contribution_timing="beginning"
                if re.search(r"beginning|start of (?:each|the) month", query, re.I)
                else "end",
                rate_convention="effective_annual"
                if re.search(r"effective", query, re.I)
                else "nominal_annual",
            )
        else:
            raise InputIssue(f"Unsupported tool: {tool}", "unsupported")
    except ValidationError as exc:
        raise InputIssue(str(exc)) from exc
    return model, provenance
