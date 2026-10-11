"""
Registry Lite Engine
--------------------
Ilgalaikė užsakymų atmintis (jobs_registry.json).
Užtikrina, kad joks failas ar užsakymas nebūtų generuojamas ar keliamas pakartotinai,
net jei programa paleidžiama iš naujo ar įvyksta sistemos perkrovimas.

Saugumas:
- Įrašymas atominis: .tmp ➔ fsync ➔ os.replace (failas niekada nebūna pusiau įrašytas).
- Prieš kiekvieną įrašymą paliekama atsarginė kopija (.bak).
- Sugadintas JSON niekada nėra tyliai „išvalomas“ (tai sukeltų masinį pakartotinį kėlimą):
  bandoma .bak kopija, o sugadintas failas išsaugomas kaip .corrupt-<laikas>.
- Visos operacijos apsaugotos threading.RLock (saugu lygiagrečioms gijoms).
"""

import os
import json
import time
import shutil
import threading
from typing import Dict, List, Optional

# Būsenos, kurių failai daugiau automatiškai neapdorojami
FINAL_STATUSES = ("dispatched", "processing", "completed", "failed", "dispatch_failed", "interrupted")


class JobRegistryLite:
    def __init__(self, registry_file: str = "jobs_registry.json"):
        self.registry_file = registry_file
        self._lock = threading.RLock()
        self.last_error: str = ""
        self.load_warnings: List[str] = []
        self.jobs: Dict[str, dict] = self._load()

    # -----------------------------------------------------------------
    # Įkėlimas / įrašymas
    # -----------------------------------------------------------------
    @staticmethod
    def _read_json(path: str) -> Dict[str, dict]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("registry turinys nėra JSON objektas")
        return data

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(self.registry_file):
            return {}
        try:
            return self._read_json(self.registry_file)
        except Exception as e:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            corrupt_copy = f"{self.registry_file}.corrupt-{stamp}"
            try:
                shutil.copy2(self.registry_file, corrupt_copy)
            except Exception:
                corrupt_copy = "(nepavyko nukopijuoti)"
            self.load_warnings.append(
                f"Atmintis '{self.registry_file}' sugadinta ({e}). Kopija: {corrupt_copy}"
            )
            bak = self.registry_file + ".bak"
            if os.path.exists(bak):
                try:
                    data = self._read_json(bak)
                    self.load_warnings.append(f"Atmintis atkurta iš atsarginės kopijos: {bak}")
                    return data
                except Exception as e2:
                    self.load_warnings.append(f"Atsarginė kopija taip pat sugadinta: {e2}")
            return {}

    def _save(self) -> bool:
        """Atominis įrašymas. Kviečiamas tik laikant self._lock."""
        temp_file = f"{self.registry_file}.{os.getpid()}.tmp"
        try:
            folder = os.path.dirname(self.registry_file)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.jobs, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            if os.path.exists(self.registry_file):
                try:
                    shutil.copyfile(self.registry_file, self.registry_file + ".bak")
                except Exception:
                    pass  # .bak tik papildoma apsauga

            # Windows: failą trumpam gali laikyti antivirusinė / indeksavimas – bandome kelis kartus
            last_exc = None
            for attempt in range(5):
                try:
                    os.replace(temp_file, self.registry_file)
                    self.last_error = ""
                    return True
                except PermissionError as e:
                    last_exc = e
                    time.sleep(0.1 * (attempt + 1))
            raise last_exc
        except Exception as e:
            self.last_error = f"Nepavyko įrašyti atminties '{self.registry_file}': {e}"
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            return False

    # -----------------------------------------------------------------
    # Užklausos
    # -----------------------------------------------------------------
    def is_file_processed(self, file_path: str) -> bool:
        """
        Patikrina ar failas jau yra apdorotas, apdorojamas arba galutinai atmestas.
        Tikrina pagal normalizuotą failo kelią arba failo vardą (apsauga nuo dublikatų,
        kai tas pats failas nukopijuojamas į kelis serverio aplankus).
        """
        norm = os.path.normcase(os.path.normpath(file_path))
        fname = os.path.basename(file_path).lower()

        with self._lock:
            for j in self.jobs.values():
                if j.get("source") == "brokas":
                    continue  # brokai sekami atskirai (is_fingerprint_processed)
                j_fp = j.get("filepath", "")
                if not j_fp:
                    continue
                j_path = os.path.normcase(os.path.normpath(j_fp))
                j_fname = os.path.basename(j_fp).lower()
                if j_path == norm or (fname and j_fname == fname):
                    if j.get("status", "") in FINAL_STATUSES:
                        return True
        return False

    def is_fingerprint_processed(self, fingerprint: str) -> bool:
        """Brokams: ar būtent šis failas (kelias + dydis + laikas) jau apdorotas."""
        if not fingerprint:
            return False
        with self._lock:
            return any(j.get("fingerprint") == fingerprint and j.get("status", "") in FINAL_STATUSES
                       for j in self.jobs.values())

    def register_or_update(self, job_id: str, data: dict) -> bool:
        with self._lock:
            if job_id not in self.jobs:
                self.jobs[job_id] = {
                    "job_id": job_id,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            self.jobs[job_id].update(data)
            self.jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return self._save()

    def set_status(self, job_id: str, status: str, message: str = "") -> bool:
        """Nustato būseną. Jei įrašo dar nėra – jį sukuria (klaida niekada nepradingsta tyliai)."""
        return self.register_or_update(job_id, {"status": status, "message": message})

    def record_failure(self, job_id: str, data: dict, message: str, max_attempts: int = 3) -> str:
        """
        Užregistruoja klaidą ir padidina bandymų skaitiklį.
        Pasiekus max_attempts būsena tampa 'failed' (daugiau automatiškai nebandoma).
        Grąžina naują būseną.
        """
        with self._lock:
            attempts = int(self.jobs.get(job_id, {}).get("attempts", 0)) + 1
            status = "failed" if attempts >= max_attempts else "error"
            payload = dict(data)
            payload.update({"status": status, "message": message, "attempts": attempts})
            self.register_or_update(job_id, payload)
            return status

    def reset_job(self, job_id: str) -> bool:
        """Leidžia operatoriui rankiniu būdu pakartoti užsakymą."""
        with self._lock:
            if job_id not in self.jobs:
                return False
            self.jobs[job_id]["status"] = "retry"
            self.jobs[job_id]["attempts"] = 0
            self.jobs[job_id]["message"] = "Pažymėta pakartojimui"
            self.jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return self._save()

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self.jobs.get(job_id)
            return json.loads(json.dumps(job)) if job is not None else None

    def get_all_jobs(self) -> List[dict]:
        with self._lock:
            items = [dict(j) for j in self.jobs.values()]
        # Surūšiuoti nuo naujausio link seniausio
        items.sort(key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True)
        return items

    def clear(self) -> bool:
        with self._lock:
            self.jobs.clear()
            return self._save()

    def mark_interrupted(self) -> List[str]:
        """
        Paleidimo metu: užsakymai, likę 'processing' būsenoje (programa nutraukta / kompiuteris
        išsijungė), pažymimi 'interrupted'. Jie automatiškai nekartojami (dalis sluoksnių galėjo
        jau būti RasterLink'e) – operatorius sprendžia rankiniu būdu.
        """
        changed = []
        with self._lock:
            for jid, j in self.jobs.items():
                if j.get("status") == "processing":
                    j["status"] = "interrupted"
                    j["message"] = "Programa nutraukta apdorojimo metu"
                    j["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    changed.append(jid)
            if changed:
                self._save()
        return changed

    def delete_job(self, job_id: str) -> bool:
        """Pašalina vieną įrašą (failas vėl bus laikomas nauju)."""
        with self._lock:
            if job_id not in self.jobs:
                return False
            del self.jobs[job_id]
            return self._save()
