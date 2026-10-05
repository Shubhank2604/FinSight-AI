"""Frozen varied CC0 fixtures plus actual government CFO pages; independent labels."""

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals/repair_v3"
COMPANIES = [
    "Cedar",
    "Harbor",
    "Quartz",
    "Maple",
    "Juniper",
    "Beacon",
    "Willow",
    "Pine",
    "Orchid",
    "Elm",
]


def emi_reference(currency):
    p, r, n = 500000, 0.08 / 12, 240
    payment = p * r / (1 - (1 + r) ** -n)
    balance = p
    interest_total = 0
    preview = []
    for month in range(1, n + 1):
        interest = balance * r
        principal = min(payment - interest, balance)
        balance -= principal
        interest_total += interest
        if month <= 12:
            preview.append(
                dict(
                    month=month,
                    emi=round(payment, 2),
                    interest=round(interest, 2),
                    principal=round(principal, 2),
                    prepayment=0.0,
                    remaining_balance=round(max(0, balance), 2),
                )
            )
    return dict(
        currency=currency,
        monthly_emi=round(payment, 2),
        months_to_close=n,
        total_interest=round(interest_total, 2),
        total_prepayment=0.0,
        interest_saved_vs_no_prepayment=0.0,
        schedule_preview=preview,
    )


