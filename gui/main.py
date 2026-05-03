from __future__ import annotations

import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from gui import theme
from gui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Douyin Downloader")
    app.setOrganizationName("douyin-downloader")
    app.setStyle("Fusion")

    base_font = QFont(app.font())
    if base_font.pointSizeF() > 0 and base_font.pointSizeF() < 11:
        base_font.setPointSize(11)
    app.setFont(base_font)

    settings = QSettings()
    theme_mode = str(settings.value("appearance/theme", "light") or "light")
    if theme_mode not in ("light", "dark"):
        theme_mode = "light"
    app.setStyleSheet(theme.stylesheet_for(theme_mode))

    window = MainWindow(initial_theme=theme_mode)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
