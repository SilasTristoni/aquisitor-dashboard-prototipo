import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.acquisition import _compare
from app.services.statistics import describe


def test_password_hash_and_token_roundtrip():
    password_hash = hash_password("uma-senha-segura")
    assert password_hash != "uma-senha-segura"
    assert verify_password("uma-senha-segura", password_hash)
    assert not verify_password("incorreta", password_hash)
    token = create_access_token("42", "operator")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "operator"


def test_descriptive_statistics():
    result = describe([1, 2, 3, 4, 100])
    assert result["count"] == 5
    assert result["min"] == 1
    assert result["max"] == 100
    assert result["median"] == 3
    assert result["range"] == 99
    assert result["p95"] == 100


@pytest.mark.parametrize(
    ("value", "operator", "threshold", "expected"),
    [(81, ">", 80, True), (80, ">", 80, False), (80, ">=", 80, True), (10, "<", 20, True)],
)
def test_alert_operators(value, operator, threshold, expected):
    assert _compare(value, operator, threshold) is expected
