from __future__ import annotations

import json
import os
import platform
import socket
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

APP_NAME = "RetroPyClip"
APP_AUTHOR = "RetroPyClip"
MAX_CONFIGURABLE_ITEM_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    settings_file: Path
    database_file: Path
    token_file: Path
    client_secrets_file: Path

    @classmethod
    def discover(cls) -> AppPaths:
        override = os.environ.get("RETROPYCLIP_HOME")
        if override:
            root = Path(override).expanduser().resolve()
            config_dir = root / "config"
            data_dir = root / "data"
            cache_dir = root / "cache"
        else:
            dirs = PlatformDirs(APP_NAME, APP_AUTHOR, roaming=False)
            config_dir = Path(dirs.user_config_dir)
            data_dir = Path(dirs.user_data_dir)
            cache_dir = Path(dirs.user_cache_dir)
        return cls(
            config_dir=config_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
            settings_file=config_dir / "settings.json",
            database_file=data_dir / "history.sqlite3",
            token_file=config_dir / "google-token.json",
            client_secrets_file=config_dir / "google-client.json",
        )

    def ensure(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.cache_dir):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)


@dataclass(slots=True)
class Settings:
    schema: int = 2
    device_id: str = ""
    device_name: str = ""
    history_limit: int = 120
    max_item_bytes: int = 64 * 1024
    capture_paused: bool = False
    pause_until: str | None = None
    sync_paused: bool = False
    local_only: bool = False
    sync_interval_minutes: int = 0
    activate_newest_remote: bool = False
    clipboard_poll_seconds: float = 0.25

    def validate(self) -> None:
        if self.schema != 2:
            raise ValueError("settings use an unsupported schema")
        try:
            uuid.UUID(self.device_id)
        except ValueError as error:
            raise ValueError("settings contain an invalid device id") from error
        if not self.device_name.strip():
            raise ValueError("device name cannot be empty")
        if not 1 <= self.history_limit <= 100_000:
            raise ValueError("history limit must be between 1 and 100000")
        if not 1 <= self.max_item_bytes <= MAX_CONFIGURABLE_ITEM_BYTES:
            raise ValueError(
                f"maximum item size must be between 1 and {MAX_CONFIGURABLE_ITEM_BYTES} bytes"
            )
        if self.sync_interval_minutes < 0:
            raise ValueError("sync interval cannot be negative")
        if not 0.1 <= self.clipboard_poll_seconds <= 60:
            raise ValueError("clipboard polling interval must be between 0.1 and 60 seconds")


class ConfigStore:
    def __init__(self, paths: AppPaths | None = None) -> None:
        self.paths = paths or AppPaths.discover()
        self.paths.ensure()

    def load(self) -> Settings:
        if not self.paths.settings_file.exists():
            settings = self._defaults()
            self.save(settings)
            return settings
        try:
            raw: dict[str, Any] = json.loads(self.paths.settings_file.read_text("utf-8"))
            migrated = False
            if raw.get("schema") == 1:
                raw["schema"] = 2
                if raw.get("clipboard_poll_seconds") == 0.5:
                    raw["clipboard_poll_seconds"] = 0.25
                migrated = True
            settings = Settings(**raw)
            settings.validate()
            if migrated:
                self.save(settings)
            return settings
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError(f"cannot load settings: {error}") from error

    def save(self, settings: Settings) -> None:
        settings.validate()
        self.paths.ensure()
        temporary = self.paths.settings_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", "utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.paths.settings_file)

    @staticmethod
    def _defaults() -> Settings:
        host = socket.gethostname().split(".", maxsplit=1)[0] or platform.node() or "device"
        settings = Settings(device_id=str(uuid.uuid4()), device_name=host)
        settings.validate()
        return settings
