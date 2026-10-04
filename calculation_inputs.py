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
MONEY = re.compile(rf"(?P<currency>CAD|AUD|USD|INR|EUR|GBP|JPY|SGD|AED|C\$|A\$|US\$|\$|€|£|₹)?\s*(?P<number>{NUMBER})\s*(?P<scale>million|billion|crore|lakh|lac|cr|[kmb])?\b", re.I)
SCALES = {"k": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9, "lakh": 1e5, "lac": 1e5, "cr": 1e7, "crore": 1e7}


def currency_from_text(text: str) -> str:
    codes = set(re.findall(r"\b(?:USD|CAD|AUD|EUR|GBP|INR|JPY|SGD|AED)\b", text.upper()))
    for pattern, code in [(r"Canadian dollars?|C\$", "CAD"), (r"Australian dollars?|A\$", "AUD"), (r"US\$|US dollars?", "USD"), (r"€|euros?", "EUR"), (r"£|pounds?", "GBP"), (r"₹|rupees?|\brs\.?\b", "INR"), (r"¥|yen", "JPY")]:
        if re.search(pattern, text, re.I):
            codes.add(code)
    if len(codes) > 1:
        raise InputIssue("Conflicting currencies; specify one currency. Currency conversion is unsupported.")
    return next(iter(codes), "USD")


def extract_dates(text: str) -> list[str]:
    return re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b(?!\s*(?:years?|months?))", text)


def _single(candidates: list[tuple[float, InputOrigin]], field: str):
    if not candidates:
        raise InputIssue(f"Missing {field}; specify it explicitly.")
    if len({value for value, _ in candidates}) > 1:
        raise InputIssue(f"Conflicting or ambiguous {field} values.")
    return candidates[0]


def extract_calculation_inputs(query: str, tool: str):
    if re.search(r"\b(?:nan|inf|infinity)\b", query, re.I):
        raise InputIssue("Nonfinite inputs are invalid.")
    unsupported = re.search(r"\b(?:prepay\w*|fees?|tax(?:es)?|inflation|variable|floating|daily|weekly|dividends?|withdraw\w*|balloon|interest.only|continuous)\b", query, re.I)
    if unsupported:
        raise InputIssue(f"Requested feature '{unsupported.group()}' is unsupported in query calculations. Use a supported form or remove it.", "unsupported")
    currency = currency_from_text(query)
    money: dict[str, list] = {"principal": [], "monthly_investment": [], "initial_amount": []}
    for match in MONEY.finditer(query):
        start, end = match.span()
        before, after = query[max(0, start-30):start].lower(), query[end:end+30].lower()
        if re.match(r"\s*(?:%|basis points?\b|bps\b|years?\b|yrs?\b|months?\b|days?\b)", after):
            continue
        if re.match(r"\s*(?:%|percent)", after):
            continue
        is_money = bool(match.group("currency") or match.group("scale"))
        initial = bool(re.search(r"(?:initial (?:balance|amount)|starting (?:balance|amount)|initially)\s*(?:of|=|:)?\s*$", before))
        contribution = bool(re.match(r"\s*(?:per month|/month|monthly|each month)", after) or re.search(r"(?:monthly (?:contribution|investment)|contribution)\s*(?:of|=|:)?\s*$", before))
        principal = bool(re.search(r"(?:principal|loan(?: of| amount)?)\s*(?:of|=|:)?\s*$", before) or re.match(r"\s*(?:loan|principal|mortgage)\b", after))
        if not (is_money or initial or contribution or principal):
            continue
        if tool == "emi_calculator":
            field = "principal"
        else:
            field = "initial_amount" if initial else "monthly_investment"
            if not initial and not contribution and not re.search(r"(?:invest|contribut)\w*\s*$", before):
                raise InputIssue("Specify whether each money amount is an initial balance or monthly contribution.")
        value = float(match.group("number").replace(",", "")) * SCALES.get((match.group("scale") or "").lower(), 1)
        money[field].append((value, InputOrigin(text=match.group(), start=start, end=end, unit=currency)))
    rates = []
    steps = []
    for match in re.finditer(rf"(?P<n>{NUMBER})\s*(?P<u>%|percent|basis points?|bps)", query, re.I):
        value = float(match.group("n").replace(",", "")) / (100 if match.group("u").lower() in {"bps", "basis point", "basis points"} else 1)
        origin = InputOrigin(text=match.group(), start=match.start(), end=match.end(), unit="percent/year")
        nearby = query[max(0,match.start()-25):match.end()+25].lower()
        (steps if re.search(r"step.up|increase contributions", nearby) else rates).append((value, origin))
    duration = []
    for match in re.finditer(rf"(?P<n>{NUMBER})\s*(?P<u>years?|yrs?|months?)\b", query, re.I):
        value = float(match.group("n").replace(",", "")) * (12 if match.group("u").lower().startswith(("y",)) else 1)
        duration.append((value, InputOrigin(text=match.group(), start=match.start(), end=match.end(), unit="months")))
    rate, rate_origin = _single(rates, "annual rate")
    months, duration_origin = _single(duration, "duration")
    if months != int(months):
        raise InputIssue("Duration must be a whole number of months.")
    field = "principal" if tool == "emi_calculator" else "monthly_investment"
    amount, amount_origin = _single(money[field], field)
    provenance = {field: amount_origin.model_dump(), "annual_rate_pct" if tool == "emi_calculator" else "annual_return_pct": rate_origin.model_dump(), "tenure_months" if tool == "emi_calculator" else "years": duration_origin.model_dump()}
    values = {field: amount, "currency": currency}
    try:
        if tool == "emi_calculator":
            if re.search(r"effective|beginning", query, re.I):
                raise InputIssue("EMI supports nominal annual rate and end-of-month payments only.", "unsupported")
            model = EMIInputs(**values, annual_rate_pct=rate, tenure_months=int(months))
        elif tool == "portfolio_growth_simulator":
            for optional, candidates in [("initial_amount", money["initial_amount"]), ("annual_step_up_pct", steps)]:
                if candidates:
                    value, origin = _single(candidates, optional)
                    values[optional] = value
                    provenance[optional] = origin.model_dump()
            model = PortfolioInputs(**values, annual_return_pct=rate, years=months/12, contribution_timing="beginning" if re.search(r"beginning|start of (?:each|the) month", query, re.I) else "end", rate_convention="effective_annual" if re.search(r"effective", query, re.I) else "nominal_annual")
        else:
            raise InputIssue(f"Unsupported tool: {tool}", "unsupported")
    except ValidationError as exc:
        raise InputIssue(str(exc)) from exc
    return model, provenance
