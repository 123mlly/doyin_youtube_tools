from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import ResumableUploadError

from utils.youtube_uploader import (
    YouTubeUploader,
    YouTubeUploadError,
    YouTubeUploadResult,
    DEFAULT_UPLOAD_CHUNK_SIZE,
    _dedupe_manifest_batch,
    _http_timeout_seconds_from_settings,
    _is_retriable_transport_timeout,
    _is_uploadable_video_file,
    _manual_aweme_id_for_path,
    _resumable_upload,
    _should_emit_progress_pct,
    _upload_chunk_size_from_settings,
    collect_uploadable_videos_in_directory,
    _format_upload_exception,
    _normalize_youtube_tags,
    publish_latest_from_manifest,
    publish_paths_to_youtube,
    youtube_upload_report_events,
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


def test_collect_uploadable_videos_in_directory_top_level_only(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"1")
    (tmp_path / "b.MP4").write_bytes(b"2")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.mp4").write_bytes(b"3")
    found = collect_uploadable_videos_in_directory(tmp_path, recursive=False)
    assert [p.name for p in found] == ["a.mp4", "b.MP4"]


def test_collect_uploadable_videos_in_directory_recursive(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"1")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "b.mov").write_bytes(b"2")
    found = collect_uploadable_videos_in_directory(tmp_path, recursive=True)
    assert {p.name for p in found} == {"a.mp4", "b.mov"}


def test_collect_uploadable_videos_in_directory_not_a_dir(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("y", encoding="utf-8")
    with pytest.raises(YouTubeUploadError, match="Not a directory"):
        collect_uploadable_videos_in_directory(f)


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
            "tags": ["shorts", "extra"],  # duplicate 'shorts' case-insensitive merge
        }
    )

    assert metadata["title"] == "Douyin 123: hello"
    assert metadata["description"] == "hello\nby Author"
    assert metadata["privacy_status"] == "public"
    assert metadata["tags"] == ["douyin", "shorts", "extra"]


def test_format_upload_exception_resumable_upload_error_is_http_error_subclass():
    """ResumableUploadError subclasses HttpError; formatting must not collapse to empty."""
    resp = MagicMock()
    resp.status = 403
    resp.reason = "Forbidden"
    content = (
        b'{"error":{"message":"Quota exceeded","errors":['
        b'{"domain":"youtube.quota","reason":"quotaExceeded","message":"Quota exceeded"}'
        b"]}}"
    )
    exc = ResumableUploadError(resp, content)
    text = _format_upload_exception(exc)
    assert "quotaExceeded" in text or "配额" in text


def test_normalize_youtube_tags_caps_count_and_length():
    many = [f"t{i}" for i in range(50)]
    merged = _normalize_youtube_tags(["a" * 40], many)
    assert len(merged) == 30
    assert all(len(t) <= 30 for t in merged)
    assert merged[0] == "a" * 30


def test_youtube_upload_report_events_upload_limit_hint():
    results = [
        YouTubeUploadResult(
            aweme_id="1",
            status="failure",
            error_message="HTTP 400 | uploadLimitExceeded: too many",
        ),
    ]
    texts = [e[1] for e in youtube_upload_report_events(results)]
    assert any("uploadLimitExceeded" in t for t in texts)
    assert not any("若出现 quotaExceeded" in t for t in texts)


def test_youtube_upload_report_events_groups_failures():
    results = [
        YouTubeUploadResult(
            aweme_id="1", status="failure", error_message="HTTP 403 | quotaExceeded: x"
        ),
        YouTubeUploadResult(
            aweme_id="2", status="failure", error_message="HTTP 403 | quotaExceeded: x"
        ),
        YouTubeUploadResult(aweme_id="3", status="skipped", error_message="already"),
    ]
    events = youtube_upload_report_events(results)
    levels = [e[0] for e in events]
    assert "success" in levels
    assert levels.count("warning") >= 2
    assert any("×2" in e[1] for e in events)


def test_dedupe_manifest_batch_keeps_last_per_aweme():
    batch = [
        {"aweme_id": "1", "n": 1},
        {"aweme_id": "2", "n": 2},
        {"aweme_id": "1", "n": 3},
    ]
    out = _dedupe_manifest_batch(batch)
    assert [r["n"] for r in out] == [2, 3]


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

    async def fake_upload(self, base_path_arg, record, force=False, explicit_video=None):
        seen.append((base_path_arg, record, force, explicit_video))
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
    assert seen[0][3] is None


@pytest.mark.asyncio
async def test_publish_paths_to_youtube_calls_upload_per_path(tmp_path, monkeypatch):
    v1 = _touch(tmp_path / "a.mp4")
    v2 = _touch(tmp_path / "b.mov")
    seen = []

    async def fake_upload(self, base_path_arg, record, force=False, explicit_video=None):
        seen.append((base_path_arg, record, force, explicit_video))
        return YouTubeUploadResult(aweme_id=record.get("aweme_id", ""), status="dry_run")

    monkeypatch.setattr(YouTubeUploader, "upload_manifest_record", fake_upload)

    results = await publish_paths_to_youtube(
        {"enabled": True, "dry_run": True},
        [v1, v2],
    )

    assert len(results) == 2
    assert len(seen) == 2
    assert seen[0][3] == v1
    assert seen[1][3] == v2


