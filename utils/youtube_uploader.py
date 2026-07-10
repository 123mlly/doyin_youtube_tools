from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiofiles

from utils.logger import setup_logger

logger = setup_logger("YouTubeUploader")

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_RETRIES = 5
VALID_PRIVACY_STATUSES = {"public", "private", "unlisted"}
# YouTube snippet limits (conservative; avoids 400 from oversized tags / description)
YOUTUBE_MAX_TAGS = 30
YOUTUBE_MAX_TAG_LEN = 30
YOUTUBE_MAX_DESCRIPTION_CHARS = 5000
# Resumable upload chunk size (must be a multiple of 256 KiB for googleapiclient)
DEFAULT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
# GUI/log progress callback: emit at most every N percent (plus 100%)
PROGRESS_CALLBACK_STEP_PCT = 5

# 本地指定文件上传（非 manifest）时允许的后缀；manifest 内仍只选主 .mp4
_UPLOADABLE_VIDEO_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".flv", ".m4v", ".avi", ".mpeg", ".mpg"}
)


def _manual_aweme_id_for_path(video_path: Path) -> str:
    """Stable id for DB dedupe when uploading arbitrary files (no manifest aweme_id)."""
    key = str(video_path.resolve()).encode("utf-8", errors="surrogatepass")
    return "manual_" + hashlib.sha256(key).hexdigest()[:24]


def _is_uploadable_video_file(path: Path) -> bool:
    return path.suffix.lower() in _UPLOADABLE_VIDEO_SUFFIXES


def collect_uploadable_videos_in_directory(
    directory: Path | str,
    *,
    recursive: bool = False,
) -> List[Path]:
    """List supported video files under ``directory`` (sorted by path).

    When ``recursive`` is False, only immediate children are scanned.
    """
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise YouTubeUploadError(f"Not a directory: {root}")
    found: List[Path] = []
    if recursive:
        for candidate in root.rglob("*"):
            if candidate.is_file() and _is_uploadable_video_file(candidate):
                found.append(candidate)
    else:
        for candidate in root.iterdir():
            if candidate.is_file() and _is_uploadable_video_file(candidate):
                found.append(candidate)
    found.sort(key=lambda p: str(p).lower())
    return found


def _suppress_google_future_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        module=r"google\.api_core(\.|$)",
    )


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


