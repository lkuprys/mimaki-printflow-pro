"""
Ringholderių sudėjimas į vieną rėmą
-----------------------------------
Užsakymų failuose dažnai būna tik 1–2 žiedai, o rėme telpa 18. Modulis iš kelių užsakymų
failų paima žiedus ir sudeda juos į laisvas rėmo vietas (WALLETGRIP šablono ringholder vietos,
6 stulpeliai × 3 eilės). Kiekvienas žiedas nukopijuojamas pikselis į pikselį (RGB + SMask),
todėl iš sujungto failo sugeneruotos CMYK / White / Primer plokštės sutampa 1:1, kaip ir
įprastų užsakymų.

Pagrindas – pirmojo užsakymo failas, jei jis rėmo dydžio (išlieka jo spalvų erdvė ir
Intent), kitaip – rėmų ribų šablonas (assets/presets/WALLETGRIP.pdf).
Vienas užsakymas visada dedamas į vieną rėmą (jei telpa), kad būtų lengva komplektuoti.
"""

import os
import shutil
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
import pymupdf

from core.size_fix import (MIN_OBJECT_MM, _load_rgba, _object_boxes, _page_image, _write_stream,
                           fix_object_sizes, fix_ring_bands)

# Ringholder vietų centrai rėme (mm nuo viršutinio kairiojo kampo) – WALLETGRIP šablono apskritimai
SLOT_COLS_MM = (66.85, 163.53, 260.14, 356.74, 453.43, 549.95)
SLOT_ROWS_MM = (167.17, 277.75, 387.39)
SLOTS_MM: List[Tuple[float, float]] = [(x, y) for y in SLOT_ROWS_MM for x in SLOT_COLS_MM]
SLOTS_PER_FRAME = len(SLOTS_MM)
FRAME_MM = (608.92, 418.93)      # rėmo (šablono) lapo dydis
FRAME_TOLERANCE_MM = 1.5
UNIT_MIN_MM, UNIT_MAX_MM = 40.0, 75.0   # žiedo (vieneto) dydžio ribos – kitokie objektai nėra ringholderiai
MARGIN_MM = 1.0                  # kopijuojama su nedidele parašte (minkšti kraštai)


class GangError(Exception):
    pass


# ---------------------------------------------------------------------------
# Šaltinio paruošimas ir žiedų paieška
# ---------------------------------------------------------------------------
def apply_ring_fixes(prod: Dict, src_pdf: str, work_dir: str, name: str,
                     log: Optional[Callable[[str], None]] = None) -> str:
    """Tie patys taisymai kaip įprastame sraute (ring_band_fix, tada fit_size_mm).
    Grąžina failą, iš kurio imami žiedai."""
    log = log or (lambda _m: None)
    os.makedirs(work_dir, exist_ok=True)
    if prod.get("ring_band_fix"):
        out = os.path.join(work_dir, f"{name}_ziedas_pataisytas.pdf")
        res = fix_ring_bands(src_pdf, out)
        if res.get("changed"):
            log(f"   ⭕ {name}: plonas žiedas ištemptas pagal šabloną")
            return out
    try:
        target = float(prod.get("fit_size_mm") or 0)
    except (TypeError, ValueError):
        target = 0.0
    if target > 0:
        out = os.path.join(work_dir, f"{name}_dydis_pataisytas.pdf")
        res = fix_object_sizes(src_pdf, out, target)
        if res.get("changed"):
            log(f"   📏 {name}: per mažas žiedas padidintas iki {target:g} mm")
            return out
    return src_pdf


