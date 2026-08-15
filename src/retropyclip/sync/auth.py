from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import keyring
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from keyring.errors import KeyringError

from retropyclip.config import AppPaths
from retropyclip.sync.backend import AuthenticationRequired, TransientBackendError

SCOPES = ["https://www.googleapis.com/auth/drive.appdata"]
KEYRING_SERVICE = "RetroPyClip"
KEYRING_ACCOUNT = "google-oauth"
DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class CredentialStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def save(self, credentials: Credentials) -> None:
        raw = credentials.to_json()
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, raw)
            if self.paths.token_file.exists():
                self.paths.token_file.unlink()
            return
        except KeyringError:
            pass
        self.paths.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.paths.token_file.with_suffix(".tmp")
        temporary.write_text(raw, "utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.paths.token_file)

    def load(self, *, refresh: bool = True) -> Credentials | None:
        raw: str | None = None
        with suppress(KeyringError):
            raw = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if raw is None and self.paths.token_file.exists():
            raw = self.paths.token_file.read_text("utf-8")
        if raw is None:
            return None
        try:
            credentials = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise AuthenticationRequired("stored Google credentials are invalid; log in again") from error
        if refresh and not credentials.valid:
            if not credentials.refresh_token:
                raise AuthenticationRequired("Google login has expired; log in again")
            try:
                credentials.refresh(Request())
            except RefreshError as error:
                raise AuthenticationRequired("Google login has expired; log in again") from error
            except OSError as error:
                raise TransientBackendError("network unavailable while refreshing Google login") from error
            self.save(credentials)
        return credentials

    def delete(self) -> None:
        with suppress(KeyringError, keyring.errors.PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if self.paths.token_file.exists():
            self.paths.token_file.unlink()

    def present(self) -> bool:
        try:
            return self.load(refresh=False) is not None
        except AuthenticationRequired:
            return True


def install_client_secrets(source: Path, paths: AppPaths) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"OAuth client file does not exist: {source}")
    try:
        payload = json.loads(source.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("OAuth client file is not valid JSON") from error
    if not isinstance(payload, dict) or not ({"installed", "web"} & set(payload)):
        raise ValueError("OAuth client file must contain an installed or web client")
    paths.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if source != paths.client_secrets_file:
        shutil.copyfile(source, paths.client_secrets_file)
    os.chmod(paths.client_secrets_file, 0o600)
    return paths.client_secrets_file


def login_browser(client_file: Path, store: CredentialStore) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=SCOPES)
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        authorization_prompt_message="Opening Google authorization in your browser…",
        success_message="RetroPyClip is connected. You may close this tab.",
        access_type="offline",
        prompt="consent",
    )
    store.save(credentials)
    return credentials


def login_device(
    client_file: Path,
    store: CredentialStore,
    *,
    display: Callable[[str, str], None],
    sleeper: Callable[[float], None] = time.sleep,
) -> Credentials:
    payload = json.loads(client_file.read_text("utf-8"))
    client: dict[str, Any] = payload.get("installed") or payload.get("web") or {}
    client_id = str(client.get("client_id", ""))
    client_secret = str(client.get("client_secret", ""))
    if not client_id:
        raise ValueError("OAuth client file has no client_id")
    response = _post_form(DEVICE_AUTH_URL, {"client_id": client_id, "scope": " ".join(SCOPES)})
    required = {"device_code", "user_code", "verification_url", "expires_in"}
    if not required.issubset(response):
        raise AuthenticationRequired("Google did not accept this client for device authorization")
    display(str(response["verification_url"]), str(response["user_code"]))
    interval = max(1, int(response.get("interval", 5)))
    deadline = time.monotonic() + int(response["expires_in"])
    while time.monotonic() < deadline:
        sleeper(interval)
        token = _post_form(
            TOKEN_URL,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": str(response["device_code"]),
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            allow_oauth_error=True,
        )
        error = token.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise AuthenticationRequired(f"Google device authorization failed: {error}")
        credentials = Credentials(
            token=str(token["access_token"]),
            refresh_token=str(token.get("refresh_token") or ""),
            token_uri=TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
            expiry=datetime.now(UTC) + timedelta(seconds=int(token.get("expires_in", 3600))),
        )
        if not credentials.refresh_token:
            raise AuthenticationRequired("Google did not issue an offline refresh token")
        store.save(credentials)
        return credentials
    raise AuthenticationRequired("Google device authorization expired before approval")


def _post_form(url: str, values: dict[str, str], *, allow_oauth_error: bool = False) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if allow_oauth_error:
            try:
                result = json.loads(error.read())
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        raise AuthenticationRequired(f"Google authorization request failed ({error.code})") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise TransientBackendError("network unavailable during Google authorization") from error
