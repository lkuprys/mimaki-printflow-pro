"""
Produkto redaktorius
--------------------
Paprastas dialogas produktui sukurti / redaguoti:
1. Pavadinimas ir raktažodžiai (pagal juos atpažįstami serverio failai)
2. Kurias plokštes generuoti (CMYK / White / Primer)
3. Kiekvienos plokštės Hotfolderis ir Thinning / Thickening (px)
4. Kėlimo eiliškumas (▲ ▼) ir pauzė tarp sluoksnių
"""

import os
import re
import copy
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QSpinBox, QDoubleSpinBox, QGroupBox, QFileDialog, QMessageBox,
    QDialogButtonBox, QFrame, QWidget, QStyle
)

from core.scanner_lite import match_product

PLATE_TYPES = ["Primer", "White", "CMYK"]

PLATE_INFO = {
    "CMYK": ("🎨", "Spalvota (CMYK)", "Originalus dizainas be pakeitimų"),
    "White": ("⬜", "Balta (White)", "Balto rašalo kaukė po spalva"),
    "Primer": ("🧪", "Gruntas (Primer)", "Grunto kaukė (sukibimui su paviršiumi)"),
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


def unique_product_id(name: str, existing_ids: List[str], keep: str = "") -> str:
    base = slugify(name)
    if keep and keep.startswith(base):
        return keep
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
    p.setdefault("keywords", [])
    if isinstance(p["keywords"], str):
        p["keywords"] = [k.strip() for k in p["keywords"].split(",") if k.strip()]
    p.setdefault("choke_white_px", 1)
    p.setdefault("choke_primer_px", 0)
    return p


def describe_plates(p: Dict) -> str:
    """'Primer ➔ White ➔ CMYK' – tik generuojamos plokštės, kėlimo tvarka."""
    p = normalize_product(p)
    return " ➔ ".join(p["dispatch_order"]) or "—"


class _PlateRow(QFrame):
    """Viena plokštės eilutė: [✓] pavadinimas | choke | hotfolderis 📂 | ▲ ▼"""

    def __init__(self, layer: str, parent_dialog):
        super().__init__()
        self.layer = layer
        self.dlg = parent_dialog
        self.setObjectName("plateRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        self.lbl_pos = QLabel("1.")
        self.lbl_pos.setFixedWidth(22)
        self.lbl_pos.setObjectName("platePos")
        lay.addWidget(self.lbl_pos)

        icon, title, hint = PLATE_INFO[layer]
        self.chk = QCheckBox(f"{icon}  {title}")
        self.chk.setToolTip(hint)
        self.chk.setMinimumWidth(170)
        self.chk.toggled.connect(self._on_toggled)
        lay.addWidget(self.chk)

        self.spn_choke = QSpinBox()
        self.spn_choke.setRange(-10, 20)
        self.spn_choke.setSuffix(" px")
        self.spn_choke.setFixedWidth(84)
        self.spn_choke.setToolTip("Teigiamas = Thinning (sutraukti kaukę)\nNeigiamas = Thickening (išpūsti kaukę)")
        if layer == "CMYK":
            self.spn_choke.setEnabled(False)
            self.spn_choke.setSpecialValueText("—")
            self.spn_choke.setMinimum(0)
            self.spn_choke.setValue(0)
            self.spn_choke.setToolTip("CMYK plokštė – originalus failas, thinning netaikomas")
        lay.addWidget(self.spn_choke)

        self.txt_hot = QLineEdit()
        self.txt_hot.setPlaceholderText("Hotfolderio kelias, pvz. C:\\MijCtrl\\Hot\\...")
        self.txt_hot.textChanged.connect(self.dlg.refresh_state)
        lay.addWidget(self.txt_hot, 1)

        self.btn_browse = QPushButton("📂")
        self.btn_browse.setToolTip("Pasirinkti Hotfolderį")
        self.btn_browse.setFixedWidth(40)
        self.btn_browse.clicked.connect(self._browse)
        lay.addWidget(self.btn_browse)

        self.btn_up = QPushButton()
        self.btn_up.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self.btn_up.setToolTip("Kelti anksčiau")
        self.btn_up.setFixedWidth(34)
        self.btn_up.clicked.connect(lambda: self.dlg.move_row(self, -1))
        lay.addWidget(self.btn_up)
        self.btn_down = QPushButton()
        self.btn_down.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.btn_down.setToolTip("Kelti vėliau")
        self.btn_down.setFixedWidth(34)
        self.btn_down.clicked.connect(lambda: self.dlg.move_row(self, +1))
        lay.addWidget(self.btn_down)

    def _browse(self):
        start = self.txt_hot.text().strip() or r"C:\MijCtrl\Hot"
        folder = QFileDialog.getExistingDirectory(self, f"Hotfolderis: {self.layer}", start)
        if folder:
            self.txt_hot.setText(os.path.normpath(folder))

    def _on_toggled(self, on: bool):
        for w in (self.spn_choke, self.txt_hot, self.btn_browse):
            w.setEnabled(on and not (w is self.spn_choke and self.layer == "CMYK"))
        if on and not self.txt_hot.text().strip():
            self.txt_hot.setText(DEFAULT_HOTFOLDERS[self.layer])
        self.dlg.refresh_state()


class ProductEditorDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], product: Optional[Dict], all_products: List[Dict],
                 default_delay: float = 0.5, template: Optional[Dict] = None):
        super().__init__(parent)
        self.is_new = product is None
        self.all_products = all_products
        self.original = normalize_product(product) if product else None
        self.result_product: Optional[Dict] = None

        self.setWindowTitle("Naujas produktas" if self.is_new else f"Redaguoti: {product.get('name', '')}")
        self.setMinimumWidth(860)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        # --- 1. Pagrindinė informacija ---------------------------------
        grp_info = QGroupBox("1. Produktas ir atpažinimas")
        g = QGridLayout(grp_info)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        g.addWidget(QLabel("Pavadinimas:"), 0, 0)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("pvz. MagSafe Ring Holders")
        self.txt_name.textChanged.connect(self.refresh_state)
        g.addWidget(self.txt_name, 0, 1)

        g.addWidget(QLabel("Raktažodžiai:"), 1, 0)
        self.txt_kw = QLineEdit()
        self.txt_kw.setPlaceholderText("pvz. magsafe-ring-holders, ring-holder, RH")
        self.txt_kw.setToolTip("Atskirkite kableliais. Failas priskiriamas produktui, jei raktažodis yra\n"
                               "serverio aplanko ar failo pavadinime. Trumpi (1–2 raidžių) akronimai\n"
                               "turi būti atskiras žodis (pvz. RH_123.pdf).")
        self.txt_kw.textChanged.connect(self.refresh_state)
        g.addWidget(self.txt_kw, 1, 1)

        g.addWidget(QLabel("Atpažinimo testas:"), 2, 0)
        test_row = QHBoxLayout()
        self.txt_test = QLineEdit()
        self.txt_test.setPlaceholderText("Įveskite failo kelią ar pavadinimą, pvz. 2026-10-09\\105\\ring-holder\\order.pdf")
        self.txt_test.textChanged.connect(self.refresh_state)
        test_row.addWidget(self.txt_test, 1)
        self.lbl_test = QLabel("")
        self.lbl_test.setMinimumWidth(260)
        test_row.addWidget(self.lbl_test)
        g.addLayout(test_row, 2, 1)
        root.addWidget(grp_info)

        # --- 2. Plokštės -------------------------------------------------
        grp_plates = QGroupBox("2. Generuojamos plokštės, Hotfolderiai ir kėlimo eiliškumas")
        pv = QVBoxLayout(grp_plates)
        hint = QLabel("Pažymėkite, kurias plokštes generuoti. Eilučių tvarka = kėlimo į RasterLink tvarka "
                      "(rodyklės ↑ ↓ keičia eiliškumą).")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        pv.addWidget(hint)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(10, 0, 10, 0)
        for text, width in (("#", 22), ("Plokštė", 170), ("Thinning", 84), ("Hotfolderis", 0)):
            l = QLabel(text)
            l.setObjectName("colHeader")
            if width:
                l.setFixedWidth(width)
                hdr.addWidget(l)
            else:
                hdr.addWidget(l, 1)
        hdr.addSpacing(40 + 34 + 34 + 20)
        pv.addLayout(hdr)

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        pv.addLayout(self.rows_box)
        self.rows: Dict[str, _PlateRow] = {l: _PlateRow(l, self) for l in PLATE_TYPES}

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Pauzė tarp sluoksnių kėlimo:"))
        self.spn_delay = QDoubleSpinBox()
        self.spn_delay.setRange(0.0, 10.0)
        self.spn_delay.setSingleStep(0.1)
        self.spn_delay.setSuffix(" s")
        self.spn_delay.setFixedWidth(90)
        self.spn_delay.setToolTip("Laikas, per kurį RasterLink spėja užregistruoti ankstesnį sluoksnį")
        delay_row.addWidget(self.spn_delay)
        delay_row.addStretch()
        pv.addLayout(delay_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("summary")
        self.lbl_summary.setWordWrap(True)
        pv.addWidget(self.lbl_summary)
        root.addWidget(grp_plates)

        # --- Mygtukai ----------------------------------------------------
        self.lbl_errors = QLabel("")
        self.lbl_errors.setObjectName("errors")
        self.lbl_errors.setWordWrap(True)
        root.addWidget(self.lbl_errors)

        buttons = QDialogButtonBox()
        self.btn_save = buttons.addButton("💾 Išsaugoti produktą", QDialogButtonBox.AcceptRole)
        self.btn_save.setObjectName("btnSuccess")
        btn_cancel = buttons.addButton("Atšaukti", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        btn_cancel.setAutoDefault(False)
        root.addWidget(buttons)

        if template is not None:
            tpl = normalize_product(template)
            tpl.pop("id", None)
            self._load(tpl, default_delay)
        else:
            self._load(self.original, default_delay)

    # -----------------------------------------------------------------
    def _load(self, p: Optional[Dict], default_delay: float):
        if p is None:
            p = normalize_product({
                "name": "", "keywords": [], "layers": ["Primer", "White", "CMYK"],
                "dispatch_order": ["Primer", "White", "CMYK"], "choke_white_px": 1, "choke_primer_px": 0,
                "hotfolders": dict(DEFAULT_HOTFOLDERS), "inter_layer_delay_sec": default_delay,
            })
        self.txt_name.setText(p.get("name", ""))
        self.txt_kw.setText(", ".join(p.get("keywords", [])))
        order = list(p["dispatch_order"]) + [l for l in PLATE_TYPES if l not in p["dispatch_order"]]
        for l in order:
            row = self.rows[l]
            row.txt_hot.setText(p["hotfolders"].get(l, ""))
            if l == "White":
                row.spn_choke.setValue(int(p.get("choke_white_px", 1)))
            elif l == "Primer":
                row.spn_choke.setValue(int(p.get("choke_primer_px", 0)))
            row.chk.setChecked(l in p["layers"])
            row._on_toggled(l in p["layers"])
            self.rows_box.addWidget(row)
        try:
            self.spn_delay.setValue(float(p.get("inter_layer_delay_sec", default_delay)))
        except (TypeError, ValueError):
            self.spn_delay.setValue(default_delay)
        self.refresh_state()

    def ordered_rows(self) -> List[_PlateRow]:
        return [self.rows_box.itemAt(i).widget() for i in range(self.rows_box.count())]

    def move_row(self, row: _PlateRow, delta: int):
        rows = self.ordered_rows()
        i = rows.index(row)
        j = i + delta
        if 0 <= j < len(rows):
            self.rows_box.removeWidget(row)
            self.rows_box.insertWidget(j, row)
            self.refresh_state()

    # -----------------------------------------------------------------
    def build_product(self) -> Dict:
        rows = self.ordered_rows()
        enabled = [r.layer for r in rows if r.chk.isChecked()]
        existing_ids = [p.get("id", "") for p in self.all_products
                        if not self.original or p.get("id") != self.original.get("id")]
        name = self.txt_name.text().strip()
        p = copy.deepcopy(self.original) if self.original else {}
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
        })
        p.pop("matched_keyword", None)
        return p

    def validate(self, p: Dict) -> (List[str], List[str]):
        errors, warnings = [], []
        if not p["name"]:
            errors.append("Įveskite produkto pavadinimą.")
        elif any(o.get("name", "").strip().lower() == p["name"].lower() and o.get("id") != p["id"]
                 for o in self.all_products):
            errors.append(f"Produktas '{p['name']}' jau egzistuoja.")
        if not p["keywords"]:
            errors.append("Įveskite bent vieną raktažodį – kitaip failai nebus atpažinti.")
        if not p["layers"]:
            errors.append("Pažymėkite bent vieną plokštę.")
        for l in p["dispatch_order"]:
            hf = p["hotfolders"].get(l, "")
            if not hf:
                errors.append(f"{PLATE_INFO[l][1]}: nenurodytas Hotfolderis.")
            elif os.name == "nt" and not os.path.isdir(hf):
                warnings.append(f"{PLATE_INFO[l][1]}: aplankas '{hf}' šiuo metu neegzistuoja.")
        # Raktažodžių konfliktai su kitais produktais
        own = {k.lower() for k in p["keywords"]}
        for o in self.all_products:
            if o.get("id") == p["id"]:
                continue
            same = own & {k.lower() for k in (o.get("keywords") or [])}
            if same:
                warnings.append(f"Raktažodis {', '.join(sorted(same))} jau naudojamas produkte '{o.get('name')}'.")
        return errors, warnings

    def refresh_state(self, *_):
        if not hasattr(self, "lbl_summary"):
            return
        rows = self.ordered_rows()
        if len(rows) != len(PLATE_TYPES):
            return
        pos = 0
        for i, r in enumerate(rows):
            on = r.chk.isChecked()
            pos += 1 if on else 0
            r.lbl_pos.setText(f"{pos}." if on else "–")
            r.btn_up.setEnabled(i > 0)
            r.btn_down.setEnabled(i < len(rows) - 1)
            r.setProperty("disabled", not on)
            r.style().unpolish(r)
            r.style().polish(r)

        p = self.build_product()
        if p["dispatch_order"]:
            steps = [f"<b>{PLATE_INFO[l][1]}</b> ➔ <i>{p['hotfolders'].get(l) or '?'}</i>" for l in p["dispatch_order"]]
            self.lbl_summary.setText("Kėlimo seka:<br>" + "<br>".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))
        else:
            self.lbl_summary.setText("Nepažymėta nė viena plokštė.")

        # Atpažinimo testas – su visais kitais produktais, kad matytųsi konfliktai
        test = self.txt_test.text().strip()
        if test:
            others = [o for o in self.all_products if o.get("id") != p["id"]]
            hit = match_product(os.path.basename(test), test, others + [p])
            if hit is None:
                self.lbl_test.setText("❌ Neatpažinta")
            elif hit.get("id") == p["id"]:
                self.lbl_test.setText(f"✅ Šis produktas (pagal '{hit['matched_keyword']}')")
            else:
                self.lbl_test.setText(f"⚠️ Priskirta kitam: {hit.get('name')}")
        else:
            self.lbl_test.setText("")

        errors, _ = self.validate(p)
        self.btn_save.setEnabled(not errors)
        self.lbl_errors.setText("\n".join(f"• {e}" for e in errors))

    def _on_save(self):
        p = self.build_product()
        errors, warnings = self.validate(p)
        if errors:
            QMessageBox.warning(self, "Trūksta duomenų", "\n".join(errors))
            return
        if warnings:
            r = QMessageBox.question(self, "Patvirtinkite",
                                     "\n".join(warnings) + "\n\nVis tiek išsaugoti?",
                                     QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self.result_product = p
        self.accept()
