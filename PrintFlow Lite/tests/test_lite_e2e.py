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
os.environ.setdefault("PRINTFLOW_NO_AUTO_UPDATE", "1")

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from core import scanner_lite, router_lite  # noqa: E402
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
    # Neegzistuojantis hotfolderis NEKURIAMAS (tylus failų „pametimas“) ir nekeliama NIEKO
    prod["hotfolders"]["CMYK"] = os.path.join(tmp, "hot", "RH COLOUR_typo")
    sent = r.dispatch_plates("j2", plates, prod, inter_layer_delay_sec=0)
    assert sent == [] and "RH COLOUR_typo" in r.last_stop_reason
    assert not os.path.exists(prod["hotfolders"]["CMYK"])
    assert not any(f.startswith("j2_") for d in hf.values() if os.path.isdir(d) for f in os.listdir(d))


# ---------------------------------------------------------------------------
# 5. Pilnas E2E per WorkerScanProcess (Qt gija) + UI
# ---------------------------------------------------------------------------
def _make_env(tmp, hot_missing=False, wait_for_pickup=False, pickup_timeout=60):
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
    cfg["wait_for_pickup"] = wait_for_pickup  # be netikro RasterLink failai HotFolderiuose nedingsta
    cfg["pickup_timeout_sec"] = pickup_timeout
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


def test_stop_monitoring_halts_running_scan(tmp):
    """Paspaudus „Sustabdyti“ vykstantis skenavimas nebeapdoroja likusių failų."""
    _app()
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    d = os.path.join(tmp, "srv", TODAY, "200", "magnetic-wallet")
    os.makedirs(d)
    for i in range(5):
        make_vector_pdf(os.path.join(d, f"many-{i}.pdf"))
        _set_old_mtime(os.path.join(d, f"many-{i}.pdf"))
    win = MainWindowLite(config_path=cfg_path)
    processed = []

    def on_job_in_worker(jname, data):
        # Vykdoma darbinėje gijoje (DirectConnection) – deterministiškai „paspaudžiama“ iškart po 1-o užsakymo.
        processed.append(jname)
        if len(processed) == 1:
            win.worker.stop()

    from PySide6.QtCore import Qt
    win.start_monitoring()
    win.worker.job_processed.connect(on_job_in_worker, Qt.DirectConnection)
    ui_stopped = False
    t0 = time.time()
    while win.worker.isRunning() and time.time() - t0 < 60:
        if processed and not ui_stopped:
            win.stop_monitoring()  # operatorius paspaudžia „Sustabdyti“ sąsajoje
            ui_stopped = True
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    if not ui_stopped:
        win.stop_monitoring()
    assert not win.auto_timer.isActive()
    dispatched = [j for j in win.registry.get_all_jobs() if j.get("status") == "dispatched"]
    assert len(dispatched) == 1, [j["job_id"] for j in dispatched]
    total_files = sum(len(os.listdir(h)) for h in hot.values())
    assert total_files <= 3, "po sustabdymo buvo keliami kiti užsakymai"
    assert win.badge_monitor.text().endswith("Stebėjimas sustabdytas")
    assert win.btn_toggle_monitor.isEnabled() and win.btn_toggle_monitor.text() == "Pradėti stebėjimą"
    win.close()


class FakeRasterLink(threading.Thread):
    """Imituoja RasterLink 7: kas `poll` s patikrina HotFolderius ir paima VISUS ten esančius .pdf."""

    def __init__(self, folders, poll=1.0):
        super().__init__(daemon=True)
        self.folders, self.poll = list(folders), poll
        self.batches = []  # kiekvieno tikrinimo metu paimti failai
        self._stop_ev = threading.Event()

    def run(self):
        while not self._stop_ev.wait(self.poll):
            batch = []
            for d in self.folders:
                for f in sorted(os.listdir(d)):
                    if f.endswith(".pdf"):
                        os.remove(os.path.join(d, f))
                        batch.append(f)
            if batch:
                self.batches.append(batch)

    def stop(self):
        self._stop_ev.set()
        self.join(5)

    def order(self):
        return [f for b in self.batches for f in b]


