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
import time
import re
import copy
import shutil
import logging
import traceback
from datetime import datetime
from typing import Optional, Tuple
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QTabWidget, QFileDialog, QMessageBox, QFrame,
    QGroupBox, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QColor, QFont, QIcon, QDesktopServices

from core.prepress_lite import export_production_plates
from core.scanner_lite import scan_server_directory, path_exists_with_timeout, is_valid_date
from core.router_lite import HotFolderRouterLite
from core.registry_lite import JobRegistryLite


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


VALID_LAYERS = {"cmyk": "CMYK", "white": "White", "primer": "Primer"}

STATUS_LABELS = {
    "dispatched": ("🟢 Įkelta", "#34d399"),
    "processing": ("⏳ Ruošiama", "#fbbf24"),
    "error": ("⚠️ Klaida (bus kartojama)", "#fb923c"),
    "failed": ("❌ Nepavyko", "#f87171"),
    "dispatch_failed": ("⛔ Įkelta dalinai", "#f87171"),
    "interrupted": ("⛔ Nutraukta", "#f87171"),
    "retry": ("🔁 Laukia pakartojimo", "#60a5fa"),
}


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
  "auto_scan": False,
  "scan_interval_sec": 10,
  "inter_layer_delay_sec": 0.5,
  "filter_date_mode": "today_only",
  "custom_start_date": "",
  "min_file_age_sec": 5,
  "max_attempts": 3,
  "plate_dpi": 300,
  "server_timeout_sec": 8,
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
            return server_dir

        reason = "neatsako (tinklo timeout)" if reachable is None else "nepasiekiamas"
        fallback = (self.config.get("local_fallback_inbox") or "").strip()
        if fallback and path_exists_with_timeout(fallback, timeout):
            self._log(f"⚠️ Serveris {reason}: {server_dir}. Naudojamas vietinis rezervas: {fallback}")
            return fallback
        self._log(f"⚠️ Serverio aplankas {reason}: {server_dir or '(nenurodytas)'}")
        return ""

    def _run_scan(self) -> Tuple[int, int]:
        server_dir = self._resolve_source_dir()
        if not server_dir:
            return 0, 0

        products = self.config.get("products", [])
        filter_mode = self.config.get("filter_date_mode", "today_only")
        target_date, date_warn = resolve_target_date(filter_mode, self.config.get("custom_start_date", ""))
        if date_warn:
            self._log(f"⚠️ {date_warn}")

        local_storage_base, storage_warn = resolve_storage_dir(self.config.get("local_storage_folder", ""))
        if storage_warn:
            self._log(f"⚠️ {storage_warn}")

        max_attempts = int(self.config.get("max_attempts", 3) or 3)
        dpi = int(self.config.get("plate_dpi", 300) or 300)

        self._log(f"🔍 Skenuojamas serveris: {server_dir}")
        self._log(f"   📅 Filtro data: {target_date} ({filter_mode}) | 📁 Vietinė talpykla: {local_storage_base}")

        errors, unstable = [], []
        found_jobs = scan_server_directory(
            root_dir=server_dir,
            products=products,
            filter_mode=filter_mode,
            target_date=target_date,
            min_file_age_sec=float(self.config.get("min_file_age_sec", 5) or 0),
            errors=errors,
            skipped_unstable=unstable,
            should_continue=lambda: self._is_running,
        )
        for e in errors[:5]:
            self._log(f"⚠️ {e}")
        if len(errors) > 5:
            self._log(f"⚠️ ... ir dar {len(errors) - 5} skenavimo klaidų")
        if unstable:
            self._log(f"⏳ {len(unstable)} failas(-ai) dar įkeliami į serverį – bus paimti kitame cikle")

        new_count = 0
        for item in found_jobs:
            if not self._is_running:
                self._log("⏹️ Skenavimas nutrauktas.")
                break
            if self.registry.is_file_processed(item["filepath"]):
                continue
            new_count += 1
            try:
                self._process_job(item, target_date, local_storage_base, max_attempts, dpi)
            except Exception as e:
                jname = item.get("job_name", "?")
                self._log(f"❌ Netikėta klaida apdorojant '{jname}': {e}")
                logging.getLogger("printflow").error("Job exception:\n%s", traceback.format_exc())
                self.registry.record_failure(jname, {"filepath": item.get("filepath", "")}, str(e), max_attempts)
                self._emit_job(jname)
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
        jname = item["job_name"]
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
        }

        self._log(f"\n📦 RASTAS NAUJAS UŽSAKYMAS: '{jname}' [{prod_name}] (BID: {item.get('bid') or '-'})")

        # -------------------------------------------------------------
        # ŽINGSNIS 1: ATSISIUNTIMAS IR KAUPIMAS VIETINIAME KOMPIUTERYJE (.part ➔ .pdf)
        # -------------------------------------------------------------
        local_orders_dir = os.path.join(local_storage_base, "originalus_uzsakymai", order_date, prod_id)
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
                job_name=jname,
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
            # Plokštės paruoštos, bet nekeliame – kitame paleidime bus pakartota nuo pradžių
            self.registry.register_or_update(jname, {"status": "retry", "message": "Nutraukta prieš kėlimą"})
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
            job_name=jname,
            plate_files=plates,
            product_config=prod,
            dispatch_order=dispatch_order,
            inter_layer_delay_sec=delay,
            log_cb=self._log
        )
        sent = [d["layer"] for d in dispatched]

        # -------------------------------------------------------------
        # ŽINGSNIS 4: REGISTRACIJA IR ATMINTIS
        # -------------------------------------------------------------
        common = {
            "dispatched_plates": sent,
            "local_plates_dir": local_plates_dir,
            "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if set(sent) == set(expected):
            common.update({"status": "dispatched", "message": ""})
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
                           "message": f"Įkelta tik {sent}, trūksta {missing}"})
            self.registry.register_or_update(jname, common)
            self._log(f"⛔ '{jname}': įkelta tik {sent}, NEĮKELTA {missing}. "
                      f"Reikia operatoriaus sprendimo (RasterLink'e jau yra dalis sluoksnių).")
            self._emit_job(jname)


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
                f"ℹ️ Programos aplankas neįrašomas (be Administratoriaus teisių) – nustatymai ir atmintis: "
                f"{os.path.dirname(writable_path)}"
            )
        self.config_path = writable_path
        self.config = self.load_config()

        registry_path = os.path.join(os.path.dirname(self.config_path), "jobs_registry.json")
        self.registry = JobRegistryLite(registry_path)
        for w in self.registry.load_warnings:
            self._startup_messages.append(f"⚠️ {w}")
        interrupted = self.registry.mark_interrupted()
        if interrupted:
            self._startup_messages.append(
                f"⚠️ {len(interrupted)} užsakymas(-ai) buvo nutraukti ankstesnio paleidimo metu "
                f"(būsena 'Nutraukta'). Patikrinkite RasterLink ir, jei reikia, spauskite '🔁 Pakartoti pažymėtą': "
                + ", ".join(interrupted[:10])
            )
        self.router = HotFolderRouterLite(
            default_delay_sec=self.config.get("inter_layer_delay_sec", 0.5)
        )

        self.worker: Optional[WorkerScanProcess] = None
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.start_scan)

        self.init_ui()
        for m in self._startup_messages:
            self.log(m)

        # Pagal pageidavimą: starto metu stebėjimas IŠJUNGTAS (auto_scan: False).
        # Jei kada nors būtų True, paleidžiame saugiai po lango atidarymo:
        if self.config.get("auto_scan", False):
            QTimer.singleShot(1000, self.start_monitoring)

    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if isinstance(cfg, dict) and cfg.get("products"):
                    # Trūkstami nauji raktai papildomi numatytosiomis reikšmėmis
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
        # Fallback į numatytąją konfigūraciją su visais 5 produktais
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

    def save_config(self):
        err = self._write_config_file(self.config)
        if err is None:
            self.log("💾 Nustatymai sėkmingai išsaugoti į config.json.")
        else:
            self.log(f"❌ Nepavyko išsaugoti nustatymų: {err}")

    def init_ui(self):
        self.setWindowTitle("Podbase Mimaki PrintFlow Lite v1.0")
        self.resize(1180, 840)
        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            QWidget { color: #f8fafc; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QGroupBox { border: 1px solid #334155; border-radius: 8px; margin-top: 10px; font-weight: bold; color: #38bdf8; padding: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #1e293b; border: 1px solid #475569; border-radius: 5px;
                padding: 6px; color: #ffffff;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #f97316; }
            QPushButton {
                background-color: #1e293b; border: 1px solid #475569; border-radius: 6px;
                padding: 7px 14px; font-weight: bold; color: #f8fafc;
            }
            QPushButton:hover { background-color: #334155; border-color: #94a3b8; }
            QPushButton#btnPrimary { background-color: #ea580c; border: 1px solid #f97316; }
            QPushButton#btnPrimary:hover { background-color: #c2410c; }
            QPushButton#btnSuccess { background-color: #059669; border: 1px solid #10b981; }
            QPushButton#btnSuccess:hover { background-color: #047857; }
            QPushButton#btnDanger { background-color: #7f1d1d; border: 1px solid #dc2626; color: #fca5a5; }
            QPushButton#btnDanger:hover { background-color: #991b1b; }
            QTableWidget {
                background-color: #1e293b; border: 1px solid #334155; border-radius: 6px;
                gridline-color: #334155; color: #f8fafc;
            }
            QHeaderView::section {
                background-color: #0f172a; color: #94a3b8; font-weight: bold; padding: 6px; border: none;
            }
            QTabWidget::pane { border: 1px solid #334155; border-radius: 8px; background: #0f172a; }
            QTabBar::tab {
                background: #1e293b; color: #94a3b8; padding: 9px 18px; font-weight: bold;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px;
            }
            QTabBar::tab:selected { background: #334155; color: #f97316; border-bottom: 2px solid #f97316; }
            QTextEdit {
                background-color: #090d16; border: 1px solid #1e293b; border-radius: 6px;
                color: #a7f3d0; font-family: 'Consolas', monospace; font-size: 12px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # 1. VIRŠUTINĖ JUOSTA (Header & Status)
        # -------------------------------------------------------------
        header = QHBoxLayout()

        title_box = QVBoxLayout()
        lbl_title = QLabel("PODBASE MIMAKI PRINTFLOW LITE")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 900; color: #f97316; letter-spacing: 1px;")
        lbl_sub = QLabel("Automatinis serverio stebėjimas, vietinis failų kaupimas ir kėlimas į Hot Folderius")
        lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box)

        header.addStretch()

        # Būsena: pagal nutylėjimą sustabdyta (laukiama operatoriaus)
        self.lbl_monitor_status = QLabel("⏸️ STEBĖJIMAS SUSTABDYTAS (Laukiama)")
        self.lbl_monitor_status.setStyleSheet("""
            background-color: #334155; color: #fbbf24; font-weight: bold;
            padding: 6px 14px; border-radius: 20px; border: 1px solid #475569;
        """)
        header.addWidget(self.lbl_monitor_status)

        self.btn_toggle_monitor = QPushButton("▶️ Pradėti stebėjimą")
        self.btn_toggle_monitor.setObjectName("btnSuccess")
        self.btn_toggle_monitor.clicked.connect(self.toggle_monitoring)
        header.addWidget(self.btn_toggle_monitor)

        self.btn_scan_now = QPushButton("🔄 Skenuoti dabar")
        self.btn_scan_now.setObjectName("btnPrimary")
        self.btn_scan_now.clicked.connect(self.start_scan)
        header.addWidget(self.btn_scan_now)

        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # 2. SERVERIO, TALPYKLOS IR DATŲ JUOSTA
        # -------------------------------------------------------------
        grp_srv = QGroupBox("Tinklo Serveris, Vietinė Talpykla ir Datų Filtravimas")
        lay_srv = QVBoxLayout(grp_srv)
        lay_srv.setSpacing(8)

        # Eilutė 1: Serveris
        row1 = QHBoxLayout()
        lbl_srv = QLabel("Tinklo serveris (šaltinis):")
        lbl_srv.setMinimumWidth(180)
        row1.addWidget(lbl_srv)
        self.txt_server_path = QLineEdit(self.config.get("server_inbox_folder", ""))
        row1.addWidget(self.txt_server_path, 1)
        btn_browse_srv = QPushButton("📂...")
        btn_browse_srv.clicked.connect(self.browse_server_path)
        row1.addWidget(btn_browse_srv)
        lay_srv.addLayout(row1)

        # Eilutė 2: Vietinė talpykla
        row2 = QHBoxLayout()
        lbl_loc = QLabel("Vietinė talpykla (kompiuteryje):")
        lbl_loc.setMinimumWidth(180)
        row2.addWidget(lbl_loc)
        default_loc = self.config.get("local_storage_folder") or get_safe_default_storage_dir()
        self.txt_local_storage = QLineEdit(default_loc)
        row2.addWidget(self.txt_local_storage, 1)
        btn_browse_loc = QPushButton("📂...")
        btn_browse_loc.clicked.connect(self.browse_local_storage_path)
        row2.addWidget(btn_browse_loc)
        btn_open_loc = QPushButton("📁 Atverti talpyklą")
        btn_open_loc.clicked.connect(self.open_local_storage_in_explorer)
        row2.addWidget(btn_open_loc)
        lay_srv.addLayout(row2)

        # Eilutė 3: Datos ir intervalas
        row3 = QHBoxLayout()
        lbl_dt = QLabel("Datos filtras:")
        lbl_dt.setMinimumWidth(180)
        row3.addWidget(lbl_dt)

        self.cmb_date_mode = QComboBox()
        self.cmb_date_mode.addItems(["Šiandienos data", "Šiandien ir naujesnės", "Visos datos"])
        mode_val = self.config.get("filter_date_mode", "today_only")
        if mode_val == "today_only":
            self.cmb_date_mode.setCurrentIndex(0)
        elif mode_val == "today_and_newer":
            self.cmb_date_mode.setCurrentIndex(1)
        else:
            self.cmb_date_mode.setCurrentIndex(2)
        self.cmb_date_mode.currentIndexChanged.connect(self.on_date_mode_changed)
        row3.addWidget(self.cmb_date_mode)

        self.txt_target_date = QLineEdit(self.config.get("custom_start_date") or datetime.now().strftime("%Y-%m-%d"))
        self.txt_target_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_target_date.setMaximumWidth(120)
        self.txt_target_date.setToolTip("Pradžios data režimams 'Šiandien ir naujesnės' / 'Visos datos'.\n"
                                         "Režime 'Šiandienos data' visada naudojama einamoji data.")
        row3.addWidget(self.txt_target_date)
        self._sync_date_field()

        row3.addSpacing(16)
        row3.addWidget(QLabel("Tikrinimo intervalas (s):"))
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(3, 300)
        self.spn_interval.setValue(self.config.get("scan_interval_sec", 10))
        self.spn_interval.valueChanged.connect(self.on_interval_changed)
        row3.addWidget(self.spn_interval)
        row3.addStretch()

        lay_srv.addLayout(row3)
        main_layout.addWidget(grp_srv)

        # -------------------------------------------------------------
        # 3. TABAI (Produktai, Atmintis)
        # -------------------------------------------------------------
        self.tabs = QTabWidget()

        # TAB 1: Produktai
        tab_products = QWidget()
        lay_prod = QVBoxLayout(tab_products)

        prod_top = QHBoxLayout()
        prod_top.addWidget(QLabel("Konfigūruokite produktus, thinning/thickening (px), eiliškumą ir hotfolderius:"))
        prod_top.addStretch()

        btn_add_prod = QPushButton("➕ Pridėti produktą")
        btn_add_prod.clicked.connect(self.add_product_row)
        prod_top.addWidget(btn_add_prod)

        btn_del_prod = QPushButton("🗑️ Pašalinti pasirinktą")
        btn_del_prod.setObjectName("btnDanger")
        btn_del_prod.clicked.connect(self.delete_selected_product)
        prod_top.addWidget(btn_del_prod)

        btn_save_prod = QPushButton("💾 Išsaugoti pakeitimus")
        btn_save_prod.setObjectName("btnSuccess")
        btn_save_prod.clicked.connect(self.save_products_from_table)
        prod_top.addWidget(btn_save_prod)

        lay_prod.addLayout(prod_top)

        self.tbl_products = QTableWidget()
        self.tbl_products.setColumnCount(10)
        self.tbl_products.setHorizontalHeaderLabels([
            "Produktas", "Raktažodžiai", "Sluoksniai",
            "White Choke (px)", "Primer Choke (px)", "Kėlimo Seka",
            "Pauzė (s)", "Hotfolder CMYK", "Hotfolder White", "Hotfolder Primer"
        ])
        self.tbl_products.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tbl_products.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.tbl_products.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.tbl_products.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.tbl_products.horizontalHeader().setSectionResizeMode(9, QHeaderView.Stretch)
        lay_prod.addWidget(self.tbl_products)

        self.populate_products_table()
        self.tabs.addTab(tab_products, "📦 Produktai ir Sluoksnių Nustatymai")

        # TAB 2: Užsakymų Atmintis (Registry)
        tab_registry = QWidget()
        lay_reg = QVBoxLayout(tab_registry)

        reg_top = QHBoxLayout()
        reg_top.addWidget(QLabel("Atmintyje esantys užsakymai (išsaugoma, kad nebūtų keliami pakartotinai):"))
        reg_top.addStretch()

        btn_open_job = QPushButton("📁 Atverti pažymėto aplanką")
        btn_open_job.clicked.connect(self.open_selected_job_folder)
        reg_top.addWidget(btn_open_job)

        btn_retry_job = QPushButton("🔁 Pakartoti pažymėtą")
        btn_retry_job.setToolTip("Leidžia pažymėtą užsakymą apdoroti ir įkelti iš naujo kitame skenavime")
        btn_retry_job.clicked.connect(self.retry_selected_job)
        reg_top.addWidget(btn_retry_job)

        btn_clear_reg = QPushButton("🗑️ Išvalyti atmintį")
        btn_clear_reg.setObjectName("btnDanger")
        btn_clear_reg.clicked.connect(self.clear_registry)
        reg_top.addWidget(btn_clear_reg)
        lay_reg.addLayout(reg_top)

        self.tbl_registry = QTableWidget()
        self.tbl_registry.setColumnCount(8)
        self.tbl_registry.setHorizontalHeaderLabels([
            "Užsakymas", "Produktas", "BID", "PID", "Plokštės", "Būsena", "Vietinis Kelias", "Data / Laikas"
        ])
        self.tbl_registry.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        lay_reg.addWidget(self.tbl_registry)

        self.populate_registry_table()
        self.tabs.addTab(tab_registry, "📋 Užsakymų Atmintis (Registry)")

        main_layout.addWidget(self.tabs, 3)

        # -------------------------------------------------------------
        # 4. GYVAS ŽURNALAS (Console Log)
        # -------------------------------------------------------------
        grp_log = QGroupBox("Gyvas Veiklos Žurnalas")
        lay_log = QVBoxLayout(grp_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.document().setMaximumBlockCount(5000)  # 24/7 darbas – atmintis neauga be galo
        lay_log.addWidget(self.txt_log)
        main_layout.addWidget(grp_log, 2)

        self.log("🚀 PrintFlow Lite sėkmingai paleista.")
        self.log(f"📂 Serverio šaknis: {self.config.get('server_inbox_folder')}")
        self.log(f"📁 Vietinė talpykla: {self.config.get('local_storage_folder')}")
        self.log(f"📦 Konfigūruota produktų: {len(self.config.get('products', []))}")
        self.log("⏸️ Automatinis stebėjimas sustabdytas. Spauskite '▶️ Pradėti stebėjimą' arba '🔄 Skenuoti dabar'.")

    # -----------------------------------------------------------------
    # TABLE POPULATION & SAVING
    # -----------------------------------------------------------------
    def populate_products_table(self):
        products = self.config.get("products", [])
        self.tbl_products.setRowCount(len(products))

        for row, p in enumerate(products):
            # 0. Pavadinimas
            self.tbl_products.setItem(row, 0, QTableWidgetItem(p.get("name", "")))

            # 1. Raktažodžiai
            kws = p.get("keywords", [])
            kw_str = ", ".join(kws) if isinstance(kws, list) else str(kws)
            self.tbl_products.setItem(row, 1, QTableWidgetItem(kw_str))

            # 2. Sluoksniai
            layers = p.get("layers", []) or []
            layer_str = " + ".join(layers)
            self.tbl_products.setItem(row, 2, QTableWidgetItem(layer_str))

            # 3. White Choke/Spread px
            spn_w = QSpinBox()
            spn_w.setRange(-10, 20)
            spn_w.setValue(_safe_int(p.get("choke_white_px", 1), 1))
            spn_w.setToolTip("+ teigiamas: Thinning (sutraukimas)\n- neigiamas: Thickening (išpūtimas)")
            self.tbl_products.setCellWidget(row, 3, spn_w)

            # 4. Primer Choke/Spread px
            spn_p = QSpinBox()
            spn_p.setRange(-10, 20)
            spn_p.setValue(_safe_int(p.get("choke_primer_px", 0), 0))
            spn_p.setToolTip("+ teigiamas: Thinning\n- neigiamas: Thickening")
            self.tbl_products.setCellWidget(row, 4, spn_p)

            # 5. Kėlimo seka
            cmb_order = QComboBox()
            cmb_order.addItems([
                "Primer ➔ White ➔ CMYK",
                "CMYK ➔ White ➔ Primer",
                "White ➔ CMYK"
            ])
            cur_order = p.get("dispatch_order") or ["Primer", "White", "CMYK"]
            order_str = " ➔ ".join(cur_order)
            idx = cmb_order.findText(order_str)
            if idx >= 0:
                cmb_order.setCurrentIndex(idx)
            else:
                cmb_order.addItem(order_str)
                cmb_order.setCurrentText(order_str)
            self.tbl_products.setCellWidget(row, 5, cmb_order)

            # 6. Pauzė (s)
            spn_delay = QDoubleSpinBox()
            spn_delay.setRange(0.0, 10.0)
            spn_delay.setSingleStep(0.1)
            spn_delay.setValue(_safe_float(p.get("inter_layer_delay_sec", self.config.get("inter_layer_delay_sec", 0.5)), 0.5))
            self.tbl_products.setCellWidget(row, 6, spn_delay)

            # 7. Hot Folder CMYK
            hf = p.get("hotfolders", {}) or {}
            self.tbl_products.setItem(row, 7, QTableWidgetItem(hf.get("CMYK", "")))

            # 8. Hot Folder White
            self.tbl_products.setItem(row, 8, QTableWidgetItem(hf.get("White", "")))

            # 9. Hot Folder Primer
            self.tbl_products.setItem(row, 9, QTableWidgetItem(hf.get("Primer", "")))

    def add_product_row(self):
        new_prod = {
            "id": f"custom_product_{int(time.time())}",
            "name": "Naujas Produktas",
            "keywords": ["naujas-produktas"],
            "layers": ["Primer", "White", "CMYK"],
            "dispatch_order": ["Primer", "White", "CMYK"],
            "choke_white_px": 1,
            "choke_primer_px": 0,
            "hotfolders": {
                "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
                "White": r"C:\MijCtrl\Hot\RH WHITE",
                "Primer": r"C:\MijCtrl\Hot\RH PRIMER"
            }
        }
        self.config.setdefault("products", []).append(new_prod)
        self.populate_products_table()
        self.log("➕ Pridėtas naujas produktas lentelėje. Nepamirškite išsaugoti pakeitimų!")

    def delete_selected_product(self):
        row = self.tbl_products.currentRow()
        products = self.config.get("products", [])
        if row < 0 or row >= len(products):
            QMessageBox.warning(self, "Pasirinkimas", "Prašome pažymėti produkto eilutę, kurią norite pašalinti.")
            return

        pname = products[row].get("name", "Produktas")
        reply = QMessageBox.question(
            self, "Pašalinti produktą",
            f"Ar tikrai norite pašalinti '{pname}' iš konfigūracijos?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            products.pop(row)
            self.populate_products_table()
            self.save_config()
            self.log(f"🗑️ Pašalintas produktas '{pname}'.")

    def save_products_from_table(self):
        def cell_text(row, col):
            it = self.tbl_products.item(row, col)
            return it.text().strip() if it is not None else ""

        products = self.config.get("products", [])
        problems = []
        for row in range(self.tbl_products.rowCount()):
            if row >= len(products):
                continue
            p = products[row]
            p["name"] = cell_text(row, 0) or p.get("name", f"Produktas {row + 1}")
            p["keywords"] = [k.strip() for k in cell_text(row, 1).split(",") if k.strip()]
            if not p["keywords"]:
                problems.append(f"'{p['name']}': nenurodyti raktažodžiai (produktas nebus atpažįstamas)")

            layers = []
            for raw in cell_text(row, 2).split("+"):
                name = VALID_LAYERS.get(raw.strip().lower())
                if raw.strip() and not name:
                    problems.append(f"'{p['name']}': nežinomas sluoksnis '{raw.strip()}' (galimi: Primer, White, CMYK)")
                elif name and name not in layers:
                    layers.append(name)
            p["layers"] = layers

            spn_w = self.tbl_products.cellWidget(row, 3)
            if spn_w:
                p["choke_white_px"] = spn_w.value()

            spn_p = self.tbl_products.cellWidget(row, 4)
            if spn_p:
                p["choke_primer_px"] = spn_p.value()

            cmb_order = self.tbl_products.cellWidget(row, 5)
            if cmb_order:
                order_parts = [VALID_LAYERS.get(x.strip().lower(), x.strip())
                               for x in cmb_order.currentText().split("➔") if x.strip()]
                p["dispatch_order"] = order_parts

            spn_delay = self.tbl_products.cellWidget(row, 6)
            if spn_delay:
                p["inter_layer_delay_sec"] = round(spn_delay.value(), 2)

            p["hotfolders"] = {
                "CMYK": cell_text(row, 7),
                "White": cell_text(row, 8),
                "Primer": cell_text(row, 9),
            }
            for layer in layers:
                if not p["hotfolders"].get(layer):
                    problems.append(f"'{p['name']}': sluoksniui {layer} nenurodytas Hotfolderis")

        # Išsaugome ir serverio bei vietinės talpyklos kelius
        self.config["server_inbox_folder"] = self.txt_server_path.text().strip()
        self.config["local_storage_folder"] = self.txt_local_storage.text().strip()

        self.save_config()
        for pr in problems:
            self.log(f"⚠️ {pr}")
        if problems:
            QMessageBox.warning(self, "Išsaugota su įspėjimais", "Nustatymai išsaugoti, tačiau rasta problemų:\n\n"
                                + "\n".join(problems[:15]))
        else:
            QMessageBox.information(self, "Išsaugota", "Produktų, talpyklos ir kėlimo nustatymai sėkmingai atnaujinti!")

    def populate_registry_table(self):
        jobs = self.registry.get_all_jobs()
        self.tbl_registry.setRowCount(len(jobs))

        for row, j in enumerate(jobs):
            item_id = QTableWidgetItem(str(j.get("job_id", "")))
            item_id.setData(Qt.UserRole, j.get("job_id", ""))
            self.tbl_registry.setItem(row, 0, item_id)
            self.tbl_registry.setItem(row, 1, QTableWidgetItem(str(j.get("product_name", ""))))
            self.tbl_registry.setItem(row, 2, QTableWidgetItem(str(j.get("bid", ""))))
            self.tbl_registry.setItem(row, 3, QTableWidgetItem(str(j.get("pid", ""))))
            plates = j.get("dispatched_plates", []) or []
            self.tbl_registry.setItem(row, 4, QTableWidgetItem(", ".join(plates)))

            status = j.get("status", "")
            label, color = STATUS_LABELS.get(status, (status, None))
            item_status = QTableWidgetItem(label)
            if color:
                item_status.setForeground(QColor(color))
            msg = j.get("message", "")
            if msg:
                attempts = j.get("attempts")
                item_status.setToolTip(f"{msg}" + (f"\nBandymų: {attempts}" if attempts else ""))
            self.tbl_registry.setItem(row, 5, item_status)

            loc_path = j.get("local_plates_dir") or j.get("local_pdf_path", "")
            self.tbl_registry.setItem(row, 6, QTableWidgetItem(loc_path))
            self.tbl_registry.setItem(row, 7, QTableWidgetItem(j.get("updated_at", "")))

    def _selected_job_id(self) -> Optional[str]:
        row = self.tbl_registry.currentRow()
        if row < 0:
            return None
        it = self.tbl_registry.item(row, 0)
        return it.data(Qt.UserRole) if it is not None else None

    def open_selected_job_folder(self):
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        if not job:
            QMessageBox.information(self, "Pasirinkimas", "Prašome pažymėti užsakymo eilutę.")
            return
        target_dir = job.get("local_plates_dir")
        if not target_dir or not os.path.exists(target_dir):
            lp = job.get("local_pdf_path")
            if lp and os.path.exists(os.path.dirname(lp)):
                target_dir = os.path.dirname(lp)

        if target_dir and os.path.exists(target_dir):
            self._open_in_explorer(target_dir)
        else:
            QMessageBox.warning(self, "Nerasta", f"Vietinis aplankas neegzistuoja arba dar nebuvo sukurtas:\n{target_dir}")

    def retry_selected_job(self):
        job_id = self._selected_job_id()
        job = self.registry.get_job(job_id) if job_id else None
        if not job:
            QMessageBox.information(self, "Pasirinkimas", "Prašome pažymėti užsakymo eilutę.")
            return
        extra = ""
        if job.get("dispatched_plates"):
            extra = (f"\n\nDĖMESIO: į RasterLink jau buvo įkelta: {', '.join(job['dispatched_plates'])}.\n"
                     f"Pakartojus šie sluoksniai bus įkelti dar kartą (galimas dublikatas).")
        reply = QMessageBox.question(
            self, "Pakartoti užsakymą",
            f"Pažymėti '{job_id}' pakartotiniam apdorojimui kitame skenavime?{extra}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.registry.reset_job(job_id):
                self.log(f"🔁 '{job_id}' pažymėtas pakartojimui – bus apdorotas kito skenavimo metu.")
            else:
                self.log(f"❌ Nepavyko pažymėti '{job_id}' pakartojimui. {self.registry.last_error}")
            self.populate_registry_table()

    def clear_registry(self):
        reply = QMessageBox.question(
            self, "Išvalyti atmintį",
            "Ar tikrai norite išvalyti visų apdorotų darbų atmintį?\n"
            "Tai padarius, programa vėl pamatys visus serverio failus kaip naujus!",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.registry.clear()
            self.populate_registry_table()
            self.log("🗑️ Užsakymų atmintis pilnai išvalyta.")

    # -------------------------------------------------------------
    # SCANNING & MONITORING
    # -------------------------------------------------------------
    def toggle_monitoring(self):
        if self.auto_timer.isActive():
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        interval_ms = self.config.get("scan_interval_sec", 10) * 1000
        self.auto_timer.start(interval_ms)
        self.lbl_monitor_status.setText("🟢 STEBĖJIMAS AKTYVUS")
        self.lbl_monitor_status.setStyleSheet("""
            background-color: #064e3b; color: #34d399; font-weight: bold;
            padding: 6px 14px; border-radius: 20px; border: 1px solid #059669;
        """)
        self.btn_toggle_monitor.setText("⏸️ Pristabdyti")
        self.btn_toggle_monitor.setStyleSheet("")
        self.log(f"▶️ Stebėjimas paleistas (tikrinama kas {self.config.get('scan_interval_sec', 10)}s).")
        self.start_scan()

    def stop_monitoring(self):
        self.auto_timer.stop()
        self.lbl_monitor_status.setText("⏸️ STEBĖJIMAS SUSTABDYTAS")
        self.lbl_monitor_status.setStyleSheet("""
            background-color: #334155; color: #fbbf24; font-weight: bold;
            padding: 6px 14px; border-radius: 20px; border: 1px solid #475569;
        """)
        self.btn_toggle_monitor.setText("▶️ Pradėti stebėjimą")
        self.btn_toggle_monitor.setStyleSheet("background-color: #059669; border: 1px solid #10b981;")
        self.log("⏸️ Stebėjimas pristabdytas.")

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return  # Jau vyksta skenavimas

        # Sinchronizuojame nustatymus iš UI
        self.config["server_inbox_folder"] = self.txt_server_path.text().strip()
        self.config["local_storage_folder"] = self.txt_local_storage.text().strip()
        self.config["custom_start_date"] = self.txt_target_date.text().strip()

        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = WorkerScanProcess(self.config, self.registry, self.router)
        self.worker.log_signal.connect(self.log)
        self.worker.job_processed.connect(self.on_job_processed)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.start()

    def on_job_processed(self, jname: str, data: dict):
        self.populate_registry_table()

    def on_scan_finished(self, total_found: int, new_processed: int):
        if self.registry.last_error:
            self.log(f"❌ {self.registry.last_error}")
        if new_processed > 0:
            self.log(f"🏁 Skenavimas baigtas: serveryje rasta {total_found} failų, apdorota naujų: {new_processed}.")
        self.populate_registry_table()

    def on_date_mode_changed(self, idx: int):
        if idx == 0:
            self.config["filter_date_mode"] = "today_only"
        elif idx == 1:
            self.config["filter_date_mode"] = "today_and_newer"
        else:
            self.config["filter_date_mode"] = "all"
        self._sync_date_field()
        self.save_config()

    def _sync_date_field(self):
        """'Šiandienos data' režime laukas rodo šiandieną ir yra užrakintas."""
        today_only = self.config.get("filter_date_mode", "today_only") == "today_only"
        if today_only:
            self.txt_target_date.setText(datetime.now().strftime("%Y-%m-%d"))
        self.txt_target_date.setEnabled(not today_only)

    def on_interval_changed(self, val: int):
        self.config["scan_interval_sec"] = val
        if self.auto_timer.isActive():
            self.auto_timer.setInterval(val * 1000)
        self.save_config()

    def browse_server_path(self):
        cur = self.txt_server_path.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Pasirinkite serverio aplanką", cur)
        if folder:
            self.txt_server_path.setText(folder)
            self.config["server_inbox_folder"] = folder
            self.save_config()

    def browse_local_storage_path(self):
        cur = self.txt_local_storage.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Pasirinkite vietinę talpyklą kompiuteryje", cur)
        if folder:
            self.txt_local_storage.setText(folder)
            self.config["local_storage_folder"] = folder
            self.save_config()

    def open_local_storage_in_explorer(self):
        folder = self.txt_local_storage.text().strip()
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Klaida", f"Nepavyko sukurti aplanko:\n{e}")
                return
        self._open_in_explorer(folder)

    def _open_in_explorer(self, folder: str):
        try:
            if hasattr(os, "startfile"):
                os.startfile(folder)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as e:
            QMessageBox.warning(self, "Klaida", f"Nepavyko atverti aplanko:\n{e}")

    def log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {text}")
        # Automatiškai slenkame žemyn
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())
        # Dubliuojame į failą (printflow_lite.log) – pėdsakas lieka ir po programos uždarymo
        logging.getLogger("printflow").info(text.strip())

    def closeEvent(self, event):
        self.auto_timer.stop()
        if self.worker and self.worker.isRunning():
            self.log("⏹️ Uždaroma – laukiama, kol baigsis einamasis žingsnis...")
            self.worker.stop()
            if not self.worker.wait(15000):
                # Gija užstrigo tinklo I/O (SMB). Visi įrašymai atominiai (.part/.tmp ➔ replace),
                # todėl priverstinis sustabdymas nepalieka sugadintų failų.
                logging.getLogger("printflow").warning("Worker neatsako – priverstinai stabdoma")
                self.worker.terminate()
                self.worker.wait(2000)
        event.accept()
