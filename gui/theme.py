"""Qt stylesheet and small visual constants for the desktop GUI."""

from __future__ import annotations

LOG_MONOSPACE_FAMILY = "Menlo, Monaco, Consolas, 'Courier New', monospace"

APP_STYLESHEET_LIGHT = """
QWidget {
    color: #0f172a;
    font-size: 13px;
}

QMainWindow, QTabWidget::pane {
    background-color: #f1f5f9;
}

QTabWidget::pane {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    top: -1px;
    padding: 8px;
    margin-top: 4px;
}

QTabBar::tab {
    background-color: #e2e8f0;
    color: #475569;
    border: 1px solid #cbd5e1;
    border-bottom-color: #cbd5e1;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    min-width: 88px;
    padding: 8px 14px;
    margin-right: 4px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #0f172a;
    font-weight: 600;
    border-bottom-color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background-color: #f8fafc;
    color: #334155;
}

QGroupBox {
    font-weight: 600;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 12px 8px 12px;
    background-color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #334155;
}

QLabel#hintLabel {
    color: #64748b;
    font-size: 12px;
}

QLabel#statusPill {
    background-color: #eff6ff;
    color: #1e40af;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 10px 12px;
}

QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f0;
    color: #475569;
}

QLineEdit, QSpinBox, QComboBox {
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 8px;
    background-color: #ffffff;
    min-height: 20px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3b82f6;
}

QTextEdit {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px;
    background-color: #ffffff;
}

QTextEdit:focus {
    border-color: #3b82f6;
}

QCheckBox {
    spacing: 8px;
}

QPushButton {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 14px;
    background-color: #ffffff;
    color: #334155;
    min-height: 22px;
}

QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background-color: #f1f5f9;
}

QPushButton:disabled {
    color: #94a3b8;
    background-color: #f1f5f9;
    border-color: #e2e8f0;
}

QPushButton#primaryButton {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: #1d4ed8;
    border-color: #1e40af;
}

QPushButton#primaryButton:pressed {
    background-color: #1e40af;
}

QPushButton#primaryButton:disabled {
    background-color: #93c5fd;
    border-color: #93c5fd;
    color: #f1f5f9;
}

QPushButton#quietButton {
    background-color: transparent;
    border-color: transparent;
    color: #2563eb;
    font-weight: 500;
}

QPushButton#quietButton:hover {
    background-color: #eff6ff;
    border-color: #bfdbfe;
}

QScrollBar:vertical {
    width: 10px;
    margin: 0;
    background: #f1f5f9;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
"""

APP_STYLESHEET_DARK = """
QWidget {
    color: #e2e8f0;
    font-size: 13px;
}

QMainWindow, QTabWidget::pane {
    background-color: #0b1220;
}

QTabWidget::pane {
    border: 1px solid #1f2937;
    border-radius: 8px;
    top: -1px;
    padding: 8px;
    margin-top: 4px;
}

QTabBar::tab {
    background-color: #111827;
    color: #94a3b8;
    border: 1px solid #1f2937;
    border-bottom-color: #1f2937;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    min-width: 88px;
    padding: 8px 14px;
    margin-right: 4px;
}

QTabBar::tab:selected {
    background-color: #0f172a;
    color: #f8fafc;
    font-weight: 600;
    border-bottom-color: #0f172a;
}

QTabBar::tab:hover:!selected {
    background-color: #1e293b;
    color: #cbd5e1;
}

QGroupBox {
    font-weight: 600;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 12px 8px 12px;
    background-color: #0f172a;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #94a3b8;
}

QLabel#hintLabel {
    color: #94a3b8;
    font-size: 12px;
}

QLabel#statusPill {
    background-color: #172554;
    color: #bfdbfe;
    border: 1px solid #1d4ed8;
    border-radius: 8px;
    padding: 10px 12px;
}

QStatusBar {
    background-color: #0f172a;
    border-top: 1px solid #1f2937;
    color: #94a3b8;
}

QLineEdit, QSpinBox, QComboBox {
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
    background-color: #020617;
    color: #e2e8f0;
    min-height: 20px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3b82f6;
}

QTextEdit {
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px;
    background-color: #020617;
    color: #e2e8f0;
}

QTextEdit:focus {
    border-color: #3b82f6;
}

QCheckBox {
    spacing: 8px;
}

QPushButton {
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 14px;
    background-color: #111827;
    color: #e2e8f0;
    min-height: 22px;
}

QPushButton:hover {
    background-color: #1e293b;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton:disabled {
    color: #64748b;
    background-color: #0f172a;
    border-color: #1f2937;
}

QPushButton#primaryButton {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: #1d4ed8;
    border-color: #1e40af;
}

QPushButton#primaryButton:pressed {
    background-color: #1e40af;
}

QPushButton#primaryButton:disabled {
    background-color: #1e3a8a;
    border-color: #1e3a8a;
    color: #cbd5e1;
}

QPushButton#quietButton {
    background-color: transparent;
    border-color: transparent;
    color: #93c5fd;
    font-weight: 500;
}

QPushButton#quietButton:hover {
    background-color: #172554;
    border-color: #1d4ed8;
}

QScrollBar:vertical {
    width: 10px;
    margin: 0;
    background: #0b1220;
}

QScrollBar::handle:vertical {
    background: #334155;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}
"""


def stylesheet_for(mode: str) -> str:
    if mode == "dark":
        return APP_STYLESHEET_DARK
    return APP_STYLESHEET_LIGHT


def log_area_stylesheet(mode: str) -> str:
    if mode == "dark":
        return (
            f"font-family: {LOG_MONOSPACE_FAMILY}; font-size: 12px; "
            "background-color: #020617; color: #e2e8f0; border: 1px solid #334155;"
        )
    return (
        f"font-family: {LOG_MONOSPACE_FAMILY}; font-size: 12px; "
        "background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1;"
    )


# Backwards compatibility for imports expecting APP_STYLESHEET
APP_STYLESHEET = APP_STYLESHEET_LIGHT
