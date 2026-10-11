"""
PrintFlow Lite atnaujintojas (be Qt)
------------------------------------
Versijos tiesa, GitHub Release paieška, atsisiuntimas, ZIP patikra ir PowerShell keitimo skriptas.
Qt dialogai ir laikmačiai – ui/update_ui.py.

Invariantai (keisti tik suderintai su tools/ ir .github/workflows/printflow-lite-release.yml):
  - CURRENT_VERSION eilutės formatas (tools/next_version.py regex)
  - žymės: lite-vX.Y.Z (senoji PrintFlow PRO naudoja vX.Y.Z – jos ignoruojamos)
  - asset'as: PrintFlowLite_vX.Y.Z.zip, viduje PrintFlowLite/PrintFlowLite.exe + PrintFlowLite/_internal/
  - vietiniai failai (LOCAL_DATA_FILES) atnaujinimo metu NELIEČIAMI
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

CURRENT_VERSION = "1.2.2"

DEFAULT_GITHUB_REPO = "lkuprys/mimaki-printflow-pro"
TAG_PREFIX = "lite-v"
RELEASE_ASSET_PATTERN = re.compile(r"^PrintFlowLite_v\d+(\.\d+)*\.zip$")
PAYLOAD_DIR_NAME = "PrintFlowLite"
PAYLOAD_EXE_NAME = "PrintFlowLite.exe"
# Vartotojo duomenys šalia .exe – atnaujinimas jų niekada neperrašo (robocopy /XF)
LOCAL_DATA_FILES = [
    "config.json", "config.json.*", "jobs_registry.json", "jobs_registry.json.*",
    "printflow_lite.log", "printflow_lite.log.*", "printflow_lite.lock",
]

PERIODIC_CHECK_INTERVAL_MS = 30 * 60 * 1000
POSTPONE_SECONDS = 4 * 3600
USER_AGENT = f"PodbasePrintFlowLite/{CURRENT_VERSION}"

TEMP_DIR = tempfile.gettempdir()
RESULT_FILE = os.path.join(TEMP_DIR, "printflow_update_result.json")
UPDATER_LOG = os.path.join(TEMP_DIR, "printflow_updater.log")
STAGING_DIR = os.path.join(TEMP_DIR, "printflow_update_staging")
PS_SCRIPT = os.path.join(TEMP_DIR, "printflow_updater.ps1")

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# Versijos
# ---------------------------------------------------------------------------
def parse_version_tuple(v: str) -> Tuple[int, int, int]:
    """'lite-v1.2.3' / 'v1.2' / '2.0.0-beta+5' ➔ (1,2,3) / (1,2,0) / (2,0,0)."""
    s = (v or "").strip()
    if s.startswith(TAG_PREFIX):
        s = s[len(TAG_PREFIX):]
    s = s.lstrip("vV")
    s = re.split(r"[-+]", s, maxsplit=1)[0]
    parts = []
    for p in s.split(".")[:3]:
        m = re.match(r"\d+", p)
        parts.append(int(m.group(0)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str = CURRENT_VERSION) -> bool:
    return parse_version_tuple(remote) > parse_version_tuple(local)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read()


def fetch_releases_safe(repo: str, api_base: str = "https://api.github.com") -> List[Dict]:
    """
    Grąžina išleidimų sąrašą. Bando: Python urllib ➔ curl.exe ➔ PowerShell (Windows).
    TLS tikrinamas visais atvejais. Išmeta RuntimeError su visų bandymų priežastimis.
    """
    url = f"{api_base}/repos/{repo}/releases?per_page=30"
    errors = []
    try:
        return json.loads(_http_get(url, 10).decode("utf-8"))
    except Exception as e:
        errors.append(f"urllib: {e}")
    if os.name == "nt":
        try:
            out = subprocess.run(["curl.exe", "-sS", "-f", "-L", "--max-time", "12", "-H", f"User-Agent: {USER_AGENT}", url],
                                 capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
            if out.returncode == 0:
                return json.loads(out.stdout.decode("utf-8"))
            errors.append(f"curl: {out.stderr.decode('utf-8', 'replace').strip()}")
        except Exception as e:
            errors.append(f"curl: {e}")
        try:
            ps = ("[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
                  f"(Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri '{url}').Content")
            out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                                 capture_output=True, timeout=25, creationflags=CREATE_NO_WINDOW)
            if out.returncode == 0:
                return json.loads(out.stdout.decode("utf-8"))
            errors.append(f"powershell: {out.stderr.decode('utf-8', 'replace').strip()[:200]}")
        except Exception as e:
            errors.append(f"powershell: {e}")
    raise RuntimeError("Nepavyko pasiekti GitHub: " + " | ".join(errors))


def select_release_asset(release: Dict) -> Optional[Dict]:
    for a in release.get("assets") or []:
        if RELEASE_ASSET_PATTERN.match(a.get("name", "")):
            return a
    return None


def select_latest_release(releases: List[Dict]) -> Optional[Dict]:
    """
    Naujausias PrintFlow Lite išleidimas: žymė lite-v*, ne juodraštis, ne pre-release,
    su tinkamu ZIP. Grąžina {"version", "tag", "changelog", "download_url", "asset_size", "asset_sha256"}.
    """
    best = None
    for r in releases or []:
        tag = r.get("tag_name", "")
        if not tag.startswith(TAG_PREFIX) or r.get("draft") or r.get("prerelease"):
            continue
        asset = select_release_asset(r)
        if asset is None:
            continue
        ver = parse_version_tuple(tag)
        if best is None or ver > best[0]:
            best = (ver, r, asset)
    if best is None:
        return None
    ver, r, asset = best
    digest = asset.get("digest") or ""
    return {
        "version": ".".join(str(x) for x in ver),
        "tag": r.get("tag_name", ""),
        "changelog": (r.get("body") or "").strip(),
        "download_url": asset.get("browser_download_url", ""),
        "asset_name": asset.get("name", ""),
        "asset_size": int(asset.get("size") or 0),
        "asset_sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
    }


def check_for_update(repo: str, current: str = CURRENT_VERSION, api_base: str = "https://api.github.com") -> Dict:
    """{'status': 'update'|'no_update'|'no_release', 'info': {...}}"""
    latest = select_latest_release(fetch_releases_safe(repo, api_base))
    if latest is None:
        return {"status": "no_release", "info": None}
    if not is_newer(latest["version"], current):
        return {"status": "no_update", "info": latest}
    return {"status": "update", "info": latest}


# ---------------------------------------------------------------------------
# Atsisiuntimas ir patikra
# ---------------------------------------------------------------------------
def download_file(url: str, dest: str, expected_size: int = 0,
                  progress: Optional[Callable[[int, int], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None) -> None:
    """Atsisiunčia per urllib (64 KB blokais); nepavykus Windows'e – curl.exe. Atšaukus – dalinis failas ištrinamas."""
    if os.path.exists(dest):
        os.remove(dest)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or expected_size or 0)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise InterruptedError("Atsisiuntimas atšauktas")
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        return
    except InterruptedError:
        _silent_remove(dest)
        raise
    except Exception as first_error:
        _silent_remove(dest)
        if os.name != "nt":
            raise
        _download_with_curl(url, dest, expected_size, progress, cancelled, first_error)


