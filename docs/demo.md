# Reproducible five-scenario demonstration

Run from the repository root with the locked Python 3.13 environment:

```powershell
python demo.py
```

This creates an isolated temporary index, uses only redistributable fixtures and writes `evals/results/demo-v2.json`. It requires neither a provider key nor a GPU. Expected scenarios:

1. Cedar revenue for 2025: USD 120 million with a citation to page 2.
2. EMI using the loan in Cedar's report: principal USD 500,000, nominal annual rate 8%, 240 months, monthly EMI USD 4,182.20, provenance on page 3.
3. Cedar reporting-period comparison: 2024 revenue USD 100 million and 2025 revenue USD 120 million, citing both pages.
4. Elm revenue has contradictory 2025 values: abstention with an understandable conflict reason.
5. Injected provider timeout: typed provider failure with no invented factual answer. This is a failure-handling test, not a claim that an actual provider timed out.

For an interactive demonstration, run `python -m streamlit run app.py`, upload `evals/fixtures/Cedar.pdf` and `Elm.pdf`, index them, select the relevant active document and submit the same questions. Leave OpenAI explanations and web access off for a deterministic demo. The Calculators tab exposes EMI, portfolio, option and tax forms. The tax form explains the reviewed rule-pack prerequisite.

Show the readable evidence and Inputs and result panels before the advanced diagnostics. Clarify that questions are independent and that the core's structured-label extraction does not support every arbitrary financial PDF. Original uploads are private local data ignored by Git; removing a document deletes index evidence, while the original remains locally available.
