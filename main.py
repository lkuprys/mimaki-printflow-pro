import os
import sys

# Ensure project root is in sys.path
if getattr(sys, "frozen", False):
    project_root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    project_root = os.path.dirname(os.path.abspath(__file__))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Qt High DPI
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from printflow.ui.controllers import PrintFlowController


def main():
    app = QGuiApplication(sys.argv)
    app.setOrganizationName("MimakiPrintFlow")
    app.setApplicationName("PrintFlow PRO")

    # Dark modern styling for controls
    QQuickStyle.setStyle("Basic")

    controller = PrintFlowController()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("printflowController", controller)

    qml_file = os.path.join(project_root, "printflow", "ui", "qml", "Main.qml")
    engine.load(qml_file)

    if not engine.rootObjects():
        print("Klaida: Nepavyko užkrauti QML sąsajos!")
        sys.exit(-1)

    print("=" * 60)
    print("   MIMAKI PRINTFLOW PRO - NATIVE DESKTOP STARTED")
    print("   Engine: PySide6 + QML | Zero-Browser Architecture")
    print("=" * 60)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
