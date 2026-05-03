from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.services import (
    DownloadOptions,
    YouTubeOptions,
    save_cookie_string,
    summarize_cookie_status,
)
from gui.workers import DownloadWorker, YouTubeAuthWorker, YouTubeUploadWorker


class MainWindow(QMainWindow):
    def __init__(self, initial_theme: str = "light"):
        super().__init__()
        self._theme_mode = initial_theme if initial_theme in ("light", "dark") else "light"
        self.setWindowTitle("抖音下载器&&YouTube上传器")
        self.setMinimumSize(1000, 760)
        self.resize(1040, 780)
        self._download_worker: Optional[DownloadWorker] = None
        self._youtube_auth_worker: Optional[YouTubeAuthWorker] = None
        self._youtube_upload_worker: Optional[YouTubeUploadWorker] = None

        self.statusBar().showMessage("就绪")

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.setCentralWidget(self.tabs)
        self._build_download_tab()
        self._build_cookie_tab()
        self._build_youtube_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self._refresh_cookie_status()
        self._apply_theme(self._theme_mode, persist=False, announce=False)

    @staticmethod
    def _page_layout(widget: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        return layout

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    def _build_download_tab(self) -> None:
        tab = QWidget()
        root = self._page_layout(tab)

        group = QGroupBox("下载任务")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.config_path_edit = QLineEdit("config.yml")
        browse_config_btn = QPushButton("浏览…")
        browse_config_btn.setFixedWidth(96)
        browse_config_btn.clicked.connect(self._pick_config_path)
        config_row = QHBoxLayout()
        config_row.setSpacing(8)
        config_row.addWidget(self.config_path_edit, 1)
        config_row.addWidget(browse_config_btn, 0)

        self.links_edit = QTextEdit()
        self.links_edit.setPlaceholderText("https://www.douyin.com/…")
        self.links_edit.setMinimumHeight(140)
        self.links_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self.output_path_edit = QLineEdit("./Downloaded/")
        browse_output_btn = QPushButton("浏览…")
        browse_output_btn.setFixedWidth(96)
        browse_output_btn.clicked.connect(self._pick_output_path)
        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        output_row.addWidget(self.output_path_edit, 1)
        output_row.addWidget(browse_output_btn, 0)

        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 64)
        self.thread_spin.setValue(5)
        self.thread_spin.setFixedWidth(120)

        self.music_check = QCheckBox("音乐")
        self.music_check.setChecked(True)
        self.cover_check = QCheckBox("封面")
        self.cover_check.setChecked(True)
        self.avatar_check = QCheckBox("头像")
        self.avatar_check.setChecked(True)
        self.json_check = QCheckBox("JSON 元数据")
        self.json_check.setChecked(True)

        toggles = QHBoxLayout()
        toggles.setSpacing(16)
        for widget in (
            self.music_check,
            self.cover_check,
            self.avatar_check,
            self.json_check,
        ):
            toggles.addWidget(widget)
        toggles.addStretch(1)

        form.addRow("配置文件", config_row)
        form.addRow("下载链接", self.links_edit)
        form.addRow("", self._hint("每行一个链接；留空则使用配置文件中的 link。"))
        form.addRow("保存目录", output_row)
        form.addRow("并发线程", self.thread_spin)
        form.addRow("附带资源", toggles)

        root.addWidget(group)

        self.start_download_btn = QPushButton("开始下载")
        self.start_download_btn.setObjectName("primaryButton")
        self.start_download_btn.setMinimumHeight(40)
        self.start_download_btn.setCursor(Qt.PointingHandCursor)
        self.start_download_btn.clicked.connect(self._start_download)
        root.addWidget(self.start_download_btn)
        root.addStretch(1)
        self.tabs.addTab(tab, "下载")

    def _build_cookie_tab(self) -> None:
        tab = QWidget()
        root = self._page_layout(tab)

        self.cookie_status_label = QLabel()
        self.cookie_status_label.setObjectName("statusPill")
        self.cookie_status_label.setWordWrap(True)
        self.cookie_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        fetch_group = QGroupBox("浏览器抓取（Playwright）")
        fetch_layout = QVBoxLayout(fetch_group)
        fetch_layout.addWidget(
            self._hint(
                "会打开浏览器并提示在终端按 Enter 确认登录；需已安装 playwright 与浏览器内核 "
                "（python -m playwright install chromium）。"
            )
        )
        fetch_row = QHBoxLayout()
        fetch_row.setSpacing(10)
        copy_cmd_btn = QPushButton("复制终端命令")
        copy_cmd_btn.setMinimumHeight(36)
        copy_cmd_btn.setCursor(Qt.PointingHandCursor)
        copy_cmd_btn.clicked.connect(self._copy_cookie_fetcher_command)
        fetch_row.addWidget(copy_cmd_btn, 0)
        if sys.platform == "darwin":
            term_btn = QPushButton("在 Terminal 中运行")
            term_btn.setMinimumHeight(36)
            term_btn.setCursor(Qt.PointingHandCursor)
            term_btn.clicked.connect(self._open_cookie_fetcher_in_terminal_macos)
            fetch_row.addWidget(term_btn, 0)
        elif sys.platform == "win32":
            cmd_btn = QPushButton("在 CMD 中运行")
            cmd_btn.setMinimumHeight(36)
            cmd_btn.setCursor(Qt.PointingHandCursor)
            cmd_btn.clicked.connect(lambda: self._open_cookie_fetcher_windows("cmd"))
            fetch_row.addWidget(cmd_btn, 0)
            ps_btn = QPushButton("在 PowerShell 中运行")
            ps_btn.setMinimumHeight(36)
            ps_btn.setCursor(Qt.PointingHandCursor)
            ps_btn.clicked.connect(lambda: self._open_cookie_fetcher_windows("powershell"))
            fetch_row.addWidget(ps_btn, 0)
        fetch_row.addStretch(1)
        fetch_layout.addLayout(fetch_row)

        paste_group = QGroupBox("粘贴 Cookie")
        paste_layout = QVBoxLayout(paste_group)
        self.cookie_text = QTextEdit()
        self.cookie_text.setPlaceholderText(
            "从浏览器开发者工具复制 Cookie 字符串（例如 ttwid=…; odin_tt=…）"
        )
        self.cookie_text.setMinimumHeight(180)
        paste_layout.addWidget(self.cookie_text)
        paste_layout.addWidget(
            self._hint("将写入 config/cookies.json，并同步更新配置文件中的 cookies 字段。")
        )

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        save_btn = QPushButton("保存 Cookie")
        save_btn.setObjectName("primaryButton")
        save_btn.setMinimumHeight(38)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_cookie)
        refresh_btn = QPushButton("刷新状态")
        refresh_btn.setMinimumHeight(38)
        refresh_btn.clicked.connect(self._refresh_cookie_status)
        btn_row.addWidget(save_btn, 1)
        btn_row.addWidget(refresh_btn, 0)

        root.addWidget(self.cookie_status_label)
        root.addWidget(fetch_group)
        root.addWidget(paste_group)
        root.addLayout(btn_row)
        root.addStretch(1)
        self.tabs.addTab(tab, "Cookie")

    def _build_youtube_tab(self) -> None:
        tab = QWidget()
        root = self._page_layout(tab)

        cred_group = QGroupBox("OAuth 凭证")
        cred_form = QFormLayout(cred_group)
        cred_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cred_form.setHorizontalSpacing(12)
        cred_form.setVerticalSpacing(10)

        self.youtube_secret_edit = QLineEdit("config/youtube_client_secret.json")
        secret_btn = QPushButton("浏览…")
        secret_btn.setFixedWidth(96)
        secret_btn.clicked.connect(self._pick_youtube_secret)
        secret_row = QHBoxLayout()
        secret_row.setSpacing(8)
        secret_row.addWidget(self.youtube_secret_edit, 1)
        secret_row.addWidget(secret_btn, 0)

        self.youtube_token_edit = QLineEdit("config/youtube_token.json")
        cred_form.addRow("Client secret", secret_row)
        cred_form.addRow("Token 文件", self.youtube_token_edit)

        upload_group = QGroupBox("上传选项")
        upload_form = QFormLayout(upload_group)
        upload_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        upload_form.setHorizontalSpacing(12)
        upload_form.setVerticalSpacing(10)

        self.youtube_privacy_combo = QComboBox()
        self.youtube_privacy_combo.addItems(["public", "private", "unlisted"])
        self.youtube_latest_spin = QSpinBox()
        self.youtube_latest_spin.setRange(0, 9999)
        self.youtube_latest_spin.setValue(1)
        self.youtube_latest_spin.setFixedWidth(120)
        self.youtube_dry_run_check = QCheckBox("Dry run（只预览，不调用上传 API）")
        self.youtube_dry_run_check.setChecked(True)

        upload_form.addRow("可见性", self.youtube_privacy_combo)
        upload_form.addRow("最近 N 条", self.youtube_latest_spin)
        upload_form.addRow("", self.youtube_dry_run_check)
        upload_form.addRow(
            "",
            self._hint("N 为 0 表示处理清单中的全部记录；数据来源为保存目录下的 download_manifest.jsonl。"),
        )
        upload_form.addRow(
            "",
            self._hint(
                "批量上传会消耗 YouTube Data API 配额；若失败多为 quotaExceeded，请减少 N 或次日再传。"
                " 上传结束后日志区会显示与命令行一致的分组说明。"
            ),
        )

        root.addWidget(cred_group)
        root.addWidget(upload_group)

        row = QHBoxLayout()
        row.setSpacing(10)
        auth_btn = QPushButton("YouTube 授权")
        auth_btn.setMinimumHeight(40)
        auth_btn.setCursor(Qt.PointingHandCursor)
        auth_btn.clicked.connect(self._start_youtube_auth)
        upload_btn = QPushButton("上传最近视频")
        upload_btn.setObjectName("primaryButton")
        upload_btn.setMinimumHeight(40)
        upload_btn.setCursor(Qt.PointingHandCursor)
        upload_btn.clicked.connect(self._start_youtube_upload)
        row.addWidget(auth_btn, 1)
        row.addWidget(upload_btn, 1)
        root.addLayout(row)
        root.addStretch(1)
        self.tabs.addTab(tab, "YouTube")

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        root = self._page_layout(tab)

        appearance_group = QGroupBox("界面")
        appearance_form = QFormLayout(appearance_group)
        appearance_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        appearance_form.setHorizontalSpacing(12)
        appearance_form.setVerticalSpacing(10)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.blockSignals(True)
        theme_index = self.theme_combo.findData(self._theme_mode)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.theme_combo.blockSignals(False)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        appearance_form.addRow("外观主题", self.theme_combo)
        root.addWidget(appearance_group)

        group = QGroupBox("基础设置")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.database_check = QCheckBox("启用下载历史数据库（SQLite）")
        self.database_check.setChecked(True)
        self.database_path_edit = QLineEdit("dy_downloader.db")
        self.proxy_edit = QLineEdit("")
        self.proxy_edit.setPlaceholderText("例如 http://127.0.0.1:7890，无则留空")
        self.quiet_logs_check = QCheckBox("下载时静默控制台日志（减少刷屏）")
        self.quiet_logs_check.setChecked(True)

        form.addRow("", self.database_check)
        form.addRow("数据库路径", self.database_path_edit)
        form.addRow("HTTP 代理", self.proxy_edit)
        form.addRow("", self.quiet_logs_check)
        form.addRow("", self._hint("代理与数据库等选项会随下载任务一并传给核心下载逻辑。"))

        root.addWidget(group)
        root.addStretch(1)
        self.tabs.addTab(tab, "设置")

    def _build_log_tab(self) -> None:
        tab = QWidget()
        root = self._page_layout(tab)

        group = QGroupBox("运行日志")
        inner = QVBoxLayout(group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(320)
        inner.addWidget(self.log_text)

        clear_btn = QPushButton("清空日志")
        clear_btn.setObjectName("quietButton")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self.log_text.clear)
        inner.addWidget(clear_btn, 0, Qt.AlignLeft)

        root.addWidget(group)
        self.tabs.addTab(tab, "日志")

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _apply_theme(self, mode: str, *, persist: bool = True, announce: bool = True) -> None:
        mode = mode if mode in ("light", "dark") else "light"
        self._theme_mode = mode
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet_for(mode))
        self.log_text.setStyleSheet(theme.log_area_stylesheet(mode))
        if persist:
            settings = QSettings()
            settings.setValue("appearance/theme", mode)
        self.theme_combo.blockSignals(True)
        idx = self.theme_combo.findData(mode)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)
        if announce:
            label = "深色" if mode == "dark" else "浅色"
            self._append_log(f"已切换为{label}主题")
        self._set_status("主题已更新" if announce else "就绪")

    def _on_theme_combo_changed(self) -> None:
        mode = self.theme_combo.currentData()
        if mode is None:
            return
        mode = str(mode)
        if mode == self._theme_mode:
            return
        self._apply_theme(mode, persist=True, announce=True)

    @staticmethod
    def _interpreter_for_cookie_subprocess() -> str:
        """PyInstaller 冻结后 sys.executable 是 GUI 可执行文件，不能用来跑 -m tools。"""
        if getattr(sys, "frozen", False):
            for name in ("python3", "python"):
                found = shutil.which(name)
                if found:
                    return found
            return "python3"
        return sys.executable

    def _cookie_fetcher_argv(self) -> list[str]:
        cfg = self.config_path_edit.text().strip() or "config.yml"
        return [
            self._interpreter_for_cookie_subprocess(),
            "-m",
            "tools.cookie_fetcher",
            "--config",
            cfg,
        ]

    def _copy_cookie_fetcher_command(self) -> None:
        command = shlex.join(self._cookie_fetcher_argv())
        QGuiApplication.clipboard().setText(command)
        self._append_log("已复制 cookie_fetcher 命令到剪贴板")
        self._set_status("已复制 cookie_fetcher 命令")

    @staticmethod
    def _escape_for_applescript_double_quoted(value: str) -> str:
        """AppleScript `do script "..."` 只认双引号字符串；需转义 \\ 与 "。"""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _open_cookie_fetcher_in_terminal_macos(self) -> None:
        if sys.platform != "darwin":
            self._message("当前系统请使用「复制终端命令」后在本机终端粘贴运行。")
            return
        cwd = str(Path.cwd().resolve())
        inner = " ".join(shlex.quote(part) for part in self._cookie_fetcher_argv())
        shell_cmd = f"cd {shlex.quote(cwd)} && {inner}"
        # 不能用 shlex.quote 拼进 AppleScript：单引号是 bash 语法，在 AppleScript 里会语法错误 (-2741)。
        escaped = self._escape_for_applescript_double_quoted(shell_cmd)
        script = f'tell application "Terminal" to do script "{escaped}"'
        completed = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, check=False
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            self._task_failed(detail or "无法通过 Terminal 启动 cookie_fetcher")
            return
        self._append_log("已在 Terminal 中启动 cookie_fetcher（按终端提示操作）")
        self._set_status("cookie_fetcher 已在 Terminal 启动")

    @staticmethod
    def _powershell_single_quoted(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _open_cookie_fetcher_windows(self, shell: str) -> None:
        """在新窗口中启动 cookie_fetcher：cmd 优先走 Windows Terminal（若已安装）。"""
        if sys.platform != "win32":
            return
        cwd = Path.cwd().resolve()
        argv = self._cookie_fetcher_argv()
        inner = " ".join(shlex.quote(part) for part in argv)
        try:
            if shell == "cmd":
                wt = shutil.which("wt.exe") or shutil.which("wt")
                if wt:
                    subprocess.Popen(
                        [wt, "-d", str(cwd), "cmd.exe", "/k", inner],
                        cwd=str(cwd),
                    )
                else:
                    subprocess.Popen(
                        [
                            "cmd.exe",
                            "/c",
                            "start",
                            "cookie_fetcher",
                            "/D",
                            str(cwd),
                            "cmd.exe",
                            "/k",
                            inner,
                        ],
                        cwd=str(cwd),
                    )
                self._append_log("已在 CMD 中启动 cookie_fetcher（按窗口提示操作）")
            elif shell == "powershell":
                pq = self._powershell_single_quoted
                tail = " ".join(pq(part) for part in argv[1:])
                ps_cmd = (
                    f"Set-Location -LiteralPath {pq(str(cwd))}; "
                    f"& {pq(str(argv[0]))} {tail}"
                )
                subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoExit",
                        "-NoLogo",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        ps_cmd,
                    ],
                    cwd=str(cwd),
                )
                self._append_log("已在 PowerShell 中启动 cookie_fetcher（按窗口提示操作）")
            else:
                self._message("未知的终端类型。")
                return
        except OSError as exc:
            self._task_failed(str(exc) or "无法启动 CMD / PowerShell")
            return
        self._set_status("cookie_fetcher 已在新终端启动")

    def _download_options(self) -> DownloadOptions:
        return DownloadOptions(
            config_path=self.config_path_edit.text().strip() or "config.yml",
            links_text=self.links_edit.toPlainText(),
            output_path=self.output_path_edit.text().strip() or "./Downloaded/",
            thread=self.thread_spin.value(),
            music=self.music_check.isChecked(),
            cover=self.cover_check.isChecked(),
            avatar=self.avatar_check.isChecked(),
            json_metadata=self.json_check.isChecked(),
            database=self.database_check.isChecked(),
            database_path=self.database_path_edit.text().strip() or "dy_downloader.db",
            proxy=self.proxy_edit.text().strip(),
            quiet_logs=self.quiet_logs_check.isChecked(),
        )

    def _youtube_options(self) -> YouTubeOptions:
        return YouTubeOptions(
            config_path=self.config_path_edit.text().strip() or "config.yml",
            client_secret_path=self.youtube_secret_edit.text().strip()
            or "config/youtube_client_secret.json",
            token_path=self.youtube_token_edit.text().strip() or "config/youtube_token.json",
            privacy_status=self.youtube_privacy_combo.currentText(),
            latest_count=self.youtube_latest_spin.value(),
            dry_run=self.youtube_dry_run_check.isChecked(),
        )

    def _start_download(self) -> None:
        if self._download_worker and self._download_worker.isRunning():
            self._message("下载任务正在运行")
            return
        self.start_download_btn.setEnabled(False)
        self._append_log("开始下载任务")
        self._set_status("下载任务进行中…")
        worker = DownloadWorker(self._download_options())
        worker.log_message.connect(self._append_log)
        worker.step_changed.connect(lambda step, detail: self._append_log(f"{step}: {detail}"))
        worker.item_advanced.connect(
            lambda status, detail: self._append_log(f"Item {status}: {detail}")
        )
        worker.finished_summary.connect(self._download_finished)
        worker.failed.connect(self._task_failed)
        worker.finished.connect(lambda: self.start_download_btn.setEnabled(True))
        self._download_worker = worker
        worker.start()

    def _download_finished(self, total: int, success: int, failed: int, skipped: int) -> None:
        self._append_log(
            f"下载完成：total={total}, success={success}, failed={failed}, skipped={skipped}"
        )
        self._set_status("就绪")

    def _start_youtube_auth(self) -> None:
        if self._youtube_auth_worker and self._youtube_auth_worker.isRunning():
            self._message("YouTube 授权正在运行")
            return
        self._append_log("开始 YouTube 授权")
        self._set_status("YouTube 授权进行中…")
        worker = YouTubeAuthWorker(self._youtube_options())
        worker.log_message.connect(self._append_log)
        worker.authorized.connect(self._on_youtube_authorized)
        worker.failed.connect(self._task_failed)
        self._youtube_auth_worker = worker
        worker.start()

    def _start_youtube_upload(self) -> None:
        if self._youtube_upload_worker and self._youtube_upload_worker.isRunning():
            self._message("YouTube 上传正在运行")
            return
        self._append_log("开始 YouTube 上传")
        self._set_status("YouTube 上传进行中…")
        worker = YouTubeUploadWorker(self._youtube_options())
        worker.log_message.connect(self._append_log)
        worker.upload_finished.connect(self._youtube_upload_finished)
        worker.failed.connect(self._task_failed)
        self._youtube_upload_worker = worker
        worker.start()

    def _youtube_upload_finished(
        self, success: int, dry_run: int, skipped: int, failed: int
    ) -> None:
        if failed and not success:
            self._set_status(f"YouTube 已结束（成功 {success}，失败 {failed}，详见日志）")
        elif failed:
            self._set_status(f"YouTube 已结束（成功 {success}，失败 {failed}，跳过 {skipped}）")
        else:
            self._set_status(
                f"YouTube 已结束（成功 {success}，预演 {dry_run}，跳过 {skipped}）"
            )

    def _on_youtube_authorized(self, path: str) -> None:
        self._append_log(f"YouTube token saved: {path}")
        self._set_status("就绪")

    def _save_cookie(self) -> None:
        try:
            cookies = save_cookie_string(
                self.cookie_text.toPlainText(),
                config_path=self.config_path_edit.text().strip() or "config.yml",
            )
        except Exception as exc:
            self._task_failed(str(exc))
            return
        self._append_log(f"已保存 {len(cookies)} 个 Cookie")
        self._refresh_cookie_status()

    def _refresh_cookie_status(self) -> None:
        status = summarize_cookie_status(self.config_path_edit.text().strip() or "config.yml")
        missing = ", ".join(status["missing"]) if status["missing"] else "无"
        self.cookie_status_label.setText(
            "Cookie 概览\n"
            f"数量：{status['count']}　"
            f"缺失关键项：{missing}　"
            f"msToken：{'有' if status['has_ms_token'] else '无'}"
        )

    def _pick_config_path(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择配置文件", str(Path.cwd()), "YAML (*.yml *.yaml);;All files (*)"
        )
        if path:
            self.config_path_edit.setText(path)
            self._refresh_cookie_status()

    def _pick_output_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_path_edit.text())
        if path:
            self.output_path_edit.setText(path)

    def _pick_youtube_secret(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择 YouTube client_secret.json",
            str(Path.cwd()),
            "JSON (*.json);;All files (*)",
        )
        if path:
            self.youtube_secret_edit.setText(path)

    def _task_failed(self, message: str) -> None:
        self._append_log(f"错误：{message}")
        self._set_status("任务出错，请查看日志")
        self._message(message, title="任务失败")

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{stamp}] {message}")

    def _message(self, message: str, title: str = "提示") -> None:
        QMessageBox.information(self, title, message)
