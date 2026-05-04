import json
import sys
from types import SimpleNamespace

import pytest

from gui import services, theme
from gui.services import DownloadOptions, YouTubeOptions


def test_interpreter_for_cookie_subprocess_not_frozen():
    from gui.main_window import MainWindow

    if getattr(sys, "frozen", False):
        pytest.skip("only meaningful in unfrozen CPython")
    assert MainWindow._interpreter_for_cookie_subprocess() == sys.executable


def test_theme_stylesheet_switch():
    assert "#f1f5f9" in theme.stylesheet_for("light")
    assert "#0b1220" in theme.stylesheet_for("dark")
    assert "#ffffff" in theme.log_area_stylesheet("light")
    assert "#020617" in theme.log_area_stylesheet("dark")


def test_parse_links_ignores_empty_lines():
    assert services.parse_links("https://a\n\n  https://b  \n") == [
        "https://a",
        "https://b",
    ]


def test_apply_download_options_updates_config(tmp_path):
    config_file = tmp_path / "config.yml"
    config_file.write_text("{}", encoding="utf-8")
    config = services.load_config(str(config_file))

    services.apply_download_options(
        config,
        DownloadOptions(
            config_path=str(config_file),
            links_text="https://www.douyin.com/video/1",
            output_path=str(tmp_path / "Downloaded"),
            thread=3,
            music=False,
            cover=True,
            avatar=False,
            json_metadata=True,
            database=False,
            proxy="http://127.0.0.1:7890",
            quiet_logs=False,
        ),
    )

    assert config.get_links() == ["https://www.douyin.com/video/1"]
    assert config.get("thread") == 3
    assert config.get("music") is False
    assert config.get("avatar") is False
    assert config.get("database") is False
    assert config.get("proxy") == "http://127.0.0.1:7890"
    assert config.get("progress")["quiet_logs"] is False


def test_save_cookie_string_updates_cookie_file_and_config(tmp_path):
    config_file = tmp_path / "config.yml"
    cookie_file = tmp_path / "config" / "cookies.json"

    cookies = services.save_cookie_string(
        "ttwid=abc; odin_tt=def; passport_csrf_token=csrf",
        config_path=str(config_file),
        cookie_file=str(cookie_file),
    )

    assert cookies["ttwid"] == "abc"
    stored = json.loads(cookie_file.read_text(encoding="utf-8"))
    assert stored["odin_tt"] == "def"
    config = services.load_config(str(config_file))
    assert config.get_cookies()["passport_csrf_token"] == "csrf"


@pytest.mark.asyncio
async def test_run_downloads_uses_download_url(monkeypatch, tmp_path):
    calls = []

    class FakeCookieManager:
        def set_cookies(self, cookies):
            self.cookies = cookies

        def validate_cookies(self):
            return True

    async def fake_download_url(
        url,
        config,
        cookie_manager,
        database,
        progress_reporter=None,
        youtube_uploader=None,
    ):
        calls.append((url, config.get("path"), progress_reporter, youtube_uploader))
        return SimpleNamespace(total=1, success=1, failed=0, skipped=0)

    monkeypatch.setattr(services, "CookieManager", FakeCookieManager)
    monkeypatch.setattr(services, "download_url", fake_download_url)
    monkeypatch.setattr(services, "build_youtube_uploader", lambda *_args, **_kwargs: None)

    summary = await services.run_downloads(
        DownloadOptions(
            links_text="https://www.douyin.com/video/1",
            output_path=str(tmp_path / "Downloaded"),
            database=False,
        )
    )

    assert summary.processed_urls == 1
    assert summary.success == 1
    assert calls[0][0] == "https://www.douyin.com/video/1"


@pytest.mark.asyncio
async def test_upload_latest_to_youtube_passes_dry_run_settings(monkeypatch, tmp_path):
    captured = {}

    async def fake_publish(settings, base_path, limit, database=None):
        captured["settings"] = settings
        captured["base_path"] = base_path
        captured["limit"] = limit
        return [SimpleNamespace(status="dry_run")]

    monkeypatch.setattr(services, "publish_latest_from_manifest", fake_publish)

    results = await services.upload_latest_to_youtube(
        YouTubeOptions(
            config_path=str(tmp_path / "missing.yml"),
            client_secret_path="secret.json",
            token_path="token.json",
            privacy_status="unlisted",
            latest_count=5,
            dry_run=True,
        )
    )

    assert results[0].status == "dry_run"
    assert captured["settings"]["client_secret_path"] == "secret.json"
    assert captured["settings"]["token_path"] == "token.json"
    assert captured["settings"]["privacy_status"] == "unlisted"
    assert captured["settings"]["dry_run"] is True
    assert captured["limit"] == 5


@pytest.mark.asyncio
async def test_upload_paths_to_youtube_passes_paths_and_settings(monkeypatch, tmp_path):
    captured = {}

    async def fake_publish(settings, paths, database=None):
        captured["settings"] = settings
        captured["paths"] = paths
        captured["database"] = database
        return [SimpleNamespace(status="dry_run")]

    monkeypatch.setattr(services, "publish_paths_to_youtube", fake_publish)

    results = await services.upload_paths_to_youtube(
        YouTubeOptions(
            config_path=str(tmp_path / "missing.yml"),
            client_secret_path="secret.json",
            token_path="token.json",
            privacy_status="private",
            latest_count=1,
            dry_run=True,
        ),
        [str(tmp_path / "a.mp4"), str(tmp_path / "b.mov")],
    )

    assert results[0].status == "dry_run"
    assert captured["settings"]["client_secret_path"] == "secret.json"
    assert captured["settings"]["privacy_status"] == "private"
    assert len(captured["paths"]) == 2
    assert {p.name for p in captured["paths"]} == {"a.mp4", "b.mov"}


@pytest.mark.asyncio
async def test_upload_paths_to_youtube_empty_paths_no_publish(monkeypatch, tmp_path):
    called = []

    async def fake_publish(*_args, **_kwargs):
        called.append(True)
        return []

    monkeypatch.setattr(services, "publish_paths_to_youtube", fake_publish)

    results = await services.upload_paths_to_youtube(
        YouTubeOptions(config_path=str(tmp_path / "missing.yml")),
        [],
    )

    assert results == []
    assert called == []
