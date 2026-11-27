#!/usr/bin/env python3
"""Build a runnable folder for one December program branch.

A program branch (pubpartner, alex, ...) holds only its own files. The shared
files it imports live on other December branches. This script never copies
those files into the program branch. Instead STANDALONE_DEPS.json pins each one
by branch, path and Git blob ID, and this script writes the program's files plus
those exact blobs into an output folder you can run and test.

Usage (PowerShell 5 or any shell):
  python tools/standalone/assemble.py build --out <folder>
  python tools/standalone/assemble.py check            # pinned blobs vs branch tips
  python tools/standalone/assemble.py discover <entry files...>  # rewrite the pins

Run it from the program branch's checkout. Git must be on PATH and the source
branches fetched (git fetch origin main-assembly pubpartner alex blackbox 2i).
"""
from __future__ import annotations

import argparse
import ast
import re
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "STANDALONE_DEPS.json"
# Where a shared file is looked for, in order, when discover pins it: the
# program branches first, because each piece lives on its own branch, then
# main-assembly for the shared PubCast files.
SOURCE_BRANCHES = ["pubpartner", "alex", "blackbox", "2i", "main-assembly"]
# Top-level packages that December code imports by path.
LOCAL_PACKAGES = ("modules", "companion_support", "pubpartner", "blackbox_event_language",
                  "blackbox_recorder", "iteration_wallet")
# Hosts, not dependencies: a standalone program is run without them.
HOSTS = {"main", "pubpartner_app", "run_reach", "start_reach"}


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace").strip()


# discover --use alex=claude/eq-prep-2026-11-27 reads that branch in place of
# alex, for a program branch's prep work that is not folded in yet.
USE: dict[str, str] = {}


def remote_ref(branch: str) -> str:
    return f"origin/{branch}"


def blob_at(branch: str, path: str) -> str | None:
    try:
        out = git("rev-parse", "--verify", "-q", f"{remote_ref(branch)}:{path}")
        return out or None
    except subprocess.CalledProcessError:
        return None


def own_files() -> list[str]:
    return [p for p in git("ls-files").splitlines() if p]


def module_to_candidates(name: str) -> list[str]:
    parts = name.split(".")
    base = "/".join(parts)
    return [base + ".py", base + "/__init__.py"]


def imports_of(source: str, path: str) -> set[str]:
    """Every module name a file imports, including imports inside functions."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return set()
    pkg = path[:-3].replace("/", ".") if path.endswith(".py") else ""
    if pkg.endswith(".__init__"):
        pkg = pkg[: -len(".__init__")]
    else:
        pkg = pkg.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".") if pkg else []
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            if mod:
                names.add(mod)
                for a in node.names:  # "from modules import auth" names a submodule
                    if a.name != "*":
                        names.add(f"{mod}.{a.name}")
    return names


STATIC_REF = re.compile(r"""/static/([A-Za-z0-9_./-]+\.(?:html|js|css|json|svg|png|webp))""")
JS_REL_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["'](\.{1,2}/[^"']+\.js)["']""")
STATIC_DIR_REF = re.compile(r"""STATIC_DIR\s*/\s*["']([A-Za-z0-9_./-]+)["']""")


def static_refs(source: str, path: str) -> set[str]:
    """Pages and scripts this file serves or loads from static/, as repo paths."""
    found = set(STATIC_REF.findall(source))
    if path.endswith(".py"):
        found |= set(STATIC_DIR_REF.findall(source))
    out = {"static/" + f.lstrip("./") for f in found if ".." not in f}
    if path.endswith(".js"):
        # ES module imports by relative path, as in the vendored three.js files.
        for rel in JS_REL_IMPORT.findall(source):
            joined = os.path.normpath(os.path.join(os.path.dirname(path), rel)).replace(os.sep, "/")
            if joined.startswith("static/"):
                out.add(joined)
    return out


def is_local(name: str) -> bool:
    top = name.split(".")[0]
    return top in LOCAL_PACKAGES or top in HOSTS


