"""
Podbase Mimaki PrintFlow Lite
Entry Point
"""

import sys
import os
import logging
import traceback
from logging.handlers import RotatingFileHandler

# PyInstaller --windowed: sys.stdout / sys.stderr yra None – bet koks print() ar
# bibliotekos įspėjimas (pvz. PyMuPDF) kitaip sukeltų išimtį.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def get_base_dir():
    """Grąžina tikrąjį programos aplanką (tiek paleidus per Python, tiek per sukompiliuotą .exe)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


base_dir = get_base_dir()
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import QLockFile, QDir  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from ui.main_window import MainWindowLite, resolve_writable_config_path  # noqa: E402
from ui.theme import resource_path  # noqa: E402


def setup_file_logging(data_dir: str):
    logger = logging.getLogger("printflow")
    logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(
            os.path.join(data_dir, "printflow_lite.log"),
            maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except Exception:
        logger.addHandler(logging.NullHandler())


def install_excepthook():
    """Zero Silent Failures: neapdorota išimtis UI gijoje užrašoma į žurnalą ir parodoma operatoriui."""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.getLogger("printflow").error("Neapdorota klaida:\n%s", text)
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "PrintFlow Lite – klaida",
                                     f"Įvyko netikėta klaida (programa veikia toliau):\n\n{exc}")
        except Exception:
            pass
    sys.excepthook = hook


def main():
    if os.name == "nt":
        # Atskira užduočių juostos grupė ir Podbase ikona (ne Python ikona)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Podbase.PrintFlowLite")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("PrintFlow Lite")
    app.setOrganizationName("Podbase")
    app.setWindowIcon(QIcon(resource_path("assets", "podbase.ico")))

    config_file = resolve_writable_config_path(os.path.join(base_dir, "config.json"))
    data_dir = os.path.dirname(config_file)
    setup_file_logging(data_dir)
    install_excepthook()

    # Vienas egzempliorius: du vienu metu veikiantys PrintFlow keltų tuos pačius užsakymus du kartus
    lock = QLockFile(QDir(data_dir).filePath("printflow_lite.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "PrintFlow Lite",
                            "PrintFlow Lite jau paleista šiame kompiuteryje.\n"
                            "Antras egzempliorius nepaleidžiamas, kad užsakymai nebūtų keliami dukart.")
        return 1
    app._instance_lock = lock  # atnaujintojas atrakina prieš os._exit

    window = MainWindowLite(config_path=config_file)
    window.show()

    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    sys.exit(main())
