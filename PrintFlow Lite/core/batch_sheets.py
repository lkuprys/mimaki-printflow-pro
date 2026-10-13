"""
Batch sheet lapai
-----------------
Šalia užsakymo PDF serveryje generuojami lapai su modeliais, kuriuos reikia sudėti į stalą:
    312-bid-26506-Clear Cases Magsafe V2.pdf
    312-bid-26506-Clear Cases Magsafe V2_batch_sheet_1.png
    312-bid-26506-Clear Cases Magsafe V2_batch_sheet_2.png ...
Modulis juos randa ir atomiškai nukopijuoja į vietinę talpyklą.
"""

import os
import re
import shutil
from typing import List

SHEET_RE = re.compile(r"^(?P<stem>.+)_batch_sheet_(?P<n>\d+)\.(png|jpe?g)$", re.IGNORECASE)


def find_batch_sheets(pdf_path: str) -> List[str]:
    """Grąžina to paties užsakymo batch sheet lapus (surikiuotus 1, 2, 3 …). Klaidos ➔ tuščias sąrašas."""
    folder = os.path.dirname(pdf_path)
    stem = os.path.splitext(os.path.basename(pdf_path))[0].lower()
    found = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                m = SHEET_RE.match(e.name)
                if m and m.group("stem").lower() == stem and e.is_file():
                    found.append((int(m.group("n")), e.path))
    except OSError:
        return []
    return [p for _, p in sorted(found)]


def copy_batch_sheets(sources: List[str], dest_dir: str) -> List[str]:
    """Kopijuoja per .part ➔ galutinis vardas (nepilnų paveikslėlių nebūna). Grąžina vietinius kelius."""
    os.makedirs(dest_dir, exist_ok=True)
    out = []
    for src in sources:
        dst = os.path.join(dest_dir, os.path.basename(src))
        tmp = dst + ".part"
        try:
            shutil.copyfile(src, tmp)
            if os.path.getsize(tmp) != os.path.getsize(src):
                raise IOError("nepilna kopija")
            os.replace(tmp, dst)
            out.append(dst)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return out
