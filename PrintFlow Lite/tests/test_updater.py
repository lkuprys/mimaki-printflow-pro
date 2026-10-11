"""
Atnaujinimų sistemos testai: versijos, GitHub išleidimų parinkimas, ZIP patikra, išleidimo įrankiai,
pilnas AppUpdater ciklas per vietinį HTTP serverį ir (Windows) tikras PowerShell keitimo skriptas.
"""

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.join(APP_DIR, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRINTFLOW_NO_AUTO_UPDATE", "1")

import updater  # noqa: E402
import next_version  # noqa: E402
import release_notes  # noqa: E402
import package_release  # noqa: E402


def make_payload_zip(path, version="9.9.9", exe_bytes=b"MZ-new", marker="new", extra=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("PrintFlowLite/PrintFlowLite.exe", exe_bytes)
        z.writestr(f"PrintFlowLite/_internal/marker_{marker}.txt", version)
        z.writestr("PrintFlowLite/README.md", "readme")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return path


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------
# Versijos ir išleidimų parinkimas
# ---------------------------------------------------------------------------
def test_parse_version_tuple():
    assert updater.parse_version_tuple("lite-v1.2.3") == (1, 2, 3)
    assert updater.parse_version_tuple("v1.2") == (1, 2, 0)
    assert updater.parse_version_tuple("2.0.0-beta+5") == (2, 0, 0)
    assert updater.parse_version_tuple("") == (0, 0, 0)
    assert updater.is_newer("1.2.1", "1.2.0") and not updater.is_newer("1.2.0", "1.2.0")
    assert not updater.is_newer("1.1.9", "1.2.0") and updater.is_newer("1.10.0", "1.9.9")


def _rel(tag, assets=("PrintFlowLite_v{v}.zip",), draft=False, pre=False, body="- x"):
    v = tag.split("v", 1)[-1]
    return {"tag_name": tag, "draft": draft, "prerelease": pre, "body": body,
            "assets": [{"name": a.format(v=v), "size": 10, "browser_download_url": f"https://x/{a.format(v=v)}",
                        "digest": "sha256:ABC"} for a in assets]}


def test_select_latest_release_ignores_pro_drafts_and_missing_assets():
    releases = [
        _rel("v9.0.0", assets=("PrintFlow-Windows-x64.zip",)),  # senoji PRO programa
        _rel("lite-v1.4.0", draft=True),
        _rel("lite-v1.5.0", pre=True),
        _rel("lite-v1.3.5", assets=("kitas.zip",)),
        _rel("lite-v1.3.0"),
        _rel("lite-v1.2.9"),
    ]
    best = updater.select_latest_release(releases)
    assert best["version"] == "1.3.0" and best["tag"] == "lite-v1.3.0"
    assert best["asset_name"] == "PrintFlowLite_v1.3.0.zip" and best["asset_sha256"] == "abc"
    assert updater.select_latest_release([_rel("v9.0.0", assets=("PrintFlow-Windows-x64.zip",))]) is None


# ---------------------------------------------------------------------------
# ZIP patikra ir PowerShell skriptas
# ---------------------------------------------------------------------------
def test_validate_update_zip(tmp_path):
    good = make_payload_zip(str(tmp_path / "good.zip"))
    size = os.path.getsize(good)
    assert updater.validate_update_zip(good, size, sha(good)) == (True, "")
    assert "nepilnas" in updater.validate_update_zip(good, size + 1)[1]
    assert "SHA-256" in updater.validate_update_zip(good, size, "0" * 64)[1]
    bad = tmp_path / "bad.zip"
    bad.write_bytes(open(good, "rb").read()[:-40])
    assert not updater.validate_update_zip(str(bad))[0]
    noexe = str(tmp_path / "noexe.zip")
    with zipfile.ZipFile(noexe, "w") as z:
        z.writestr("PrintFlowLite/_internal/a.txt", "x")
    assert "PrintFlowLite.exe" in updater.validate_update_zip(noexe)[1]
    evil = make_payload_zip(str(tmp_path / "evil.zip"), extra={"PrintFlowLite/../../evil.txt": "x"})
    assert "Netinkamas kelias" in updater.validate_update_zip(evil)[1]


def test_ps_script_quoting_and_bom(tmp_path):
    weird = r"C:\Users\Jonas O'Brien\Darbai $env:X `n Ąžuolas"
    script = updater.build_ps_script(weird, weird + r"\staged", weird, weird + r"\u.zip", 1234, "1.2.3")
    assert "'C:\\Users\\Jonas O''Brien\\Darbai $env:X `n Ąžuolas'" in script
    assert "__" not in script.replace("__internal", "")  # visi žymekliai pakeisti
    assert "'config.json'" in script and "'jobs_registry.json'" in script
    p = tmp_path / "u.ps1"
    updater.write_ps_script(str(p), script)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_apply_update_refuses_outside_frozen(tmp_path):
    z = make_payload_zip(str(tmp_path / "u.zip"))
    with pytest.raises(RuntimeError):
        updater.apply_update(z, {"version": "9.9.9", "asset_size": 0, "asset_sha256": ""})


def test_read_last_update_result(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"ok": True, "version": "1.2.3"}), encoding="utf-8")
    assert updater.read_last_update_result(str(p)) == {"ok": True, "version": "1.2.3"}
    assert not p.exists() and updater.read_last_update_result(str(p)) is None


