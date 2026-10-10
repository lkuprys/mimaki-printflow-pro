"""
Atnaujinimų sąsaja: fono gijos, dialogai ir AppUpdater valdiklis.
Logika (API, patikra, PowerShell) – updater.py.
"""

import os
import time
from typing import Dict, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
import re

from PySide6.QtWidgets import QApplication, QDialog, QFrame, QProgressBar, QSizePolicy, QTextEdit, QVBoxLayout

import updater
from ui import theme as th
from ui.widgets import Badge, button, hbox, label, section


# ---------------------------------------------------------------------------
# Fono gijos
# ---------------------------------------------------------------------------
class VersionCheckWorker(QThread):
    result = Signal(dict)

    def __init__(self, repo: str, manual: bool, parent=None, api_base: str = "https://api.github.com"):
        super().__init__(parent)
        self.repo, self.manual, self.api_base = repo, manual, api_base

    def run(self):
        try:
            r = updater.check_for_update(self.repo, api_base=self.api_base)
        except Exception as e:
            r = {"status": "error", "info": None, "error": str(e)}
        r["manual"] = self.manual
        self.result.emit(r)


class DownloadWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, info: Dict, parent=None):
        super().__init__(parent)
        self.info = info
        self._cancel = False
        self.dest = os.path.join(updater.TEMP_DIR, f"printflow_update_v{info['version']}.zip")

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            updater.download_file(self.info["download_url"], self.dest, self.info.get("asset_size", 0),
                                  progress=lambda d, t: self.progress.emit(d, t),
                                  cancelled=lambda: self._cancel)
            ok, msg = updater.validate_update_zip(self.dest, self.info.get("asset_size", 0),
                                                  self.info.get("asset_sha256", ""))
            if not ok:
                updater._silent_remove(self.dest)
                self.failed.emit(msg)
                return
            self.finished_ok.emit(self.dest)
        except InterruptedError:
            self.failed.emit("cancelled")
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Dialogai (priglušintas fonas + kortelė su 24 px kampais)
# ---------------------------------------------------------------------------
class _OverlayDialog(QDialog):
    def __init__(self, parent, width=480):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        top = parent.window() if parent else None
        if top:
            self.setGeometry(top.geometry())
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        self.card = QFrame()
        self.card.setObjectName("dialogCard")
        self.card.setFixedWidth(width)
        self.card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(24, 24, 24, 20)
        self.body.setSpacing(10)
        outer.addWidget(self.card, 0, Qt.AlignCenter)

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        c = QColor("#171717")
        c.setAlphaF(0.28)
        p.fillRect(self.rect(), c)
        p.end()


class UpdateConfirmDialog(_OverlayDialog):
    def __init__(self, parent, info: Dict):
        super().__init__(parent, 520)
        self.body.addWidget(label("Yra nauja programos versija", "subtitle"))
        self.body.addLayout(hbox(Badge(f"Dabartinė v{updater.CURRENT_VERSION}", "neutral"), label("→", "secondary"),
                                 Badge(f"Nauja v{info['version']}", "success"), None))
        self.body.addSpacing(4)
        self.body.addWidget(section("Kas naujo"))
        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setFixedHeight(160)
        text = re.sub(r"^\s*#+ .*\n+", "", info.get("changelog") or "").strip()  # antraštė jau rodoma
        notes.setMarkdown(text or "Smulkūs patobulinimai.")
        notes.setObjectName("changelog")
        self.body.addWidget(notes)
        self.body.addWidget(label("Programa bus uždaryta, atnaujinta ir paleista iš naujo. Nustatymai, produktai ir "
                                  "užsakymų istorija neliečiami.", "secondary", wrap=True))
        self.body.addSpacing(8)
        self.btn_later = button("Priminti vėliau", on_click=self.reject)
        self.btn_now = button("Atnaujinti dabar", "primary", on_click=self.accept)
        self.body.addLayout(hbox(None, self.btn_later, self.btn_now))


