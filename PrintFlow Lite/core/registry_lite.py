"""
Registry Lite Engine
--------------------
Ilgalaikė užsakymų atmintis (jobs_registry.json).
Užtikrina, kad joks failas ar užsakymas nebūtų generuojamas ar keliamas pakartotinai,
net jei programa paleidžiama iš naujo ar įvyksta sistemos perkrovimas.
"""

import os
import json
import time
import threading
from typing import Dict, List, Optional


class JobRegistryLite:
    def __init__(self, registry_file: str = "jobs_registry.json"):
        self.registry_file = registry_file
        self._lock = threading.Lock()
        self.jobs: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        try:
            temp_file = self.registry_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.jobs, f, indent=2, ensure_ascii=False)
            if os.path.exists(self.registry_file):
                try:
                    os.remove(self.registry_file)
                except Exception:
                    pass
            os.replace(temp_file, self.registry_file)
        except Exception:
            pass

    def is_file_processed(self, file_path: str) -> bool:
        """
        Patikrina ar failas jau yra apdorotas arba šiuo metu apdorojamas.
        Tikrina pagal normalizuotą failo kelią arba failo vardą.
        """
        norm = os.path.normpath(file_path).lower()
        fname = os.path.basename(file_path).lower()

        with self._lock:
            for j in self.jobs.values():
                j_path = os.path.normpath(j.get("filepath", "")).lower()
                j_fname = os.path.basename(j.get("filepath", "")).lower()

                if j_path == norm or (fname and j_fname == fname):
                    status = j.get("status", "")
                    if status in ["dispatched", "processing", "completed"]:
                        return True
        return False

    def register_or_update(self, job_id: str, data: dict):
        with self._lock:
            if job_id not in self.jobs:
                self.jobs[job_id] = {
                    "job_id": job_id,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            self.jobs[job_id].update(data)
            self.jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save()

    def set_status(self, job_id: str, status: str, message: str = ""):
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = status
                self.jobs[job_id]["message"] = message
                self.jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._save()

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            return self.jobs.get(job_id)

    def get_all_jobs(self) -> List[dict]:
        with self._lock:
            # Grąžiname surūšiuotus nuo naujausio link seniausio
            items = list(self.jobs.values())
            items.sort(key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True)
            return items

    def clear(self):
        with self._lock:
            self.jobs.clear()
            self._save()
