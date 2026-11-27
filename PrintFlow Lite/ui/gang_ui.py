"""
„Sudėti į rėmą“ – kelių ringholder užsakymų žiedai viename rėme
---------------------------------------------------------------
Įprastas srautas nesikeičia: kiekvienas užsakymas apdorojamas ir įkeliamas atskirai.
Šis langas papildomai sukuria vieną (ar kelis, jei netelpa) sujungtus rėmus iš pasirinktų
užsakymų ir, jei pažymėta, įkelia juos į RasterLink kaip atskirus darbus „RINKINYS_…“.
"""

import copy
import logging
import os
import time
import traceback
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHeaderView, QLineEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.prepress_lite import export_production_plates
from core.ring_gang import GangError, count_units, gang_jobs, plan_frames, print_profile, SLOTS_PER_FRAME
from ui.widgets import Switch, button, hbox, label, tok

GANG_SOURCE = "rinkinys"
SKIP_STATUSES = ("processing",)


def ring_jobs(registry_jobs: List[Dict], products: List[Dict], ring_ids) -> List[Dict]:
    """Užsakymai, kuriuos galima dėti į rėmą: ringholder produktas, yra vietinis originalas."""
    by_id = {p.get("id"): p for p in products}
    out = []
    for j in registry_jobs:
        prod = by_id.get(j.get("product_id"))
        if j.get("source") == GANG_SOURCE or prod is None or j.get("status") in SKIP_STATUSES:
            continue
        if not (prod.get("id") in ring_ids or prod.get("ring_band_fix")):
            continue
        if not os.path.isfile(j.get("local_pdf_path") or ""):
            continue
        out.append(j)
    out.sort(key=lambda j: (j.get("created_at", ""), j.get("job_id", "")))
    return out


def group_label(products: List[Dict]) -> str:
    names = sorted({p.get("name") or p.get("id", "?") for p in products})
    layers = " → ".join(l for l in (products[0].get("dispatch_order") or products[0].get("layers") or [])
                        if l in (products[0].get("layers") or []))
    return f"{', '.join(names)}  ·  {layers}"


class _CountThread(QThread):
    counted = Signal(str, int, str)   # job_id, žiedų sk. (-1 = klaida), klaida

    def __init__(self, jobs: List[Dict]):
        super().__init__()
        self.jobs = jobs
        self._run = True

    def stop(self):
        self._run = False

    def run(self):
        for j in self.jobs:
            if not self._run:
                return
            try:
                self.counted.emit(j["job_id"], count_units(j["local_pdf_path"]), "")
            except Exception as e:
                self.counted.emit(j["job_id"], -1, str(e))


