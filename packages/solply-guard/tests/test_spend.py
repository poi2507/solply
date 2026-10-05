import pytest

from solply_guard import SpendPolicy, Verdict, affordable, check_spend

P = SpendPolicy(auto_pay_limit=10, min_reserve=2)


def test_within_bounds_pays():
    d = check_spend(5, P, balance=20)
    assert d.allowed and d.balance_after == 15


def test_over_limit_goes_to_a_human_even_if_rich():
    d = check_spend(12, P, balance=1000)
    assert d.verdict is Verdict.NEEDS_HUMAN and not d.allowed


def test_human_approval_lifts_only_the_limit():
    assert check_spend(12, P, balance=1000, human_approved=True).allowed
    assert check_spend(12, P, balance=5, human_approved=True).verdict is Verdict.INSUFFICIENT


def test_reserve_is_kept():
    d = check_spend(9, P, balance=10)
    assert d.verdict is Verdict.BREAKS_RESERVE and d.balance_after == 1


def test_limit_only_check_when_balance_unknown():
    assert check_spend(9, P).allowed
    assert check_spend(11, P).verdict is Verdict.NEEDS_HUMAN


def test_affordable_and_bad_inputs():
    assert affordable(10, P) == 8 and affordable(1, P) == 0
    with pytest.raises(ValueError):
        check_spend(0, P)
    with pytest.raises(ValueError):
        SpendPolicy(auto_pay_limit=0)