# ---------------------------------------------------------------------------
# Išleidimo įrankiai
# ---------------------------------------------------------------------------
def test_next_version(tmp_path):
    assert next_version.compute("1.2.0", None, "patch") == (1, 2, 0)
    assert next_version.compute("1.2.0", "lite-v1.2.0", "patch") == (1, 2, 1)
    assert next_version.compute("1.2.0", "lite-v1.2.7", "minor") == (1, 3, 0)
    assert next_version.compute("2.0.0", "lite-v1.9.9", "patch") == (2, 0, 0)  # rankinis nustatymas
    assert next_version.compute("1.0.0", "lite-v1.2.3", "major") == (2, 0, 0)

    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    upd = repo / "updater.py"
    upd.write_text('X = 1\nCURRENT_VERSION = "1.2.0"\n', encoding="utf-8")
    run("add", ".")
    run("commit", "-qm", "init")
    for t in ("v5.0.0", "lite-v1.2.0", "lite-v1.2.10", "lite-v1.2.9"):
        run("tag", t)
    out = tmp_path / "gh_out"
    os.environ["GITHUB_OUTPUT"] = str(out)
    try:
        new = next_version.main(["--bump", "patch", "--updater", str(upd), "--git-dir", str(repo)])
    finally:
        os.environ.pop("GITHUB_OUTPUT")
    assert new == "1.2.11"
    assert 'CURRENT_VERSION = "1.2.11"' in upd.read_text(encoding="utf-8")
    assert out.read_text() == "version=1.2.11\n"


def test_release_notes(tmp_path):
    kn = tmp_path / "KAS_NAUJO.md"
    kn.write_text(release_notes.HEADER + "- Pirmas punktas\n- Antras punktas\nne punktas\n", encoding="utf-8")
    notes = release_notes.build_notes("1.3.0", "", str(kn))
    assert notes == "## PrintFlow Lite v1.3.0\n\n- Pirmas punktas\n- Antras punktas\n"
    assert release_notes.build_notes("1.3.0", "Vienas\n- Du", str(kn)).endswith("- Vienas\n- Du\n")
    out = tmp_path / "dist" / "notes.md"
    os.environ.pop("NOTES", None)
    release_notes.main(["--version", "1.3.0", "--out", str(out), "--kas-naujo", str(kn)])
    assert "Pirmas punktas" in out.read_text(encoding="utf-8")
    assert release_notes.read_items(str(kn)) == []  # išvalyta


def test_package_release(tmp_path):
    dist = tmp_path / "dist"
    app = dist / "PrintFlowLite"
    (app / "_internal" / "fonts").mkdir(parents=True)
    (app / "PrintFlowLite.exe").write_bytes(b"MZ")
    (app / "_internal" / "fonts" / "Inter.ttf").write_bytes(b"f")
    (app / "config.json").write_text("{}")  # vartotojo failas – NEturi patekti į paketą
    (app / "printflow_lite.log").write_text("x")
    readme = tmp_path / "README.md"
    readme.write_text("r")
    z = package_release.package("1.3.0", str(dist), str(tmp_path / "out"), str(readme))
    names = zipfile.ZipFile(z).namelist()
    assert os.path.basename(z) == "PrintFlowLite_v1.3.0.zip"
    assert "PrintFlowLite/PrintFlowLite.exe" in names and "PrintFlowLite/_internal/fonts/Inter.ttf" in names
    assert "PrintFlowLite/README.md" in names
    assert not any(n.endswith(("config.json", ".log")) for n in names)
    assert updater.RELEASE_ASSET_PATTERN.match(os.path.basename(z))


