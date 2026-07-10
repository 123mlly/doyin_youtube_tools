from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from auth import CookieManager
from cli.main import download_url
from config import ConfigLoader
from core.downloader_base import DownloadResult
from storage import Database
from utils.cookie_utils import parse_cookie_header, sanitize_cookies
from utils.youtube_uploader import (
    build_youtube_uploader,
    publish_latest_from_manifest,
    publish_paths_to_youtube,
    run_youtube_auth,
    youtube_settings,
    youtube_upload_report_events,
)

LogCallback = Optional[Callable[[str], None]]


@dataclass
class DownloadOptions:
    config_path: str = "config.yml"
    links_text: str = ""
    output_path: str = "./Downloaded/"
    thread: int = 5
    music: bool = True
    cover: bool = True
    avatar: bool = True
    json_metadata: bool = True
    database: bool = True
    database_path: str = "dy_downloader.db"
    proxy: str = ""
    quiet_logs: bool = True


@dataclass
class YouTubeOptions:
    config_path: str = "config.yml"
    client_secret_path: str = "config/youtube_client_secret.json"
    token_path: str = "config/youtube_token.json"
    privacy_status: str = "public"
    latest_count: int = 1
    dry_run: bool = True


@dataclass
class DownloadSummary:
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    processed_urls: int = 0
    messages: List[str] = field(default_factory=list)


def parse_links(links_text: str) -> List[str]:
    links = []
    for line in (links_text or "").splitlines():
        value = line.strip()
        if value:
            links.append(value)
    return links


def load_config(config_path: str) -> ConfigLoader:
    path = Path(config_path or "config.yml")
    return ConfigLoader(str(path)) if path.exists() else ConfigLoader(None)


def apply_download_options(config: ConfigLoader, options: DownloadOptions) -> None:
    links = parse_links(options.links_text)
    if links:
        config.update(link=links)
    config.update(
        path=options.output_path or "./Downloaded/",
        thread=max(1, int(options.thread or 1)),
        music=bool(options.music),
        cover=bool(options.cover),
        avatar=bool(options.avatar),
        json=bool(options.json_metadata),
        database=bool(options.database),
        database_path=options.database_path or "dy_downloader.db",
        proxy=options.proxy or "",
        progress={"quiet_logs": bool(options.quiet_logs)},
    )


def apply_youtube_options(config: ConfigLoader, options: YouTubeOptions) -> None:
    youtube_upload = dict(config.get("youtube_upload", {}) or {})
    youtube_upload.update(
        {
            "enabled": True,
            "client_secret_path": options.client_secret_path
            or "config/youtube_client_secret.json",
            "token_path": options.token_path or "config/youtube_token.json",
            "privacy_status": options.privacy_status or "public",
            "dry_run": bool(options.dry_run),
            # GUI 使用独立日志回调展示进度，关闭 CLI Rich 进度条避免输出到终端 stderr。
            "show_upload_progress": False,
        }
    )
    config.update(youtube_upload=youtube_upload)


def summarize_cookie_status(config_path: str) -> Dict[str, Any]:
    config = load_config(config_path)
    cookies = config.get_cookies()
    required = {"ttwid", "odin_tt", "passport_csrf_token"}
    missing = sorted(required - set(cookies))
    return {
        "count": len(cookies),
        "missing": missing,
        "has_ms_token": bool(cookies.get("msToken")),
    }


def save_cookie_string(
    cookie_text: str,
    *,
    config_path: str = "config.yml",
    cookie_file: str = "config/cookies.json",
) -> Dict[str, str]:
    cookies = sanitize_cookies(parse_cookie_header(cookie_text or ""))
    if not cookies:
        raise ValueError("No valid cookies found in pasted text.")

    cookie_path = Path(cookie_file)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _update_config_cookies(Path(config_path), cookies)
    return cookies


