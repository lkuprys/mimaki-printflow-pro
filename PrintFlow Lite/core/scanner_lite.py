"""
Scanner Lite Engine
-------------------
Tinklo serverio ir vietinių aplankų skenavimo variklis.
Palaiko griežtą datų filtravimą (pagal nutylėjimą tik šiandienos data ir naujesnės),
greitą produktų atpažinimą pagal kelio hierarchiją ir BID/PID metaduomenų ištraukimą.

Tinklo atsparumas:
- `path_exists_with_timeout` – SMB kelio patikra su laiko limitu (nepasiekiamas serveris
  Windows sistemoje gali „kabėti“ 20–60 s).
- os.walk klaidos (atjungtas tinklas, teisės) nebėra tyliai praryjamos – grąžinamos per `errors`.
- Failai, kurie dar kopijuojami į serverį (per nauji / keičiasi dydis), praleidžiami iki kito ciklo.
"""

import os
import re
import time
import threading
from datetime import datetime
from typing import List, Dict, Optional

DATE_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")
IGNORED_NAME_PARTS = ("_Plate_", "_preview_", ".tmp", ".part")


def clean_str(s: str) -> str:
    """Išvalo eilutę palikdamas tik mažąsias raides ir skaičius."""
    return "".join(c for c in s.lower() if c.isalnum())


def is_valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def path_exists_with_timeout(path: str, timeout_sec: float = 8.0) -> Optional[bool]:
    """
    os.path.exists su laiko limitu. Grąžina True/False, arba None jei patikra užstrigo
    (serveris neatsako). Naudojama daemon gija – užstrigusi gija neblokuoja programos uždarymo.
    """
    if not path:
        return False
    result = {}

    def _probe():
        try:
            result["ok"] = os.path.isdir(path)
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        return None
    return result.get("ok", False)


def extract_order_meta(file_path: str, root_dir: str) -> Dict[str, str]:
    """
    Išskleidžia gamybinius metaduomenis (BID, PID, data, subaplankas)
    iš failo kelio ir pavadinimo.
    Pvz.: '\\\\192.168.1.143\\podbase-hotfolder\\BENDRAS_PODBASE_HOTFOLDER\\2026-09-05\\105\\magnetic-wallet\\file.pdf'
    """
    filename = os.path.basename(file_path)
    try:
        rel_path = os.path.relpath(file_path, root_dir)
        rel_dir = os.path.dirname(rel_path)
    except Exception:
        rel_path = filename
        rel_dir = ""

    # Metaduomenys ieškomi tik santykiniame kelyje (šaknies pavadinimas jų neiškraipo)
    search_in = rel_path if rel_path and not rel_path.startswith("..") else file_path

    # BID paieška: 'bid-10507', 'bid_10507', 'bid10507', arba skaičius kelyje (pvz., /105/ arba /98/)
    bid_match = re.search(r"bid[-_]?(\d+)", search_in, re.IGNORECASE)
    if bid_match:
        bid = bid_match.group(1)
    else:
        parts = os.path.normpath(search_in).split(os.sep)
        num_parts = [p for p in parts[:-1] if p.isdigit() and len(p) <= 6]
        bid = num_parts[-1] if num_parts else ""

    # PID paieška: 'pid-123', 'pid_123', 'pid123'
    pid_match = re.search(r"pid[-_]?(\d+)", search_in, re.IGNORECASE)
    pid = pid_match.group(1) if pid_match else ""

    # Datos paieška kelyje (YYYY-MM-DD arba YYYY_MM_DD)
    order_date = ""
    for m in re.finditer(r"(\d{4}[-_]\d{2}[-_]\d{2})", search_in):
        cand = m.group(1).replace("_", "-")
        if is_valid_date(cand):
            order_date = cand
            break

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


def _short_kw_regex(kw: str):
    # Trumpas akronimas turi būti atskiras žodis: 'RH' tinka 'RH_123', 'case-rh.pdf',
    # bet NE 'shirt.pdf' ar 'accessory.pdf'.
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(kw)}(?![A-Za-z0-9])", re.IGNORECASE)


