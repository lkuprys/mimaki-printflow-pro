"""
PrintFlow Lite UI
-----------------
Moderni, kompaktiška ir patikima valdymo panelė.
Leidžia valdyti serverio aplankus, datų filtrus, produktų thinning/thickening pikselius,
kėlimo eiliškumą ir peržiūrėti jau apdorotų darbų atmintį.
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QTabWidget, QFileDialog, QMessageBox, QFrame,
    QGroupBox, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon

from core.prepress_lite import export_production_plates
from core.scanner_lite import scan_server_directory
from core.router_lite import HotFolderRouterLite
from core.registry_lite import JobRegistryLite


def get_app_base_dir():
    """Nustato pagrindinį programos aplanką (tiek .exe, tiek .py paleidimui)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    this_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(this_dir)
    if os.path.exists(os.path.join(parent, "config.json")):
        return parent
    return this_dir


DEFAULT_CONFIG = {
  "server_inbox_folder": r"\\192.168.1.143\podbase-hotfolder\BENDRAS_PODBASE_HOTFOLDER",
  "local_fallback_inbox": r"E:\Projektai\TEST\INBOX_PRINT_FILES",
  "staging_folder": r"C:\Users\user\Desktop\mimaki\staging_lite",
  "auto_scan": True,
  "scan_interval_sec": 10,
  "inter_layer_delay_sec": 0.5,
  "filter_date_mode": "today_only",
  "custom_start_date": "",
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


class WorkerScanProcess(QThread):
    log_signal = Signal(str)
    job_processed = Signal(str, dict)
    scan_finished = Signal(int, int)  # total_found, new_processed

    def __init__(self, config: dict, registry: JobRegistryLite, router: HotFolderRouterLite):
        super().__init__()
        self.config = config
        self.registry = registry
        self.router = router
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        server_dir = self.config.get("server_inbox_folder", "")
        if not os.path.exists(server_dir):
            # Tikriname ar yra vietinis atsarginis aplankas
            fallback = self.config.get("local_fallback_inbox", "")
            if os.path.exists(fallback):
                server_dir = fallback
            else:
                self.log_signal.emit(f"⚠️ Serverio aplankas nepasiekiamas: {server_dir}")
                self.scan_finished.emit(0, 0)
                return

        products = self.config.get("products", [])
        filter_mode = self.config.get("filter_date_mode", "today_only")
        target_date = self.config.get("custom_start_date", "")
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

        self.log_signal.emit(f"🔍 Skenuojamas aplankas: {server_dir} (Data: {target_date}, Režimas: {filter_mode})...")

        found_jobs = scan_server_directory(
            root_dir=server_dir,
            products=products,
            filter_mode=filter_mode,
            target_date=target_date
        )

        new_count = 0
        for item in found_jobs:
            if not self._is_running:
                break

            filepath = item["filepath"]
            jname = item["job_name"]
            prod = item["product"]

            # Tikriname atmintį - ar jau buvo apdorotas
            if self.registry.is_file_processed(filepath):
                continue

            new_count += 1
            self.log_signal.emit(f"\n⚙️ APDOROJAMAS: '{jname}' [{prod['name']}] (BID: {item.get('bid', '-')})...")

            # Registruojame pradžią
            self.registry.register_or_update(jname, {
                "filepath": filepath,
                "product_id": prod["id"],
                "product_name": prod["name"],
                "bid": item.get("bid", ""),
                "pid": item.get("pid", ""),
                "order_date": item.get("order_date", ""),
                "status": "processing"
            })

            staging_base = self.config.get("staging_folder", "C:\\PrintFlow\\staging")
            job_out_dir = os.path.join(staging_base, jname)

            try:
                # 1. Prepress plokščių generavimas su thinning/thickening
                layers = prod.get("layers", ["Primer", "White", "CMYK"])
                choke_w = prod.get("choke_white_px", 1)
                choke_p = prod.get("choke_primer_px", 0)

                self.log_signal.emit(f"   [1/2] Generuojamos plokštės (White px={choke_w}, Primer px={choke_p})...")
                plates = export_production_plates(
                    source_pdf_path=filepath,
                    job_name=jname,
                    output_dir=job_out_dir,
                    layers=layers,
                    choke_white_px=choke_w,
                    choke_primer_px=choke_p
                )

                # 2. Perkėlimas į Hot Folderius su nustatytu eiliškumu ir pauze
                dispatch_order = prod.get("dispatch_order") or ["Primer", "White", "CMYK"]
                delay = self.config.get("inter_layer_delay_sec", 0.5)

                self.log_signal.emit(f"   [2/2] Keliama į Hot Folderius (Seka: {' ➔ '.join(dispatch_order)}, pauzė={delay}s)...")
                dispatched = self.router.dispatch_plates(
                    job_name=jname,
                    plate_files=plates,
                    product_config=prod,
                    dispatch_order=dispatch_order,
                    inter_layer_delay_sec=delay,
                    log_cb=lambda m: self.log_signal.emit(m)
                )

                # 3. Užfiksuojame sėkmingą pabaigą atmintyje
                self.registry.register_or_update(jname, {
                    "status": "dispatched",
                    "dispatched_plates": [d["layer"] for d in dispatched],
                    "staged_dir": job_out_dir,
                    "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S")
                })
                self.job_processed.emit(jname, self.registry.get_job(jname))
                self.log_signal.emit(f"✅ SĖKMINGAI PARUOŠTA IR ĮKELTA: '{jname}'")

            except Exception as e:
                self.log_signal.emit(f"❌ Klaida apdorojant '{jname}': {e}")
                self.registry.set_status(jname, "error", str(e))

        self.scan_finished.emit(len(found_jobs), new_count)


