from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from retropyclip.core.models import Record, RecordKind, uuid7
from retropyclip.crypto.diagnostics import sanitize_diagnostic
from retropyclip.crypto.envelope import (
    CryptoError,
    EnvelopeCipher,
    InvalidEnvelope,
    InvalidPassphrase,
    KDFParameters,
    KeyInfo,
    derive_key,
)

FAST_KDF = KDFParameters(time_cost=1, memory_cost_kib=64, parallelism=1)
KAT_KDF = KDFParameters(time_cost=1, memory_cost_kib=32, parallelism=1)
PASSPHRASE = "correct horse battery staple"
KAT_PASSPHRASE = "known-answer-passphrase"
KAT_SALT = bytes.fromhex("00112233445566778899aabbccddeeff")
KAT_KEY = bytes.fromhex("97313ae64a93b966095f83920d7df2f4aff44d3fa3f44f5c0806c2ee8c9cc5f3")
KAT_NONCE = bytes.fromhex("0102030405060708090a0b0c")
KAT_RECORD_ID = "018f0000-0000-7000-8000-000000000001"
KAT_ENVELOPE = (
    '{"ciphertext":"NdPpk4CcKJTl5ZnYSOOd0FU+dQ7SKOn93KH2C1nbK6Bb7SrqDmWGnOIml1QMnN4kvA9G9'
    "/cdkmdDxtH27KHgnTnyWWhK7BWS4dVv7+ZodoZyeTozeEqn+OadRxL6VtGW4VI0ZFxyAP5Fuc/wY06l3oqKd+"
    "rLS7BcdENP6qgqBg6K+hssgatduuhZqeIXT3y+fIOLLqwFsxpUtRa4QCzEm3oPvI4o8J7WFu7z19WB7ZvlBd7"
    "PxYn1L4tHP4fVrSOYAn57dJsov/qBN5rIuMo96n6Oj2q+TfYk/mOs/m57UqEWw+NYzTojS8oBYxjB1dL0e0wq"
    "4mj0+WVVJv4g+795trMzvYtlydLqQRp64mklL8CG7re9PAog8yIZAlIKYfuxkZlNwwByoqN1HDz88Yv6RbsjD"
    'BzdoOcfJWdPvCwdMA==","id":"018f0000-0000-7000-8000-000000000001","kind":"clip",'
    '"nonce":"AQIDBAUGBwgJCgsM","schema":"retropyclip.record/1"}'
)


def clip(**overrides: object) -> Record:
    payload = dict(
        id=uuid7(),
        kind=RecordKind.CLIP,
        captured_at=datetime(2026, 8, 15, tzinfo=UTC),
        device_id="device",
        device_name="Mac",
        sequence=1,
        text=" private text \n",
        content_hash="local digest replaced during encryption",
    )
    payload.update(overrides)
    return Record(**payload)  # type: ignore[arg-type]


def test_keyinfo_round_trip_and_passphrase_verifier() -> None:
    keyinfo, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    restored = KeyInfo.from_json(keyinfo.to_json())
    assert restored.derive_and_verify(PASSPHRASE) == key
    with pytest.raises(InvalidPassphrase, match="does not match"):
        restored.derive_and_verify("incorrect passphrase value")


def test_passphrase_minimum_length() -> None:
    with pytest.raises(InvalidPassphrase, match="at least"):
        KeyInfo.create("short", parameters=FAST_KDF)


def test_known_answer_key_derivation() -> None:
    assert derive_key(KAT_PASSPHRASE, KAT_SALT, KAT_KDF) == KAT_KEY


def test_known_answer_encrypt_decrypt() -> None:
    cipher = EnvelopeCipher(KAT_KEY)
    record = clip(
        id=KAT_RECORD_ID,
        captured_at=datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        device_id="kat-device",
        device_name="KAT",
        text="known plaintext\n",
    )
    encrypted = cipher.encrypt(record, nonce=KAT_NONCE)
    assert encrypted.decode().strip() == KAT_ENVELOPE
    restored = cipher.decrypt(encrypted, max_envelope_bytes=4096)
    assert restored.text == "known plaintext\n"
    fixture = EnvelopeCipher(KAT_KEY).decrypt(KAT_ENVELOPE.encode() + b"\n", max_envelope_bytes=4096)
    assert fixture.text == "known plaintext\n"


