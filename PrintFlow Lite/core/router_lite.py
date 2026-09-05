"""
Router Lite Engine
------------------
Saugus, atominis sugeneruotų spaudos plokščių perkėlimas į Mimaki Hot Folderius.
Užkerta kelią failų „prasimetimui“ ar sugadinimui per .tmp ➔ .pdf pervardinimo mechanizmą.
Palaiko vartotojo nustatytą kėlimo eiliškumą ir pauzę tarp sluoksnių.
"""

import os
import shutil
import time
from typing import Dict, List, Optional, Callable


class HotFolderRouterLite:
    def __init__(self, default_delay_sec: float = 0.5):
        self.default_delay_sec = default_delay_sec

    def dispatch_plates(
        self,
        job_name: str,
        plate_files: Dict[str, str],
        product_config: Dict,
        dispatch_order: Optional[List[str]] = None,
        inter_layer_delay_sec: Optional[float] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> List[Dict]:
        """
        Perkelia sugeneruotas plokštes į produkto Hot Folderius.
        
        Saugumo principas (Atominis įrašymas):
        1. Failas nukopijuojamas kaip .tmp
        2. Užbaigus kopijavimą, failas akimirksniu pervardinamas į .pdf
        3. RasterLink mato tik pilną, paruoštą failą.
        
        Eiliškumas:
        Pagal dispatch_order (pvz. Primer ➔ White ➔ CMYK) su nustatyta pauze tarp jų.
        """
        def log(msg):
            if log_cb:
                log_cb(msg)

        if inter_layer_delay_sec is None:
            inter_layer_delay_sec = self.default_delay_sec

        hotfolders = product_config.get("hotfolders", {})

        # Nustatome kėlimo seką
        order = dispatch_order or product_config.get("dispatch_order") or ["Primer", "White", "CMYK"]
        # Užtikriname, kad visi esami sluoksniai būtų sekoje
        for l in plate_files.keys():
            if l not in order:
                order.append(l)

        dispatched = []

        for idx, layer_name in enumerate(order):
            if layer_name not in plate_files:
                continue

            src_path = plate_files[layer_name]
            if not os.path.exists(src_path):
                log(f"⚠️ Nerastas plokštės failas: {src_path}")
                continue

            target_folder = hotfolders.get(layer_name)
            if not target_folder:
                # Jei šiam sluoksniui nėra nurodyto hotfolderio (pvz., Primer produkte išjungtas)
                continue

            try:
                os.makedirs(target_folder, exist_ok=True)
            except Exception as e:
                log(f"❌ Nepavyko pasiekti/sukurti Hotfolderio '{target_folder}': {e}")
                continue

            # Failo pavadinimas Hotfolderyje
            dest_filename_pdf = f"{job_name}_{layer_name}.pdf"
            dest_path_pdf = os.path.join(target_folder, dest_filename_pdf)
            dest_path_tmp = os.path.join(target_folder, f"{job_name}_{layer_name}.tmp")

            try:
                # 1. Atominis kopijavimas per .tmp
                shutil.copy2(src_path, dest_path_tmp)
                # 2. Pervardinimas į .pdf (atominė operacija tame pačiame diske)
                if os.path.exists(dest_path_pdf):
                    try:
                        os.remove(dest_path_pdf)
                    except Exception:
                        pass
                os.replace(dest_path_tmp, dest_path_pdf)

                log(f"   [+] [{idx+1}/{len(order)}] '{layer_name}' sėkmingai įkeltas į: {target_folder}")

                dispatched.append({
                    "layer": layer_name,
                    "target_path": dest_path_pdf,
                    "target_folder": target_folder,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })

                # Pauzė tarp sluoksnių, kad RasterLink ramiai spėtų sukurti eilutę sąraše
                if inter_layer_delay_sec > 0 and idx < len(order) - 1:
                    time.sleep(inter_layer_delay_sec)

            except Exception as e:
                log(f"❌ Klaida keliant '{layer_name}' į Hotfolderį: {e}")
                if os.path.exists(dest_path_tmp):
                    try:
                        os.remove(dest_path_tmp)
                    except Exception:
                        pass

        return dispatched
