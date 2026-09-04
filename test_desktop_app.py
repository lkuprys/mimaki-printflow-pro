import os
import sys
import json
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Run offscreen for headless CI/CD
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from printflow.ui.controllers import PrintFlowController
from printflow.core.prepress import extract_pdf_data, generate_preview_files


def test_qml_interface_loads():
    """Verify PySide6 and QML engine load without any UI syntax errors."""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    QQuickStyle.setStyle("Basic")
    
    controller = PrintFlowController()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("printflowController", controller)
    
    qml_file = os.path.abspath(os.path.join("printflow", "ui", "qml", "Main.qml"))
    assert os.path.exists(qml_file), f"QML file missing: {qml_file}"
    
    engine.load(qml_file)
    roots = engine.rootObjects()
    assert len(roots) > 0, "QML Engine failed to create root objects"
    print("  [PASS] test_qml_interface_loads")


def test_controller_configuration():
    """Verify loading and reading configuration."""
    controller = PrintFlowController()
    cfg = controller._read_config()
    assert "products" in cfg, "Config missing products key"
    assert "inbox_folder" in cfg, "Config missing inbox_folder key"
    assert len(cfg["products"]) > 0, "Config has no products"
    print(f"  [PASS] test_controller_configuration ({len(cfg['products'])} products)")


def test_file_inspection_and_previews():
    """Verify fast PDF extraction and disk preview file generation."""
    pdf_path = os.path.abspath("Untitled-1.pdf")
    assert os.path.exists(pdf_path), f"Test PDF missing: {pdf_path}"
    
    controller = PrintFlowController()
    t0 = time.time()
    w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask = extract_pdf_data(pdf_path)
    previews = generate_preview_files(thumb_rgb, thumb_mask, controller.temp_dir, choke_px=1)
    dur = time.time() - t0
    
    assert "composite" in previews
    assert "cmyk" in previews
    assert "white" in previews
    assert "primer" in previews
    
    # Check that disk files actually exist
    for key in ["composite", "cmyk", "white", "primer"]:
        raw_path = previews[key].replace("file:///", "")
        assert os.path.exists(raw_path), f"Preview file missing: {raw_path}"
        
    print(f"  [PASS] test_file_inspection_and_previews ({dur*1000:.1f} ms)")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING AUTOMATED DESKTOP APP TESTS")
    print("=" * 60)
    test_controller_configuration()
    test_file_inspection_and_previews()
    test_qml_interface_loads()
    print("=" * 60)
    print("ALL DESKTOP TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
