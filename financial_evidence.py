"""Financial quantities and conservative labeled facts, not a general entailment engine."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from calculation_inputs import InputIssue, SCALES, currency_from_text
from schemas import RetrievalHit


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    tolerance: Decimal


QUANTITY = re.compile(r"(?<![\w])(?P<open>\()?\s*(?P<cur>USD|CAD|AUD|EUR|GBP|INR|C\$|A\$|US\$|\$|€|£|₹)?\s*(?P<n>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?P<scale>million|billion|thousand|crore|lakh|[kmb])?(?P<close>\))?\s*(?P<rate>%|percent|basis points?|bps|fraction)?\s*(?P<cur_after>USD|CAD|AUD|EUR|GBP|INR)?(?!\w)", re.I)


def quantities(text: str, default_currency: str | None = None, default_scale: str | None = None) -> list[Quantity]:
    text = re.sub(r"(USD|CAD|AUD|EUR|GBP|INR|\$|€|£|₹)\s*\((\d[\d,.]*)\)\s*(million|billion|thousand|[kmb])?", lambda m: f"{m.group(1)} -{m.group(2)} {m.group(3) or ''}", text, flags=re.I)
    result = []
    for m in QUANTITY.finditer(text):
        n = m.group("n").replace(",", "")
        value = Decimal(n)
        if m.group("open") and m.group("close"):
            value = -value
        currency_token = m.group("cur") or m.group("cur_after")
        is_year = not currency_token and not m.group("scale") and not m.group("rate") and n.isdigit() and 1900 <= int(n) <= 2099
        scale = (m.group("scale") or (default_scale if not currency_token and not is_year else "") or "").lower()
        multiplier = Decimal(str(SCALES.get(scale, 1000 if scale == "thousand" else 1)))
        precision = len(n.partition(".")[2])
        tolerance = Decimal(5) * Decimal(10) ** (-precision-1)
        if m.group("rate"):
            unit = "fraction"
            multiplier = Decimal("1") if m.group("rate").lower() == "fraction" else (Decimal("0.0001") if m.group("rate").lower() in {"basis point", "basis points", "bps"} else Decimal("0.01"))
        else:
            unit = currency_from_text(currency_token) if currency_token else ("number" if is_year else (default_currency or "number"))
        result.append(Quantity(value*multiplier, unit, tolerance*multiplier))
    return result


METRICS = {
    "revenue": r"\brevenue\b",
    "net_income": r"\bnet (?:income|profit)\b",
    "operating_income": r"\boperating (?:income|profit)\b",
    "current_assets": r"\bcurrent assets\b",
    "current_liabilities": r"\bcurrent liabilities\b",
    "debt": r"\b(?:total )?debt\b",
    "equity": r"\b(?:shareholders.? |total )?equity\b",
}


def supported_numbers(claim: str, evidence: str) -> bool:
    numbers = quantities(claim)
    if not numbers:
        return True
    currency_match = re.search(r"Currency\s*:\s*(\w+)", evidence, re.I)
    scale_match = re.search(r"(?:Units?|in)\s*[: ]\s*(million|billion|thousand)", evidence, re.I)
    defaults = (currency_match.group(1).upper() if currency_match else None, scale_match.group(1).lower() if scale_match else None)
    entity_match = re.search(r"(?:Company|Entity)\s*:\s*([^\n;]+)", evidence, re.I)
    named_entity = re.search(r"^([A-Z][A-Za-z '&.-]*?)(?:'s)?\s+(?:20\d{2}\s+)?(?:revenue|net income|current assets|current liabilities|debt|equity)\b", claim)
    if entity_match and named_entity:
        name = re.sub(r"\s+(?:reported|reports|generated|has)(?:\s+an?)?$", "", named_entity.group(1).strip(), flags=re.I).casefold().removesuffix("'s")
        if name != entity_match.group(1).strip().casefold():
            return False
    # Pages are validated against Citation.page in the verifier, not as money.
    numbers = quantities(re.sub(r"\bpage\s+\d+", "page", claim, flags=re.I))
    for line in re.split(r"[\n;]|(?<=\.)\s+", evidence):
        for metric, pattern in METRICS.items():
            if re.search(pattern, claim, re.I) and not re.search(pattern, line, re.I):
                continue
        if any(re.search(pattern, claim, re.I) and not re.search(pattern, line, re.I) for pattern in METRICS.values()):
            continue
        up = r"increas\w*|grew|growth|rose"
        down = r"declin\w*|decreas\w*|fell"
        if (re.search(up, claim, re.I) and re.search(down, line, re.I)) or (re.search(down, claim, re.I) and re.search(up, line, re.I)):
            continue
        available = quantities(line, *defaults)
        if all(any(a.unit == n.unit and abs(a.value-n.value) <= n.tolerance for a in available) for n in numbers):
            return True
    return False


@dataclass
class FinancialFact:
    metric: str
    value: Decimal
    currency: str
    period: int
    entity: str
    chunk_id: str
    page: int | None
    source_name: str
    text: str

    def provenance(self):
        return {"source": "document", "chunk_id": self.chunk_id, "page": self.page, "source_name": self.source_name, "text": self.text, "unit": self.currency, "period": self.period, "entity": self.entity}


def extract_facts(hits: list[RetrievalHit]) -> list[FinancialFact]:
    facts = []
    for hit in hits:
        chunk = hit.chunk
        text = chunk.content
        entity_match = re.search(r"(?:Company|Entity)\s*:\s*([^\n;]+)", text, re.I)
        period_match = re.search(r"(?:Period|Year)\s*:\s*(20\d{2})", text, re.I)
        entity = entity_match.group(1).strip() if entity_match else str(chunk.metadata.get("entity", chunk.source_name))
        default_period = int(period_match.group(1)) if period_match else chunk.metadata.get("period")
        currency_match = re.search(r"Currency\s*:\s*(\w+)", text, re.I)
        currency = currency_match.group(1).upper() if currency_match else chunk.metadata.get("currency")
        units_match = re.search(r"(?:Units?|in)\s*[: ]\s*(million|billion|thousand)", text, re.I)
        scale = units_match.group(1).lower() if units_match else chunk.metadata.get("units")
        header_years = []
        for line in text.splitlines():
            period_header = re.search(r"(?:Period|Year)\s*:\s*(20\d{2})", line, re.I)
            if period_header:
                default_period = int(period_header.group(1))
            if "|" in line and not any(re.search(pattern, line, re.I) for pattern in METRICS.values()):
                found = re.findall(r"\b20\d{2}\b", line)
                if found:
                    header_years = [int(y) for y in found]
            for metric, pattern in METRICS.items():
                match = re.search(pattern, line, re.I)
                if not match:
                    continue
                tail = line[match.end():].strip(" :|=")
                years = re.findall(r"\b20\d{2}\b", tail)
                if header_years and "|" in line and not years:
                    values = [quantities(cell.strip(), currency, scale) for cell in tail.split("|")]
                    pairs = [(year, values[i][0]) for i, year in enumerate(header_years) if i < len(values) and values[i]]
                else:
                    period = int(years[0]) if len(set(years)) == 1 else default_period
                    clean = re.sub(r"\b20\d{2}\b", "", tail)
                    values = quantities(clean, currency, scale)
                    pairs = [(period, values[0])] if period and len(values) == 1 else []
                for period, value in pairs:
                    if value.unit not in {"number", "fraction"}:
                        facts.append(FinancialFact(metric, value.value, value.unit, int(period), entity, chunk.id, chunk.page, chunk.source_name, line))
    return facts


def select_fact(facts: list[FinancialFact], metric: str, period: int | None = None, entity: str | None = None) -> FinancialFact:
    matching = [f for f in facts if f.metric == metric and (period is None or f.period == period) and (entity is None or f.entity.casefold() == entity.casefold())]
    if not matching:
        raise InputIssue(f"No supported {metric} value for the requested company/period.", "abstained")
    if len({(f.value, f.currency, f.period, f.entity.casefold()) for f in matching}) > 1:
        raise InputIssue(f"Conflicting or ambiguous {metric} values; specify one company and reporting period.", "abstained")
    return matching[0]