async def run_downloads(
    options: DownloadOptions,
    *,
    progress_reporter: Any = None,
    log: LogCallback = None,
) -> DownloadSummary:
    config = load_config(options.config_path)
    apply_download_options(config, options)
    if not config.validate():
        raise ValueError("Invalid configuration: links and output path are required.")

    cookies = config.get_cookies()
    cookie_manager = CookieManager()
    cookie_manager.set_cookies(cookies)
    if log and not cookie_manager.validate_cookies():
        log("Cookies may be invalid or incomplete.")

    database = None
    summary = DownloadSummary()
    try:
        if config.get("database"):
            db_path = config.get("database_path", "dy_downloader.db") or "dy_downloader.db"
            database = Database(db_path=str(db_path))
            await database.initialize()
            if log:
                log("Database initialized.")

        youtube_uploader = build_youtube_uploader(config, database=database)
        urls = config.get_links()
        summary.processed_urls = len(urls)
        for url in urls:
            if log:
                log(f"Start: {url}")
            result = await download_url(
                url,
                config,
                cookie_manager,
                database,
                progress_reporter=progress_reporter,
                youtube_uploader=youtube_uploader,
            )
            if result:
                _merge_result(summary, result)
                if log:
                    log(
                        "Done: total=%s success=%s failed=%s skipped=%s"
                        % (result.total, result.success, result.failed, result.skipped)
                    )
            elif log:
                log("Download failed or URL was invalid.")
    finally:
        if database is not None:
            await database.close()
    return summary


def run_youtube_authorization(options: YouTubeOptions) -> Dict[str, Any]:
    config = load_config(options.config_path)
    apply_youtube_options(config, options)
    return run_youtube_auth(youtube_settings(config))


async def upload_latest_to_youtube(
    options: YouTubeOptions,
    *,
    log: LogCallback = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[Any]:
    config = load_config(options.config_path)
    apply_youtube_options(config, options)
    base_path = Path(config.get("path") or "./Downloaded/")
    database = None
    try:
        if config.get("database"):
            db_path = config.get("database_path", "dy_downloader.db") or "dy_downloader.db"
            database = Database(db_path=str(db_path))
            await database.initialize()
        results = await publish_latest_from_manifest(
            youtube_settings(config),
            base_path,
            int(options.latest_count or 0),
            database=database,
            progress_callback=progress_callback,
        )
        if log:
            prefix = {"success": "", "warning": "[!] ", "info": "[i] "}
            for level, text in youtube_upload_report_events(results):
                log(prefix.get(level, "") + text)
        return results
    finally:
        if database is not None:
            await database.close()


async def upload_paths_to_youtube(
    options: YouTubeOptions,
    paths: List[str],
    *,
    log: LogCallback = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[Any]:
    if not paths:
        if log:
            log("[i] YouTube：未选择任何文件。")
        return []
    config = load_config(options.config_path)
    apply_youtube_options(config, options)
    database = None
    try:
        if config.get("database"):
            db_path = config.get("database_path", "dy_downloader.db") or "dy_downloader.db"
            database = Database(db_path=str(db_path))
            await database.initialize()
        results = await publish_paths_to_youtube(
            youtube_settings(config),
            [Path(p) for p in paths],
            database=database,
            progress_callback=progress_callback,
        )
        if log:
            prefix = {"success": "", "warning": "[!] ", "info": "[i] "}
            for level, text in youtube_upload_report_events(results):
                log(prefix.get(level, "") + text)
        return results
    finally:
        if database is not None:
            await database.close()


def _merge_result(summary: DownloadSummary, result: DownloadResult) -> None:
    summary.total += result.total
    summary.success += result.success
    summary.failed += result.failed
    summary.skipped += result.skipped
    for msg in getattr(result, "messages", ()) or ():
        if msg and msg not in summary.messages:
            summary.messages.append(msg)


def _update_config_cookies(config_path: Path, cookies: Dict[str, str]) -> None:
    data: Dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    data["cookies"] = cookies
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
