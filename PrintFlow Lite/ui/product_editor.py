"""
Produkto forma
--------------
Produkto kūrimas / redagavimas (Produktai ➔ sąrašas + forma):
1. Pavadinimas ir raktažodžiai (pagal juos atpažįstami serverio failai) + atpažinimo testas
2. Kurias plokštes generuoti (CMYK / White / Primer)
3. Kiekvienos plokštės Hotfolderis ir Thinning / Thickening (px)
4. Kėlimo eiliškumas (rodyklės) ir pauzė tarp sluoksnių
"""

import os
import re
import copy
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QFileDialog, QVBoxLayout, QWidget
)

from core.scanner_lite import match_product
from ui.widgets import Badge, Switch, button, field, label, section, divider, icon_button

PLATE_TYPES = ["Primer", "White", "CMYK"]

PLATE_INFO = {
    "CMYK": ("CMYK", "Spalvota plokštė", "Originalus dizainas be pakeitimų"),
    "White": ("White", "Balta plokštė", "Balto rašalo kaukė po spalva"),
    "Primer": ("Primer", "Grunto plokštė", "Grunto kaukė sukibimui su paviršiumi"),
}

DEFAULT_HOTFOLDERS = {
    "CMYK": r"C:\MijCtrl\Hot\RH COLOR",
    "White": r"C:\MijCtrl\Hot\RH WHITE",
    "Primer": r"C:\MijCtrl\Hot\RH PRIMER",
}


def slugify(name: str) -> str:
    repl = str.maketrans("ąčęėįšųūžĄČĘĖĮŠŲŪŽ", "aceeisuuzACEEISUUZ")
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").translate(repl).lower()).strip("_")
    return s or "produktas"


def unique_product_id(name: str, existing_ids: List[str]) -> str:
    base = slugify(name)
    pid, n = base, 2
    while pid in existing_ids:
        pid = f"{base}_{n}"
        n += 1
    return pid


def normalize_product(p: Dict) -> Dict:
    """Užtikrina, kad produktas turi visus laukus (seni config.json failai)."""
    p = copy.deepcopy(p)
    layers = [l for l in (p.get("layers") or []) if l in PLATE_TYPES]
    order = [l for l in (p.get("dispatch_order") or []) if l in PLATE_TYPES]
    for l in layers:
        if l not in order:
            order.append(l)
    p["layers"] = layers
    p["dispatch_order"] = [l for l in order if l in layers] or list(layers)
    hf = p.get("hotfolders") or {}
    p["hotfolders"] = {l: (hf.get(l) or "") for l in PLATE_TYPES}
    kws = p.get("keywords", [])
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",") if k.strip()]
    p["keywords"] = list(kws or [])
    p.setdefault("choke_white_px", 1)
    p.setdefault("choke_primer_px", 0)
    return p


def describe_plates(p: Dict) -> str:
    """'Primer → White → CMYK' – tik generuojamos plokštės, kėlimo tvarka."""
    return " → ".join(normalize_product(p)["dispatch_order"]) or "—"


