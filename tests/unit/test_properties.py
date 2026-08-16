from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from retropyclip.core.models import Record, RecordKind, uuid7
from retropyclip.core.text import InvalidClip, validate_text
from retropyclip.crypto.envelope import EnvelopeCipher, KDFParameters, KeyInfo

FAST_KDF = KDFParameters(time_cost=1, memory_cost_kib=32, parallelism=1)
PASSPHRASE = "hypothesis-sync-pass"

clip_text = (
    st.text(min_size=1, max_size=80)
    .map(lambda value: value.replace("\x00", ""))
    .filter(lambda value: bool(value.replace("\r\n", "\n").replace("\r", "\n")))
)


def _clip(text: str, sequence: int = 1) -> Record:
    return Record(
        id=uuid7(),
        kind=RecordKind.CLIP,
        captured_at=datetime(2026, 8, 16, tzinfo=UTC),
        device_id="prop-device",
        device_name="Prop",
        sequence=sequence,
        text=text,
    )


@given(clip_text)
@settings(max_examples=25, deadline=None)
def test_payload_round_trip(text: str) -> None:
    original = _clip(text)
    assert Record.from_payload(original.to_payload()) == original


@given(clip_text)
@settings(max_examples=15, deadline=None)
def test_envelope_round_trip(text: str) -> None:
    validate_text(text, 65_536)
    _, key = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    cipher = EnvelopeCipher(key)
    original = _clip(text)
    restored = cipher.decrypt(cipher.encrypt(original), max_envelope_bytes=200_000)
    assert restored.text == original.text
    assert restored.id == original.id


@given(st.binary(min_size=1, max_size=40))
@settings(max_examples=20, deadline=None)
def test_binary_looking_input_is_either_stored_or_rejected(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        assert validate_text(text, 65_536).encode("utf-8")
    except InvalidClip:
        assert (not text.replace("\r\n", "\n").replace("\r", "\n")) or "\x00" in text