def _run_until_done(win, timeout=120):
    from PySide6.QtWidgets import QApplication
    t0 = time.time()
    while win.worker.isRunning() and time.time() - t0 < timeout:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()


def test_rasterlink_receives_plates_one_by_one_in_order(tmp):
    """Su „Laukti, kol RasterLink paims“ RasterLink niekada nemato dviejų plokščių vienu metu."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp, wait_for_pickup=True, pickup_timeout=20)
    rl = FakeRasterLink(hot.values(), poll=0.7)
    rl.start()
    win = MainWindowLite(config_path=cfg_path)
    win.start_scan()
    _run_until_done(win)
    rl.stop()
    assert all(len(b) == 1 for b in rl.batches), f"RasterLink rado kelias plokštes vienu metu: {rl.batches}"
    order = rl.order()
    for job, expected in (("order-pid-77", ["Primer", "White", "CMYK"]), ("wallet-1", ["White", "CMYK"])):
        got = [f.rsplit("_", 1)[1][:-4] for f in order if f.startswith(job + "_")]
        assert got == expected, (job, got)
    # Užsakymai nesimaišo: visos vieno užsakymo plokštės prieš kito pirmąją
    jobs_seq = [f.rsplit("_", 1)[0] for f in order]
    assert jobs_seq == sorted(jobs_seq, key=jobs_seq.index), jobs_seq
    j = win.registry.get_job("order-pid-77")
    assert j["status"] == "dispatched" and j["dispatched_plates"] == ["Primer", "White", "CMYK"]
    win.close()


def test_without_pickup_wait_rasterlink_sees_plates_together(tmp):
    """Kontrolinis: senasis elgesys (tik 0,05 s pauzė) – lėtai tikrinantis RasterLink plokštes randa kartu."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp, wait_for_pickup=False)
    rl = FakeRasterLink(hot.values(), poll=2.0)
    rl.start()
    win = MainWindowLite(config_path=cfg_path)
    win.start_scan()
    _run_until_done(win)
    time.sleep(2.5)
    rl.stop()
    assert any(len(b) > 1 for b in rl.batches), rl.batches
    win.close()