def youtube_upload_report_events(
    results: List[YouTubeUploadResult],
) -> List[Tuple[str, str]]:
    """(level, message) for CLI / GUI: level is success | warning | info."""
    events: List[Tuple[str, str]] = []
    if not results:
        events.append(("info", "YouTube：无待处理记录。"))
        return events
    success = sum(1 for r in results if r.status == "success")
    dry_run = sum(1 for r in results if r.status == "dry_run")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failure")
    events.append(
        (
            "success",
            f"YouTube 上传完成：成功={success}, 预演={dry_run}, 跳过={skipped}, 失败={failed}",
        )
    )
    if failed:
        buckets: Dict[str, List[str]] = {}
        for r in results:
            if r.status != "failure":
                continue
            detail = (r.error_message or "unknown").strip()
            buckets.setdefault(detail, []).append(r.aweme_id)
        events.append(("warning", "失败明细（按原因分组）："))
        for detail, ids in buckets.items():
            events.append(("warning", f"  ×{len(ids)}  {detail[:420]}"))
            if len(ids) <= 8:
                events.append(("warning", f"    aweme_id: {', '.join(ids)}"))
            else:
                events.append(
                    (
                        "warning",
                        f"    aweme_id: {', '.join(ids[:8])}, …（共 {len(ids)} 条）",
                    )
                )
    if skipped:
        reasons: Dict[str, int] = {}
        no_reason = 0
        for r in results:
            if r.status != "skipped":
                continue
            msg = (r.error_message or "").strip()
            if msg:
                reasons[msg] = reasons.get(msg, 0) + 1
            else:
                no_reason += 1
        if reasons or no_reason:
            parts = ["跳过统计："]
            if no_reason:
                parts.append(f"无原因记录={no_reason}")
            if reasons:
                parts.append(
                    "; ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
                )
            events.append(("info", " ".join(parts)))
    if failed and not success:
        fail_text = " ".join(
            (r.error_message or "") for r in results if r.status == "failure"
        )
        if "quotaExceeded" in fail_text or "youtube.quota" in fail_text:
            events.append(
                (
                    "info",
                    "若出现 quotaExceeded：为当日 YouTube Data API 配额用尽，通常次日恢复；"
                    "详见 https://developers.google.com/youtube/v3/getting-started#quota 。"
                    " CLI 可加 -v 查看详细日志。",
                )
            )
        if "uploadLimitExceeded" in fail_text:
            events.append(
                (
                    "info",
                    "若出现 uploadLimitExceeded：为 YouTube 对频道「可上传视频数量」等产品限制，"
                    "与 Google Cloud 里 Data API 的每日配额不是同一回事；请到 YouTube 工作室检查账号状态、"
                    "是否需手机验证，或等待限制解除后再传。",
                )
            )
    return events


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
    def __init__(
        self,
        settings: Dict[str, Any],
        database: Any = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.settings = settings or {}
        self.database = database
        self.progress_callback = progress_callback
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
        explicit_video: Optional[Path] = None,
    ) -> YouTubeUploadResult:
        record = dict(record)
        video_path: Optional[Path] = None
        if explicit_video is not None:
            try:
                resolved = Path(explicit_video).expanduser().resolve(strict=False)
            except OSError:
                return YouTubeUploadResult(
                    aweme_id="",
                    status="skipped",
                    error_message=f"cannot resolve path: {explicit_video}",
                )
            if not resolved.is_file():
                return YouTubeUploadResult(
                    aweme_id="",
                    status="skipped",
                    error_message=f"video file not found: {resolved}",
                )
            if not _is_uploadable_video_file(resolved):
                return YouTubeUploadResult(
                    aweme_id="",
                    status="skipped",
                    error_message=(
                        f"unsupported video type {resolved.suffix!r} "
                        f"(allowed: {', '.join(sorted(_UPLOADABLE_VIDEO_SUFFIXES))})"
                    ),
                )
            video_path = resolved
            if not str(record.get("desc") or "").strip():
                record["desc"] = resolved.stem
            if not str(record.get("aweme_id") or "").strip():
                record["aweme_id"] = _manual_aweme_id_for_path(resolved)

        aweme_id = str(record.get("aweme_id") or "").strip()
        if not aweme_id:
            return YouTubeUploadResult(
                aweme_id="", status="skipped", error_message="missing aweme_id"
            )
        if not (self.enabled or force):
            return YouTubeUploadResult(
                aweme_id=aweme_id,
                status="skipped",
                error_message="youtube_upload disabled",
            )
        if self.database and await self.database.is_youtube_uploaded(aweme_id):
            return YouTubeUploadResult(
                aweme_id=aweme_id,
                status="skipped",
                error_message="already uploaded (success in database)",
            )

        if video_path is None:
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
            video_id = await self._upload_video_async(
                video_path,
                metadata,
                aweme_id=aweme_id,
            )
        except Exception as exc:
            message = _format_upload_exception(exc)
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
        description = _truncate_description(
            description_template.format_map(values).strip()
        )
        tags = _normalize_youtube_tags(
            self.settings.get("tags"),
            record.get("tags"),
        )
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

    async def _upload_video_async(
        self,
        video_path: Path,
        metadata: Dict[str, Any],
        *,
        aweme_id: str = "",
    ) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_video_sync(video_path, metadata, aweme_id=aweme_id),
        )

    def _upload_video_sync(
        self, video_path: Path, metadata: Dict[str, Any], *, aweme_id: str = ""
    ) -> str:
        _flow_cls, _credentials_cls, _request_cls = _load_google_auth_dependencies()
        build_func, media_upload_cls, http_error_cls = _load_google_api_dependencies()
        credentials = self.auth.load_credentials()
        timeout_sec = _http_timeout_seconds_from_settings(self.settings)
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
        except ImportError as exc:
            raise YouTubeUploadError(
                "YouTube upload dependencies are missing. Install with: "
                'pip install -e ".[youtube]"'
            ) from exc
        http = httplib2.Http(timeout=timeout_sec)
        authed_http = AuthorizedHttp(credentials, http=http)
        youtube = build_func("youtube", "v3", http=authed_http)
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
        chunksize = _upload_chunk_size_from_settings(self.settings)
        media = media_upload_cls(
            str(video_path), chunksize=chunksize, resumable=True
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        try:
            total_bytes = max(int(video_path.stat().st_size), 1)
        except OSError:
            total_bytes = 1
        show_bar = _as_bool(self.settings.get("show_upload_progress"), default=True)
        title_hint = str(metadata.get("title") or video_path.name).strip() or "YouTube"
        if len(title_hint) > 48:
            title_hint = title_hint[:45] + "..."
        return _resumable_upload(
            request,
            http_error_cls,
            total_bytes=total_bytes,
            show_progress=show_bar,
            description=f"YouTube ↑ {title_hint}",
            progress_callback=self.progress_callback,
            progress_label=(aweme_id or title_hint),
        )

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
    _suppress_google_future_warnings()
    return YouTubeAuthManager(settings).run_authorization()


def _dedupe_manifest_batch(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep last manifest line per aweme_id (file order); drops earlier duplicates."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for record in reversed(records):
        aid = str(record.get("aweme_id") or "").strip()
        if aid:
            if aid in seen:
                continue
            seen.add(aid)
        out.append(record)
    out.reverse()
    return out


async def publish_latest_from_manifest(
    settings: Dict[str, Any],
    base_path: Path,
    limit: int,
    database: Any = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[YouTubeUploadResult]:
    _suppress_google_future_warnings()
    records = _dedupe_manifest_batch(
        await _read_latest_manifest_records(base_path, limit)
    )
    uploader = YouTubeUploader(
        {**settings, "enabled": True},
        database=database,
        progress_callback=progress_callback,
    )
    results = []
    max_items = int(settings.get("max_items_per_run") or 0)
    for record in records:
        if max_items and len(results) >= max_items:
            break
        results.append(await uploader.upload_manifest_record(base_path, record, force=True))
    return results


async def publish_paths_to_youtube(
    settings: Dict[str, Any],
    paths: List[Path],
    database: Any = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[YouTubeUploadResult]:
    """Upload local video files (not tied to download_manifest.jsonl)."""
    _suppress_google_future_warnings()
    uploader = YouTubeUploader(
        {**settings, "enabled": True},
        database=database,
        progress_callback=progress_callback,
    )
    results: List[YouTubeUploadResult] = []
    dummy_base = Path(".")
    max_items = int(settings.get("max_items_per_run") or 0)
    for raw in paths:
        if max_items and len(results) >= max_items:
            break
        rec: Dict[str, Any] = {
            "aweme_id": "",
            "media_type": "video",
            "desc": "",
            "author_name": "",
            "date": "",
            "file_paths": [],
        }
        results.append(
            await uploader.upload_manifest_record(
                dummy_base, rec, force=True, explicit_video=Path(raw)
            )
        )
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


def _upload_progress_bytes(chunk_status: Any, total_bytes: int) -> int:
    """Bytes uploaded so far from googleapiclient MediaUploadProgress (best effort)."""
    if chunk_status is None:
        return 0
    rp = getattr(chunk_status, "resumable_progress", None)
    if rp is not None:
        return min(max(int(rp), 0), total_bytes)
    try:
        frac = float(chunk_status.progress())
        return min(max(int(frac * total_bytes), 0), total_bytes)
    except Exception:
        return 0


def _resumable_upload(
    request: Any,
    http_error_cls: Any,
    *,
    total_bytes: int = 1,
    show_progress: bool = False,
    description: str = "YouTube 上传",
    progress_callback: Optional[Callable[[str], None]] = None,
    progress_label: str = "",
) -> str:
    progress_cm: Any = None
    progress: Any = None
    task_id: Optional[int] = None
    if show_progress and total_bytes > 0:
        try:
            from rich.console import Console
            from rich.markup import escape
            from rich.progress import (
                BarColumn,
                DownloadColumn,
                Progress,
                TextColumn,
                TimeRemainingColumn,
                TransferSpeedColumn,
            )

            safe_desc = escape(description) if description else "YouTube 上传"
            progress_cm = Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                DownloadColumn(binary_units=True),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=Console(stderr=True),
                transient=True,
                refresh_per_second=4,
            )
            progress = progress_cm.__enter__()
            task_id = progress.add_task(safe_desc, total=total_bytes)
        except Exception:
            logger.debug("YouTube upload progress bar unavailable", exc_info=True)
            progress_cm = None
            progress = None
            task_id = None

    try:
        response = None
        retry = 0
        last_pct = -1
        while response is None:
            try:
                chunk_status, response = request.next_chunk()
                done = _upload_progress_bytes(chunk_status, total_bytes)
                if progress is not None and task_id is not None:
                    progress.update(task_id, completed=done)
                if progress_callback and total_bytes > 0:
                    pct = min(100, max(0, int((done * 100) / total_bytes)))
                    if _should_emit_progress_pct(pct, last_pct):
                        tag = progress_label.strip() or "video"
                        progress_callback(f"[i] 上传中 {tag}: {pct}%")
                        last_pct = pct
                if response and response.get("id"):
                    if progress is not None and task_id is not None:
                        progress.update(task_id, completed=total_bytes)
                    if progress_callback and last_pct < 100:
                        tag = progress_label.strip() or "video"
                        progress_callback(f"[i] 上传完成 {tag}: 100%")
                    return str(response["id"])
            except Exception as exc:
                if _is_retriable_transport_timeout(exc):
                    retry += 1
                    if retry > MAX_RETRIES:
                        raise YouTubeUploadError(
                            "YouTube upload timed out after retries; "
                            "check network or raise youtube_upload.http_timeout_seconds"
                        ) from exc
                    logger.warning(
                        "YouTube upload transport timeout, retry %s/%s: %s",
                        retry,
                        MAX_RETRIES,
                        exc,
                    )
                    time.sleep(random.random() * (2 ** retry))
                    continue
                if not isinstance(exc, http_error_cls):
                    raise
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status not in RETRIABLE_STATUS_CODES:
                    raise
                retry += 1
                if retry > MAX_RETRIES:
                    raise YouTubeUploadError("YouTube upload retries exhausted") from exc
                logger.warning(
                    "YouTube upload HTTP %s, retry %s/%s",
                    status,
                    retry,
                    MAX_RETRIES,
                )
                time.sleep(random.random() * (2 ** retry))
        raise YouTubeUploadError(f"YouTube upload returned unexpected response: {response}")
    finally:
        if progress_cm is not None:
            try:
                progress_cm.__exit__(None, None, None)
            except Exception:
                logger.debug("YouTube upload progress teardown failed", exc_info=True)


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


def _http_timeout_seconds_from_settings(settings: Dict[str, Any]) -> float:
    raw = settings.get("http_timeout_seconds", 600)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 600.0
    if value <= 0:
        return 600.0
    return value


def _upload_chunk_size_from_settings(settings: Dict[str, Any]) -> int:
    """Return MediaFileUpload chunksize (multiple of 256 KiB), or default 8 MiB."""
    raw = settings.get("upload_chunk_size_bytes", DEFAULT_UPLOAD_CHUNK_SIZE)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_UPLOAD_CHUNK_SIZE
    if value <= 0:
        return DEFAULT_UPLOAD_CHUNK_SIZE
    # googleapiclient requires multiples of 256 KiB when not uploading in one shot
    unit = 256 * 1024
    return max(unit, (value // unit) * unit)


def _should_emit_progress_pct(pct: int, last_pct: int) -> bool:
    """Throttle log/GUI progress to every PROGRESS_CALLBACK_STEP_PCT (and 100%)."""
    if pct <= last_pct:
        return False
    if pct >= 100:
        return True
    step = PROGRESS_CALLBACK_STEP_PCT
    # Treat unset last_pct (-1) as 0 so we do not emit a useless 0% line
    baseline = max(last_pct, 0)
    return pct // step > baseline // step


def _is_retriable_transport_timeout(
    exc: BaseException, _seen: Optional[set] = None
) -> bool:
    seen = _seen if _seen is not None else set()
    eid = id(exc)
    if eid in seen:
        return False
    seen.add(eid)
    if isinstance(exc, TimeoutError):
        return True
    # socket.timeout is TimeoutError on Py3; also catch wrapped OSError messages
    if isinstance(exc, OSError) and "timed out" in str(exc).lower():
        return True
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, BaseException) and _is_retriable_transport_timeout(
        cause, seen
    ):
        return True
    ctx = getattr(exc, "__context__", None)
    if (
        isinstance(ctx, BaseException)
        and ctx is not cause
        and _is_retriable_transport_timeout(ctx, seen)
    ):
        return True
    return False


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


def _truncate_description(text: str) -> str:
    if len(text) <= YOUTUBE_MAX_DESCRIPTION_CHARS:
        return text
    return text[: YOUTUBE_MAX_DESCRIPTION_CHARS - 3].rstrip() + "..."


def _normalize_youtube_tags(*tag_sources: Any) -> List[str]:
    """Merge tag lists, dedupe, enforce YouTube-friendly length/count."""
    seen: set[str] = set()
    out: List[str] = []
    for source in tag_sources:
        items: List[Any]
        if source is None:
            continue
        if isinstance(source, (list, tuple)):
            items = list(source)
        else:
            items = [source]
        for raw in items:
            s = str(raw).strip().lstrip("#")
            if not s:
                continue
            s = s[:YOUTUBE_MAX_TAG_LEN]
            key = s.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= YOUTUBE_MAX_TAGS:
                return out
    return out


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    s = _HTML_TAG_RE.sub("", text)
    return (
        s.replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("\n", " ")
    )


def _unwrap_google_http_error(exc: BaseException) -> Optional[Any]:
    """Find googleapiclient HttpError (including ResumableUploadError subclass) in chain."""
    try:
        from googleapiclient.errors import HttpError as GoogleHttpError
    except ImportError:
        return None
    stack: List[BaseException] = [exc]
    visited: set[int] = set()
    while stack:
        cur = stack.pop()
        if not isinstance(cur, BaseException):
            continue
        cid = id(cur)
        if cid in visited:
            continue
        visited.add(cid)
        if isinstance(cur, GoogleHttpError):
            return cur
        cause = getattr(cur, "__cause__", None)
        if isinstance(cause, BaseException) and id(cause) not in visited:
            stack.append(cause)
        ctx = getattr(cur, "__context__", None)
        if (
            isinstance(ctx, BaseException)
            and ctx is not cause
            and id(ctx) not in visited
        ):
            stack.append(ctx)
        for arg in getattr(cur, "args", ()) or ():
            if isinstance(arg, BaseException):
                stack.append(arg)
    return None


def _format_upload_exception(exc: BaseException) -> str:
    """Readable API / transport errors for logs and CLI."""
    try:
        from googleapiclient.errors import HttpError as GoogleHttpError
    except ImportError:
        GoogleHttpError = ()  # type: ignore[misc,assignment]

    if GoogleHttpError and isinstance(exc, GoogleHttpError):
        return _format_google_http_error(exc)
    http = _unwrap_google_http_error(exc)
    if http is not None:
        return _format_google_http_error(http)
    text = str(exc)
    if "quotaExceeded" in text or (
        "youtube.quota" in text and "403" in text
    ):
        return (
            "HTTP 403 | quotaExceeded: YouTube Data API 上传/写入配额已用完"
            "（默认按天重置，见 https://developers.google.com/youtube/v3/getting-started#quota ）"
        )
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, OSError) and "timed out" in str(exc).lower()
    ):
        return (
            "TimeoutError: timed out（上传连接超时；请检查网络/代理，"
            "或在 config.yml 的 youtube_upload.http_timeout_seconds 调大，默认 600）"
        )
    return f"{type(exc).__name__}: {_strip_html(text)[:500]}"


def _format_google_http_error(exc: Any) -> str:
    parts: List[str] = []
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is not None:
        parts.append(f"HTTP {status}")
    details = getattr(exc, "error_details", None) or ()
    for item in details[:3]:
        if isinstance(item, dict):
            msg = item.get("message") or str(item)
            reason = item.get("reason", "")
            if reason:
                parts.append(f"{reason}: {msg}")
            else:
                parts.append(msg)
        else:
            parts.append(str(item))
    raw = getattr(exc, "content", None)
    if not parts and raw:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            data = json.loads(raw)
            err = data.get("error") or {}
            parts.append(err.get("message", str(data))[:500])
            for e in (err.get("errors") or [])[:3]:
                if isinstance(e, dict):
                    parts.append(
                        f"{e.get('reason', 'error')}: {e.get('message', '')}"[:300]
                    )
        except (json.JSONDecodeError, TypeError, ValueError):
            parts.append(str(raw)[:300])
    if not parts:
        parts.append(str(exc))
    joined = " | ".join(_strip_html(p) for p in parts)
    joined = " ".join(joined.split())
    if "quotaExceeded" in joined or "youtube.quota" in joined:
        return (
            "HTTP 403 | quotaExceeded: YouTube Data API 上传/写入配额已用完"
            "（默认按天重置，见 https://developers.google.com/youtube/v3/getting-started#quota ）"
        )
    if "uploadLimitExceeded" in joined.casefold():
        suffix = (
            " ［说明：此为频道可上传视频数等产品限制，非 Cloud Console 里 Data API 的 Queries/day。］"
        )
        if len(joined) + len(suffix) <= 450:
            return joined + suffix
    if len(joined) > 400:
        return joined[:397] + "..."
    return joined
