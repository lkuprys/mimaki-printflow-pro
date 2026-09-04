import os
import io
import time
import base64
import numpy as np
from PIL import Image
import pymupdf


def compute_choke(mask_bool: np.ndarray, p: int = 1) -> np.ndarray:
    """Greitas 1-20 px kaukės sutraukimas (erosion) baltam rašalui ir gruntui."""
    if p <= 0:
        return mask_bool
    h, w = mask_bool.shape
    if h <= 2 * p or w <= 2 * p:
        return mask_bool
    eroded = np.zeros_like(mask_bool)
    eroded[p:-p, p:-p] = (
        mask_bool[p:-p, p:-p] &
        mask_bool[:-p*2, p:-p] &
        mask_bool[p*2:, p:-p] &
        mask_bool[p:-p, :-p*2] &
        mask_bool[p:-p, p*2:]
    )
    return eroded


def extract_pdf_data(file_path: str):
    """
    Nuskaito PDF failą. Jei faile yra integruotas SMask (kaip Podbase failuose),
    ištraukia jį akimirksniu (per ~0.2s). Jei ne - naudoja 300 DPI rastravimą.
    Grąžina: (w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask)
    """
    doc = pymupdf.open(file_path)
    page = doc[0]
    rect = page.rect
    w_pt, h_pt = rect.width, rect.height

    # Tikriname ar yra SMask (Podbase standartas)
    smask_xref = None
    for img_info in page.get_images():
        if img_info[1] > 0:  # smask xref exists
            smask_xref = img_info[1]
            break

    if smask_xref:
        smask_dict = doc.extract_image(smask_xref)
        smask_img = Image.open(io.BytesIO(smask_dict['image']))
        mask_arr = np.array(smask_img)
        mask_bool = mask_arr > 128
        h_px, w_px = mask_bool.shape
        
        # Sukuriame greita sumazinta perziura (Thumbnail) UI rodymui (max 1000px)
        scale = min(1000.0 / w_px, 1000.0 / h_px, 1.0)
        t_w, t_h = int(w_px * scale), int(h_px * scale)
        mat = pymupdf.Matrix(scale * (w_px / (w_pt / 72.0 * 72.0)), scale * (h_px / (h_pt / 72.0 * 72.0)))
        # arba paprasciau: pixmap is page with scale based on rect
        mat = pymupdf.Matrix(t_w / rect.width, t_h / rect.height)
        thumb_pix = page.get_pixmap(matrix=mat)
        thumb_rgb = Image.frombytes("RGB", [thumb_pix.width, thumb_pix.height], thumb_pix.samples)
        thumb_mask = np.array(smask_img.resize((thumb_pix.width, thumb_pix.height), Image.Resampling.NEAREST)) > 128
    else:
        # Standartinis PDF be atskiro smask
        pix = page.get_pixmap(dpi=300)
        img_rgb = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        arr = np.array(img_rgb)
        mask_bool = (arr[..., 0] < 245) | (arr[..., 1] < 245) | (arr[..., 2] < 245)
        h_px, w_px = mask_bool.shape
        
        scale = min(1000.0 / w_px, 1000.0 / h_px, 1.0)
        t_w, t_h = int(w_px * scale), int(h_px * scale)
        thumb_rgb = img_rgb.resize((t_w, t_h), Image.Resampling.BILINEAR)
        thumb_mask = np.array(Image.fromarray(mask_bool).resize((t_w, t_h), Image.Resampling.NEAREST))

    doc.close()
    return w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask


def generate_web_previews(thumb_rgb: Image.Image, thumb_mask: np.ndarray, choke_px: int = 1):
    """Sugeneruoja lengvus Base64 peržiūros paveikslėlius vartotojo sąsajai."""
    w, h = thumb_rgb.size
    arr = np.array(thumb_rgb)
    choked_mask = compute_choke(thumb_mask, choke_px)

    def to_b64(pil_img, fmt="JPEG", quality=85):
        buf = io.BytesIO()
        pil_img.save(buf, format=fmt, quality=quality)
        return "data:image/" + fmt.lower() + ";base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    # 1. Composite RGBA (ant skaidraus tamsaus fono)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = arr
    rgba[..., 3] = np.where(thumb_mask, 255, 0)
    img_comp = Image.fromarray(rgba, mode="RGBA")
    comp_b64 = to_b64(img_comp, fmt="PNG")

    # 2. CMYK
    cmyk_b64 = to_b64(thumb_rgb, fmt="JPEG", quality=80)

    # 3. White (cianu pažymėtas padas)
    w_vis = np.zeros((h, w, 4), dtype=np.uint8)
    w_vis[choked_mask] = [56, 189, 248, 230]  # Cyan UV white atvaizdavimui
    img_white = Image.fromarray(w_vis, mode="RGBA")
    white_b64 = to_b64(img_white, fmt="PNG")

    # 4. Primer (gintarinis padas)
    p_vis = np.zeros((h, w, 4), dtype=np.uint8)
    p_vis[thumb_mask] = [251, 191, 36, 230]  # Amber Primer atvaizdavimui
    img_primer = Image.fromarray(p_vis, mode="RGBA")
    primer_b64 = to_b64(img_primer, fmt="PNG")

    return {
        "composite": comp_b64,
        "cmyk": cmyk_b64,
        "white": white_b64,
        "primer": primer_b64,
        "width_px": w,
        "height_px": h
    }


