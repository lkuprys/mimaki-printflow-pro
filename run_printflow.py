import os
import sys

# Ensure current project directory is in sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import subprocess
import webbrowser
import threading
import time

def open_app_window():
    time.sleep(1.0)
    url = "http://localhost:8080"
    
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
    ]
    
    launched = False
    for p in edge_paths + chrome_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}", "--start-maximized"])
                launched = True
                print(f"[PRINTFLOW] Atidarytas App Mode langas per: {os.path.basename(p)}")
                break
            except Exception:
                pass
                
    if not launched:
        print(f"[PRINTFLOW] Atidaroma narsykleje: {url}")
        webbrowser.open(url)

if __name__ == "__main__":
    print("=" * 70)
    print("   MIMAKI PRINTFLOW PRO - Gamybinis Spaudos Valdiklis")
    print("   Versija 1.0.0 Enterprise | Standalone Mode")
    print("=" * 70)
    
    # Open browser / app window
    threading.Thread(target=open_app_window, daemon=True).start()
    
    import uvicorn
    uvicorn.run("printflow.server.app:app", host="0.0.0.0", port=8080, log_level="info")