def _download_with_curl(url, dest, expected_size, progress, cancelled, first_error):
    proc = subprocess.Popen(["curl.exe", "-f", "-L", "-sS", "--retry", "2", "--connect-timeout", "15", "-o", dest, url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            proc.wait()
            _silent_remove(dest)
            raise InterruptedError("Atsisiuntimas atšauktas")
        if progress and os.path.exists(dest):
            progress(os.path.getsize(dest), expected_size)
        time.sleep(0.2)
    if proc.returncode != 0:
        err = proc.stderr.read().decode("utf-8", "replace").strip() if proc.stderr else ""
        _silent_remove(dest)
        raise RuntimeError(f"Atsisiųsti nepavyko ({first_error}; curl: {err or proc.returncode})")


def _silent_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_update_zip(path: str, expected_size: int = 0, expected_sha256: str = "") -> Tuple[bool, str]:
    """Dydis ➔ SHA-256 ➔ ZIP CRC ➔ struktūra (PrintFlowLite/PrintFlowLite.exe + _internal/)."""
    if not os.path.isfile(path):
        return False, "Atsisiųstas failas nerastas"
    size = os.path.getsize(path)
    if expected_size and size != expected_size:
        return False, f"Atsisiųstas failas nepilnas ({size} iš {expected_size} B)"
    if expected_sha256 and sha256_file(path).lower() != expected_sha256.lower():
        return False, "Kontrolinė suma (SHA-256) nesutampa"
    if not zipfile.is_zipfile(path):
        return False, "Failas nėra ZIP archyvas"
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            if bad:
                return False, f"ZIP archyvas sugadintas ({bad})"
            names = set(n.replace("\\", "/") for n in z.namelist())
    except Exception as e:
        return False, f"ZIP archyvas sugadintas ({e})"
    if f"{PAYLOAD_DIR_NAME}/{PAYLOAD_EXE_NAME}" not in names:
        return False, f"Archyve nėra {PAYLOAD_DIR_NAME}/{PAYLOAD_EXE_NAME}"
    if not any(n.startswith(f"{PAYLOAD_DIR_NAME}/_internal/") for n in names):
        return False, f"Archyve nėra {PAYLOAD_DIR_NAME}/_internal/"
    for n in names:
        if n.startswith("/") or ".." in n.split("/"):
            return False, f"Netinkamas kelias archyve: {n}"
    return True, ""


# ---------------------------------------------------------------------------
# PowerShell keitimo skriptas
# ---------------------------------------------------------------------------
def ps_quote(value) -> str:
    """PowerShell eilutė viengubose kabutėse ('' = ')."""
    return "'" + str(value).replace("'", "''") + "'"


UPDATER_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$AppDir      = __APP_DIR__
$ExeName     = __EXE_NAME__
$Staged      = __STAGED__
$StagingRoot = __STAGING_ROOT__
$ZipPath     = __ZIP__
$AppPid      = __PID__
$NewVersion  = __NEW_VERSION__
$OldVersion  = __OLD_VERSION__
$ResultFile  = __RESULT_FILE__
$LogFile     = __LOG_FILE__
$Exclude     = @(__EXCLUDE__)
$NoRestart   = __NO_RESTART__

function Log([string]$m) {
    try { Add-Content -LiteralPath $LogFile -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $m) -Encoding UTF8 } catch {}
}

$Exe     = Join-Path $AppDir $ExeName
$Int     = Join-Path $AppDir '_internal'
$IntOld  = Join-Path $AppDir '_internal.old'
$ExeOld  = $Exe + '.old'
$ok      = $false
$message = ''
$backup  = $false

try {
    Log ('Atnaujinimas ' + $OldVersion + ' -> ' + $NewVersion + ', aplankas: ' + $AppDir)

    # 1. Laukiama, kol programa užsidarys
    try { Wait-Process -Id $AppPid -Timeout 20 -ErrorAction SilentlyContinue } catch {}
    try { Stop-Process -Id $AppPid -Force -ErrorAction SilentlyContinue } catch {}
    try {
        Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path -ieq $Exe) } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    } catch {}

    # 2. Laukiama, kol .exe bus atrakintas
    $unlocked = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            if (-not (Test-Path -LiteralPath $Exe)) { $unlocked = $true; break }
            $fs = [System.IO.File]::Open($Exe, 'Open', 'ReadWrite', 'None')
            $fs.Close(); $unlocked = $true; break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $unlocked) { throw 'Programos failas vis dar naudojamas (antivirusinė ar kitas procesas)' }

    # 3. Atsarginė kopija
    if (Test-Path -LiteralPath $IntOld) { Remove-Item -LiteralPath $IntOld -Recurse -Force }
    if (Test-Path -LiteralPath $ExeOld) { Remove-Item -LiteralPath $ExeOld -Force }
    if (Test-Path -LiteralPath $Int) { Rename-Item -LiteralPath $Int -NewName '_internal.old' }
    if (Test-Path -LiteralPath $Exe) { Copy-Item -LiteralPath $Exe -Destination $ExeOld -Force }
    $backup = $true
    Log 'Atsarginė kopija sukurta'

    # 4. Naujas _internal (švari kopija)
    $src = Join-Path $Staged '_internal'
    if (-not (Test-Path -LiteralPath $src)) { throw ('Nerastas ' + $src) }
    $out = & robocopy $src $Int /E /R:10 /W:1 /NP /NFL /NDL /NJH 2>&1
    $code = $LASTEXITCODE
    Log (($out | Out-String).Trim())
    if ($code -ge 8) { throw ('robocopy klaida ' + $code + ' (_internal)') }

    # 5. Šakniniai failai (be vartotojo duomenų)
    $args5 = @($Staged, $AppDir, '/E', '/IS', '/IT', '/R:10', '/W:1', '/NP', '/NFL', '/NDL', '/NJH',
               '/XD', '_internal', '_internal.old', '/XF') + $Exclude
    $out = & robocopy @args5 2>&1
    $code = $LASTEXITCODE
    Log (($out | Out-String).Trim())
    if ($code -ge 8) { throw ('robocopy klaida ' + $code + ' (programos failai)') }

    $ok = $true
    $message = 'Programa atnaujinta'
    Log 'Atnaujinimas sėkmingas'
}
catch {
    $message = $_.Exception.Message
    Log ('KLAIDA: ' + $message)
    if ($backup) {
        try {
            if (Test-Path -LiteralPath $IntOld) {
                if (Test-Path -LiteralPath $Int) { Remove-Item -LiteralPath $Int -Recurse -Force }
                Rename-Item -LiteralPath $IntOld -NewName '_internal'
            }
            if (Test-Path -LiteralPath $ExeOld) { Copy-Item -LiteralPath $ExeOld -Destination $Exe -Force }
            Log 'Atstatyta ankstesnė versija'
        } catch { Log ('Atstatymo klaida: ' + $_.Exception.Message) }
    }
}
finally {
    $logText = ''
    try { $logText = Get-Content -LiteralPath $LogFile -Raw -Encoding UTF8 } catch {}
    $result = [ordered]@{ ok = $ok; version = $NewVersion; old_version = $OldVersion; message = $message; log = $LogFile }
    try {
        $json = $result | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($ResultFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch { Log ('Nepavyko įrašyti rezultato: ' + $_.Exception.Message) }
    if ($ok) {
        try { if (Test-Path -LiteralPath $IntOld) { Remove-Item -LiteralPath $IntOld -Recurse -Force } } catch {}
        try { if (Test-Path -LiteralPath $ExeOld) { Remove-Item -LiteralPath $ExeOld -Force } } catch {}
    }
    try { if (Test-Path -LiteralPath $StagingRoot) { Remove-Item -LiteralPath $StagingRoot -Recurse -Force } } catch {}
    try { if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force } } catch {}
    # Programa paleidžiama VISADA – nauja arba atstatyta sena
    if (-not $NoRestart) {
        try { Start-Process -FilePath $Exe -WorkingDirectory $AppDir } catch { Log ('Nepavyko paleisti: ' + $_.Exception.Message) }
    }
}
"""


def build_ps_script(app_dir: str, staged: str, staging_root: str, zip_path: str, pid: int,
                    new_version: str, old_version: str = CURRENT_VERSION,
                    result_file: str = RESULT_FILE, log_file: str = UPDATER_LOG,
                    exe_name: str = PAYLOAD_EXE_NAME, restart: bool = True) -> str:
    values = {
        "__APP_DIR__": ps_quote(app_dir), "__EXE_NAME__": ps_quote(exe_name), "__STAGED__": ps_quote(staged),
        "__STAGING_ROOT__": ps_quote(staging_root), "__ZIP__": ps_quote(zip_path), "__PID__": str(int(pid)),
        "__NEW_VERSION__": ps_quote(new_version), "__OLD_VERSION__": ps_quote(old_version),
        "__RESULT_FILE__": ps_quote(result_file), "__LOG_FILE__": ps_quote(log_file),
        "__EXCLUDE__": ", ".join(ps_quote(x) for x in LOCAL_DATA_FILES),
        "__NO_RESTART__": "$false" if restart else "$true",
    }
    script = UPDATER_PS_TEMPLATE
    for k, v in values.items():
        script = script.replace(k, v)
    return script


def write_ps_script(path: str, script: str):
    """UTF-8 su BOM – kitaip Windows PowerShell 5.1 sugadina lietuviškas raides keliuose."""
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(script)


def stage_update(zip_path: str, staging_root: str = STAGING_DIR) -> str:
    """Išarchyvuoja į staging ir grąžina PrintFlowLite aplanko kelią."""
    if os.path.exists(staging_root):
        shutil.rmtree(staging_root, ignore_errors=True)
    os.makedirs(staging_root, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(staging_root)
    staged = os.path.join(staging_root, PAYLOAD_DIR_NAME)
    if not os.path.isfile(os.path.join(staged, PAYLOAD_EXE_NAME)) or not os.path.isdir(os.path.join(staged, "_internal")):
        raise RuntimeError("Išarchyvuotame atnaujinime nėra programos failų")
    return staged


def apply_update(zip_path: str, info: Dict, expected_exe: Optional[str] = None) -> str:
    """
    Paruošia ir paleidžia PowerShell keitimą. Grąžina PS skripto kelią.
    Iškvietęs turi NEDELSIANT baigti procesą (os._exit), kad atsilaisvintų failai.
    Išmeta RuntimeError, jei atnaujinti negalima.
    """
    if not getattr(sys, "frozen", False) and expected_exe is None:
        raise RuntimeError("Atnaujinti galima tik sukompiliuotą programą (PrintFlowLite.exe)")
    if os.name != "nt":
        raise RuntimeError("Atnaujinimas palaikomas tik Windows sistemoje")
    exe = expected_exe or sys.executable
    if os.path.basename(exe).lower() != PAYLOAD_EXE_NAME.lower():
        raise RuntimeError(f"Programos failas pavadintas „{os.path.basename(exe)}“, o ne {PAYLOAD_EXE_NAME} – "
                           f"atnaujinimas atšauktas")
    ok, msg = validate_update_zip(zip_path, info.get("asset_size", 0), info.get("asset_sha256", ""))
    if not ok:
        raise RuntimeError(msg)
    staged = stage_update(zip_path)
    app_dir = os.path.dirname(os.path.abspath(exe))
    script = build_ps_script(app_dir, staged, STAGING_DIR, zip_path, os.getpid(), info["version"])
    write_ps_script(PS_SCRIPT, script)
    _silent_remove(RESULT_FILE)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", PS_SCRIPT],
        creationflags=CREATE_NO_WINDOW, close_fds=True,
    )
    return PS_SCRIPT


def read_last_update_result(path: str = RESULT_FILE) -> Optional[Dict]:
    """Perskaito ir ištrina paskutinio atnaujinimo rezultatą."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        data = None
    _silent_remove(path)
    return data if isinstance(data, dict) else None
