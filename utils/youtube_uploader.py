from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from utils.logger import setup_logger

logger = setup_logger("YouTubeUploader")

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_RETRIES = 5
VALID_PRIVACY_STATUSES = {"public", "private", "unlisted"}


class YouTubeUploadError(Exception):
    pass


@dataclass
class YouTubeUploadResult:
    aweme_id: str
    status: str
    video_id: Optional[str] = None
    error_message: Optional[str] = None
    dry_run: bool = False
    file_path: Optional[str] = None
    title: Optional[str] = None


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


class YouTubeAuthManager:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings or {}
        self.client_secret_path = Path(
            str(
                self.settings.get("client_secret_path")
                or "config/youtube_client_secret.json"
            )
        )
        self.token_path = Path(
            str(self.settings.get("token_path") or "config/youtube_token.json")
        )

    def run_authorization(self) -> Dict[str, Any]:
        flow_cls, _credentials_cls, _request_cls = _load_google_auth_dependencies()
        if not self.client_secret_path.exists():
            raise YouTubeUploadError(
                f"YouTube client secret not found: {self.client_secret_path}"
            )
        flow = flow_cls.from_client_secrets_file(
            str(self.client_secret_path), [YOUTUBE_UPLOAD_SCOPE]
        )
        credentials = flow.run_local_server(port=0)
        self.save_credentials(credentials)
        return json.loads(credentials.to_json())

    def load_credentials(self) -> Any:
        _flow_cls, credentials_cls, request_cls = _load_google_auth_dependencies()
        if not self.token_path.exists():
            raise YouTubeUploadError(
                "YouTube token not found. Run douyin-dl --youtube-auth first."
            )
        credentials = credentials_cls.from_authorized_user_file(
            str(self.token_path), [YOUTUBE_UPLOAD_SCOPE]
        )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(request_cls())
            self.save_credentials(credentials)
        if not credentials or not credentials.valid:
            raise YouTubeUploadError(
                "YouTube credentials are invalid. Run douyin-dl --youtube-auth again."
            )
        return credentials

    def save_credentials(self, credentials: Any) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")