def build():
    if (OUT / "application.json").exists():
        raise SystemExit("Dataset frozen; create a new version instead of overwriting.")
    OUT.mkdir(parents=True, exist_ok=True)
    documents = []
    cases = []
    for i, company in enumerate(COMPANIES):
        currency = ["USD", "CAD", "EUR", "GBP", "AUD"][i % 5]
        prior = {
            "revenue": 100 + i * 13,
            "net_income": 20 + i * 3,
            "current_assets": 40 + i * 7,
            "current_liabilities": 25 + i * 2,
            "debt": 30 + i * 5,
            "equity": 80 + i * 9,
        }
        current = {
            "revenue": 120 + i * 19,
            "net_income": 19 + i * 5 if i != 4 else -13,
            "current_assets": 60 + i * 11,
            "current_liabilities": 28 + i * 4,
            "debt": 37 + i * 8,
            "equity": 85 + i * 6,
        }
        path = OUT / f"{company}-v3.pdf"
        split = "development" if i < 7 else "held_out"
        scale = ["million", "thousand", "billion"][i % 3]
        factor = {"million": 1e6, "thousand": 1e3, "billion": 1e9}[scale]
        with pymupdf.open() as doc:
            for year, values in [(2024, prior), (2025, current)]:
                page = doc.new_page()
                lines = [
                    f"Company: {company}",
                    f"Period: {year}",
                    f"Currency: {currency}",
                    f"Units: {scale}",
                ]
                for metric, value in values.items():
                    label = metric.replace("_", " ")
                    if i % 3 == 1 and metric == "revenue":
                        label = "Net sales"
                    if i % 3 == 2 and metric == "net_income":
                        label = "Net earnings"
                    number = (
                        f"{value * 1e6 / factor:g}"
                        if value >= 0
                        else f"({abs(value) * 1e6 / factor:g})"
                    )
                    cell = f"{currency} {number}" if i % 2 else number
                    lines.append(f"{label}: {cell}")
                lines.append("Supply risk: component shortages can delay orders.")
                page.insert_text((40, 40), "\n".join(lines), fontsize=11)
            page = doc.new_page()
            page.insert_text(
                (40, 40),
                f"Company: {company}\nLoan principal: {currency} 500 thousand"
                + ("" if i == 2 else "\nAnnual interest rate: 8%\nDuration: 20 years"),
                fontsize=11,
            )
            if i == 2:
                page = doc.new_page()
                page.insert_text(
                    (40, 40),
                    f"Company: {company}\nAnnual interest rate: 8%\nDuration: 20 years",
                    fontsize=11,
                )
            if i == 9:
                page = doc.new_page()
                page.insert_text(
                    (40, 40),
                    f"Company: {company}\nPeriod: 2025\nCurrency: {currency}\nUnits: million\nRevenue: 999",
                    fontsize=11,
                )
            doc.save(path, garbage=4, deflate=True)
        documents.append(
            dict(
                source_name=path.name,
                path=path.relative_to(ROOT).as_posix(),
                company=company,
                split=split,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                license="CC0-1.0",
                label_provenance="Agent-authored parameters and independent formula labels; no human review",
            )
        )

        def add(
            op,
            q,
            value=None,
            metrics=None,
            years=None,
            inputs=None,
            result=None,
            status="ok",
            pages=None,
        ):
            c = dict(
                id=f"{company.lower()}-{sum(x.get('expected_entity') == company for x in cases) + 1:02d}",
                query=q,
                sources=[path.name],
                split=split,
                operation=op,
                expected_entity=company,
                expected_period=2025,
                expected_currency=currency,
                expected_value=value,
                expected_status=status,
                required_pages=pages or [2],
                tags=[op],
            )
            if metrics:
                c["expected_facts"] = [
                    dict(
                        entity=company,
                        metric=m,
                        period=y,
                        value=(prior if y == 2024 else current)[m] * 1e6,
                        currency=currency,
                    )
                    for m, y in zip(metrics, years, strict=True)
                ]
            if inputs is not None:
                c["expected_inputs"] = inputs
            if result is not None:
                c["expected_result"] = result
            cases.append(c)

        for m in ["revenue", "net_income", "current_assets"]:
            add(
                m,
                f"According to the report, what is {m.replace('_', ' ')} for {company} in 2025?",
                current[m] * 1e6,
                [m],
                [2025],
                status="abstained" if i == 9 and m == "revenue" else "ok",
            )
        for op, num, den, key, mult in [
            ("current_ratio", "current_assets", "current_liabilities", "ratio", 1),
            ("margin", "net_income", "revenue", "margin_pct", 100),
            ("debt_to_equity", "debt", "equity", "ratio", 1),
        ]:
            val = round(current[num] / current[den] * mult, 4)
            add(
                op,
                f"Calculate {dict(current_ratio='current ratio', margin='net margin', debt_to_equity='debt-to-equity')[op]} for {company} in the report for 2025",
                val,
                inputs={num: current[num] * 1e6, den: current[den] * 1e6},
                result={
                    key: val,
                    "entity": company,
                    "periods": [2025],
                    "currency": currency,
                    "metric": op,
                },
                status="abstained" if i == 9 and op == "margin" else "ok",
            )
        for m in ["revenue", "net_income", "current_assets"]:
            val = round((current[m] - prior[m]) / prior[m] * 100, 4)
            add(
                "yoy_growth",
                f"Compute year-over-year {m.replace('_', ' ')} growth for {company} in the report for 2025",
                val,
                inputs={f"prior_{m}": prior[m] * 1e6, f"current_{m}": current[m] * 1e6},
                result={
                    "growth_pct": val,
                    "entity": company,
                    "periods": [2024, 2025],
                    "currency": currency,
                    "metric": m,
                },
                status="abstained" if i == 9 and m == "revenue" else "ok",
                pages=[1, 2],
            )
        add(
            "comparison",
            f"Compare revenue for {company} in the report for 2024 and 2025",
            [prior["revenue"] * 1e6, current["revenue"] * 1e6],
            ["revenue", "revenue"],
            [2024, 2025],
            status="abstained" if i == 9 else "ok",
            pages=[1, 2],
        )
        add(
            "absent",
            f"What is revenue for {company} in the report for 2028?",
            status="abstained",
        )
        add(
            "emi_calculator",
            f"Calculate EMI using the loan in the report for {company}",
            4182.2,
            inputs={
                "principal": 500000,
                "annual_rate_pct": 8,
                "tenure_months": 240,
                "currency": currency,
                "prepayments": [],
            },
            result=emi_reference(currency),
            pages=[3, 4] if i == 2 else [3],
        )
    for source, page, year, url in [
        (
            ROOT / "2024-annual-report.pdf",
            38,
            2024,
            "https://www.usmint.gov/content/dam/usmint/reports/2024-annual-report.pdf",
        ),
        (
            ROOT / ".test-tmp/Mint-2023.pdf",
            39,
            2023,
            "https://oig.treasury.gov/system/files/2024-10/OIG-24-011-web-copy-508.pdf",
        ),
    ]:
        path = OUT / f"Mint-{year}-CFO.pdf"
        with pymupdf.open(source) as original, pymupdf.open() as excerpt:
            excerpt.insert_pdf(original, from_page=page - 1, to_page=page - 1)
            excerpt.set_metadata(
                {
                    "title": f"United States Mint {year} CFO page",
                    "subject": json.dumps(
                        {
                            "source_url": url,
                            "original_page": page,
                            "original_sha256": hashlib.sha256(
                                source.read_bytes()
                            ).hexdigest(),
                        }
                    ),
                }
            )
            excerpt.save(path, garbage=4, deflate=True)
        documents.append(
            dict(
                source_name=path.name,
                path=path.relative_to(ROOT).as_posix(),
                company="United States Mint",
                split="held_out",
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                license="Government-authored CFO page; excludes auditor opinion pages",
                source_url=url,
                original_page=page,
                label_provenance="Agent transcription from CFO sentence, no independent human review",
            )
        )
        base = dict(
            sources=[path.name],
            split="held_out",
            expected_entity="United States Mint",
            expected_period=year,
            expected_currency="USD",
            required_pages=[1],
            expected_value=None,
        )
        for n, (op, q, status) in enumerate(
            [
                (
                    "revenue",
                    f"What is revenue for United States Mint in the report for {year}?",
                    "ok",
                ),
                (
                    "absent",
                    "What is revenue for United States Mint in the report for 2028?",
                    "abstained",
                ),
                ("unsupported", "Compute EBITDA in this report", "unsupported"),
                (
                    "emi_calculator",
                    "Calculate EMI using the loan in this report",
                    "abstained",
                ),
                (
                    "multiple",
                    "Calculate current ratio and net margin in this report",
                    "clarification",
                ),
            ],
            1,
        ):
            c = {
                **base,
                "id": f"mint-{year}-{n}",
                "operation": op,
                "query": q,
                "expected_status": status,
                "tags": ["real_document", op],
            }
            if status == "ok":
                c.update(
                    expected_value={2024: 3385700000, 2023: 4681600000}[year],
                    expected_facts=[
                        dict(
                            entity="United States Mint",
                            metric="revenue",
                            period=year,
                            value={2024: 3385700000, 2023: 4681600000}[year],
                            currency="USD",
                        )
                    ],
                )
            cases.append(c)
    dataset = dict(
        version="3.0.0",
        label_provenance="Agent-authored/transcribed, not independently human-reviewed",
        split_policy="Seven synthetic companies development; final three and both Mint excerpts held out; frozen before benchmark execution",
        documents=documents,
        cases=cases,
    )
    (OUT / "application.json").write_text(
        json.dumps(dataset, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Frozen {len(documents)} documents and {len(cases)} questions.")


if __name__ == "__main__":
    build()
