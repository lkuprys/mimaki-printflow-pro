"""
Pakeitimų aprašas išleidimui ➔ dist/release_notes.md.

Šaltinių eilė: NOTES aplinkos kintamasis ➔ KAS_NAUJO.md punktai ➔ commit'ų pavadinimai
nuo paskutinės lite-v* žymės (tik 'PrintFlow Lite/' aplankas) ➔ „Smulkūs patobulinimai.“
Po to KAS_NAUJO.md išvalomas (paliekama antraštė).
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
MARKER = "<!-- Pakeitimai žemiau šios eilutės -->"
HEADER = (
    "# Kas naujo\n\n"
    "Čia rašomi naudotojui matomi pakeitimai, kurie bus parodyti atnaujinimo lange.\n"
    "Kiekvienas punktas – nauja eilutė, prasidedanti „- “, lietuviškai, paprasta kalba.\n"
    "Išleidus versiją šis sąrašas automatiškai išvalomas.\n\n"
    f"{MARKER}\n"
)



def _utf8_stdout():
    """Windows konsolė (GitHub Actions) naudoja cp1252 – lietuviškos raidės kitaip sugriauna skriptą."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

def read_items(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    body = text.split(MARKER, 1)[1] if MARKER in text else text
    return [l.strip() for l in body.splitlines() if l.strip().startswith(("- ", "* "))]


def commit_subjects(since_tag, cwd=None):
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    try:
        out = subprocess.run(["git", "log", "--format=%s", rng, "--", "PrintFlow Lite"],
                             capture_output=True, text=True, cwd=cwd, check=True).stdout
    except Exception:
        return []
    return [f"- {s.strip()}" for s in out.splitlines()
            if s.strip() and not s.startswith(("Versija ", "Merge "))][:20]


def build_notes(version, notes_env, kas_naujo, since_tag=None, cwd=None):
    if notes_env and notes_env.strip():
        lines = [l.strip() for l in notes_env.strip().splitlines() if l.strip()]
        items = [l if l.startswith(("- ", "* ")) else f"- {l}" for l in lines]
    else:
        items = read_items(kas_naujo) or commit_subjects(since_tag, cwd) or ["- Smulkūs patobulinimai."]
    return f"## PrintFlow Lite v{version}\n\n" + "\n".join(items) + "\n"


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--since-tag", default="")
    ap.add_argument("--out", default=os.path.join(APP_DIR, "dist", "release_notes.md"))
    ap.add_argument("--kas-naujo", default=os.path.join(APP_DIR, "KAS_NAUJO.md"))
    args = ap.parse_args(argv)
    notes = build_notes(args.version, os.environ.get("NOTES", ""), args.kas_naujo, args.since_tag or None)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(notes)
    with open(args.kas_naujo, "w", encoding="utf-8") as f:
        f.write(HEADER)
    print(notes)


if __name__ == "__main__":
    main()
