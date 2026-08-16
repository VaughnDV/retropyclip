from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from typing import TypeVar

from retropyclip.core.models import OverallSyncState, SyncReport, format_utc, utc_now
from retropyclip.core.text import InvalidClip, validate_text
from retropyclip.crypto.diagnostics import sanitize_diagnostic
from retropyclip.crypto.envelope import (
    KEYINFO_FILENAME,
    CryptoError,
    EnvelopeCipher,
    KDFParameters,
    KeyInfo,
)
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.backend import (
    AuthenticationRequired,
    QuotaExceeded,
    RemoteBackend,
    RemoteObject,
    TransientBackendError,
)


class SyncDisabled(RuntimeError):
    pass


T = TypeVar("T")


class SyncEngine:
    def __init__(
        self,
        repository: Repository,
        backend: RemoteBackend,
        *,
        max_item_bytes: int,
        history_limit: int,
        local_only: bool = False,
        sync_paused: bool = False,
        attempts: int = 4,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        kdf_parameters: KDFParameters | None = None,
    ) -> None:
        self.repository = repository
        self.backend = backend
        self.max_item_bytes = max_item_bytes
        self.history_limit = history_limit
        self.local_only = local_only
        self.sync_paused = sync_paused
        self.attempts = attempts
        self.sleeper = sleeper
        self.jitter = jitter
        self.kdf_parameters = kdf_parameters

    def sync(self, passphrase: str) -> SyncReport:
        self._check_enabled()
        self._set_state(OverallSyncState.SYNCING)
        try:
            cipher, objects = self._prepare_cipher(passphrase)
            report = self._pull_with(cipher, objects)
            # Refresh the listing before push so two first-time devices are more likely
            # to detect conflicting key metadata before any encrypted clip is uploaded.
            objects = self._retry(self.backend.list_objects)
            self._verify_remote_keyinfo(objects)
            report = report.merged(self._push_with(cipher, objects))
            self.repository.enforce_retention(self.history_limit)
            self._set_state(OverallSyncState.UP_TO_DATE, report)
            return report
        except AuthenticationRequired:
            self._set_state(OverallSyncState.AUTH_REQUIRED)
            raise
        except TransientBackendError:
            self._set_state(OverallSyncState.OFFLINE)
            raise
        except QuotaExceeded as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise
        except Exception as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise

    def pull(self, passphrase: str) -> SyncReport:
        self._check_enabled()
        self._set_state(OverallSyncState.SYNCING)
        try:
            cipher, objects = self._prepare_cipher(passphrase)
            report = self._pull_with(cipher, objects)
            self.repository.enforce_retention(self.history_limit)
            self._set_state(OverallSyncState.UP_TO_DATE, report)
            return report
        except AuthenticationRequired:
            self._set_state(OverallSyncState.AUTH_REQUIRED)
            raise
        except TransientBackendError:
            self._set_state(OverallSyncState.OFFLINE)
            raise
        except QuotaExceeded as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise
        except Exception as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise

    def push(self, passphrase: str) -> SyncReport:
        self._check_enabled()
        self._set_state(OverallSyncState.SYNCING)
        try:
            cipher, objects = self._prepare_cipher(passphrase)
            report = self._push_with(cipher, objects)
            self._set_state(OverallSyncState.UP_TO_DATE, report)
            return report
        except AuthenticationRequired:
            self._set_state(OverallSyncState.AUTH_REQUIRED)
            raise
        except TransientBackendError:
            self._set_state(OverallSyncState.OFFLINE)
            raise
        except QuotaExceeded as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise
        except Exception as error:
            self._record_error(error)
            self._set_state(OverallSyncState.ERROR)
            raise

    def _prepare_cipher(self, passphrase: str) -> tuple[EnvelopeCipher, list[RemoteObject]]:
        objects = self._retry(self.backend.list_objects)
        key_objects = self._key_objects(objects)
        local_raw_text = self.repository.get_meta("keyinfo")
        local_raw = local_raw_text.encode() if local_raw_text else None

        if key_objects:
            remote_raw = self._read_remote_keyinfo(key_objects)
            remote_info = KeyInfo.from_json(remote_raw)
            key = remote_info.derive_and_verify(passphrase)
            if local_raw != remote_raw:
                # Local clips are plaintext until upload, so adopting an established
                # single remote KDF configuration is safe.
                self.repository.set_meta("keyinfo", remote_raw.decode())
            return EnvelopeCipher(key), objects

        if local_raw:
            info = KeyInfo.from_json(local_raw)
            key = info.derive_and_verify(passphrase)
            upload_keyinfo = local_raw
            self._retry(lambda: self.backend.upload(KEYINFO_FILENAME, upload_keyinfo))
        else:
            info, key = KeyInfo.create(passphrase, parameters=self.kdf_parameters)
            local_raw = info.to_json()
            self.repository.set_meta("keyinfo", local_raw.decode())
            self._retry(lambda: self.backend.upload(KEYINFO_FILENAME, local_raw))

        refreshed = self._retry(self.backend.list_objects)
        remote_raw = self._verify_remote_keyinfo(refreshed)
        if remote_raw != local_raw:
            raise CryptoError("remote sync key configuration changed during initial setup")
        return EnvelopeCipher(key), refreshed

    @staticmethod
    def _key_objects(objects: list[RemoteObject]) -> list[RemoteObject]:
        return sorted(
            [item for item in objects if item.name == KEYINFO_FILENAME],
            key=lambda item: (item.created_time or "", item.id),
        )

    def _read_remote_keyinfo(self, key_objects: list[RemoteObject]) -> bytes:
        values: list[bytes] = []
        for item in key_objects:
            def download(remote_id: str = item.id) -> bytes:
                return self.backend.download(remote_id)

            values.append(self._retry(download))
        if not values:
            raise CryptoError("remote sync key configuration is missing")
        if any(value != values[0] for value in values[1:]):
            raise CryptoError(
                "multiple sync key configurations exist; do not upload more clips and resolve the initial-device race"
            )
        return values[0]

    def _verify_remote_keyinfo(self, objects: list[RemoteObject]) -> bytes:
        remote_raw = self._read_remote_keyinfo(self._key_objects(objects))
        local_raw = self.repository.get_meta("keyinfo")
        if local_raw is not None and remote_raw != local_raw.encode():
            raise CryptoError("remote sync key configuration does not match this device")
        return remote_raw

    def _pull_with(self, cipher: EnvelopeCipher, objects: list[RemoteObject]) -> SyncReport:
        seen = self.repository.seen_remote_ids()
        pulled = skipped = 0
        errors: list[str] = []
        record_objects = sorted(
            [item for item in objects if item.name.endswith(".rpc.json")],
            key=lambda item: (item.created_time or "", item.name, item.id),
        )
        maximum = self.max_item_bytes * 2 + 8192
        for item in record_objects:
            if item.id in seen:
                skipped += 1
                continue
            if item.size is not None and item.size > maximum:
                message = sanitize_diagnostic(
                    f"remote object {item.id} exceeds the encrypted size limit"
                )
                self.repository.record_sync_error("OversizedRemoteRecord", message)
                self.repository.mark_seen(item.id)
                errors.append(message)
                continue
            try:
                def download(remote_id: str = item.id) -> bytes:
                    return self.backend.download(remote_id)

                raw = self._retry(download)
                record = cipher.decrypt(raw, max_envelope_bytes=maximum)
                if record.text is not None:
                    validate_text(record.text, self.max_item_bytes)
                if self.repository.import_remote(record, item.id):
                    pulled += 1
                else:
                    skipped += 1
            except (CryptoError, InvalidClip) as error:
                message = sanitize_diagnostic(
                    f"remote object {item.id} was rejected: {error}"
                )
                self.repository.record_sync_error(type(error).__name__, message)
                self.repository.mark_seen(item.id)
                errors.append(message)
        return SyncReport(pulled=pulled, skipped=skipped, errors=tuple(errors))

    def _push_with(self, cipher: EnvelopeCipher, objects: list[RemoteObject]) -> SyncReport:
        names = {item.name: item for item in objects}
        pushed = skipped = 0
        for item in self.repository.pending_records():
            name = f"{item.record.id}.rpc.json"
            existing = names.get(name)
            if existing:
                self.repository.mark_uploaded(item.record.id, existing.id)
                skipped += 1
                continue
            encrypted = cipher.encrypt(item.record)

            def upload(upload_name: str = name, upload_data: bytes = encrypted) -> str:
                return self.backend.upload(upload_name, upload_data)

            remote_file_id = self._retry(upload)
            self.repository.mark_uploaded(item.record.id, remote_file_id)
            names[name] = RemoteObject(id=remote_file_id, name=name, size=len(encrypted))
            pushed += 1
        return SyncReport(pushed=pushed, skipped=skipped)

    def _retry(self, operation: Callable[[], T]) -> T:
        delay = 0.25
        for attempt in range(self.attempts):
            try:
                return operation()
            except TransientBackendError:
                if attempt + 1 >= self.attempts:
                    raise
                spread = 0.5 + self.jitter()
                self.sleeper(delay * spread)
                delay = min(delay * 2, 4.0)
        raise AssertionError("retry loop did not return")

    def _record_error(self, error: BaseException) -> None:
        self.repository.record_sync_error(
            type(error).__name__, sanitize_diagnostic(str(error))
        )

    def _check_enabled(self) -> None:
        if self.local_only:
            raise SyncDisabled("sync is disabled while local-only mode is enabled")
        if self.sync_paused:
            raise SyncDisabled("sync is paused")

    def _set_state(self, state: OverallSyncState, report: SyncReport | None = None) -> None:
        payload: dict[str, object] = {"state": state.value, "updated_at": format_utc(utc_now())}
        if report is not None:
            payload["pulled"] = report.pulled
            payload["pushed"] = report.pushed
            payload["skipped"] = report.skipped
            payload["error_count"] = len(report.errors)
        self.repository.set_meta("sync_status", json.dumps(payload, sort_keys=True))
