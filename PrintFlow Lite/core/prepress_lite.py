"""
Prepress Lite Engine
--------------------
Aukštos kokybės, itin greitas spaudos plokščių (CMYK, White, Primer) generavimo
variklis su SMask tiesioginiu ištraukimu ir precizišku Thinning / Thickening valdymu.
"""

import os
import io
import time
import numpy as np
from PIL import Image, ImageFilter
import pymupdf


def extract_pdf_data(file_path: str):
    """
    Nuskaito PDF failą. Jei faile yra integruotas SMask (Podbase standartas),
    ištraukia jį akimirksniu (~0.2s). Jei ne - naudoja 300 DPI rastravimą.
    Grąžina: (w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask)
    """
    doc = pymupdf.open(file_path)
    page = doc[0]
    rect = page.rect
    w_pt, h_pt = rect.width, rect.height

    # Tikriname ar yra integruotas SMask
    smask_xref = None
    for img_info in page.get_images():
        if img_info[1] > 0:
            smask_xref = img_info[1]
            break

    if smask_xref:
        smask_dict = doc.extract_image(smask_xref)
        smask_img = Image.open(io.BytesIO(smask_dict['image']))
        mask_arr = np.array(smask_img)
        mask_bool = mask_arr > 128
        h_px, w_px = mask_bool.shape

        # Greita sumažinta peržiūra (max 800px)
        scale = min(800.0 / w_px, 800.0 / h_px, 1.0)
        t_w, t_h = int(w_px * scale), int(h_px * scale)
        mat = pymupdf.Matrix(t_w / rect.width, t_h / rect.height)
        thumb_pix = page.get_pixmap(matrix=mat)
        thumb_rgb = Image.frombytes("RGB", [thumb_pix.width, thumb_pix.height], thumb_pix.samples)
        thumb_mask = Image.fromarray(mask_bool).resize((t_w, t_h), Image.Resampling.NEAREST)
        doc.close()
        return w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, np.array(thumb_mask)
    else:
        # Fallback: 300 DPI rastravimas
        dpi = 300
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=True)
        img_data = pix.samples
        w_px, h_px = pix.width, pix.height
        arr = np.frombuffer(img_data, dtype=np.uint8).reshape((h_px, w_px, 4))
        mask_bool = arr[..., 3] > 10

        scale = min(800.0 / w_px, 800.0 / h_px, 1.0)
        t_w, t_h = int(w_px * scale), int(h_px * scale)
        mat_thumb = pymupdf.Matrix(t_w / rect.width, t_h / rect.height)
        thumb_pix = page.get_pixmap(matrix=mat_thumb, alpha=False)
        thumb_rgb = Image.frombytes("RGB", [thumb_pix.width, thumb_pix.height], thumb_pix.samples)
        thumb_mask = Image.fromarray(mask_bool).resize((t_w, t_h), Image.Resampling.NEAREST)
        doc.close()
        return w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, np.array(thumb_mask)


def compute_mask_choke_spread(mask: np.ndarray, pixels: int) -> np.ndarray:
    """
    Taikoma kaukei:
    - pixels > 0: Thinning (Choke / erozija) – sutraukia kaukę, kad balta/gruntas neišlįstų po CMYK.
    - pixels < 0: Thickening (Spread / plėtimas) – išpučia kaukę.
    - pixels == 0: Originalas be pakeitimų.
    Greita C lygio operacija per Pillow MinFilter / MaxFilter.
    """
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


def export_production_plates(
    source_pdf_path: str,
    job_name: str,
    output_dir: str,
    layers: list,
    choke_white_px: int = 1,
    choke_primer_px: int = 0
) -> dict:
    """
    Sugeneruoja paruoštas spaudos plokštes (PDF 1.4 suderinamas su RasterLink 7).
    Grąžina žodyną: {"CMYK": kelias, "White": kelias, "Primer": kelias}
    """
    os.makedirs(output_dir, exist_ok=True)
    generated = {}

    w_pt, h_pt, w_px, h_px, mask_bool, _, _ = extract_pdf_data(source_pdf_path)

    # 1. CMYK plokštė
    if "CMYK" in layers:
        cmyk_path = os.path.join(output_dir, f"{job_name}_Plate_1_CMYK.pdf")
        doc_src = pymupdf.open(source_pdf_path)
        doc_src.save(cmyk_path, deflate=True)
        doc_src.close()
        generated["CMYK"] = cmyk_path

    # 2. White plokštė (su Choke/Spread nustatymu)
    if "White" in layers:
        processed_white = compute_mask_choke_spread(mask_bool, choke_white_px)
        white_mono = np.full((h_px, w_px), 255, dtype=np.uint8)
        white_mono[processed_white] = 0  # Black (0) = 100% White Ink Mimaki spausdintuve

        white_doc = pymupdf.open()
        white_page = white_doc.new_page(width=w_pt, height=h_pt)

        white_img = Image.fromarray(white_mono, mode='L')
        buf = io.BytesIO()
        white_img.save(buf, format='PNG', optimize=False)
        white_page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), stream=buf.getvalue())

        white_path = os.path.join(output_dir, f"{job_name}_Plate_2_White.pdf")
        white_doc.save(white_path, deflate=True)
        white_doc.close()
        generated["White"] = white_path

    # 3. Primer plokštė (su Choke/Spread nustatymu)
    if "Primer" in layers:
        processed_primer = compute_mask_choke_spread(mask_bool, choke_primer_px)
        primer_mono = np.full((h_px, w_px), 255, dtype=np.uint8)
        primer_mono[processed_primer] = 0  # Black (0) = 100% Primer

        primer_doc = pymupdf.open()
        primer_page = primer_doc.new_page(width=w_pt, height=h_pt)

        primer_img = Image.fromarray(primer_mono, mode='L')
        buf_p = io.BytesIO()
        primer_img.save(buf_p, format='PNG', optimize=False)
        primer_page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), stream=buf_p.getvalue())

        primer_path = os.path.join(output_dir, f"{job_name}_Plate_3_Primer.pdf")
        primer_doc.save(primer_path, deflate=True)
        primer_doc.close()
        generated["Primer"] = primer_path

    return generated
