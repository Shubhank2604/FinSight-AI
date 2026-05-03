from __future__ import annotations


def local_educational_answer(query: str) -> str:
    lowered = query.lower()
    if "retire" in lowered or "retirement" in lowered:
        return (
            "To estimate the amount you need to retire at 40, calculate your retirement corpus as a function of spending, inflation, retirement horizon, and expected real return.\n\n"
            "1. Estimate annual spending in today's money: `E`.\n"
            "2. Estimate years until retirement: `N = 40 - current_age`.\n"
            "3. Inflate spending to age 40: `E40 = E * (1 + inflation_rate)^N`.\n"
            "4. Estimate retirement duration: `T = life_expectancy - 40`.\n"
            "5. Use a real return assumption: `real_return = ((1 + nominal_return) / (1 + inflation_rate)) - 1`.\n"
            "6. Corpus using present value of withdrawals: `Corpus = E40 * (1 - (1 + real_return)^(-T)) / real_return`.\n"
            "7. Quick rule of thumb: `Corpus ~= 25 * annual_expenses_at_retirement`, but this assumes about a 4% withdrawal rate and may be aggressive for very early retirement.\n"
            "8. Subtract existing investments, expected pensions, rental income, or other income-producing assets.\n\n"
            "To calculate your exact number, you need current age, current annual expenses, inflation assumption, expected retirement age, life expectancy, expected post-retirement return, existing assets, and any recurring income after retirement."
        )

    if "sec" in lowered and ("filing" in lowered or "filings" in lowered):
        return (
            "SEC filings are formal disclosures that public companies and regulated entities submit to the U.S. Securities and Exchange Commission. They help investors understand a company's financial condition, risks, governance, and major events.\n\n"
            "Common filings include:\n"
            "- `10-K`: annual report with audited financials, business overview, risks, and management discussion.\n"
            "- `10-Q`: quarterly report with unaudited financials and updates.\n"
            "- `8-K`: current report for material events such as acquisitions, leadership changes, or major agreements.\n"
            "- `S-1`: registration statement for companies planning an IPO.\n"
            "- `DEF 14A`: proxy statement for shareholder votes and executive compensation.\n\n"
            "For analysis, focus on business description, risk factors, MD&A, financial statements, footnotes, debt/liquidity disclosures, and changes versus prior periods."
        )

    return (
        "I cannot call Gemini right now because the API quota was exceeded. "
        "Try again after the quota reset, or ask a calculation question that can be handled by the local deterministic tools."
    )
