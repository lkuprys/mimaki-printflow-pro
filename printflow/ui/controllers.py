import os
import re
import json
import time
import shutil
from datetime import datetime
from typing import Optional, List, Dict

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

from printflow.core.prepress import extract_pdf_data, generate_web_previews, generate_preview_files, export_production_plates
from printflow.core.rasterlink_bridge import bridge


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
    configLoaded = Signal(str)       # JSON string
    inboxUpdated = Signal(str)       # JSON string
    inspectStarted = Signal()
    inspectFinished = Signal(str)     # JSON string: {filename, file_path, width_mm, height_mm, previews, elapsed_ms}
    inspectFailed = Signal(str)
    dispatchStarted = Signal()
    dispatchFinished = Signal(str)    # JSON string: {job_name, elapsed_ms, dispatched}
    dispatchFailed = Signal(str)
    compositeStarted = Signal(str)   # job_name
    compositeFinished = Signal(str)  # JSON string: {status, message, job_name}
    compositeFailed = Signal(str)
    printStarted = Signal(str)       # job_name
    printFinished = Signal(str)      # JSON string: {status, message, job_name}
    printFailed = Signal(str)
    rasterLinkVisibilityChanged = Signal(bool)  # True = visible, False = hidden
    logMessage = Signal(str)
    historyUpdated = Signal(str)     # JSON string

    def __init__(self, config_path: str = "printflow/config/app_config.json"):
        super().__init__()
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isabs(config_path):
            self.config_path = os.path.join(base_dir, config_path)
        else:
            self.config_path = os.path.abspath(config_path)

        self.temp_dir = os.path.join(base_dir, "printflow", "temp_cache")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        self.current_config = self._read_config()
        self.job_history = []
        self._inspect_worker = None
        self._dispatch_worker = None
        self._composite_worker = None
        self._print_worker = None

        # Paleidžiame foninį RasterLink pop-up stebėtoją
        bridge.start()

    def _read_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return {
            "inbox_folder": os.path.join(base_dir, "INBOX_PRINT_FILES"),
            "products": []
        }

    # -----------------------------------------------------------------
    # CONFIGURATION SLOTS
    # -----------------------------------------------------------------
    @Slot()
    def loadConfig(self):
        self.current_config = self._read_config()
        cfg_str = json.dumps(self.current_config, ensure_ascii=False)
        self.configLoaded.emit(cfg_str)
        self.log(f"Konfigūracija užkrauta iš: {self.config_path}")

    @Slot(str)
    def saveConfigJson(self, json_str: str):
        try:
            data = json.loads(json_str)
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.current_config = data
            
            inbox = data.get("inbox_folder")
            if inbox:
                os.makedirs(inbox, exist_ok=True)
                
            self.configLoaded.emit(json.dumps(self.current_config, ensure_ascii=False))
            self.log("Konfigūracija sėkmingai išsaugota!")
            self.refreshInbox()
        except Exception as e:
            self.log(f"Klaida saugant konfigūraciją: {e}")

    # -----------------------------------------------------------------
    # INBOX SLOTS
    # -----------------------------------------------------------------
    @Slot()
    def refreshInbox(self):
        inbox_dir = self.current_config.get("inbox_folder", "")
        files_list = []
        
        if os.path.exists(inbox_dir):
            try:
                for entry in os.scandir(inbox_dir):
                    if entry.is_file() and entry.name.lower().endswith((".pdf", ".tif", ".tiff")):
                        size_mb = entry.stat().st_size / (1024 * 1024)
                        mod_time = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                        # Flexible keyword matching
                        matched_id = ""
                        matched_name = ""
                        fname_clean = "".join(c for c in entry.name.lower() if c.isalnum())
                        for p in self.current_config.get("products", []):
                            kw = p.get("keyword", "")
                            if kw:
                                kw_clean = "".join(c for c in kw.lower() if c.isalnum())
                                if kw_clean and kw_clean in fname_clean:
                                    matched_id = p["id"]
                                    matched_name = p["name"]
                                    break

                        files_list.append({
                            "filename": entry.name,
                            "filepath": entry.path,
                            "size_mb": round(size_mb, 2),
                            "modified": mod_time,
                            "matched_product_id": matched_id,
                            "matched_product_name": matched_name
                        })
            except Exception as e:
                self.log(f"Klaida nuskaitant Inbox: {e}")

        files_list.sort(key=lambda x: x["modified"], reverse=True)
        res = {
            "inbox_folder": inbox_dir,
            "count": len(files_list),
            "files": files_list
        }
        self.inboxUpdated.emit(json.dumps(res, ensure_ascii=False))

    # -----------------------------------------------------------------
    # INSPECT SLOTS (NON-BLOCKING QTHREAD)
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
    # DISPATCH SLOTS (NON-BLOCKING QTHREAD)
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
        self.log(f"Generuojamos plokštės darbui: {final_job_name} ({product['name']})...")

        def _do_dispatch(fpath, prod, jname, ch_w):
            t0 = time.time()
            job_out_dir = os.path.join(self.temp_dir, f"out_{int(time.time())}")
            ch_p = prod.get("choke_primer_px", 0)
            layers = prod.get("layers", ["CMYK"])
            hotfolders = prod.get("hotfolders", {})

            # Generate Plates
            plates = export_production_plates(
                source_pdf_path=fpath,
                job_name=jname,
                output_dir=job_out_dir,
                layers=layers,
                choke_white_px=ch_w,
                choke_primer_px=ch_p
            )

            # Copy to Hot Folders
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
        self.log(f"SĖKMINGAI NUSIŲSTA į {len(res['dispatched'])} Hot Folderius ({res['elapsed_ms']} ms)!")
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
        self.log(f"Klaida siunčiant į Hot Folderius: {err}")
        self.dispatchFailed.emit(err)

    # -----------------------------------------------------------------
    # RASTERLINK AUTOMATION SLOTS
    # -----------------------------------------------------------------
    @Slot(str)
    def startComposite(self, job_name: str):
        self.compositeStarted.emit(job_name)
        self.log(f"Pradedama RasterLink 7 kompozicija darbui: {job_name} (Quality režimas)...")

        def _do_comp(jname):
            success, msg = bridge.composite_and_quality(
                job_name_keyword=jname,
                timeout=40.0,
                status_cb=lambda m: self.log(f"[RasterLink] {m}")
            )
            return {"success": success, "message": msg, "job_name": jname}

        self._composite_worker = WorkerThread(_do_comp, job_name)
        self._composite_worker.finished.connect(lambda res: self._on_composite_finished(res))
        self._composite_worker.error.connect(lambda err: self._on_composite_error(err))
        self._composite_worker.start()

    def _on_composite_finished(self, res: dict):
        if res.get("success"):
            self.log(f"✅ KOMPOZICIJA PARUOŠTA: {res.get('message')}")
            self.compositeFinished.emit(json.dumps(res, ensure_ascii=False))
        else:
            self.log(f"⚠️ Kompozicijos įspėjimas: {res.get('message')}")
            self.compositeFailed.emit(res.get("message", "Nežinoma klaida"))

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
        if res.get("success"):
            self.log(f"🎉 SPAUSDINIMAS PALEISTAS: {res.get('message')}")
            self.printFinished.emit(json.dumps(res, ensure_ascii=False))
        else:
            self.log(f"⚠️ Spausdinimo paleidimo klaida: {res.get('message')}")
            self.printFailed.emit(res.get("message", "Klaida paleidžiant spaudą"))

    def _on_print_error(self, err: str):
        self.log(f"❌ Spausdinimo vykdymo klaida: {err}")
        self.printFailed.emit(err)

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
