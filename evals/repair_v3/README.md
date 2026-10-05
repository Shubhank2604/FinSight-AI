# Frozen repair dataset v3

The checked-in PDF bytes and `application.json` are the frozen evaluation inputs.
Do not overwrite this version to improve a score. Create a new version for future
fixtures. The initial agent-authored split precedes this delivery's measurements;
held-out results are an internal regression split, not an independently blind study.
The engineer and scorer can inspect all labels. No human label review is claimed.

There are 12 documents and 130 questions: ten varied synthetic company reports
(84 development, 36 held-out questions) and two real government CFO pages
(10 held-out questions). Of 130 outcomes, 108 should be accepted, 18 abstained,
two unsupported and two clarification. Synthetic values vary scale, currency,
negative income, metric vocabulary and ratios. Quartz has split loan inputs;
Elm contains a conflict. Most synthetic layouts remain labeled statements.

Synthetic PDF fixtures are dedicated under CC0-1.0. Real excerpts retain the
government-authored United States Mint CFO pages only; third-party auditor
opinions are excluded. Source identity is acquisition metadata, not expected
answer metadata. Reviewable revenue labels are transcribed independently of
the extraction implementation and remain agent-reviewed.

| Excerpt | Original source and physical PDF page | Original SHA-256 | Label |
|---|---|---|---|
| Mint-2024-CFO.pdf | [Mint FY2024 annual report](https://www.usmint.gov/content/dam/usmint/reports/2024-annual-report.pdf), page 38 (printed 36) | `4389413383aa228e9538fcd136dec5dd810b273ccc5928cea64eab4e5afdd6df` | FY2024 revenue USD 3,385.7 million |
| Mint-2023-CFO.pdf | [Treasury OIG FY2023 Mint report](https://oig.treasury.gov/system/files/2024-10/OIG-24-011-web-copy-508.pdf), page 39 (printed 33) | `517d911779dc5ce4e5a80a6011a8ea59e29a0371cd88937ccbbf3f2eb51ebe7a` | FY2023 revenue USD 4,681.6 million |

The excerpt hashes are in the manifest. Each PDF's subject contains the original
URL, hash and physical page number. Acquisition was checked against the original
PDF text on 2026-10-05. To review, download the linked originals privately and
inspect those pages. `evaluation/build_repair_dataset.py` documents construction
and independent arithmetic labels; it deliberately refuses to overwrite the
existing manifest. PDF metadata identifiers may vary on reconstruction, so use
the checked-in frozen bytes for exact replication.

This satisfies the requested document/question count but is still narrow real
evidence: two pages, one issuer, two positive fact questions. It does not measure
full annual-report extraction, audited table interpretation, or arbitrary PDF
accuracy. Required-page relevance treats duplicate text/table chunks on a page
as relevant; ranking and final-context page coverage are different metrics.
