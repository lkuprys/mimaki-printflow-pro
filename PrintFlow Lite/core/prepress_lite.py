"""
Prepress Lite Engine
--------------------
Aukštos kokybės, itin greitas spaudos plokščių (CMYK, White, Primer) generavimo
variklis su SMask tiesioginiu ištraukimu ir precizišku Thinning / Thickening valdymu.

Mimaki / RasterLink 7 suderinamumas:
- Visos White / Primer kaukės sugeneruojamos TIKSLIAI tame pačiame rastro tinklelyje
  (numatyta 300 DPI: w_px = round(w_pt / 72 * 300)), nepriklausomai nuo SMask raiškos.
- Visos plokštės (CMYK, White, Primer) gauna identiškus MediaBox / CropBox / TrimBox /
  BleedBox / ArtBox ir /Rotate įrašus, todėl RasterLink 7 sluoksnius sutapdina 1:1 ir
  nereikalauja rankinio REMOTE / pozicijos koregavimo.
- Kiekviena plokštė įrašoma atomiškai (.part ➔ .pdf) ir po įrašymo patikrinama.
"""

import os
import io
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter
import pymupdf

DEFAULT_PLATE_DPI = 300
MAX_PLATE_PIXELS = 250_000_000  # apsauga nuo atminties perpildymo (pvz. klaidingai milžiniškas puslapis)
BOX_KEYS = ("MediaBox", "CropBox", "TrimBox", "BleedBox", "ArtBox")
GEOMETRY_TOLERANCE_PT = 0.01


class PrepressError(Exception):
    """Aiški, operatoriui suprantama prepress klaida."""


# ---------------------------------------------------------------------------
# PDF pagalbinės funkcijos
# ---------------------------------------------------------------------------
def _open_pdf(file_path: str) -> "pymupdf.Document":
    if not os.path.isfile(file_path):
        raise PrepressError(f"PDF failas nerastas: {file_path}")
    if os.path.getsize(file_path) == 0:
        raise PrepressError(f"PDF failas tuščias (0 B): {file_path}")
    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        raise PrepressError(f"Nepavyko atidaryti PDF (sugadintas ar nepilnas failas?): {e}")
    if doc.needs_pass:
        doc.close()
        raise PrepressError("PDF užšifruotas slaptažodžiu – negalima apdoroti")
    if doc.page_count < 1:
        doc.close()
        raise PrepressError("PDF neturi nė vieno puslapio")
    return doc


def _target_pixels(w_pt: float, h_pt: float, dpi: int) -> Tuple[int, int]:
    w_px = max(1, int(round(w_pt / 72.0 * dpi)))
    h_px = max(1, int(round(h_pt / 72.0 * dpi)))
    if w_px * h_px > MAX_PLATE_PIXELS:
        raise PrepressError(
            f"Puslapis per didelis rastravimui ({w_pt:.0f}x{h_pt:.0f} pt ➔ {w_px}x{h_px} px @ {dpi} DPI)"
        )
    return w_px, h_px


def _parse_pdf_array(value: str) -> Optional[List[float]]:
    try:
        nums = [float(x) for x in value.strip().strip("[]").split()]
        return nums if len(nums) == 4 else None
    except Exception:
        return None


def _get_inherited_key(doc, xref: int, key: str) -> Tuple[str, str]:
    """Nuskaito puslapio raktą, atsižvelgiant į paveldėjimą iš /Parent (MediaBox, CropBox, Rotate)."""
    seen = set()
    while xref and xref not in seen:
        seen.add(xref)
        typ, val = doc.xref_get_key(xref, key)
        if typ != "null":
            return typ, val
        ptyp, pval = doc.xref_get_key(xref, "Parent")
        if ptyp != "xref":
            break
        xref = int(pval.split()[0])
    return "null", "null"


