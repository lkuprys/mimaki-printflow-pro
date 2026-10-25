"""
Objektų dydžio taisymas (pvz. MagSafe Ring Holder)
-------------------------------------------------
Kartais serveris atsiunčia teisingo dydžio lapą, bet objektas (žiedas) jame per mažas –
pvz. 57,2 mm vietoj 60,5 mm. Modulis randa kiekvieną objektą pagal permatomumą (SMask),
išmatuoja jo skersmenį ir per mažą objektą proporcingai padidina iki tikslinio dydžio
apie tą patį centrą. Lapo geometrija ir paveikslėlio raiška nesikeičia, todėl CMYK,
White ir Primer plokštės, sugeneruotos iš pataisyto failo, sutampa 1:1.

Palaikoma Podbase struktūra: vienas RGB paveikslėlis su SMask per visą puslapį.
Kitokios struktūros failai nekeičiami (grąžinama priežastis).
"""

import io
import os
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
import pymupdf

DOWNSAMPLE = 8          # objektų paieška sumažintame tinklelyje (greitis)
ALPHA_ON = 128          # nuo kokio permatomumo pikselis laikomas objekto dalimi
MIN_OBJECT_MM = 5.0     # smulkesni dalykai (dulkės, žymės) ignoruojami
ROUND_TOLERANCE = 0.03  # pločio/aukščio skirtumas, kad objektas būtų laikomas apvaliu/kvadratiniu
GAP_MM = 1.0            # padidintas objektas negali priartėti prie kaimyno arčiau nei tiek


def _page_image(doc, page) -> Tuple[Optional[int], Optional[int], str]:
    """Grąžina (paveikslėlio xref, smask xref, klaida) – tik jei vienas paveikslėlis dengia visą lapą."""
    if page.rotation % 360:
        return None, None, "puslapis pasuktas"
    infos = page.get_image_info(xrefs=True)
    if len(infos) != 1 or not infos[0].get("xref"):
        return None, None, "lape ne vienas paveikslėlis"
    info = infos[0]
    a, b, c, d, _e, _f = info.get("transform", (0, 0, 0, 0, 0, 0))
    if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
        return None, None, "paveikslėlis pasuktas arba apverstas"
    bbox, pr = pymupdf.Rect(info["bbox"]), page.rect
    if max(abs(bbox.x0 - pr.x0), abs(bbox.y0 - pr.y0), abs(bbox.x1 - pr.x1), abs(bbox.y1 - pr.y1)) > 0.5:
        return None, None, "paveikslėlis nedengia viso lapo"
    xref = info["xref"]
    smask = next((img[1] for img in page.get_images(full=True) if img[0] == xref), 0)
    if not smask:
        return None, None, "paveikslėlis be permatomumo (SMask)"
    return xref, smask, ""


def _components(mask: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Sujungtų sričių ribos (y0, y1, x0, x1) sumažintame tinklelyje (8 kaimynai)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        seen[y, x] = True
        q = deque([(y, x)])
        y0 = y1 = y
        x0 = x1 = x
        while q:
            cy, cx = q.popleft()
            y0, y1, x0, x1 = min(y0, cy), max(y1, cy), min(x0, cx), max(x1, cx)
            for ny in (cy - 1, cy, cy + 1):
                if 0 <= ny < h:
                    for nx in (cx - 1, cx, cx + 1):
                        if 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
        out.append((y0, y1 + 1, x0, x1 + 1))
    return out


def _load_rgba(doc, xref: int, smask: int) -> Optional[np.ndarray]:
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.colorspace is None or pix.colorspace.n != 3:
        return None
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * 3]
    sm = Image.open(io.BytesIO(doc.extract_image(smask)["image"]))
    sm = sm.convert("L")
    if sm.size != (pix.width, pix.height):
        sm = sm.resize((pix.width, pix.height), Image.Resampling.BILINEAR)
    rgba = np.empty((pix.height, pix.width, 4), dtype=np.uint8)
    rgba[..., :3] = rgb.reshape(pix.height, pix.width, 3)
    rgba[..., 3] = np.asarray(sm)
    return rgba


def _write_stream(doc, xref: int, raw: bytes, w: int, h: int):
    """Įrašo nesuspaustus 8 bitų pikselius į esamą paveikslėlio objektą (Flate), panaikinant seną kodavimą."""
    for key in ("DecodeParms", "Decode", "DL"):
        if doc.xref_get_key(xref, key)[0] != "null":
            doc.xref_set_key(xref, key, "null")
    doc.xref_set_key(xref, "Width", str(w))
    doc.xref_set_key(xref, "Height", str(h))
    doc.xref_set_key(xref, "BitsPerComponent", "8")
    doc.update_stream(xref, raw, compress=True)


