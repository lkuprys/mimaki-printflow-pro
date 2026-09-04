import os
import re
from datetime import datetime
from typing import List, Dict, Optional


def clean_str(s: str) -> str:
    """Išvalo eilutę palikdamas tik raides ir skaičius palyginimui."""
    return "".join(c for c in s.lower() if c.isalnum())


def extract_order_meta(file_path: str, root_dir: str) -> Dict[str, str]:
    """
    Išskleidžia gamybinius metaduomenis (BID, PID, data, subaplankas)
    iš failo kelio ir pavadinimo.
    Pvz.: '2026-09-04/gen1/bid10507_pid12/98-bid-10507-MagSafe Ring Holders.pdf'
    """
    filename = os.path.basename(file_path)
    rel_path = os.path.relpath(file_path, root_dir)
    rel_dir = os.path.dirname(rel_path)

    # BID paieška: 'bid-10507', 'bid_10507', 'bid10507'
    bid_match = re.search(r"bid[-_]?(\d+)", file_path, re.IGNORECASE)
    bid = bid_match.group(1) if bid_match else ""

    # PID paieška: 'pid-123', 'pid_123', 'pid123'
    pid_match = re.search(r"pid[-_]?(\d+)", file_path, re.IGNORECASE)
    pid = pid_match.group(1) if pid_match else ""

    # Datos paieška kelyje (YYYY-MM-DD arba YYYY_MM_DD)
    date_match = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", file_path)
    order_date = date_match.group(1).replace("_", "-") if date_match else ""

    # Švarus darbo bazinis pavadinimas
    base_name = os.path.splitext(filename)[0]

    return {
        "bid": bid,
        "pid": pid,
        "order_date": order_date,
        "rel_dir": rel_dir if rel_dir and rel_dir != "." else "Šakninis",
        "job_name": base_name
    }


def extract_product_keywords(prod: Dict) -> List[str]:
    """
    Išskleidžia visus raktažodžius iš produkto apibrėžimo.
    Palaiko tiek 'keywords' sąrašą, tiek 'keyword' kableliais atskirtą eilutę.
    """
    kws = []
    # 1. Jei yra 'keywords' sąrašas
    prod_kws = prod.get("keywords")
    if isinstance(prod_kws, list):
        for k in prod_kws:
            if isinstance(k, str) and k.strip():
                kws.append(k.strip())
    elif isinstance(prod_kws, str) and prod_kws.strip():
        for k in prod_kws.split(","):
            if k.strip():
                kws.append(k.strip())

    # 2. Jei yra 'keyword' eilutė (suderinamumui)
    kw_str = prod.get("keyword", "")
    if isinstance(kw_str, str) and kw_str.strip():
        for k in kw_str.split(","):
            k_clean = k.strip()
            if k_clean and k_clean not in kws:
                kws.append(k_clean)

    return kws


def match_product(filename: str, file_path: str, products: List[Dict]) -> Optional[Dict]:
    """
    Lanksčiai ir tiksliai nustato produktą pagal raktažodžius:
    tikrina tiek aplankų kelyje pavadinimus (folder names), tiek patį failo vardą.
    Kiekvienas produktas gali turėti kelis raktažodžius (folderių pavadinimus).
    Grąžina: suderintą produkto kopiją su 'matched_keyword' lauku arba None.
    """
    fname_clean = clean_str(filename)
    norm_path = os.path.normpath(file_path)
    path_parts = norm_path.split(os.sep)
    # Aplankų pavadinimai be paties failo
    folder_parts = path_parts[:-1] if len(path_parts) > 1 else []
    cleaned_folders = [clean_str(part) for part in folder_parts]
    full_path_clean = clean_str(file_path)

    for p in products:
        keywords = extract_product_keywords(p)
        for kw in keywords:
            kw_clean = clean_str(kw)
            if not kw_clean:
                continue

            matched = False
            # Trumpiems akronimams (< 3 simboliai, pvz., 'rh', 'cc') reikalaujame žodžio ribų
            if len(kw_clean) < 3:
                pattern = rf"(?i)(?:\b|_|-|^){re.escape(kw)}(?:\b|_|-|$)"
                if re.search(pattern, filename) or any(re.search(pattern, part) for part in folder_parts):
                    matched = True
            else:
                # 1. Tikriname ar atitinka kurį nors aplanko pavadinimą
                if any(kw_clean in cf for cf in cleaned_folders):
                    matched = True
                # 2. Tikriname ar atitinka failo pavadinimą
                elif kw_clean in fname_clean:
                    matched = True
                # 3. Tikriname pilną kelią
                elif kw_clean in full_path_clean:
                    matched = True

            if matched:
                res = dict(p)
                res["matched_keyword"] = kw
                return res

    return None


def scan_inbox_recursive(
    inbox_dir: str,
    products: List[Dict],
    folder_filter_keywords: Optional[List[str]] = None,
    max_files: int = 500
) -> List[Dict]:
    """
    Rekursyviai skenuoja visą nurodytą gaunamų failų medį (Inbox),
    randa visus .pdf failus, priskiria produktą pagal kelis folderių/failų raktažodžius,
    ir pagal pasirinkimą filtruoja pagal folderių paieškos filtrus.
    """
    if not inbox_dir or not os.path.exists(inbox_dir):
        return []

    # Paruošiame katalogų filtrus, jei nurodyti
    clean_filters = []
    if folder_filter_keywords:
        for f in folder_filter_keywords:
            if isinstance(f, str) and f.strip():
                clean_filters.append(clean_str(f.strip()))

    found_files = []

    try:
        for root, dirs, files in os.walk(inbox_dir):
            rel_dir_from_root = os.path.relpath(root, inbox_dir)
            rel_dir_clean = clean_str(rel_dir_from_root)

            # Jei nurodyti katalogų filtrai, tikriname ar einamasis katalogas atitinka
            if clean_filters and rel_dir_from_root != ".":
                if not any(kf in rel_dir_clean for kf in clean_filters):
                    continue

            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                
                # Ignoruojame laikinus ar sistemos failus
                if fname.startswith((".", "~$", "_")):
                    continue

                full_path = os.path.join(root, fname)
                try:
                    stat = os.stat(full_path)
                except OSError:
                    continue

                size_mb = stat.st_size / (1024 * 1024)
                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                meta = extract_order_meta(full_path, inbox_dir)
                matched_prod = match_product(fname, full_path, products)

                found_files.append({
                    "filename": fname,
                    "filepath": full_path,
                    "rel_dir": meta["rel_dir"],
                    "bid": meta["bid"],
                    "pid": meta["pid"],
                    "order_date": meta["order_date"],
                    "job_name": meta["job_name"],
                    "size_mb": round(size_mb, 2),
                    "modified": mod_time,
                    "mtime_ts": stat.st_mtime,
                    "matched_product_id": matched_prod["id"] if matched_prod else "",
                    "matched_product_name": matched_prod["name"] if matched_prod else "",
                    "matched_keyword": matched_prod.get("matched_keyword", "") if matched_prod else "",
                    "layers": matched_prod.get("layers", ["CMYK"]) if matched_prod else []
                })

                if len(found_files) >= max_files:
                    break
            if len(found_files) >= max_files:
                break
    except Exception as e:
        print(f"Klaida skenuojant Inbox: {e}")

    # Rūšiuojame: naujausi modifikuoti failai viršuje
    found_files.sort(key=lambda x: x["mtime_ts"], reverse=True)
    return found_files
