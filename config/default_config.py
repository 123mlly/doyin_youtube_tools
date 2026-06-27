from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "path": "./Downloaded/",
    "music": True,
    "cover": True,
    "avatar": True,
    "json": True,
    "start_time": "",
    "end_time": "",
    "folderstyle": True,
    "mode": ["post"],
    "number": {
        "post": 0,
        "like": 0,
        "allmix": 0,
        "mix": 0,
        "music": 0,
        "collect": 0,
        "collectmix": 0,
    },
    "increase": {
        "post": False,
        "like": False,
        "allmix": False,
        "mix": False,
        "music": False,
    },
    "thread": 5,
    "retry_times": 3,
    "rate_limit": 2,
    "proxy": "",
    "database": True,
    "database_path": "dy_downloader.db",
    "progress": {
        "quiet_logs": True,
    },
    "transcript": {
        "enabled": False,
        "model": "gpt-4o-mini-transcribe",
        "output_dir": "",
        "response_formats": ["txt", "json"],
        "api_url": "https://api.openai.com/v1/audio/transcriptions",
        "api_key_env": "OPENAI_API_KEY",
        "api_key": "",
    },
    "auto_cookie": False,
    "browser_fallback": {
        "enabled": True,
        "headless": False,
        "max_scrolls": 240,
        "idle_rounds": 8,
        "wait_timeout_seconds": 600,
    },
    # 下载完成通知（可选）。providers 支持 bark / telegram / webhook。
    "notifications": {
        "enabled": False,
        "on_success": True,
        "on_failure": True,
        "providers": [],
    },
    # 评论采集（可选）。启用后每个作品会额外生成 *_comments.json。
    "comments": {
        "enabled": False,
        "include_replies": False,
        "max_comments": 0,  # 0 = 不限
        "page_size": 20,
    },
    # 直播录制（可选）。由 live.douyin.com / /follow/live/ 链接触发。
    "live": {
        "max_duration_seconds": 0,  # 0 = 直到流结束
        "chunk_size": 65536,
        # 单次读流超过该秒数无新数据则结束录制（保留已录部分）；过小易误判卡顿为结束
        "idle_timeout_seconds": 90,
    },
    # REST API 服务模式（可选，需 fastapi + uvicorn）。
    "server": {
        "max_jobs": 500,        # 内存中保留的 job 条数上限（不含 in-flight）
        "job_ttl_seconds": 86400,  # 完成态 job 保留时间（秒）
    },
    # YouTube 上传（可选）。需安装 [youtube] extra 并先运行 --youtube-auth。
    "youtube_upload": {
        "enabled": False,
        "auto_after_download": False,
        "client_secret_path": "config/youtube_client_secret.json",
        "token_path": "config/youtube_token.json",
        "privacy_status": "public",
        "category_id": "22",
        "tags": [],
        "title_template": "{desc}",
        "description_template": "{desc}\n\nAuthor: {author_name}\nAweme ID: {aweme_id}",
        "max_items_per_run": 0,
        "dry_run": False,
        # 真实上传时在 stderr 显示 Rich 进度条（与下载总进度独立；在 executor 线程内绘制）
        "show_upload_progress": True,
        # googleapiclient/httplib2 默认 socket 超时偏短，慢网络易 TimeoutError；0 或无效值回退 600
        "http_timeout_seconds": 600,
    },
}
