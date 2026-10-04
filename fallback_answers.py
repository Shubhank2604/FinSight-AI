from __future__ import annotations


def local_educational_answer(query: str) -> str:
    lowered = query.lower()
    if "retire" in lowered or "retirement" in lowered:
        return (
            "To estimate a retirement corpus, choose a retirement age R and use spending, inflation, retirement horizon, and expected real return.\n\n"
            "1. Estimate annual spending in today's money: `E`.\n"
            "2. Estimate years until retirement: `N = R - current_age`.\n"
            "3. Inflate spending to retirement: `ER = E * (1 + inflation_rate)^N`.\n"
            "4. Estimate retirement duration: `T = life_expectancy - R`.\n"
            "5. Use a real return assumption: `real_return = ((1 + nominal_return) / (1 + inflation_rate)) - 1`.\n"
            "6. Corpus using present value of withdrawals: `Corpus = ER * (1 - (1 + real_return)^(-T)) / real_return`; at zero real return, use `ER * T`.\n"
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

    for term, answer in {
        "current ratio": "Current ratio = current assets / current liabilities, using the same reporting period and currency. A zero denominator makes the ratio undefined.",
        "margin": "Net margin = net income / revenue * 100, using the same company and reporting period. Operating margin uses operating income instead; FinSight's document calculator supports net margin.",
        "emi": "EMI is a fixed monthly loan payment. FinSight uses a nominal annual rate divided by 12, a principal and a whole-month duration. Fees and floating rates are excluded.",
        "revenue": "Revenue is income from ordinary sales before expenses. Compare the same entity, currency, period and accounting definition.",
        "debt": "Debt-to-equity = total debt / shareholders' equity. Use matching dates and definitions; zero equity makes this ratio undefined.",
        "growth": "Year-over-year growth = (current value - prior value) / prior value * 100. Use consecutive reporting years and compatible units.",
    }.items():
        if term in lowered:
            return answer
    return "Supported offline education covers revenue, current ratio, net margin, debt-to-equity, year-over-year growth, EMI, retirement frameworks and SEC filing types. Specify one topic."