class MainWindowLite(QMainWindow):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        base_dir = get_app_base_dir()
        if not config_path:
            config_path = os.path.join(base_dir, "config.json")
        elif not os.path.isabs(config_path):
            config_path = os.path.join(base_dir, config_path)

        self.config_path = config_path
        self.config = self.load_config()

        registry_path = os.path.join(os.path.dirname(self.config_path), "jobs_registry.json")
        self.registry = JobRegistryLite(registry_path)
        self.router = HotFolderRouterLite(
            default_delay_sec=self.config.get("inter_layer_delay_sec", 0.5)
        )

        self.worker: WorkerScanProcess = None
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.start_scan)

        self.init_ui()

        # Jei įjungtas auto_scan, pradedame stebėjimą
        if self.config.get("auto_scan", True):
            self.start_monitoring()

    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg.get("products"):
                        return cfg
            except Exception:
                pass
        # Fallback į numatytąją konfigūraciją su visais 5 produktais
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return cfg

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.log("💾 Nustatymai sėkmingai išsaugoti į config.json.")
        except Exception as e:
            self.log(f"❌ Nepavyko išsaugoti nustatymų: {e}")

    def init_ui(self):
        self.setWindowTitle("Podbase Mimaki PrintFlow Lite v1.0")
        self.resize(1180, 820)
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
        lbl_sub = QLabel("Automatinis serverio stebėjimas, sluoksnių generavimas ir kėlimas į Hot Folderius")
        lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box)

        header.addStretch()

        self.lbl_monitor_status = QLabel("🟢 STEBĖJIMAS AKTYVUS")
        self.lbl_monitor_status.setStyleSheet("""
            background-color: #064e3b; color: #34d399; font-weight: bold;
            padding: 6px 14px; border-radius: 20px; border: 1px solid #059669;
        """)
        header.addWidget(self.lbl_monitor_status)

        self.btn_toggle_monitor = QPushButton("⏸️ Pristabdyti")
        self.btn_toggle_monitor.clicked.connect(self.toggle_monitoring)
        header.addWidget(self.btn_toggle_monitor)

        self.btn_scan_now = QPushButton("🔄 Skenuoti dabar")
        self.btn_scan_now.setObjectName("btnPrimary")
        self.btn_scan_now.clicked.connect(self.start_scan)
        header.addWidget(self.btn_scan_now)

        main_layout.addLayout(header)

        # -------------------------------------------------------------
        # 2. SERVERIO IR DATŲ JUOSTA
        # -------------------------------------------------------------
        grp_srv = QGroupBox("Tinklo Serverio ir Datų Filtravimas")
        lay_srv = QHBoxLayout(grp_srv)

        lay_srv.addWidget(QLabel("Serverio kelias:"))
        self.txt_server_path = QLineEdit(self.config.get("server_inbox_folder", ""))
        lay_srv.addWidget(self.txt_server_path, 3)

        btn_browse_srv = QPushButton("📂...")
        btn_browse_srv.clicked.connect(self.browse_server_path)
        lay_srv.addWidget(btn_browse_srv)

        lay_srv.addWidget(QLabel("Data:"))
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
        lay_srv.addWidget(self.cmb_date_mode)

        self.txt_target_date = QLineEdit(self.config.get("custom_start_date", datetime.now().strftime("%Y-%m-%d")))
        self.txt_target_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_target_date.setMaximumWidth(110)
        lay_srv.addWidget(self.txt_target_date)

        lay_srv.addWidget(QLabel("Intervalas (s):"))
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(3, 300)
        self.spn_interval.setValue(self.config.get("scan_interval_sec", 10))
        self.spn_interval.valueChanged.connect(self.on_interval_changed)
        lay_srv.addWidget(self.spn_interval)

        main_layout.addWidget(grp_srv)

        # -------------------------------------------------------------
        # 3. TABAI (Produktai, Atmintis, Žurnalas)
        # -------------------------------------------------------------
        self.tabs = QTabWidget()

        # TAB 1: Produktai ir Thinning/Thickening
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

        # TAB 2: Atmintis (Registry)
        tab_registry = QWidget()
        lay_reg = QVBoxLayout(tab_registry)

        reg_top = QHBoxLayout()
        reg_top.addWidget(QLabel("Atmintyje esantys užsakymai (šie failai NIEKADA nebus keliami pakartotinai):"))
        reg_top.addStretch()
        btn_refresh_reg = QPushButton("🔄 Atnaujinti")
        btn_refresh_reg.clicked.connect(self.populate_registry_table)
        reg_top.addWidget(btn_refresh_reg)
        btn_clear_reg = QPushButton("🗑️ Išvalyti atmintį")
        btn_clear_reg.clicked.connect(self.clear_registry)
        reg_top.addWidget(btn_clear_reg)
        lay_reg.addLayout(reg_top)

        self.tbl_registry = QTableWidget()
        self.tbl_registry.setColumnCount(7)
        self.tbl_registry.setHorizontalHeaderLabels([
            "Darbo pavadinimas", "Produktas", "BID", "PID", "Plokštės", "Būsena", "Laikas"
        ])
        self.tbl_registry.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tbl_registry.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
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
        lay_log.addWidget(self.txt_log)
        main_layout.addWidget(grp_log, 2)

        self.log("🚀 PrintFlow Lite sėkmingai paleista.")
        self.log(f"📂 Serverio šaknis: {self.config.get('server_inbox_folder')}")
        self.log(f"📦 Konfigūruota produktų: {len(self.config.get('products', []))}")

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
            layers = p.get("layers", [])
            layer_str = " + ".join(layers)
            self.tbl_products.setItem(row, 2, QTableWidgetItem(layer_str))

            # 3. White Choke/Spread px
            spn_w = QSpinBox()
            spn_w.setRange(-10, 20)
            spn_w.setValue(p.get("choke_white_px", 1))
            spn_w.setToolTip("+ teigiamas: Thinning (sutraukimas)\n- neigiamas: Thickening (išpūtimas)")
            self.tbl_products.setCellWidget(row, 3, spn_w)

            # 4. Primer Choke/Spread px
            spn_p = QSpinBox()
            spn_p.setRange(-10, 20)
            spn_p.setValue(p.get("choke_primer_px", 0))
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
            spn_delay.setRange(0.0, 5.0)
            spn_delay.setSingleStep(0.1)
            spn_delay.setValue(self.config.get("inter_layer_delay_sec", 0.5))
            self.tbl_products.setCellWidget(row, 6, spn_delay)

            # 7. Hot Folder CMYK
            hf = p.get("hotfolders", {})
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
        products = self.config.get("products", [])
        for row in range(self.tbl_products.rowCount()):
            if row < len(products):
                p = products[row]
                p["name"] = self.tbl_products.item(row, 0).text().strip()
                kws_raw = self.tbl_products.item(row, 1).text().strip()
                p["keywords"] = [k.strip() for k in kws_raw.split(",") if k.strip()]

                layers_raw = self.tbl_products.item(row, 2).text().strip()
                p["layers"] = [l.strip() for l in layers_raw.split("+") if l.strip()]

                spn_w = self.tbl_products.cellWidget(row, 3)
                if spn_w:
                    p["choke_white_px"] = spn_w.value()

                spn_p = self.tbl_products.cellWidget(row, 4)
                if spn_p:
                    p["choke_primer_px"] = spn_p.value()

                cmb_order = self.tbl_products.cellWidget(row, 5)
                if cmb_order:
                    order_text = cmb_order.currentText()
                    p["dispatch_order"] = [x.strip() for x in order_text.split("➔")]

                spn_delay = self.tbl_products.cellWidget(row, 6)
                if spn_delay:
                    self.config["inter_layer_delay_sec"] = spn_delay.value()

                hf_cmyk = self.tbl_products.item(row, 7).text().strip() if self.tbl_products.item(row, 7) else ""
                hf_white = self.tbl_products.item(row, 8).text().strip() if self.tbl_products.item(row, 8) else ""
                hf_primer = self.tbl_products.item(row, 9).text().strip() if self.tbl_products.item(row, 9) else ""
                p["hotfolders"] = {
                    "CMYK": hf_cmyk,
                    "White": hf_white,
                    "Primer": hf_primer
                }

        self.save_config()
        QMessageBox.information(self, "Išsaugota", "Produktų ir kėlimo nustatymai sėkmingai atnaujinti!")

    def populate_registry_table(self):
        jobs = self.registry.get_all_jobs()
        self.tbl_registry.setRowCount(len(jobs))

        for row, j in enumerate(jobs):
            self.tbl_registry.setItem(row, 0, QTableWidgetItem(j.get("job_id", "")))
            self.tbl_registry.setItem(row, 1, QTableWidgetItem(j.get("product_name", "")))
            self.tbl_registry.setItem(row, 2, QTableWidgetItem(j.get("bid", "")))
            self.tbl_registry.setItem(row, 3, QTableWidgetItem(j.get("pid", "")))
            plates = j.get("dispatched_plates", [])
            self.tbl_registry.setItem(row, 4, QTableWidgetItem(", ".join(plates)))

            status = j.get("status", "")
            item_status = QTableWidgetItem(status)
            if status == "dispatched":
                item_status.setText("🟢 Įkelta")
                item_status.setForeground(QColor("#34d399"))
            elif status == "processing":
                item_status.setText("⏳ Ruošiama")
                item_status.setForeground(QColor("#fbbf24"))
            elif status == "error":
                item_status.setText("❌ Klaida")
                item_status.setForeground(QColor("#f87171"))
            self.tbl_registry.setItem(row, 5, item_status)

            self.tbl_registry.setItem(row, 6, QTableWidgetItem(j.get("updated_at", "")))

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

    # -----------------------------------------------------------------
    # SCANNING & MONITORING
    # -----------------------------------------------------------------
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
        self.log(f"▶️ Stebėjimas paleistas (tikrinama kas {self.config.get('scan_interval_sec', 10)}s).")
        self.start_scan()

    def stop_monitoring(self):
        self.auto_timer.stop()
        self.lbl_monitor_status.setText("⏸️ STEBĖJIMAS SUSTABDYTAS")
        self.lbl_monitor_status.setStyleSheet("""
            background-color: #7f1d1d; color: #f87171; font-weight: bold;
            padding: 6px 14px; border-radius: 20px; border: 1px solid #dc2626;
        """)
        self.btn_toggle_monitor.setText("▶️ Tęsti")
        self.log("⏸️ Stebėjimas pristabdytas.")

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return  # Jau vyksta skenavimas

        # Sinchronizuojame nustatymus iš UI
        self.config["server_inbox_folder"] = self.txt_server_path.text().strip()
        self.config["custom_start_date"] = self.txt_target_date.text().strip()

        self.worker = WorkerScanProcess(self.config, self.registry, self.router)
        self.worker.log_signal.connect(self.log)
        self.worker.job_processed.connect(self.on_job_processed)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.start()

    def on_job_processed(self, jname: str, data: dict):
        self.populate_registry_table()

    def on_scan_finished(self, total_found: int, new_processed: int):
        if new_processed > 0:
            self.log(f"🏁 Skenavimas baigtas: rasta {total_found} failų, apdorota naujų: {new_processed}.")
        self.populate_registry_table()

    def on_date_mode_changed(self, idx: int):
        if idx == 0:
            self.config["filter_date_mode"] = "today_only"
            self.txt_target_date.setText(datetime.now().strftime("%Y-%m-%d"))
        elif idx == 1:
            self.config["filter_date_mode"] = "today_and_newer"
        else:
            self.config["filter_date_mode"] = "all"
        self.save_config()

    def on_interval_changed(self, val: int):
        self.config["scan_interval_sec"] = val
        if self.auto_timer.isActive():
            self.auto_timer.setInterval(val * 1000)
        self.save_config()

    def browse_server_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasirinkite serverio arba gaunamų failų aplanką")
        if folder:
            self.txt_server_path.setText(folder)
            self.config["server_inbox_folder"] = folder
            self.save_config()

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {msg}")