def fix_object_sizes(src_pdf: str, out_pdf: str, target_mm: float,
                     min_ratio: float = 0.85, tolerance: float = 0.01) -> Dict:
    """
    Per mažus objektus (skersmuo tarp target*min_ratio ir target*(1-tolerance)) padidina iki target_mm.
    Grąžina {"changed": bool, "fixed": [(prieš_mm, po_mm)], "notes": [str], "error": str}.
    out_pdf įrašomas tik jei kas nors pakeista.
    """
    res = {"changed": False, "fixed": [], "notes": [], "error": ""}
    doc = pymupdf.open(src_pdf)
    try:
        page = doc[0]
        xref, smask, err = _page_image(doc, page)
        if err:
            res["error"] = err
            return res
        rgba = _load_rgba(doc, xref, smask)
        if rgba is None:
            res["error"] = "paveikslėlis ne RGB"
            return res
        h, w = rgba.shape[:2]
        px_per_mm = w / (page.rect.width / 72.0 * 25.4)
        alpha = rgba[..., 3]

        small = alpha[::DOWNSAMPLE, ::DOWNSAMPLE] >= ALPHA_ON
        boxes = []
        for y0, y1, x0, x1 in _components(small):
            # Tikslios ribos pilnoje raiškoje
            Y0, Y1 = max(0, (y0 - 1) * DOWNSAMPLE), min(h, (y1 + 1) * DOWNSAMPLE)
            X0, X1 = max(0, (x0 - 1) * DOWNSAMPLE), min(w, (x1 + 1) * DOWNSAMPLE)
            ys, xs = np.nonzero(alpha[Y0:Y1, X0:X1] >= ALPHA_ON)
            if not len(ys):
                continue
            boxes.append((Y0 + ys.min(), Y0 + ys.max() + 1, X0 + xs.min(), X0 + xs.max() + 1))

        gap = int(round(GAP_MM * px_per_mm))
        for i, (y0, y1, x0, x1) in enumerate(boxes):
            bw, bh = x1 - x0, y1 - y0
            size_mm = max(bw, bh) / px_per_mm
            if size_mm < MIN_OBJECT_MM:
                continue
            if abs(bw - bh) > ROUND_TOLERANCE * max(bw, bh):
                res["notes"].append(f"objektas {bw / px_per_mm:.1f}×{bh / px_per_mm:.1f} mm nėra apvalus – nekeičiamas")
                continue
            if size_mm >= target_mm * (1 - tolerance):
                continue
            if size_mm < target_mm * min_ratio:
                res["notes"].append(f"objektas {size_mm:.1f} mm per mažas automatiniam taisymui "
                                    f"(< {min_ratio:.0%} nuo {target_mm:g} mm) – nekeičiamas")
                continue
            f = target_mm / size_mm
            nw, nh = int(round(bw * f)), int(round(bh * f))
            cy, cx = (y0 + y1) / 2.0, (x0 + x1) / 2.0
            ny0, nx0 = int(round(cy - nh / 2.0)), int(round(cx - nw / 2.0))
            ny1, nx1 = ny0 + nh, nx0 + nw
            if ny0 < 0 or nx0 < 0 or ny1 > h or nx1 > w:
                res["notes"].append(f"objektas {size_mm:.1f} mm prie lapo krašto – padidintas netilptų")
                continue
            if any(not (nx1 + gap <= ox0 or ox1 + gap <= nx0 or ny1 + gap <= oy0 or oy1 + gap <= ny0)
                   for j, (oy0, oy1, ox0, ox1) in enumerate(boxes) if j != i):
                res["notes"].append(f"objektas {size_mm:.1f} mm per arti kaimyno – padidintas užliptų")
                continue
            # Premultiplied alfa – kad kraštai neįgautų tamsaus apvado
            crop = Image.fromarray(rgba[y0:y1, x0:x1].copy(), "RGBA").convert("RGBa")
            big = np.asarray(crop.resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA"))
            rgba[y0:y1, x0:x1, 3] = 0
            rgba[ny0:ny1, nx0:nx1] = big
            res["fixed"].append((round(size_mm, 2), round(nw / px_per_mm, 2)))

        if not res["fixed"]:
            return res
        # Keičiame tik pikselius tame pačiame objekte: spalvų erdvė (DeviceRGB), Intent ir kiti
        # raktai lieka originalūs, kad RasterLink spalvas traktuotų lygiai taip pat.
        _write_stream(doc, xref, np.ascontiguousarray(rgba[..., :3]).tobytes(), w, h)
        _write_stream(doc, smask, np.ascontiguousarray(rgba[..., 3]).tobytes(), w, h)
        tmp = out_pdf + ".part"
        doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, out_pdf)
        res["changed"] = True
        return res
    finally:
        doc.close()
