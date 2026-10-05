"""Single-process, persisted estimated-spend cap for explicitly authorized evals.

Text BPE token counts are bounded conservatively by UTF-8 bytes plus 1024 framing
tokens. Output is bounded by max_output_tokens. Unknown/failed usage retains the
reservation; reported usage replaces it. This is a list-price estimate, not billing.
"""

import json
from pathlib import Path

PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-4.1-mini": (0.40, 1.60),
    "text-embedding-3-small": (0.02, 0),
}


class BudgetExceeded(ValueError):
    pass


class EvaluationBudget:
    def __init__(self, limit, path):
        if not 0 < float(limit) <= 100:
            raise ValueError("Budget must be finite and between 0 and 100 USD.")
        self.path = Path(path)
        self.data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "limit_usd": float(limit),
                "basis": "2026-10-05 standard list prices; estimated, not invoice cost",
                "entries": [],
            }
        )
        if self.data["limit_usd"] != float(limit):
            raise ValueError(
                "Existing ledger cap differs; use the existing cap or a separate explicitly authorized ledger."
            )

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.path.with_suffix(".pending.json")
        pending.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        pending.replace(self.path)

    def reserve(self, model, input_bytes, max_output=0, attempts=1):
        if (
            any(
                isinstance(v, bool) or not isinstance(v, int)
                for v in [input_bytes, max_output, attempts]
            )
            or input_bytes < 0
            or max_output < 0
            or attempts < 1
        ):
            raise ValueError(
                "Budget reservation requires nonnegative integer token/byte limits and positive attempts."
            )
        key = next((k for k in PRICES if model == k or model.startswith(k + "-")), None)
        if key is None:
            raise BudgetExceeded(
                "No verified price profile for this model; no paid request issued."
            )
        input_price, output_price = PRICES[key]
        upper = (
            ((input_bytes + 1024) * input_price + max_output * output_price)
            * attempts
            / 1e6
        )
        spent = sum(e["accounted_usd"] for e in self.data["entries"])
        if spent + upper > self.data["limit_usd"]:
            raise BudgetExceeded(
                "Evaluation spend cap reached; completed requests are retained. No next paid request issued."
            )
        token = len(self.data["entries"])
        self.data["entries"].append(
            {
                "model": model,
                "upper_bound_usd": upper,
                "accounted_usd": upper,
                "state": "reserved",
                "sdk_attempt_bound": attempts,
            }
        )
        self.save()
        return token

    def settle(self, token, usage):
        if not usage:
            return
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", 0)
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
            # Missing or malformed usage must never release a reservation.
            return
        entry = self.data["entries"][token]
        key = next(
            k
            for k in PRICES
            if entry["model"] == k or entry["model"].startswith(k + "-")
        )
        inp, out = PRICES[key]
        value = (
            input_tokens * inp + output_tokens * out
        ) / 1e6
        retry_allowance = (
            entry["upper_bound_usd"]
            * (entry["sdk_attempt_bound"] - 1)
            / entry["sdk_attempt_bound"]
        )
        entry.update(
            state="reported_usage",
            usage=usage,
            accounted_usd=value + retry_allowance,
            unobserved_retry_allowance_usd=retry_allowance,
        )
        self.save()
