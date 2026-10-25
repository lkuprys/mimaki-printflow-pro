"""
Rėmų ribos
----------
Paspaudus „Rėmų ribos“, į CMYK HotFolderį įkeliamas kontūrų lapas (assets/presets/WALLETGRIP.pdf),
kurį RasterLink atspausdina ant rėmo – pagal jį sudedami GRIP / WALLET gaminiai.
Windows faile negali būti „/“, todėl varde naudojamas jam vizualiai identiškas pilno pločio
pasvirasis brūkšnys „／“ (yra ir Shift-JIS lentelėje – RasterLink jį rodo kaip įprastą simbolį).
"""

import os
from typing import Dict, List, Optional

import pymupdf

DEFAULT_NAME = "GRIP／WALLET remas"   # „GRIP／WALLET remas“
PDF_TITLE = "GRIP/WALLET remas"
_WIN_FORBIDDEN = '<>:"/\\|?*'


class FrameGuideError(Exception):
    pass


def safe_file_name(name: str) -> str:
    """Windows draudžiamus simbolius pakeičia; „/“ ➔ „／“, kad RasterLink'e atrodytų taip pat."""
    out = name.strip().replace("/", "／")
    out = "".join("-" if c in _WIN_FORBIDDEN or ord(c) < 32 else c for c in out).rstrip(". ")
    return out or DEFAULT_NAME


def pick_hotfolder(products: List[Dict], configured: str = "") -> str:
    """Nustatymuose nurodytas ➔ Magnetic Wallet / Grip produkto CMYK ➔ bet kurio produkto CMYK."""
    if configured:
        return configured
    ordered = sorted(products, key=lambda p: 0 if any(
        k in (p.get("id", "") + " " + p.get("name", "")).lower() for k in ("wallet", "grip")) else 1)
    for p in ordered:
        hf = (p.get("hotfolders") or {}).get("CMYK") or ""
        if hf:
            return hf
    return ""


def send_frame_guide(src_pdf: str, hotfolder: str, name: str = DEFAULT_NAME) -> str:
    """Įkelia lapą į HotFolderį atomiškai (.tmp ➔ .pdf). Grąžina galutinį kelią."""
    if not os.path.isfile(src_pdf):
        raise FrameGuideError(f"Nerastas rėmų ribų failas: {src_pdf}")
    if not hotfolder:
        raise FrameGuideError("Nenurodytas CMYK HotFolderis (Produktai → Magnetic Wallet → CMYK)")
    if not os.path.isdir(hotfolder):
        raise FrameGuideError(f"CMYK HotFolderis nepasiekiamas: {hotfolder}")
    dst = os.path.join(hotfolder, safe_file_name(name) + ".pdf")
    if os.path.exists(dst):
        raise FrameGuideError("Rėmų ribos jau laukia HotFolderyje – RasterLink jų dar nepaėmė")
    tmp = os.path.splitext(dst)[0] + ".tmp"  # kaip router_lite: RasterLink .tmp failų neima
    doc: Optional[pymupdf.Document] = None
    try:
        doc = pymupdf.open(src_pdf)
        meta = dict(doc.metadata or {})
        meta["title"] = PDF_TITLE
        doc.set_metadata(meta)
        doc.save(tmp, garbage=0, deflate=False)
        doc.close()
        doc = None
        os.replace(tmp, dst)
    finally:
        if doc is not None:
            doc.close()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return dst
