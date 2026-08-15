from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from retropyclip.core.models import Record, RecordKind, parse_utc, uuid7
from retropyclip.core.text import InvalidClip, normalize_text, one_line_preview, validate_text


def test_uuid7_has_expected_version_and_variant() -> None:
    value = uuid.UUID(uuid7())
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_record_payload_round_trip() -> None:
    original = Record(
        id=uuid7(),
        kind=RecordKind.CLIP,
        captured_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        device_id="device-a",
        device_name="Mac",
        sequence=3,
        text="  exact\ntext  ",
        content_hash="digest",
    )
    restored = Record.from_payload(original.to_payload())
    assert restored == original


def test_tombstone_requires_target() -> None:
    with pytest.raises(ValueError, match="tombstones require"):
        Record(
            id=uuid7(),
            kind=RecordKind.TOMBSTONE,
            captured_at=datetime.now(UTC),
            device_id="device",
            device_name="Pi",
            sequence=1,
        )


def test_text_normalization_only_changes_line_endings() -> None:
    assert normalize_text("  a\r\nb\rc  \t") == "  a\nb\nc  \t"


def test_validate_text_rejects_empty_and_oversized() -> None:
    with pytest.raises(InvalidClip, match="empty"):
        validate_text("", 10)
    with pytest.raises(InvalidClip, match="limit"):
        validate_text("£" * 6, 10)


def test_preview_is_one_line_without_changing_source() -> None:
    source = " first\nsecond\tthird "
    assert one_line_preview(source) == "first second third"
    assert source == " first\nsecond\tthird "


def test_parse_utc_normalizes_to_utc() -> None:
    assert parse_utc("2026-08-15T13:00:00+01:00") == datetime(2026, 8, 15, 12, tzinfo=UTC)