def discover(entries: list[str]) -> dict:
    own = set(own_files())
    pins: dict[str, dict] = {}
    unresolved: set[str] = set()
    seen: set[str] = set()
    queue = list(entries)

    def text_of(path: str) -> str | None:
        if path in own:
            return (ROOT / path).read_text(encoding="utf-8", errors="replace")
        if path in pins:
            return git("cat-file", "blob", pins[path]["blob"])
        return None

    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        if not path.endswith((".py", ".html", ".js", ".css")):
            continue
        src = text_of(path)
        if src is None:
            continue
        # Static pages and scripts are found by their /static/ paths, not imports.
        for ref in sorted(static_refs(src, path)):
            if ref in own or ref in pins:
                queue.append(ref)
                continue
            for br in (USE.get(x, x) for x in SOURCE_BRANCHES):
                b = blob_at(br, ref)
                if b:
                    pins[ref] = {"path": ref, "branch": br, "blob": b}
                    queue.append(ref)
                    break
            else:
                unresolved.add(ref)
        if not path.endswith(".py"):
            continue
        for name in sorted(imports_of(src, path)):
            if not is_local(name) or name.split(".")[0] in HOSTS:
                continue
            # A package's __init__ runs before any submodule it holds.
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                sub = ".".join(parts[:i])
                found = False
                for cand in module_to_candidates(sub):
                    if cand in own:
                        queue.append(cand)
                        found = True
                        break
                    if cand in pins:
                        found = True
                        break
                    for br in (USE.get(x, x) for x in SOURCE_BRANCHES):
                        b = blob_at(br, cand)
                        if b:
                            pins[cand] = {"path": cand, "branch": br, "blob": b}
                            queue.append(cand)
                            found = True
                            break
                    if found:
                        break
                if not found and i == len(parts):
                    # "from modules import auth_routes" may name an attribute, not a module.
                    unresolved.add(sub)
    return {"pins": sorted(pins.values(), key=lambda d: d["path"]),
            "unresolved": sorted(u for u in unresolved
                                 if not any(c in own or c in pins for c in module_to_candidates(u.rpartition('.')[0])) or u.count('.') == 0)}


def build(out: Path) -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        print(f"refusing: {out} is not empty", file=sys.stderr)
        return 2
    for path in own_files():
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = ROOT / path
        if src.is_file():
            dest.write_bytes(src.read_bytes())
    missing = 0
    for pin in data["pins"]:
        dest = out / pin["path"]
        if dest.exists():
            print(f"refusing: {pin['path']} is a program file and also pinned", file=sys.stderr)
            return 3
        try:
            body = git("cat-file", "blob", pin["blob"], binary=True)
        except subprocess.CalledProcessError:
            print(f"missing blob {pin['blob']} for {pin['path']} (fetch {pin['branch']})", file=sys.stderr)
            missing += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    print(f"built {out}: {len(own_files())} program files, {len(data['pins']) - missing} pinned shared files")
    return 1 if missing else 0


def check() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    drift = 0
    for pin in data["pins"]:
        now = blob_at(pin["branch"], pin["path"])
        if now != pin["blob"]:
            drift += 1
            print(f"changed on {pin['branch']}: {pin['path']} pinned {pin['blob'][:10]} now {(now or 'gone')[:10]}")
    print("all pins match their branch tips" if not drift else f"{drift} pinned files changed since pinning")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", required=True)
    sub.add_parser("check")
    d = sub.add_parser("discover"); d.add_argument("entries", nargs="+")
    d.add_argument("--note", default="")
    d.add_argument("--use", action="append", default=[], metavar="BRANCH=OTHER",
                   help="read OTHER in place of BRANCH, e.g. alex=claude/eq-prep-2026-11-27")
    args = ap.parse_args()
    if args.cmd == "build":
        return build(Path(args.out).resolve())
    if args.cmd == "check":
        return check()
    for item in args.use:
        k, _, v = item.partition("=")
        if k not in SOURCE_BRANCHES or not v:
            ap.error(f"--use wants BRANCH=OTHER with BRANCH one of {SOURCE_BRANCHES}")
        USE[k] = v
    result = discover(args.entries)
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    manifest = {
        "about": "Shared files this program imports, pinned by blob. Built into a run folder by tools/standalone/assemble.py; never copied into this branch.",
        "program": old.get("program") or git("rev-parse", "--abbrev-ref", "HEAD"),
        "entries": args.entries,
        "source_order": [USE.get(x, x) for x in SOURCE_BRANCHES],
        "pins": result["pins"],
        "unresolved_imports": result["unresolved"],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"pinned {len(result['pins'])} files; unresolved: {result['unresolved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
