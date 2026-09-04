import os
import io
import zlib
import numpy as np
from PIL import Image
import pymupdf
from reportlab.pdfgen import canvas
from reportlab.lib.colors import CMYKColorSep, CMYKColor
import tifffile

OUTPUT_DIR = "mimaki_test_files"
os.makedirs(OUTPUT_DIR, exist_ok=True)
PLATES_DIR = os.path.join(OUTPUT_DIR, "individual_plates")
os.makedirs(PLATES_DIR, exist_ok=True)

# 1. Base Dimensions & Source Image
src_img = Image.open("extracted_img.png")
w_px, h_px = src_img.size # 2100, 1500
dpi = 300.0
w_pt = (w_px / dpi) * 72.0 # 504.0 pt
h_pt = (h_px / dpi) * 72.0 # 360.0 pt

arr = np.array(src_img)
# Graphic is dark pixels on white background
is_graphic = (arr[..., 0] < 128) | (arr[..., 1] < 128) | (arr[..., 2] < 128)

def compute_choke(mask: np.ndarray, p: int = 1) -> np.ndarray:
    if p <= 0:
        return mask
    h, w = mask.shape
    eroded = np.zeros_like(mask)
    eroded[p:-p, p:-p] = (
        mask[p:-p, p:-p] &
        mask[:-p*2, p:-p] &
        mask[p*2:, p:-p] &
        mask[p:-p, :-p*2] &
        mask[p:-p, p*2:]
    )
    return eroded

mask_exact = is_graphic
mask_choked = compute_choke(is_graphic, 1)

# Graphic bounding box
rows = np.any(is_graphic, axis=1)
cols = np.any(is_graphic, axis=0)
rmin, rmax = np.where(rows)[0][[0, -1]]
cmin, cmax = np.where(cols)[0][[0, -1]]

bbox_x_pt = (cmin / dpi) * 72.0
bbox_w_pt = ((cmax - cmin + 1) / dpi) * 72.0
bbox_y_pt = ((h_px - rmax - 1) / dpi) * 72.0
bbox_h_pt = ((rmax - rmin + 1) / dpi) * 72.0

# Assets
rgba_graphic = np.zeros((h_px, w_px, 4), dtype=np.uint8)
rgba_graphic[..., 0:3] = arr
rgba_graphic[..., 3] = (is_graphic * 255).astype(np.uint8)
rgba_img_path = os.path.join(OUTPUT_DIR, "_tmp_graphic_rgba.png")
Image.fromarray(rgba_graphic, mode='RGBA').save(rgba_img_path)

# Grayscale / Mono images (0 = 100% ink, 255 = 0% ink)
mono_white = np.full((h_px, w_px), 255, dtype=np.uint8)
mono_white[mask_choked] = 0
mono_white_path = os.path.join(OUTPUT_DIR, "_tmp_mono_white.png")
Image.fromarray(mono_white, mode='L').save(mono_white_path)

mono_primer = np.full((h_px, w_px), 255, dtype=np.uint8)
mono_primer[mask_exact] = 0
mono_primer_path = os.path.join(OUTPUT_DIR, "_tmp_mono_primer.png")
Image.fromarray(mono_primer, mode='L').save(mono_primer_path)

# -------------------------------------------------------------------------
# Group A: Vector Spot Color PDF
# -------------------------------------------------------------------------
def create_vector_spot_pdf(filename: str, white_spot_name: str, primer_spot_name: str, title: str = ""):
    filepath = os.path.join(OUTPUT_DIR, filename)
    c = canvas.Canvas(filepath, pagesize=(w_pt, h_pt))
    c.setTitle(title or filename)
    
    # 1. Primer Underbase (Bottom layer) - Spot Primer
    spot_primer = CMYKColorSep(1, 0, 0, 0, spotName=primer_spot_name, density=1.0)
    c.setFillOverprint(True)
    c.setFillColor(spot_primer)
    c.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    
    # 2. White Underbase (Middle layer) - Spot White
    spot_white = CMYKColorSep(0, 1, 0, 0, spotName=white_spot_name, density=1.0)
    c.setFillOverprint(True)
    c.setFillColor(spot_white)
    c.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    
    # 3. CMYK Artwork (Top layer)
    c.drawImage(rgba_img_path, 0, 0, width=w_pt, height=h_pt, mask='auto')
    c.save()
    print(f"Created Vector Spot PDF: {filename} (White='{white_spot_name}', Primer='{primer_spot_name}')")

