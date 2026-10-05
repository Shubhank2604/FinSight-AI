# Reproducible demonstration

Run `python demo.py` from the repository root in the locked environment.
It creates a temporary index and writes `.test-tmp/demo.json`. Use `--output`
to choose another report path. Retained delivery evidence is not overwritten.
Generation is disabled except for a deliberately injected failure; no API calls occur.

| Scenario | Expected result |
|---|---|
| Cedar document fact | 2025 revenue USD 120 million, page 2 |
| Real Mint document fact | FY2024 revenue USD 3,385.7 million, excerpt page 1, original PDF page 38 |
| Document EMI | USD 500,000; nominal annual 8%; 240 months; monthly EMI USD 4,182.20, page 3 provenance |
| Period comparison | Cedar 2024 revenue USD 100 million and 2025 USD 120 million, both pages |
| Contradiction | Elm's conflicting 2025 revenue causes abstention |
| Injected timeout | `provider_failure`, no invented fact; this is not a real timed-out API call |

For an interactive demo run `python -m streamlit run app.py`, upload
`evals/fixtures/Cedar.pdf`, `Elm.pdf`, and `evals/repair_v3/Mint-2024-CFO.pdf`,
index them, select the appropriate source and use the queries in `demo.py`.
Keep generation and web access off. Show evidence and interpreted inputs before
advanced diagnostics. Tax has no reachable calculation form. Options are a
deterministic Black-Scholes model with stated assumptions; web/vision remain experimental.

Original uploads remain private locally when index evidence is removed.
Document extraction is conservative; this demo does not establish arbitrary-PDF support.
