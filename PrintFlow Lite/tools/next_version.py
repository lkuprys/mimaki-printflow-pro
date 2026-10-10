"""
Kitos PrintFlow Lite versijos skaičiavimas (naudoja release workflow).

1. Nuskaito CURRENT_VERSION iš updater.py.
2. Randa didžiausią žymę lite-v* (reikia fetch-depth: 0).
3. Jei versija kode didesnė už paskutinę žymę – naudoja ją (rankinis nustatymas, pvz. 2.0.0).
4. Kitu atveju padidina paskutinę žymę pagal --bump (patch / minor / major).
5. Įrašo naują versiją į updater.py ir išveda version=X.Y.Z į $GITHUB_OUTPUT.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATER = os.path.join(os.path.dirname(HERE), "updater.py")
VERSION_RE = re.compile(r'^CURRENT_VERSION\s*=\s*"([^"]+)"', re.M)
TAG_PREFIX = "lite-v"


def parse(v):
    v = v[len(TAG_PREFIX):] if v.startswith(TAG_PREFIX) else v.lstrip("v")
    parts = [int(re.match(r"\d+", p).group(0)) if re.match(r"\d+", p) else 0 for p in re.split(r"[-+]", v)[0].split(".")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def latest_tag(cwd=None):
    out = subprocess.run(["git", "tag", "--list", f"{TAG_PREFIX}*"], capture_output=True, text=True, cwd=cwd, check=True)
    tags = [t.strip() for t in out.stdout.splitlines() if re.match(rf"^{TAG_PREFIX}\d+(\.\d+)*$", t.strip())]
    return max(tags, key=parse) if tags else None


def bump_version(v, kind):
    major, minor, patch = v
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def compute(code_version, last_tag, kind):
    code = parse(code_version)
    if last_tag is None:
        return code
    last = parse(last_tag)
    if code > last:
        return code
    return bump_version(last, kind)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bump", choices=["patch", "minor", "major"], default="patch")
    ap.add_argument("--updater", default=UPDATER)
    ap.add_argument("--git-dir", default=None)
    args = ap.parse_args(argv)

    with open(args.updater, encoding="utf-8") as f:
        src = f.read()
    m = VERSION_RE.search(src)
    if not m:
        sys.exit("CURRENT_VERSION nerasta updater.py")
    tag = latest_tag(args.git_dir)
    new = ".".join(str(x) for x in compute(m.group(1), tag, args.bump))
    src = VERSION_RE.sub(f'CURRENT_VERSION = "{new}"', src, count=1)
    with open(args.updater, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"Paskutinė žymė: {tag or '(nėra)'} | kode: {m.group(1)} | nauja: {new}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"version={new}\n")
    return new


if __name__ == "__main__":
    main()
