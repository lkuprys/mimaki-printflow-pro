import os
import re
import json
import time
import shutil
import threading
from datetime import datetime
from typing import Optional, List, Dict

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

from printflow.core.prepress import extract_pdf_data, generate_preview_files, export_production_plates
from printflow.core.rasterlink_bridge import bridge
from printflow.core.scanner import scan_inbox_recursive
from printflow.core.job_registry import JobRegistry


class WorkerThread(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, task_func, *args, **kwargs):
        super().__init__()
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.task_func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class PrintFlowController(QObject):
    # Signals for QML
    configLoaded = Signal(str)            # JSON string
    inboxUpdated = Signal(str)            # JSON string
    readyJobsUpdated = Signal(str)        # JSON string: list of ready to print jobs
    autoPipelineStatus = Signal(bool)     # True = running, False = idle
    inspectStarted = Signal()
    inspectFinished = Signal(str)         # JSON string
    inspectFailed = Signal(str)
    dispatchStarted = Signal()
    dispatchFinished = Signal(str)        # JSON string
    dispatchFailed = Signal(str)
    compositeStarted = Signal(str)        # job_name
    compositeFinished = Signal(str)       # JSON string
    compositeFailed = Signal(str)
    printStarted = Signal(str)            # job_name
    printFinished = Signal(str)           # JSON string
    printFailed = Signal(str)
    rasterLinkVisibilityChanged = Signal(bool)
    logMessage = Signal(str)
    historyUpdated = Signal(str)          # JSON string

    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        import sys
        if getattr(sys, "frozen", False):
            # When running as compiled standalone EXE, base_dir is the folder where PrintFlow.exe is located
            base_dir = os.path.dirname(os.path.abspath(sys.executable))
            bundle_dir = getattr(sys, "_MEIPASS", base_dir)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            bundle_dir = base_dir

        self.base_dir = base_dir
        self.bundle_dir = bundle_dir

        # Determine config file location:
        # 1. Explicit path if passed
        # 2. app_config.json in the same directory as the executable (portable & easy to edit/migrate)
        # 3. printflow/config/app_config.json in project dir
        # 4. Fallback template bundled inside PyInstaller
        bundled_config = os.path.join(bundle_dir, "printflow", "config", "app_config.json")
        external_config = os.path.join(base_dir, "app_config.json")
        project_config = os.path.join(base_dir, "printflow", "config", "app_config.json")

        if config_path:
            self.config_path = os.path.abspath(config_path) if os.path.isabs(config_path) else os.path.join(base_dir, config_path)
        elif os.path.exists(external_config):
            self.config_path = external_config
        elif os.path.exists(project_config):
            self.config_path = project_config
        else:
            self.config_path = external_config
            if os.path.exists(bundled_config):
                self._fallback_template = bundled_config

        self.temp_dir = os.path.join(base_dir, "temp_cache")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.current_config = self._read_config()
        self.staging_dir = self._resolve_staging_dir()
        self.prepared_jobs_dir = os.path.join(self.staging_dir, "paruosti_darbai")
        os.makedirs(self.prepared_jobs_dir, exist_ok=True)

        # Inicijuojame užduočių registrą Desktop/mimaki kataloge
        self.registry = JobRegistry(os.path.join(self.staging_dir, "job_registry.json"))

        self.job_history = []
        self._inspect_worker = None
        self._dispatch_worker = None
        self._composite_worker = None
        self._print_worker = None

        # Automatinio gamybos konvejerio būsena
        self._auto_pipeline_running = bool(self.current_config.get("auto_pipeline", False))
        self._auto_thread = None
        self._stop_auto_event = threading.Event()

        # Paleidžiame foninį RasterLink pop-up stebėtoją
        bridge.start()

        if self._auto_pipeline_running:
            self._start_auto_pipeline_thread()

    def _resolve_staging_dir(self) -> str:
        staging = self.current_config.get("staging_folder", "").strip()
        if not staging:
            staging = os.path.join(os.path.expanduser("~"), "Desktop", "mimaki")
        path = os.path.abspath(staging)
        os.makedirs(path, exist_ok=True)
        return path

    def _read_config(self) -> dict:
        default_inbox = os.path.join(self.base_dir, "INBOX_PRINT_FILES")
        default_staging = os.path.join(os.path.expanduser("~"), "Desktop", "mimaki")

        # Jei konfigūracijos failo dar nėra išorėje, nukopijuojame šabloną
        if not os.path.exists(self.config_path) and hasattr(self, "_fallback_template") and os.path.exists(self._fallback_template):
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                shutil.copyfile(self._fallback_template, self.config_path)
            except Exception:
                pass

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "staging_folder" not in data or not data["staging_folder"]:
                        data["staging_folder"] = default_staging
                    if "auto_pipeline" not in data:
                        data["auto_pipeline"] = False
                    if "scan_interval_sec" not in data:
                        data["scan_interval_sec"] = 15
                    return data
            except Exception:
                pass

        return {
            "inbox_folder": default_inbox,
            "staging_folder": default_staging,
            "auto_pipeline": False,
            "scan_interval_sec": 15,
            "products": []
        }

    # -----------------------------------------------------------------
    # CONFIGURATION SLOTS
    # -----------------------------------------------------------------
    @Slot()
    def loadConfig(self):
        self.current_config = self._read_config()
        self.staging_dir = self._resolve_staging_dir()
        self.prepared_jobs_dir = os.path.join(self.staging_dir, "paruosti_darbai")
        os.makedirs(self.prepared_jobs_dir, exist_ok=True)

        cfg_str = json.dumps(self.current_config, ensure_ascii=False)
        self.configLoaded.emit(cfg_str)
        self.log(f"Konfigūracija užkrauta. Staging: {self.staging_dir}")
        self.loadReadyJobs()

    @Slot(str)
    def saveConfigJson(self, json_str: str):
        try:
            data = json.loads(json_str)
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.current_config = data
            self.staging_dir = self._resolve_staging_dir()
            self.prepared_jobs_dir = os.path.join(self.staging_dir, "paruosti_darbai")
            os.makedirs(self.prepared_jobs_dir, exist_ok=True)

            inbox = data.get("inbox_folder")
            if inbox:
                os.makedirs(inbox, exist_ok=True)

            self.configLoaded.emit(json.dumps(self.current_config, ensure_ascii=False))
            self.log("Konfigūracija sėkmingai išsaugota!")
            self.refreshInbox()
            self.loadReadyJobs()
        except Exception as e:
            self.log(f"Klaida saugant konfigūraciją: {e}")

    @Slot()
    def openStagingFolder(self):
        """Atveria Desktop/mimaki/paruosti_darbai katalogą Windows Explorer lange."""
        try:
            os.makedirs(self.prepared_jobs_dir, exist_ok=True)
            os.startfile(self.prepared_jobs_dir)
            self.log(f"Atvertas aplankas: {self.prepared_jobs_dir}")
        except Exception as e:
            self.log(f"Klaida atveriant aplanką: {e}")

    def _get_folder_filter_keywords(self) -> List[str]:
        raw = self.current_config.get("folder_filter_keywords", "")
        if isinstance(raw, list):
            return [k.strip() for k in raw if isinstance(k, str) and k.strip()]
        elif isinstance(raw, str) and raw.strip():
            return [k.strip() for k in raw.split(",") if k.strip()]
        return []

    # -----------------------------------------------------------------
    # INBOX SLOTS (RECURSIVE SCANNER)
    # -----------------------------------------------------------------
    @Slot()
    def refreshInbox(self):
        inbox_dir = self.current_config.get("inbox_folder", "")
        products = self.current_config.get("products", [])
        folder_filters = self._get_folder_filter_keywords()

        # Rekursyviai skenuojame visą bendrą gamybos aplanką su filtrais
        files_list = scan_inbox_recursive(inbox_dir, products, folder_filter_keywords=folder_filters)

        # Pažymime, ar failas jau paruoštas / registruotas
        for f in files_list:
            reg_entry = self.registry.get_job(f["job_name"])
            if reg_entry:
                f["status"] = reg_entry.get("status", "pending")
                f["is_processed"] = f["status"] in ["ready_to_print", "printed", "composited"]
            else:
                f["status"] = "naujas"
                f["is_processed"] = False

        res = {
            "inbox_folder": inbox_dir,
            "staging_folder": self.staging_dir,
            "count": len(files_list),
            "files": files_list
        }
        self.inboxUpdated.emit(json.dumps(res, ensure_ascii=False))
        self.loadReadyJobs()

    # -----------------------------------------------------------------
    # READY JOBS / QUEUE SLOTS
    # -----------------------------------------------------------------
    @Slot()
    def loadReadyJobs(self):
        """Nuskaito visus darbus, paruoštus spaudai (su atlikta kompozicija)."""
        ready_jobs = self.registry.get_ready_jobs()
        self.readyJobsUpdated.emit(json.dumps(ready_jobs, ensure_ascii=False))

    @Slot(str)
    def printReadyJob(self, job_name: str):
        """Vienu mygtuko paspaudimu paleidžia paruošto darbo spaudą."""
        self.executePrint(job_name)

    # -----------------------------------------------------------------
    # INSPECT SLOTS
    # -----------------------------------------------------------------
    @Slot(str, int)
    def inspectFile(self, file_path: str, choke_pixels: int = 1):
        if not os.path.exists(file_path):
            self.inspectFailed.emit("Failas nerastas: " + file_path)
            return

        self.inspectStarted.emit()
        self.log(f"Analizuojamas failas: {os.path.basename(file_path)}...")

        def _do_inspect(fpath, choke):
            t0 = time.time()
            w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask = extract_pdf_data(fpath)
            previews = generate_preview_files(thumb_rgb, thumb_mask, self.temp_dir, choke_px=choke)
            elapsed_ms = round((time.time() - t0) * 1000)

            w_mm = round((w_pt / 72.0) * 25.4, 1)
            h_mm = round((h_pt / 72.0) * 25.4, 1)

            return {
                "status": "ok",
                "filename": os.path.basename(fpath),
                "filepath": fpath,
                "width_mm": w_mm,
                "height_mm": h_mm,
                "width_px": w_px,
                "height_px": h_px,
                "elapsed_ms": elapsed_ms,
                "previews": previews
            }

        self._inspect_worker = WorkerThread(_do_inspect, file_path, choke_pixels)
        self._inspect_worker.finished.connect(lambda res: self._on_inspect_finished(res))
        self._inspect_worker.error.connect(lambda err: self._on_inspect_error(err))
        self._inspect_worker.start()

    def _on_inspect_finished(self, res: dict):
        self.log(f"Failas apdorotas per {res['elapsed_ms']} ms: {res['filename']} ({res['width_mm']} x {res['height_mm']} mm)")
        self.inspectFinished.emit(json.dumps(res, ensure_ascii=False))

    def _on_inspect_error(self, err: str):
        self.log(f"Klaida analizuojant failą: {err}")
        self.inspectFailed.emit(err)

    # -----------------------------------------------------------------
    # DISPATCH SLOTS (LOCAL STAGING + HOT FOLDER DISPATCH)
    # -----------------------------------------------------------------
    @Slot(str, str, str, int)
    def dispatchJob(self, file_path: str, product_id: str, job_name: str, choke_white: int = 1):
        product = next((p for p in self.current_config.get("products", []) if p["id"] == product_id), None)
        if not product:
            self.dispatchFailed.emit(f"Nerastas produktas su ID: {product_id}")
            return

        if not os.path.exists(file_path):
            self.dispatchFailed.emit("Failas nerastas diske: " + file_path)
            return

        final_job_name = job_name.strip() if job_name.strip() else os.path.splitext(os.path.basename(file_path))[0]
        self.dispatchStarted.emit()
        self.log(f"Ruošiamas darbas: {final_job_name} ({product['name']}) lokaliame aplanke Desktop/mimaki...")

        def _do_dispatch(fpath, prod, jname, ch_w):
            t0 = time.time()
            job_out_dir = os.path.join(self.prepared_jobs_dir, jname)
            os.makedirs(job_out_dir, exist_ok=True)

            ch_p = prod.get("choke_primer_px", 0)
            layers = prod.get("layers", ["CMYK"])
            hotfolders = prod.get("hotfolders", {})

            # 1. Sugeneruojame plokštes Desktop/mimaki/paruosti_darbai/{jname}
            plates = export_production_plates(
                source_pdf_path=fpath,
                job_name=jname,
                output_dir=job_out_dir,
                layers=layers,
                choke_white_px=ch_w,
                choke_primer_px=ch_p
            )

            # 2. Įrašome informacinį failą
            meta_info = {
                "job_name": jname,
                "source_file": fpath,
                "product_id": prod["id"],
                "product_name": prod["name"],
                "layers": layers,
                "choke_white": ch_w,
                "choke_primer": ch_p,
                "plates": plates,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            try:
                with open(os.path.join(job_out_dir, "job_info.json"), "w", encoding="utf-8") as mf:
                    json.dump(meta_info, mf, indent=2, ensure_ascii=False)
            except Exception:
                pass

            # 3. Registruojame registre
            self.registry.register_or_update(jname, {
                "file_path": fpath,
                "product_id": prod["id"],
                "product_name": prod["name"],
                "staged_dir": job_out_dir,
                "plates": plates,
                "status": "staged"
            })

            # 4. Kopijuojame į Mimaki Hot Folderius
            dispatched = []
            for layer, plate_file in plates.items():
                hf_dir = hotfolders.get(layer)
                if hf_dir:
                    os.makedirs(hf_dir, exist_ok=True)
                    dst = os.path.join(hf_dir, os.path.basename(plate_file))
                    shutil.copy2(plate_file, dst)
                    dispatched.append({
                        "layer": layer,
                        "file": os.path.basename(plate_file),
                        "hotfolder": hf_dir,
                        "destination": dst
                    })

            self.registry.set_status(jname, "hotfoldered")
            elapsed_ms = round((time.time() - t0) * 1000)
            return {
                "job_name": jname,
                "product_name": prod["name"],
                "layers": list(plates.keys()),
                "elapsed_ms": elapsed_ms,
                "dispatched": dispatched
            }

        self._dispatch_worker = WorkerThread(_do_dispatch, file_path, product, final_job_name, choke_white)
        self._dispatch_worker.finished.connect(lambda res: self._on_dispatch_finished(res))
        self._dispatch_worker.error.connect(lambda err: self._on_dispatch_error(err))
        self._dispatch_worker.start()

    def _on_dispatch_finished(self, res: dict):
        self.log(f"SĖKMINGAI PARUOŠTA ir įkelta į Hot Folderius ({res['elapsed_ms']} ms): {res['job_name']}")
        for d in res["dispatched"]:
            self.log(f"   -> [{d['layer']}] {d['destination']}")

        history_item = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "job_name": res["job_name"],
            "product_name": res["product_name"],
            "layers": res["layers"],
            "dispatched_count": len(res["dispatched"]),
            "elapsed_ms": res["elapsed_ms"]
        }
        self.job_history.insert(0, history_item)
        self.historyUpdated.emit(json.dumps(self.job_history[:50], ensure_ascii=False))
        self.dispatchFinished.emit(json.dumps(res, ensure_ascii=False))

        # Automatiškai pradedame RasterLink kompoziciją fone
        self.startComposite(res["job_name"])

    def _on_dispatch_error(self, err: str):
        self.log(f"Klaida ruošiant plokštes: {err}")
        self.dispatchFailed.emit(err)

    # -----------------------------------------------------------------
    # RASTERLINK AUTOMATION SLOTS
    # -----------------------------------------------------------------
    @Slot(str)
    def startComposite(self, job_name: str):
        self.compositeStarted.emit(job_name)
        self.log(f"Pradedama RasterLink 7 kompozicija darbui: {job_name} (Quality režimas)...")

        job_data = self.registry.get_job(job_name) or {}
        prod_id = job_data.get("product_id")
        prod = self.getProductById(prod_id) if prod_id else None
        expected_layers = prod.get("layers") if prod else ["Primer", "White", "CMYK"]

        def _do_comp(jname):
            success, msg = bridge.composite_and_quality(
                job_name_keyword=jname,
                expected_layers=expected_layers,
                timeout=45.0,
                status_cb=lambda m: self.log(f"[RasterLink] {m}")
            )
            return {"success": success, "message": msg, "job_name": jname}

        self._composite_worker = WorkerThread(_do_comp, job_name)
        self._composite_worker.finished.connect(lambda res: self._on_composite_finished(res))
        self._composite_worker.error.connect(lambda err: self._on_composite_error(err))
        self._composite_worker.start()

    def _on_composite_finished(self, res: dict):
        jname = res.get("job_name", "")
        if res.get("success"):
            self.log(f"✅ KOMPOZICIJA PARUOŠTA: {res.get('message')}")
            self.registry.set_status(jname, "ready_to_print", res.get("message"))
            self.compositeFinished.emit(json.dumps(res, ensure_ascii=False))
        else:
            self.log(f"⚠️ Kompozicijos įspėjimas: {res.get('message')}")
            self.registry.set_status(jname, "error", res.get("message"))
            self.compositeFailed.emit(res.get("message", "Nežinoma klaida"))

        self.loadReadyJobs()
        self.refreshInbox()

    def _on_composite_error(self, err: str):
        self.log(f"❌ Kompozicijos klaida: {err}")
        self.compositeFailed.emit(err)

    @Slot(str)
    def executePrint(self, job_name: str):
        self.printStarted.emit(job_name)
        self.log(f"Siunčiama į RIP & Print darbui: {job_name}...")

        def _do_print(jname):
            success, msg = bridge.rip_and_print(
                job_name_keyword=jname,
                status_cb=lambda m: self.log(f"[RasterLink] {m}")
            )
            return {"success": success, "message": msg, "job_name": jname}

        self._print_worker = WorkerThread(_do_print, job_name)
        self._print_worker.finished.connect(lambda res: self._on_print_finished(res))
        self._print_worker.error.connect(lambda err: self._on_print_error(err))
        self._print_worker.start()

    def _on_print_finished(self, res: dict):
        jname = res.get("job_name", "")
        if res.get("success"):
            self.log(f"🎉 SPAUSDINIMAS PALEISTAS: {res.get('message')}")
            self.registry.set_status(jname, "printed", res.get("message"))
            self.printFinished.emit(json.dumps(res, ensure_ascii=False))
        else:
            self.log(f"⚠️ Spausdinimo paleidimo klaida: {res.get('message')}")
            self.printFailed.emit(res.get("message", "Klaida paleidžiant spaudą"))

        self.loadReadyJobs()
        self.refreshInbox()

    def _on_print_error(self, err: str):
        self.log(f"❌ Spausdinimo vykdymo klaida: {err}")
        self.printFailed.emit(err)

    # -----------------------------------------------------------------
    # AUTOMATIC PIPELINE & BATCH PROCESSING
    # -----------------------------------------------------------------
    @Slot(result=bool)
    def isAutoPipelineEnabled(self) -> bool:
        return self._auto_pipeline_running

    @Slot(bool)
    def setAutoPipeline(self, enabled: bool):
        self._auto_pipeline_running = enabled
        self.current_config["auto_pipeline"] = enabled
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.current_config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        if enabled:
            self.log("⚡ Automatinis gamybos konvejeris ĮJUNGTAS.")
            self._start_auto_pipeline_thread()
        else:
            self.log("⚡ Automatinis gamybos konvejeris IŠJUNGTAS.")
            self._stop_auto_event.set()

        self.autoPipelineStatus.emit(enabled)

    def _start_auto_pipeline_thread(self):
        self._stop_auto_event.clear()
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._auto_thread = threading.Thread(target=self._auto_pipeline_loop, daemon=True)
        self._auto_thread.start()

    def _auto_pipeline_loop(self):
        while not self._stop_auto_event.is_set():
            try:
                interval = int(self.current_config.get("scan_interval_sec", 15))
                inbox_dir = self.current_config.get("inbox_folder", "")
                products = self.current_config.get("products", [])

                if inbox_dir and os.path.exists(inbox_dir):
                    folder_filters = self._get_folder_filter_keywords()
                    files = scan_inbox_recursive(inbox_dir, products, folder_filter_keywords=folder_filters)
                    for item in files:
                        if self._stop_auto_event.is_set():
                            break
                        if not item.get("matched_product_id"):
                            continue
                        if self.registry.is_file_processed(item["filepath"]):
                            continue

                        # Radome naują failą: paruošiame jį
                        self.log(f"⚡ [Auto-Pipeline] Aptiktas naujas užsakymas: {item['filename']} (BID: {item.get('bid', '-')})")
                        self._process_single_job_sync(item)
                        time.sleep(3.0)

            except Exception as e:
                self.log(f"Klaida automatiniame konvejeryje: {e}")

            # Laukiame intervalą arba sustabdymo signalo
            self._stop_auto_event.wait(timeout=float(self.current_config.get("scan_interval_sec", 15)))

    @Slot()
    def batchPrepareAll(self):
        """Vienu paspaudimu paruošia visus rastus neapdorotus failus."""
        self.log("🚀 Pradedamas visų naujų failų paruošimas...")
        th = threading.Thread(target=self._run_batch_prepare, daemon=True)
        th.start()

    def _run_batch_prepare(self):
        inbox_dir = self.current_config.get("inbox_folder", "")
        products = self.current_config.get("products", [])
        folder_filters = self._get_folder_filter_keywords()
        files = scan_inbox_recursive(inbox_dir, products, folder_filter_keywords=folder_filters)

        pending = [
            f for f in files
            if f.get("matched_product_id") and not self.registry.is_file_processed(f["filepath"])
        ]

        if not pending:
            self.log("ℹ️ Nėra naujų neapdorotų failų.")
            return

        self.log(f"Rasta {len(pending)} naujų darbų paruošimui.")
        for item in pending:
            self._process_single_job_sync(item)
            time.sleep(2.0)

        self.log("🎉 Visi nauji darbai sėkmingai paruošti spaudai!")

    def _process_single_job_sync(self, item: dict):
        products = self.current_config.get("products", [])
        prod = next((p for p in products if p["id"] == item["matched_product_id"]), None)
        if not prod:
            return

        ch_w = prod.get("choke_white_px", 1)
        ch_p = prod.get("choke_primer_px", 0)
        jname = item["job_name"]
        job_out_dir = os.path.join(self.prepared_jobs_dir, jname)
        os.makedirs(job_out_dir, exist_ok=True)
        layers = prod.get("layers", ["CMYK"])
        hotfolders = prod.get("hotfolders", {})

        try:
            # 0. Nedelsiant pažymime registre, kad darbas apdorojamas (užkerta kelią pasikartojančiam ciklui)
            self.registry.register_or_update(jname, {
                "file_path": item["filepath"],
                "product_id": prod["id"],
                "product_name": prod["name"],
                "status": "processing"
            })

            # 1. Sugeneruojame plokštes
            plates = export_production_plates(
                source_pdf_path=item["filepath"],
                job_name=jname,
                output_dir=job_out_dir,
                layers=layers,
                choke_white_px=ch_w,
                choke_primer_px=ch_p
            )

            # 2. Įrašome informaciją
            meta_info = {
                "job_name": jname,
                "source_file": item["filepath"],
                "product_id": prod["id"],
                "product_name": prod["name"],
                "bid": item.get("bid", ""),
                "pid": item.get("pid", ""),
                "rel_dir": item.get("rel_dir", ""),
                "plates": plates,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(os.path.join(job_out_dir, "job_info.json"), "w", encoding="utf-8") as mf:
                json.dump(meta_info, mf, indent=2, ensure_ascii=False)

            # 3. Kopijuojame į Hot Folderius
            for layer, plate_file in plates.items():
                hf_dir = hotfolders.get(layer)
                if hf_dir:
                    os.makedirs(hf_dir, exist_ok=True)
                    dst = os.path.join(hf_dir, os.path.basename(plate_file))
                    shutil.copy2(plate_file, dst)

            self.registry.register_or_update(jname, {
                "file_path": item["filepath"],
                "product_id": prod["id"],
                "product_name": prod["name"],
                "bid": item.get("bid", ""),
                "pid": item.get("pid", ""),
                "rel_dir": item.get("rel_dir", ""),
                "staged_dir": job_out_dir,
                "plates": plates,
                "status": "hotfoldered"
            })
            self.log(f"   [+] '{jname}' plokštės įkeltos į Hot Folderius.")

            # 4. Atliekame kompoziciją RasterLink 7
            self.log(f"   [+] Laukiama RasterLink kompozicijos darbui '{jname}'...")
            expected_layers = prod.get("layers", ["Primer", "White", "CMYK"])
            ok, msg = bridge.composite_and_quality(
                job_name_keyword=jname,
                expected_layers=expected_layers,
                timeout=45.0,
                status_cb=lambda m: self.log(f"   [RasterLink] {m}")
            )
            if ok:
                self.registry.set_status(jname, "ready_to_print", msg)
                self.log(f"✅ Darbas '{jname}' PARUOŠTAS SPAUDAI!")
            else:
                self.registry.set_status(jname, "error", msg)
                self.log(f"⚠️ Darbui '{jname}' nepavyko kompozicija: {msg}")

            self.loadReadyJobs()
            self.refreshInbox()
        except Exception as e:
            self.log(f"❌ Klaida apdorojant '{jname}': {e}")

    # -----------------------------------------------------------------
    # RASTERLINK WINDOW TOGGLE
    # -----------------------------------------------------------------
    @Slot()
    def toggleRasterLink(self):
        is_vis = bridge.toggle_window()
        state_str = "atvertas ekrane" if is_vis else "paslėptas į foną"
        self.log(f"👁️ RasterLink 7 langas {state_str}.")
        self.rasterLinkVisibilityChanged.emit(is_vis)

    @Slot()
    def showRasterLink(self):
        bridge.show_window()
        self.log("👁️ RasterLink 7 langas atvertas ekrane.")
        self.rasterLinkVisibilityChanged.emit(True)

    @Slot()
    def hideRasterLink(self):
        bridge.hide_window()
        self.log("👁️ RasterLink 7 langas paslėptas į foną.")
        self.rasterLinkVisibilityChanged.emit(False)

    @Slot(result=bool)
    def isRasterLinkVisible(self) -> bool:
        return bridge.is_window_visible_on_screen()

    # -----------------------------------------------------------------
    # LOG & HISTORY SLOTS
    # -----------------------------------------------------------------
    @Slot(str)
    def log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        msg = f"[{timestamp}] {text}"
        self.logMessage.emit(msg)

    @Slot()
    def loadHistory(self):
        self.historyUpdated.emit(json.dumps(self.job_history[:50], ensure_ascii=False))