def test_rasterlink_not_running_halts_dispatch(tmp):
    """RasterLink išjungtas: pirmoji plokštė nepaimama ➔ likusios nekeliamos, skenavimas sustoja."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp, wait_for_pickup=True, pickup_timeout=1)
    win = MainWindowLite(config_path=cfg_path)
    halted = []
    win.start_monitoring()
    win.worker.halted.connect(halted.append)
    _run_until_done(win)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    on_disk = sorted(f for d in hot.values() for f in os.listdir(d))
    assert len(on_disk) == 1, f"po nepaimtos plokštės buvo keliama toliau: {on_disk}"
    jobs = {j["job_id"]: j for j in win.registry.get_all_jobs()}
    first = jobs[on_disk[0].rsplit("_", 1)[0]]
    assert first["status"] == "dispatch_failed" and "nepaėmė" in first["message"], first
    assert len(jobs) == 1, "kiti užsakymai neturėjo būti pradėti"
    assert halted and not win.auto_timer.isActive()
    win.close()


def test_router_stops_after_failed_layer(tmp):
    """Nepavykus įkelti White, CMYK nebekeliamas (kitaip RasterLink gautų CMYK be baltos)."""
    hf = {l: os.path.join(tmp, "hot", l) for l in ("Primer", "White", "CMYK")}
    for d in hf.values():
        os.makedirs(d)
    plates = {}
    for l in hf:
        p = os.path.join(tmp, f"{l}.pdf")
        make_vector_pdf(p)
        plates[l] = p
    r = HotFolderRouterLite(0)
    real_copy = router_lite.shutil.copyfile

    def failing_copy(src, dst, *a, **k):
        if "_White." in dst:
            raise OSError(28, "No space left on device")
        return real_copy(src, dst, *a, **k)

    router_lite.shutil.copyfile = failing_copy
    try:
        sent = r.dispatch_plates("j", plates, {"hotfolders": hf}, ["Primer", "White", "CMYK"], 0)
    finally:
        router_lite.shutil.copyfile = real_copy
    assert [d["layer"] for d in sent] == ["Primer"]
    assert not os.listdir(hf["CMYK"]) and "White" in r.last_stop_reason
    assert not os.listdir(hf["White"]), ".tmp turi būti išvalytas"


def _setup_rejects(tmp, cfg_path, date=TODAY):
    rej = os.path.join(tmp, "BROKAI")
    d = os.path.join(rej, date, "magsafe-ring-holders")
    os.makedirs(d)
    path = os.path.join(d, "order-pid-77.pdf")  # tas pats vardas kaip originalo užsakymo!
    make_smask_pdf(path)
    _set_old_mtime(path)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["rejects_folder"] = rej
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return rej, path


def test_rejects_folder_reprints_same_named_order(tmp):
    """Brokas su tuo pačiu vardu kaip jau atspausdintas užsakymas – keliamas kaip BROKAS_, originalas nepaliestas."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    _run_worker(win)  # originalai iš serverio
    original = win.registry.get_job("order-pid-77")
    assert original["status"] == "dispatched"
    for d in hot.values():
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))

    win.close()
    rej, path = _setup_rejects(tmp, cfg_path)
    win = MainWindowLite(config_path=cfg_path)
    _run_worker(win)
    assert sorted(os.listdir(hot["CMYK"])) == ["BROKAS_order-pid-77_CMYK.pdf"]
    assert sorted(os.listdir(hot["Primer"])) == ["BROKAS_order-pid-77_Primer.pdf"]
    rejects = [j for j in win.registry.get_all_jobs() if j.get("source") == "brokas"]
    assert len(rejects) == 1 and rejects[0]["status"] == "dispatched"
    assert rejects[0]["job_id"].startswith("BROKAS_order-pid-77_")
    assert win.registry.get_job("order-pid-77") == original, "originalo įrašas neturi keistis"
    assert os.path.exists(path), "broko failas paliekamas vietoje"

    # Antras skenavimas – tas pats brokas nekeliamas dar kartą
    for d in hot.values():
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    _run_worker(win)
    assert not any(os.listdir(d) for d in hot.values())

    # Failas pakeistas (vėl įdėtas) – spausdinamas iš naujo
    make_smask_pdf(path, w_px=600, h_px=1200)
    _set_old_mtime(path, age_sec=60)
    _run_worker(win)
    assert sorted(os.listdir(hot["CMYK"])) == ["BROKAS_order-pid-77_CMYK.pdf"]
    assert len([j for j in win.registry.get_all_jobs() if j.get("source") == "brokas"]) == 2
    win.close()