# -------------------------------------------------------------------------
# Group B: Pixel-Exact Raster Spot Mask PDF
# -------------------------------------------------------------------------
def create_raster_mask_spot_pdf(filename: str, white_spot_name: str, primer_spot_name: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    # We construct a clean PDF with ReportLab that contains:
    # 1. Spot Primer Separation channel + Overprint
    # 2. Spot White Separation channel + Overprint
    # 3. CMYK Artwork
    c = canvas.Canvas(filepath, pagesize=(w_pt, h_pt))
    c.setTitle(filename)
    
    spot_primer = CMYKColorSep(1, 0, 0, 0, spotName=primer_spot_name, density=1.0)
    spot_white = CMYKColorSep(0, 1, 0, 0, spotName=white_spot_name, density=1.0)
    
    # Layer 1: Primer Mask Image with Spot Color
    c.setFillOverprint(True)
    c.setFillColor(spot_primer)
    # Drawing the mono primer mask
    c.drawImage(mono_primer_path, 0, 0, width=w_pt, height=h_pt)
    
    # Layer 2: White Mask Image with Spot Color
    c.setFillOverprint(True)
    c.setFillColor(spot_white)
    c.drawImage(mono_white_path, 0, 0, width=w_pt, height=h_pt)
    
    # Layer 3: CMYK Graphic Artwork
    c.drawImage(rgba_img_path, 0, 0, width=w_pt, height=h_pt, mask='auto')
    c.save()
    print(f"Created Pixel-Exact Raster Spot PDF: {filename} (White='{white_spot_name}', Primer='{primer_spot_name}')")

# -------------------------------------------------------------------------
# Group C: PDF with OCG (Interactive Acrobat / RIP Layers)
# -------------------------------------------------------------------------
def create_ocg_layers_pdf(filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    
    # Create OCGs (Layers)
    ocg_primer = doc.add_ocg("01_Primer_Base")
    ocg_white = doc.add_ocg("02_White_Underbase")
    ocg_cmyk = doc.add_ocg("03_CMYK_Artwork")
    
    # Draw Primer layer
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), filename=mono_primer_path, oc=ocg_primer)
    # Draw White layer
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), filename=mono_white_path, oc=ocg_white)
    # Draw CMYK layer
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), filename=rgba_img_path, oc=ocg_cmyk)
    
    doc.save(filepath)
    doc.close()
    print(f"Created OCG Layers PDF: {filename}")

# -------------------------------------------------------------------------
# Group D: Multi-Page Separation PDF
# -------------------------------------------------------------------------
def create_multipage_pdf(filename: str, with_spots: bool = False):
    filepath = os.path.join(OUTPUT_DIR, filename)
    c = canvas.Canvas(filepath, pagesize=(w_pt, h_pt))
    
    # Page 1: CMYK Full Color Artwork
    c.setTitle("Multi-Page Separation for RasterLink Layer Composition")
    c.drawImage(rgba_img_path, 0, 0, width=w_pt, height=h_pt, mask='auto')
    c.showPage()
    
    # Page 2: White Underbase Plate
    if with_spots:
        spot_white = CMYKColorSep(0, 1, 0, 0, spotName="RawWhite", density=1.0)
        c.setFillColor(spot_white)
        c.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    else:
        # Grayscale Mono Color image (Black = 100% ink)
        c.drawImage(mono_white_path, 0, 0, width=w_pt, height=h_pt)
    c.showPage()
    
    # Page 3: Primer Base Plate
    if with_spots:
        spot_primer = CMYKColorSep(1, 0, 0, 0, spotName="Primer", density=1.0)
        c.setFillColor(spot_primer)
        c.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    else:
        # Grayscale Mono Color image (Black = 100% ink)
        c.drawImage(mono_primer_path, 0, 0, width=w_pt, height=h_pt)
    c.showPage()
    
    c.save()
    print(f"Created Multi-Page PDF: {filename} (with_spots={with_spots})")

# -------------------------------------------------------------------------
# Group E: Individual Plate PDFs
# -------------------------------------------------------------------------
def create_individual_plates():
    # 1. Artwork CMYK
    c1 = canvas.Canvas(os.path.join(PLATES_DIR, "Plate_1_CMYK_Artwork.pdf"), pagesize=(w_pt, h_pt))
    c1.drawImage(rgba_img_path, 0, 0, width=w_pt, height=h_pt, mask='auto')
    c1.save()
    
    # 2. White Plate (Spot RawWhite)
    c2 = canvas.Canvas(os.path.join(PLATES_DIR, "Plate_2_Spot_RawWhite.pdf"), pagesize=(w_pt, h_pt))
    spot_w = CMYKColorSep(0, 1, 0, 0, spotName="RawWhite", density=1.0)
    c2.setFillColor(spot_w)
    c2.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    c2.save()
    
    # 3. Primer Plate (Spot Primer)
    c3 = canvas.Canvas(os.path.join(PLATES_DIR, "Plate_3_Spot_Primer.pdf"), pagesize=(w_pt, h_pt))
    spot_p = CMYKColorSep(1, 0, 0, 0, spotName="Primer", density=1.0)
    c3.setFillColor(spot_p)
    c3.rect(bbox_x_pt, bbox_y_pt, bbox_w_pt, bbox_h_pt, fill=1, stroke=0)
    c3.save()
    
    # 4. White Plate (Mono Color Grayscale)
    c4 = canvas.Canvas(os.path.join(PLATES_DIR, "Plate_2_Mono_White_Grayscale.pdf"), pagesize=(w_pt, h_pt))
    c4.drawImage(mono_white_path, 0, 0, width=w_pt, height=h_pt)
    c4.save()
    
    # 5. Primer Plate (Mono Color Grayscale)
    c5 = canvas.Canvas(os.path.join(PLATES_DIR, "Plate_3_Mono_Primer_Grayscale.pdf"), pagesize=(w_pt, h_pt))
    c5.drawImage(mono_primer_path, 0, 0, width=w_pt, height=h_pt)
    c5.save()
    print("Created Individual Plate PDFs in individual_plates/")

