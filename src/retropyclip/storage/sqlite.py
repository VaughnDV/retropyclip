from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from retropyclip.config import ensure_private_dir, ensure_private_file
from retropyclip.core.models import (
    Record,
    RecordKind,
    StoredRecord,
    SyncState,
    format_utc,
    parse_utc,
    utc_now,
    uuid7,
)
from retropyclip.core.text import local_content_hash, validate_text
from retropyclip.crypto.diagnostics import sanitize_diagnostic

SCHEMA_VERSION = 1


class Repository:
    def __init__(self, database: Path) -> None:
        self.database = database
        ensure_private_dir(database.parent)
        self._initialize()
        self._protect_database_files()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
                )
            if current == 0:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    CREATE TABLE meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE records (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL CHECK (kind IN ('clip', 'tombstone')),
                        text TEXT,
                        target_id TEXT,
                        captured_at TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        device_name TEXT NOT NULL,
                        sequence INTEGER NOT NULL CHECK (sequence > 0),
                        content_hash TEXT,
                        origin TEXT NOT NULL CHECK (origin IN ('local', 'remote')),
                        sync_state TEXT NOT NULL CHECK (sync_state IN ('pending', 'synced', 'remote')),
                        remote_file_id TEXT,
                        deleted_at TEXT,
                        created_at TEXT NOT NULL,
                        CHECK (
                            (kind = 'clip' AND text IS NOT NULL AND target_id IS NULL)
                            OR
                            (kind = 'tombstone' AND text IS NULL AND target_id IS NOT NULL)
                        )
                    );
                    CREATE INDEX records_history_idx
                        ON records(kind, deleted_at, captured_at DESC, device_id, sequence DESC);
                    CREATE INDEX records_pending_idx ON records(sync_state, kind);
                    CREATE INDEX records_tombstone_target_idx ON records(target_id)
                        WHERE kind = 'tombstone';
                    CREATE TABLE seen_remote (
                        remote_file_id TEXT PRIMARY KEY,
                        record_id TEXT,
                        seen_at TEXT NOT NULL
                    );
                    CREATE TABLE sync_errors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        occurred_at TEXT NOT NULL,
                        code TEXT NOT NULL,
                        message TEXT NOT NULL
                    );
                    PRAGMA user_version = 1;
                    """
                )
        self._protect_database_files()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
            self._protect_database_files()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _protect_database_files(self) -> None:
        ensure_private_file(self.database)
        for suffix in ("-wal", "-shm", "-journal"):
            ensure_private_file(Path(str(self.database) + suffix))

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT value FROM meta WHERE key = 'device_sequence'").fetchone()
        sequence = int(row[0]) + 1 if row else 1
        connection.execute(
            """
            INSERT INTO meta(key, value) VALUES('device_sequence', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(sequence),),
        )
        return sequence

    def create_local_clip(
        self,
        text: str,
        *,
        device_id: str,
        device_name: str,
        max_bytes: int,
        history_limit: int,
        captured_at: datetime | None = None,
    ) -> tuple[StoredRecord | None, bool]:
        normalized = validate_text(text, max_bytes)
        digest = local_content_hash(normalized)
        with self.transaction() as connection:
            suppressed = connection.execute(
                "SELECT value FROM meta WHERE key = 'clipboard_suppression_hash'"
            ).fetchone()
            if suppressed:
                connection.execute("DELETE FROM meta WHERE key = 'clipboard_suppression_hash'")
                if suppressed[0] == digest:
                    row = connection.execute(
                        """
                        SELECT * FROM records
                        WHERE kind = 'clip' AND deleted_at IS NULL AND content_hash = ?
                        ORDER BY captured_at DESC, sequence DESC LIMIT 1
                        """,
                        (digest,),
                    ).fetchone()
                    return (self._stored_from_row(row) if row else None), False

            latest = connection.execute(
                """
                SELECT * FROM records
                WHERE kind = 'clip' AND deleted_at IS NULL
                ORDER BY captured_at DESC, device_id, sequence DESC, id LIMIT 1
                """
            ).fetchone()
            if latest and latest["content_hash"] == digest and latest["text"] == normalized:
                return self._stored_from_row(latest), False

            record = Record(
                id=uuid7(),
                kind=RecordKind.CLIP,
                captured_at=captured_at or utc_now(),
                device_id=device_id,
                device_name=device_name,
                sequence=self._next_sequence(connection),
                text=normalized,
                content_hash=digest,
            )
            self._insert_record(
                connection,
                record,
                origin="local",
                sync_state=SyncState.PENDING,
                remote_file_id=None,
            )
            self._prune(connection, history_limit)
            row = connection.execute("SELECT * FROM records WHERE id = ?", (record.id,)).fetchone()
            assert row is not None
            return self._stored_from_row(row), True

    def set_clipboard_suppression(self, text: str) -> None:
        self.set_meta("clipboard_suppression_hash", local_content_hash(text))

    def create_tombstones(
        self,
        target_ids: Sequence[str],
        *,
        device_id: str,
        device_name: str,
    ) -> int:
        created = 0
        now = utc_now()
        with self.transaction() as connection:
            for target_id in dict.fromkeys(target_ids):
                target = connection.execute(
                    "SELECT id FROM records WHERE id = ? AND kind = 'clip'", (target_id,)
                ).fetchone()
                existing = connection.execute(
                    "SELECT id FROM records WHERE kind = 'tombstone' AND target_id = ? LIMIT 1",
                    (target_id,),
                ).fetchone()
                if not target or existing:
                    continue
                record = Record(
                    id=uuid7(),
                    kind=RecordKind.TOMBSTONE,
                    captured_at=now,
                    device_id=device_id,
                    device_name=device_name,
                    sequence=self._next_sequence(connection),
                    target_id=target_id,
                )
                self._insert_record(
                    connection,
                    record,
                    origin="local",
                    sync_state=SyncState.PENDING,
                    remote_file_id=None,
                )
                connection.execute(
                    "UPDATE records SET deleted_at = COALESCE(deleted_at, ?) WHERE id = ?",
                    (format_utc(now), target_id),
                )
                created += 1
        return created

    def clear_everywhere(self, *, device_id: str, device_name: str) -> int:
        ids = [item.record.id for item in self.list_history(limit=None)]
        return self.create_tombstones(ids, device_id=device_id, device_name=device_name)

    def clear_local(self) -> int:
        now = format_utc(utc_now())
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE records SET deleted_at = ? WHERE kind = 'clip' AND deleted_at IS NULL",
                (now,),
            )
            return cursor.rowcount

    def import_remote(self, record: Record, remote_file_id: str) -> bool:
        with self.transaction() as connection:
            exists = connection.execute("SELECT 1 FROM records WHERE id = ?", (record.id,)).fetchone()
            if exists:
                connection.execute(
                    """
                    UPDATE records
                    SET remote_file_id = COALESCE(remote_file_id, ?),
                        sync_state = CASE WHEN origin = 'local' THEN 'synced' ELSE sync_state END
                    WHERE id = ?
                    """,
                    (remote_file_id, record.id),
                )
                self._mark_seen_in(connection, remote_file_id, record.id)
                return False

            deleted_at: datetime | None = None
            if record.kind is RecordKind.CLIP:
                tombstone = connection.execute(
                    "SELECT 1 FROM records WHERE kind = 'tombstone' AND target_id = ? LIMIT 1",
                    (record.id,),
                ).fetchone()
                if tombstone:
                    deleted_at = utc_now()
            self._insert_record(
                connection,
                record,
                origin="remote",
                sync_state=SyncState.REMOTE,
                remote_file_id=remote_file_id,
                deleted_at=deleted_at,
            )
            if record.kind is RecordKind.TOMBSTONE:
                connection.execute(
                    "UPDATE records SET deleted_at = COALESCE(deleted_at, ?) WHERE id = ?",
                    (format_utc(utc_now()), record.target_id),
                )
            self._mark_seen_in(connection, remote_file_id, record.id)
            return True

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        record: Record,
        *,
        origin: str,
        sync_state: SyncState,
        remote_file_id: str | None,
        deleted_at: datetime | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO records(
                id, kind, text, target_id, captured_at, device_id, device_name,
                sequence, content_hash, origin, sync_state, remote_file_id,
                deleted_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.kind.value,
                record.text,
                record.target_id,
                format_utc(record.captured_at),
                record.device_id,
                record.device_name,
                record.sequence,
                record.content_hash,
                origin,
                sync_state.value,
                remote_file_id,
                format_utc(deleted_at) if deleted_at else None,
                format_utc(utc_now()),
            ),
        )

    def list_history(self, limit: int | None = 120) -> list[StoredRecord]:
        sql = """
            SELECT * FROM records
            WHERE kind = 'clip' AND deleted_at IS NULL
            ORDER BY captured_at DESC, device_id, sequence DESC, id
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (limit,)
        with self._connect() as connection:
            return [self._stored_from_row(row) for row in connection.execute(sql, parameters)]

    def get(self, record_id: str, *, include_deleted: bool = False) -> StoredRecord | None:
        sql = "SELECT * FROM records WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        with self._connect() as connection:
            row = connection.execute(sql, (record_id,)).fetchone()
        return self._stored_from_row(row) if row else None

    def resolve(self, record_id_or_prefix: str) -> StoredRecord | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM records
                WHERE id LIKE ? AND kind = 'clip' AND deleted_at IS NULL
                ORDER BY captured_at DESC LIMIT 2
                """,
                (record_id_or_prefix + "%",),
            ).fetchall()
        if len(rows) > 1:
            raise ValueError("item id prefix is ambiguous")
        return self._stored_from_row(rows[0]) if rows else None

    def pending_records(self) -> list[StoredRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM records WHERE sync_state = 'pending'
                ORDER BY captured_at, device_id, sequence, id
                """
            ).fetchall()
        return [self._stored_from_row(row) for row in rows]

    def mark_uploaded(self, record_id: str, remote_file_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE records SET sync_state = 'synced', remote_file_id = ?
                WHERE id = ? AND sync_state = 'pending'
                """,
                (remote_file_id, record_id),
            )
            self._mark_seen_in(connection, remote_file_id, record_id)

    def mark_seen(self, remote_file_id: str, record_id: str | None = None) -> None:
        with self.transaction() as connection:
            self._mark_seen_in(connection, remote_file_id, record_id)

    @staticmethod
    def _mark_seen_in(
        connection: sqlite3.Connection, remote_file_id: str, record_id: str | None
    ) -> None:
        connection.execute(
            """
            INSERT INTO seen_remote(remote_file_id, record_id, seen_at) VALUES(?, ?, ?)
            ON CONFLICT(remote_file_id) DO UPDATE SET
                record_id = COALESCE(excluded.record_id, seen_remote.record_id),
                seen_at = excluded.seen_at
            """,
            (remote_file_id, record_id, format_utc(utc_now())),
        )

    def seen_remote_ids(self) -> set[str]:
        with self._connect() as connection:
            return {str(row[0]) for row in connection.execute("SELECT remote_file_id FROM seen_remote")}

    def enforce_retention(self, limit: int) -> int:
        with self.transaction() as connection:
            return self._prune(connection, limit)

    @staticmethod
    def _prune(connection: sqlite3.Connection, limit: int) -> int:
        rows = connection.execute(
            """
            SELECT id FROM records
            WHERE kind = 'clip' AND deleted_at IS NULL
            ORDER BY captured_at DESC, device_id, sequence DESC, id
            LIMIT -1 OFFSET ?
            """,
            (limit,),
        ).fetchall()
        if not rows:
            return 0
        now = format_utc(utc_now())
        connection.executemany(
            "UPDATE records SET deleted_at = ? WHERE id = ?",
            [(now, row[0]) for row in rows],
        )
        return len(rows)

    def get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def delete_meta(self, key: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM meta WHERE key = ?", (key,))

    def record_sync_error(self, code: str, message: str) -> None:
        safe = sanitize_diagnostic(message)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO sync_errors(occurred_at, code, message) VALUES (?, ?, ?)",
                (format_utc(utc_now()), code[:50], safe),
            )
            connection.execute(
                """
                DELETE FROM sync_errors WHERE id NOT IN (
                    SELECT id FROM sync_errors ORDER BY id DESC LIMIT 50
                )
                """
            )

    def recent_errors(self, limit: int = 5) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT occurred_at, code, message FROM sync_errors ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  SUM(CASE WHEN kind = 'clip' AND deleted_at IS NULL THEN 1 ELSE 0 END) active,
                  SUM(CASE WHEN sync_state = 'pending' THEN 1 ELSE 0 END) pending,
                  SUM(CASE WHEN kind = 'tombstone' THEN 1 ELSE 0 END) tombstones,
                  COUNT(*) total
                FROM records
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("active", "pending", "tombstones", "total")}

    def export_json(self) -> str:
        payload = {
            "schema": "retropyclip.export/1",
            "exported_at": format_utc(utc_now()),
            "clips": [item.record.to_payload() for item in reversed(self.list_history(limit=None))],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _stored_from_row(row: sqlite3.Row) -> StoredRecord:
        kind = RecordKind(str(row["kind"]))
        record = Record(
            id=str(row["id"]),
            kind=kind,
            captured_at=parse_utc(str(row["captured_at"])),
            device_id=str(row["device_id"]),
            device_name=str(row["device_name"]),
            sequence=int(row["sequence"]),
            text=str(row["text"]) if kind is RecordKind.CLIP else None,
            target_id=str(row["target_id"]) if kind is RecordKind.TOMBSTONE else None,
            content_hash=str(row["content_hash"]) if row["content_hash"] else None,
        )
        deleted_at = parse_utc(str(row["deleted_at"])) if row["deleted_at"] else None
        return StoredRecord(
            record=record,
            sync_state=SyncState(str(row["sync_state"])),
            origin=str(row["origin"]),
            remote_file_id=str(row["remote_file_id"]) if row["remote_file_id"] else None,
            deleted_at=deleted_at,
        )
