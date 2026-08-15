from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RecordKind(StrEnum):
    CLIP = "clip"
    TOMBSTONE = "tombstone"


class SyncState(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    REMOTE = "remote"


class OverallSyncState(StrEnum):
    OFFLINE = "offline"
    SYNCING = "syncing"
    UP_TO_DATE = "up_to_date"
    AUTH_REQUIRED = "authentication_required"
    ERROR = "error"


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def uuid7() -> str:
    """Return an RFC 9562 UUIDv7 using the current Unix millisecond timestamp."""
    timestamp_ms = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return str(uuid.UUID(int=value))


@dataclass(frozen=True, slots=True)
class Record:
    id: str
    kind: RecordKind
    captured_at: datetime
    device_id: str
    device_name: str
    sequence: int
    text: str | None = None
    target_id: str | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        try:
            parsed_id = uuid.UUID(self.id)
        except ValueError as error:
            raise ValueError("record id must be a UUID") from error
        if parsed_id.version not in {4, 7}:
            raise ValueError("record id must be UUIDv7 (UUIDv4 accepted for legacy fixtures)")
        if self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if not self.device_id or not self.device_name:
            raise ValueError("device identity is required")
        if self.kind is RecordKind.CLIP:
            if self.text is None or self.target_id is not None:
                raise ValueError("clip records require text and cannot have a target")
        elif (
            self.kind is RecordKind.TOMBSTONE
            and (self.target_id is None or self.text is not None)
        ):
            raise ValueError("tombstones require a target and cannot contain text")

    def to_payload(self, *, content_hash: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "retropyclip.payload/1",
            "id": self.id,
            "kind": self.kind.value,
            "captured_at": format_utc(self.captured_at),
            "device_id": self.device_id,
            "device_name": self.device_name,
            "sequence": self.sequence,
        }
        if self.kind is RecordKind.CLIP:
            payload["text"] = self.text
            payload["content_hash"] = content_hash or self.content_hash
        else:
            payload["target_id"] = self.target_id
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Record:
        if payload.get("schema") != "retropyclip.payload/1":
            raise ValueError("unsupported record payload schema")
        allowed = {
            "schema",
            "id",
            "kind",
            "captured_at",
            "device_id",
            "device_name",
            "sequence",
            "text",
            "target_id",
            "content_hash",
        }
        if unknown := set(payload) - allowed:
            raise ValueError(f"unexpected payload fields: {', '.join(sorted(unknown))}")
        try:
            kind = RecordKind(str(payload["kind"]))
            return cls(
                id=str(payload["id"]),
                kind=kind,
                captured_at=parse_utc(str(payload["captured_at"])),
                device_id=str(payload["device_id"]),
                device_name=str(payload["device_name"]),
                sequence=int(payload["sequence"]),
                text=str(payload["text"]) if kind is RecordKind.CLIP else None,
                target_id=str(payload["target_id"])
                if kind is RecordKind.TOMBSTONE
                else None,
                content_hash=str(payload["content_hash"])
                if payload.get("content_hash") is not None
                else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("malformed record payload") from error


@dataclass(frozen=True, slots=True)
class StoredRecord:
    record: Record
    sync_state: SyncState
    origin: str
    remote_file_id: str | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class SyncReport:
    pulled: int = 0
    pushed: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()

    def merged(self, other: SyncReport) -> SyncReport:
        return SyncReport(
            pulled=self.pulled + other.pulled,
            pushed=self.pushed + other.pushed,
            skipped=self.skipped + other.skipped,
            errors=self.errors + other.errors,
        )