def test_rejects_folder_date_filter_and_server_down(tmp):
    """Brokams taikomas datos filtras; brokų aplankas veikia ir kai pagrindinis serveris nepasiekiamas."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    rej, path = _setup_rejects(tmp, cfg_path)
    old = os.path.join(rej, "2020-01-01", "magnetic-wallet")
    os.makedirs(old)
    make_vector_pdf(os.path.join(old, "senas-brokas.pdf"))
    _set_old_mtime(os.path.join(old, "senas-brokas.pdf"))
    win = MainWindowLite(config_path=cfg_path)
    win.txt_server_path.setText(os.path.join(tmp, "atjungtas_serveris"))
    logs = _run_worker(win)
    assert any("nepasiekiamas" in l for l in logs)
    assert sorted(os.listdir(hot["CMYK"])) == ["BROKAS_order-pid-77_CMYK.pdf"], "senesnės datos brokas neturi būti keliamas"
    win.close()


def _png(path, color=(200, 30, 30)):
    Image.new("RGB", (60, 80), color).save(path)


def _enable_batch_sheet(cfg_path, product_id="magsafe_ring_holders"):
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    for p in cfg["products"]:
        if p["id"] == product_id:
            p["batch_sheet"] = True
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def test_find_batch_sheets_order_and_filtering(tmp):
    from core.batch_sheets import find_batch_sheets
    pdf = os.path.join(tmp, "312-bid-26506-Clear Cases Magsafe V2.pdf")
    make_vector_pdf(pdf)
    for n in (10, 2, 1):
        _png(os.path.join(tmp, f"312-bid-26506-Clear Cases Magsafe V2_batch_sheet_{n}.png"))
    _png(os.path.join(tmp, "313-bid-1-Kitas_batch_sheet_1.png"))  # kito užsakymo lapas
    _png(os.path.join(tmp, "312-bid-26506-Clear Cases Magsafe V2.png"))  # ne batch sheet
    got = [os.path.basename(p) for p in find_batch_sheets(pdf)]
    assert got == [f"312-bid-26506-Clear Cases Magsafe V2_batch_sheet_{n}.png" for n in (1, 2, 10)]
    assert find_batch_sheets(os.path.join(tmp, "nera", "x.pdf")) == []


def test_batch_sheet_shown_for_flagged_product_only(tmp):
    """Pažymėtas produktas: lapai nukopijuojami ir rodomi kortelėje; nepažymėtas – ignoruojamas."""
    _app()
    from ui import main_window as mw
    cfg_path, hot = _make_env(tmp)
    _enable_batch_sheet(cfg_path)
    d = os.path.join(tmp, "srv", TODAY, "105", "magsafe-ring-holders")
    for n in (1, 2):
        _png(os.path.join(d, f"order-pid-77_batch_sheet_{n}.png"))
    _png(os.path.join(tmp, "srv", TODAY, "106", "magnetic-wallet", "wallet-1_batch_sheet_1.png"))
    win = mw.MainWindowLite(config_path=cfg_path)
    _run_worker(win)
    job = win.registry.get_job("order-pid-77")
    assert job["batch_sheet_expected"] and len(job["batch_sheets"]) == 2
    assert all(os.path.isfile(p) and "storage" in p for p in job["batch_sheets"])
    assert not win.registry.get_job("wallet-1").get("batch_sheet_expected")
    card = win.batch_card
    assert card.job["job_id"] == "order-pid-77" and card.image.has_image()
    assert card.lbl_page.text() == "Lapas 1 iš 2"
    card.set_page(1)
    assert card.page == 1

    printed = []
    orig = mw.print_images
    mw.print_images = lambda paths: (printed.append(list(paths)), (True, "Testinis spausdintuvas"))[1]
    try:
        card.btn_print.click()
    finally:
        mw.print_images = orig
    assert printed == [job["batch_sheets"]]
    win.close()


def test_batch_sheet_card_fills_width_and_scrolls(tmp):
    """Lapas ištemptas per kortelės plotį, rodomas nuo viršaus, slenkasi; atnaujinimas slinkimo nenumeta."""
    _app()
    from ui.batch_sheet_ui import BatchSheetCard
    from PySide6.QtWidgets import QApplication
    path = os.path.join(tmp, "o_batch_sheet_1.png")
    Image.new("RGB", (1240, 1754), (255, 255, 255)).save(path)
    card = BatchSheetCard(lambda _: None, lambda _: None)
    card.resize(700, 500)
    card.show()
    jobs = [{"job_id": "o", "batch_sheets": [path]}]
    card.set_jobs(jobs)
    QApplication.processEvents()
    view, bar = card.image, card.image.verticalScrollBar()
    assert view.has_image() and bar.value() == 0 and bar.maximum() > 0
    assert view.img.width() >= view.viewport().width() - 2
    bar.setValue(bar.maximum() // 2)
    card.set_jobs(jobs)  # registro atnaujinimas su tuo pačiu lapu
    assert bar.value() == bar.maximum() // 2
    card.close()


def test_batch_sheet_appearing_later_is_attached(tmp):
    """Lapas atsiranda serveryje vėliau už PDF – prijungiamas kito skenavimo metu."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    _enable_batch_sheet(cfg_path)
    win = MainWindowLite(config_path=cfg_path)
    _run_worker(win)
    job = win.registry.get_job("order-pid-77")
    assert job["batch_sheet_expected"] and job["batch_sheets"] == []
    assert win.batch_card.badge.text().endswith("Batch sheet nerastas")
    _png(os.path.join(tmp, "srv", TODAY, "105", "magsafe-ring-holders", "order-pid-77_batch_sheet_1.png"))
    logs = _run_worker(win)
    assert any("Batch sheet prijungtas" in l for l in logs), logs
    assert len(win.registry.get_job("order-pid-77")["batch_sheets"]) == 1
    assert win.batch_card.image.has_image()
    win.close()


