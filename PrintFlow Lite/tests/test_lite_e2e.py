"""
PrintFlow Lite – end-to-end testai
==================================
Paleidimas (iš 'PrintFlow Lite' aplanko):

    python -m pytest tests -q
    # arba be pytest:
    python tests/test_lite_e2e.py

Su realiais gamybiniais PDF (pvz. E:\\Projektai\\TEST\\INBOX_PRINT_FILES):

    set PRINTFLOW_TEST_INBOX=E:\\Projektai\\TEST\\INBOX_PRINT_FILES
    python tests/test_lite_e2e.py

Testai nenaudoja tikrų Mimaki hotfolderių – viskas vyksta laikinuose aplankuose.
"""

import io
import os
import sys
import json
import time
import glob
import shutil
import tempfile
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from core import scanner_lite  # noqa: E402
from core.prepress_lite import export_production_plates, read_page_geometry, PrepressError  # noqa: E402
from core.registry_lite import JobRegistryLite  # noqa: E402
from core.router_lite import HotFolderRouterLite  # noqa: E402
from core.scanner_lite import scan_server_directory, match_product, path_exists_with_timeout  # noqa: E402

TODAY = datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Testinių PDF generavimas
# ---------------------------------------------------------------------------
def make_smask_pdf(path, w_pt=216, h_pt=432, w_px=900, h_px=1800):
    """Podbase standartas: vienas paveikslėlis per visą lapą su SMask (permatomumu)."""
    rgb = np.zeros((h_px, w_px, 3), np.uint8)
    rgb[..., 0] = 200
    a = np.zeros((h_px, w_px), np.uint8)
    a[h_px // 4:3 * h_px // 4, w_px // 4:3 * w_px // 4] = 255
    buf = io.BytesIO()
    Image.fromarray(np.dstack([rgb, a]), "RGBA").save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def make_rotated_offset_pdf(path):
    """Sunkiausias geometrijos atvejis: /Rotate 90, MediaBox ne ties 0,0, atskiri Crop/TrimBox."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(20, 20, 120, 80), color=(1, 0, 0), fill=(1, 0, 0))
    doc.xref_set_key(page.xref, "MediaBox", "[10 10 310 210]")
    doc.xref_set_key(page.xref, "CropBox", "[15 15 305 205]")
    doc.xref_set_key(page.xref, "TrimBox", "[20 20 300 200]")
    doc.xref_set_key(page.xref, "Rotate", "90")
    doc.save(path)
    doc.close()


def make_vector_pdf(path, pages=1):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=100, height=100).draw_circle((50, 50), 30, fill=(0, 0, 1))
    doc.save(path)
    doc.close()


def _set_old_mtime(path, age_sec=600):
    t = time.time() - age_sec
    os.utime(path, (t, t))


# ---------------------------------------------------------------------------
# Pagalbinės patikros
# ---------------------------------------------------------------------------
def assert_plates_registered(plates, dpi=300):
    """Visos plokštės: identiški langeliai + /Rotate, kaukės efektyvus DPI = dpi."""
    geos = {}
    for layer, path in plates.items():
        doc = pymupdf.open(path)
        assert doc.page_count == 1, f"{layer}: {doc.page_count} psl."
        geos[layer] = read_page_geometry(doc, 0)
        if layer != "CMYK":
            page = doc[0]
            info = page.get_image_info()[0]
            unrot = page.rect * page.derotation_matrix
            unrot = pymupdf.Rect(unrot).normalize()
            assert abs(info["width"] - round(unrot.width / 72 * dpi)) <= 1, (layer, info["width"])
            assert abs(info["height"] - round(unrot.height / 72 * dpi)) <= 1, (layer, info["height"])
        doc.close()
    ref = next(iter(geos.values()))
    for layer, g in geos.items():
        assert g == ref, f"{layer} geometrija {g} != {ref}"


def pixel_mismatch(cmyk_path, mask_path, alpha_threshold=10):
    """Rastruoja CMYK (alfa) ir kaukės plokštę su /Rotate ir grąžina nesutampančių px skaičių."""
    m = pymupdf.Matrix(300 / 72, 300 / 72)
    c = pymupdf.open(cmyk_path)[0].get_pixmap(matrix=m, alpha=True)
    p = pymupdf.open(mask_path)[0].get_pixmap(matrix=m, colorspace=pymupdf.csGRAY)
    assert (c.width, c.height) == (p.width, p.height), "plokščių rastro dydžiai nesutampa"
    a = np.frombuffer(c.samples, np.uint8).reshape(c.height, c.width, 4)[..., 3] > alpha_threshold
    g = np.frombuffer(p.samples, np.uint8).reshape(p.height, p.width) < 128
    return int((a != g).sum()), int(a.sum())


# ---------------------------------------------------------------------------
# 1. Prepress: DPI ir geometrija
# ---------------------------------------------------------------------------
def test_prepress_smask_dpi_normalized(tmp):
    src = os.path.join(tmp, "RH-smask.pdf")
    make_smask_pdf(src, w_px=1800, h_px=3600)  # 600 DPI SMask ➔ turi tapti 300 DPI
    plates = export_production_plates(src, "job", os.path.join(tmp, "out"), ["Primer", "White", "CMYK"], 1, 0)
    assert set(plates) == {"Primer", "White", "CMYK"}
    assert_plates_registered(plates)
    bad, total = pixel_mismatch(plates["CMYK"], plates["Primer"], alpha_threshold=128)
    assert bad == 0, f"SMask registracija: {bad} px nesutampa iš {total}"


def test_prepress_rotated_offset_geometry(tmp):
    src = os.path.join(tmp, "CC-rot.pdf")
    make_rotated_offset_pdf(src)
    plates = export_production_plates(src, "rot", os.path.join(tmp, "out"), ["Primer", "White", "CMYK"], 1, 0)
    assert_plates_registered(plates)
    doc = pymupdf.open(plates["White"])
    geo = read_page_geometry(doc, 0)
    assert geo["Rotate"] == 90 and geo["MediaBox"] == [10, 10, 310, 210] and geo["TrimBox"] == [20, 20, 300, 200]
    bad, total = pixel_mismatch(plates["CMYK"], plates["Primer"])
    assert bad == 0, f"Pasukto puslapio registracija: {bad} px nesutampa iš {total}"


def test_prepress_multipage_and_choke(tmp):
    src = os.path.join(tmp, "MW-multi.pdf")
    make_vector_pdf(src, pages=3)
    warns = []
    plates = export_production_plates(src, "mp", os.path.join(tmp, "out"), ["White", "CMYK"], 3, 0, warnings_out=warns)
    assert any("3 puslap" in w for w in warns)
    assert pymupdf.open(plates["CMYK"]).page_count == 1
    assert_plates_registered(plates)
    # Choke 3px: balta turi būti mažesnė už CMYK
    bad, total = pixel_mismatch(plates["CMYK"], plates["White"])
    assert bad > 0


def test_prepress_broken_pdf(tmp):
    src = os.path.join(tmp, "broken.pdf")
    with open(src, "wb") as f:
        f.write(b"%PDF-1.4\n nepilnas")
    try:
        export_production_plates(src, "b", os.path.join(tmp, "out"), ["White", "CMYK"])
        raise AssertionError("turėjo mesti PrepressError")
    except PrepressError:
        pass
    assert not glob.glob(os.path.join(tmp, "out", "*.part"))


def test_prepress_real_inbox_files(tmp):
    """Realūs PDF iš PRINTFLOW_TEST_INBOX (arba repo Untitled-1.pdf)."""
    inbox = os.environ.get("PRINTFLOW_TEST_INBOX", "")
    files = sorted(glob.glob(os.path.join(inbox, "**", "*.pdf"), recursive=True))[:20] if inbox else []
    repo_sample = os.path.join(os.path.dirname(APP_DIR), "Untitled-1.pdf")
    if not files and os.path.exists(repo_sample):
        files = [repo_sample]
    assert files, "nėra realių PDF testui"
    for i, f in enumerate(files):
        t0 = time.time()
        plates = export_production_plates(f, f"real{i}", os.path.join(tmp, "real"), ["Primer", "White", "CMYK"], 1, 0)
        assert_plates_registered(plates)
        print(f"      ✓ {os.path.basename(f)} ➔ {len(plates)} plokštės per {time.time() - t0:.2f}s")


# ---------------------------------------------------------------------------
# 2. Skeneris
# ---------------------------------------------------------------------------
PRODUCTS = None


def _products():
    global PRODUCTS
    if PRODUCTS is None:
        with open(os.path.join(APP_DIR, "config.json"), encoding="utf-8") as f:
            PRODUCTS = json.load(f)["products"]
    return PRODUCTS


def test_match_product_specificity_and_acronyms(tmp):
    P = _products()
    assert match_product("x.pdf", "/s/2026-01-01/1/clear-cases-v1/x.pdf", P, "/s")["id"] == "clear_cases_v1"
    assert match_product("x.pdf", "/s/clear-cases-v0/x.pdf", P, "/s")["id"] == "clear_cases_v0"
    assert match_product("x.pdf", "/s/clear-cases-magsafe-v2/x.pdf", P, "/s")["id"] == "clear_cases_v2"
    assert match_product("RH_123.pdf", "/s/RH_123.pdf", P, "/s")["id"] == "magsafe_ring_holders"
    # Akronimas failo pavadinimo gale / po tarpo (senas regex turėjo \x08 vietoj \b ir jų neatpažindavo)
    assert match_product("order_RH.pdf", "/s/order_RH.pdf", P, "/s")["id"] == "magsafe_ring_holders"
    assert match_product("case CC.pdf", "/s/case CC.pdf", P, "/s")["id"] == "clear_cases_v2"
    # Trumpi akronimai NEBETINKA žodžio viduje
    assert match_product("shirt.pdf", "/s/shirt.pdf", P, "/s") is None
    assert match_product("accessory.pdf", "/s/accessory.pdf", P, "/s") is None


def test_scanner_date_filter_and_unstable(tmp):
    root = os.path.join(tmp, "srv")
    old = os.path.join(root, "2020-01-01", "1", "magnetic-wallet")
    new = os.path.join(root, TODAY, "105", "magnetic-wallet")
    os.makedirs(old)
    os.makedirs(new)
    for d, n in ((old, "a.pdf"), (new, "b.pdf"), (new, "c_Plate_1_CMYK.pdf")):
        make_vector_pdf(os.path.join(d, n))
        _set_old_mtime(os.path.join(d, n))
    make_vector_pdf(os.path.join(new, "fresh.pdf"))  # dar „kopijuojamas“
    unstable, errs = [], []
    jobs = scan_server_directory(root, _products(), "today_only", TODAY, min_file_age_sec=5,
                                 errors=errs, skipped_unstable=unstable)
    assert [j["filename"] for j in jobs] == ["b.pdf"], jobs
    assert jobs[0]["bid"] == "105" and jobs[0]["order_date"] == TODAY
    assert len(unstable) == 1 and not errs


def test_scanner_unreachable_and_timeout(tmp):
    errs = []
    assert scan_server_directory(os.path.join(tmp, "nera"), _products(), errors=errs) == []
    assert errs
    real_isdir = os.path.isdir

    def slow_isdir(p):
        time.sleep(3)
        return real_isdir(p)

    scanner_lite.os.path.isdir = slow_isdir
    try:
        t0 = time.time()
        assert path_exists_with_timeout(tmp, timeout_sec=0.5) is None
        assert time.time() - t0 < 1.5
    finally:
        scanner_lite.os.path.isdir = real_isdir


# ---------------------------------------------------------------------------
# 3. Registry
# ---------------------------------------------------------------------------
def test_registry_threadsafe_atomic(tmp):
    path = os.path.join(tmp, "jobs_registry.json")
    reg = JobRegistryLite(path)

    def worker(n):
        for i in range(25):
            reg.register_or_update(f"job_{n}_{i}", {"filepath": f"/x/{n}_{i}.pdf", "status": "dispatched"})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(path, encoding="utf-8") as f:
        assert len(json.load(f)) == 200
    assert reg.is_file_processed("/kitur/3_7.pdf")  # dublikato apsauga pagal vardą
    assert not glob.glob(path + ".*.tmp")


def test_registry_corruption_recovery(tmp):
    path = os.path.join(tmp, "jobs_registry.json")
    reg = JobRegistryLite(path)
    reg.register_or_update("a", {"filepath": "/x/a.pdf", "status": "dispatched"})
    reg.register_or_update("b", {"filepath": "/x/b.pdf", "status": "dispatched"})  # sukuria .bak su 'a'
    with open(path, "w") as f:
        f.write('{"pusiau": ')
    reg2 = JobRegistryLite(path)
    assert reg2.is_file_processed("/x/a.pdf"), "atmintis turėjo būti atkurta iš .bak"
    assert reg2.load_warnings and glob.glob(path + ".corrupt-*")


def test_registry_retry_policy(tmp):
    reg = JobRegistryLite(os.path.join(tmp, "r.json"))
    for expected in ("error", "error", "failed"):
        assert reg.record_failure("j", {"filepath": "/x/j.pdf"}, "klaida", 3) == expected
    assert reg.is_file_processed("/x/j.pdf")
    reg.reset_job("j")
    assert not reg.is_file_processed("/x/j.pdf")
    reg.register_or_update("k", {"filepath": "/x/k.pdf", "status": "processing"})
    assert JobRegistryLite(reg.registry_file).mark_interrupted() == ["k"]


# ---------------------------------------------------------------------------
# 4. Router
# ---------------------------------------------------------------------------
def test_router_atomic_order_and_missing_folder(tmp):
    hf = {l: os.path.join(tmp, "hot", l) for l in ("Primer", "White", "CMYK")}
    for d in hf.values():
        os.makedirs(d)
    plates = {}
    for l in hf:
        p = os.path.join(tmp, f"{l}.pdf")
        make_vector_pdf(p)
        plates[l] = p
    prod = {"hotfolders": dict(hf), "dispatch_order": ["Primer", "White", "CMYK"]}
    order_before = list(prod["dispatch_order"])
    r = HotFolderRouterLite(0.05)
    sent = r.dispatch_plates("j", plates, prod, inter_layer_delay_sec=0.05)
    assert [d["layer"] for d in sent] == ["Primer", "White", "CMYK"]
    assert prod["dispatch_order"] == order_before, "konfigūracijos sąrašas neturi būti keičiamas"
    assert not glob.glob(os.path.join(tmp, "hot", "*", "*.tmp"))
    # Neegzistuojantis hotfolderis NEKURIAMAS (tylus failų „pametimas“)
    prod["hotfolders"]["CMYK"] = os.path.join(tmp, "hot", "RH COLOUR_typo")
    sent = r.dispatch_plates("j2", plates, prod, inter_layer_delay_sec=0)
    assert [d["layer"] for d in sent] == ["Primer", "White"]
    assert not os.path.exists(prod["hotfolders"]["CMYK"])


# ---------------------------------------------------------------------------
# 5. Pilnas E2E per WorkerScanProcess (Qt gija) + UI
# ---------------------------------------------------------------------------
def _make_env(tmp, hot_missing=False):
    from ui import main_window as mw
    srv = os.path.join(tmp, "srv")
    hot = {l: os.path.join(tmp, "hot", l) for l in ("CMYK", "White", "Primer")}
    for l, d in hot.items():
        if not (hot_missing and l == "CMYK"):
            os.makedirs(d, exist_ok=True)
    d1 = os.path.join(srv, TODAY, "105", "magsafe-ring-holders")
    d2 = os.path.join(srv, TODAY, "106", "magnetic-wallet")
    os.makedirs(d1)
    os.makedirs(d2)
    make_smask_pdf(os.path.join(d1, "order-pid-77.pdf"))
    make_vector_pdf(os.path.join(d2, "wallet-1.pdf"))
    for f in glob.glob(os.path.join(srv, "**", "*.pdf"), recursive=True):
        _set_old_mtime(f)
    cfg = json.loads(json.dumps(mw.DEFAULT_CONFIG))
    cfg.update({"server_inbox_folder": srv, "local_fallback_inbox": "", "server_timeout_sec": 3,
                "local_storage_folder": os.path.join(tmp, "storage"), "inter_layer_delay_sec": 0.05})
    for p in cfg["products"]:
        p["hotfolders"] = {l: (hot[l] if p["hotfolders"].get(l) else "") for l in hot}
    cfg_path = os.path.join(tmp, "app", "config.json")
    os.makedirs(os.path.dirname(cfg_path))
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return cfg_path, hot


def _run_worker(win):
    logs = []
    win.start_scan()
    w = win.worker
    w.log_signal.connect(logs.append)
    from PySide6.QtWidgets import QApplication
    t0 = time.time()
    while w.isRunning() and time.time() - t0 < 60:
        QApplication.processEvents()  # GUI ciklas lieka gyvas, kol gija dirba
        time.sleep(0.01)
    QApplication.processEvents()
    assert not w.isRunning(), "worker užstrigo"
    return logs


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_e2e_worker_full_pipeline(tmp):
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    assert not win.auto_timer.isActive(), "auto_scan turi būti išjungtas starto metu"
    _run_worker(win)
    jobs = {j["job_id"]: j for j in win.registry.get_all_jobs()}
    assert jobs["order-pid-77"]["status"] == "dispatched", jobs["order-pid-77"]
    assert jobs["order-pid-77"]["dispatched_plates"] == ["Primer", "White", "CMYK"]
    assert jobs["order-pid-77"]["bid"] == "105" and jobs["order-pid-77"]["pid"] == "77"
    assert jobs["wallet-1"]["dispatched_plates"] == ["White", "CMYK"]
    assert sorted(os.listdir(hot["CMYK"])) == ["order-pid-77_CMYK.pdf", "wallet-1_CMYK.pdf"]
    assert not glob.glob(os.path.join(tmp, "storage", "**", "*.part"), recursive=True)
    # Antras skenavimas – jokių dublikatų
    for d in hot.values():
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    _run_worker(win)
    assert all(not os.listdir(d) for d in hot.values()), "užsakymai įkelti pakartotinai!"
    win.close()


def test_e2e_network_drop_during_download(tmp):
    _app()
    from ui import main_window as mw
    cfg_path, hot = _make_env(tmp)
    win = mw.MainWindowLite(config_path=cfg_path)
    real_copy = mw.shutil.copyfile

    def broken_copy(src, dst, *a, **k):
        if dst.endswith(".part"):
            with open(dst, "wb") as f:
                f.write(b"%PDF-1.4 dalis")
            raise OSError(64, "The specified network name is no longer available")
        return real_copy(src, dst, *a, **k)

    mw.shutil.copyfile = broken_copy
    try:
        logs = _run_worker(win)
    finally:
        mw.shutil.copyfile = real_copy
    assert not glob.glob(os.path.join(tmp, "storage", "**", "*.p*"), recursive=True), "liko .part/.pdf šiukšlės"
    jobs = {j["job_id"]: j for j in win.registry.get_all_jobs()}
    assert jobs["order-pid-77"]["status"] == "error" and jobs["order-pid-77"]["attempts"] == 1
    assert any("network name" in l for l in logs)
    # Tinklas grįžo – kitas ciklas sėkmingas
    _run_worker(win)
    assert win.registry.get_job("order-pid-77")["status"] == "dispatched"
    win.close()


def test_e2e_server_unreachable_and_hotfolder_missing(tmp):
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp, hot_missing=True)
    win = MainWindowLite(config_path=cfg_path)
    win.txt_server_path.setText(os.path.join(tmp, "atjungtas_serveris"))
    logs = _run_worker(win)
    assert any("nepasiekiamas" in l for l in logs)
    win.txt_server_path.setText(os.path.join(tmp, "srv"))
    _run_worker(win)
    j = win.registry.get_job("order-pid-77")
    assert j["status"] == "dispatch_failed" and j["dispatched_plates"] == ["Primer", "White"], j
    j = win.registry.get_job("wallet-1")
    assert j["status"] == "dispatch_failed" and j["dispatched_plates"] == ["White"], j
    win.close()


def test_e2e_hung_server_gui_stays_responsive(tmp):
    """Serveris „pakimba“ (SMB I/O be atsako): GUI turi likti gyvas, gija – baigtis per timeout."""
    _app()
    from PySide6.QtCore import QTimer
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    win.config["server_timeout_sec"] = 1
    hung = os.path.join(tmp, "srv")
    real_isdir = scanner_lite.os.path.isdir

    def hanging_isdir(p):
        if os.path.abspath(p) == os.path.abspath(hung):
            time.sleep(6)  # imituoja \\192.168.1.143 be atsako
        return real_isdir(p)

    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.time()))
    timer.start(50)
    scanner_lite.os.path.isdir = hanging_isdir
    try:
        t0 = time.time()
        logs = _run_worker(win)
        elapsed = time.time() - t0
    finally:
        scanner_lite.os.path.isdir = real_isdir
        timer.stop()
    assert elapsed < 4, f"skenavimas laukė {elapsed:.1f}s – timeout neveikia"
    assert any("timeout" in l for l in logs), logs
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert ticks and max(gaps or [0]) < 0.5, f"GUI užšalo {max(gaps):.2f}s"
    win.close()


def test_storage_fallback_without_admin(tmp):
    from ui import main_window as mw
    path, warn = mw.resolve_storage_dir(os.path.join(tmp, "ok"))
    assert path == os.path.join(tmp, "ok") and not warn
    real = mw.is_dir_writable
    saved_lad = os.environ.get("LOCALAPPDATA")
    mw.is_dir_writable = lambda p: (not p.startswith(os.path.join(tmp, "locked"))) and real(p)
    try:
        path, warn = mw.resolve_storage_dir(os.path.join(tmp, "locked", "store"))
        assert warn and not path.startswith(os.path.join(tmp, "locked"))
        cfg_locked = os.path.join(tmp, "locked", "config.json")
        os.makedirs(os.path.dirname(cfg_locked))
        with open(cfg_locked, "w") as f:
            f.write("{}")
        os.environ["LOCALAPPDATA"] = os.path.join(tmp, "localappdata")
        new_cfg = mw.resolve_writable_config_path(cfg_locked)
        assert new_cfg.startswith(os.environ["LOCALAPPDATA"]) and os.path.exists(new_cfg)
    finally:
        mw.is_dir_writable = real
        if saved_lad is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = saved_lad


def test_config_corruption_preserved(tmp):
    _app()
    from ui.main_window import MainWindowLite
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w") as f:
        f.write('{"products": [')
    win = MainWindowLite(config_path=cfg_path)
    assert glob.glob(cfg_path + ".corrupt-*"), "sugadinto config kopija turi būti išsaugota"
    assert len(win.config["products"]) == 5 and win.config["auto_scan"] is False
    win.close()


# ---------------------------------------------------------------------------
# Paleidiklis be pytest
# ---------------------------------------------------------------------------
def _run_all():
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        tmp = tempfile.mkdtemp(prefix="pfl_")
        t0 = time.time()
        try:
            fn(tmp)
            print(f"  ✅ {name} ({time.time() - t0:.2f}s)")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  ❌ {name}: {e}")
            traceback.print_exc()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} testų sėkmingi")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