class PlateRow(QFrame):
    """Viena plokštės eilutė: nr. | jungiklis + pavadinimas | thinning | hotfolderis | naršyti | ↑ ↓"""

    def __init__(self, layer: str, form: "ProductForm"):
        super().__init__()
        self.layer = layer
        self.form = form
        self.setObjectName("plateRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)

        self.lbl_pos = QLabel("1")
        self.lbl_pos.setObjectName("platePos")
        self.lbl_pos.setFixedWidth(18)
        lay.addWidget(self.lbl_pos)

        short, title, hint = PLATE_INFO[layer]
        self.switch = Switch(short)
        self.switch.setToolTip(f"{title}: {hint}")
        self.switch.setFixedWidth(110)
        self.switch.toggled.connect(self._on_toggled)
        lay.addWidget(self.switch)

        self.spn_choke = QSpinBox()
        self.spn_choke.setRange(-10, 20)
        self.spn_choke.setSuffix(" px")
        self.spn_choke.setFixedWidth(84)
        self.spn_choke.setToolTip("Teigiamas – thinning (sutraukti kaukę)\nNeigiamas – thickening (išpūsti kaukę)")
        self.spn_choke.valueChanged.connect(self.form.on_changed)
        if layer == "CMYK":
            self.spn_choke.setRange(0, 0)
            self.spn_choke.setSpecialValueText("—")
            self.spn_choke.setToolTip("CMYK – originalus failas, thinning netaikomas")
        lay.addWidget(self.spn_choke)

        self.txt_hot = QLineEdit()
        self.txt_hot.setPlaceholderText("HotFolderio kelias")
        self.txt_hot.textChanged.connect(self.form.on_changed)
        lay.addWidget(self.txt_hot, 1)

        self.btn_browse = button("Naršyti…", icon="folder", on_click=self._browse)
        lay.addWidget(self.btn_browse)
        self.btn_up = icon_button("up", "Kelti anksčiau", lambda: self.form.move_row(self, -1))
        self.btn_down = icon_button("down", "Kelti vėliau", lambda: self.form.move_row(self, +1))
        lay.addWidget(self.btn_up)
        lay.addWidget(self.btn_down)

    def _browse(self):
        start = self.txt_hot.text().strip() or r"C:\MijCtrl\Hot"
        folder = QFileDialog.getExistingDirectory(self, f"HotFolderis – {PLATE_INFO[self.layer][1]}", start)
        if folder:
            self.txt_hot.setText(os.path.normpath(folder))

    def _on_toggled(self, on: bool):
        self.spn_choke.setEnabled(on and self.layer != "CMYK")
        self.txt_hot.setEnabled(on)
        self.btn_browse.setEnabled(on)
        if on and not self.txt_hot.text().strip() and not self.form.loading:
            self.txt_hot.setText(DEFAULT_HOTFOLDERS[self.layer])
        self.setProperty("off", not on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.form.on_changed()


class ProductForm(QWidget):
    """Produkto forma (be išsaugojimo mygtukų – juos valdo puslapis)."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.loading = False
        self.all_products: List[Dict] = []
        self.original: Optional[Dict] = None
        self.default_delay = 0.5

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("pvz. MagSafe Ring Holders")
        self.txt_name.textChanged.connect(self.on_changed)
        grid.addWidget(field("Produkto pavadinimas", self.txt_name), 0, 0, Qt.AlignTop)

        self.txt_kw = QLineEdit()
        self.txt_kw.setPlaceholderText("pvz. magsafe-ring-holders, ring-holder, RH")
        self.txt_kw.textChanged.connect(self.on_changed)
        grid.addWidget(field("Raktažodžiai", self.txt_kw,
                             "Atskirkite kableliais. Ieškoma serverio aplankų ir failų pavadinimuose. "
                             "1–2 raidžių akronimai turi būti atskiras žodis (RH_123.pdf)."), 0, 1)

        self.txt_test = QLineEdit()
        self.txt_test.setPlaceholderText("Įveskite failo kelią, pvz. 2026-10-09\\105\\ring-holder\\uzsakymas.pdf")
        self.txt_test.textChanged.connect(lambda _: self.refresh())  # testas nėra produkto pakeitimas
        self.badge_test = Badge("Įveskite kelią", "neutral")
        test_wrap = QWidget()
        test_row = QHBoxLayout(test_wrap)
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.setSpacing(12)
        test_row.addWidget(self.txt_test, 1)
        test_row.addWidget(self.badge_test)
        grid.addWidget(field("Atpažinimo testas", test_wrap,
                             "Patikrina, kuriam produktui būtų priskirtas toks failas."), 1, 0, 1, 2)
        self.sw_batch_sheet = Switch("Rodyti batch sheet")
        self.sw_batch_sheet.toggled.connect(self.on_changed)
        grid.addWidget(field("Sudėjimo lapas", self.sw_batch_sheet,
                             "Šalia užsakymo PDF ieškoma „…_batch_sheet_1.png“ lapų su modeliais. Jie rodomi "
                             "skirtuke „Stebėjimas“ kortelėje „Sudėti į stalą“."), 2, 0)
        self.spn_fit = QDoubleSpinBox()
        self.spn_fit.setRange(0.0, 500.0)
        self.spn_fit.setDecimals(1)
        self.spn_fit.setSingleStep(0.5)
        self.spn_fit.setSuffix(" mm")
        self.spn_fit.setSpecialValueText("Išjungta")
        self.spn_fit.setFixedWidth(140)
        self.spn_fit.valueChanged.connect(self.on_changed)
        grid.addWidget(field("Objekto dydis", self.spn_fit,
                             "Teisingas objekto (pvz. žiedo) skersmuo. Jei faile objektas mažesnis "
                             "(85–99 %), jis automatiškai padidinamas iki šio dydžio. 0 – išjungta."), 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        root.addWidget(divider())
        root.addWidget(section("Plokštės ir kėlimo tvarka"))
        root.addWidget(label("Įjunkite plokštes, kurias reikia generuoti. Eilučių tvarka – tai tvarka, "
                             "kuria plokštės keliamos į RasterLink HotFolderius.", "secondary", wrap=True))

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(8)
        root.addLayout(self.rows_box)
        self.rows: Dict[str, PlateRow] = {l: PlateRow(l, self) for l in PLATE_TYPES}
        for l in PLATE_TYPES:
            self.rows_box.addWidget(self.rows[l])

        self.spn_delay = QDoubleSpinBox()
        self.spn_delay.setRange(0.0, 10.0)
        self.spn_delay.setSingleStep(0.1)
        self.spn_delay.setSuffix(" s")
        self.spn_delay.setFixedWidth(120)
        self.spn_delay.valueChanged.connect(self.on_changed)
        self.lbl_summary = label("", "", wrap=True)
        self.lbl_summary.setMinimumHeight(40)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(field("Pauzė tarp plokščių", self.spn_delay))
        bottom.addWidget(field("Kėlimo seka", self.lbl_summary), 1)
        root.addLayout(bottom)

        self.lbl_errors = label("", "error", wrap=True)
        root.addWidget(self.lbl_errors)
        root.addStretch(1)

    # -----------------------------------------------------------------
    def load(self, product: Optional[Dict], all_products: List[Dict], default_delay: float = 0.5,
             template: Optional[Dict] = None):
        """product=None ➔ naujas produktas (template – pradinės reikšmės)."""
        self.loading = True
        self.all_products = all_products
        self.default_delay = default_delay
        self.original = normalize_product(product) if product else None
        if self.original is None and template is not None:
            src = normalize_product(template)
            src.pop("id", None)
        else:
            src = self.original or normalize_product({
                "name": "", "keywords": [], "layers": ["Primer", "White", "CMYK"],
                "dispatch_order": ["Primer", "White", "CMYK"], "choke_white_px": 1, "choke_primer_px": 0,
                "hotfolders": dict(DEFAULT_HOTFOLDERS), "inter_layer_delay_sec": default_delay,
            })
        self.txt_name.setText(src.get("name", ""))
        self.txt_kw.setText(", ".join(src.get("keywords", [])))
        self.sw_batch_sheet.setChecked(bool(src.get("batch_sheet", False)))
        try:
            self.spn_fit.setValue(float(src.get("fit_size_mm") or 0))
        except (TypeError, ValueError):
            self.spn_fit.setValue(0)
        self.txt_test.clear()
        order = list(src["dispatch_order"]) + [l for l in PLATE_TYPES if l not in src["dispatch_order"]]
        for l in order:
            row = self.rows[l]
            self.rows_box.removeWidget(row)
            self.rows_box.addWidget(row)
            row.txt_hot.setText(src["hotfolders"].get(l, ""))
            if l == "White":
                row.spn_choke.setValue(int(src.get("choke_white_px", 1)))
            elif l == "Primer":
                row.spn_choke.setValue(int(src.get("choke_primer_px", 0)))
            row.switch.setChecked(l in src["layers"])
            row._on_toggled(l in src["layers"])
        try:
            self.spn_delay.setValue(float(src.get("inter_layer_delay_sec", default_delay)))
        except (TypeError, ValueError):
            self.spn_delay.setValue(default_delay)
        self.loading = False
        self.refresh()

    def ordered_rows(self) -> List[PlateRow]:
        return [self.rows_box.itemAt(i).widget() for i in range(self.rows_box.count())]

    def move_row(self, row: PlateRow, delta: int):
        rows = self.ordered_rows()
        j = rows.index(row) + delta
        if 0 <= j < len(rows):
            self.rows_box.removeWidget(row)
            self.rows_box.insertWidget(j, row)
            self.on_changed()

    def on_changed(self, *_):
        if self.loading:
            return
        self.refresh()
        self.changed.emit()

    # -----------------------------------------------------------------
    def build_product(self) -> Dict:
        enabled = [r.layer for r in self.ordered_rows() if r.switch.isChecked()]
        name = self.txt_name.text().strip()
        p = copy.deepcopy(self.original) if self.original else {}
        existing_ids = [o.get("id", "") for o in self.all_products]
        p.update({
            "id": (self.original or {}).get("id") or unique_product_id(name, existing_ids),
            "name": name,
            "keywords": [k.strip() for k in self.txt_kw.text().split(",") if k.strip()],
            "layers": [l for l in PLATE_TYPES if l in enabled],
            "dispatch_order": enabled,
            "choke_white_px": self.rows["White"].spn_choke.value(),
            "choke_primer_px": self.rows["Primer"].spn_choke.value(),
            "hotfolders": {l: (self.rows[l].txt_hot.text().strip() if l in enabled else "") for l in PLATE_TYPES},
            "inter_layer_delay_sec": round(self.spn_delay.value(), 2),
            "batch_sheet": self.sw_batch_sheet.isChecked(),
            "fit_size_mm": round(self.spn_fit.value(), 1),
        })
        p.pop("matched_keyword", None)
        return p

    def validate(self, p: Optional[Dict] = None) -> Tuple[List[str], List[str]]:
        p = p or self.build_product()
        errors, warnings = [], []
        others = [o for o in self.all_products if o.get("id") != p["id"]]
        if not p["name"]:
            errors.append("Įveskite produkto pavadinimą.")
        elif any(o.get("name", "").strip().lower() == p["name"].lower() for o in others):
            errors.append(f"Produktas „{p['name']}“ jau yra.")
        if not p["keywords"]:
            errors.append("Įveskite bent vieną raktažodį – kitaip failai nebus atpažinti.")
        if not p["layers"]:
            errors.append("Įjunkite bent vieną plokštę.")
        for l in p["dispatch_order"]:
            hf = p["hotfolders"].get(l, "")
            if not hf:
                errors.append(f"{PLATE_INFO[l][1]}: nenurodytas HotFolderis.")
            elif os.name == "nt" and not os.path.isdir(hf):
                warnings.append(f"{PLATE_INFO[l][1]}: aplankas „{hf}“ šiuo metu nerastas.")
        own = {k.lower() for k in p["keywords"]}
        for o in others:
            same = own & {k.lower() for k in normalize_product(o)["keywords"]}
            if same:
                warnings.append(f"Raktažodis {', '.join(sorted(same))} jau naudojamas produkte „{o.get('name')}“.")
        return errors, warnings

    def refresh(self):
        rows = self.ordered_rows()
        pos = 0
        for i, r in enumerate(rows):
            on = r.switch.isChecked()
            pos += 1 if on else 0
            r.lbl_pos.setText(str(pos) if on else "–")
            r.btn_up.setEnabled(i > 0)
            r.btn_down.setEnabled(i < len(rows) - 1)

        p = self.build_product()
        if p["dispatch_order"]:
            self.lbl_summary.setText("   →   ".join(f"{i}. {l}" for i, l in enumerate(p["dispatch_order"], 1)))
        else:
            self.lbl_summary.setText("Neįjungta nė viena plokštė")

        test = self.txt_test.text().strip()
        if not test:
            self.badge_test.set("Įveskite kelią", "neutral")
        else:
            others = [o for o in self.all_products if o.get("id") != p["id"]]
            hit = match_product(os.path.basename(test.replace("\\", "/")), test, others + [p])
            if hit is None:
                self.badge_test.set("Neatpažinta", "error")
            elif hit.get("id") == p["id"]:
                self.badge_test.set(f"Šis produktas · „{hit['matched_keyword']}“", "success")
            else:
                self.badge_test.set(f"Priskirta: {hit.get('name')}", "warning")

        errors, _ = self.validate(p)
        self.lbl_errors.setText("\n".join(errors))
        self.lbl_errors.setVisible(bool(errors))

    def is_valid(self) -> bool:
        return not self.validate()[0]
