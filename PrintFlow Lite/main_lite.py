"""
Podbase Mimaki PrintFlow Lite
Entry Point
"""

import sys
import os

def get_base_dir():
    """Grąžina tikrąjį programos aplanką (tiek paleidus per Python, tiek per sukompiliuotą .exe)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

base_dir = get_base_dir()
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindowLite


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PrintFlow Lite")
    app.setOrganizationName("Podbase")

    config_file = os.path.join(base_dir, "config.json")
    window = MainWindowLite(config_path=config_file)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
