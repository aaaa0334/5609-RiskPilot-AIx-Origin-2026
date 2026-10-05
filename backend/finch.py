"""Finch Direct API adapter for the free RiskPilot educational pilot."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from data_loader import extract_risk_engine_input, load_stock_snapshot
from risk_engine import UserInput, run_risk_engine

router = APIRouter(prefix="/api/finch", tags=["Finch Direct API"])


class FinchRiskRequest(BaseModel):
    stock_code: str = Field(default="601318", pattern=r"^\d{6}$")
    capital: float = Field(default=100000, ge=1000, le=10000000)
    max_loss: float = Field(default=3000, gt=0, le=10000000)


@router.get("/health")
def finch_health():
    """Anonymous health endpoint required by Finch Direct API."""
    return {
        "status": "ready",
        "service": "RiskPilot Risk Discipline Coach",
        "mode": "historical_education",
        "side_effects": "none",
    }


@router.post("/risk-coach")
def finch_risk_coach(request: FinchRiskRequest):
    """Return a compact, deterministic historical risk-budget simulation."""
    if request.max_loss > request.capital:
        raise HTTPException(400, "max_loss must not exceed capital")

    snapshot = load_stock_snapshot(request.stock_code)
    if snapshot is None:
        raise HTTPException(404, "No verified historical snapshot is available for this stock code")

    stock = extract_risk_engine_input(snapshot, request.stock_code)
    result = run_risk_engine(UserInput(
        stock_code=request.stock_code,
        stock_name=stock["stock_name"],
        capital=request.capital,
        max_loss=request.max_loss,
        current_price=stock["current_price"],
        atr_14=stock["atr_14"],
        key_support=stock["key_support"],
        board=stock["board"],
    ))
    position = result.position

    if position.vetoed:
        summary = (
            "The modeled minimum position does not fit the selected standard-scenario "
            "loss budget. This is a historical education result, not a trading instruction."
        )
    else:
        summary = (
            f"In this historical snapshot, a simulated position of {position.final_shares} shares "
            f"has a modeled standard-scenario loss of CNY {position.standard_loss:.2f}, "
            f"within the selected CNY {request.max_loss:.2f} budget. "
            "Actual losses can be larger in gaps, limit moves, suspensions, or illiquid markets."
        )

    return {
        "service": "RiskPilot Risk Discipline Coach",
        "result_type": "historical_risk_education",
        "stock": {
            "code": request.stock_code,
            "name": stock["stock_name"],
            "snapshot_date": stock.get("snapshot_date", ""),
            "is_live": False,
            "is_synthetic": bool(stock.get("is_synthetic", False)),
        },
        "input": {
            "capital_cny": round(request.capital, 2),
            "max_loss_budget_cny": round(request.max_loss, 2),
        },
        "simulation": {
            "reference_price_cny": round(stock["current_price"], 4),
            "reference_stop_price_cny": round(position.stop_loss_price, 4),
            "simulated_shares": position.final_shares,
            "simulated_position_value_cny": round(position.final_position_value, 2),
            "simulated_position_ratio_pct": round(position.final_position_ratio * 100, 2),
            "standard_scenario_loss_cny": round(position.standard_loss, 2),
            "within_selected_budget": bool(position.within_budget),
        },
        "risk_flags": {
            "risk_mismatch": bool(position.vetoed),
            "reason": position.veto_reason or "",
            "high_risk_warning": bool(position.high_risk_warning),
        },
        "stress_scenarios": [
            {
                "scenario": item.scenario,
                "modeled_loss_cny": round(item.actual_loss, 2),
                "exceeds_selected_budget": bool(item.exceeds_budget),
            }
            for item in result.stress_tests
        ],
        "summary": summary,
        "limitations": [
            "Uses stored historical snapshots rather than live market data.",
            "Does not connect to a brokerage account or execute transactions.",
            "Historical and modeled results do not predict future performance.",
            "This service is for education and research, not investment advice.",
        ],
    }