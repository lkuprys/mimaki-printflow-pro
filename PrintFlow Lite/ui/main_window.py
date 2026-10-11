"""
PrintFlow Lite UI
-----------------
Moderni, kompaktiška ir patikima valdymo panelė.
Leidžia valdyti serverio aplankus, vietinį archyvą kompiuteryje, datų filtrus,
produktų thinning/thickening pikselius, kėlimo eiliškumą ir peržiūrėti jau apdorotų darbų atmintį.
"""

import os
import sys
import json
import html
import time
import re
import copy
import shutil
import logging
import traceback
from datetime import datetime
from typing import Optional, Tuple
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QFileDialog, QFrame, QStackedWidget, QButtonGroup, QListWidget, QListWidgetItem, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl, QSize
from PySide6.QtGui import QColor, QFont, QPixmap, QDesktopServices, QIcon

from core.prepress_lite import export_production_plates
from core.scanner_lite import scan_server_directory, path_exists_with_timeout, is_valid_date
from core.router_lite import HotFolderRouterLite
from core.registry_lite import JobRegistryLite
import updater
from ui.update_ui import AppUpdater
from ui.product_editor import ProductForm, normalize_product, describe_plates
from ui import theme as th
from ui.widgets import (
    Badge, Card, ConfirmDialog, Segmented, Switch, ToastHost, apply_theme, button, current_theme, divider,
    field, hbox, icon_button, label, make_icon, section, set_icon, tok
)


def get_app_base_dir() -> str:
    """Nustato pagrindinį programos aplanką (tiek .exe, tiek .py paleidimui)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    this_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(this_dir)
    if os.path.exists(os.path.join(parent, "config.json")):
        return parent
    return this_dir


def _is_foreign_os_path(path: str) -> bool:
    """Windows kelias (C:\\..., \\\\server\\...) ne Windows sistemoje – laikomas nepasiekiamu."""
    if os.name == "nt" or not path:
        return False
    return bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith("\\\\")


def is_dir_writable(path: str) -> bool:
    """Patikrina ar aplankas egzistuoja (arba gali būti sukurtas) ir į jį galima rašyti be UAC."""
    if not path or _is_foreign_os_path(path):
        return False
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, f".perm_test_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False


def get_user_data_dir() -> str:
    """Vartotojo duomenų aplankas, kuriam niekada nereikia Administratoriaus teisių."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "PodbasePrintFlowLite")


def resolve_writable_config_path(config_path: str) -> str:
    """
    Jei programa įdiegta į apsaugotą vietą (pvz. C:\\Program Files), config.json ir
    jobs_registry.json perkeliami į %LOCALAPPDATA%\\PodbasePrintFlowLite (be UAC).
    Esama konfigūracija nukopijuojama, kad nustatymai nepasimestų.
    """
    folder = os.path.dirname(os.path.abspath(config_path))
    if is_dir_writable(folder):
        return config_path
    user_dir = get_user_data_dir()
    os.makedirs(user_dir, exist_ok=True)
    new_path = os.path.join(user_dir, os.path.basename(config_path))
    if not os.path.exists(new_path) and os.path.exists(config_path):
        try:
            shutil.copyfile(config_path, new_path)
        except Exception:
            pass
    return new_path


def get_safe_default_storage_dir() -> str:
    """Suranda arba sukuria saugų vietinį aplanką failų kaupimui (be UAC / Admin reikalavimo)."""
    candidates = []
    # 1. Jei yra diskas E:\\ (pvz. produkcijos / projektų diskas):
    if os.name == "nt" and os.path.exists("E:\\"):
        candidates.append(r"E:\Podbase_PrintFlow_Storage")
    # 2. Vartotojo profilis: %USERPROFILE%\Podbase_PrintFlow_Storage
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    candidates.append(os.path.join(home, "Podbase_PrintFlow_Storage"))
    # 3. %LOCALAPPDATA%\PodbasePrintFlowLite\storage
    candidates.append(os.path.join(get_user_data_dir(), "storage"))
    # 4. Šalia programos esantis aplankas:
    candidates.append(os.path.join(get_app_base_dir(), "local_storage"))

    for cand in candidates:
        if is_dir_writable(cand):
            return cand
    return candidates[1]


def resolve_storage_dir(preferred: str) -> Tuple[str, str]:
    """
    Grąžina (naudojamas_kelias, įspėjimas). Jei nurodyta talpykla nepasiekiama ar
    neįrašoma (pvz. kitame PC nėra E: disko) – automatiškai parenkama vieta %USERPROFILE%.
    """
    if preferred and is_dir_writable(preferred):
        return preferred, ""
    fallback = get_safe_default_storage_dir()
    if preferred:
        return fallback, f"Talpykla '{preferred}' nepasiekiama arba neįrašoma – naudojama '{fallback}'"
    return fallback, ""


def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


DEFAULT_CONFIG = {
  "server_inbox_folder": r"\\192.168.1.143\podbase-hotfolder\BENDRAS_PODBASE_HOTFOLDER",
  "local_fallback_inbox": r"E:\Projektai\TEST\INBOX_PRINT_FILES",
  "local_storage_folder": r"E:\Podbase_PrintFlow_Storage",
  "rejects_folder": "",
  "auto_scan": False,
  "scan_interval_sec": 10,
  "inter_layer_delay_sec": 0.5,
  "filter_date_mode": "today_only",
  "custom_start_date": "",
  "min_file_age_sec": 5,
  "max_attempts": 3,
  "plate_dpi": 300,
  "server_timeout_sec": 8,
  "wait_for_pickup": True,
  "pickup_timeout_sec": 60,
  "theme": "light",
  "github_repo": "lkuprys/mimaki-printflow-pro",
  "auto_check_updates": True,
  "products": [
    {
      "id": "magnetic_wallet",
      "name": "Magnetic Wallet",
      "keywords": [
        "magnetic-wallet",
        "wallet",
        "MW"
      ],
      "layers": [
        "White",
        "CMYK"
      ],
      "dispatch_order": [
        "White",
        "CMYK"
      ],
      "choke_white_px": 1,
      "choke_primer_px": 0,
      "hotfolders": {
        "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
        "White": r"C:\MijCtrl\Hot\RH WHITE",
        "Primer": ""
      }
    },
    {
      "id": "magsafe_ring_holders",
      "name": "MagSafe Ring Holders",
      "keywords": [
        "magsafe-ring-holders",
        "ring-holder",
        "RH"
      ],
      "layers": [
        "Primer",
        "White",
        "CMYK"
      ],
      "dispatch_order": [
        "Primer",
        "White",
        "CMYK"
      ],
      "choke_white_px": 1,
      "choke_primer_px": 0,
      "hotfolders": {
        "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
        "White": r"C:\MijCtrl\Hot\RH WHITE",
        "Primer": r"C:\MijCtrl\Hot\RH PRIMER"
      }
    },
    {
      "id": "clear_cases_v2",
      "name": "Clear Cases MagSafe V2",
      "keywords": [
        "clear-cases-magsafe-v2",
        "clear-cases",
        "CC"
      ],
      "layers": [
        "Primer",
        "White",
        "CMYK"
      ],
      "dispatch_order": [
        "Primer",
        "White",
        "CMYK"
      ],
      "choke_white_px": 1,
      "choke_primer_px": 0,
      "hotfolders": {
        "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
        "White": r"C:\MijCtrl\Hot\RH WHITE",
        "Primer": r"C:\MijCtrl\Hot\RH PRIMER"
      }
    },
    {
      "id": "clear_cases_v1",
      "name": "Clear Cases V1",
      "keywords": [
        "clear-cases-v1"
      ],
      "layers": [
        "Primer",
        "White",
        "CMYK"
      ],
      "dispatch_order": [
        "Primer",
        "White",
        "CMYK"
      ],
      "choke_white_px": 1,
      "choke_primer_px": 0,
      "hotfolders": {
        "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
        "White": r"C:\MijCtrl\Hot\RH WHITE",
        "Primer": r"C:\MijCtrl\Hot\RH PRIMER"
      }
    },
    {
      "id": "clear_cases_v0",
      "name": "Clear Cases V0",
      "keywords": [
        "clear-cases-v0"
      ],
      "layers": [
        "Primer",
        "White",
        "CMYK"
      ],
      "dispatch_order": [
        "Primer",
        "White",
        "CMYK"
      ],
      "choke_white_px": 1,
      "choke_primer_px": 0,
      "hotfolders": {
        "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
        "White": r"C:\MijCtrl\Hot\RH WHITE",
        "Primer": r"C:\MijCtrl\Hot\RH PRIMER"
      }
    }
  ]
}


