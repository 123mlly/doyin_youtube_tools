from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class GuiProgressAdapter(QObject):
    step_changed = Signal(str, str)
    item_total_changed = Signal(int, str)
    item_advanced = Signal(str, str)

    def advance_step(self, step: str, detail: str = "") -> None:
        self.step_changed.emit(step, detail)

    def update_step(self, step: str, detail: str = "") -> None:
        self.step_changed.emit(step, detail)

    def set_item_total(self, total: int, detail: str = "") -> None:
        self.item_total_changed.emit(int(total), detail)

    def advance_item(self, status: str, detail: str = "") -> None:
        self.item_advanced.emit(status, detail)