def test_tools_survive_cp1252_console(tmp_path):
    """GitHub Actions Windows konsolė – cp1252; lietuviškos raidės neturi sugriauti išleidimo."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    env.pop("PYTHONUTF8", None)
    env.pop("GITHUB_OUTPUT", None)
    upd = tmp_path / "updater.py"
    upd.write_text('CURRENT_VERSION = "1.2.0"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    r = subprocess.run([sys.executable, os.path.join(APP_DIR, "tools", "next_version.py"),
                        "--updater", str(upd), "--git-dir", str(tmp_path)],
                       env=env, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    kn = tmp_path / "KAS_NAUJO.md"
    kn.write_text(release_notes.HEADER + "- Ąžuolas ėjo į šilą\n", encoding="utf-8")
    r = subprocess.run([sys.executable, os.path.join(APP_DIR, "tools", "release_notes.py"), "--version", "1.2.0",
                        "--out", str(tmp_path / "n.md"), "--kas-naujo", str(kn)], env=env, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "Ąžuolas ėjo į šilą" in (tmp_path / "n.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pilnas AppUpdater ciklas per vietinį „GitHub“
# ---------------------------------------------------------------------------
class _FakeGitHub(http.server.ThreadingHTTPServer):
    pass


def _serve(tmp_path, releases_factory):
    zip_path = make_payload_zip(str(tmp_path / "PrintFlowLite_v9.9.9.zip"))
    state = {"zip": zip_path}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/repos/"):
                body = json.dumps(releases_factory(self.server.server_port, state)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            elif self.path.endswith(".zip"):
                body = open(state["zip"], "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
            else:
                self.send_response(404)
                body = b""
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = _FakeGitHub(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


def _release_list(port, state, version="9.9.9"):
    z = state["zip"]
    return [
        {"tag_name": "v1.0.0", "draft": False, "prerelease": False, "body": "PRO",
         "assets": [{"name": "PrintFlow-Windows-x64.zip", "size": 1, "browser_download_url": "x"}]},
        {"tag_name": f"lite-v{version}", "draft": False, "prerelease": False, "body": "- Naujiena",
         "assets": [{"name": f"PrintFlowLite_v{version}.zip", "size": os.path.getsize(z),
                     "digest": "sha256:" + sha(z),
                     "browser_download_url": f"http://127.0.0.1:{port}/dl/PrintFlowLite_v{version}.zip"}]},
    ]


def _wait(app, cond, timeout=20):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    return cond()


def _window(tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.main_window import MainWindowLite
    cfg = tmp_path / "app" / "config.json"
    cfg.parent.mkdir()
    return app, MainWindowLite(config_path=str(cfg))


def test_app_updater_full_cycle(tmp_path, monkeypatch):
    srv, state = _serve(tmp_path, _release_list)
    monkeypatch.setattr(updater, "TEMP_DIR", str(tmp_path / "temp"))
    os.makedirs(updater.TEMP_DIR)
    app, win = _window(tmp_path)
    u = win.updater
    u.api_base = f"http://127.0.0.1:{srv.server_port}"
    u.auto_answer = True
    applied = {}

    def fake_apply(path, info, expected_exe=None):
        applied["ok"] = updater.validate_update_zip(path, info["asset_size"], info["asset_sha256"])
        applied["version"] = info["version"]
        raise RuntimeError("testas: diegimas sustabdytas")

    monkeypatch.setattr(updater, "apply_update", fake_apply)
    states = []
    u.state_changed.connect(lambda s, t: states.append((s, t)))
    u.check(manual=True)
    assert _wait(app, lambda: "version" in applied), states
    assert applied == {"ok": (True, ""), "version": "9.9.9"}
    assert ("update", "Yra nauja versija v9.9.9") in states
    assert _wait(app, lambda: not u._busy)

    # Atidėjimas: automatinė patikra tos pačios versijos nebesiūlo 4 val.
    u.auto_answer = False
    u.check(manual=True)
    assert _wait(app, lambda: "9.9.9" in u._postponed)
    applied.clear()
    u.auto_answer = True
    u.check(manual=False)
    _wait(app, lambda: not u._checking)
    time.sleep(0.3)
    app.processEvents()
    assert "version" not in applied, "atidėta versija neturi būti siūloma automatiškai"
    win.close()
    srv.shutdown()


def test_app_updater_no_update_and_bad_download(tmp_path, monkeypatch):
    srv, state = _serve(tmp_path, lambda port, st: _release_list(port, st, version=updater.CURRENT_VERSION))
    monkeypatch.setattr(updater, "TEMP_DIR", str(tmp_path / "temp"))
    os.makedirs(updater.TEMP_DIR)
    app, win = _window(tmp_path)
    u = win.updater
    u.api_base = f"http://127.0.0.1:{srv.server_port}"
    states = []
    u.state_changed.connect(lambda s, t: states.append(s))
    u.check(manual=True)
    assert _wait(app, lambda: "ok" in states)

    # Sugadintas atsisiuntimas (SHA nesutampa) – nediegiama, rodoma klaida, failas ištrintas
    bad_list = _release_list(srv.server_port, state)
    bad_list[1]["tag_name"] = "lite-v9.9.9"
    bad_list[1]["assets"][0]["digest"] = "sha256:" + "0" * 64
    monkeypatch.setattr(updater, "fetch_releases_safe", lambda repo, api_base: bad_list)
    monkeypatch.setattr(updater, "apply_update", lambda *a, **k: pytest.fail("neturi būti diegiama"))
    errors = []
    real_show = win.toasts.show
    monkeypatch.setattr(win.toasts, "show", lambda kind, title, text="", sticky=False:
                        (errors.append((kind, title, text)), real_show(kind, title, text, sticky))[1])
    u.auto_answer = True
    states.clear()
    u.check(manual=True)
    assert _wait(app, lambda: "error" in states), states
    assert any(k == "error" and "SHA-256" in t for k, _, t in errors), errors
    assert not [f for f in os.listdir(updater.TEMP_DIR) if f.endswith(".zip")]
    win.close()
    srv.shutdown()


# ---------------------------------------------------------------------------
# Tikras PowerShell keitimas (tik Windows – vykdoma GitHub Actions windows-latest)
# ---------------------------------------------------------------------------
def _fake_install(root):
    app = root / "Programos Ąžuolas O'Brien" / "PrintFlowLite"
    (app / "_internal").mkdir(parents=True)
    shutil.copyfile(os.path.join(os.environ["SystemRoot"], "System32", "whoami.exe"), app / "PrintFlowLite.exe")
    (app / "_internal" / "marker_old.txt").write_text("old")
    (app / "config.json").write_text('{"vartotojo": true}', encoding="utf-8")
    (app / "jobs_registry.json").write_text('{"job": 1}', encoding="utf-8")
    return app


def _run_ps(tmp_path, app, staged_root, zip_path, new_exe_src):
    pid_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    result = tmp_path / "result.json"
    log = tmp_path / "updater.log"
    script = updater.build_ps_script(str(app), str(staged_root / "PrintFlowLite"), str(staged_root), str(zip_path),
                                     pid_proc.pid, "9.9.9", "1.0.0", str(result), str(log), restart=False)
    ps1 = tmp_path / "u.ps1"
    updater.write_ps_script(str(ps1), script)
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                   timeout=120, check=False)
    pid_proc.wait()
    return json.loads(result.read_text(encoding="utf-8-sig")), log.read_text(encoding="utf-8-sig")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell keitimas tik Windows")
def test_powershell_update_success_keeps_user_data(tmp_path):
    app = _fake_install(tmp_path)
    new_exe = os.path.join(os.environ["SystemRoot"], "System32", "hostname.exe")
    zip_path = tmp_path / "PrintFlowLite_v9.9.9.zip"
    make_payload_zip(str(zip_path), exe_bytes=open(new_exe, "rb").read(),
                     extra={"PrintFlowLite/config.json": '{"is_paketo": true}'})
    staging = tmp_path / "staging"
    updater.stage_update(str(zip_path), str(staging))
    res, log = _run_ps(tmp_path, app, staging, zip_path, new_exe)
    assert res["ok"] is True, log
    assert (app / "_internal" / "marker_new.txt").exists()
    assert not (app / "_internal" / "marker_old.txt").exists()
    assert (app / "PrintFlowLite.exe").read_bytes() == open(new_exe, "rb").read()
    assert json.loads((app / "config.json").read_text(encoding="utf-8")) == {"vartotojo": True}
    assert (app / "jobs_registry.json").read_text(encoding="utf-8") == '{"job": 1}'
    assert not (app / "_internal.old").exists() and not (app.parent / "PrintFlowLite" / "PrintFlowLite.exe.old").exists()
    assert not staging.exists() and not zip_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell keitimas tik Windows")
def test_powershell_update_failure_rolls_back(tmp_path):
    app = _fake_install(tmp_path)
    old_exe = (app / "PrintFlowLite.exe").read_bytes()
    zip_path = tmp_path / "PrintFlowLite_v9.9.9.zip"
    make_payload_zip(str(zip_path))
    staging = tmp_path / "staging"
    updater.stage_update(str(zip_path), str(staging))
    shutil.rmtree(staging / "PrintFlowLite" / "_internal")  # imituojamas sugedęs paketas
    res, log = _run_ps(tmp_path, app, staging, zip_path, None)
    assert res["ok"] is False and res["old_version"] == "1.0.0", log
    assert "Atstatyta" in log
    assert (app / "_internal" / "marker_old.txt").exists()
    assert (app / "PrintFlowLite.exe").read_bytes() == old_exe
    assert (app / "config.json").exists() and not (app / "_internal.old").exists()
