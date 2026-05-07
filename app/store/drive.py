"""Google Drive integration: persist transcripts and structured JSON."""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


@dataclass
class DriveStore:
    """Thin async wrapper over the Drive v3 API."""

    folder_id: str
    sa_json: str
    _service: Any = None
    _subfolders: dict[str, str] | None = None

    @classmethod
    def from_settings(cls) -> DriveStore:
        s = get_settings()
        return cls(folder_id=s.google_drive_folder_id, sa_json=s.google_service_account_json)

    # --- internals (sync, run in a worker thread via asyncio.to_thread) ---

    def _build_service(self) -> Any:
        info = json.loads(self.sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _service_or_build(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _ensure_subfolder(self, name: str) -> str:
        """Find or create a subfolder under self.folder_id; cache its ID."""
        if self._subfolders is None:
            self._subfolders = {}
        if name in self._subfolders:
            return self._subfolders[name]

        svc = self._service_or_build()
        q = (
            f"'{self.folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{name}' and trashed = false"
        )
        res = svc.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
        files = res.get("files", [])
        if files:
            sub_id = files[0]["id"]
        else:
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [self.folder_id],
            }
            created = svc.files().create(body=meta, fields="id").execute()
            sub_id = created["id"]
        self._subfolders[name] = sub_id
        return sub_id

    def _upload(
        self,
        *,
        subfolder: str,
        filename: str,
        mime: str,
        data: bytes,
    ) -> str:
        svc = self._service_or_build()
        parent_id = self._ensure_subfolder(subfolder)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
        meta = {"name": filename, "parents": [parent_id]}
        created = svc.files().create(body=meta, media_body=media, fields="id").execute()
        return created["id"]

    # --- public async API ---

    async def save_transcript(self, short_id: str, text: str) -> str:
        """Upload a UTF-8 plain-text transcript. Returns the Drive file ID."""

        def _do() -> str:
            return self._upload(
                subfolder="text",
                filename=f"{short_id}.txt",
                mime="text/plain; charset=utf-8",
                data=text.encode("utf-8"),
            )

        file_id = await asyncio.to_thread(_do)
        log.info("drive_saved_transcript", short_id=short_id, file_id=file_id)
        return file_id

    async def save_entry_json(self, short_id: str, payload: dict[str, Any]) -> str:
        """Upload the structured JSON payload. Returns the Drive file ID."""

        def _do() -> str:
            return self._upload(
                subfolder="entries",
                filename=f"{short_id}.json",
                mime="application/json",
                data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            )

        file_id = await asyncio.to_thread(_do)
        log.info("drive_saved_entry_json", short_id=short_id, file_id=file_id)
        return file_id