def test_envelope_round_trip_hides_plaintext() -> None:
    _keyinfo, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    original = clip()
    encrypted = cipher.encrypt(original)
    assert original.text.encode() not in encrypted  # type: ignore[union-attr]
    restored = cipher.decrypt(encrypted, max_envelope_bytes=4096)
    assert restored.text == original.text
    assert restored.id == original.id
    assert restored.content_hash != original.content_hash


def test_successive_encryptions_use_distinct_nonces() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    first = json.loads(cipher.encrypt(clip()))
    second = json.loads(cipher.encrypt(clip()))
    assert first["nonce"] != second["nonce"]


def test_injected_nonce_must_be_12_bytes() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    with pytest.raises(CryptoError, match="nonce"):
        EnvelopeCipher(key).encrypt(clip(), nonce=b"short")


def test_envelope_tampering_is_rejected() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    payload = json.loads(cipher.encrypt(clip()))
    payload["id"] = uuid7()
    tampered = json.dumps(payload).encode()
    with pytest.raises(InvalidEnvelope, match="authentication failed"):
        cipher.decrypt(tampered, max_envelope_bytes=4096)


def test_truncated_record_is_rejected() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    encrypted = cipher.encrypt(clip())
    with pytest.raises(InvalidEnvelope):
        cipher.decrypt(encrypted[:20], max_envelope_bytes=4096)
    payload = json.loads(encrypted)
    payload["ciphertext"] = payload["ciphertext"][:-8]
    with pytest.raises(InvalidEnvelope):
        cipher.decrypt(json.dumps(payload).encode(), max_envelope_bytes=4096)


def test_wrong_passphrase_cannot_decrypt() -> None:
    info, _ = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    encrypted = EnvelopeCipher(info.derive_and_verify(PASSPHRASE)).encrypt(clip())
    other, other_key = KeyInfo.create("a different long passphrase", parameters=FAST_KDF)
    del other
    with pytest.raises(InvalidEnvelope, match="authentication failed"):
        EnvelopeCipher(other_key).decrypt(encrypted, max_envelope_bytes=4096)


def test_nonce_and_version_mismatch_are_rejected() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    original = clip()
    payload = json.loads(cipher.encrypt(original, nonce=KAT_NONCE))
    payload["nonce"] = "AAAAAAAAAAAAAAAA"
    with pytest.raises(InvalidEnvelope, match="authentication failed"):
        cipher.decrypt(json.dumps(payload).encode(), max_envelope_bytes=4096)
    payload = json.loads(cipher.encrypt(original))
    payload["schema"] = "retropyclip.record/2"
    with pytest.raises(InvalidEnvelope, match="unsupported encrypted record schema"):
        cipher.decrypt(json.dumps(payload).encode(), max_envelope_bytes=4096)


def test_crypto_errors_do_not_include_plaintext_or_key() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    original = clip(text="super-secret-clipboard-value")
    encrypted = EnvelopeCipher(key).encrypt(original)
    payload = json.loads(encrypted)
    payload["id"] = uuid7()
    with pytest.raises(InvalidEnvelope) as error:
        EnvelopeCipher(key).decrypt(json.dumps(payload).encode(), max_envelope_bytes=4096)
    message = str(error.value)
    assert "super-secret-clipboard-value" not in message
    assert key.hex() not in message
    assert PASSPHRASE not in message


def test_oversized_envelope_is_rejected_before_parsing() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    with pytest.raises(InvalidEnvelope, match="size limit"):
        EnvelopeCipher(key).decrypt(b"{}" * 100, max_envelope_bytes=10)


def test_sanitize_diagnostic_redacts_tokens_and_secrets() -> None:
    dirty = "token ya29.a0AbCdEf and passphrase hunter2 plus 1//refresh"
    clean = sanitize_diagnostic(dirty, secrets=("hunter2",))
    assert "ya29." not in clean
    assert "hunter2" not in clean
    assert "1//refresh" not in clean
    assert "[redacted]" in clean