@pytest.mark.asyncio
async def test_upload_manifest_record_explicit_video_dry_run(tmp_path):
    video = _touch(tmp_path / "clip.mkv")
    uploader = YouTubeUploader({"enabled": True, "dry_run": True})
    result = await uploader.upload_manifest_record(
        tmp_path,
        {"aweme_id": "", "media_type": "video", "desc": "", "author_name": ""},
        force=True,
        explicit_video=video,
    )
    assert result.status == "dry_run"
    assert result.aweme_id.startswith("manual_")
    assert result.file_path == str(video.resolve())


def test_manual_aweme_id_stable(tmp_path):
    p = _touch(tmp_path / "x.mp4")
    a = _manual_aweme_id_for_path(p)
    b = _manual_aweme_id_for_path(p)
    assert a == b
    assert a.startswith("manual_")


def test_is_uploadable_video_file_suffix(tmp_path):
    assert _is_uploadable_video_file(tmp_path / "missing.mp4") is True
    f = _touch(tmp_path / "a.mp4")
    assert _is_uploadable_video_file(f) is True
    assert _is_uploadable_video_file(tmp_path / "x.txt") is False


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
            assert media_body.chunksize == DEFAULT_UPLOAD_CHUNK_SIZE
            assert media_body.resumable is True
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


def test_http_timeout_seconds_from_settings_defaults_and_invalid():
    assert _http_timeout_seconds_from_settings({}) == 600.0
    assert _http_timeout_seconds_from_settings({"http_timeout_seconds": 900}) == 900.0
    assert _http_timeout_seconds_from_settings({"http_timeout_seconds": 0}) == 600.0
    assert _http_timeout_seconds_from_settings({"http_timeout_seconds": "bad"}) == 600.0


def test_upload_chunk_size_from_settings_aligns_to_256kib():
    assert _upload_chunk_size_from_settings({}) == DEFAULT_UPLOAD_CHUNK_SIZE
    assert _upload_chunk_size_from_settings({"upload_chunk_size_bytes": 0}) == (
        DEFAULT_UPLOAD_CHUNK_SIZE
    )
    # 1 MiB is already a multiple of 256 KiB
    assert _upload_chunk_size_from_settings({"upload_chunk_size_bytes": 1024 * 1024}) == (
        1024 * 1024
    )
    # Round down to 256 KiB boundary
    assert _upload_chunk_size_from_settings(
        {"upload_chunk_size_bytes": 1024 * 1024 + 100}
    ) == (1024 * 1024)


def test_should_emit_progress_pct_throttles():
    assert _should_emit_progress_pct(0, -1) is False
    assert _should_emit_progress_pct(5, -1) is True
    assert _should_emit_progress_pct(6, 5) is False
    assert _should_emit_progress_pct(10, 5) is True
    assert _should_emit_progress_pct(100, 95) is True
    assert _should_emit_progress_pct(4, 4) is False


def test_is_retriable_transport_timeout():
    assert _is_retriable_transport_timeout(TimeoutError("timed out")) is True
    assert _is_retriable_transport_timeout(OSError("timed out")) is True
    assert _is_retriable_transport_timeout(ValueError("nope")) is False
    wrapped = RuntimeError("wrap")
    wrapped.__cause__ = TimeoutError("timed out")
    assert _is_retriable_transport_timeout(wrapped) is True


def test_resumable_upload_retries_on_timeout(monkeypatch):
    calls = {"n": 0}

    class FakeRequest:
        def next_chunk(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("timed out")
            return None, {"id": "yt-id-after-retry"}

    monkeypatch.setattr("utils.youtube_uploader.time.sleep", lambda _s: None)
    video_id = _resumable_upload(FakeRequest(), Exception)
    assert video_id == "yt-id-after-retry"
    assert calls["n"] == 3


def test_format_upload_exception_timeout_hint():
    msg = _format_upload_exception(TimeoutError("timed out"))
    assert "http_timeout_seconds" in msg


def test_resumable_upload_progress_callback_throttled(monkeypatch):
    events = []

    class FakeStatus:
        def __init__(self, done):
            self.resumable_progress = done

    class FakeRequest:
        def __init__(self):
            self.n = 0
            self.sizes = [1_000_000, 3_000_000, 5_000_000, 8_000_000, 10_000_000]

        def next_chunk(self):
            done = self.sizes[self.n]
            self.n += 1
            if done >= 10_000_000:
                return FakeStatus(done), {"id": "done"}
            return FakeStatus(done), None

    video_id = _resumable_upload(
        FakeRequest(),
        Exception,
        total_bytes=10_000_000,
        show_progress=False,
        progress_callback=events.append,
        progress_label="vid",
    )
    assert video_id == "done"
    # 10%, 30%, 50%, 80%, then completion 100% (or 100% from last chunk)
    assert any("10%" in e for e in events)
    assert any("100%" in e for e in events)
    # Should not emit every single percent
    assert len(events) <= 8
