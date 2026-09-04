import os
import json
import shutil
import time
from typing import Dict, List, Optional


class HotFolderRouter:
    def __init__(self, config_path: str = "printflow/config/presets.json"):
        self.config_path = config_path
        self.presets = self.load_presets()
        self.base_root = self.presets.get("base_hotfolder_root", "C:/PrintFlow/HotFolders")
        self.init_all_hotfolders()

    def load_presets(self) -> dict:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"base_hotfolder_root": "C:/PrintFlow/HotFolders", "products": []}

    def save_presets(self, data: dict):
        self.presets = data
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.init_all_hotfolders()

    def get_products(self) -> List[dict]:
        return self.presets.get("products", [])

    def get_product_by_id(self, product_id: str) -> Optional[dict]:
        for p in self.get_products():
            if p["id"] == product_id:
                return p
        return None

    def init_all_hotfolders(self):
        """Uztikrina, kad visi Hot Folderiai egzistuotu diske."""
        os.makedirs(self.base_root, exist_ok=True)
        for product in self.get_products():
            subpath = product.get("hotfolder_subpath", product["id"])
            product_root = os.path.join(self.base_root, subpath)
            os.makedirs(product_root, exist_ok=True)
            
            for layer in product.get("layers", []):
                layer_folder = os.path.join(product_root, layer)
                os.makedirs(layer_folder, exist_ok=True)

    def dispatch_plates(self, job_id: str, product_config: dict, plate_files: Dict[str, str]) -> List[dict]:
        """Nukopijuoja sugeneruotas plokstes i atitinkamus Hot Folderius."""
        subpath = product_config.get("hotfolder_subpath", product_config["id"])
        product_root = os.path.join(self.base_root, subpath)
        
        dispatched = []
        for layer_name, file_path in plate_files.items():
            target_dir = os.path.join(product_root, layer_name)
            os.makedirs(target_dir, exist_ok=True)
            
            target_file_name = f"{job_id}_{layer_name}.pdf"
            target_file_path = os.path.join(target_dir, target_file_name)
            
            # Nukopijuojame i Hot Folder
            shutil.copy2(file_path, target_file_path)
            
            dispatched.append({
                "layer": layer_name,
                "source": file_path,
                "destination": target_file_path,
                "timestamp": time.time()
            })
            print(f"[ROUTER] Nukopijuota: {layer_name} -> {target_file_path}")
            
        return dispatched