def read_page_geometry(doc, page_index: int = 0) -> Dict:
    """
    Grąžina efektyvią puslapio geometriją PDF koordinatėmis:
    {"MediaBox": [..], "CropBox": [..], "TrimBox": [..], "BleedBox": [..], "ArtBox": [..], "Rotate": int}
    Trūkstami langeliai užpildomi pagal PDF specifikaciją (Crop=Media, Trim/Bleed/Art=Crop).
    """
    page = doc[page_index]
    xref = page.xref
    mb = None
    typ, val = _get_inherited_key(doc, xref, "MediaBox")
    if typ == "array":
        mb = _parse_pdf_array(val)
    if not mb:
        r = page.mediabox
        mb = [r.x0, r.y0, r.x1, r.y1]

    def _box(key, inherited, default):
        if inherited:
            t, v = _get_inherited_key(doc, xref, key)
        else:
            t, v = doc.xref_get_key(xref, key)
        arr = _parse_pdf_array(v) if t == "array" else None
        if not arr:
            return list(default)
        # Langelis negali išeiti už MediaBox ribų (PDF spec. – apkerpama)
        return [
            max(arr[0], mb[0]), max(arr[1], mb[1]),
            min(arr[2], mb[2]), min(arr[3], mb[3]),
        ]

    cb = _box("CropBox", True, mb)
    geo = {
        "MediaBox": mb,
        "CropBox": cb,
        "TrimBox": _box("TrimBox", False, cb),
        "BleedBox": _box("BleedBox", False, cb),
        "ArtBox": _box("ArtBox", False, cb),
        "Rotate": int(page.rotation) % 360,
    }
    return geo


def apply_page_geometry(doc, page_index: int, geo: Dict, rotate: Optional[int] = None):
    """Įrašo identiškus langelius ir pasukimą į puslapį (tiesiogiai į PDF objektą)."""
    page = doc[page_index]
    xref = page.xref
    for key in BOX_KEYS:
        arr = geo[key]
        doc.xref_set_key(xref, key, "[%s]" % " ".join(_fmt_num(v) for v in arr))
    rot = int(geo.get("Rotate", 0)) if rotate is None else int(rotate)
    doc.xref_set_key(xref, "Rotate", str(rot))


def _fmt_num(v: float) -> str:
    s = ("%.4f" % float(v)).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _geometry_equal(a: Dict, b: Dict) -> bool:
    for key in BOX_KEYS:
        if any(abs(x - y) > GEOMETRY_TOLERANCE_PT for x, y in zip(a[key], b[key])):
            return False
    return int(a.get("Rotate", 0)) == int(b.get("Rotate", 0))


# ---------------------------------------------------------------------------
# Kaukės ištraukimas
# ---------------------------------------------------------------------------
def _try_extract_smask(doc, page, w_px: int, h_px: int) -> Optional[np.ndarray]:
    """
    Greitas kelias: integruotas SMask (Podbase standartas).
    Naudojamas TIK jei vienintelis paveikslėlis su SMask dengia visą matomą puslapį,
    nėra pasuktas / apverstas ir puslapis nepasuktas. Kitaip – None (saugus rastravimas).
    """
    if page.rotation % 360 != 0:
        return None

    infos = page.get_image_info(xrefs=True)
    if len(infos) != 1:
        return None
    info = infos[0]
    xref = info.get("xref", 0)
    if not xref:
        return None

    smask_xref = 0
    for img in page.get_images(full=True):
        if img[0] == xref:
            smask_xref = img[1]
            break
    if not smask_xref:
        return None

    a, b, c, d, _e, _f = info.get("transform", (0, 0, 0, 0, 0, 0))
    if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
        return None

    bbox = pymupdf.Rect(info["bbox"])
    pr = page.rect
    tol = 0.5  # pt
    if (abs(bbox.x0 - pr.x0) > tol or abs(bbox.y0 - pr.y0) > tol or
            abs(bbox.x1 - pr.x1) > tol or abs(bbox.y1 - pr.y1) > tol):
        return None

    try:
        smask_dict = doc.extract_image(smask_xref)
        smask_img = Image.open(io.BytesIO(smask_dict["image"]))
        smask_img.load()
    except Exception:
        return None

    # Bet koks režimas ('1', 'L', 'I;16', 'RGB'...) ➔ 8 bitų pilkas
    if smask_img.mode == "1":
        smask_img = smask_img.convert("L")
    elif smask_img.mode in ("I;16", "I;16B", "I;16L", "I"):
        arr16 = np.array(smask_img, dtype=np.float64)
        maxv = 65535.0 if arr16.max() > 255 else 255.0
        smask_img = Image.fromarray(np.clip(arr16 / maxv * 255.0, 0, 255).astype(np.uint8), "L")
    elif smask_img.mode != "L":
        smask_img = smask_img.convert("L")

    # Normalizuojame į tikslų plokštės tinklelį (vienodas DPI visoms plokštėms)
    if smask_img.size != (w_px, h_px):
        smask_img = smask_img.resize((w_px, h_px), Image.Resampling.BILINEAR)

    return np.array(smask_img) > 128