def generate_preview_files(thumb_rgb: Image.Image, thumb_mask: np.ndarray, output_dir: str, choke_px: int = 1) -> dict:
    """Išsaugo sumažintus peržiūros failus į diską ir grąžina tiesioginius file:/// kelius QML Image komponentui."""
    os.makedirs(output_dir, exist_ok=True)
    w, h = thumb_rgb.size
    arr = np.array(thumb_rgb)
    choked_mask = compute_choke(thumb_mask, choke_px)
    ts = int(time.time() * 1000)

    # 1. Composite (RGBA)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = arr
    rgba[..., 3] = np.where(thumb_mask, 255, 0)
    comp_img = Image.fromarray(rgba, mode="RGBA")
    comp_path = os.path.join(output_dir, f"preview_comp_{ts}.png")
    comp_img.save(comp_path, format="PNG")

    # 2. CMYK
    cmyk_path = os.path.join(output_dir, f"preview_cmyk_{ts}.jpg")
    thumb_rgb.save(cmyk_path, format="JPEG", quality=85)

    # 3. White
    w_vis = np.zeros((h, w, 4), dtype=np.uint8)
    w_vis[choked_mask] = [56, 189, 248, 230]
    white_img = Image.fromarray(w_vis, mode="RGBA")
    white_path = os.path.join(output_dir, f"preview_white_{ts}.png")
    white_img.save(white_path, format="PNG")

    # 4. Primer
    p_vis = np.zeros((h, w, 4), dtype=np.uint8)
    p_vis[thumb_mask] = [251, 191, 36, 230]
    primer_img = Image.fromarray(p_vis, mode="RGBA")
    primer_path = os.path.join(output_dir, f"preview_primer_{ts}.png")
    primer_img.save(primer_path, format="PNG")

    return {
        "composite": "file:///" + comp_path.replace("\\", "/"),
        "cmyk": "file:///" + cmyk_path.replace("\\", "/"),
        "white": "file:///" + white_path.replace("\\", "/"),
        "primer": "file:///" + primer_path.replace("\\", "/"),
        "width_px": w,
        "height_px": h
    }


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

    # 2. White plokštė (su Choke sutraukimu)
    if "White" in layers:
        choked_white = compute_choke(mask_bool, choke_white_px)
        white_mono = np.full((h_px, w_px), 255, dtype=np.uint8)
        white_mono[choked_white] = 0  # Black (0) = 100% White Ink

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

    # 3. Primer plokštė (grunto kaukė)
    if "Primer" in layers:
        choked_primer = compute_choke(mask_bool, choke_primer_px)
        primer_mono = np.full((h_px, w_px), 255, dtype=np.uint8)
        primer_mono[choked_primer] = 0  # Black (0) = 100% Primer

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


# =========================================================================
# Backward Compatibility Wrappers
# =========================================================================
def extract_image_and_mask(file_path: str, dpi: int = 300):
    w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask = extract_pdf_data(file_path)
    return thumb_rgb, thumb_mask, w_pt, h_pt


def generate_previews(img_rgb, is_graphic, choke_pixels: int = 1):
    return generate_web_previews(img_rgb, is_graphic, choke_px=choke_pixels)


def export_job_plates(job_id: str, test_pdf: str, product: dict, temp_dir: str):
    layers = product.get("layers", ["CMYK"])
    choke_w = product.get("choke_pixels", product.get("choke_white_px", 1))
    choke_p = product.get("choke_primer_px", 0)
    return export_production_plates(test_pdf, job_id, temp_dir, layers, choke_w, choke_p)
