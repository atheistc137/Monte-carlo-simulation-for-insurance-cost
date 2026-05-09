"""
Liquidation waterfall: compute coverage ratio when borrower defaults.

Assets: BTC collateral (sold at spot) + PUT option (sold at mark-to-market).
Liabilities: outstanding debt + liquidator fee (buffer % of debt).
Surplus goes to protocol. Shortfall = lender loss.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WaterfallResult:
    btc_value: float
    put_mtm: float
    total_proceeds: float
    debt: float
    liquidator_fee: float
    total_liabilities: float
    coverage_ratio: float
    shortfall_usd: float
    surplus_to_protocol: float


def compute_waterfall(
    allocated_btc: float,
    spot: float,
    put_mtm: float,
    debt: float,
    liq_buffer: float,
) -> WaterfallResult:
    """Compute the liquidation waterfall.

    Parameters
    ----------
    allocated_btc : BTC remaining in the loan (after any micro-liquidations)
    spot          : BTC price at default
    put_mtm       : Mark-to-market value of held PUT (after slippage)
    debt          : Outstanding debt (principal + accrued interest - payments)
    liq_buffer    : Liquidator fee as fraction of debt (e.g. 0.03)

    Returns
    -------
    WaterfallResult with all waterfall components.
    """
    btc_value = allocated_btc * spot
    total_proceeds = btc_value + put_mtm

    liquidator_fee = liq_buffer * debt
    total_liabilities = debt + liquidator_fee

    if total_liabilities <= 0:
        coverage_ratio = float("inf")
    else:
        coverage_ratio = total_proceeds / total_liabilities

    if total_proceeds >= total_liabilities:
        shortfall = 0.0
        surplus = total_proceeds - total_liabilities
    else:
        shortfall = total_liabilities - total_proceeds
        surplus = 0.0

    return WaterfallResult(
        btc_value=btc_value,
        put_mtm=put_mtm,
        total_proceeds=total_proceeds,
        debt=debt,
        liquidator_fee=liquidator_fee,
        total_liabilities=total_liabilities,
        coverage_ratio=coverage_ratio,
        shortfall_usd=shortfall,
        surplus_to_protocol=surplus,
    )
