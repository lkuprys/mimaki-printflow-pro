"""
Rėmų ribų šablono papildymas
----------------------------
Uždeda naują kontūrų sluoksnį (pvz. ringholder apskritimus) ant esamo rėmų ribų šablono:
    python tools/merge_frame_layout.py assets/presets/WALLETGRIP.pdf naujas_layout.pdf

Abu PDF turi būti to paties dydžio Photoshop eksportai: vienas paveikslėlis per visą lapą su
permatomumu (SMask). Rezultatas įrašomas į pirmą failą: keičiami tik paveikslėlio pikseliai,
lapo dydis, spalvų erdvė (DeviceRGB) ir raiška lieka tokie patys.
"""

import argparse
import io
import os
import sys

import numpy as np
import pymupdf
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.size_fix import _page_image, _write_stream  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _load(doc) -> tuple:
    """(xref, smask, RGB float 0..1, alfa float 0..1) – pilkas paveikslėlis paverčiamas RGB."""
    page = doc[0]
    xref, smask, err = _page_image(doc, page)
    if err:
        raise SystemExit(f"Netinkamas failas: {err}")
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.n not in (1, 3):
        raise SystemExit("Paveikslėlis turi būti RGB arba pilkas")
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * pix.n]
    arr = arr.reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        arr = np.repeat(arr, 3, axis=2)
    sm = Image.open(io.BytesIO(doc.extract_image(smask)["image"])).convert("L")
    if sm.size != (pix.width, pix.height):
        sm = sm.resize((pix.width, pix.height), Image.Resampling.BILINEAR)
    return xref, smask, arr.astype(np.float32) / 255.0, np.asarray(sm, np.float32) / 255.0


def merge(base_pdf: str, overlay_pdf: str, out_pdf: str) -> None:
    base, over = pymupdf.open(base_pdf), pymupdf.open(overlay_pdf)
    try:
        if [round(v, 1) for v in base[0].rect] != [round(v, 1) for v in over[0].rect]:
            raise SystemExit(f"Skiriasi lapų dydžiai: {base[0].rect} ir {over[0].rect}")
        bx, bs, bc, ba = _load(base)
        _, _, oc, oa = _load(over)
        if bc.shape != oc.shape:
            raise SystemExit(f"Skiriasi raiška: {bc.shape[1]}x{bc.shape[0]} ir {oc.shape[1]}x{oc.shape[0]} px")
        # Standartinis „over“ sudėjimas: naujas sluoksnis viršuje
        a = oa + ba * (1.0 - oa)
        safe = np.where(a > 0, a, 1.0)[..., None]
        c = (oc * oa[..., None] + bc * (ba * (1.0 - oa))[..., None]) / safe
        c = np.where(a[..., None] > 0, c, 1.0)  # visiškai permatomose vietose – balta, kaip originale
        h, w = a.shape
        rgb = np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)
        alpha = np.clip(np.rint(a * 255), 0, 255).astype(np.uint8)
        _write_stream(base, bx, rgb.tobytes(), w, h)
        _write_stream(base, bs, alpha.tobytes(), w, h)
        tmp = out_pdf + ".part"
        base.save(tmp, garbage=3, deflate=True)
    finally:
        base.close()
        over.close()
    os.replace(tmp, out_pdf)


def main() -> int:
    ap = argparse.ArgumentParser(description="Uždeda naują kontūrų sluoksnį ant rėmų ribų šablono")
    ap.add_argument("base", help="esamas šablonas (bus perrašytas, jei nenurodytas --out)")
    ap.add_argument("overlay", help="naujas sluoksnis (to paties dydžio PDF)")
    ap.add_argument("--out", help="kur įrašyti rezultatą")
    args = ap.parse_args()
    out = args.out or args.base
    merge(args.base, args.overlay, out)
    print(f"Sujungta: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
