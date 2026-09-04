import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional


class JobRegistry:
    """
    Nuolatinis gamybinių užduočių registras (JSON pagrindu).
    Saugo informaciją apie paruoštus darbus, atskirtas plokštes ir spaudos būsenas.
    """

    def __init__(self, registry_file: Optional[str] = None):
        self._lock = threading.Lock()
        if registry_file:
            self.registry_file = os.path.abspath(registry_file)
        else:
            # Pagal nutylėjimą saugoma šalia konfigūracijos
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.registry_file = os.path.join(base_dir, "printflow", "config", "job_registry.json")

        os.makedirs(os.path.dirname(self.registry_file), exist_ok=True)
        self.jobs: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Klaida skaitant registrą: {e}")
        return {}

    def _save(self):
        try:
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(self.jobs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Klaida saugant registrą: {e}")

    def get_job(self, job_name: str) -> Optional[dict]:
        with self._lock:
            return self.jobs.get(job_name)

    def is_file_processed(self, file_path: str) -> bool:
        """Patikrina ar šis failas jau buvo apdorotas arba yra apdorojamas (užkerta kelią begaliniam ciklui)."""
        abs_p = os.path.abspath(file_path).lower()
        with self._lock:
            for j in self.jobs.values():
                if os.path.abspath(j.get("file_path", "")).lower() == abs_p:
                    if j.get("status") in ["ready_to_print", "printed", "composited", "processing", "error", "hotfoldered"]:
                        return True
        return False

    def register_or_update(self, job_name: str, data: dict):
        with self._lock:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if job_name not in self.jobs:
                self.jobs[job_name] = {
                    "job_name": job_name,
                    "created_at": now,
                    "updated_at": now,
                    "status": "pending"
                }
            self.jobs[job_name].update(data)
            self.jobs[job_name]["updated_at"] = now
            self._save()

    def set_status(self, job_name: str, status: str, message: str = ""):
        with self._lock:
            if job_name in self.jobs:
                self.jobs[job_name]["status"] = status
                if message:
                    self.jobs[job_name]["message"] = message
                self.jobs[job_name]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save()

    def get_all_jobs(self) -> List[dict]:
        with self._lock:
            # Rūšiuojame pagal atnaujinimo laiką mažėjančia tvarka
            items = list(self.jobs.values())
            items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return items

    def get_ready_jobs(self) -> List[dict]:
        """Grąžina visus darbus, kurie paruošti spaudai (kompozicija atlikta)."""
        with self._lock:
            items = [j for j in self.jobs.values() if j.get("status") in ["ready_to_print", "composited"]]
            items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return items

    def clear_finished(self):
        """Išvalo atspausdintus darbus iš aktyvaus sąrašo."""
        with self._lock:
            self.jobs = {k: v for k, v in self.jobs.items() if v.get("status") != "printed"}
            self._save()