class GangDialog(QDialog):
    """Užsakymų pasirinkimas. Rezultatas: self.selected (įrašai) ir self.dispatch (bool)."""

    def __init__(self, parent: QWidget, registry_jobs: List[Dict], products: List[Dict], ring_ids,
                 unit_cache: Dict[str, int], scan_running: bool = False):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        top = parent.window() if parent else None
        if top:
            self.setGeometry(top.geometry())
        self.products = {p.get("id"): p for p in products}
        self.all_jobs = ring_jobs(registry_jobs, products, ring_ids)
        self.cache = unit_cache
        self.selected: List[Dict] = []
        self.dispatch = True
        self._counter: Optional[_CountThread] = None
        self._groups: List[Tuple] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        card = QFrame()
        card.setObjectName("dialogCard")
        card.setMaximumWidth(980)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label("Sudėti ringholderius į vieną rėmą", "subtitle"))
        lay.addWidget(label("Pažymėti užsakymai sudedami į laisvas rėmo vietas (18 vietų rėme). Įprasti "
                            "užsakymų failai lieka kaip buvo – papildomai sukuriamas sujungtas failas "
                            "„RINKINYS_…“ ir vietų žemėlapis komplektavimui.", "secondary", wrap=True))

        self.txt_date = QLineEdit(datetime.now().strftime("%Y-%m-%d"))
        self.txt_date.setFixedWidth(130)
        self.txt_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_date.setToolTip("Užsakymo data (tuščia – visos datos)")
        self.txt_date.editingFinished.connect(self._fill)
        self.cmb_group = QComboBox()
        self.cmb_group.setMinimumWidth(420)
        self.cmb_group.currentIndexChanged.connect(lambda _i: self._fill_table())
        lay.addLayout(hbox(label("Užsakymo data", "secondary"), self.txt_date, None,
                           label("Produktai", "secondary"), self.cmb_group, spacing=8))

        self.tbl = QTableWidget()
        self.tbl.setColumnCount(4)
        self.tbl.setHorizontalHeaderLabels(["UŽSAKYMAS", "PRODUKTAS", "ŽIEDAI", "PASTABA"])
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionMode(QTableWidget.NoSelection)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(36)
        self.tbl.setShowGrid(False)
        self.tbl.setFocusPolicy(Qt.NoFocus)
        self.tbl.setWordWrap(False)
        self.tbl.setTextElideMode(Qt.ElideMiddle)
        hh = self.tbl.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 230), (2, 70), (3, 220)):
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
            self.tbl.setColumnWidth(c, w)
        self.tbl.itemChanged.connect(lambda _it: self._update_summary())
        self.tbl.setMinimumHeight(260)
        lay.addWidget(self.tbl, 1)
        self.lbl_empty = label("", "secondary", wrap=True)
        lay.addWidget(self.lbl_empty)

        self.sw_dispatch = Switch("Iškart įkelti į RasterLink (HotFolderius)")
        self.sw_dispatch.setChecked(not scan_running)
        self.sw_dispatch.setEnabled(not scan_running)
        if scan_running:
            self.sw_dispatch.setToolTip("Vyksta skenavimas – sujungtas failas bus tik sugeneruotas")
        self.lbl_summary = label("", "")
        self.btn_all = button("Žymėti visus", size="small", on_click=lambda: self._check_all(True))
        self.btn_none = button("Nuimti visus", size="small", on_click=lambda: self._check_all(False))
        lay.addLayout(hbox(self.btn_all, self.btn_none, None, self.lbl_summary, spacing=8))
        self.btn_ok = button("Sudėti į rėmą", "primary", "rings", on_click=self._accept)
        lay.addLayout(hbox(self.sw_dispatch, None, button("Atšaukti", on_click=self.reject), self.btn_ok))
        outer.addWidget(card, 0, Qt.AlignHCenter)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        self._fill()

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor("#171717")
        c.setAlphaF(0.28)
        p.fillRect(self.rect(), c)
        p.end()

    # -- duomenys ---------------------------------------------------------
    def _jobs_for_date(self) -> List[Dict]:
        d = self.txt_date.text().strip()
        return [j for j in self.all_jobs if not d or j.get("order_date") == d]

    def _fill(self):
        jobs = self._jobs_for_date()
        groups: Dict[Tuple, List[Dict]] = {}
        for j in jobs:
            groups.setdefault(print_profile(self.products[j["product_id"]]), []).append(j)
        self._groups = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        self.cmb_group.blockSignals(True)
        self.cmb_group.clear()
        for _prof, gj in self._groups:
            prods = [self.products[pid] for pid in dict.fromkeys(j["product_id"] for j in gj)]
            self.cmb_group.addItem(f"{group_label(prods)}  ({len(gj)} užs.)")
        self.cmb_group.blockSignals(False)
        self.cmb_group.setVisible(len(self._groups) > 0)
        self._fill_table()
        pending = [j for j in jobs if self._cached(j) is None]
        if pending:
            self._start_counting(pending)

    def _group_jobs(self) -> List[Dict]:
        i = self.cmb_group.currentIndex()
        return self._groups[i][1] if 0 <= i < len(self._groups) else []

    def _key(self, j: Dict) -> str:
        p = j.get("local_pdf_path", "")
        try:
            return f"{p}|{int(os.path.getmtime(p))}"
        except OSError:
            return p

    def _cached(self, j: Dict) -> Optional[int]:
        return self.cache.get(self._key(j))

    def _fill_table(self):
        jobs = self._group_jobs()
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(jobs))
        for r, j in enumerate(jobs):
            it = QTableWidgetItem(j["job_id"])
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if j.get("combined_into") else Qt.Checked)
            it.setData(Qt.UserRole, j["job_id"])
            self.tbl.setItem(r, 0, it)
            self.tbl.setItem(r, 1, QTableWidgetItem(j.get("product_name", "")))
            n = self._cached(j)
            self.tbl.setItem(r, 2, QTableWidgetItem("…" if n is None else ("klaida" if n < 0 else str(n))))
            note = f"Jau rinkinyje {j['combined_into']}" if j.get("combined_into") else ""
            it_note = QTableWidgetItem(note)
            it_note.setForeground(QColor(tok("muted")))
            self.tbl.setItem(r, 3, it_note)
        self.tbl.blockSignals(False)
        empty = not self.all_jobs or not jobs
        self.tbl.setVisible(not empty)
        self.lbl_empty.setVisible(empty)
        self.lbl_empty.setText("Nėra ringholder užsakymų su išsaugotu originalu šiai datai."
                               if empty else "")
        self._update_summary()

    def _start_counting(self, jobs: List[Dict]):
        if self._counter and self._counter.isRunning():
            self._counter.stop()
            self._counter.wait(5000)
        self._counter = _CountThread(jobs)
        self._counter.counted.connect(self._on_counted)
        self._counter.start()

    def _on_counted(self, job_id: str, n: int, err: str):
        j = next((x for x in self.all_jobs if x["job_id"] == job_id), None)
        if j is None:
            return
        self.cache[self._key(j)] = n
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it and it.data(Qt.UserRole) == job_id:
                cell = self.tbl.item(r, 2)
                cell.setText(str(n) if n >= 0 else "klaida")
                if err:
                    cell.setToolTip(err)
                    self.tbl.item(r, 3).setText(err)
        self._update_summary()

    def _checked(self) -> List[Dict]:
        by_id = {j["job_id"]: j for j in self._group_jobs()}
        out = []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it and it.checkState() == Qt.Checked and it.data(Qt.UserRole) in by_id:
                out.append(by_id[it.data(Qt.UserRole)])
        return out

    def _check_all(self, on: bool):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            self.tbl.item(r, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.tbl.blockSignals(False)
        self._update_summary()

    def _update_summary(self):
        jobs = self._checked()
        counts = [(j["job_id"], self._cached(j)) for j in jobs]
        known = [(jid, n) for jid, n in counts if n is not None and n > 0]
        rings = sum(n for _jid, n in known)
        pending = any(n is None for _jid, n in counts)
        frames = len(plan_frames(known)) if known else 0
        txt = f"Pažymėta: {len(jobs)} užs. · {rings}{'+' if pending else ''} žied."
        if frames:
            txt += f" → {frames} rėm. ({SLOTS_PER_FRAME} vietų)"
        self.lbl_summary.setText(txt)
        self.btn_ok.setEnabled(bool(jobs))

    def _accept(self):
        self.selected = [copy.deepcopy(j) for j in self._checked()]
        self.dispatch = self.sw_dispatch.isChecked() and self.sw_dispatch.isEnabled()
        if self.selected:
            self.accept()

    def done(self, r):
        if self._counter and self._counter.isRunning():
            self._counter.stop()
            self._counter.wait(15000)
        super().done(r)


class GangWorker(QThread):
    """Sujungia pasirinktus užsakymus, sugeneruoja plokštes ir (jei reikia) įkelia į HotFolderius."""
    log_signal = Signal(str)
    finished_gang = Signal(dict)   # {"frames": [job_id], "skipped": [(id, priežastis)], "error": str, "halted": str}

    def __init__(self, config: dict, registry, router, jobs: List[Dict], dispatch: bool,
                 storage_base: str, template_pdf: str, font_dir: str):
        super().__init__()
        self.config = copy.deepcopy(config)
        self.registry, self.router = registry, router
        self.jobs, self.dispatch = jobs, dispatch
        self.storage_base, self.template_pdf, self.font_dir = storage_base, template_pdf, font_dir
        self._run = True

    def stop(self):
        self._run = False

    def _log(self, m: str):
        self.log_signal.emit(m)

    def run(self):
        result = {"frames": [], "skipped": [], "error": "", "halted": ""}
        try:
            self._do(result)
        except GangError as e:
            result["error"] = str(e)
            self._log(f"❌ Sudėti į rėmą nepavyko: {e}")
        except Exception as e:
            result["error"] = str(e)
            self._log(f"❌ Netikėta klaida dedant į rėmą: {e}")
            logging.getLogger("printflow").error("Gang exception:\n%s", traceback.format_exc())
        finally:
            self.finished_gang.emit(result)

    def _do(self, result: dict):
        products = {p.get("id"): p for p in self.config.get("products", [])}
        profiles = {print_profile(products[j["product_id"]]) for j in self.jobs if j.get("product_id") in products}
        if len(profiles) != 1:
            raise GangError("pasirinkti produktai turi skirtingus sluoksnius / HotFolderius – jų sudėti negalima")
        prod = copy.deepcopy(products[self.jobs[0]["product_id"]])
        dates = {j.get("order_date", "") for j in self.jobs}
        date = dates.pop() if len(dates) == 1 and "" not in dates else datetime.now().strftime("%Y-%m-%d")
        name = f"RINKINYS_{date}_{time.strftime('%H%M%S')}"
        dpi = int(self.config.get("plate_dpi", 300) or 300)
        work_dir = os.path.join(self.storage_base, "paruostos_plokstes")
        self._log(f"\n🧩 SUDEDAMA Į RĖMĄ: {len(self.jobs)} užsakymai ({prod.get('name', '')}…)")

        frames, skipped = gang_jobs(self.jobs, products, work_dir, name, self.template_pdf, self.font_dir,
                                    log=self._log, should_continue=lambda: self._run)
        result["skipped"] = skipped
        for jid, why in skipped:
            self._log(f"   ⚠️ Praleista „{jid}“: {why}")

        layers = prod.get("layers") or ["Primer", "White", "CMYK"]
        dispatch_order = prod.get("dispatch_order") or layers
        delay = prod.get("inter_layer_delay_sec", self.config.get("inter_layer_delay_sec", 0.5))
        halted = ""
        for fr in frames:
            rid = fr["name"]
            members = fr["members"]
            entry = {
                "source": GANG_SOURCE,
                "product_id": prod.get("id", ""),
                "product_name": "Rinkinys · " + ", ".join(dict.fromkeys(
                    products[self._job(m)["product_id"]].get("name", "") for m in members)),
                "bid": ", ".join(dict.fromkeys(self._job(m).get("bid", "") for m in members if self._job(m).get("bid"))),
                "order_date": date,
                "members": members,
                "slots": fr["slots"],
                "rings": len(fr["slots"]),
                "local_pdf_path": fr["source_pdf"],
                "local_plates_dir": fr["dir"],
                "slot_map_pdf": fr["slot_map_pdf"],
                "status": "processing",
                "message": "",
            }
            self.registry.register_or_update(rid, entry)
            try:
                plates = export_production_plates(
                    source_pdf_path=fr["source_pdf"], job_name=rid, output_dir=fr["dir"], layers=layers,
                    choke_white_px=int(prod.get("choke_white_px", 1)),
                    choke_primer_px=int(prod.get("choke_primer_px", 0)), dpi=dpi)
            except Exception as e:
                self.registry.register_or_update(rid, {"status": "failed", "message": f"Prepress klaida: {e}"})
                self._log(f"❌ '{rid}': plokščių generavimas nepavyko: {e}")
                result["frames"].append(rid)
                continue
            for m in members:
                self.registry.register_or_update(m, {"combined_into": rid})
            if not self.dispatch or halted or not self._run:
                why = "Sugeneruota – į RasterLink nekelta" if not self.dispatch else \
                      f"Neįkelta: {halted or 'sustabdyta'}"
                self.registry.register_or_update(rid, {"status": "generated", "message": why})
                self._log(f"   💾 {rid}: plokštės sugeneruotos ({fr['dir']})")
                result["frames"].append(rid)
                continue
            self._log(f"   🚀 {rid}: keliama į Hot Folderius ({' ➔ '.join(dispatch_order)})...")
            dispatched = self.router.dispatch_plates(
                job_name=rid, plate_files=plates, product_config=prod, dispatch_order=dispatch_order,
                inter_layer_delay_sec=delay, log_cb=self._log,
                wait_for_pickup=bool(self.config.get("wait_for_pickup", True)),
                pickup_timeout_sec=float(self.config.get("pickup_timeout_sec", 60) or 60))
            sent = [d["layer"] for d in dispatched]
            expected = self.router.expected_layers(plates, prod)
            stop_reason = self.router.last_stop_reason
            common = {"dispatched_plates": sent, "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            if sent and set(sent) == set(expected):
                common.update({"status": "dispatched", "message": stop_reason})
                self._log(f"✅ RINKINYS ĮKELTAS Į RASTERLINK: '{rid}' ({len(fr['slots'])} žied.)")
            elif not sent:
                common.update({"status": "generated", "message": f"Neįkelta: {stop_reason}".strip()})
                self._log(f"❌ '{rid}': nė viena plokštė neįkelta ({stop_reason})")
            else:
                missing = [l for l in expected if l not in sent]
                common.update({"status": "dispatch_failed",
                               "message": f"Įkelta tik {sent}, trūksta {missing}. {stop_reason}".strip()})
                self._log(f"⛔ '{rid}': įkelta tik {sent}, NEĮKELTA {missing}.")
            if stop_reason:
                halted = stop_reason
                result["halted"] = stop_reason
            self.registry.register_or_update(rid, common)
            result["frames"].append(rid)

    def _job(self, jid: str) -> Dict:
        return next((j for j in self.jobs if j["job_id"] == jid), {})
