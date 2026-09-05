"""
Podbase Mimaki PrintFlow Lite
Entry Point
"""

import sys
import os

# Užtikriname, kad moduliai būtų randami nepriklausomai nuo paleidimo vietos
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindowLite


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PrintFlow Lite")
    app.setOrganizationName("Podbase")

    config_file = os.path.join(current_dir, "config.json")
    window = MainWindowLite(config_path=config_file)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
