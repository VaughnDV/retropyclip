from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Protocol

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload


class BackendError(RuntimeError):
    pass


class AuthenticationRequired(BackendError):
    pass


class TransientBackendError(BackendError):
    pass


@dataclass(frozen=True, slots=True)
class RemoteObject:
    id: str
    name: str
    size: int | None = None
    created_time: str | None = None


class RemoteBackend(Protocol):
    def list_objects(self) -> list[RemoteObject]: ...

    def download(self, remote_file_id: str) -> bytes: ...

    def upload(self, name: str, data: bytes) -> str: ...


class DriveBackend:
    """Google Drive v3 appDataFolder transport."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_objects(self) -> list[RemoteObject]:
        objects: list[RemoteObject] = []
        page_token: str | None = None
        try:
            while True:
                response = (
                    self._service.files()
                    .list(
                        spaces="appDataFolder",
                        q="trashed = false",
                        fields="nextPageToken,files(id,name,size,createdTime)",
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
                for item in response.get("files", []):
                    objects.append(
                        RemoteObject(
                            id=str(item["id"]),
                            name=str(item["name"]),
                            size=int(item["size"]) if item.get("size") is not None else None,
                            created_time=str(item["createdTime"])
                            if item.get("createdTime")
                            else None,
                        )
                    )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as error:
            raise _translate_http_error(error) from error
        except OSError as error:
            raise TransientBackendError("network unavailable while listing Drive data") from error
        return objects

    def download(self, remote_file_id: str) -> bytes:
        try:
            result = self._service.files().get_media(fileId=remote_file_id).execute()
        except HttpError as error:
            raise _translate_http_error(error) from error
        except OSError as error:
            raise TransientBackendError("network unavailable while downloading Drive data") from error
        if not isinstance(result, bytes):
            raise BackendError("Drive returned a non-binary record")
        return result

    def upload(self, name: str, data: bytes) -> str:
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json", resumable=False)
        try:
            result = (
                self._service.files()
                .create(
                    body={"name": name, "parents": ["appDataFolder"]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
        except HttpError as error:
            raise _translate_http_error(error) from error
        except OSError as error:
            raise TransientBackendError("network unavailable while uploading Drive data") from error
        if not result.get("id"):
            raise BackendError("Drive did not return an uploaded file id")
        return str(result["id"])


def _translate_http_error(error: HttpError) -> BackendError:
    status = int(getattr(error.resp, "status", 0))
    if status in {401, 403}:
        return AuthenticationRequired("Google authorization is missing or no longer valid")
    if status in {408, 409, 429} or 500 <= status <= 599:
        return TransientBackendError(f"temporary Google Drive error ({status})")
    return BackendError(f"Google Drive request failed ({status or 'unknown status'})")


class MemoryBackend:
    """Small immutable backend used by integration tests and local simulations."""

    def __init__(self) -> None:
        self._files: dict[str, tuple[str, bytes]] = {}
        self._counter = 0

    def list_objects(self) -> list[RemoteObject]:
        return [
            RemoteObject(id=file_id, name=name, size=len(data), created_time=file_id)
            for file_id, (name, data) in self._files.items()
        ]

    def download(self, remote_file_id: str) -> bytes:
        try:
            return self._files[remote_file_id][1]
        except KeyError as error:
            raise BackendError("remote test record does not exist") from error

    def upload(self, name: str, data: bytes) -> str:
        self._counter += 1
        file_id = f"memory-{self._counter:08d}"
        self._files[file_id] = (name, bytes(data))
        return file_id