def _merge_boxes(boxes: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int, int]]:
    """Susikertančios sritys (pvz. žiedas ir atskiri jo viduje esantys elementai) – vienas vienetas."""
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: List[List[int]] = []
        for b in boxes:
            for o in out:
                if b[0] < o[1] and o[0] < b[1] and b[2] < o[3] and o[2] < b[3]:
                    o[0], o[1], o[2], o[3] = min(o[0], b[0]), max(o[1], b[1]), min(o[2], b[2]), max(o[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return [tuple(b) for b in boxes]


def _open_rgba(pdf_path: str) -> Tuple[np.ndarray, float, str]:
    """(RGBA masyvas, px/mm, spalvų erdvė) – tik Podbase struktūra (vienas RGB paveikslėlis su SMask)."""
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        raise GangError(f"nepavyko atidaryti PDF: {e}")
    try:
        if doc.page_count < 1:
            raise GangError("PDF be puslapių")
        page = doc[0]
        xref, smask, err = _page_image(doc, page)
        if err:
            raise GangError(err)
        rgba = _load_rgba(doc, xref, smask)
        if rgba is None:
            raise GangError("paveikslėlis ne RGB")
        px_per_mm = rgba.shape[1] / (page.rect.width / 72 * 25.4)
        cs = str(doc.xref_get_key(xref, "ColorSpace")[1])
        return rgba, px_per_mm, cs
    finally:
        doc.close()


def find_units(rgba: np.ndarray, px_per_mm: float) -> Tuple[List[Tuple[int, int, int, int]], List[str]]:
    """Žiedų (vienetų) ribos (y0, y1, x0, x1), surūšiuotos eilėmis (viršus → apačia, kairė → dešinė)."""
    notes = []
    alpha = rgba[..., 3]
    boxes = _merge_boxes(_object_boxes(alpha))
    units = []
    for y0, y1, x0, x1 in boxes:
        h_mm, w_mm = (y1 - y0) / px_per_mm, (x1 - x0) / px_per_mm
        if max(h_mm, w_mm) < MIN_OBJECT_MM:
            notes.append(f"smulkus objektas {w_mm:.1f}×{h_mm:.1f} mm praleistas")
            continue
        if not (UNIT_MIN_MM <= w_mm <= UNIT_MAX_MM and UNIT_MIN_MM <= h_mm <= UNIT_MAX_MM):
            raise GangError(f"objektas {w_mm:.1f}×{h_mm:.1f} mm – ne ringholder žiedas "
                            f"({UNIT_MIN_MM:g}–{UNIT_MAX_MM:g} mm)")
        units.append((y0, y1, x0, x1))
    row_mm = 20.0 * px_per_mm  # tos pačios eilės žiedai – ±20 mm
    units.sort(key=lambda b: (round(((b[0] + b[1]) / 2) / row_mm), (b[2] + b[3]) / 2))
    return units, notes


def count_units(pdf_path: str) -> int:
    rgba, px_per_mm, _cs = _open_rgba(pdf_path)
    return len(find_units(rgba, px_per_mm)[0])


def extract_units(pdf_path: str, px_per_mm_out: float) -> Tuple[List[np.ndarray], str, List[str]]:
    """Kiekvieno žiedo RGBA iškarpa (su parašte, centras = iškarpos centras) rėmo raiška."""
    rgba, px_per_mm, cs = _open_rgba(pdf_path)
    units, notes = find_units(rgba, px_per_mm)
    if not units:
        raise GangError("faile nerasta žiedų")
    h, w = rgba.shape[:2]
    m = int(round(MARGIN_MM * px_per_mm))
    crops = []
    for y0, y1, x0, x1 in units:
        cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
        half_h, half_w = (y1 - y0) / 2 + m, (x1 - x0) / 2 + m
        Y0, Y1 = int(np.floor(cy - half_h)), int(np.ceil(cy + half_h))
        X0, X1 = int(np.floor(cx - half_w)), int(np.ceil(cx + half_w))
        crop = np.zeros((Y1 - Y0, X1 - X0, 4), np.uint8)
        sy0, sy1, sx0, sx1 = max(0, Y0), min(h, Y1), max(0, X0), min(w, X1)
        crop[sy0 - Y0:sy1 - Y0, sx0 - X0:sx1 - X0] = rgba[sy0:sy1, sx0:sx1]
        if abs(px_per_mm - px_per_mm_out) / px_per_mm_out > 0.002:
            # Kita raiška – perskaičiuojama premultiplied (kad permatomi kraštai neįgautų fono spalvos)
            k = px_per_mm_out / px_per_mm
            a = crop[..., 3:4].astype(np.float32) / 255.0
            pre = np.concatenate([crop[..., :3].astype(np.float32) * a, crop[..., 3:4].astype(np.float32)], axis=2)
            size = (max(1, int(round(crop.shape[1] * k))), max(1, int(round(crop.shape[0] * k))))
            chans = [np.asarray(Image.fromarray(pre[..., i]).resize(size, Image.Resampling.BILINEAR))
                     for i in range(4)]
            al = np.clip(chans[3], 0, 255)
            safe = np.where(al > 0, al / 255.0, 1.0)
            rgb = np.stack([np.clip(c / safe, 0, 255) for c in chans[:3]], axis=2)
            crop = np.dstack([rgb, al]).round().astype(np.uint8)
        crops.append(crop)
    return crops, cs, notes


# ---------------------------------------------------------------------------
# Išdėstymas
# ---------------------------------------------------------------------------
def plan_frames(counts: Sequence[Tuple[str, int]], capacity: int = SLOTS_PER_FRAME) -> List[List[Tuple[str, int]]]:
    """[(užsakymas, žiedų sk.)] ➔ rėmai [[(užsakymas, kiek žiedų šiame rėme)], ...].
    Užsakymas neskaidomas į kelis rėmus, jei telpa viename (first-fit)."""
    frames: List[List[Tuple[str, int]]] = []
    free: List[int] = []
    for job_id, n in counts:
        while n > capacity:                       # labai didelis užsakymas – pilni rėmai
            frames.append([(job_id, capacity)])
            free.append(0)
            n -= capacity
        if n <= 0:
            continue
        for i, f in enumerate(free):
            if f >= n:
                frames[i].append((job_id, n))
                free[i] -= n
                break
        else:
            frames.append([(job_id, n)])
            free.append(capacity - n)
    return frames


def _frame_base(first_src: str, template_pdf: str) -> str:
    """Pirmojo užsakymo failas, jei jis rėmo dydžio, kitaip – šablonas."""
    try:
        with pymupdf.open(first_src) as d:
            r = d[0].rect
            w_mm, h_mm = r.width / 72 * 25.4, r.height / 72 * 25.4
            ok = not _page_image(d, d[0])[2]
        if ok and abs(w_mm - FRAME_MM[0]) <= FRAME_TOLERANCE_MM and abs(h_mm - FRAME_MM[1]) <= FRAME_TOLERANCE_MM:
            return first_src
    except Exception:
        pass
    return template_pdf


def frame_resolution(base_pdf: str) -> Tuple[int, int, float]:
    with pymupdf.open(base_pdf) as d:
        page = d[0]
        xref, _smask, err = _page_image(d, page)
        if err:
            raise GangError(f"rėmo pagrindas netinkamas: {err}")
        pix = pymupdf.Pixmap(d, xref)
        w_mm = page.rect.width / 72 * 25.4
        return pix.width, pix.height, pix.width / w_mm


def compose_frame(base_pdf: str, placements: List[Tuple[int, np.ndarray]], out_pdf: str):
    """placements: [(vietos indeksas 0..17, RGBA iškarpa)] ➔ naujas rėmo PDF (geometrija – kaip pagrindo)."""
    doc = pymupdf.open(base_pdf)
    try:
        page = doc[0]
        xref, smask, err = _page_image(doc, page)
        if err:
            raise GangError(f"rėmo pagrindas netinkamas: {err}")
        pix = pymupdf.Pixmap(doc, xref)
        W, H = pix.width, pix.height
        px_per_mm = W / (page.rect.width / 72 * 25.4)
        rgb = np.full((H, W, 3), 255, np.uint8)
        alpha = np.zeros((H, W), np.uint8)
        for slot, crop in placements:
            sx, sy = SLOTS_MM[slot]
            ch, cw = crop.shape[:2]
            y0, x0 = int(round(sy * px_per_mm - ch / 2)), int(round(sx * px_per_mm - cw / 2))
            if y0 < 0 or x0 < 0 or y0 + ch > H or x0 + cw > W:
                raise GangError(f"žiedas netelpa į rėmo vietą {slot + 1}")
            a = crop[..., 3] > 0
            rgb[y0:y0 + ch, x0:x0 + cw][a] = crop[..., :3][a]
            alpha[y0:y0 + ch, x0:x0 + cw] = np.maximum(alpha[y0:y0 + ch, x0:x0 + cw], crop[..., 3])
        _write_stream(doc, xref, rgb.tobytes(), W, H)
        _write_stream(doc, smask, alpha.tobytes(), W, H)
        meta = dict(doc.metadata or {})
        meta["title"] = os.path.splitext(os.path.basename(out_pdf))[0]
        doc.set_metadata(meta)
        tmp = out_pdf + ".part"
        doc.save(tmp, garbage=3, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, out_pdf)


def write_slot_map(path: str, title: str, slots: List[Dict], font_dir: str = ""):
    """A4 vietų žemėlapis komplektavimui: kuri rėmo vieta – kurio užsakymo."""
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    reg, bold = "helv", "hebo"
    fr = os.path.join(font_dir, "Inter-Regular.ttf") if font_dir else ""
    fb = os.path.join(font_dir, "Inter-SemiBold.ttf") if font_dir else ""
    if fr and os.path.isfile(fr) and fb and os.path.isfile(fb):
        page.insert_font(fontname="inr", fontfile=fr)
        page.insert_font(fontname="inb", fontfile=fb)
        reg, bold = "inr", "inb"
    page.insert_text((36, 44), title, fontname=bold, fontsize=16)
    page.insert_text((36, 62), f"Vietų žemėlapis · {len(slots)} žied. · vietos skaičiuojamos iš kairės į dešinę, "
                               f"nuo viršaus", fontname=reg, fontsize=9, color=(0.35, 0.35, 0.4))
    by_slot = {s["slot"]: s for s in slots}
    jobs = []
    for s in slots:
        if s["job_id"] not in jobs:
            jobs.append(s["job_id"])
    palette = [(0.91, 0.95, 1.0), (0.93, 0.98, 0.92), (1.0, 0.95, 0.88), (0.97, 0.92, 1.0),
               (1.0, 0.92, 0.93), (0.92, 0.98, 0.98)]
    cell_w, cell_h, x0, y0 = 128, 118, 36, 80
    for i in range(SLOTS_PER_FRAME):
        r, c = divmod(i, len(SLOT_COLS_MM))
        rect = pymupdf.Rect(x0 + c * (cell_w + 4), y0 + r * (cell_h + 4),
                            x0 + c * (cell_w + 4) + cell_w, y0 + r * (cell_h + 4) + cell_h)
        s = by_slot.get(i + 1)
        fill = palette[jobs.index(s["job_id"]) % len(palette)] if s else (0.97, 0.97, 0.97)
        page.draw_rect(rect, color=(0.75, 0.76, 0.85), fill=fill, width=0.8)
        page.insert_text((rect.x0 + 8, rect.y0 + 22), str(i + 1), fontname=bold, fontsize=18)
        if not s:
            page.insert_text((rect.x0 + 8, rect.y0 + 44), "tuščia", fontname=reg, fontsize=9, color=(0.55, 0.55, 0.6))
            continue
        page.insert_text((rect.x0 + 8, rect.y0 + 42), f"BID {s.get('bid') or '-'}", fontname=bold, fontsize=11)
        page.insert_textbox(pymupdf.Rect(rect.x0 + 8, rect.y0 + 48, rect.x1 - 6, rect.y0 + 70),
                            s.get("product", ""), fontname=reg, fontsize=8)
        page.insert_textbox(pymupdf.Rect(rect.x0 + 8, rect.y0 + 72, rect.x1 - 6, rect.y0 + 98),
                            s["job_id"], fontname=reg, fontsize=7, color=(0.35, 0.35, 0.4))
        page.insert_text((rect.x0 + 8, rect.y1 - 9), f"žiedas {s.get('unit', 1)} iš {s.get('of', 1)}",
                         fontname=reg, fontsize=8)
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# Visas sudėjimas
# ---------------------------------------------------------------------------
def gang_jobs(jobs: List[Dict], products: Dict[str, Dict], work_dir: str, name: str, template_pdf: str,
              font_dir: str = "", log: Optional[Callable[[str], None]] = None,
              should_continue: Callable[[], bool] = lambda: True) -> Tuple[List[Dict], List[Tuple[str, str]]]:
    """
    jobs: registro įrašai (job_id, local_pdf_path, product_id, bid). Grąžina:
      frames  – [{"name", "source_pdf", "slot_map_pdf", "slots": [...], "members": [...]}]
      skipped – [(job_id, priežastis)]
    """
    log = log or (lambda _m: None)
    skipped: List[Tuple[str, str]] = []
    prepared: List[Tuple[Dict, str]] = []
    fixes_dir = os.path.join(work_dir, "_paruosti")
    for job in jobs:
        jid = job["job_id"]
        src = job.get("local_pdf_path") or ""
        prod = products.get(job.get("product_id", ""))
        if not src or not os.path.isfile(src):
            skipped.append((jid, f"nerastas originalas: {src or '(nėra)'}"))
            continue
        if prod is None:
            skipped.append((jid, f"produktas „{job.get('product_id', '')}“ nerastas nustatymuose"))
            continue
        try:
            prepared.append((job, apply_ring_fixes(prod, src, fixes_dir, jid, log)))
        except Exception as e:
            skipped.append((jid, f"taisymas nepavyko: {e}"))
    if not prepared:
        raise GangError("nėra tinkamų užsakymų")

    base = _frame_base(prepared[0][1], template_pdf)
    _w, _h, px_per_mm = frame_resolution(base)
    base_cs = None
    with pymupdf.open(base) as d:
        base_cs = str(d.xref_get_key(_page_image(d, d[0])[0], "ColorSpace")[1])

    units: Dict[str, List[np.ndarray]] = {}
    order: List[Tuple[str, int]] = []
    for job, src in prepared:
        if not should_continue():
            raise GangError("sustabdyta")
        jid = job["job_id"]
        try:
            crops, cs, notes = extract_units(src, px_per_mm)
        except GangError as e:
            skipped.append((jid, str(e)))
            continue
        for n in notes:
            log(f"   ⚠️ {jid}: {n}")
        if cs != base_cs:
            log(f"   ⚠️ {jid}: kita spalvų erdvė ({cs}) nei rėmo ({base_cs}) – patikrinkite spalvas")
        units[jid] = crops
        order.append((jid, len(crops)))
    if not order:
        raise GangError("nė viename faile nerasta tinkamų žiedų")

    by_id = {job["job_id"]: job for job, _ in prepared}
    frames_plan = plan_frames(order)
    used = {jid: 0 for jid, _ in order}
    frames = []
    for k, frame in enumerate(frames_plan, 1):
        fname = name if len(frames_plan) == 1 else f"{name}_{k}"
        fdir = os.path.join(work_dir, fname)
        os.makedirs(fdir, exist_ok=True)
        placements, slots, slot = [], [], 0
        for jid, n in frame:
            job = by_id[jid]
            prod = products.get(job.get("product_id", ""), {})
            total = len(units[jid])
            for _ in range(n):
                i = used[jid]
                placements.append((slot, units[jid][i]))
                slots.append({"slot": slot + 1, "job_id": jid, "bid": job.get("bid", ""),
                              "product": prod.get("name", job.get("product_name", "")),
                              "unit": i + 1, "of": total})
                used[jid] += 1
                slot += 1
        src_pdf = os.path.join(fdir, f"{fname}.pdf")
        compose_frame(base, placements, src_pdf)
        map_pdf = os.path.join(fdir, f"{fname}_vietu_zemelapis.pdf")
        write_slot_map(map_pdf, fname, slots, font_dir)
        frames.append({"name": fname, "dir": fdir, "source_pdf": src_pdf, "slot_map_pdf": map_pdf,
                       "slots": slots, "members": [jid for jid, _ in frame]})
        log(f"   🧩 {fname}: {len(slots)} žied. iš {len(frame)} užsak. (vietos 1–{len(slots)})")
    shutil.rmtree(fixes_dir, ignore_errors=True)
    return frames, skipped


def print_profile(prod: Dict) -> Tuple:
    """Produktai, kuriuos galima dėti į vieną rėmą: tie patys sluoksniai, eilė, HotFolderiai ir choke."""
    layers = tuple(prod.get("layers") or ())
    hf = prod.get("hotfolders") or {}
    return (layers, tuple(l for l in (prod.get("dispatch_order") or layers) if l in layers),
            tuple((l, (hf.get(l) or "").strip().lower()) for l in layers),
            int(prod.get("choke_white_px", 1) or 0), int(prod.get("choke_primer_px", 0) or 0))