def match_product(filename: str, file_path: str, products: List[Dict], root_dir: str = "") -> Optional[Dict]:
    """
    Atpažįsta produktą pagal aplankų kelyje pavadinimus ir patį failą.
    Jei tinka keli produktai – laimi ilgiausias (konkrečiausias) raktažodis,
    pvz. 'clear-cases-v1' laimi prieš bendresnį 'clear-cases'.
    Paieška vyksta tik santykiniame kelyje nuo serverio šaknies.
    """
    rel = file_path
    if root_dir:
        try:
            r = os.path.relpath(file_path, root_dir)
            if not r.startswith(".."):
                rel = r
        except Exception:
            pass

    path_parts = os.path.normpath(rel).split(os.sep)
    folder_parts = path_parts[:-1] if len(path_parts) > 1 else []
    fname_clean = clean_str(filename)
    cleaned_folders = [clean_str(p) for p in folder_parts]
    rel_clean = clean_str(rel)
    stem = os.path.splitext(filename)[0]

    best = None  # (keyword_score, product_index, product, kw)
    for idx, p in enumerate(products):
        kws = p.get("keywords", [])
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]

        for kw in kws:
            kw_clean = clean_str(kw)
            if not kw_clean:
                continue

            matched = False
            if len(kw_clean) < 3:
                rx = _short_kw_regex(kw.strip())
                if rx.search(stem) or any(rx.search(part) for part in folder_parts):
                    matched = True
            else:
                if any(kw_clean in cf for cf in cleaned_folders):
                    matched = True
                elif kw_clean in fname_clean:
                    matched = True
                elif kw_clean in rel_clean:
                    matched = True

            if matched:
                score = len(kw_clean)
                if best is None or score > best[0] or (score == best[0] and idx < best[1]):
                    best = (score, idx, p, kw)

    if best is None:
        return None
    res = dict(best[2])
    res["matched_keyword"] = best[3]
    return res


def _is_file_stable(path: str, min_age_sec: float) -> bool:
    """Failas laikomas pilnai įkeltu, jei jo neliesta bent min_age_sec ir jis netuščias."""
    if min_age_sec <= 0:
        return True
    try:
        st = os.stat(path)
    except OSError:
        return False
    if st.st_size == 0:
        return False
    return (time.time() - st.st_mtime) >= min_age_sec


def scan_server_directory(
    root_dir: str,
    products: List[Dict],
    filter_mode: str = "today_only",
    target_date: str = "",
    max_files: int = 1000,
    min_file_age_sec: float = 0.0,
    errors: Optional[List[str]] = None,
    skipped_unstable: Optional[List[str]] = None,
    should_continue=None,
) -> List[Dict]:
    """
    Greitai ir optimizuotai skenuoja nurodytą serverio aplanką.
    Optimizacija tinklui (SMB):
    Jei šakniniame aplanke yra datų katalogai (pvz., '2026-09-05'),
    senesni nei target_date katalogai net NĖRA atveriami, taupant tinklo srautą.
    Datos filtras taikomas ir failo lygiu (jei data yra gilesniame kelyje).
    """
    def err(msg):
        if errors is not None:
            errors.append(msg)

    if not os.path.isdir(root_dir):
        err(f"Aplankas nepasiekiamas: {root_dir}")
        return []

    if not target_date or not is_valid_date(target_date):
        target_date = datetime.now().strftime("%Y-%m-%d")

    found_jobs = []

    # 1. Tikriname tiesioginius šaknies pakatalogius (ar tai datų aplankai)
    try:
        with os.scandir(root_dir) as it:
            top_entries = list(it)
    except Exception as e:
        err(f"Nepavyko perskaityti '{root_dir}': {e}")
        return []

    def _is_dir(entry) -> bool:
        try:
            return entry.is_dir()
        except OSError:
            return False

    date_dirs = [e for e in top_entries if _is_dir(e) and DATE_DIR_RE.match(e.name)]

    if date_dirs:
        # Eina tik per leidžiamus datų aplankus!
        target_dirs = sorted(
            e.path for e in date_dirs if is_date_matching(e.name, filter_mode, target_date)
        )
    else:
        target_dirs = [root_dir]

    def _onerror(exc):
        err(f"Klaida skaitant aplanką: {exc}")

    for scan_root in target_dirs:
        for current_root, dirs, files in os.walk(scan_root, onerror=_onerror):
            if should_continue is not None and not should_continue():
                return found_jobs
            dirs.sort()
            for fname in sorted(files):
                if not fname.lower().endswith(".pdf"):
                    continue

                # Ignoruojame laikinus ar jau sugeneruotus plokščių failus
                if any(x in fname for x in IGNORED_NAME_PARTS) or fname.startswith(("~", ".")):
                    continue

                full_path = os.path.join(current_root, fname)
                prod = match_product(fname, full_path, products, root_dir)
                if not prod:
                    continue

                meta = extract_order_meta(full_path, root_dir)
                if meta["order_date"] and not is_date_matching(meta["order_date"], filter_mode, target_date):
                    continue

                if not _is_file_stable(full_path, min_file_age_sec):
                    if skipped_unstable is not None:
                        skipped_unstable.append(full_path)
                    continue

                meta["product"] = prod
                found_jobs.append(meta)

                if len(found_jobs) >= max_files:
                    err(f"Pasiekta failų riba ({max_files}) – likę bus apdoroti kitame cikle")
                    return found_jobs

    return found_jobs
