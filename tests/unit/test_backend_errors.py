from __future__ import annotations

from types import SimpleNamespace

from retropyclip.sync.backend import (
    AuthenticationRequired,
    QuotaExceeded,
    TransientBackendError,
    _translate_http_error,
)


def _http_error(status: int, body: bytes | None = None) -> SimpleNamespace:
    error = SimpleNamespace(resp=SimpleNamespace(status=status), content=body)
    return error  # type: ignore[return-value]


def test_quota_reason_is_terminal_not_auth_failure() -> None:
    body = b'{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}'
    translated = _translate_http_error(_http_error(403, body))  # type: ignore[arg-type]
    assert isinstance(translated, QuotaExceeded)


def test_revoked_oauth_is_authentication_required() -> None:
    translated = _translate_http_error(_http_error(401))  # type: ignore[arg-type]
    assert isinstance(translated, AuthenticationRequired)


def test_server_error_is_transient() -> None:
    translated = _translate_http_error(_http_error(503))  # type: ignore[arg-type]
    assert isinstance(translated, TransientBackendError)
