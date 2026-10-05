import pytest

from solply_guard import route

A = {"accept", "reject"}


def test_confident_allowed_choice_goes_fast():
    assert route("reject", 0.93, 70, allowed=A).fast


def test_low_confidence_goes_slow():
    r = route("reject", 0.44, 70, allowed=A)
    assert not r.fast and "44%" in r.reason


def test_off_switch_unknown_choice_and_always_slow():
    assert not route("reject", 0.99, 100, allowed=A).fast
    assert not route("maybe", 0.99, 70, allowed=A).fast
    assert not route("accept", 0.99, 70, allowed=A, always_slow={"accept"}).fast


def test_bad_threshold():
    with pytest.raises(ValueError):
        route("reject", 0.9, 120, allowed=A)
