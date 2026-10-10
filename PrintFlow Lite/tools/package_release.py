"""
Release ZIP sudarymas iš PyInstaller --onedir rezultato.

PrintFlowLite_vX.Y.Z.zip
└── PrintFlowLite/
    ├── PrintFlowLite.exe
    ├── _internal/            (Python, Qt, fonts/, assets/ …)
    └── README.md

config.json į paketą NEDEDAMAS – jis sukuriamas pirmą kartą paleidus, o atnaujinimas jo neliečia.
"""

import argparse
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
sys.path.insert(0, APP_DIR)
from updater import PAYLOAD_DIR_NAME, PAYLOAD_EXE_NAME, validate_update_zip  # noqa: E402


def package(version, dist_dir, out_dir, readme=None):
    src = os.path.join(dist_dir, PAYLOAD_DIR_NAME)
    if not os.path.isfile(os.path.join(src, PAYLOAD_EXE_NAME)):
        raise SystemExit(f"Nerastas {src}/{PAYLOAD_EXE_NAME}")
    if not os.path.isdir(os.path.join(src, "_internal")):
        raise SystemExit(f"Nerastas {src}/_internal (reikia PyInstaller --onedir)")
    if readme and os.path.exists(readme):
        shutil.copyfile(readme, os.path.join(src, "README.md"))
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"PrintFlowLite_v{version}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(src):
            dirs.sort()
            for fn in sorted(files):
                if fn in ("config.json", "jobs_registry.json") or fn.endswith((".log", ".lock")):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, dist_dir).replace(os.sep, "/")
                z.write(full, rel)
    ok, msg = validate_update_zip(zip_path)
    if not ok:
        raise SystemExit(f"Sugeneruotas ZIP netinkamas: {msg}")
    print(f"Paketas: {zip_path} ({os.path.getsize(zip_path) / 1024 / 1024:.1f} MB)")
    return zip_path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--dist", default=os.path.join(APP_DIR, "dist"))
    ap.add_argument("--out", default=os.path.join(APP_DIR, "dist"))
    ap.add_argument("--readme", default=os.path.join(APP_DIR, "README.md"))
    a = ap.parse_args(argv)
    package(a.version, a.dist, a.out, a.readme)


if __name__ == "__main__":
    main()