def resolve_target_date(filter_mode: str, custom_date: str) -> Tuple[str, str]:
    """
    Grąžina (data, įspėjimas).
    - 'today_only': VISADA šiandienos data (net jei programa veikia per vidurnaktį
      ar config.json liko vakarykštė data).
    - kiti režimai: operatoriaus nurodyta pradžios data, jei ji teisinga, kitaip šiandiena.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if filter_mode == "today_only":
        return today, ""
    custom_date = (custom_date or "").strip()
    if not custom_date:
        return today, ""
    if is_valid_date(custom_date):
        return custom_date, ""
    return today, f"Neteisinga data '{custom_date}' (formatas YYYY-MM-DD) – naudojama šiandiena {today}"


class WorkerScanProcess(QThread):
    log_signal = Signal(str)
    job_processed = Signal(str, dict)
    scan_finished = Signal(int, int)  # total_found, new_processed
    source_state = Signal(str, str)   # būsena (success/warning/error), tekstas
    halted = Signal(str)              # skenavimas sustabdytas dėl RasterLink / HotFolderio problemos

    def __init__(self, config: dict, registry: JobRegistryLite, router: HotFolderRouterLite):
        super().__init__()
        # Gilioji kopija: UI gali keisti konfigūraciją, kol gija dirba
        self.config = copy.deepcopy(config)
        self.registry = registry
        self.router = router
        self._is_running = True

    def stop(self):
        self._is_running = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    def _check_registry(self):
        if self.registry.last_error:
            self._log(f"❌ {self.registry.last_error}")

    def run(self):
        total, new_count = 0, 0
        try:
            total, new_count = self._run_scan()
        except Exception as e:
            # Zero Silent Failures: jokia išimtis neišeina iš gijos be pranešimo
            self._log(f"❌ Netikėta skenavimo klaida: {e}")
            logging.getLogger("printflow").error("Worker exception:\n%s", traceback.format_exc())
        finally:
            self.scan_finished.emit(total, new_count)

    def _resolve_source_dir(self) -> str:
        server_dir = (self.config.get("server_inbox_folder") or "").strip()
        timeout = float(self.config.get("server_timeout_sec", 8) or 8)
        reachable = path_exists_with_timeout(server_dir, timeout) if server_dir else False
        if reachable:
            self.source_state.emit("success", "Serveris pasiekiamas")
            return server_dir

        reason = "neatsako (tinklo timeout)" if reachable is None else "nepasiekiamas"
        fallback = (self.config.get("local_fallback_inbox") or "").strip()
        if fallback and path_exists_with_timeout(fallback, timeout):
            self._log(f"⚠️ Serveris {reason}: {server_dir}. Naudojamas vietinis rezervas: {fallback}")
            self.source_state.emit("warning", "Naudojamas vietinis rezervas")
            return fallback
        self._log(f"⚠️ Serverio aplankas {reason}: {server_dir or '(nenurodytas)'}")
        self.source_state.emit("error", "Serveris nepasiekiamas" if server_dir else "Serveris nenurodytas")
        return ""

    def _scan_folder(self, root: str, label: str, filter_mode: str, target_date: str) -> list:
        errors, unstable = [], []
        found = scan_server_directory(
            root_dir=root,
            products=self.config.get("products", []),
            filter_mode=filter_mode,
            target_date=target_date,
            min_file_age_sec=float(self.config.get("min_file_age_sec", 5) or 0),
            errors=errors,
            skipped_unstable=unstable,
            should_continue=lambda: self._is_running,
        )
        for e in errors[:5]:
            self._log(f"⚠️ {label}: {e}")
        if len(errors) > 5:
            self._log(f"⚠️ {label}: ... ir dar {len(errors) - 5} skenavimo klaidų")
        if unstable:
            self._log(f"⏳ {label}: {len(unstable)} failas(-ai) dar įkeliami – bus paimti kitame cikle")
        return found

    def _resolve_rejects_dir(self) -> str:
        rej = (self.config.get("rejects_folder") or "").strip()
        if not rej:
            return ""
        timeout = float(self.config.get("server_timeout_sec", 8) or 8)
        ok = path_exists_with_timeout(rej, timeout)
        if ok:
            return rej
        reason = "neatsako (tinklo timeout)" if ok is None else "nepasiekiamas"
        self._log(f"⚠️ Brokų aplankas {reason}: {rej}")
        return ""

    @staticmethod
    def _as_reject(item: dict) -> Optional[dict]:
        """Brokas: unikalus įrašas pagal failą (kelias + dydis + laikas), nes pavadinimas dažniausiai
        sutampa su originalo užsakymu. Į RasterLink keliama su priešdėliu BROKAS_."""
        try:
            st = os.stat(item["filepath"])
        except OSError:
            return None
        item = dict(item)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(st.st_mtime))
        item["source"] = "brokas"
        item["fingerprint"] = f"{os.path.normcase(os.path.normpath(item['filepath']))}|{st.st_size}|{int(st.st_mtime)}"
        item["job_id"] = f"BROKAS_{item['job_name']}_{stamp}"
        item["out_name"] = f"BROKAS_{item['job_name']}"
        return item

    def _run_scan(self) -> Tuple[int, int]:
        server_dir = self._resolve_source_dir()
        rejects_dir = self._resolve_rejects_dir()
        if not server_dir and not rejects_dir:
            return 0, 0

        filter_mode = self.config.get("filter_date_mode", "today_only")
        target_date, date_warn = resolve_target_date(filter_mode, self.config.get("custom_start_date", ""))
        if date_warn:
            self._log(f"⚠️ {date_warn}")

        local_storage_base, storage_warn = resolve_storage_dir(self.config.get("local_storage_folder", ""))
        if storage_warn:
            self._log(f"⚠️ {storage_warn}")

        max_attempts = int(self.config.get("max_attempts", 3) or 3)
        dpi = int(self.config.get("plate_dpi", 300) or 300)

        found_jobs = []
        if server_dir:
            self._log(f"🔍 Skenuojamas serveris: {server_dir}")
            self._log(f"   📅 Filtro data: {target_date} ({filter_mode}) | 📁 Vietinė talpykla: {local_storage_base}")
            found_jobs += self._scan_folder(server_dir, "Serveris", filter_mode, target_date)
        if rejects_dir and self._is_running:
            self._log(f"🔍 Skenuojamas brokų aplankas: {rejects_dir}")
            for it in self._scan_folder(rejects_dir, "Brokai", filter_mode, target_date):
                rej = self._as_reject(it)
                if rej:
                    found_jobs.append(rej)

        new_count = 0
        for item in found_jobs:
            if not self._is_running:
                left = len(found_jobs) - found_jobs.index(item)
                self._log(f"⏹️ Skenavimas sustabdytas – {left} failas(-ai) liko neapdoroti.")
                break
            if item.get("source") == "brokas":
                if self.registry.is_fingerprint_processed(item["fingerprint"]):
                    continue
            elif self.registry.is_file_processed(item["filepath"]):
                continue
            new_count += 1
            jid = item.get("job_id") or item.get("job_name", "?")
            try:
                self._process_job(item, target_date, local_storage_base, max_attempts, dpi)
            except Exception as e:
                self._log(f"❌ Netikėta klaida apdorojant '{jid}': {e}")
                logging.getLogger("printflow").error("Job exception:\n%s", traceback.format_exc())
                self.registry.record_failure(jid, {"filepath": item.get("filepath", ""),
                                                   "source": item.get("source", "serveris"),
                                                   "fingerprint": item.get("fingerprint", "")},
                                             str(e), max_attempts)
                self._emit_job(jid)
            self._check_registry()

        return len(found_jobs), new_count

    def _emit_job(self, jname: str):
        job = self.registry.get_job(jname)
        if job is not None:
            self.job_processed.emit(jname, job)

    def _fail(self, jname: str, base_data: dict, message: str, max_attempts: int):
        status = self.registry.record_failure(jname, base_data, message, max_attempts)
        if status == "failed":
            self._log(f"⛔ '{jname}' nepavyko {max_attempts} kartus – automatiškai nebebandoma. "
                      f"Pataisykite priežastį ir spauskite '🔁 Pakartoti pažymėtą'.")
        else:
            self._log(f"   ↻ '{jname}' bus bandoma dar kartą kitame cikle.")
        self._emit_job(jname)

    def _process_job(self, item: dict, target_date: str, local_storage_base: str, max_attempts: int, dpi: int):
        filepath = item["filepath"]
        jname = item.get("job_id") or item["job_name"]       # įrašo ID atmintyje
        out_name = item.get("out_name") or item["job_name"]  # failų vardai plokštėse / HotFolderiuose
        is_reject = item.get("source") == "brokas"
        prod = item["product"]
        prod_id = prod.get("id") or "produktas"
        prod_name = prod.get("name") or prod_id
        order_date = item.get("order_date") or target_date

        base_data = {
            "filepath": filepath,
            "product_id": prod_id,
            "product_name": prod_name,
            "bid": item.get("bid", ""),
            "pid": item.get("pid", ""),
            "order_date": order_date,
            "source": "brokas" if is_reject else "serveris",
        }
        if is_reject:
            base_data["fingerprint"] = item["fingerprint"]

        kind = "BROKAS (perspausdinimas)" if is_reject else "NAUJAS UŽSAKYMAS"
        self._log(f"\n📦 RASTAS {kind}: '{item['job_name']}' [{prod_name}] (BID: {item.get('bid') or '-'})")

        # -------------------------------------------------------------
        # ŽINGSNIS 1: ATSISIUNTIMAS IR KAUPIMAS VIETINIAME KOMPIUTERYJE (.part ➔ .pdf)
        # -------------------------------------------------------------
        local_orders_dir = os.path.join(local_storage_base, "brokai" if is_reject else "originalus_uzsakymai",
                                        order_date, prod_id)
        if is_reject:
            local_orders_dir = os.path.join(local_orders_dir, jname)  # originalas su tuo pačiu vardu neperrašomas
        local_pdf_path = os.path.join(local_orders_dir, item["filename"])
        temp_download = local_pdf_path + ".part"
        try:
            os.makedirs(local_orders_dir, exist_ok=True)
            self._log("   ⬇️ [1/3] Siunčiamas failas iš serverio į vietinį kompiuterį...")
            src_size = os.path.getsize(filepath)
            shutil.copyfile(filepath, temp_download)
            got = os.path.getsize(temp_download)
            if got != src_size:
                raise IOError(f"nepilnas atsisiuntimas: {got} B iš {src_size} B")
            # Failas serveryje neturi keistis siuntimo metu (dar kopijuojamas į serverį?)
            if os.path.getsize(filepath) != src_size:
                raise IOError("failas serveryje pasikeitė siuntimo metu")
            os.replace(temp_download, local_pdf_path)
            self._log(f"   💾 Originalas išsaugotas kompiuteryje: {local_pdf_path}")
        except Exception as e:
            try:
                if os.path.exists(temp_download):
                    os.remove(temp_download)
            except Exception:
                pass
            self._log(f"❌ Klaida siunčiant failą iš serverio: {e}")
            self._fail(jname, base_data, f"Siuntimo klaida: {e}", max_attempts)
            return

        if not self._is_running:
            # Sustabdyta po atsisiuntimo: nieko negeneruojame ir neregistruojame –
            # failas bus paimtas kito skenavimo metu.
            self._log(f"⏹️ Sustabdyta – '{jname}' nebus generuojamas.")
            return

        # Registruojame pradžią su vietiniu originalo keliu
        data = dict(base_data)
        data.update({"local_pdf_path": local_pdf_path, "status": "processing", "message": ""})
        self.registry.register_or_update(jname, data)

        # -------------------------------------------------------------
        # ŽINGSNIS 2: PREPRESS PLOKŠČIŲ GENERAVIMAS VIETINIAME KOMPIUTERYJE (SSD)
        # -------------------------------------------------------------
        local_plates_dir = os.path.join(local_storage_base, "paruostos_plokstes", jname)
        try:
            layers = prod.get("layers") or ["Primer", "White", "CMYK"]
            choke_w = int(prod.get("choke_white_px", 1))
            choke_p = int(prod.get("choke_primer_px", 0))

            self._log(f"   ⚙️ [2/3] Generuojamos plokštės vietoje ({dpi} DPI, White px={choke_w}, Primer px={choke_p})...")
            warnings = []
            plates = export_production_plates(
                source_pdf_path=local_pdf_path,  # <--- NUSKAITOMA IŠ VIETINIO SSD!
                job_name=out_name,
                output_dir=local_plates_dir,     # <--- IŠSAUGOMA VIETINIAME KOMPIUTERYJE!
                layers=layers,
                choke_white_px=choke_w,
                choke_primer_px=choke_p,
                dpi=dpi,
                warnings_out=warnings,
            )
            for w in warnings:
                self._log(f"   ⚠️ {w}")
            self._log(f"   ✔️ Geometrija (Media/Crop/TrimBox) ir {dpi} DPI patikrinti – plokštės sutampa 1:1")
        except Exception as e:
            self._log(f"❌ Klaida generuojant plokštes '{jname}': {e}")
            self._fail(jname, base_data, f"Prepress klaida: {e}", max_attempts)
            return

        if not self._is_running:
            # Plokštės paruoštos, bet nekeliame – kitame skenavime bus pakartota nuo pradžių
            self.registry.register_or_update(jname, {"status": "retry", "message": "Sustabdyta prieš kėlimą"})
            self._log(f"⏹️ Sustabdyta – '{jname}' plokštės paruoštos, bet neįkeltos (bus pakartota).")
            self._emit_job(jname)
            return

        # -------------------------------------------------------------
        # ŽINGSNIS 3: PERKĖLIMAS Į HOT FOLDERIUS IŠ VIETINIO KOMPIUTERIO
        # -------------------------------------------------------------
        dispatch_order = prod.get("dispatch_order") or ["Primer", "White", "CMYK"]
        delay = prod.get("inter_layer_delay_sec", self.config.get("inter_layer_delay_sec", 0.5))
        expected = self.router.expected_layers(plates, prod)
        missing_hf = [l for l in plates if l not in expected]
        if missing_hf:
            self._log(f"   ⚠️ Sluoksniams {missing_hf} nenurodytas Hotfolderis – jie nebus keliami")

        if not expected:
            self._log(f"❌ '{jname}': nė vienam sluoksniui nenurodytas Hotfolderis")
            self._fail(jname, base_data, "Nenurodyti Hotfolderiai", 1)
            return

        self._log(f"   🚀 [3/3] Keliama iš kompiuterio į Hot Folderius ({' ➔ '.join(dispatch_order)}, pauzė={delay}s)...")
        dispatched = self.router.dispatch_plates(
            job_name=out_name,
            plate_files=plates,
            product_config=prod,
            dispatch_order=dispatch_order,
            inter_layer_delay_sec=delay,
            log_cb=self._log,
            wait_for_pickup=bool(self.config.get("wait_for_pickup", True)),
            pickup_timeout_sec=_safe_float(self.config.get("pickup_timeout_sec", 60), 60.0),
        )
        sent = [d["layer"] for d in dispatched]
        stop_reason = self.router.last_stop_reason
        if stop_reason and sent:
            # RasterLink nepaima plokščių arba įkėlimas nutrūko – kiti užsakymai nekeliami,
            # kitaip RasterLink vėliau rastų kelių užsakymų plokštes vienu metu ir susimaišytų seka.
            self._is_running = False
            self.halted.emit(stop_reason)

        # -------------------------------------------------------------
        # ŽINGSNIS 4: REGISTRACIJA IR ATMINTIS
        # -------------------------------------------------------------
        common = {
            "dispatched_plates": sent,
            "local_plates_dir": local_plates_dir,
            "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if set(sent) == set(expected):
            common.update({"status": "dispatched", "message": stop_reason})
            self.registry.register_or_update(jname, common)
            self._log(f"✅ SĖKMINGAI PARUOŠTA IR ĮKELTA Į RASTERLINK: '{jname}'")
            self._emit_job(jname)
        elif not sent:
            # Niekas neiškeliavo – saugu bandyti dar kartą (nebus dublikatų)
            self.registry.register_or_update(jname, common)
            self._log(f"❌ '{jname}': nė viena plokštė neįkelta į Hotfolderius")
            self._fail(jname, base_data, "Nepavyko įkelti į Hotfolderius", max_attempts)
        else:
            # Dalis sluoksnių jau RasterLink'e – automatinis kartojimas sukeltų dublikatus
            missing = [l for l in expected if l not in sent]
            common.update({"status": "dispatch_failed",
                           "message": f"Įkelta tik {sent}, trūksta {missing}. {stop_reason}".strip()})
            self.registry.register_or_update(jname, common)
            self._log(f"⛔ '{jname}': įkelta tik {sent}, NEĮKELTA {missing}. "
                      f"Reikia operatoriaus sprendimo (RasterLink'e jau yra dalis sluoksnių).")
            self._emit_job(jname)


APP_VERSION = updater.CURRENT_VERSION

STATUS_VIEW = {
    "dispatched": ("Įkelta", "success"),
    "processing": ("Ruošiama", "warning"),
    "error": ("Klaida · bus kartojama", "warning"),
    "failed": ("Nepavyko", "error"),
    "dispatch_failed": ("Įkelta dalinai", "error"),
    "interrupted": ("Nutraukta", "error"),
    "retry": ("Laukia pakartojimo", "info"),
}

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def classify_log(text: str) -> Tuple[str, str]:
    """Žurnalo eilutė ➔ (lygis, švarus tekstas be emoji)."""
    t = text.strip()
    level = "neutral"
    if t.startswith(("✅", "🟢", "🏁")):
        level = "success"
    elif t.startswith(("❌", "⛔")):
        level = "error"
    elif t.startswith(("⚠️", "⏳", "↻")):
        level = "warning"
    elif t.startswith(("📦", "▶️", "🔍", "🔁")):
        level = "info"
    t = t.replace("➔", "→")
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"^\s*(\[\+\]\s*)?", "", t)
    return level, re.sub(r"\s{2,}", " ", t).strip()


def _table(headers) -> QTableWidget:
    tbl = QTableWidget()
    tbl.setColumnCount(len(headers))
    tbl.setHorizontalHeaderLabels([h.upper() for h in headers])
    tbl.setEditTriggers(QTableWidget.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectRows)
    tbl.setSelectionMode(QTableWidget.SingleSelection)
    tbl.verticalHeader().setVisible(False)
    tbl.verticalHeader().setDefaultSectionSize(40)
    tbl.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    tbl.horizontalHeader().setHighlightSections(False)
    tbl.setShowGrid(False)
    tbl.setFocusPolicy(Qt.NoFocus)
    tbl.setWordWrap(False)
    return tbl


class MainWindowLite(QMainWindow):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        base_dir = get_app_base_dir()
        if not config_path:
            config_path = os.path.join(base_dir, "config.json")
        elif not os.path.isabs(config_path):
            config_path = os.path.join(base_dir, config_path)

        # Be UAC: jei programos aplankas neįrašomas – naudojamas %LOCALAPPDATA%
        self._startup_messages = []
        writable_path = resolve_writable_config_path(config_path)
        if os.path.normcase(writable_path) != os.path.normcase(config_path):
            self._startup_messages.append(
                f"ℹ️ Programos aplankas neįrašomas – nustatymai ir atmintis saugomi: {os.path.dirname(writable_path)}"
            )
        self.config_path = writable_path
        self.config = self.load_config()

        registry_path = os.path.join(os.path.dirname(self.config_path), "jobs_registry.json")
        self.registry = JobRegistryLite(registry_path)
        for w in self.registry.load_warnings:
            self._startup_messages.append(f"⚠️ {w}")
        self._interrupted = self.registry.mark_interrupted()
        if self._interrupted:
            self._startup_messages.append(
                f"⚠️ {len(self._interrupted)} užsakymas(-ai) nutraukti ankstesnio paleidimo metu: "
                + ", ".join(self._interrupted[:10])
            )
        self.router = HotFolderRouterLite(default_delay_sec=self.config.get("inter_layer_delay_sec", 0.5))

        self.worker: Optional[WorkerScanProcess] = None
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.start_scan)
        self._last_scan = "—"
        self._product_dirty = False
        self._product_index = -1  # -1 = naujas produktas formoje
        self._path_checkers = []

        app = QApplication.instance()
        th.load_fonts()
        if app is not None:
            app.setFont(QFont(th.FONT_FAMILY, 10))
            apply_theme(app, self.config.get("theme", "light"))

        self.setWindowIcon(QIcon(th.resource_path("assets", "podbase.ico")))
        self.init_ui()
        self.updater = AppUpdater(self)
        self.updater.state_changed.connect(self._on_update_state)
        if not os.environ.get("PRINTFLOW_NO_AUTO_UPDATE"):
            self.updater.start()
        for m in self._startup_messages:
            self.log(m)
        if self._interrupted:
            QTimer.singleShot(300, lambda: self.toasts.show(
                "error", "Yra nutrauktų užsakymų",
                "Patikrinkite RasterLink ir, jei reikia, pakartokite juos skiltyje Istorija.", sticky=True))

        # Starto metu stebėjimas IŠJUNGTAS (auto_scan: false) – laukiama operatoriaus.
        if self.config.get("auto_scan", False):
            QTimer.singleShot(1000, self.start_monitoring)

    # =================================================================
    # Konfigūracija
    # =================================================================
    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if isinstance(cfg, dict) and cfg.get("products"):
                    for k, v in DEFAULT_CONFIG.items():
                        if k != "products":
                            cfg.setdefault(k, copy.deepcopy(v))
                    if not cfg.get("local_storage_folder"):
                        cfg["local_storage_folder"] = get_safe_default_storage_dir()
                    return cfg
                self._startup_messages.append("⚠️ config.json neturi produktų – naudojama numatytoji konfigūracija")
            except Exception as e:
                # NIEKADA neperrašome sugadinto failo be kopijos (jame gali būti hotfolderių keliai)
                backup = f"{self.config_path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
                try:
                    shutil.copyfile(self.config_path, backup)
                except Exception:
                    backup = "(nepavyko nukopijuoti)"
                self._startup_messages.append(
                    f"⚠️ config.json sugadintas ({e}). Kopija: {backup}. Naudojama numatytoji konfigūracija."
                )
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["local_storage_folder"] = get_safe_default_storage_dir()
        self._write_config_file(cfg)
        return cfg

    def _write_config_file(self, cfg: dict) -> Optional[str]:
        """Atominis config.json įrašymas. Grąžina klaidos tekstą arba None."""
        tmp = self.config_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.config_path)
            return None
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return str(e)

    def save_config(self, quiet: bool = False) -> bool:
        err = self._write_config_file(self.config)
        if err is None:
            if not quiet:
                self.log("Nustatymai išsaugoti.")
            return True
        self.log(f"❌ Nepavyko išsaugoti nustatymų: {err}")
        self.toasts.show("error", "Nepavyko išsaugoti nustatymų", err, sticky=True)
        return False

    # =================================================================
    # Karkasas
    # =================================================================
    def init_ui(self):
        self.setWindowTitle("Podbase PrintFlow Lite")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 820)

        central = QWidget()
        central.setObjectName("page")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Viršutinė juosta (56 px) ---------------------------------
        self.topbar = QFrame()
        self.topbar.setObjectName("topbar")
        self.topbar.setFixedHeight(56)
        tb = QHBoxLayout(self.topbar)
        tb.setContentsMargins(24, 0, 16, 0)
        tb.setSpacing(12)
        logo = QLabel()
        pm = QPixmap(th.resource_path("assets", "podbase_icon.png"))
        if not pm.isNull():
            logo.setPixmap(self._scaled_logo(pm, 24))
            tb.addWidget(logo)
        tb.addWidget(label("Podbase PrintFlow Lite", "appname"))
        tb.addStretch(1)
        self.badge_monitor = Badge("Stebėjimas sustabdytas", "neutral")
        tb.addWidget(self.badge_monitor)
        self.badge_server = Badge("Serveris netikrintas", "neutral")
        tb.addWidget(self.badge_server)
        ver = label(f"v{APP_VERSION}", "caption")
        ver.setFont(th.tnum_font(ver.font()))
        tb.addWidget(ver)
        tb.addWidget(icon_button("log", "Atidaryti žurnalo failą", self.open_log_file))
        tb.addWidget(icon_button("refresh", "Tikrinti atnaujinimus", lambda: self.updater.check(manual=True)))
        self.btn_theme = icon_button("moon", "Perjungti temą", self.toggle_theme)
        tb.addWidget(self.btn_theme)
        root.addWidget(self.topbar)

        # --- Skirtukai (44 px, pabraukimas) ----------------------------
        self.tabbar = QFrame()
        self.tabbar.setObjectName("tabbar")
        self.tabbar.setFixedHeight(44)
        tl = QHBoxLayout(self.tabbar)
        tl.setContentsMargins(24, 0, 24, 0)
        tl.setSpacing(24)
        self.tab_group = QButtonGroup(self)
        self.pages = QStackedWidget()
        for i, (title, builder) in enumerate((
            ("Stebėjimas", self._build_monitor_page),
            ("Istorija", self._build_history_page),
            ("Produktai", self._build_products_page),
            ("Nustatymai", self._build_settings_page),
        )):
            b = QPushButton(title)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            tl.addWidget(b)
            self.pages.addWidget(builder())
        tl.addStretch(1)
        self.tab_group.button(0).setChecked(True)
        self.tab_group.idClicked.connect(self._on_tab)
        root.addWidget(self.tabbar)
        root.addWidget(self.pages, 1)

        self.toasts = ToastHost(self, lambda: self.topbar.height() + self.tabbar.height())
        self._refresh_theme_button()

        self.log(f"PrintFlow Lite v{APP_VERSION} paleista.")
        self.log(f"Serverio aplankas: {self.config.get('server_inbox_folder')}")
        self.log(f"Vietinė talpykla: {self.config.get('local_storage_folder')}")
        self.log(f"Produktų: {len(self.config.get('products', []))}")
        self.log("Automatinis stebėjimas išjungtas. Spauskite „Pradėti stebėjimą“ arba „Skenuoti dabar“.")

    def _page(self) -> Tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        return w, lay

    def _on_tab(self, idx: int):
        if self.pages.currentIndex() == 2 and idx != 2 and not self._confirm_discard_product():
            self.tab_group.button(2).setChecked(True)
            return
        self.pages.setCurrentIndex(idx)
        if idx == 1:
            self.populate_registry_table()
        elif idx == 3:
            self._check_paths_async()

    # =================================================================
    # 1. Stebėjimas
    # =================================================================
    def _build_monitor_page(self) -> QWidget:
        page, lay = self._page()

        head = QHBoxLayout()
        head.setSpacing(8)
        tcol = QVBoxLayout()
        tcol.setSpacing(4)
        tcol.addWidget(label("Stebėjimas", "title"))
        self.lbl_monitor_hint = label("Stebėjimas išjungtas. Failai iš serverio neimami, kol jo nepaleisite.",
                                      "secondary", wrap=True)
        tcol.addWidget(self.lbl_monitor_hint)
        head.addLayout(tcol, 1)
        self.btn_scan_now = button("Skenuoti dabar", icon="refresh", on_click=self.start_scan)
        self.btn_scan_now.setProperty("size", "large")
        head.addWidget(self.btn_scan_now, 0, Qt.AlignBottom)
        self.btn_toggle_monitor = button("Pradėti stebėjimą", "primary", "play", "large", self.toggle_monitoring)
        self.btn_toggle_monitor.setMinimumWidth(210)
        head.addWidget(self.btn_toggle_monitor, 0, Qt.AlignBottom)
        lay.addLayout(head)

        # Būsenos juosta
        stats = Card(margins=(20, 16, 20, 16), spacing=0)
        row = QHBoxLayout()
        row.setSpacing(24)

        def stat(title, widget):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(section(title))
            col.addWidget(widget)
            return col

        self.lbl_stat_today = label("0", "subtitle")
        self.lbl_stat_today.setFont(th.tnum_font(self.lbl_stat_today.font()))
        self.lbl_stat_attention = label("0", "subtitle")
        self.lbl_stat_attention.setFont(th.tnum_font(self.lbl_stat_attention.font()))
        self.lbl_stat_last = label("—", "subtitle")
        self.lbl_stat_last.setFont(th.tnum_font(self.lbl_stat_last.font()))

        self.seg_date = Segmented(["Šiandien", "Nuo datos", "Visos"],
                                  {"today_only": 0, "today_and_newer": 1}.get(self.config.get("filter_date_mode"), 2))
        self.seg_date.changed.connect(self.on_date_mode_changed)
        self.txt_target_date = QLineEdit(self.config.get("custom_start_date") or datetime.now().strftime("%Y-%m-%d"))
        self.txt_target_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_target_date.setFixedWidth(130)
        self.txt_target_date.setFont(th.tnum_font(self.txt_target_date.font()))
        self.txt_target_date.setToolTip("Pradžios data režimui „Nuo datos“")
        self.txt_target_date.editingFinished.connect(self._on_target_date_edited)
        date_row = hbox(self.seg_date, self.txt_target_date, spacing=8)
        self._sync_date_field()

        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(3, 300)
        self.spn_interval.setSuffix(" s")
        self.spn_interval.setFixedWidth(100)
        self.spn_interval.setValue(_safe_int(self.config.get("scan_interval_sec", 10), 10))
        self.spn_interval.valueChanged.connect(self.on_interval_changed)

        row.addLayout(stat("Įkelta šiandien", self.lbl_stat_today))
        row.addWidget(self._vline())
        row.addLayout(stat("Reikia dėmesio", self.lbl_stat_attention))
        row.addWidget(self._vline())
        row.addLayout(stat("Paskutinis skenavimas", self.lbl_stat_last))
        row.addWidget(self._vline())
        dcol = QVBoxLayout()
        dcol.setSpacing(6)
        dcol.addWidget(section("Datos filtras"))
        dcol.addLayout(date_row)
        row.addLayout(dcol)
        row.addLayout(stat("Tikrinti kas", self.spn_interval))
        row.addStretch(1)
        stats.body.addLayout(row)
        lay.addWidget(stats)

        # Žurnalas
        log_card = Card(margins=(20, 16, 12, 12), spacing=8)
        log_card.body.addLayout(hbox(section("Veiklos žurnalas"), None,
                                     button("Išvalyti vaizdą", "ghost", size="small",
                                            on_click=lambda: self.txt_log.clear())))
        self.txt_log = QTextEdit()
        self.txt_log.setObjectName("log")
        self.txt_log.setReadOnly(True)
        self.txt_log.document().setMaximumBlockCount(5000)  # 24/7 darbas – atmintis neauga be galo
        self.txt_log.document().setDocumentMargin(0)
        log_card.body.addWidget(self.txt_log, 1)
        lay.addWidget(log_card, 1)
        self._update_stats()
        return page

    def _vline(self) -> QFrame:
        f = QFrame()
        f.setObjectName("divider")
        f.setFixedWidth(1)
        f.setStyleSheet("max-height: 10000px;")
        return f

    def _update_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        jobs = self.registry.get_all_jobs()
        n_today = sum(1 for j in jobs if j.get("status") == "dispatched"
                      and str(j.get("dispatched_at", "")).startswith(today))
        n_attn = sum(1 for j in jobs if j.get("status") in ("failed", "dispatch_failed", "interrupted", "error"))
        self.lbl_stat_today.setText(str(n_today))
        self.lbl_stat_attention.setText(str(n_attn))
        color = th.STATUS["error"][0] if n_attn else tok("text")
        self.lbl_stat_attention.setStyleSheet(f"color: {color};")
        self.lbl_stat_last.setText(self._last_scan)

    # =================================================================
    # 2. Istorija
    # =================================================================
    def _build_history_page(self) -> QWidget:
        page, lay = self._page()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Ieškoti pagal užsakymą, produktą ar BID")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setFixedWidth(320)
        self.txt_search.addAction(make_icon("search", tok("muted")), QLineEdit.LeadingPosition)
        self.txt_search.textChanged.connect(lambda _: self.populate_registry_table())
        lay.addLayout(hbox(label("Užsakymų istorija", "title"), None, self.txt_search,
                           button("Atnaujinti", icon="refresh", on_click=self.populate_registry_table),
                           button("Išvalyti istoriją", "danger", "trash", on_click=self.clear_registry)))

        body = QHBoxLayout()
        body.setSpacing(16)
        tcard = Card(margins=(8, 8, 8, 8), spacing=0)
        self.tbl_registry = _table(["Data", "Užsakymas", "Produktas", "Būsena"])
        hh = self.tbl_registry.horizontalHeader()
        for c, width in enumerate((130, 0, 200, 200)):
            if width:
                hh.setSectionResizeMode(c, QHeaderView.Interactive)
                self.tbl_registry.setColumnWidth(c, width)
            else:
                hh.setSectionResizeMode(c, QHeaderView.Stretch)
        self.tbl_registry.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_registry.setTextElideMode(Qt.ElideMiddle)
        self.tbl_registry.itemSelectionChanged.connect(self._show_job_details)
        tcard.body.addWidget(self.tbl_registry)
        self.lbl_history_empty = label("Apdoroti užsakymai atsiras čia.", "secondary")
        self.lbl_history_empty.setAlignment(Qt.AlignCenter)
        tcard.body.addWidget(self.lbl_history_empty)
        body.addWidget(tcard, 3)

        # Detalės
        self.detail_card = Card(margins=(20, 20, 20, 20), spacing=12)
        self.detail_card.setMinimumWidth(360)
        self.lbl_job_title = label("Pasirinkite užsakymą", "subtitle", wrap=True)
        self.badge_job = Badge("", "neutral")
        self.detail_card.body.addLayout(hbox(self.lbl_job_title, None, self.badge_job))
        self.job_meta = QGridLayout()
        self.job_meta.setHorizontalSpacing(16)
        self.job_meta.setVerticalSpacing(8)
        self.detail_card.body.addLayout(self.job_meta)
        self.lbl_job_message = label("", "secondary", wrap=True)
        self.detail_card.body.addWidget(self.lbl_job_message)
        self.detail_card.body.addStretch(1)
        self.detail_card.body.addWidget(divider())
        self.btn_job_open = button("Atidaryti plokščių aplanką", "primary", "folder", "large",
                                   self.open_selected_job_folder)
        self.detail_card.body.addWidget(self.btn_job_open)
        self.btn_job_retry = button("Pakartoti", icon="retry", on_click=self.retry_selected_job,
                                    tooltip="Užsakymas bus apdorotas ir įkeltas iš naujo kito skenavimo metu")
        self.btn_job_original = button("Originalas", icon="folder", on_click=self.open_selected_job_original)
        self.detail_card.body.addLayout(hbox(self.btn_job_retry, self.btn_job_original, spacing=8))
        self.btn_job_delete = button("Ištrinti įrašą", "danger", "trash", size="small",
                                     on_click=self.delete_selected_job)
        self.detail_card.body.addLayout(hbox(self.btn_job_delete, None))
        body.addWidget(self.detail_card, 2)
        lay.addLayout(body, 1)
        self.populate_registry_table()
        return page

    def populate_registry_table(self):
        if not hasattr(self, "tbl_registry"):
            return
        selected = self._selected_job_id()
        q = self.txt_search.text().strip().lower() if hasattr(self, "txt_search") else ""
        jobs = self.registry.get_all_jobs()
        if q:
            jobs = [j for j in jobs if q in " ".join(str(j.get(k, "")) for k in
                                                     ("job_id", "product_name", "bid", "pid")).lower()]
        self.tbl_registry.setRowCount(len(jobs))
        reselect = -1
        for row, j in enumerate(jobs):
            ts = str(j.get("updated_at", ""))[5:16]  # MM-DD HH:MM
            it_date = QTableWidgetItem(ts)
            it_date.setFont(th.tnum_font(it_date.font()))
            it_date.setForeground(QColor(tok("secondary")))
            self.tbl_registry.setItem(row, 0, it_date)
            it_id = QTableWidgetItem(str(j.get("job_id", "")))
            it_id.setData(Qt.UserRole, j.get("job_id", ""))
            self.tbl_registry.setItem(row, 1, it_id)
            self.tbl_registry.setItem(row, 2, QTableWidgetItem(str(j.get("product_name", ""))))
            text, kind = STATUS_VIEW.get(j.get("status", ""), (j.get("status", ""), "neutral"))
            it_st = QTableWidgetItem(f"●  {text}")
            it_st.setForeground(QColor(th.status_colors(kind, current_theme())[0]))
            if j.get("message"):
                it_st.setToolTip(j["message"])
            self.tbl_registry.setItem(row, 3, it_st)
            if j.get("job_id") == selected:
                reselect = row
        empty = not jobs
        self.tbl_registry.setVisible(not empty)
        self.lbl_history_empty.setVisible(empty)
        if empty and q:
            self.lbl_history_empty.setText("Pagal paiešką nieko nerasta.")
        elif empty:
            self.lbl_history_empty.setText("Apdoroti užsakymai atsiras čia.")
        if reselect >= 0:
            self.tbl_registry.selectRow(reselect)
        elif jobs:
            self.tbl_registry.selectRow(0)
        self._show_job_details()
        if hasattr(self, "lbl_stat_today"):
            self._update_stats()

    def _selected_job_id(self) -> Optional[str]:
        if not hasattr(self, "tbl_registry"):
            return None
        row = self.tbl_registry.currentRow()
        if row < 0 or not self.tbl_registry.selectionModel().hasSelection():
            return None
        it = self.tbl_registry.item(row, 1)
        return it.data(Qt.UserRole) if it is not None else None

    def _show_job_details(self):
        while self.job_meta.count():
            w = self.job_meta.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        for b in (self.btn_job_open, self.btn_job_retry, self.btn_job_original, self.btn_job_delete):
            b.setEnabled(job is not None)
        if not job:
            self.lbl_job_title.setText("Pasirinkite užsakymą")
            self.badge_job.hide()
            self.lbl_job_message.setText("")
            return
        self.lbl_job_title.setText(job_id)
        text, kind = STATUS_VIEW.get(job.get("status", ""), (job.get("status", ""), "neutral"))
        self.badge_job.set(text, kind)
        self.badge_job.show()
        rows = [
            ("Atnaujinta", job.get("updated_at", "")),
            ("Produktas", job.get("product_name", "")),
            ("BID", job.get("bid", "")),
            ("PID", job.get("pid", "")),
            ("Užsakymo data", job.get("order_date", "")),
            ("Įkeltos plokštės", " → ".join(job.get("dispatched_plates") or [])),
            ("Bandymai", str(job.get("attempts", "")) if job.get("attempts") else ""),
            ("Šaltinis", ("Brokų aplankas · " if job.get("source") == "brokas" else "") + job.get("filepath", "")),
        ]
        r = 0
        for k, v in rows:
            if not v:
                continue
            kl = label(k, "secondary")
            kl.setStyleSheet(f"color: {tok('muted')};")
            vl = label(str(v), "", wrap=True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.job_meta.addWidget(kl, r, 0, Qt.AlignTop)
            self.job_meta.addWidget(vl, r, 1)
            r += 1
        self.job_meta.setColumnStretch(1, 1)
        self.lbl_job_message.setText(job.get("message", ""))

    def open_selected_job_folder(self):
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        if not job:
            return
        target = job.get("local_plates_dir")
        if target and os.path.isdir(target):
            self._open_in_explorer(target)
        else:
            self.toasts.show("warning", "Plokščių aplankas nerastas", target or "Plokštės dar nesugeneruotos.")

    def open_selected_job_original(self):
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        if not job:
            return
        lp = job.get("local_pdf_path") or ""
        folder = os.path.dirname(lp) if lp else ""
        if folder and os.path.isdir(folder):
            self._open_in_explorer(folder)
        else:
            self.toasts.show("warning", "Originalas nerastas", lp or "Failas dar neatsisiųstas.")

    def retry_selected_job(self):
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        if not job:
            return
        text = "Užsakymas bus apdorotas ir įkeltas į HotFolderius kito skenavimo metu."
        if job.get("dispatched_plates"):
            text += (f" Į RasterLink jau įkelta: {', '.join(job['dispatched_plates'])} – "
                     f"šios plokštės bus įkeltos dar kartą.")
        if not ConfirmDialog.ask(self, "Pakartoti užsakymą?", text, "Pakartoti", danger=False):
            return
        if self.registry.reset_job(job_id):
            self.log(f"🔁 „{job_id}“ pažymėtas pakartojimui.")
            self.toasts.show("info", "Pažymėta pakartojimui", f"„{job_id}“ bus apdorotas kito skenavimo metu.")
        else:
            self.toasts.show("error", "Nepavyko pažymėti", self.registry.last_error, sticky=True)
        self.populate_registry_table()

    def delete_selected_job(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        if not ConfirmDialog.ask(self, "Ištrinti įrašą?",
                                 f"Įrašas „{job_id}“ bus pašalintas iš istorijos. Jei failas vis dar yra serveryje, "
                                 f"jis bus apdorotas iš naujo. Spaudos failai neliečiami.", "Ištrinti"):
            return
        self.registry.delete_job(job_id)
        self.log(f"Ištrintas įrašas „{job_id}“.")
        self.populate_registry_table()

    def clear_registry(self):
        if not ConfirmDialog.ask(self, "Išvalyti istoriją?",
                                 "Visi įrašai bus pašalinti, o serverio failai vėl bus laikomi naujais ir gali būti "
                                 "įkelti pakartotinai. Šio veiksmo atšaukti negalima.", "Išvalyti"):
            return
        self.registry.clear()
        self.populate_registry_table()
        self.log("Užsakymų istorija išvalyta.")

    # =================================================================
    # 3. Produktai
    # =================================================================
    def _build_products_page(self) -> QWidget:
        page, lay = self._page()
        self.btn_product_save = button("Išsaugoti", "primary", "check", on_click=self.save_current_product)
        lay.addLayout(hbox(label("Produktai", "title"), None, self.btn_product_save))

        body = QHBoxLayout()
        body.setSpacing(16)
        left = Card(margins=(16, 16, 16, 16), spacing=10)
        left.setFixedWidth(300)
        left.body.addWidget(section("Produktai"))
        self.txt_product_search = QLineEdit()
        self.txt_product_search.setPlaceholderText("Ieškoti produkto")
        self.txt_product_search.setClearButtonEnabled(True)
        self.txt_product_search.addAction(make_icon("search", tok("muted")), QLineEdit.LeadingPosition)
        self.txt_product_search.textChanged.connect(self._filter_products)
        left.body.addWidget(self.txt_product_search)
        self.list_products = QListWidget()
        self.list_products.setFocusPolicy(Qt.NoFocus)
        self.list_products.currentRowChanged.connect(self._on_product_selected)
        left.body.addWidget(self.list_products, 1)
        left.body.addLayout(hbox(button("Naujas", icon="plus", on_click=self.add_product), None,
                                 button("Ištrinti", "danger", "trash", on_click=self.delete_selected_product)))
        body.addWidget(left)

        right = Card(margins=(20, 20, 20, 16), spacing=16)
        self.lbl_product_title = label("", "subtitle")
        self.badge_product_state = Badge("", "neutral")
        self.badge_product_state.hide()
        right.body.addLayout(hbox(self.lbl_product_title, self.badge_product_state, None,
                                  button("Kopijuoti", icon="copy", size="small",
                                         on_click=self.duplicate_selected_product,
                                         tooltip="Sukurti naują produktą pagal šio nustatymus"),
                                  button("Atšaukti pakeitimus", "ghost", size="small",
                                         on_click=self._revert_product)))
        self.product_form = ProductForm()
        self.product_form.changed.connect(self._on_product_form_changed)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        holder.setObjectName("plain")
        holder.setStyleSheet("QWidget#plain { background: transparent; }")
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.addWidget(self.product_form)
        scroll.setWidget(holder)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        right.body.addWidget(scroll, 1)
        body.addWidget(right, 1)
        lay.addLayout(body, 1)

        self.populate_products_table()
        if self.config.get("products"):
            self.list_products.setCurrentRow(0)
        else:
            self.add_product()
        return page

    def populate_products_table(self):
        """Atnaujina produktų sąrašą (pavadinimas ir kėlimo seka)."""
        self.list_products.blockSignals(True)
        self.list_products.clear()
        for p in self.config.get("products", []):
            it = QListWidgetItem(f"{p.get('name', '')}\n{describe_plates(p)}")
            it.setSizeHint(QSize(0, 52))
            self.list_products.addItem(it)
        self.list_products.blockSignals(False)
        if 0 <= self._product_index < self.list_products.count():
            self.list_products.setCurrentRow(self._product_index)
        self._filter_products(self.txt_product_search.text())

    def _filter_products(self, text: str):
        q = (text or "").strip().lower()
        for i, p in enumerate(self.config.get("products", [])):
            hay = (p.get("name", "") + " " + " ".join(normalize_product(p)["keywords"])).lower()
            self.list_products.item(i).setHidden(bool(q) and q not in hay)

    def _confirm_discard_product(self) -> bool:
        if not self._product_dirty:
            return True
        if ConfirmDialog.ask(self, "Išmesti pakeitimus?",
                             "Produkto pakeitimai neišsaugoti. Jei tęsite, jie bus prarasti.", "Išmesti"):
            self._product_dirty = False
            return True
        return False

    def _load_product_form(self, index: int, template: Optional[dict] = None):
        products = self.config.get("products", [])
        self._product_index = index
        prod = products[index] if 0 <= index < len(products) else None
        self.product_form.load(prod, products,
                               _safe_float(self.config.get("inter_layer_delay_sec", 0.5), 0.5), template=template)
        self._product_dirty = template is not None
        self._update_product_header()

    def _update_product_header(self):
        if self._product_index < 0:
            self.lbl_product_title.setText(self.product_form.txt_name.text().strip() or "Naujas produktas")
        else:
            self.lbl_product_title.setText(self.config["products"][self._product_index].get("name", ""))
        if self._product_dirty:
            self.badge_product_state.set("Neišsaugota", "warning")
            self.badge_product_state.show()
        else:
            self.badge_product_state.hide()
        self.btn_product_save.setEnabled(self._product_dirty and self.product_form.is_valid())

    def _on_product_selected(self, row: int):
        if row == self._product_index:
            return
        if not self._confirm_discard_product():
            self.list_products.blockSignals(True)
            if self._product_index >= 0:
                self.list_products.setCurrentRow(self._product_index)
            else:
                self.list_products.clearSelection()
            self.list_products.blockSignals(False)
            return
        if row >= 0:
            self._load_product_form(row)

    def _on_product_form_changed(self):
        self._product_dirty = True
        self._update_product_header()

    def _revert_product(self):
        if self._product_index >= 0:
            self._load_product_form(self._product_index)
        elif self.config.get("products"):
            self._product_dirty = False
            self.list_products.setCurrentRow(0)
            self._load_product_form(0)

    def add_product(self, template: Optional[dict] = None):
        if hasattr(self, "product_form") and self.list_products.count() and not self._confirm_discard_product():
            return
        self.list_products.blockSignals(True)
        self.list_products.clearSelection()
        self.list_products.setCurrentRow(-1)
        self.list_products.blockSignals(False)
        self._load_product_form(-1, template=template)
        if template is None:
            self._product_dirty = False
            self._update_product_header()
        self.product_form.txt_name.setFocus()

    def duplicate_selected_product(self):
        if self._product_index < 0:
            return
        src = copy.deepcopy(self.config["products"][self._product_index])
        src.pop("id", None)
        src["name"] = f"{src.get('name', 'Produktas')} (kopija)"
        src["keywords"] = []
        self.add_product(template=src)

    def save_current_product(self) -> bool:
        form = self.product_form
        p = form.build_product()
        errors, warnings = form.validate(p)
        if errors:
            self.toasts.show("error", "Produktas neišsaugotas", " ".join(errors))
            return False
        if warnings and not ConfirmDialog.ask(self, "Išsaugoti produktą?", " ".join(warnings),
                                              "Išsaugoti", danger=False):
            return False
        products = self.config.setdefault("products", [])
        if self._product_index >= 0:
            products[self._product_index] = p
            msg = f"Produktas „{p['name']}“ atnaujintas"
        else:
            products.append(p)
            self._product_index = len(products) - 1
            msg = f"Produktas „{p['name']}“ sukurtas"
        self._product_dirty = False
        self._products_changed(f"{msg}: {describe_plates(p)}.")
        self._load_product_form(self._product_index)
        self.toasts.show("success", msg, describe_plates(p))
        return True

    def delete_selected_product(self):
        if self._product_index < 0:
            self._revert_product()
            return
        pname = self.config["products"][self._product_index].get("name", "Produktas")
        if not ConfirmDialog.ask(self, "Ištrinti produktą?",
                                 f"„{pname}“ bus pašalintas. Šio produkto failai serveryje nebebus apdorojami. "
                                 f"Spaudos failai ir istorija neliečiami.", "Ištrinti"):
            return
        self.config["products"].pop(self._product_index)
        self._product_dirty = False
        self._product_index = -1
        self._products_changed(f"Pašalintas produktas „{pname}“.")
        if self.config["products"]:
            self.list_products.setCurrentRow(0)
            self._load_product_form(0)
        else:
            self.add_product()

    def _products_changed(self, message: str):
        self.populate_products_table()
        self.save_config(quiet=True)
        self.log(message)

    # =================================================================
    # 4. Nustatymai
    # =================================================================
    def _build_settings_page(self) -> QWidget:
        page, lay = self._page()
        self.seg_theme = Segmented(["Šviesi", "Tamsi"], 1 if self.config.get("theme") == "dark" else 0)
        self.seg_theme.changed.connect(lambda i: self.set_theme("dark" if i == 1 else "light"))
        lay.addLayout(hbox(label("Nustatymai", "title"), None, self.seg_theme,
                           button("Išsaugoti", "primary", "check", on_click=self.save_settings)))
        self.seg_settings = Segmented(["Šaltinis ir talpykla", "Apdorojimas", "Atnaujinimai"])
        lay.addLayout(hbox(self.seg_settings, None))
        stack = QStackedWidget()
        self.seg_settings.changed.connect(stack.setCurrentIndex)
        lay.addWidget(stack, 1)

        # --- Šaltinis ir talpykla ---
        src_page = QWidget()
        sl = QVBoxLayout(src_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        c1 = Card()
        self.badge_src = Badge("Netikrinta", "neutral")
        c1.body.addLayout(hbox(label("Serverio aplankas", "subtitle"), None, self.badge_src))
        c1.body.addWidget(label("Tinklo aplankas, kuriame atsiranda nauji užsakymų PDF failai.", "secondary", True))
        self.txt_server_path = QLineEdit(self.config.get("server_inbox_folder", ""))
        self.txt_server_path.editingFinished.connect(self._check_paths_async)
        c1.body.addWidget(field("Aplanko kelias", self._path_row(self.txt_server_path, self.browse_server_path)))
        self.txt_fallback = QLineEdit(self.config.get("local_fallback_inbox", ""))
        c1.body.addWidget(field("Vietinis rezervas", self._path_row(self.txt_fallback, self.browse_fallback_path),
                                "Naudojamas, kai serveris nepasiekiamas. Gali būti tuščias."))
        sl.addWidget(c1)

        c_rej = Card()
        self.badge_rejects = Badge("Nenustatytas", "neutral")
        c_rej.body.addLayout(hbox(label("Brokų aplankas", "subtitle"), None, self.badge_rejects))
        c_rej.body.addWidget(label("Aplankas, kuriame atsiranda perspausdinami (brokuoti) užsakymai. Stebimi visi "
                                   "jo poaplankiai; taikomas tas pats datos filtras. Kiekvienas failas keliamas "
                                   "vieną kartą – jį pakeitus ar įdėjus iš naujo, bus atspausdintas vėl.",
                                   "secondary", True))
        self.txt_rejects = QLineEdit(self.config.get("rejects_folder", ""))
        self.txt_rejects.setPlaceholderText("pvz. \\\\192.168.1.143\\podbase-hotfolder\\BROKAI")
        self.txt_rejects.editingFinished.connect(self._check_paths_async)
        c_rej.body.addWidget(field("Aplanko kelias", self._path_row(self.txt_rejects, self.browse_rejects_path),
                                   "Palikite tuščią, jei brokų aplanko nenaudojate. RasterLink'e brokai matomi su "
                                   "priešdėliu BROKAS_."))
        sl.addWidget(c_rej)

        c2 = Card()
        self.badge_storage = Badge("Netikrinta", "neutral")
        c2.body.addLayout(hbox(label("Vietinė talpykla", "subtitle"), None, self.badge_storage))
        c2.body.addWidget(label("Čia saugomi atsisiųsti originalai ir sugeneruotos plokštės.", "secondary", True))
        default_loc = self.config.get("local_storage_folder") or get_safe_default_storage_dir()
        self.txt_local_storage = QLineEdit(default_loc)
        self.txt_local_storage.editingFinished.connect(self._check_paths_async)
        row = self._path_row(self.txt_local_storage, self.browse_local_storage_path)
        row.layout().addWidget(button("Atidaryti", icon="folder", on_click=self.open_local_storage_in_explorer))
        c2.body.addWidget(field("Aplanko kelias", row,
                                "Jei aplankas nepasiekiamas, automatiškai naudojamas %USERPROFILE%\\Podbase_PrintFlow_Storage."))
        sl.addWidget(c2)
        sl.addStretch(1)
        stack.addWidget(self._scroll(src_page))

        # --- Apdorojimas ---
        proc = QWidget()
        pl = QVBoxLayout(proc)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(16)
        c3 = Card()
        c3.body.addWidget(label("Apdorojimas", "subtitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        def spin(key, lo, hi, default, suffix, dbl=False):
            w = QDoubleSpinBox() if dbl else QSpinBox()
            w.setRange(lo, hi)
            w.setSuffix(suffix)
            if dbl:
                w.setSingleStep(0.1)
                w.setValue(_safe_float(self.config.get(key, default), default))
            else:
                w.setValue(_safe_int(self.config.get(key, default), default))
            return w

        self.spn_min_age = spin("min_file_age_sec", 0, 600, 5, " s")
        self.spn_attempts = spin("max_attempts", 1, 10, 3, "")
        self.spn_timeout = spin("server_timeout_sec", 2, 60, 8, " s")
        self.spn_default_delay = spin("inter_layer_delay_sec", 0, 10, 0.5, " s", dbl=True)
        grid.addWidget(field("Failo „nusistovėjimo“ laikas", self.spn_min_age,
                             "Ką tik įkeliami į serverį failai praleidžiami, kol nepasikeičia tiek laiko."), 0, 0)
        grid.addWidget(field("Bandymų skaičius klaidos atveju", self.spn_attempts,
                             "Po tiek nesėkmių užsakymas pažymimas „Nepavyko“ ir laukia operatoriaus."), 0, 1)
        grid.addWidget(field("Serverio atsako laukimas", self.spn_timeout,
                             "Po tiek laiko nepasiekiamas serveris laikomas atjungtu."), 1, 0)
        grid.addWidget(field("Numatytoji pauzė tarp plokščių", self.spn_default_delay,
                             "Naudojama naujiems produktams."), 1, 1)
        self.sw_wait_pickup = Switch("Laukti, kol RasterLink paims plokštę")
        self.sw_wait_pickup.setChecked(bool(self.config.get("wait_for_pickup", True)))
        grid.addWidget(field("Kėlimo seka", self.sw_wait_pickup,
                             "Kita plokštė (ir kitas užsakymas) keliama tik kai RasterLink paėmė ankstesnę – "
                             "failas dingo iš HotFolderio. Taip seka garantuota."), 3, 0)
        self.spn_pickup_timeout = spin("pickup_timeout_sec", 5, 600, 60, " s")
        grid.addWidget(field("Ilgiausias laukimas", self.spn_pickup_timeout,
                             "Jei RasterLink nepaima plokštės per šį laiką, likusios nekeliamos ir stebėjimas "
                             "sustabdomas."), 3, 1)
        dpi = label(f"{_safe_int(self.config.get('plate_dpi', 300), 300)} DPI", "strong")
        grid.addWidget(field("Plokščių raiška", dpi,
                             "Visos plokštės generuojamos vienoda raiška ir identiška geometrija (RasterLink 7)."), 2, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        c3.body.addLayout(grid)
        pl.addWidget(c3)
        pl.addStretch(1)
        stack.addWidget(self._scroll(proc))

        # --- Atnaujinimai ---
        upd = QWidget()
        ul = QVBoxLayout(upd)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(16)
        c4 = Card(margins=(20, 20, 20, 20), spacing=12)
        logo = QLabel()
        pm = QPixmap(th.resource_path("assets", "podbase_icon.png"))
        if not pm.isNull():
            logo.setPixmap(self._scaled_logo(pm, 44))
        info = QVBoxLayout()
        info.setSpacing(4)
        info.addWidget(label("Podbase PrintFlow Lite", "subtitle"))
        v = label(f"Įdiegta versija v{APP_VERSION}", "secondary")
        v.setFont(th.tnum_font(v.font()))
        info.addWidget(v)
        self.badge_update = Badge("Dar netikrinta", "neutral")
        c4.body.addLayout(hbox(logo, 12, info, None, self.badge_update, spacing=0))
        c4.body.addWidget(label(f"Nustatymai ir istorija: {os.path.dirname(self.config_path)}", "caption", True))
        self.btn_check_updates = button("Tikrinti atnaujinimus", "primary", "refresh",
                                        on_click=lambda: self.updater.check(manual=True))
        c4.body.addLayout(hbox(None, button("Atidaryti žurnalą", icon="log", on_click=self.open_log_file),
                               self.btn_check_updates))
        ul.addWidget(c4)

        c5 = Card()
        c5.body.addWidget(label("Automatiniai atnaujinimai", "subtitle"))
        c5.body.addWidget(label("Programa tikrina naujas versijas paleidus ir kas 30 min. Radus naują versiją, "
                                "parodomas pasiūlymas atnaujinti – nieko nediegiama be jūsų sutikimo.", "secondary", True))
        self.txt_github_repo = QLineEdit(self.config.get("github_repo") or updater.DEFAULT_GITHUB_REPO)
        self.txt_github_repo.setPlaceholderText(updater.DEFAULT_GITHUB_REPO)
        c5.body.addWidget(field("GitHub repozitorija", self.txt_github_repo,
                                "Išleidimai su žyme lite-vX.Y.Z ir failu PrintFlowLite_vX.Y.Z.zip."))
        self.sw_auto_update = Switch("Automatiškai tikrinti atnaujinimus")
        self.sw_auto_update.setChecked(bool(self.config.get("auto_check_updates", True)))
        self.sw_auto_update.toggled.connect(self._on_auto_update_toggled)
        c5.body.addWidget(self.sw_auto_update)
        ul.addWidget(c5)
        ul.addStretch(1)
        stack.addWidget(self._scroll(upd))
        return page

    @staticmethod
    def _scaled_logo(pm: QPixmap, size: int) -> QPixmap:
        dpr = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
        out = pm.scaled(int(size * dpr), int(size * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out.setDevicePixelRatio(dpr)
        return out

    def _on_auto_update_toggled(self, on: bool):
        self.config["auto_check_updates"] = bool(on)
        self.save_config(quiet=True)
        self.updater.apply_auto_setting()

    def _on_update_state(self, state: str, text: str):
        kind = {"checking": "neutral", "ok": "success", "update": "info", "error": "error"}.get(state, "neutral")
        if hasattr(self, "badge_update"):
            self.badge_update.set(text, kind)
            self.btn_check_updates.setEnabled(state != "checking")

    def prepare_for_update(self):
        """Prieš atnaujinimą: sustabdomas stebėjimas ir palaukiama, kol baigsis einamasis užsakymas."""
        self.auto_timer.stop()
        if self.worker and self.worker.isRunning():
            self.log("Laukiama, kol baigsis einamasis užsakymas…")
            self.worker.stop()
            if not self.worker.wait(60000):
                raise RuntimeError("Vyksta užsakymo apdorojimas – pabandykite atnaujinti vėliau")
        self.save_config(quiet=True)

    def _scroll(self, w: QWidget) -> QScrollArea:
        w.setObjectName("page")
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(w)
        return sa

    def _path_row(self, edit: QLineEdit, on_browse) -> QWidget:
        w = QWidget()
        w.setObjectName("plain")
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(8)
        l.addWidget(edit, 1)
        l.addWidget(button("Naršyti…", icon="folder", on_click=on_browse))
        return w

    def save_settings(self):
        self.config["server_inbox_folder"] = self.txt_server_path.text().strip()
        self.config["local_fallback_inbox"] = self.txt_fallback.text().strip()
        self.config["rejects_folder"] = self.txt_rejects.text().strip()
        self.config["local_storage_folder"] = self.txt_local_storage.text().strip()
        self.config["min_file_age_sec"] = self.spn_min_age.value()
        self.config["max_attempts"] = self.spn_attempts.value()
        self.config["server_timeout_sec"] = self.spn_timeout.value()
        self.config["wait_for_pickup"] = self.sw_wait_pickup.isChecked()
        self.config["pickup_timeout_sec"] = self.spn_pickup_timeout.value()
        self.config["inter_layer_delay_sec"] = round(self.spn_default_delay.value(), 2)
        self.config["github_repo"] = self.txt_github_repo.text().strip() or updater.DEFAULT_GITHUB_REPO
        if self.save_config():
            self.toasts.show("success", "Nustatymai išsaugoti")
        self._check_paths_async()

    def _check_paths_async(self):
        """Kelių pasiekiamumo patikra fone (tinklo kelias gali „kabėti“)."""
        if not hasattr(self, "badge_src"):
            return
        srv = self.txt_server_path.text().strip()
        loc = self.txt_local_storage.text().strip()
        rej = self.txt_rejects.text().strip()
        self.badge_src.set("Tikrinama…", "neutral")
        if rej:
            self.badge_rejects.set("Tikrinama…", "neutral")
        timeout = _safe_float(self.config.get("server_timeout_sec", 8), 8)

        def work():
            ok_srv = path_exists_with_timeout(srv, timeout) if srv else False
            ok_loc = is_dir_writable(loc) if loc else False
            ok_rej = path_exists_with_timeout(rej, timeout) if rej else False
            return ok_srv, ok_loc, ok_rej

        checker = _PathCheck(work, self)
        checker.done.connect(lambda r, s=srv, l=loc, j=rej: self._apply_path_check(s, l, *r, rej=j))
        self._path_checkers.append(checker)
        checker.finished.connect(lambda c=checker: self._path_checkers.remove(c) if c in self._path_checkers else None)
        checker.start()

    def _apply_path_check(self, srv, loc, ok_srv, ok_loc, ok_rej=False, rej=""):
        if not rej:
            self.badge_rejects.set("Nenustatytas", "neutral")
        elif ok_rej:
            self.badge_rejects.set("Pasiekiamas", "success")
        else:
            self.badge_rejects.set("Nerastas arba nepasiekiamas", "error")
        if not srv:
            self.badge_src.set("Nenustatytas", "neutral")
        elif ok_srv:
            self.badge_src.set("Pasiekiamas", "success")
        else:
            self.badge_src.set("Nerastas arba nepasiekiamas", "error")
        if not loc:
            self.badge_storage.set("Nenustatyta", "neutral")
        elif ok_loc:
            self.badge_storage.set("Pasiekiama", "success")
        else:
            self.badge_storage.set("Neįrašoma – bus naudojamas %USERPROFILE%", "warning")

    # =================================================================
    # Tema
    # =================================================================
    def set_theme(self, theme: str):
        self.config["theme"] = theme
        apply_theme(QApplication.instance(), theme)
        self._refresh_theme_button()
        if hasattr(self, "seg_theme"):
            self.seg_theme.set_index(1 if theme == "dark" else 0)
        self.save_config(quiet=True)
        self.populate_registry_table()
        self._update_stats()

    def toggle_theme(self):
        self.set_theme("light" if current_theme() == "dark" else "dark")

    def _refresh_theme_button(self):
        set_icon(self.btn_theme, "sun" if current_theme() == "dark" else "moon")

    # =================================================================
    # Skenavimas ir stebėjimas
    # =================================================================
    def _scan_running(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def toggle_monitoring(self):
        # Mygtukas stabdo ir stebėjimą, ir vykstantį (taip pat rankinį) skenavimą
        if self.auto_timer.isActive() or self._scan_running():
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        interval = _safe_int(self.config.get("scan_interval_sec", 10), 10)
        self.auto_timer.start(interval * 1000)
        self.badge_monitor.set("Stebėjimas aktyvus", "success")
        self.btn_toggle_monitor.setText("Sustabdyti stebėjimą")
        set_icon(self.btn_toggle_monitor, "pause", "on_primary")
        self.lbl_monitor_hint.setText(f"Serveris tikrinamas kas {interval} s. Nauji failai apdorojami automatiškai.")
        self.log(f"▶️ Stebėjimas paleistas (kas {interval} s).")
        self.start_scan()

    def stop_monitoring(self):
        """Sustabdo laikmatį IR vykstantį skenavimą (saugiu tašku – niekada įkėlimo viduryje)."""
        self.auto_timer.stop()
        if self._scan_running():
            self.worker.stop()
            self._stopping = True
            self.badge_monitor.set("Stabdoma…", "warning")
            self.btn_toggle_monitor.setEnabled(False)
            self.btn_toggle_monitor.setText("Stabdoma…")
            self.lbl_monitor_hint.setText("Baigiamas einamasis žingsnis. Kiti failai nebus apdorojami.")
            self.log("⏹️ Stabdoma – baigiamas einamasis žingsnis, kiti failai nebus apdorojami.")
            return
        self._set_stopped_state()
        self.log("Stebėjimas sustabdytas.")

    _stopping = False

    def _set_stopped_state(self):
        self._stopping = False
        self.badge_monitor.set("Stebėjimas sustabdytas", "neutral")
        self.btn_toggle_monitor.setEnabled(True)
        self.btn_toggle_monitor.setText("Pradėti stebėjimą")
        set_icon(self.btn_toggle_monitor, "play", "on_primary")
        self.lbl_monitor_hint.setText("Stebėjimas išjungtas. Failai iš serverio neimami, kol jo nepaleisite.")

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return  # Jau vyksta skenavimas

        # Nustatymų laukų reikšmės taikomos iškart (išsaugoma mygtuku „Išsaugoti“)
        self.config["server_inbox_folder"] = self.txt_server_path.text().strip()
        self.config["local_storage_folder"] = self.txt_local_storage.text().strip()
        self.config["local_fallback_inbox"] = self.txt_fallback.text().strip()
        self.config["rejects_folder"] = self.txt_rejects.text().strip()
        self.config["custom_start_date"] = self.txt_target_date.text().strip()

        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = WorkerScanProcess(self.config, self.registry, self.router)
        self.worker.log_signal.connect(self.log)
        self.worker.job_processed.connect(self.on_job_processed)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.source_state.connect(self.on_source_state)
        self.worker.halted.connect(self.on_worker_halted)
        self.btn_scan_now.setEnabled(False)
        self.btn_scan_now.setText("Skenuojama…")
        if not self.auto_timer.isActive():
            # Rankinis skenavimas – pagrindinis mygtukas leidžia jį sustabdyti
            self.badge_monitor.set("Skenuojama", "info")
            self.btn_toggle_monitor.setText("Sustabdyti skenavimą")
            set_icon(self.btn_toggle_monitor, "pause", "on_primary")
        self.worker.start()

    def on_source_state(self, kind: str, text: str):
        self.badge_server.set(text, kind)
        if kind == "error" and self._last_source_kind != "error":
            self.toasts.show("error", text, self.config.get("server_inbox_folder", ""))
        self._last_source_kind = kind

    _last_source_kind = ""

    def on_worker_halted(self, reason: str):
        """RasterLink nepaima plokščių – stabdomas stebėjimas, kad nesusikauptų plokštės."""
        self.toasts.show("error", "Kėlimas sustabdytas", f"{reason} Patikrinkite RasterLink 7 ir vėl paleiskite "
                         f"stebėjimą. Užsakymą galite pakartoti skiltyje Istorija.", sticky=True)
        if self.auto_timer.isActive() or self._scan_running():
            self.stop_monitoring()

    def on_job_processed(self, jname: str, data: dict):
        status = data.get("status")
        if status == "dispatched":
            self.toasts.show("success", f"Įkelta: {jname}", " → ".join(data.get("dispatched_plates") or []))
        elif status == "dispatch_failed":
            self.toasts.show("error", f"Ne visos plokštės įkeltos: {jname}", data.get("message", ""), sticky=True)
        elif status == "failed":
            self.toasts.show("error", f"Nepavyko: {jname}", data.get("message", ""), sticky=True)
        self.populate_registry_table()

    def on_scan_finished(self, total_found: int, new_processed: int):
        self.btn_scan_now.setEnabled(True)
        self.btn_scan_now.setText("Skenuoti dabar")
        if self._stopping:
            self._set_stopped_state()
            self.log("Stebėjimas sustabdytas.")
        elif not self.auto_timer.isActive():
            self._set_stopped_state()
        self._last_scan = datetime.now().strftime("%H:%M:%S")
        if self.registry.last_error:
            self.log(f"❌ {self.registry.last_error}")
            self.toasts.show("error", "Nepavyko įrašyti istorijos", self.registry.last_error, sticky=True)
        if new_processed > 0:
            self.log(f"🏁 Skenavimas baigtas: rasta {total_found}, apdorota naujų {new_processed}.")
        self.populate_registry_table()
        self._update_stats()

    def on_date_mode_changed(self, idx: int):
        self.config["filter_date_mode"] = ["today_only", "today_and_newer", "all"][idx]
        self._sync_date_field()
        self.save_config(quiet=True)

    def _on_target_date_edited(self):
        val = self.txt_target_date.text().strip()
        if val and not is_valid_date(val):
            self.txt_target_date.setProperty("invalid", True)
            self.toasts.show("warning", "Neteisinga data", "Formatas YYYY-MM-DD, pvz. 2026-10-09.")
        else:
            self.txt_target_date.setProperty("invalid", False)
            self.config["custom_start_date"] = val
            self.save_config(quiet=True)
        self.txt_target_date.style().unpolish(self.txt_target_date)
        self.txt_target_date.style().polish(self.txt_target_date)

    def _sync_date_field(self):
        """„Šiandien“ režime visada naudojama einamoji data – laukas paslėptas."""
        mode = self.config.get("filter_date_mode", "today_only")
        if mode == "today_only":
            self.txt_target_date.setText(datetime.now().strftime("%Y-%m-%d"))
        self.txt_target_date.setVisible(mode == "today_and_newer")

    def on_interval_changed(self, val: int):
        self.config["scan_interval_sec"] = val
        if self.auto_timer.isActive():
            self.auto_timer.setInterval(val * 1000)
        self.save_config(quiet=True)

    # =================================================================
    # Aplankai
    # =================================================================
    def _browse_into(self, edit: QLineEdit, title: str):
        folder = QFileDialog.getExistingDirectory(self, title, edit.text().strip())
        if folder:
            edit.setText(os.path.normpath(folder))
            self._check_paths_async()

    def browse_server_path(self):
        self._browse_into(self.txt_server_path, "Serverio aplankas")

    def browse_rejects_path(self):
        self._browse_into(self.txt_rejects, "Brokų aplankas")

    def browse_fallback_path(self):
        self._browse_into(self.txt_fallback, "Vietinis rezervas")

    def browse_local_storage_path(self):
        self._browse_into(self.txt_local_storage, "Vietinė talpykla")

    def open_local_storage_in_explorer(self):
        folder = self.txt_local_storage.text().strip()
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            self.toasts.show("error", "Nepavyko sukurti aplanko", str(e))
            return
        self._open_in_explorer(folder)

    def open_log_file(self):
        path = os.path.join(os.path.dirname(self.config_path), "printflow_lite.log")
        if os.path.exists(path):
            self._open_in_explorer(path)
        else:
            self.toasts.show("info", "Žurnalo failas dar nesukurtas", path)

    def _open_in_explorer(self, path: str):
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self.toasts.show("error", "Nepavyko atidaryti", str(e))

    # =================================================================
    # Žurnalas
    # =================================================================
    def log(self, text: str):
        level, clean = classify_log(text)
        if not clean:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        if hasattr(self, "txt_log"):
            color = th.status_colors(level, current_theme())[0] if level != "neutral" else tok("strong")
            self.txt_log.append(
                f'<span style="color:{tok("muted")}">{ts}</span>&nbsp;&nbsp;'
                f'<span style="color:{color}">●</span>&nbsp;&nbsp;'
                f'<span style="color:{tok("text")}">{html.escape(clean)}</span>'
            )
            sb = self.txt_log.verticalScrollBar()
            sb.setValue(sb.maximum())
        # Dubliuojame į failą (printflow_lite.log) – pėdsakas lieka ir po programos uždarymo
        logging.getLogger("printflow").info(clean)

    def closeEvent(self, event):
        if self.pages.currentIndex() == 2 and not self._confirm_discard_product():
            event.ignore()
            return
        self.auto_timer.stop()
        if self.worker and self.worker.isRunning():
            self.log("Uždaroma – laukiama, kol baigsis einamasis žingsnis…")
            self.worker.stop()
            if not self.worker.wait(15000):
                # Gija užstrigo tinklo I/O (SMB). Visi įrašymai atominiai (.part/.tmp ➔ replace),
                # todėl priverstinis sustabdymas nepalieka sugadintų failų.
                logging.getLogger("printflow").warning("Worker neatsako – priverstinai stabdoma")
                self.worker.terminate()
                self.worker.wait(2000)
        for c in list(self._path_checkers):
            c.wait(int(_safe_float(self.config.get("server_timeout_sec", 8), 8) * 1000) + 1000)
        event.accept()


class _PathCheck(QThread):
    done = Signal(tuple)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(tuple(self.fn()))
        except Exception:
            self.done.emit((False, False, False))