class DownloadDialog(_OverlayDialog):
    cancel_requested = Signal()

    def __init__(self, parent, info: Dict):
        super().__init__(parent, 440)
        self.body.addWidget(label("Atsisiunčiamas atnaujinimas", "subtitle"))
        self.body.addWidget(label(f"PrintFlow Lite v{info['version']}", "secondary"))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 0)
        self.body.addWidget(self.bar)
        self.lbl = label("Jungiamasi…", "secondary")
        self.lbl.setFont(th.tnum_font(self.lbl.font()))
        self.body.addWidget(self.lbl)
        self.body.addSpacing(8)
        self.btn_cancel = button("Atšaukti", on_click=self.cancel_requested.emit)
        self.body.addLayout(hbox(None, self.btn_cancel))

    def set_progress(self, done: int, total: int):
        mb = lambda b: f"{b / 1024 / 1024:.1f}".replace(".", ",")
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.lbl.setText(f"{mb(done)} / {mb(total)} MB")
        else:
            self.lbl.setText(f"{mb(done)} MB")

    def set_status(self, text: str):
        self.bar.setRange(0, 0)
        self.lbl.setText(text)
        self.btn_cancel.setEnabled(False)


# ---------------------------------------------------------------------------
# Valdiklis
# ---------------------------------------------------------------------------
class AppUpdater(QObject):
    """
    Integracija su pagrindiniu langu (window turi: config, save_config, toasts, log,
    prepare_for_update, on_update_check_state).
    """
    state_changed = Signal(str, str)  # (būsena, tekstas) Nustatymų puslapiui

    def __init__(self, window, api_base: str = "https://api.github.com"):
        super().__init__(window)
        self.window = window
        self.api_base = api_base
        self._busy = False
        self._checking = False
        self._workers = []
        self._postponed: Dict[str, float] = {}
        self.last_check_text = "Dar netikrinta"
        self.timer = QTimer(self)
        self.timer.setInterval(updater.PERIODIC_CHECK_INTERVAL_MS)
        self.timer.timeout.connect(lambda: self.check(manual=False))
        # Testams: automatiškai atsakyti į dialogus (None = rodyti)
        self.auto_answer: Optional[bool] = None

    # --- konfigūracija ---
    def repo(self) -> str:
        return (self.window.config.get("github_repo") or updater.DEFAULT_GITHUB_REPO).strip()

    def auto_enabled(self) -> bool:
        return bool(self.window.config.get("auto_check_updates", True))

    def start(self):
        """Paleidus: rezultatas po 1,5 s, pirmas tikrinimas po 3,5 s, vėliau kas 30 min."""
        QTimer.singleShot(1500, self.show_last_update_result)
        if self.auto_enabled():
            QTimer.singleShot(3500, lambda: self.check(manual=False))
        self.apply_auto_setting()

    def apply_auto_setting(self):
        if self.auto_enabled():
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    # --- rezultatas po atnaujinimo ---
    def show_last_update_result(self):
        res = updater.read_last_update_result()
        if not res:
            return
        if res.get("ok"):
            self.window.toasts.show("success", "Programa atnaujinta",
                                    f"Dabar naudojate v{res.get('version', updater.CURRENT_VERSION)}.")
            self.window.log(f"✅ Programa atnaujinta į v{res.get('version')}.")
        else:
            self.window.toasts.show("error", "Atnaujinti nepavyko",
                                    f"{res.get('message', '')} Palikta v{res.get('old_version', updater.CURRENT_VERSION)}. "
                                    f"Žurnalas: {res.get('log', updater.UPDATER_LOG)}", sticky=True)
            self.window.log(f"❌ Atnaujinti nepavyko: {res.get('message', '')}")

    # --- tikrinimas ---
    def check(self, manual: bool = True):
        if self._busy or self._checking:
            if manual:
                self.window.toasts.show("info", "Atnaujinimai jau tikrinami")
            return
        self._checking = True
        self.state_changed.emit("checking", "Tikrinama…")
        w = VersionCheckWorker(self.repo(), manual, self, self.api_base)
        w.result.connect(self._on_check_result)
        self._keep(w)
        w.start()

    def _keep(self, w):
        self._workers.append(w)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)

    def _on_check_result(self, r: Dict):
        self._checking = False
        manual = r.get("manual", False)
        self.last_check_text = time.strftime("%Y-%m-%d %H:%M")
        status = r.get("status")
        if status == "error":
            self.state_changed.emit("error", "Nepavyko patikrinti")
            if manual:
                self.window.toasts.show("error", "Nepavyko patikrinti atnaujinimų", r.get("error", ""))
            self.window.log(f"⚠️ Atnaujinimų patikra nepavyko: {r.get('error', '')}")
            return
        if status == "no_release":
            self.state_changed.emit("ok", "Išleidimų dar nėra")
            if manual:
                self.window.toasts.show("info", "Išleidimų dar nėra",
                                        f"Repozitorijoje {self.repo()} nerasta PrintFlow Lite versijų.")
            return
        if status == "no_update":
            self.state_changed.emit("ok", f"Naujausia versija (v{updater.CURRENT_VERSION})")
            if manual:
                self.window.toasts.show("success", "Naudojate naujausią versiją", f"v{updater.CURRENT_VERSION}")
            return
        self.on_update_available(r["info"], manual)

    def on_update_available(self, info: Dict, manual: bool):
        self.state_changed.emit("update", f"Yra nauja versija v{info['version']}")
        if not info.get("download_url"):
            if manual:
                self.window.toasts.show("warning", "Nėra diegimo failo", f"Versija v{info['version']} be ZIP failo.")
            return
        until = self._postponed.get(info["version"], 0)
        if not manual and time.time() < until:
            return
        if self._busy:
            return
        self._busy = True
        try:
            if self.auto_answer is None:
                accepted = UpdateConfirmDialog(self.window, info).exec() == QDialog.Accepted
            else:
                accepted = self.auto_answer
        finally:
            self._busy = False
        if not accepted:
            self._postponed[info["version"]] = time.time() + updater.POSTPONE_SECONDS
            self.window.log(f"Atnaujinimas v{info['version']} atidėtas.")
            return
        self.download(info)

    # --- atsisiuntimas ir diegimas ---
    def download(self, info: Dict):
        self._busy = True
        self.dialog = DownloadDialog(self.window, info)
        w = DownloadWorker(info, self)
        self.dialog.cancel_requested.connect(w.cancel)
        w.progress.connect(self.dialog.set_progress)
        w.finished_ok.connect(lambda path: self._on_downloaded(path, info))
        w.failed.connect(self._on_download_failed)
        self._keep(w)
        self.window.log(f"Atsisiunčiama v{info['version']}…")
        w.start()
        if self.auto_answer is None:
            self.dialog.show()

    def _on_download_failed(self, msg: str):
        self._busy = False
        self.dialog.close()
        if msg == "cancelled":
            self.window.toasts.show("info", "Atnaujinimas atšauktas")
            return
        self.window.toasts.show("error", "Atnaujinimo atsisiųsti nepavyko", msg, sticky=True)
        self.window.log(f"❌ Atnaujinimo atsisiųsti nepavyko: {msg}")
        self.state_changed.emit("error", "Atsisiųsti nepavyko")

    def _on_downloaded(self, path: str, info: Dict):
        self.dialog.set_status("Diegiama… programa netrukus pasileis iš naujo.")
        self.window.log(f"Atnaujinimas v{info['version']} atsisiųstas ir patikrintas.")
        QTimer.singleShot(1200, lambda: self._apply(path, info))

    def _apply(self, path: str, info: Dict):
        try:
            self.window.prepare_for_update()
            updater.apply_update(path, info)
        except Exception as e:
            self._busy = False
            self.dialog.close()
            self.window.toasts.show("error", "Atnaujinti nepavyko", str(e), sticky=True)
            self.window.log(f"❌ Atnaujinti nepavyko: {e}")
            self.state_changed.emit("error", "Atnaujinti nepavyko")
            return
        # Procesas baigiamas iškart – kad PowerShell galėtų pakeisti failus
        app = QApplication.instance()
        lock = getattr(app, "_instance_lock", None)
        if lock is not None:
            try:
                lock.unlock()
            except Exception:
                pass
        app.quit()
        os._exit(0)
