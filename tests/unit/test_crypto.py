from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from retropyclip.core.models import Record, RecordKind, uuid7
from retropyclip.crypto.envelope import (
    EnvelopeCipher,
    InvalidEnvelope,
    InvalidPassphrase,
    KDFParameters,
    KeyInfo,
)

FAST_KDF = KDFParameters(time_cost=1, memory_cost_kib=64, parallelism=1)
PASSPHRASE = "correct horse battery staple"


def clip() -> Record:
    return Record(
        id=uuid7(),
        kind=RecordKind.CLIP,
        captured_at=datetime(2026, 8, 15, tzinfo=UTC),
        device_id="device",
        device_name="Mac",
        sequence=1,
        text=" private text \n",
        content_hash="local digest replaced during encryption",
    )


def test_keyinfo_round_trip_and_passphrase_verifier() -> None:
    keyinfo, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    restored = KeyInfo.from_json(keyinfo.to_json())
    assert restored.derive_and_verify(PASSPHRASE) == key
    with pytest.raises(InvalidPassphrase, match="does not match"):
        restored.derive_and_verify("incorrect passphrase value")


def test_passphrase_minimum_length() -> None:
    with pytest.raises(InvalidPassphrase, match="at least"):
        KeyInfo.create("short", parameters=FAST_KDF)


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


def test_envelope_tampering_is_rejected() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    payload = json.loads(cipher.encrypt(clip()))
    payload["id"] = uuid7()
    tampered = json.dumps(payload).encode()
    with pytest.raises(InvalidEnvelope, match="authentication failed"):
        cipher.decrypt(tampered, max_envelope_bytes=4096)


def test_oversized_envelope_is_rejected_before_parsing() -> None:
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    with pytest.raises(InvalidEnvelope, match="size limit"):
        EnvelopeCipher(key).decrypt(b"{}" * 100, max_envelope_bytes=10)