class YouTubeUploader:
    def __init__(self, settings: Dict[str, Any], database: Any = None):
        self.settings = settings or {}
        self.database = database
        self.enabled = _as_bool(self.settings.get("enabled"), default=False)
        self.auto_after_download = _as_bool(
            self.settings.get("auto_after_download"), default=False
        )
        self.dry_run = _as_bool(self.settings.get("dry_run"), default=False)
        self.auth = YouTubeAuthManager(self.settings)

    async def upload_manifest_record(
        self,
        base_path: Path,
        record: Dict[str, Any],
        *,
        force: bool = False,
    ) -> YouTubeUploadResult:
        aweme_id = str(record.get("aweme_id") or "")
        if not aweme_id:
            return YouTubeUploadResult(
                aweme_id="", status="skipped", error_message="missing aweme_id"
            )
        if not (self.enabled or force):
            return YouTubeUploadResult(aweme_id=aweme_id, status="skipped")
        if self.database and await self.database.is_youtube_uploaded(aweme_id):
            return YouTubeUploadResult(aweme_id=aweme_id, status="skipped")

        video_path = self.select_video_path(base_path, record)
        if video_path is None:
            return YouTubeUploadResult(
                aweme_id=aweme_id,
                status="skipped",
                error_message="no uploadable mp4 video",
            )

        metadata = self.build_metadata(record)
        if self.dry_run:
            logger.info(
                "YouTube dry-run: aweme_id=%s file=%s title=%r privacy=%s",
                aweme_id,
                video_path,
                metadata["title"],
                metadata["privacy_status"],
            )
            result = YouTubeUploadResult(
                aweme_id=aweme_id,
                status="dry_run",
                dry_run=True,
                file_path=str(video_path),
                title=metadata["title"],
            )
            await self._record_result(result)
            return result

        try:
            video_id = await self._upload_video_async(video_path, metadata)
        except Exception as exc:
            message = str(exc)
            logger.warning("YouTube upload failed for %s: %s", aweme_id, message)
            result = YouTubeUploadResult(
                aweme_id=aweme_id,
                status="failure",
                error_message=message,
                file_path=str(video_path),
                title=metadata["title"],
            )
            await self._record_result(result)
            return result

        result = YouTubeUploadResult(
            aweme_id=aweme_id,
            status="success",
            video_id=video_id,
            file_path=str(video_path),
            title=metadata["title"],
        )
        await self._record_result(result)
        return result

    def select_video_path(self, base_path: Path, record: Dict[str, Any]) -> Optional[Path]:
        if str(record.get("media_type") or "") != "video":
            return None
        file_paths = record.get("file_paths") or []
        for raw_path in file_paths:
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = base_path / path
            if path.exists() and _is_primary_mp4(path):
                return path
        return None

    def build_metadata(self, record: Dict[str, Any]) -> Dict[str, Any]:
        values = _SafeFormatDict(
            {
                "desc": str(record.get("desc") or ""),
                "author_name": str(record.get("author_name") or ""),
                "aweme_id": str(record.get("aweme_id") or ""),
                "date": str(record.get("date") or ""),
            }
        )
        title_template = str(self.settings.get("title_template") or "{desc}")
        description_template = str(
            self.settings.get("description_template")
            or "{desc}\n\nAuthor: {author_name}\nAweme ID: {aweme_id}"
        )
        title = title_template.format_map(values).strip() or values["aweme_id"]
        description = description_template.format_map(values).strip()
        tags = self.settings.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        privacy_status = str(self.settings.get("privacy_status") or "public")
        if privacy_status not in VALID_PRIVACY_STATUSES:
            privacy_status = "public"
        return {
            "title": _truncate_title(title),
            "description": description,
            "tags": [str(tag) for tag in tags],
            "category_id": str(self.settings.get("category_id") or "22"),
            "privacy_status": privacy_status,
        }

    async def _upload_video_async(self, video_path: Path, metadata: Dict[str, Any]) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._upload_video_sync(video_path, metadata)
        )

    def _upload_video_sync(self, video_path: Path, metadata: Dict[str, Any]) -> str:
        _flow_cls, _credentials_cls, _request_cls = _load_google_auth_dependencies()
        build_func, media_upload_cls, http_error_cls = _load_google_api_dependencies()
        credentials = self.auth.load_credentials()
        youtube = build_func("youtube", "v3", credentials=credentials)
        body = {
            "snippet": {
                "title": metadata["title"],
                "description": metadata["description"],
                "tags": metadata["tags"],
                "categoryId": metadata["category_id"],
            },
            "status": {
                "privacyStatus": metadata["privacy_status"],
                "selfDeclaredMadeForKids": False,
            },
        }
        media = media_upload_cls(str(video_path), chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        return _resumable_upload(request, http_error_cls)

    async def _record_result(self, result: YouTubeUploadResult) -> None:
        if not self.database:
            return
        await self.database.upsert_youtube_upload_history(
            {
                "aweme_id": result.aweme_id,
                "video_id": result.video_id,
                "status": result.status,
                "error_message": result.error_message,
            }
        )


def run_youtube_auth(settings: Dict[str, Any]) -> Dict[str, Any]:
    return YouTubeAuthManager(settings).run_authorization()


async def publish_latest_from_manifest(
    settings: Dict[str, Any],
    base_path: Path,
    limit: int,
    database: Any = None,
) -> List[YouTubeUploadResult]:
    records = await _read_latest_manifest_records(base_path, limit)
    uploader = YouTubeUploader({**settings, "enabled": True}, database=database)
    results = []
    max_items = int(settings.get("max_items_per_run") or 0)
    for record in records:
        if max_items and len(results) >= max_items:
            break
        results.append(await uploader.upload_manifest_record(base_path, record, force=True))
    return results


def build_youtube_uploader(
    config_source: Any, database: Any = None
) -> Optional[YouTubeUploader]:
    cfg = youtube_settings(config_source)
    if not isinstance(cfg, dict):
        return None
    uploader = YouTubeUploader(cfg, database=database)
    if not uploader.enabled and not uploader.auto_after_download:
        return None
    return uploader


def youtube_settings(config_source: Any) -> Dict[str, Any]:
    if hasattr(config_source, "get"):
        cfg = config_source.get("youtube_upload", {}) or {}
    elif isinstance(config_source, dict):
        cfg = config_source.get("youtube_upload", {}) or {}
    else:
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


async def _read_latest_manifest_records(
    base_path: Path, limit: int
) -> List[Dict[str, Any]]:
    manifest_path = base_path / "download_manifest.jsonl"
    if not manifest_path.exists():
        raise YouTubeUploadError(f"Manifest not found: {manifest_path}")
    async with aiofiles.open(manifest_path, "r", encoding="utf-8") as file_obj:
        content = await file_obj.read()

    records = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid manifest line: %s", line[:80])
            continue
        if isinstance(record, dict):
            records.append(record)
    if limit and limit > 0:
        return records[-limit:]
    return records


def _resumable_upload(request: Any, http_error_cls: Any) -> str:
    response = None
    retry = 0
    while response is None:
        try:
            _status, response = request.next_chunk()
            if response and response.get("id"):
                return str(response["id"])
        except http_error_cls as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status not in RETRIABLE_STATUS_CODES:
                raise
            retry += 1
            if retry > MAX_RETRIES:
                raise YouTubeUploadError("YouTube upload retries exhausted") from exc
            time.sleep(random.random() * (2 ** retry))
    raise YouTubeUploadError(f"YouTube upload returned unexpected response: {response}")


def _load_google_auth_dependencies():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise YouTubeUploadError(
            "YouTube upload dependencies are missing. Install with: "
            'pip install -e ".[youtube]"'
        ) from exc
    return InstalledAppFlow, Credentials, Request


def _load_google_api_dependencies():
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise YouTubeUploadError(
            "YouTube upload dependencies are missing. Install with: "
            'pip install -e ".[youtube]"'
        ) from exc
    return build, MediaFileUpload, HttpError


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _is_primary_mp4(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(("_data.json", "_comments.json")):
        return False
    if "_cover" in name or "_avatar" in name or "_music" in name:
        return False
    return path.suffix.lower() == ".mp4"


def _truncate_title(title: str) -> str:
    title = " ".join(title.split())
    if len(title) <= 100:
        return title
    return title[:97].rstrip() + "..."
