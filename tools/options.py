from __future__ import annotations

import math
from statistics import NormalDist

from schemas import ToolCalculation, ToolResult
from tools.validation import finite_values, valid_currency


def price_black_scholes_option(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate_pct: float,
    volatility_pct: float,
    option_type: str = "call",
    currency: str = "USD",
) -> ToolResult:
    inputs = {
        "spot": spot,
        "strike": strike,
        "time_to_expiry_years": time_to_expiry_years,
        "risk_free_rate_pct": risk_free_rate_pct,
        "volatility_pct": volatility_pct,
        "option_type": option_type,
        "currency": currency,
    }

    try:
        finite_values(spot=spot, strike=strike, time_to_expiry_years=time_to_expiry_years, risk_free_rate_pct=risk_free_rate_pct, volatility_pct=volatility_pct)
        valid_currency(currency)
        if option_type not in {"call", "put"}:
            raise ValueError("option_type must be call or put")
        if spot <= 0 or strike <= 0:
            raise ValueError("spot and strike must be positive")
        if time_to_expiry_years <= 0:
            raise ValueError("time_to_expiry_years must be positive")
        if volatility_pct <= 0:
            raise ValueError("volatility_pct must be positive")

        flag = "c" if option_type == "call" else "p"
        rate = risk_free_rate_pct / 100
        volatility = volatility_pct / 100
        t = time_to_expiry_years
        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot/strike)+(rate+volatility**2/2)*t)/(volatility*sqrt_t)
        d2 = d1-volatility*sqrt_t
        cdf = NormalDist().cdf
        pdf = math.exp(-d1*d1/2)/math.sqrt(2*math.pi)
        discount = math.exp(-rate*t)
        call_price = spot*cdf(d1)-strike*discount*cdf(d2)
        price = call_price if flag == "c" else call_price-spot+strike*discount
        option_delta = cdf(d1) if flag == "c" else cdf(d1)-1
        option_gamma = pdf/(spot*volatility*sqrt_t)
        option_vega = spot*pdf*sqrt_t/100
        option_rho = (strike*t*discount*cdf(d2) if flag == "c" else -strike*t*discount*cdf(-d2))/100
        option_theta = (-spot*pdf*volatility/(2*sqrt_t) + (-rate*strike*discount*cdf(d2) if flag == "c" else rate*strike*discount*cdf(-d2)))/365
        finite_values(price=price, delta=option_delta, gamma=option_gamma, vega=option_vega, rho=option_rho, theta=option_theta)

        result = {
            "currency": currency,
            "option_type": "call" if flag == "c" else "put",
            "price": round(price, 4),
            "delta": round(option_delta, 6),
            "gamma": round(option_gamma, 6),
            "theta": round(option_theta, 6),
            "vega": round(option_vega, 6),
            "rho": round(option_rho, 6),
        }

        calculation = ToolCalculation(
            tool_name="black_scholes_option_pricer",
            inputs=inputs,
            result=result,
            assumptions=[
                "European vanilla option.",
                "No dividends or carrying costs.",
                "Constant volatility and risk-free rate.",
                "Black-Scholes assumptions apply; this is analytical pricing, not investment advice.",
            ],
            trace="Closed-form Black-Scholes using the normal CDF. Theta is per day; vega/rho per one percentage point.",
            confidence=1.0,
        )
        return ToolResult(success=True, calculation=calculation)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))