# -------------------------------------------------------------------------
# Group F: Multi-Channel TIFF
# -------------------------------------------------------------------------
def create_multichannel_tiff(filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    cmyk_arr = np.zeros((h_px, w_px, 4), dtype=np.uint8)
    cmyk_arr[mask_exact, 3] = 255 # 100% Black
    
    out_7ch = np.zeros((h_px, w_px, 7), dtype=np.uint8)
    out_7ch[..., 0:4] = cmyk_arr
    out_7ch[..., 4] = (mask_exact * 255).astype(np.uint8) # Alpha
    
    # White channel
    w_ch = np.full((h_px, w_px), 255, dtype=np.uint8)
    w_ch[mask_choked] = 0
    out_7ch[..., 5] = w_ch
    
    # Primer channel
    p_ch = np.full((h_px, w_px), 255, dtype=np.uint8)
    p_ch[mask_exact] = 0
    out_7ch[..., 6] = p_ch
    
    ink_names = "Cyan\x00Magenta\x00Yellow\x00Black\x00Transparency\x00W\x00Primer\x00"
    tags = [
        (332, 'H', 1, 1, True),
        (333, 's', 0, ink_names, True),
    ]
    
    tifffile.imwrite(
        filepath,
        out_7ch,
        photometric='separated',
        extrasamples=[1, 0, 0],
        byteorder='>',
        compression='lzw',
        resolution=(300, 300, 'inch'),
        extratags=tags
    )
    print(f"Created Multi-Channel 7Ch TIFF: {filename}")

# Clean up temp files when done
def cleanup_temps():
    for f in [rgba_img_path, mono_white_path, mono_primer_path, os.path.join(OUTPUT_DIR, "_tmp_mask_white.png"), os.path.join(OUTPUT_DIR, "_tmp_mask_primer.png")]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

# =========================================================================
# RUN GENERATION OF ALL SAMPLES
# =========================================================================
print("\n--- Generating Mimaki Sample Files ---")
# Group A: Vector Spot Color PDFs
create_vector_spot_pdf("01_Spot_RawWhite_RawPrimer_Vector.pdf", "RawWhite", "RawPrimer")
create_vector_spot_pdf("02_Spot_RawWhite_Primer_Vector.pdf", "RawWhite", "Primer")
create_vector_spot_pdf("03_Spot_White_Primer_Vector.pdf", "White", "Primer")
create_vector_spot_pdf("04_Spot_Spot1_Spot2_Vector.pdf", "Spot1", "Spot2")
create_vector_spot_pdf("05_Spot_RDG_White_Primer_Vector.pdf", "RDG_WHITE", "RDG_PRIMER")
create_vector_spot_pdf("06_Spot_MIMAKI_White_Primer_Vector.pdf", "MIMAKI_WHITE", "MIMAKI_PRIMER")
create_vector_spot_pdf("07_Spot_W_PR_Vector.pdf", "W", "PR")

# Group B: Raster Spot Mask PDFs
create_raster_mask_spot_pdf("08_RasterMask_RawWhite_Primer.pdf", "RawWhite", "Primer")
create_raster_mask_spot_pdf("09_RasterMask_White_Primer.pdf", "White", "Primer")

# Group C: OCG Layers PDF
create_ocg_layers_pdf("10_OCG_Layers_Acrobat.pdf")

# Group D: Multi-Page PDFs
create_multipage_pdf("11_MultiPage_Mono_Color_White_Primer.pdf", with_spots=False)
create_multipage_pdf("12_MultiPage_Spot_RawWhite_Primer.pdf", with_spots=True)

# Group E: Individual Plates
create_individual_plates()

# Group F: Multi-Channel TIFF
create_multichannel_tiff("13_MultiChannel_7Ch_TIFF_White_Primer.tif")

cleanup_temps()
print("\n--- All 13 Variations Generated Successfully! ---")
