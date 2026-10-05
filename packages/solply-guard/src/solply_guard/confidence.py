"""Confidence gate — when may a fast decision model act without a slower second look?

A System One model (one that scores fixed options, such as TypeSafe's Jev) returns a choice and a
confidence. Accept it only when:

  - the choice is one you allowed for this decision,
  - the confidence clears a bar a person set (as a percentage; 100 turns the fast path off),
  - and the choice is not one you always want reviewed (e.g. "accept" when accepting also requires
    picking *which* candidate — a question the fast model was never asked).

Otherwise route to the slow path (an LLM that reasons from scratch, or a person).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    fast: bool
    reason: str


def route(choice: str, confidence: float, min_confidence_pct: float, *,
          allowed: set[str], always_slow: set[str] = frozenset()) -> Route:
    if not 0 <= min_confidence_pct <= 100:
        raise ValueError("min_confidence_pct must be within 0..100")
    if min_confidence_pct >= 100:
        return Route(False, "the fast path is switched off")
    if choice not in allowed:
        return Route(False, f"'{choice}' is not an allowed option")
    if choice in always_slow:
        return Route(False, f"'{choice}' always gets a second look")
    if confidence * 100 < min_confidence_pct:
        return Route(False, f"confidence {confidence * 100:.0f}% is under {min_confidence_pct:g}%")
    return Route(True, f"confidence {confidence * 100:.0f}% clears {min_confidence_pct:g}%")
