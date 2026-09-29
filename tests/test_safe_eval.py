import pytest

from ws.utils.safe_eval import ConditionSecurityError, evaluate_condition


def test_equality_true():
    assert evaluate_condition(
        "slots.get('status') == '已发货'",
        {"status": "已发货"}) is True


def test_equality_false():
    assert evaluate_condition(
        "slots.get('status') == '已发货'",
        {"status": "待付款"}) is False


def test_missing_key_default():
    assert evaluate_condition(
        "slots.get('x', '') == ''", {}) is True


def test_in_operator():
    assert evaluate_condition(
        "'已' in slots.get('status', '')",
        {"status": "已发货"}) is True


def test_bool_and_or():
    slots = {"a": "x", "b": "y"}
    assert evaluate_condition(
        "slots.get('a') == 'x' and slots.get('b') == 'y'", slots) is True
    assert evaluate_condition(
        "slots.get('a') == 'z' or slots.get('b') == 'y'", slots) is True


def test_not_operator():
    assert evaluate_condition("not slots.get('missing')", {}) is True


def test_subscript():
    assert evaluate_condition("slots['a'] == 1", {"a": 1}) is True


def test_numeric_compare():
    assert evaluate_condition(
        "slots.get('n', 0) > 3", {"n": 5}) is True


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hacked')",
    "slots.__class__",
    "(lambda: 1)()",
    "[x for x in range(3)]",
    "open('x')",
    "slots.get('a') or unknown_name",
    "slots.keys()",
])
def test_malicious_expressions_rejected(expr):
    with pytest.raises(ConditionSecurityError):
        evaluate_condition(expr, {})


def test_syntax_error_rejected():
    with pytest.raises(ConditionSecurityError):
        evaluate_condition("slots.get(", {})


def test_empty_condition_rejected():
    with pytest.raises(ConditionSecurityError):
        evaluate_condition("   ", {})
