"""
Batch sheet sąsaja: kortelė „Sudėti į stalą“, peržiūra per visą ekraną ir spausdinimas.
"""

import os
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPainter, QPixmap, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)

from ui.widgets import Badge, Card, button, hbox, icon_button, label, section


# ---------------------------------------------------------------------------
# Spausdinimas
# ---------------------------------------------------------------------------
def print_images(paths: List[str]) -> Tuple[bool, str]:
    """Spausdina lapus numatytuoju Windows spausdintuvu (kiekvienas lapas – atskiras puslapis)."""
    from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        return False, "Nėra lapų spausdinimui"
    default = QPrinterInfo.defaultPrinter()
    if default.isNull():
        return False, "Nenustatytas numatytasis spausdintuvas (Windows → Spausdintuvai)"
    printer = QPrinter(default, QPrinter.HighResolution)
    printer.setDocName(os.path.basename(paths[0]))
    painter = QPainter()
    if not painter.begin(printer):
        return False, f"Nepavyko pradėti spausdinti į „{default.printerName()}“"
    try:
        for i, path in enumerate(paths):
            if i:
                printer.newPage()
            pm = QPixmap(path)
            if pm.isNull():
                continue
            area = painter.viewport()
            scaled = pm.size().scaled(area.size(), Qt.KeepAspectRatio)
            painter.setViewport(area.x(), area.y(), scaled.width(), scaled.height())
            painter.setWindow(pm.rect())
            painter.drawPixmap(0, 0, pm)
            painter.setViewport(area)
            painter.setWindow(area)
    finally:
        painter.end()
    return True, default.printerName()


