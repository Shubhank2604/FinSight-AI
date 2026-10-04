"""Reachable deterministic calculator forms; results share the application response contract."""
import streamlit as st
from schemas import Route, RouterDecision
from tools import calculate_emi, estimate_tax, price_black_scholes_option, simulate_portfolio_growth
from verifier.verifi import verify_response


def _append_tool_result(query, route, result):
    if not result.success:
        from schemas import VerifiedResponse
        response = VerifiedResponse(answer=result.error or "Calculation failed", status="clarification", reasons=[result.error or "Calculation failed"])
    else:
        response = verify_response('', RouterDecision(route=route, required_tools=[result.calculation.tool_name], reason="Calculator form"), tool_results=[result])
    st.session_state.setdefault('history', []).append({'query': query, 'response': response.model_dump(mode='json')})


def _render_tool_forms() -> None:
    st.subheader("Deterministic Tool Forms")
    tabs = st.tabs(["EMI", "Portfolio", "Options", "Tax"])

    with tabs[0]:
        with st.form("emi_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="emi_currency",
            )
            principal = st.number_input(
                "Principal",
                min_value=0.0,
                value=500000.0,
                step=1000.0,
                key="emi_principal",
            )
            annual_rate_pct = st.number_input(
                "Annual interest rate (%)",
                min_value=0.0,
                value=8.75,
                step=0.05,
                key="emi_rate",
            )
            tenure_years = st.number_input(
                "Tenure (years)",
                min_value=0.1,
                value=20.0,
                step=0.5,
                key="emi_tenure",
            )
            prepayment_month = st.number_input(
                "Optional prepayment month",
                min_value=0,
                value=0,
                step=1,
                key="emi_prepay_month",
            )
            prepayment_amount = st.number_input(
                "Optional prepayment amount",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                key="emi_prepay_amount",
            )
            submitted = st.form_submit_button("Calculate EMI", type="primary")

        if submitted:
            prepayments = []
            if prepayment_month > 0 and prepayment_amount > 0:
                prepayments.append(
                    {"month": int(prepayment_month), "amount": prepayment_amount}
                )
            tool_result = calculate_emi(
                principal=principal,
                annual_rate_pct=annual_rate_pct,
                tenure_months=int(round(tenure_years * 12)),
                currency=currency,
                prepayments=prepayments,
            )
            query = (
                f"Calculate EMI for {currency} {principal:,.2f} loan at "
                f"{annual_rate_pct}% for {tenure_years} years"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[2]:
        with st.form("option_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="option_currency",
            )
            option_type = st.selectbox("Option type", ["call", "put"], key="option_type")
            spot = st.number_input(
                "Spot price",
                min_value=0.01,
                value=100.0,
                step=1.0,
                key="option_spot",
            )
            strike = st.number_input(
                "Strike price",
                min_value=0.01,
                value=100.0,
                step=1.0,
                key="option_strike",
            )
            time_to_expiry_years = st.number_input(
                "Time to expiry (years)",
                min_value=0.001,
                value=0.5,
                step=0.05,
                key="option_expiry",
            )
            risk_free_rate_pct = st.number_input(
                "Risk-free rate (%)",
                value=5.0,
                step=0.1,
                key="option_rate",
            )
            volatility_pct = st.number_input(
                "Volatility (%)",
                min_value=0.01,
                value=22.0,
                step=0.5,
                key="option_vol",
            )
            submitted = st.form_submit_button("Price Option", type="primary")

        if submitted:
            tool_result = price_black_scholes_option(
                spot=spot,
                strike=strike,
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate_pct=risk_free_rate_pct,
                volatility_pct=volatility_pct,
                option_type=option_type,
                currency=currency,
            )
            query = (
                f"Price a {time_to_expiry_years}Y {option_type} option with spot "
                f"{currency} {spot:,.2f}, strike {strike:,.2f}, rate "
                f"{risk_free_rate_pct}%, vol {volatility_pct}%"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[3]:
        with st.form("tax_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="tax_currency",
            )
            jurisdiction = st.text_input(
                "Jurisdiction code",
                value="US",
                help="Example: US, IN, UK. Requires a matching non-demo rule pack.",
                key="tax_jurisdiction",
            )
            tax_year = st.number_input(
                "Tax year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
                key="tax_year",
            )
            filing_status = st.selectbox(
                "Filing status",
                ["single", "married_joint", "head_of_household"],
                key="tax_filing_status",
            )
            gross_income = st.number_input(
                "Gross income",
                min_value=0.0,
                value=100000.0,
                step=1000.0,
                key="tax_income",
            )
            deductions = st.number_input(
                "Deductions",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                key="tax_deductions",
            )
            submitted = st.form_submit_button("Estimate Tax", type="primary")

        if submitted:
            tool_result = estimate_tax(
                jurisdiction=jurisdiction,
                tax_year=int(tax_year),
                gross_income=gross_income,
                deductions=deductions,
                filing_status=filing_status,
                currency=currency,
            )
            query = (
                f"Estimate {jurisdiction.upper()} {int(tax_year)} tax for "
                f"{currency} {gross_income:,.2f} gross income"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[1]:
        with st.form("portfolio_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="portfolio_currency",
            )
            monthly_investment = st.number_input(
                "Monthly investment",
                min_value=0.0,
                value=1000.0,
                step=100.0,
                key="portfolio_monthly",
            )
            annual_return_pct = st.number_input(
                "Expected annual return (%)",
                value=8.0,
                step=0.25,
                key="portfolio_return",
            )
            years = st.number_input(
                "Years",
                min_value=0.1,
                value=10.0,
                step=0.5,
                key="portfolio_years",
            )
            initial_amount = st.number_input(
                "Initial amount",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key="portfolio_initial",
            )
            annual_step_up_pct = st.number_input(
                "Annual contribution step-up (%)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                key="portfolio_step_up",
            )
            submitted = st.form_submit_button("Simulate Portfolio", type="primary")

        if submitted:
            tool_result = simulate_portfolio_growth(
                monthly_investment=monthly_investment,
                annual_return_pct=annual_return_pct,
                years=years,
                initial_amount=initial_amount,
                annual_step_up_pct=annual_step_up_pct,
                currency=currency,
            )
            query = (
                f"Simulate investing {currency} {monthly_investment:,.2f}/month "
                f"at {annual_return_pct}% for {years} years"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