def make_ring_pdf(path, diameters_mm, w_mm=200.0, h_mm=80.0, dpi=300):
    """Ringholder lapas: RGB paveikslėlis per visą lapą + SMask su žiedais (skylė = 65 % skersmens)."""
    px = dpi / 25.4
    w_px, h_px = int(round(w_mm * px)), int(round(h_mm * px))
    yy, xx = np.mgrid[0:h_px, 0:w_px]
    a = np.zeros((h_px, w_px), np.uint8)
    for i, d in enumerate(diameters_mm):
        cx, cy = (35 + i * 65) * px, h_mm / 2 * px
        r = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
        a[(r <= d / 2 * px) & (r >= d / 2 * 0.65 * px)] = 255
    rgb = np.dstack([np.full_like(a, 30), (xx % 256).astype(np.uint8), np.full_like(a, 200)])
    buf = io.BytesIO()
    Image.fromarray(np.dstack([rgb, a]), "RGBA").save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=w_mm / 25.4 * 72, height=h_mm / 25.4 * 72)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def _ring_sizes(pdf_path, dpi=300):
    """Žiedų skersmenys (mm) pagal White/kaukę – iš kairės į dešinę."""
    from core.prepress_lite import extract_pdf_data
    mask = extract_pdf_data(pdf_path, dpi=dpi)[4]
    cols = np.nonzero(mask.any(axis=0))[0]
    groups = np.split(cols, np.nonzero(np.diff(cols) > 1)[0] + 1)
    return [round((g[-1] - g[0] + 1) / dpi * 25.4, 1) for g in groups]


def _close(got, expected, tol=0.2):
    return len(got) == len(expected) and all(abs(g - e) <= tol for g, e in zip(got, expected))


def test_size_fix_enlarges_only_undersized_rings(tmp):
    from core.size_fix import fix_object_sizes
    src, out = os.path.join(tmp, "rh.pdf"), os.path.join(tmp, "rh_fixed.pdf")
    make_ring_pdf(src, [60.5, 57.2, 40.0])
    res = fix_object_sizes(src, out, 60.5)
    assert res["changed"] and len(res["fixed"]) == 1 and abs(res["fixed"][0][0] - 57.2) < 0.2
    assert any("per mažas automatiniam" in n for n in res["notes"])  # 40 mm – ne ringholder klaida
    assert _close(_ring_sizes(src), [60.5, 57.2, 40.0])
    assert _close(_ring_sizes(out), [60.5, 60.5, 40.0])
    with pymupdf.open(src) as a, pymupdf.open(out) as b:
        assert read_page_geometry(a, 0) == read_page_geometry(b, 0)
        assert b[0].get_images(full=True)[0][5] == a[0].get_images(full=True)[0][5]  # spalvų erdvė ta pati
    plates = export_production_plates(out, "rh", os.path.join(tmp, "plates"), ["Primer", "White", "CMYK"])
    assert_plates_registered(plates)

    good = os.path.join(tmp, "good.pdf")
    make_ring_pdf(good, [60.5, 60.4])
    assert not fix_object_sizes(good, os.path.join(tmp, "x.pdf"), 60.5)["changed"]
    assert not os.path.exists(os.path.join(tmp, "x.pdf"))
    vec = os.path.join(tmp, "vec.pdf")
    make_vector_pdf(vec)
    assert fix_object_sizes(vec, os.path.join(tmp, "y.pdf"), 60.5)["error"]


