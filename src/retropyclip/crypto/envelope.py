from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, replace
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from retropyclip.core.models import Record, RecordKind
from retropyclip.core.text import local_content_hash

ENVELOPE_SCHEMA = "retropyclip.record/1"
KEYINFO_SCHEMA = "retropyclip.keyinfo/1"
KEYINFO_FILENAME = "retropyclip.keyinfo.v1.json"
MIN_PASSPHRASE_LENGTH = 12
VERIFIER_CONTEXT = b"retropyclip key verifier/1"
HASH_CONTEXT = b"retropyclip content hash/1\x00"


class CryptoError(ValueError):
    pass


class InvalidPassphrase(CryptoError):
    pass


class InvalidEnvelope(CryptoError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: Any, *, label: str) -> bytes:
    if not isinstance(value, str):
        raise InvalidEnvelope(f"{label} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise InvalidEnvelope(f"invalid {label} encoding") from error


@dataclass(frozen=True, slots=True)
class KDFParameters:
    time_cost: int = 3
    memory_cost_kib: int = 65_536
    parallelism: int = 2

    def validate(self) -> None:
        if not 1 <= self.time_cost <= 10:
            raise CryptoError("Argon2 time cost is outside the supported range")
        if not 8 * self.parallelism <= self.memory_cost_kib <= 1_048_576:
            raise CryptoError("Argon2 memory cost is outside the supported range")
        if not 1 <= self.parallelism <= 16:
            raise CryptoError("Argon2 parallelism is outside the supported range")


@dataclass(frozen=True, slots=True)
class KeyInfo:
    salt: bytes
    parameters: KDFParameters
    verifier: bytes

    @classmethod
    def create(
        cls, passphrase: str, *, parameters: KDFParameters | None = None
    ) -> tuple[KeyInfo, bytes]:
        _validate_passphrase(passphrase)
        selected = parameters or KDFParameters()
        selected.validate()
        salt = os.urandom(16)
        key = derive_key(passphrase, salt, selected)
        verifier = hmac.digest(key, VERIFIER_CONTEXT, "sha256")
        return cls(salt=salt, parameters=selected, verifier=verifier), key

    def derive_and_verify(self, passphrase: str) -> bytes:
        _validate_passphrase(passphrase)
        self.parameters.validate()
        key = derive_key(passphrase, self.salt, self.parameters)
        expected = hmac.digest(key, VERIFIER_CONTEXT, "sha256")
        if not hmac.compare_digest(self.verifier, expected):
            raise InvalidPassphrase("the sync passphrase does not match this history")
        return key

    def to_json(self) -> bytes:
        payload = {
            "schema": KEYINFO_SCHEMA,
            "kdf": "argon2id",
            "salt": _b64encode(self.salt),
            "time_cost": self.parameters.time_cost,
            "memory_cost_kib": self.parameters.memory_cost_kib,
            "parallelism": self.parameters.parallelism,
            "verifier": _b64encode(self.verifier),
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @classmethod
    def from_json(cls, raw: bytes) -> KeyInfo:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CryptoError("invalid key metadata") from error
        if not isinstance(payload, dict) or payload.get("schema") != KEYINFO_SCHEMA:
            raise CryptoError("unsupported key metadata schema")
        if payload.get("kdf") != "argon2id":
            raise CryptoError("unsupported key derivation function")
        allowed = {
            "schema",
            "kdf",
            "salt",
            "time_cost",
            "memory_cost_kib",
            "parallelism",
            "verifier",
        }
        if set(payload) - allowed:
            raise CryptoError("key metadata contains unexpected fields")
        try:
            parameters = KDFParameters(
                time_cost=int(payload["time_cost"]),
                memory_cost_kib=int(payload["memory_cost_kib"]),
                parallelism=int(payload["parallelism"]),
            )
            parameters.validate()
            salt = _b64decode(payload["salt"], label="salt")
            verifier = _b64decode(payload["verifier"], label="verifier")
        except (KeyError, TypeError, ValueError) as error:
            raise CryptoError("malformed key metadata") from error
        if len(salt) < 16 or len(verifier) != 32:
            raise CryptoError("malformed key metadata values")
        return cls(salt=salt, parameters=parameters, verifier=verifier)


def _validate_passphrase(passphrase: str) -> None:
    if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise InvalidPassphrase(
            f"sync passphrase must contain at least {MIN_PASSPHRASE_LENGTH} characters"
        )


def derive_key(passphrase: str, salt: bytes, parameters: KDFParameters) -> bytes:
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=parameters.time_cost,
        memory_cost=parameters.memory_cost_kib,
        parallelism=parameters.parallelism,
        hash_len=32,
        type=Type.ID,
    )


class EnvelopeCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise CryptoError("AES-256-GCM requires a 32-byte key")
        self._key = key
        self._aes = AESGCM(key)

    def encrypt(self, record: Record, *, nonce: bytes | None = None) -> bytes:
        keyed_hash: str | None = None
        if record.kind is RecordKind.CLIP:
            assert record.text is not None
            keyed_hash = hmac.new(
                self._key, HASH_CONTEXT + record.text.encode("utf-8"), hashlib.sha256
            ).hexdigest()
        payload = record.to_payload(content_hash=keyed_hash)
        plaintext = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        selected_nonce = os.urandom(12) if nonce is None else nonce
        if len(selected_nonce) != 12:
            raise CryptoError("AES-GCM nonce must be 12 bytes")
        associated = self._associated_data(record.id, record.kind)
        ciphertext = self._aes.encrypt(selected_nonce, plaintext, associated)
        envelope = {
            "schema": ENVELOPE_SCHEMA,
            "id": record.id,
            "kind": record.kind.value,
            "nonce": _b64encode(selected_nonce),
            "ciphertext": _b64encode(ciphertext),
        }
        return (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def decrypt(self, raw: bytes, *, max_envelope_bytes: int) -> Record:
        if len(raw) > max_envelope_bytes:
            raise InvalidEnvelope("encrypted record exceeds the configured size limit")
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InvalidEnvelope("record is not valid JSON") from error
        if not isinstance(envelope, dict) or envelope.get("schema") != ENVELOPE_SCHEMA:
            raise InvalidEnvelope("unsupported encrypted record schema")
        if set(envelope) != {"schema", "id", "kind", "nonce", "ciphertext"}:
            raise InvalidEnvelope("encrypted record contains unexpected or missing fields")
        try:
            record_id = str(envelope["id"])
            kind = RecordKind(str(envelope["kind"]))
            nonce = _b64decode(envelope["nonce"], label="nonce")
            ciphertext = _b64decode(envelope["ciphertext"], label="ciphertext")
        except (KeyError, ValueError) as error:
            raise InvalidEnvelope("malformed encrypted record") from error
        if len(nonce) != 12 or len(ciphertext) < 16:
            raise InvalidEnvelope("malformed encrypted record values")
        try:
            plaintext = self._aes.decrypt(
                nonce, ciphertext, self._associated_data(record_id, kind)
            )
        except InvalidTag as error:
            raise InvalidEnvelope("record authentication failed") from error
        try:
            payload = json.loads(plaintext)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InvalidEnvelope("decrypted payload is invalid") from error
        if not isinstance(payload, dict):
            raise InvalidEnvelope("decrypted payload must be an object")
        try:
            record = Record.from_payload(payload)
        except ValueError as error:
            raise InvalidEnvelope(str(error)) from error
        if record.id != record_id or record.kind is not kind:
            raise InvalidEnvelope("envelope identity does not match its payload")
        if record.kind is RecordKind.CLIP:
            assert record.text is not None
            expected = hmac.new(
                self._key, HASH_CONTEXT + record.text.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            if record.content_hash is None or not hmac.compare_digest(
                record.content_hash, expected
            ):
                raise InvalidEnvelope("record content hash does not match")
            record = replace(record, content_hash=local_content_hash(record.text))
        return record

    @staticmethod
    def _associated_data(record_id: str, kind: RecordKind) -> bytes:
        return f"{ENVELOPE_SCHEMA}\x00{record_id}\x00{kind.value}".encode("ascii")
