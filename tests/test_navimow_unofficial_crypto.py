import base64
import json

from navimow_unofficial_crypto import pack, decode_response, SESSION_KEY, _aes_cbc_enc


def test_pack_envelope_shape():
    env = pack({"vehicle_sn": "TEST123"})
    assert set(env) == {"d", "h", "k", "p", "t"}
    assert env["p"] == "101"
    assert env["t"] == "0"
    assert len(env["h"]) == 32
    int(env["h"], 16)  # gültiges Hex
    assert len(base64.b64decode(env["k"])) == 128  # RSA-1024-Block
    base64.b64decode(env["d"])  # gültiges Base64


def test_decode_response_roundtrip():
    business = {"code": 1, "data": {"foo": "bar"}}
    data_b64 = base64.b64encode(json.dumps(business, separators=(",", ":")).encode()).decode()
    pt = json.dumps({"data": data_b64}, separators=(",", ":")).encode()
    r = base64.b64encode(_aes_cbc_enc(SESSION_KEY, pt)).decode()
    assert decode_response({"r": r, "s": "1", "v": "1"}) == business


def test_decode_response_passthrough_without_r():
    err = {"code": 90015, "desc": "token expired"}
    assert decode_response(err) == err
