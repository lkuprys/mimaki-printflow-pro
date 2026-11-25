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
RING_OUTER_MM = 58.92   # rėmų ribų šablono punktyrinės linijos (ringholder užlaidos ribos)
RING_INNER_MM = 40.92
THIN_RING_RATIO = 0.72  # skylė / išorė: normalūs žiedai ~0,65–0,70, blogi (ploni) ~0,77


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


def _object_boxes(alpha: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Objektų ribos (y0, y1, x0, x1) pilnoje raiškoje pagal permatomumą."""
    h, w = alpha.shape
    small = alpha[::DOWNSAMPLE, ::DOWNSAMPLE] >= ALPHA_ON
    boxes = []
    for y0, y1, x0, x1 in _components(small):
        Y0, Y1 = max(0, (y0 - 1) * DOWNSAMPLE), min(h, (y1 + 1) * DOWNSAMPLE)
        X0, X1 = max(0, (x0 - 1) * DOWNSAMPLE), min(w, (x1 + 1) * DOWNSAMPLE)
        ys, xs = np.nonzero(alpha[Y0:Y1, X0:X1] >= ALPHA_ON)
        if len(ys):
            boxes.append((Y0 + ys.min(), Y0 + ys.max() + 1, X0 + xs.min(), X0 + xs.max() + 1))
    return boxes


def _save_pixels(doc, xref: int, smask: int, rgba: np.ndarray, out_pdf: str):
    """Keičiame tik pikselius tame pačiame objekte: spalvų erdvė (DeviceRGB), Intent ir kiti
    raktai lieka originalūs, kad RasterLink spalvas traktuotų lygiai taip pat."""
    h, w = rgba.shape[:2]
    _write_stream(doc, xref, np.ascontiguousarray(rgba[..., :3]).tobytes(), w, h)
    _write_stream(doc, smask, np.ascontiguousarray(rgba[..., 3]).tobytes(), w, h)
    tmp = out_pdf + ".part"
    doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, out_pdf)


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

        boxes = _object_boxes(alpha)

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
        _save_pixels(doc, xref, smask, rgba, out_pdf)
        res["changed"] = True
        return res
    finally:
        doc.close()


def fix_ring_bands(src_pdf: str, out_pdf: str, outer_mm: float = RING_OUTER_MM, inner_mm: float = RING_INNER_MM,
                   thin_ratio: float = THIN_RING_RATIO) -> Dict:
    """
    Per ploną žiedą (skylės ir išorės santykis > thin_ratio, pvz. 46,8 / 60,5 mm) radialiai ištempia
    į šabloną: išorė outer_mm, skylė inner_mm (rėmų ribų punktyrinės linijos), centras tas pats.
    Visas dizainas išlieka – jis ištempiamas skersai juostos. Normalūs žiedai nekeičiami.
    Grąžina {"changed", "fixed": [(išorė_prieš, skylė_prieš, išorė_po, skylė_po)], "notes", "error"}.
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
        boxes = _object_boxes(alpha)
        R_new, r_new = outer_mm / 2 * px_per_mm, inner_mm / 2 * px_per_mm

        for i, (y0, y1, x0, x1) in enumerate(boxes):
            bw, bh = x1 - x0, y1 - y0
            if max(bw, bh) / px_per_mm < MIN_OBJECT_MM or abs(bw - bh) > ROUND_TOLERANCE * max(bw, bh):
                continue
            cy, cx = (y0 + y1) / 2.0, (x0 + x1) / 2.0
            R_old = max(bw, bh) / 2.0
            sub = alpha[y0:y1, x0:x1] >= ALPHA_ON
            yy, xx = np.nonzero(sub)
            rr = np.hypot(xx + x0 + 0.5 - cx, yy + y0 + 0.5 - cy)
            r_old = float(np.percentile(rr, 0.5))          # skylės kraštas (atsparu pavieniams taškams)
            # Tikra skylė: centre nėra dizaino
            c = alpha[int(cy) - 2:int(cy) + 3, int(cx) - 2:int(cx) + 3]
            if r_old < 0.3 * R_old or c.size == 0 or c.max() >= ALPHA_ON:
                continue
            ratio = r_old / R_old
            if ratio <= thin_ratio:
                continue                                    # normalus (storas) žiedas – nekeičiamas
            # Naujasis žiedas turi tilpti lape ir neužlipti ant kaimynų
            Rb = max(R_new, R_old) + 2
            by0, by1 = int(np.floor(cy - Rb)), int(np.ceil(cy + Rb))
            bx0, bx1 = int(np.floor(cx - Rb)), int(np.ceil(cx + Rb))
            if by0 < 0 or bx0 < 0 or by1 > h or bx1 > w:
                res["notes"].append(f"žiedas {2 * R_old / px_per_mm:.1f} mm prie lapo krašto – netaisomas")
                continue
            if any(not (bx1 <= ox0 or ox1 <= bx0 or by1 <= oy0 or oy1 <= by0)
                   for j, (oy0, oy1, ox0, ox1) in enumerate(boxes) if j != i):
                res["notes"].append(f"žiedas {2 * R_old / px_per_mm:.1f} mm per arti kaimyno – netaisomas")
                continue
            # Radialinis atvaizdavimas: naujas [r_new, R_new] <- senas [r_old+1, R_old-1]
            src = rgba[by0:by1, bx0:bx1].astype(np.float32)
            pa = src[..., 3:4] / 255.0
            pre = np.concatenate([src[..., :3] * pa, src[..., 3:4]], axis=2)   # premultiplied
            gy, gx = np.mgrid[by0:by1, bx0:bx1].astype(np.float32)
            dy, dx = gy + 0.5 - cy, gx + 0.5 - cx
            r = np.hypot(dx, dy)
            t = np.clip((r - r_new) / (R_new - r_new), 0.0, 1.0)
            rs = (r_old + 1.0) + t * ((R_old - 1.0) - (r_old + 1.0))
            k = np.where(r > 0, rs / np.maximum(r, 1e-6), 0.0)
            sx = np.clip(cx + dx * k - 0.5 - bx0, 0, (bx1 - bx0) - 1.001)
            sy = np.clip(cy + dy * k - 0.5 - by0, 0, (by1 - by0) - 1.001)
            ix, iy = sx.astype(np.int32), sy.astype(np.int32)
            fx, fy = (sx - ix)[..., None], (sy - iy)[..., None]
            val = (pre[iy, ix] * (1 - fx) * (1 - fy) + pre[iy, ix + 1] * fx * (1 - fy)
                   + pre[iy + 1, ix] * (1 - fx) * fy + pre[iy + 1, ix + 1] * fx * fy)
            cover = np.clip(R_new - r + 0.5, 0, 1) * np.clip(r - r_new + 0.5, 0, 1)   # glotnūs kraštai
            a_new = np.clip(val[..., 3] / 255.0, 0, 1) * cover
            rgb = np.where(val[..., 3:4] > 0, val[..., :3] / np.maximum(val[..., 3:4] / 255.0, 1e-6), 255.0)
            out = np.empty_like(rgba[by0:by1, bx0:bx1])
            out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
            out[..., 3] = np.clip(np.rint(a_new * 255), 0, 255).astype(np.uint8)
            rgba[by0:by1, bx0:bx1] = out
            res["fixed"].append((round(2 * R_old / px_per_mm, 1), round(2 * r_old / px_per_mm, 1),
                                 round(outer_mm, 1), round(inner_mm, 1)))

        if not res["fixed"]:
            return res
        _save_pixels(doc, xref, smask, rgba, out_pdf)
        res["changed"] = True
        return res
    finally:
        doc.close()
