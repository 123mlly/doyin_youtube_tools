from pathlib import Path

import pytest

from utils.youtube_uploader import (
    YouTubeUploader,
    YouTubeUploadError,
    publish_latest_from_manifest,
)


class _FakeDatabase:
    def __init__(self, uploaded=False):
        self.uploaded = uploaded
        self.history = []

    async def is_youtube_uploaded(self, aweme_id):
        return self.uploaded

    async def upsert_youtube_upload_history(self, upload_data):
        self.history.append(upload_data)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    return path


def test_youtube_uploader_selects_primary_video(tmp_path):
    base_path = tmp_path / "Downloaded"
    video = _touch(base_path / "author" / "demo.mp4")
    _touch(base_path / "author" / "demo_cover.jpg")
    _touch(base_path / "author" / "demo_music.mp3")
    _touch(base_path / "author" / "demo_data.json")

    uploader = YouTubeUploader({"enabled": True, "dry_run": True})
    record = {
        "aweme_id": "123",
        "media_type": "video",
        "file_paths": [
            "author/demo_cover.jpg",
            "author/demo_music.mp3",
            "author/demo_data.json",
            "author/demo.mp4",
        ],
    }

    assert uploader.select_video_path(base_path, record) == video


def test_youtube_uploader_skips_non_video_records(tmp_path):
    base_path = tmp_path / "Downloaded"
    _touch(base_path / "author" / "live_1.mp4")
    uploader = YouTubeUploader({"enabled": True, "dry_run": True})

    assert uploader.select_video_path(
        base_path,
        {
            "aweme_id": "123",
            "media_type": "gallery",
            "file_paths": ["author/live_1.mp4"],
        },
    ) is None


def test_youtube_uploader_builds_metadata_from_templates():
    uploader = YouTubeUploader(
        {
            "title_template": "Douyin {aweme_id}: {desc}",
            "description_template": "{desc}\nby {author_name}",
            "privacy_status": "public",
            "tags": ["douyin", "shorts"],
        }
    )

    metadata = uploader.build_metadata(
        {
            "aweme_id": "123",
            "desc": "hello",
            "author_name": "Author",
        }
    )

    assert metadata["title"] == "Douyin 123: hello"
    assert metadata["description"] == "hello\nby Author"
    assert metadata["privacy_status"] == "public"
    assert metadata["tags"] == ["douyin", "shorts"]


@pytest.mark.asyncio
async def test_youtube_uploader_dry_run_records_history(tmp_path):
    base_path = tmp_path / "Downloaded"
    _touch(base_path / "author" / "demo.mp4")
    database = _FakeDatabase()
    uploader = YouTubeUploader(
        {"enabled": True, "dry_run": True},
        database=database,
    )

    result = await uploader.upload_manifest_record(
        base_path,
        {
            "aweme_id": "123",
            "desc": "hello world",
            "media_type": "video",
            "file_paths": ["author/demo.mp4"],
        },
    )

    assert result.status == "dry_run"
    assert result.dry_run is True
    assert result.file_path.endswith("demo.mp4")
    assert database.history[0]["status"] == "dry_run"


@pytest.mark.asyncio
async def test_youtube_uploader_skips_already_uploaded(tmp_path):
    uploader = YouTubeUploader(
        {"enabled": True, "dry_run": True},
        database=_FakeDatabase(uploaded=True),
    )

    result = await uploader.upload_manifest_record(
        tmp_path,
        {"aweme_id": "123", "media_type": "video", "file_paths": []},
    )

    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_publish_latest_from_manifest_reads_recent_records(tmp_path, monkeypatch):
    base_path = tmp_path / "Downloaded"
    base_path.mkdir()
    manifest = base_path / "download_manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                '{"aweme_id": "1", "desc": "one", "media_type": "video", "file_paths": []}',
                '{"aweme_id": "2", "desc": "two", "media_type": "video", "file_paths": []}',
            ]
        ),
        encoding="utf-8",
    )
    seen = []

    async def fake_upload(self, base_path_arg, record, force=False):
        seen.append((base_path_arg, record, force))
        return type("Result", (), {"status": "dry_run"})()

    monkeypatch.setattr(YouTubeUploader, "upload_manifest_record", fake_upload)

    results = await publish_latest_from_manifest(
        {"enabled": True, "dry_run": True},
        base_path,
        1,
    )

    assert len(results) == 1
    assert seen[0][0] == base_path
    assert seen[0][1]["aweme_id"] == "2"
    assert seen[0][2] is True


def test_youtube_uploader_missing_dependencies_message(monkeypatch, tmp_path):
    uploader = YouTubeUploader(
        {
            "enabled": True,
            "dry_run": False,
            "token_path": str(tmp_path / "token.json"),
        }
    )

    def fail_dependencies():
        raise YouTubeUploadError("missing google deps")

    monkeypatch.setattr(
        "utils.youtube_uploader._load_google_auth_dependencies",
        fail_dependencies,
    )

    with pytest.raises(YouTubeUploadError, match="missing google deps"):
        uploader._upload_video_sync(tmp_path / "demo.mp4", uploader.build_metadata({}))


def test_youtube_uploader_upload_success_with_mocked_google_client(
    monkeypatch, tmp_path
):
    video = _touch(tmp_path / "demo.mp4")
    uploader = YouTubeUploader({"enabled": True})

    class FakeRequest:
        def next_chunk(self):
            return None, {"id": "youtube-video-id"}

    class FakeVideos:
        def insert(self, part, body, media_body):
            assert part == "snippet,status"
            assert body["status"]["privacyStatus"] == "public"
            assert media_body.path == str(video)
            return FakeRequest()

    class FakeService:
        def videos(self):
            return FakeVideos()

    class FakeMediaUpload:
        def __init__(self, path, chunksize=-1, resumable=True):
            self.path = path
            self.chunksize = chunksize
            self.resumable = resumable

    monkeypatch.setattr(
        "utils.youtube_uploader._load_google_auth_dependencies",
        lambda: (object, object, object),
    )
    monkeypatch.setattr(
        "utils.youtube_uploader._load_google_api_dependencies",
        lambda: (lambda *_args, **_kwargs: FakeService(), FakeMediaUpload, Exception),
    )
    monkeypatch.setattr(uploader.auth, "load_credentials", lambda: object())

    video_id = uploader._upload_video_sync(video, uploader.build_metadata({"desc": "demo"}))

    assert video_id == "youtube-video-id"
