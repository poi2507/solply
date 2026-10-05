"""solply-guard — guardrails for AI agents that hold a wallet.

Extracted from Solply (an agent that settles franchise supply payments in USDC on Solana).
No dependencies; bring your own wallet, RPC client and model.
"""

from solply_guard.confidence import Route, route
from solply_guard.onchain import Check, Expected, Observed, parse_transaction, verify_payment
from solply_guard.spend import SpendDecision, SpendPolicy, Verdict, affordable, check_spend

__all__ = [
    "Check", "Expected", "Observed", "Route", "SpendDecision", "SpendPolicy", "Verdict",
    "affordable", "check_spend", "parse_transaction", "route", "verify_payment",
]
__version__ = "0.1.0"
