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

DEFAULT_ORDER = ["Primer", "White", "CMYK"]


class HotFolderRouterLite:
    def __init__(self, default_delay_sec: float = 0.5, create_missing_hotfolders: bool = False):
        self.default_delay_sec = default_delay_sec
        # Pagal nutylėjimą hotfolderiai NEKURIAMI: jei kelyje klaida (pvz. rašybos),
        # failai būtų tyliai numesti į aplanką, kurio RasterLink nestebi.
        self.create_missing_hotfolders = create_missing_hotfolders

    @staticmethod
    def expected_layers(plate_files: Dict[str, str], product_config: Dict) -> List[str]:
        """Sluoksniai, kuriems sugeneruota plokštė IR nurodytas hotfolderis."""
        hotfolders = product_config.get("hotfolders", {}) or {}
        return [l for l in plate_files if (hotfolders.get(l) or "").strip()]

    def dispatch_plates(
        self,
        job_name: str,
        plate_files: Dict[str, str],
        product_config: Dict,
        dispatch_order: Optional[List[str]] = None,
        inter_layer_delay_sec: Optional[float] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        wait_for_pickup: bool = False,
        pickup_timeout_sec: float = 60.0,
    ) -> List[Dict]:
        """
        Perkelia sugeneruotas plokštes į produkto Hot Folderius.

        Saugumo principas (Atominis įrašymas):
        1. Failas nukopijuojamas kaip .tmp (RasterLink .tmp failų neima)
        2. Patikrinamas nukopijuoto failo dydis
        3. Failas akimirksniu pervardinamas į .pdf (tame pačiame aplanke – atominė operacija)

        Eiliškumas:
        Pagal dispatch_order (pvz. Primer ➔ White ➔ CMYK) su nustatyta pauze tarp jų.
        wait_for_pickup=True: kita plokštė keliama tik kai RasterLink paėmė ankstesnę
        (failas dingo iš HotFolderio). Laukiama ir po paskutinės plokštės – kad kito
        užsakymo plokštės neatsirastų anksčiau, nei RasterLink paėmė šio užsakymo plokštes.
        Jei plokštė nepaimama per pickup_timeout_sec arba įkelti nepavyksta – likusios
        plokštės NEKELIAMOS (kitaip RasterLink gautų sluoksnius netinkama tvarka).
        Rezultatas: self.last_stop_reason (tuščias = viskas įkelta).
        """
        self.last_stop_reason = ""
        def log(msg):
            if log_cb:
                try:
                    log_cb(msg)
                except Exception:
                    pass

        if inter_layer_delay_sec is None:
            inter_layer_delay_sec = self.default_delay_sec
        try:
            inter_layer_delay_sec = max(0.0, float(inter_layer_delay_sec))
        except (TypeError, ValueError):
            inter_layer_delay_sec = self.default_delay_sec

        hotfolders = product_config.get("hotfolders", {}) or {}

        # Nustatome kėlimo seką (KOPIJA – nekeičiame konfigūracijos sąrašo!)
        order = list(dispatch_order or product_config.get("dispatch_order") or DEFAULT_ORDER)
        for l in plate_files.keys():
            if l not in order:
                order.append(l)

        # Tik realiai keliami sluoksniai (pauzė skaičiuojama tarp jų)
        to_send = []
        for layer_name in order:
            if layer_name not in plate_files or layer_name in to_send:
                continue
            target_folder = (hotfolders.get(layer_name) or "").strip()
            if not target_folder:
                log(f"   ℹ️ '{layer_name}' neturi nurodyto Hotfolderio – praleidžiama")
                continue
            to_send.append(layer_name)

        dispatched = []

        # Patikra PRIEŠ keliant: jei trūksta bent vieno failo ar HotFolderio – nekeliama nieko
        # (dalinis užsakymas RasterLink'e = sumaišyta sluoksnių seka).
        for layer_name in to_send:
            src_path = plate_files[layer_name]
            target_folder = hotfolders[layer_name].strip()
            problem = ""
            if not os.path.isfile(src_path):
                problem = f"Nerastas plokštės failas: {src_path}"
            elif not os.path.isdir(target_folder):
                if self.create_missing_hotfolders:
                    try:
                        os.makedirs(target_folder, exist_ok=True)
                    except Exception as e:
                        problem = f"Nepavyko sukurti Hotfolderio '{target_folder}': {e}"
                else:
                    problem = (f"Hotfolderis neegzistuoja / nepasiekiamas: '{target_folder}' "
                               f"(patikrinkite kelią ir ar RasterLink 7 įjungtas)")
            if problem:
                self.last_stop_reason = problem
                log(f"❌ {problem}")
                log(f"⛔ '{job_name}': nekeliama nė viena plokštė, kad RasterLink negautų dalies užsakymo.")
                return dispatched

        for idx, layer_name in enumerate(to_send):
            src_path = plate_files[layer_name]
            target_folder = hotfolders[layer_name].strip()

            dest_path_pdf = os.path.join(target_folder, f"{job_name}_{layer_name}.pdf")
            dest_path_tmp = os.path.join(target_folder, f"{job_name}_{layer_name}.tmp")

            try:
                # 1. Kopijavimas per .tmp
                shutil.copyfile(src_path, dest_path_tmp)
                # 2. Dydžio patikra (nepilnas įrašymas / pilnas diskas)
                src_size = os.path.getsize(src_path)
                tmp_size = os.path.getsize(dest_path_tmp)
                if src_size != tmp_size:
                    raise IOError(f"nukopijuota {tmp_size} B iš {src_size} B")
                # 3. Atominis pervardinimas (os.replace perrašo esamą failą ir Windows sistemoje)
                os.replace(dest_path_tmp, dest_path_pdf)

                log(f"   [+] [{idx+1}/{len(to_send)}] '{layer_name}' sėkmingai įkeltas į: {target_folder}")

                record = {
                    "layer": layer_name,
                    "target_path": dest_path_pdf,
                    "target_folder": target_folder,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                dispatched.append(record)

            except Exception as e:
                log(f"❌ Klaida keliant '{layer_name}' į Hotfolderį: {e}")
                if os.path.exists(dest_path_tmp):
                    try:
                        os.remove(dest_path_tmp)
                    except Exception:
                        pass
                rest = to_send[idx + 1:]
                self.last_stop_reason = f"Nepavyko įkelti '{layer_name}': {e}"
                if rest:
                    log(f"⛔ Likusios plokštės {rest} nekeliamos, kad nesusimaišytų sluoksnių tvarka.")
                break

            # Laukiama, kol RasterLink paims plokštę (failas dings iš HotFolderio)
            if wait_for_pickup:
                waited = self._wait_until_gone(dest_path_pdf, pickup_timeout_sec)
                if waited is None:
                    rest = to_send[idx + 1:]
                    self.last_stop_reason = (f"RasterLink nepaėmė '{layer_name}' per {pickup_timeout_sec:.0f} s "
                                             f"(ar RasterLink 7 įjungtas?)")
                    log(f"⛔ {self.last_stop_reason}." + (f" Likusios plokštės {rest} nekeliamos." if rest else ""))
                    record["picked_up"] = False
                    break
                record["picked_up"] = True
                record["pickup_sec"] = round(waited, 1)
                log(f"   ✔️ RasterLink paėmė '{layer_name}' per {waited:.1f} s")

            # Papildoma pauzė tarp sluoksnių, kad RasterLink ramiai spėtų sukurti eilutę sąraše
            if inter_layer_delay_sec > 0 and idx < len(to_send) - 1:
                self._sleep(inter_layer_delay_sec)

        return dispatched

    last_stop_reason = ""
    poll_interval_sec = 0.25

    @staticmethod
    def _sleep(sec: float):
        time.sleep(sec)

    def _wait_until_gone(self, path: str, timeout_sec: float) -> Optional[float]:
        """Grąžina laukimo trukmę sekundėmis arba None, jei failas neišnyko per timeout_sec."""
        t0 = time.monotonic()
        while True:
            try:
                exists = os.path.exists(path)
            except OSError:
                exists = True
            elapsed = time.monotonic() - t0
            if not exists:
                return elapsed
            if elapsed >= timeout_sec:
                return None
            self._sleep(self.poll_interval_sec)
