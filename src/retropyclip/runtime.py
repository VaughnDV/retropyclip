from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from googleapiclient.discovery import build

from retropyclip.config import AppPaths, ConfigStore, Settings
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.auth import CredentialStore
from retropyclip.sync.backend import AuthenticationRequired, DriveBackend
from retropyclip.sync.engine import SyncEngine


@dataclass(slots=True)
class Runtime:
    paths: AppPaths
    config: ConfigStore
    settings: Settings
    repository: Repository
    credentials: CredentialStore

    @classmethod
    def open(cls) -> Runtime:
        paths = AppPaths.discover()
        config = ConfigStore(paths)
        settings = config.load()
        repository = Repository(paths.database_file)
        return cls(
            paths=paths,
            config=config,
            settings=settings,
            repository=repository,
            credentials=CredentialStore(paths),
        )

    def reload_settings(self) -> Settings:
        self.settings = self.config.load()
        return self.settings

    def capture_enabled(self) -> bool:
        settings = self.reload_settings()
        if not settings.capture_paused:
            return True
        if not settings.pause_until:
            return False
        try:
            deadline = datetime.fromisoformat(settings.pause_until.replace("Z", "+00:00"))
        except ValueError:
            return False
        if datetime.now(UTC) < deadline:
            return False
        settings.capture_paused = False
        settings.pause_until = None
        self.config.save(settings)
        return True

    def sync_engine(self) -> SyncEngine:
        credentials = self.credentials.load()
        if credentials is None:
            raise AuthenticationRequired("Google account is not connected; run 'retropyclip login'")
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        settings = self.reload_settings()
        return SyncEngine(
            self.repository,
            DriveBackend(service),
            max_item_bytes=settings.max_item_bytes,
            history_limit=settings.history_limit,
            local_only=settings.local_only,
            sync_paused=settings.sync_paused,
        )

    def sync_status(self) -> dict[str, object] | None:
        raw = self.repository.get_meta("sync_status")
        if raw is None:
            return None
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return result if isinstance(result, dict) else None
