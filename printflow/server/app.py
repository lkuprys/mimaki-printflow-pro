import os
import json
import shutil
import time
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from printflow.core.prepress import extract_pdf_data, generate_web_previews, export_production_plates

CONFIG_PATH = os.path.abspath("printflow/config/app_config.json")
TEMP_DIR = os.path.abspath("printflow/temp_cache")
os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI(title="Mimaki PrintFlow PRO Engine")

# WebSocket clients
connected_clients: List[WebSocket] = []
job_history: List[Dict] = []


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Default fallback
    return {
        "inbox_folder": "E:\\Projektai\\TEST\\INBOX_PRINT_FILES",
        "auto_process_inbox": false,
        "products": []
    }


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# Broadcast helper
async def broadcast_event(event_type: str, data: dict):
    for client in connected_clients:
        try:
            await client.send_json({"event": event_type, "data": data})
        except Exception:
            pass


@app.get("/api/config")
async def get_config():
    return load_config()


@app.post("/api/config")
async def update_config(new_config: dict):
    save_config(new_config)
    # Ensure inbox folder exists
    inbox = new_config.get("inbox_folder")
    if inbox:
        os.makedirs(inbox, exist_ok=True)
    return {"status": "ok", "message": "Konfiguracija sekmingai issaugota"}


@app.get("/api/inbox")
async def get_inbox_files():
    cfg = load_config()
    inbox = cfg.get("inbox_folder", "")
    files = []
    if os.path.exists(inbox):
        for entry in os.scandir(inbox):
            if entry.is_file() and entry.name.lower().endswith((".pdf", ".tif", ".tiff")):
                size_mb = entry.stat().st_size / (1024 * 1024)
                mod_time = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                # Auto-match product by flexible keyword
                matched_product_id = None
                fname_clean = "".join(c for c in entry.name.lower() if c.isalnum())
                for p in cfg.get("products", []):
                    kw = p.get("keyword", "")
                    if kw:
                        kw_clean = "".join(c for c in kw.lower() if c.isalnum())
                        if kw_clean in fname_clean:
                            matched_product_id = p["id"]
                            break
                        
                files.append({
                    "filename": entry.name,
                    "filepath": entry.path,
                    "size_mb": round(size_mb, 2),
                    "modified": mod_time,
                    "matched_product_id": matched_product_id
                })
    return {"inbox_folder": inbox, "files": sorted(files, key=lambda x: x["modified"], reverse=True)}


@app.post("/api/inspect")
async def inspect_file(
    file: Optional[UploadFile] = File(None),
    inbox_filename: Optional[str] = Form(None),
    choke_pixels: int = Form(1)
):
    t0 = time.time()
    cfg = load_config()

    if inbox_filename:
        file_path = os.path.join(cfg.get("inbox_folder", ""), inbox_filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Failas nerastas Inbox aplanke")
        temp_id = f"inbox_{int(time.time())}_{os.path.basename(file_path)}"
    elif file:
        temp_id = f"upload_{int(time.time())}_{file.filename}"
        file_path = os.path.join(TEMP_DIR, temp_id)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    else:
        raise HTTPException(status_code=400, detail="Nepateiktas failas")

    # Pre-press inspection
    w_pt, h_pt, w_px, h_px, mask_bool, thumb_rgb, thumb_mask = extract_pdf_data(file_path)
    previews = generate_web_previews(thumb_rgb, thumb_mask, choke_px=choke_pixels)

    w_mm = (w_pt / 72.0) * 25.4
    h_mm = (h_pt / 72.0) * 25.4

    return {
        "status": "ok",
        "temp_file_id": file_path,
        "filename": os.path.basename(file_path),
        "width_mm": round(w_mm, 1),
        "height_mm": round(h_mm, 1),
        "width_px": w_px,
        "height_px": h_px,
        "elapsed_ms": round((time.time() - t0) * 1000),
        "previews": previews
    }


@app.post("/api/dispatch")
async def dispatch_job(
    file_path: str = Form(...),
    product_id: str = Form(...),
    job_name: Optional[str] = Form(None),
    choke_white_override: Optional[int] = Form(None)
):
    t0 = time.time()
    cfg = load_config()
    
    # Find product
    product = next((p for p in cfg.get("products", []) if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=400, detail=f"Nerastas produktas su ID: {product_id}")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Gamybinis failas nerastas")

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    final_job_name = job_name.strip() if job_name else base_name

    choke_w = choke_white_override if choke_white_override is not None else product.get("choke_white_px", 1)
    choke_p = product.get("choke_primer_px", 0)
    layers = product.get("layers", ["CMYK"])
    hotfolders = product.get("hotfolders", {})

    # Generate Plates
    job_out_dir = os.path.join(TEMP_DIR, f"out_{int(time.time())}")
    plates = export_production_plates(
        source_pdf_path=file_path,
        job_name=final_job_name,
        output_dir=job_out_dir,
        layers=layers,
        choke_white_px=choke_w,
        choke_primer_px=choke_p
    )

    # Dispatch to real Hot Folders
    dispatched = []
    for layer, plate_file in plates.items():
        hf_dir = hotfolders.get(layer)
        if hf_dir and os.path.exists(hf_dir):
            dst = os.path.join(hf_dir, os.path.basename(plate_file))
            shutil.copy2(plate_file, dst)
            dispatched.append({
                "layer": layer,
                "file": os.path.basename(plate_file),
                "hotfolder": hf_dir,
                "destination": dst
            })
            print(f"[DISPATCH] {layer} -> {dst}")
        else:
            print(f"[WARN] Hotfolder missing for {layer}: {hf_dir}")

    elapsed_ms = round((time.time() - t0) * 1000)

    log_entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "job_name": final_job_name,
        "product_name": product["name"],
        "layers": list(plates.keys()),
        "dispatched_count": len(dispatched),
        "dispatched": dispatched,
        "elapsed_ms": elapsed_ms
    }
    job_history.insert(0, log_entry)
    await broadcast_event("job_dispatched", log_entry)

    return {
        "status": "success",
        "job_name": final_job_name,
        "elapsed_ms": elapsed_ms,
        "dispatched": dispatched
    }


@app.get("/api/history")
async def get_history():
    return job_history[:50]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# Static files mount
STATIC_DIR = os.path.abspath("printflow/static")
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
