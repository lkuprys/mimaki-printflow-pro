import pytest


@pytest.fixture
def tmp(tmp_path):
    return str(tmp_path)


def pytest_sessionfinish(session, exitstatus):
    """Qt langai sunaikinami, kol QApplication dar gyvas, o jų fono gijos (serverio patikra)
    pirma sulaukiamos. Kitaip Windows'e Python kartais nulūžta uždarant interpretatorių –
    visi testai praėję, bet procesas grąžina klaidos kodą."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QThread
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        for t in w.findChildren(QThread):
            if t.isRunning():
                t.wait(15000)
        w.hide()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
