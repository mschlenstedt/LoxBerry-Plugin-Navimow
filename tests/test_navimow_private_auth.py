import pytest

from navimow_private_auth import Tokens, _sign, _signed_headers


def test_sign_known_vector():
    # Von Hand mit hashlib.sha256 nachgerechnet, unabhaengig von _sign().
    vector = {"a": "1", "b": "2", "c": "x"}
    expected = "bd2ca1cba8d25bd1e5abaf6961680e0dde59957db76c1588aba3eac707a70bb6"
    assert _sign(vector) == expected


def test_signed_headers_structure():
    h = _signed_headers("/v3/user/login", {"username": "a@b.c", "password": "x", "device": "ANDROID"})
    assert h["clientId"] == "mowerbot_app_prod"
    assert len(h["sign"]) == 64
    int(h["sign"], 16)


def test_tokens_defaults():
    t = Tokens(access_token="AT", refresh_token="RT")
    assert t.uuid == ""
    assert t.region == "fra"
