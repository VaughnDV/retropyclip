from __future__ import annotations

from pathlib import Path

from retropyclip.crypto.envelope import EnvelopeCipher, KeyInfo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v1"
KAT_KEY = bytes.fromhex("97313ae64a93b966095f83920d7df2f4aff44d3fa3f44f5c0806c2ee8c9cc5f3")


def test_released_v1_envelope_fixture_still_decrypts() -> None:
    raw = (FIXTURES / "envelope.rpc.json").read_bytes()
    record = EnvelopeCipher(KAT_KEY).decrypt(raw, max_envelope_bytes=4096)
    assert record.text == "known plaintext\n"
    assert record.id == "018f0000-0000-7000-8000-000000000001"


def test_released_v1_keyinfo_fixture_still_verifies() -> None:
    info = KeyInfo.from_json((FIXTURES / "keyinfo.json").read_bytes())
    assert info.derive_and_verify("known-answer-passphrase") == KAT_KEY