# ---------------------------------------------------------------------------
# Paveikslėlis, kuris prisitaiko prie vietos
# ---------------------------------------------------------------------------
class SheetImage(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self._pm: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Spustelėkite – atidaryti per visą ekraną")

    def set_path(self, path: Optional[str]):
        self._pm = QPixmap(path) if path and os.path.isfile(path) else None
        if self._pm is not None and self._pm.isNull():
            self._pm = None
        self._rescale()

    def has_image(self) -> bool:
        return self._pm is not None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._pm is None:
            self.clear()
            return
        dpr = self.devicePixelRatioF()
        target = QSize(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        scaled = self._pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self.setPixmap(scaled)

    def mouseReleaseEvent(self, e):
        if self._pm is not None and e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ---------------------------------------------------------------------------
# Peržiūra per visą ekraną
# ---------------------------------------------------------------------------
class SheetViewerDialog(QDialog):
    def __init__(self, parent: QWidget, paths: List[str], title: str, index: int = 0,
                 on_print: Optional[Callable[[List[str]], None]] = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        top = parent.window() if parent else None
        if top:
            self.setGeometry(top.geometry())
        self.paths, self.index, self.zoom = paths, index, 0.0  # 0 = pritaikyti prie lango

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        card = QFrame()
        card.setObjectName("dialogCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        self.lbl_title = label(title, "subtitle")
        self.lbl_page = label("", "secondary")
        self.btn_prev = icon_button("left", "Ankstesnis lapas (←)", lambda: self.go(-1))
        self.btn_next = icon_button("right", "Kitas lapas (→)", lambda: self.go(+1))
        btn_print = button("Spausdinti", icon="send", on_click=lambda: on_print(self.paths) if on_print else None)
        lay.addLayout(hbox(self.lbl_title, self.lbl_page, None,
                           button("−", on_click=lambda: self.set_zoom(-1), tooltip="Mažinti"),
                           button("Pritaikyti", on_click=lambda: self.set_zoom(0), tooltip="Pritaikyti prie lango"),
                           button("+", on_click=lambda: self.set_zoom(+1), tooltip="Didinti"),
                           self.btn_prev, self.btn_next, btn_print,
                           button("Uždaryti", "primary", on_click=self.accept)))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.img)
        lay.addWidget(self.scroll, 1)
        outer.addWidget(card)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.accept)
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.go(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.go(+1))
        self._render()

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor("#171717")
        c.setAlphaF(0.28)
        p.fillRect(self.rect(), c)
        p.end()

    def go(self, delta: int):
        n = self.index + delta
        if 0 <= n < len(self.paths):
            self.index = n
            self._render()

    def set_zoom(self, direction: int):
        if direction == 0:
            self.zoom = 0.0
        else:
            base = self.zoom or self._fit_factor()
            self.zoom = max(0.1, min(4.0, base * (1.25 if direction > 0 else 0.8)))
        self._render()

    def _fit_factor(self) -> float:
        pm = QPixmap(self.paths[self.index])
        if pm.isNull():
            return 1.0
        vp = self.scroll.viewport().size()
        return min(vp.width() / pm.width(), vp.height() / pm.height(), 4.0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.zoom == 0.0:
            self._render()

    def _render(self):
        if not self.paths:
            return
        pm = QPixmap(self.paths[self.index])
        self.lbl_page.setText(f"Lapas {self.index + 1} iš {len(self.paths)}" if len(self.paths) > 1 else "")
        self.btn_prev.setVisible(len(self.paths) > 1)
        self.btn_next.setVisible(len(self.paths) > 1)
        if pm.isNull():
            self.img.setText("Nepavyko atidaryti paveikslėlio")
            self.img.adjustSize()
            return
        factor = self.zoom or self._fit_factor()
        scaled = pm.scaled(max(1, int(pm.width() * factor)), max(1, int(pm.height() * factor)),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.img.setPixmap(scaled)
        self.img.resize(scaled.size())


# ---------------------------------------------------------------------------
# Kortelė „Sudėti į stalą“
# ---------------------------------------------------------------------------
class BatchSheetCard(Card):
    """Rodo naujausio užsakymo su batch sheet lapą; žemiau – ankstesni užsakymai."""

    def __init__(self, on_print: Callable[[List[str]], None], on_open_folder: Callable[[str], None]):
        super().__init__(margins=(20, 16, 20, 16), spacing=10)
        self.on_print, self.on_open_folder = on_print, on_open_folder
        self.jobs: List[Dict] = []
        self.job: Optional[Dict] = None
        self.page = 0

        self.lbl_job = label("", "strong")
        self.badge = Badge("", "neutral")
        self.badge.hide()
        self.body.addLayout(hbox(section("Sudėti į stalą"), None, self.badge))
        self.body.addWidget(self.lbl_job)

        self.image = SheetImage()
        self.image.clicked.connect(self.open_viewer)
        self.body.addWidget(self.image, 1)
        self.lbl_empty = label("Pažymėtų produktų (Produktai → „Rodyti batch sheet“) lapai atsiras čia.",
                               "secondary", wrap=True)
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.lbl_empty, 1)

        self.btn_prev = icon_button("left", "Ankstesnis lapas", lambda: self.set_page(self.page - 1))
        self.btn_next = icon_button("right", "Kitas lapas", lambda: self.set_page(self.page + 1))
        self.lbl_page = label("", "secondary")
        self.btn_print = button("Spausdinti", icon="send", on_click=lambda: self.on_print(self.sheets()))
        self.btn_folder = button("Atidaryti aplanką", icon="folder",
                                 on_click=lambda: self.on_open_folder(os.path.dirname(self.sheets()[0])))
        self.btn_full = button("Per visą ekraną", on_click=self.open_viewer)
        self.body.addLayout(hbox(self.btn_prev, self.lbl_page, self.btn_next, None,
                                 self.btn_full, self.btn_folder, self.btn_print))

        self.recent_row = QHBoxLayout()
        self.recent_row.setSpacing(6)
        self.recent_wrap = QWidget()
        self.recent_wrap.setObjectName("plain")
        rl = QVBoxLayout(self.recent_wrap)
        rl.setContentsMargins(0, 4, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(section("Ankstesni"))
        rl.addLayout(self.recent_row)
        self.body.addWidget(self.recent_wrap)
        self._render()

    # --- duomenys ---
    def set_jobs(self, jobs: List[Dict]):
        """jobs – registro įrašai su batch_sheet_expected, naujausi pirmi.
        Atėjus naujam užsakymui rodomas jis; kitaip lieka operatoriaus pasirinktas."""
        self.jobs = jobs[:6]
        newest_id = self.jobs[0].get("job_id") if self.jobs else None
        selected_id = self.job.get("job_id") if self.job else None
        if newest_id != self._newest_id or selected_id is None:
            self.job, self.page = (self.jobs[0] if self.jobs else None), 0
        else:
            self.job = next((j for j in self.jobs if j.get("job_id") == selected_id), self.jobs[0])
        self._newest_id = newest_id
        self.page = min(self.page, max(0, len(self.sheets()) - 1))
        self._render()

    _newest_id = None

    def show_job(self, job_id: str):
        self.job = next((j for j in self.jobs if j.get("job_id") == job_id), self.job)
        self.page = 0
        self._render()

    def sheets(self) -> List[str]:
        return [p for p in (self.job or {}).get("batch_sheets", []) if os.path.isfile(p)]

    def set_page(self, n: int):
        if 0 <= n < len(self.sheets()):
            self.page = n
            self._render()

    def open_viewer(self):
        sheets = self.sheets()
        if sheets:
            SheetViewerDialog(self.window(), sheets, self._title(), self.page, self.on_print).exec()

    def _title(self) -> str:
        j = self.job or {}
        bid = f"BID {j['bid']} · " if j.get("bid") else ""
        return f"{bid}{j.get('product_name', '')} · {j.get('job_id', '')}"

    # --- vaizdas ---
    def _render(self):
        sheets = self.sheets()
        has_job = self.job is not None
        self.lbl_job.setVisible(has_job)
        self.lbl_job.setText(self._title() if has_job else "")
        if not has_job:
            self.badge.hide()
        elif sheets:
            self.badge.set(str(self.job.get("dispatched_at") or self.job.get("updated_at", ""))[11:16] or "Įkelta",
                           "neutral")
            self.badge.show()
        else:
            self.badge.set("Batch sheet nerastas", "warning")
            self.badge.show()
        self.image.set_path(sheets[self.page] if sheets and self.page < len(sheets) else None)
        self.image.setVisible(bool(sheets))
        self.lbl_empty.setVisible(not sheets)
        if has_job and not sheets:
            self.lbl_empty.setText("Šiam užsakymui batch sheet lapas serveryje dar nerastas – "
                                   "programa jo ieškos dar 30 min.")
        elif not has_job:
            self.lbl_empty.setText("Pažymėtų produktų (Produktai → „Rodyti batch sheet“) lapai atsiras čia.")
        multi = len(sheets) > 1
        for w in (self.btn_prev, self.btn_next, self.lbl_page):
            w.setVisible(multi)
        self.lbl_page.setText(f"Lapas {self.page + 1} iš {len(sheets)}")
        for b in (self.btn_print, self.btn_folder, self.btn_full):
            b.setEnabled(bool(sheets))

        while self.recent_row.count():
            w = self.recent_row.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        others = [j for j in self.jobs if not self.job or j.get("job_id") != self.job.get("job_id")]
        for j in others[:5]:
            text = (j.get("bid") and f"BID {j['bid']}") or j.get("job_id", "")[:24]
            b = button(text, size="small", on_click=lambda _=False, jid=j.get("job_id"): self.show_job(jid),
                       tooltip=f"{j.get('job_id')}\n{j.get('product_name', '')}")
            self.recent_row.addWidget(b)
        self.recent_row.addStretch(1)
        self.recent_wrap.setVisible(bool(others))
