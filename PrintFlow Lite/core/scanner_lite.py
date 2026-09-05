"""
Scanner Lite Engine
-------------------
Tinklo serverio ir vietinių aplankų skenavimo variklis.
Palaiko griežtą datų filtravimą (pagal nutylėjimą tik šiandienos data ir naujesnės),
greitą produktų atpažinimą pagal kelio hierarchiją ir BID/PID metaduomenų ištraukimą.
"""

import os
import re
from datetime import datetime
from typing import List, Dict, Optional


def clean_str(s: str) -> str:
    """Išvalo eilutę palikdamas tik mažąsias raides ir skaičius."""
    return "".join(c for c in s.lower() if c.isalnum())


def extract_order_meta(file_path: str, root_dir: str) -> Dict[str, str]:
    """
    Išskleidžia gamybinius metaduomenis (BID, PID, data, subaplankas)
    iš failo kelio ir pavadinimo.
    Pvz.: '\\192.168.1.143\podbase-hotfolder\BENDRAS_PODBASE_HOTFOLDER\2026-09-05\105\magnetic-wallet\file.pdf'
    """
    filename = os.path.basename(file_path)
    try:
        rel_path = os.path.relpath(file_path, root_dir)
        rel_dir = os.path.dirname(rel_path)
    except Exception:
        rel_path = filename
        rel_dir = ""

    # BID paieška: 'bid-10507', 'bid_10507', 'bid10507', arba skaičius kelyje (pvz., /105/ arba /98/)
    bid_match = re.search(r"bid[-_]?(\d+)", file_path, re.IGNORECASE)
    if bid_match:
        bid = bid_match.group(1)
    else:
        # Tikriname ar kuris nors aplankas kelyje yra grynai skaičius (pvz., '105' arba '98')
        norm = os.path.normpath(file_path)
        parts = norm.split(os.sep)
        num_parts = [p for p in parts[:-1] if p.isdigit() and len(p) <= 6]
        bid = num_parts[-1] if num_parts else ""

    # PID paieška: 'pid-123', 'pid_123', 'pid123'
    pid_match = re.search(r"pid[-_]?(\d+)", file_path, re.IGNORECASE)
    pid = pid_match.group(1) if pid_match else ""

    # Datos paieška kelyje (YYYY-MM-DD arba YYYY_MM_DD)
    date_match = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", file_path)
    order_date = date_match.group(1).replace("_", "-") if date_match else ""

    base_name = os.path.splitext(filename)[0]

    return {
        "bid": bid,
        "pid": pid,
        "order_date": order_date,
        "rel_dir": rel_dir if rel_dir and rel_dir != "." else "Šakninis",
        "job_name": base_name,
        "filename": filename,
        "filepath": file_path
    }


def is_date_matching(folder_date: str, filter_mode: str, target_date: str) -> bool:
    """
    Patikrina ar rastas datos aplankas atitinka filtrą.
    """
    if not folder_date or not target_date:
        return True
    if filter_mode == "today_only":
        return folder_date == target_date
    elif filter_mode == "today_and_newer":
        return folder_date >= target_date
    elif filter_mode == "all":
        return True
    return folder_date >= target_date


def match_product(filename: str, file_path: str, products: List[Dict]) -> Optional[Dict]:
    """
    Atpažįsta produktą pagal aplankų kelyje pavadinimus ir patį failą.
    """
    fname_clean = clean_str(filename)
    norm_path = os.path.normpath(file_path)
    path_parts = norm_path.split(os.sep)
    folder_parts = path_parts[:-1] if len(path_parts) > 1 else []
    cleaned_folders = [clean_str(p) for p in folder_parts]
    full_path_clean = clean_str(file_path)

    for p in products:
        kws = p.get("keywords", [])
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]

        for kw in kws:
            kw_clean = clean_str(kw)
            if not kw_clean:
                continue

            matched = False
            # Trumpiems akronimams (< 3 raidės, pvz., 'cc', 'rh', 'mw')
            if len(kw_clean) < 3:
                pattern = rf"(?i)(?:|_|-|^){re.escape(kw)}(?:|_|-|$)"
                if re.search(pattern, filename) or any(re.search(pattern, part) for part in folder_parts):
                    matched = True
            else:
                # 1. Aplanko pavadinimas
                if any(kw_clean in cf for cf in cleaned_folders):
                    matched = True
                # 2. Failo pavadinimas
                elif kw_clean in fname_clean:
                    matched = True
                # 3. Pilnas kelias
                elif kw_clean in full_path_clean:
                    matched = True

            if matched:
                res = dict(p)
                res["matched_keyword"] = kw
                return res

    return None


def scan_server_directory(
    root_dir: str,
    products: List[Dict],
    filter_mode: str = "today_only",
    target_date: str = "",
    max_files: int = 1000
) -> List[Dict]:
    """
    Greitai ir optimizuotai skenuoja nurodytą serverio aplanką.
    Optimizacija tinklui (SMB):
    Jei šakniniame aplanke yra datų katalogai (pvz., '2026-09-05'),
    senesni nei target_date katalogai net NĖRA atveriami, taupant tinklo srautą.
    """
    if not os.path.exists(root_dir):
        return []

    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    found_jobs = []

    # 1. Tikriname tiesioginius šaknies pakatalogius (ar tai datų aplankai)
    try:
        top_entries = list(os.scandir(root_dir))
    except Exception:
        return []

    has_date_subdirs = any(
        e.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", e.name) for e in top_entries
    )

    if has_date_subdirs:
        # Eina tik per leidžiamus datų aplankus!
        target_dirs = []
        for e in top_entries:
            if e.is_dir():
                d_match = re.match(r"^(\d{4}-\d{2}-\d{2})$", e.name)
                if d_match:
                    d_str = d_match.group(1)
                    if is_date_matching(d_str, filter_mode, target_date):
                        target_dirs.append(e.path)
    else:
        target_dirs = [root_dir]

    for scan_root in target_dirs:
        for current_root, dirs, files in os.walk(scan_root):
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue

                # Ignoruojame laikinus ar jau sugeneruotus plokščių failus
                if any(x in fname for x in ["_Plate_", "_preview_", ".tmp"]):
                    continue

                full_path = os.path.join(current_root, fname)
                prod = match_product(fname, full_path, products)
                if prod:
                    meta = extract_order_meta(full_path, root_dir)
                    meta["product"] = prod
                    found_jobs.append(meta)

                    if len(found_jobs) >= max_files:
                        return found_jobs

    return found_jobs
