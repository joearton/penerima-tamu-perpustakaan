import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def qt_widgets(qapp):
    """Daftar widget milik tes; dihapus eksplisit saat tes selesai.

    Widget PySide6 yang dibiarkan hidup sampai QApplication dimusnahkan di akhir proses
    (atau dihapus garbage collector di waktu acak) bisa memicu segfault.
    """
    from PySide6.QtCore import QEvent

    widgets = []
    yield widgets.append
    for widget in reversed(widgets):
        widget.close()
        widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()
