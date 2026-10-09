"""
Podbase WORK elementai: piktogramos, jungiklis, segmentų valdiklis, ženkliukai,
kortelės, iššokantys pranešimai ir patvirtinimo dialogas.
"""

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QSize, QTimer, QRectF, QByteArray, Signal, QEvent, QPoint
from PySide6.QtGui import QPainter, QColor, QPixmap, QIcon, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QApplication
)

from ui import theme as th

# ---------------------------------------------------------------------------
# Tema (vienas globalus būvis – keičiamas per apply_theme)
# ---------------------------------------------------------------------------
_state = {"theme": "light"}
_themed: List = []  # objektai su .refresh_theme()


def current_theme() -> str:
    return _state["theme"]


def tok(name: str) -> str:
    return th.tokens(_state["theme"])[name]


def register_themed(obj):
    _themed.append(obj)
    return obj


def apply_theme(app: QApplication, theme: str):
    _state["theme"] = "dark" if theme == "dark" else "light"
    app.setStyleSheet(th.build_qss(_state["theme"]))
    alive = []
    for obj in _themed:
        try:
            obj.refresh_theme()
            alive.append(obj)
        except RuntimeError:
            pass  # objektas jau sunaikintas
    _themed[:] = alive


# ---------------------------------------------------------------------------
# Piktogramos (24×24 linijinės, spalva iš temos)
# ---------------------------------------------------------------------------
_PATHS: Dict[str, str] = {
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.34-5.66L20 8.5"/><path d="M20 3.5v5h-5"/>',
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M18 13l-6 6-6-6"/>',
    "log": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.5 12h-2M21.5 12h-2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V5.5a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 10"/>',
    "alert": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.3v.2"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.3v.2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.7v.2"/>',
    "retry": '<path d="M4 12a8 8 0 1 0 2.34-5.66L4 8.5"/><path d="M4 3.5v5h5"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "send": '<path d="M4 12l16-8-6 16-2.5-6.5z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
}


def make_icon(name: str, color: str, size: int = 16) -> QIcon:
    body = _PATHS.get(name, "")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


class _IconBinding:
    def __init__(self, button, name, role):
        self.button, self.name, self.role = button, name, role

    def refresh_theme(self):
        color = self.role if self.role.startswith("#") else tok(self.role)
        self.button.setIcon(make_icon(self.name, color))
        self.button.setIconSize(QSize(16, 16))


def set_icon(button, name: str, role: str = "secondary"):
    """Piktograma, kuri perpiešiama keičiant temą. role – žetonas arba #spalva."""
    b = _IconBinding(button, name, role)
    b.refresh_theme()
    register_themed(b)
    button._icon_binding = b
    return button


# ---------------------------------------------------------------------------
# Mygtukai, etiketės, kortelės
# ---------------------------------------------------------------------------
def button(text: str = "", variant: str = "", icon: str = "", size: str = "",
           on_click: Optional[Callable] = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if size:
        b.setProperty("size", size)
    if icon:
        role = {"primary": "on_primary", "danger": "#D64545", "danger-solid": "#FFFFFF",
                "success": "#FFFFFF"}.get(variant, "secondary")
        set_icon(b, icon, role)
    if on_click:
        b.clicked.connect(on_click)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def icon_button(icon: str, tooltip: str, on_click: Optional[Callable] = None) -> QPushButton:
    return button("", "icon", icon, on_click=on_click, tooltip=tooltip)


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if role:
        l.setProperty("role", role)
    if wrap:
        l.setWordWrap(True)
    return l


def section(text: str) -> QLabel:
    return label(text.upper(), "section")


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.NoFrame)
    return f


class Card(QFrame):
    def __init__(self, margins=(20, 18, 20, 18), spacing=12):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)


def field(label_text: str, widget: QWidget, caption: str = "") -> QWidget:
    """Etiketė virš lauko (6 px), užuomina po lauku."""
    w = QWidget()
    w.setObjectName("plain")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(label(label_text, "label"))
    lay.addWidget(widget)
    if caption:
        c = label(caption, "caption", wrap=True)
        lay.addWidget(c)
        w.caption = c
    return w


