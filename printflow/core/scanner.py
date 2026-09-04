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


def match_product(filename: str, file_path: str, products: List[Dict]) -> Optional[Dict]:
    """
    Lanksčiai nustato produktą pagal raktažodžius failo pavadinime arba kelyje.
    """
    fname_clean = clean_str(filename)
    path_clean = clean_str(file_path)

    for p in products:
        kw = p.get("keyword", "").strip()
        if not kw:
            continue
        kw_clean = clean_str(kw)
        if kw_clean in fname_clean or kw_clean in path_clean:
            return p

    return None


def scan_inbox_recursive(
    inbox_dir: str,
    products: List[Dict],
    max_files: int = 500
) -> List[Dict]:
    """
    Rekursyviai skenuoja visą nurodytą gaunamų failų medį (Inbox),
    randa visus .pdf failus, priskiria produktą ir išskiria metaduomenis.
    """
    if not inbox_dir or not os.path.exists(inbox_dir):
        return []

    found_files = []

    try:
        for root, dirs, files in os.walk(inbox_dir):
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
