from __future__ import annotations

from py_vollib.black_scholes import black_scholes
from py_vollib.black_scholes.greeks.analytical import delta, gamma, rho, theta, vega

from schemas import ToolCalculation, ToolResult


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
        if spot <= 0 or strike <= 0:
            raise ValueError("spot and strike must be positive")
        if time_to_expiry_years <= 0:
            raise ValueError("time_to_expiry_years must be positive")
        if volatility_pct <= 0:
            raise ValueError("volatility_pct must be positive")

        flag = "c" if option_type.lower().startswith("c") else "p"
        rate = risk_free_rate_pct / 100
        volatility = volatility_pct / 100
        price = black_scholes(flag, spot, strike, time_to_expiry_years, rate, volatility)

        result = {
            "currency": currency,
            "option_type": "call" if flag == "c" else "put",
            "price": round(price, 4),
            "delta": round(delta(flag, spot, strike, time_to_expiry_years, rate, volatility), 6),
            "gamma": round(gamma(flag, spot, strike, time_to_expiry_years, rate, volatility), 6),
            "theta": round(theta(flag, spot, strike, time_to_expiry_years, rate, volatility), 6),
            "vega": round(vega(flag, spot, strike, time_to_expiry_years, rate, volatility), 6),
            "rho": round(rho(flag, spot, strike, time_to_expiry_years, rate, volatility), 6),
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
            trace="Computed Black-Scholes price and analytical Greeks with py_vollib.",
            confidence=1.0,
        )
        return ToolResult(success=True, calculation=calculation)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))
