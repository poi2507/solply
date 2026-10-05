"""Spend guard — may an agent move this money on its own?

An autonomous agent that holds a wallet needs two numbers set by a person, not by the model:

  auto_pay_limit  — above this amount a human approves the payment
  min_reserve     — the agent never pays if the wallet would drop below this

The model may choose *whether* to pay; these numbers decide whether it *may*.
"""

from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    PAY = "pay"                    # within every bound — the agent may pay now
    NEEDS_HUMAN = "needs_human"    # over the auto-pay limit — park it for a person
    INSUFFICIENT = "insufficient"  # the wallet cannot cover the amount
    BREAKS_RESERVE = "breaks_reserve"  # it could pay, but would fall under the reserve


@dataclass(frozen=True)
class SpendPolicy:
    auto_pay_limit: float
    min_reserve: float = 0.0

    def __post_init__(self) -> None:
        if self.auto_pay_limit <= 0:
            raise ValueError("auto_pay_limit must be positive")
        if self.min_reserve < 0:
            raise ValueError("min_reserve cannot be negative")


@dataclass(frozen=True)
class SpendDecision:
    verdict: Verdict
    reason: str
    amount: float
    balance_after: float | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.PAY


def check_spend(amount: float, policy: SpendPolicy, *, balance: float | None = None,
                human_approved: bool = False) -> SpendDecision:
    """Decide whether an agent may pay `amount` by itself.

    `balance=None` checks only the authority (the limit) — use it at the moment of paying when the
    balance check already happened upstream. `human_approved=True` lifts only the limit; a person
    can approve a big payment but cannot make an empty wallet pay it.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount > policy.auto_pay_limit and not human_approved:
        return SpendDecision(Verdict.NEEDS_HUMAN,
                             f"{amount:g} is over the auto-pay limit of {policy.auto_pay_limit:g}",
                             amount)
    if balance is None:
        return SpendDecision(Verdict.PAY, "within the auto-pay limit", amount)
    after = round(balance - amount, 6)
    if after < 0:
        return SpendDecision(Verdict.INSUFFICIENT,
                             f"balance {balance:g} cannot cover {amount:g}", amount, after)
    if after < policy.min_reserve:
        return SpendDecision(Verdict.BREAKS_RESERVE,
                             f"paying {amount:g} leaves {after:g}, under the reserve of {policy.min_reserve:g}",
                             amount, after)
    return SpendDecision(Verdict.PAY, "within the limit and keeps the reserve", amount, after)


def affordable(balance: float, policy: SpendPolicy) -> float:
    """The most the agent could pay right now without breaking the reserve (ignores the limit)."""
    return round(max(0.0, balance - policy.min_reserve), 6)
