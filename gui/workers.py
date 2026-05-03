from __future__ import annotations

import asyncio
from typing import Callable

from PySide6.QtCore import QThread, Signal

from gui.progress_adapter import GuiProgressAdapter
from gui.services import (
    DownloadOptions,
    YouTubeOptions,
    run_downloads,
    run_youtube_authorization,
    upload_latest_to_youtube,
)


class _BaseWorker(QThread):
    log_message = Signal(str)
    failed = Signal(str)

    def _log(self, message: str) -> None:
        self.log_message.emit(message)

    def _run_guarded(self, task: Callable[[], None]) -> None:
        try:
            task()
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(_BaseWorker):
    finished_summary = Signal(int, int, int, int, str)
    step_changed = Signal(str, str)
    item_advanced = Signal(str, str)

    def __init__(self, options: DownloadOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        self._run_guarded(self._run)

    def _run(self) -> None:
        progress = GuiProgressAdapter()
        progress.step_changed.connect(self.step_changed.emit)
        progress.item_advanced.connect(self.item_advanced.emit)
        summary = asyncio.run(
            run_downloads(
                self.options,
                progress_reporter=progress,
                log=self._log,
            )
        )
        self.finished_summary.emit(
            summary.total,
            summary.success,
            summary.failed,
            summary.skipped,
            "\n".join(summary.messages),
        )


class YouTubeAuthWorker(_BaseWorker):
    authorized = Signal(str)

    def __init__(self, options: YouTubeOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        self._run_guarded(self._run)

    def _run(self) -> None:
        token = run_youtube_authorization(self.options)
        token_path = self.options.token_path or "config/youtube_token.json"
        if token.get("refresh_token"):
            self._log("Refresh token received.")
        self.authorized.emit(token_path)


class YouTubeUploadWorker(_BaseWorker):
    upload_finished = Signal(int, int, int, int)

    def __init__(self, options: YouTubeOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        self._run_guarded(self._run)

    def _run(self) -> None:
        results = asyncio.run(upload_latest_to_youtube(self.options, log=self._log))
        success = sum(1 for result in results if result.status == "success")
        dry_run = sum(1 for result in results if result.status == "dry_run")
        skipped = sum(1 for result in results if result.status == "skipped")
        failed = sum(1 for result in results if result.status == "failure")
        self.upload_finished.emit(success, dry_run, skipped, failed)