def _render_alpha_mask(page, w_px: int, h_px: int) -> np.ndarray:
    """Saugus kelias: puslapis rastruojamas su permatomu fonu, kaukė = alfa kanalas."""
    mat = pymupdf.Matrix(w_px / page.rect.width, h_px / page.rect.height)
    pix = page.get_pixmap(matrix=mat, alpha=True)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.stride // pix.n, pix.n))
    arr = arr[:, :pix.width, :]
    alpha = np.ascontiguousarray(arr[..., -1])
    if alpha.shape != (h_px, w_px):
        alpha = np.array(Image.fromarray(alpha, "L").resize((w_px, h_px), Image.Resampling.NEAREST))
    return alpha > 10


def extract_pdf_data(file_path: str, dpi: int = DEFAULT_PLATE_DPI):
    """
    Nuskaito PDF failą ir grąžina kaukę tiksliame `dpi` tinklelyje.
    Kaukė visada skaičiuojama NEPASUKTOJE CropBox erdvėje (PDF vartotojo koordinatės),
    kad plokštėje ji būtų įdėta į tą pačią erdvę kaip CMYK turinys, o /Rotate taikomas vienodai.
    Jei faile yra integruotas visą puslapį dengiantis SMask – ištraukia jį akimirksniu (~0.2s),
    kitaip rastruoja puslapį su alfa kanalu.
    Grąžina: (w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask)
    """
    doc = _open_pdf(file_path)
    try:
        page = doc[0]
        if page.rotation % 360:
            page.set_rotation(0)  # tik atmintyje – šaltinio failas nekeičiamas
        rect = page.rect
        w_pt, h_pt = rect.width, rect.height
        if w_pt <= 0 or h_pt <= 0:
            raise PrepressError(f"Netinkami puslapio matmenys: {w_pt}x{h_pt} pt")
        w_px, h_px = _target_pixels(w_pt, h_pt, dpi)

        mask_bool = _try_extract_smask(doc, page, w_px, h_px)
        if mask_bool is None:
            mask_bool = _render_alpha_mask(page, w_px, h_px)

        # Greita sumažinta peržiūra (max 800px)
        scale = min(800.0 / w_px, 800.0 / h_px, 1.0)
        t_w, t_h = max(1, int(w_px * scale)), max(1, int(h_px * scale))
        thumb_pix = page.get_pixmap(matrix=pymupdf.Matrix(t_w / w_pt, t_h / h_pt), alpha=False)
        thumb_rgb = Image.frombytes("RGB", [thumb_pix.width, thumb_pix.height], thumb_pix.samples)
        thumb_mask = Image.fromarray(mask_bool).resize((t_w, t_h), Image.Resampling.NEAREST)
        return w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, np.array(thumb_mask)
    finally:
        doc.close()


def compute_mask_choke_spread(mask: np.ndarray, pixels: int) -> np.ndarray:
    """
    Taikoma kaukei:
    - pixels > 0: Thinning (Choke / erozija) – sutraukia kaukę, kad balta/gruntas neišlįstų po CMYK.
    - pixels < 0: Thickening (Spread / plėtimas) – išpučia kaukę.
    - pixels == 0: Originalas be pakeitimų.
    Greita C lygio operacija per Pillow MinFilter / MaxFilter.
    """
    pixels = int(pixels)
    if pixels == 0:
        return mask.copy()

    k = abs(pixels)
    filter_size = 2 * k + 1
    pil_mask = Image.fromarray((mask.astype(np.uint8)) * 255)

    if pixels > 0:
        # Thinning (sutraukimas / choke)
        filtered = pil_mask.filter(ImageFilter.MinFilter(filter_size))
    else:
        # Thickening (išpūtimas / spread)
        filtered = pil_mask.filter(ImageFilter.MaxFilter(filter_size))

    return np.array(filtered) > 128