def test_size_fix_in_worker_pipeline(tmp):
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    src = os.path.join(tmp, "srv", TODAY, "105", "magsafe-ring-holders", "order-pid-77.pdf")
    make_ring_pdf(src, [57.2])
    _set_old_mtime(src)
    win = MainWindowLite(config_path=cfg_path)
    logs = _run_worker(win)
    job = win.registry.get_job("order-pid-77")
    assert job["status"] == "dispatched", job
    assert job["size_fix"].endswith("→ 60.5 mm"), job
    assert any("padidintas iki 60.5 mm" in l for l in logs), logs
    assert _close(_ring_sizes(os.path.join(hot["CMYK"], "order-pid-77_CMYK.pdf")), [60.5])
    assert _close(_ring_sizes(job["local_pdf_path"]), [57.2])  # originalas nekeičiamas
    win.close()


def test_frame_guide_button_sends_only_to_cmyk(tmp):
    """„Rėmų ribos“: lapas iškart į CMYK HotFolderį vardu „GRIP／WALLET remas“, antras kartas – neperrašo."""
    _app()
    from ui.main_window import MainWindowLite
    from core.frame_guide import safe_file_name
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    win.btn_frame_guide.click()
    expected = "GRIP\uff0fWALLET remas.pdf"
    assert os.listdir(hot["CMYK"]) == [expected]
    assert os.listdir(hot["White"]) == [] and os.listdir(hot["Primer"]) == []
    with pymupdf.open(os.path.join(hot["CMYK"], expected)) as d:
        assert d.metadata["title"] == "GRIP/WALLET remas"
        assert [round(v / 72 * 25.4) for v in d[0].rect] == [0, 0, 609, 419]
    win.btn_frame_guide.click()  # dar nepaimtas – nedubliuojama
    assert os.listdir(hot["CMYK"]) == [expected]
    assert any("jau laukia" in l for l in win.txt_log.toPlainText().splitlines())
    os.remove(os.path.join(hot["CMYK"], expected))  # RasterLink paėmė
    shutil.rmtree(hot["CMYK"])
    win.btn_frame_guide.click()
    assert "nepasiekiamas" in win.txt_log.toPlainText()
    assert safe_file_name('a/b:c?') == "a\uff0fb-c-"
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
    # Trūksta CMYK HotFolderio ➔ nekeliama nieko (jokio dalinio užsakymo RasterLink'e), klaida kartojama
    for name in ("order-pid-77", "wallet-1"):
        j = win.registry.get_job(name)
        assert j["status"] == "error" and not j.get("dispatched_plates"), j
    assert not any(os.listdir(d) for d in hot.values() if os.path.isdir(d))
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


