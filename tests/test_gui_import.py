import importlib

import pytest


def test_gui_main_import_when_pyside6_available():
    pytest.importorskip("PySide6")

    module = importlib.import_module("gui.main")

    assert callable(module.main)