def hbox(*items, spacing=8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


# ---------------------------------------------------------------------------
# Būsenos ženkliukas
# ---------------------------------------------------------------------------
class Badge(QLabel):
    def __init__(self, text: str = "", kind: str = "neutral", dot: bool = True):
        super().__init__()
        self._text, self._kind, self._dot = text, kind, dot
        self.setFixedHeight(24)
        register_themed(self)
        self.refresh_theme()

    def set(self, text: str, kind: str = None):
        self._text = text
        if kind:
            self._kind = kind
        self.refresh_theme()

    def kind(self) -> str:
        return self._kind

    def refresh_theme(self):
        color, bg, _ = th.status_colors(self._kind, current_theme())
        self.setText(("●  " if self._dot else "") + self._text)
        self.setStyleSheet(f"QLabel {{ background: {bg}; color: {color}; border-radius: 12px; "
                           f"padding: 0 10px; font-size: 12px; font-weight: 500; }}")


# ---------------------------------------------------------------------------
# Jungiklis (vietoj varnelės)
# ---------------------------------------------------------------------------
class Switch(QAbstractButton):
    def __init__(self, text: str = ""):
        super().__init__()
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        w = 36 + (10 + fm.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(w + 2, max(24, fm.height() + 4))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - 20) / 2
        on = self.isChecked()
        enabled = self.isEnabled()
        track = QColor(tok("text") if on else tok("strong"))
        if not enabled:
            track.setAlphaF(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, y, 36, 20), 10, 10)
        p.setBrush(QColor(tok("card")))
        p.drawEllipse(QRectF(18 if on else 2, y + 2, 16, 16))
        if self.text():
            p.setPen(QPen(QColor(tok("text") if enabled else tok("disabled"))))
            p.setFont(self.font())
            p.drawText(QRectF(46, 0, self.width() - 46, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


# ---------------------------------------------------------------------------
# Segmentų valdiklis
# ---------------------------------------------------------------------------
class Segmented(QFrame):
    changed = Signal(int)

    def __init__(self, options: List[str], current: int = 0):
        super().__init__()
        self.setObjectName("segmented")
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(current).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int):
        b = self.group.button(i)
        if b:
            b.setChecked(True)


# ---------------------------------------------------------------------------
# Iššokantys pranešimai (dešinėje viršuje, po skirtukais)
# ---------------------------------------------------------------------------
_TOAST_ICON = {"success": "check", "warning": "alert", "error": "error", "info": "info"}


class Toast(QFrame):
    closed = Signal(object)

    def __init__(self, parent: QWidget, kind: str, title: str, text: str = "", sticky: bool = False):
        super().__init__(parent)
        self.kind = kind
        color, bg, border = th.status_colors(kind, current_theme())
        self.setObjectName("toast")
        self.setStyleSheet(
            f"QFrame#toast {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}"
            f"QFrame#toast QLabel {{ background: transparent; }}"
        )
        self.setFixedWidth(400)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 10, 12)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(make_icon(_TOAST_ICON.get(kind, "info"), color).pixmap(16, 16))
        ic.setAlignment(Qt.AlignTop)
        ic.setContentsMargins(0, 2, 0, 0)
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(title, "strong", wrap=True)
        col.addWidget(t)
        if text:
            col.addWidget(label(text, "secondary", wrap=True))
        lay.addLayout(col, 1)
        x = QPushButton()
        x.setProperty("variant", "icon")
        x.setFixedSize(26, 26)
        x.setStyleSheet("QPushButton { min-height: 26px; max-height: 26px; min-width: 26px; max-width: 26px; }")
        x.setIcon(make_icon("close", tok("secondary")))
        x.setCursor(Qt.PointingHandCursor)
        x.clicked.connect(self.dismiss)
        lay.addWidget(x, 0, Qt.AlignTop)
        if not sticky:
            QTimer.singleShot(10000 if kind == "warning" else 4500 if kind == "error" else 3500, self.dismiss)

    def dismiss(self):
        if self.isVisible():
            self.hide()
            self.closed.emit(self)
            self.deleteLater()


class ToastHost:
    """Valdo pranešimų stulpelį lango dešiniame viršutiniame kampe."""

    def __init__(self, window: QWidget, top_offset: Callable[[], int]):
        self.window = window
        self.top_offset = top_offset
        self.toasts: List[Toast] = []
        window.installEventFilter(_ResizeFilter(window, self.relayout))

    def show(self, kind: str, title: str, text: str = "", sticky: bool = False):
        # Tas pats pranešimas nedubliuojamas
        for t in self.toasts:
            if getattr(t, "_key", None) == (kind, title, text):
                return t
        toast = Toast(self.window, kind, title, text, sticky)
        toast._key = (kind, title, text)
        toast.closed.connect(self._on_closed)
        self.toasts.append(toast)
        if len(self.toasts) > 4:
            self.toasts[0].dismiss()
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self.relayout()
        return toast

    def _on_closed(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        self.relayout()

    def relayout(self):
        y = self.top_offset() + 16
        for t in self.toasts:
            t.adjustSize()
            t.move(QPoint(self.window.width() - t.width() - 24, y))
            t.raise_()
            y += t.height() + 8


class _ResizeFilter(QWidget):
    def __init__(self, parent, cb):
        super().__init__(parent)
        self.cb = cb
        self.hide()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            QTimer.singleShot(0, self.cb)
        return False


# ---------------------------------------------------------------------------
# Patvirtinimo dialogas (priglušintas fonas + kortelė su 24 px kampais)
# ---------------------------------------------------------------------------
class ConfirmDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, text: str, confirm_text: str,
                 cancel_text: str = "Atšaukti", danger: bool = True):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        top = parent.window() if parent else None
        if top:
            self.setGeometry(top.geometry())

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("dialogCard")
        card.setFixedWidth(440)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 24, 24, 20)
        lay.setSpacing(8)
        lay.addWidget(label(title, "subtitle", wrap=True))
        lay.addWidget(label(text, "secondary", wrap=True))
        lay.addSpacing(12)
        self.btn_cancel = button(cancel_text, on_click=self.reject)
        self.btn_ok = button(confirm_text, "danger-solid" if danger else "primary", on_click=self.accept)
        lay.addLayout(hbox(None, self.btn_cancel, self.btn_ok))
        outer.addWidget(card)

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor("#171717")
        c.setAlphaF(0.28)
        p.fillRect(self.rect(), c)
        p.end()

    @staticmethod
    def ask(parent, title, text, confirm_text, danger=True) -> bool:
        return ConfirmDialog(parent, title, text, confirm_text, danger=danger).exec() == QDialog.Accepted