# ---------------------------------------------------------------------------
# Plokščių įrašymas
# ---------------------------------------------------------------------------
def _atomic_save(doc, final_path: str):
    tmp_path = final_path + ".part"
    try:
        doc.save(tmp_path, deflate=True, garbage=1)
        os.replace(tmp_path, final_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _write_mask_plate(mask: np.ndarray, geo: Dict, out_path: str, dpi: int):
    """Sukuria vienspalvę (Black = 100% White/Primer rašalo) plokštę su šaltinio geometrija."""
    h_px, w_px = mask.shape
    mono = np.full((h_px, w_px), 255, dtype=np.uint8)
    mono[mask] = 0

    mb = geo["MediaBox"]
    plate = pymupdf.open()
    try:
        plate.new_page(width=mb[2] - mb[0], height=mb[3] - mb[1])
        # Paveikslėlis įdedamas esant /Rotate 0 (PyMuPDF insert_image netiksliai elgiasi su
        # pasuktais puslapiais, kurių MediaBox nėra ties 0,0). Pasukimas pritaikomas po to –
        # identiškai kaip CMYK plokštėje.
        apply_page_geometry(plate, 0, geo, rotate=0)
        page = plate[0]

        buf = io.BytesIO()
        Image.fromarray(mono, mode="L").save(buf, format="PNG", dpi=(dpi, dpi), optimize=False)
        # page.rect = nepasuktas CropBox plotas – lygiai tas pats plotas, kurį rastravome kaukei.
        page.insert_image(page.rect, stream=buf.getvalue(), keep_proportion=False)
        apply_page_geometry(plate, 0, geo)
        _atomic_save(plate, out_path)
    finally:
        plate.close()


def verify_plates(plate_files: Dict[str, str], dpi: int = DEFAULT_PLATE_DPI) -> List[str]:
    """
    Patikrina, kad visų plokščių geometrija identiška ir kaukių efektyvus DPI = `dpi`.
    Grąžina problemų sąrašą (tuščias = viskas gerai).
    """
    problems = []
    ref_geo = None
    ref_name = None
    for layer, path in plate_files.items():
        try:
            doc = pymupdf.open(path)
        except Exception as e:
            problems.append(f"{layer}: nepavyko atidaryti sugeneruotos plokštės ({e})")
            continue
        try:
            if doc.page_count != 1:
                problems.append(f"{layer}: plokštė turi {doc.page_count} puslapius (turi būti 1)")
            geo = read_page_geometry(doc, 0)
            if ref_geo is None:
                ref_geo, ref_name = geo, layer
            elif not _geometry_equal(ref_geo, geo):
                problems.append(f"{layer}: geometrija nesutampa su {ref_name} ({geo} != {ref_geo})")

            if layer != "CMYK":
                page = doc[0]
                infos = page.get_image_info()
                if len(infos) != 1:
                    problems.append(f"{layer}: tikėtasi 1 paveikslėlio, rasta {len(infos)}")
                else:
                    info = infos[0]
                    bbox = pymupdf.Rect(info["bbox"])
                    # Paveikslėlis turi dengti visą matomą plotą (tikriname ir pasuktą, ir nepasuktą erdvę)
                    candidates = [page.rect, page.rect * page.derotation_matrix]
                    covered = None
                    for pr in candidates:
                        pr = pymupdf.Rect(pr).normalize()
                        if (abs(bbox.x0 - pr.x0) <= 0.05 and abs(bbox.y0 - pr.y0) <= 0.05 and
                                abs(bbox.x1 - pr.x1) <= 0.05 and abs(bbox.y1 - pr.y1) <= 0.05):
                            covered = pr
                            break
                    if covered is None:
                        problems.append(f"{layer}: kaukė nedengia viso puslapio ({bbox} != {page.rect})")
                    else:
                        # Efektyvus DPI (paveikslėlio px / matomo ploto coliai) – abiem ašimis
                        dpis = [
                            (info["width"] / (bbox.width / 72.0), info["height"] / (bbox.height / 72.0)),
                            (info["width"] / (bbox.height / 72.0), info["height"] / (bbox.width / 72.0)),
                        ]
                        if not any(abs(x - dpi) <= 0.5 and abs(y - dpi) <= 0.5 for x, y in dpis):
                            ex, ey = dpis[0]
                            problems.append(f"{layer}: efektyvus DPI {ex:.2f}x{ey:.2f} != {dpi}")
        finally:
            doc.close()
    return problems


def export_production_plates(
    source_pdf_path: str,
    job_name: str,
    output_dir: str,
    layers: list,
    choke_white_px: int = 1,
    choke_primer_px: int = 0,
    dpi: int = DEFAULT_PLATE_DPI,
    warnings_out: Optional[list] = None,
) -> dict:
    """
    Sugeneruoja paruoštas spaudos plokštes (PDF suderinamas su RasterLink 7).
    Grąžina žodyną: {"CMYK": kelias, "White": kelias, "Primer": kelias}
    Išmeta PrepressError, jei plokščių geometrija ar DPI nesutampa.
    """
    def warn(msg):
        if warnings_out is not None:
            warnings_out.append(msg)

    unknown = [l for l in layers if l not in ("CMYK", "White", "Primer")]
    if unknown:
        raise PrepressError(f"Nežinomi sluoksniai: {unknown} (galimi: CMYK, White, Primer)")
    if not layers:
        raise PrepressError("Produktui nenurodytas nė vienas sluoksnis")

    os.makedirs(output_dir, exist_ok=True)
    generated = {}

    # Šaltinio geometrija (vienintelis tiesos šaltinis visoms plokštėms)
    doc_src = _open_pdf(source_pdf_path)
    try:
        if doc_src.page_count > 1:
            warn(f"PDF turi {doc_src.page_count} puslapius – naudojamas tik 1-as puslapis")
        geo = read_page_geometry(doc_src, 0)

        # 1. CMYK plokštė – originalus turinys, tik 1 puslapis, aiškiai įrašyti langeliai
        if "CMYK" in layers:
            if doc_src.page_count > 1:
                doc_src.select([0])
            apply_page_geometry(doc_src, 0, geo)
            cmyk_path = os.path.join(output_dir, f"{job_name}_Plate_1_CMYK.pdf")
            _atomic_save(doc_src, cmyk_path)
            generated["CMYK"] = cmyk_path
    finally:
        doc_src.close()

    need_mask = "White" in layers or "Primer" in layers
    if need_mask:
        _, _, _, _, mask_bool, _, _ = extract_pdf_data(source_pdf_path, dpi=dpi)
        if not mask_bool.any():
            warn("Kaukė tuščia – White/Primer plokštės bus be rašalo (patikrinkite failo permatomumą)")
        elif mask_bool.all():
            warn("Kaukė dengia VISĄ lapą – faile nėra permatomumo (SMask/alfa), balta bus per visą plotą")

        # 2. White plokštė (su Choke/Spread nustatymu)
        if "White" in layers:
            white_path = os.path.join(output_dir, f"{job_name}_Plate_2_White.pdf")
            _write_mask_plate(compute_mask_choke_spread(mask_bool, choke_white_px), geo, white_path, dpi)
            generated["White"] = white_path

        # 3. Primer plokštė (su Choke/Spread nustatymu)
        if "Primer" in layers:
            primer_path = os.path.join(output_dir, f"{job_name}_Plate_3_Primer.pdf")
            _write_mask_plate(compute_mask_choke_spread(mask_bool, choke_primer_px), geo, primer_path, dpi)
            generated["Primer"] = primer_path

    problems = verify_plates(generated, dpi=dpi)
    if problems:
        raise PrepressError("Plokščių patikra nepavyko: " + "; ".join(problems))

    return generated