def test_product_editor_create_reorder_and_dispatch(tmp):
    """Naujas produktas per Produktai formą: tik White + CMYK, tvarka CMYK → White, savi hotfolderiai."""
    _app()
    from ui.main_window import MainWindowLite
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    n_before = len(win.config["products"])
    assert win.list_products.count() == n_before

    win.add_product()
    form = win.product_form
    assert not win.btn_product_save.isEnabled(), "tuščias produktas neturi būti išsaugomas"
    form.txt_name.setText("Phone Grip Ąžuolas")
    form.txt_kw.setText("phone-grip, PG")
    form.rows["Primer"].switch.setChecked(False)
    my_hot = {l: os.path.join(tmp, "grip_hot", l) for l in ("CMYK", "White")}
    for l, d in my_hot.items():
        os.makedirs(d)
        form.rows[l].txt_hot.setText(d)
    form.rows["White"].spn_choke.setValue(2)
    form.move_row(form.rows["CMYK"], -1)  # CMYK prieš White
    form.txt_test.setText("2026-10-09/7/phone-grip/x.pdf")
    assert form.badge_test.kind() == "success", form.badge_test.text()
    assert win.btn_product_save.isEnabled(), form.lbl_errors.text()
    prod = form.build_product()
    assert prod["id"] == "phone_grip_azuolas"
    assert prod["layers"] == ["White", "CMYK"] and prod["dispatch_order"] == ["CMYK", "White"]
    assert prod["hotfolders"]["Primer"] == "" and prod["choke_white_px"] == 2
    assert win.save_current_product()
    assert not win._product_dirty

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)["products"]
    assert len(saved) == n_before + 1 and saved[-1]["dispatch_order"] == ["CMYK", "White"]
    assert win.list_products.count() == n_before + 1

    # Dublikato pavadinimas blokuojamas
    win.add_product()
    win.product_form.txt_name.setText("phone grip ąžuolas")
    win.product_form.txt_kw.setText("x")
    assert not win.btn_product_save.isEnabled()
    win._product_dirty = False

    # Failas serveryje → apdorojamas naujojo produkto taisyklėmis
    d = os.path.join(tmp, "srv", TODAY, "7", "phone-grip")
    os.makedirs(d)
    make_smask_pdf(os.path.join(d, "grip-1.pdf"))
    _set_old_mtime(os.path.join(d, "grip-1.pdf"))
    _run_worker(win)
    job = win.registry.get_job("grip-1")
    assert job["status"] == "dispatched" and job["dispatched_plates"] == ["CMYK", "White"], job
    assert os.listdir(my_hot["CMYK"]) == ["grip-1_CMYK.pdf"]
    assert os.listdir(my_hot["White"]) == ["grip-1_White.pdf"]
    win.close()


def test_product_editor_loads_legacy_config(tmp):
    """Seni config.json produktai (be per-produkto pauzės ir pan.) atsidaro formoje be klaidų."""
    _app()
    from ui.product_editor import ProductForm, normalize_product
    legacy = {"id": "old", "name": "Senas", "keywords": "a-b, CC", "layers": ["CMYK", "White"],
              "dispatch_order": ["Primer", "White", "CMYK"], "hotfolders": {"CMYK": "c", "White": "w"}}
    n = normalize_product(legacy)
    assert n["dispatch_order"] == ["White", "CMYK"] and n["keywords"] == ["a-b", "CC"]
    form = ProductForm()
    form.load(legacy, [legacy])
    p = form.build_product()
    assert p["id"] == "old" and p["dispatch_order"] == ["White", "CMYK"] and p["hotfolders"]["Primer"] == ""


def test_ui_pages_theme_and_log(tmp):
    """Visi skirtukai atsidaro, tema persijungia ir išsisaugo, žurnalas be emoji."""
    _app()
    from ui.main_window import MainWindowLite, classify_log
    from ui.widgets import current_theme
    cfg_path, hot = _make_env(tmp)
    win = MainWindowLite(config_path=cfg_path)
    for i in range(4):
        win.tab_group.button(i).click()
        assert win.pages.currentIndex() == i
    win.set_theme("dark")
    assert current_theme() == "dark"
    with open(cfg_path, encoding="utf-8") as f:
        assert json.load(f)["theme"] == "dark"
    win.set_theme("light")
    assert classify_log("✅ SĖKMINGAI: 'x'") == ("success", "SĖKMINGAI: 'x'")
    assert classify_log("   ⬇️ [1/3] Siunčiamas") == ("neutral", "[1/3] Siunčiamas")
    assert classify_log("❌ Klaida")[0] == "error"
    assert "➔" not in classify_log("A ➔ B")[1]
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
    assert not win.auto_timer.isActive()
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
