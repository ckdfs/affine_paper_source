#!/usr/bin/env python3
"""Doctor / verifier for the affine-framework paper. Read-only.

Runs four families of checks and prints a PASS/WARN/FAIL report:

  1. Cross-reference integrity   -- every \\ref/\\eqref target has a \\label;
                                    flags labels that are never referenced.
  2. Citation integrity          -- every \\cite key has a \\bibitem; flags
                                    bibitems that are never cited.
  3. Figure integrity            -- every \\includegraphics file exists.
  4. Number reconciliation       -- every entry in scripts/paper_metrics.json
                                    occurs literally in the .tex AND is
                                    reproduced (within tol) by the captured
                                    simulation stdout (build/sim_output.txt).
  (+) LaTeX log scan             -- Overfull \\hbox and undefined references,
                                    if <tex>.log is present.

Usage:
    python scripts/check.py                 # checks paper_zh.tex
    python scripts/check.py --tex paper.tex
    python scripts/check.py --no-sim        # skip reconciliation

Reconciliation needs build/sim_output.txt; regenerate it with
    python scripts/build.py figs
Exit code is nonzero if any FAIL was reported.
"""
from __future__ import annotations
import os, re, sys, json, argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, Y, R, X = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
_fails = 0
_warns = 0


def _emit(level: str, msg: str) -> None:
    global _fails, _warns
    if level == "FAIL":
        _fails += 1; print(f"  {R}FAIL{X} {msg}")
    elif level == "WARN":
        _warns += 1; print(f"  {Y}WARN{X} {msg}")
    else:
        print(f"  {G}ok  {X} {msg}")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def check_refs(tex: str) -> None:
    print("[1] cross-reference integrity")
    labels = set(re.findall(r"\\label\{([^}]+)\}", tex))
    refs = set()
    for m in re.findall(r"\\(?:ref|eqref|cref|Cref|autoref)\{([^}]+)\}", tex):
        refs.update(k.strip() for k in m.split(","))
    undefined = sorted(refs - labels)
    unused = sorted(labels - refs)
    if undefined:
        _emit("FAIL", f"\\ref to undefined label(s): {', '.join(undefined)}")
    if unused:
        _emit("WARN", f"label(s) defined but never \\ref'd: {', '.join(unused)}")
    if not undefined and not unused:
        _emit("ok", f"{len(labels)} labels all defined and referenced")


def check_cites(tex: str) -> None:
    print("[2] citation integrity")
    bib = set(re.findall(r"\\bibitem\{([^}]+)\}", tex))
    cites = set()
    for m in re.findall(r"\\cite\{([^}]+)\}", tex):
        cites.update(k.strip() for k in m.split(","))
    if not bib:
        _emit("WARN", "no \\bibitem found (external .bib?) -- skipping")
        return
    missing = sorted(cites - bib)
    uncited = sorted(bib - cites)
    if missing:
        _emit("FAIL", f"\\cite to missing bibitem(s): {', '.join(missing)}")
    if uncited:
        _emit("WARN", f"bibitem(s) never cited: {', '.join(uncited)}")
    if not missing and not uncited:
        _emit("ok", f"{len(bib)} references all cited and defined")


def check_figs(tex: str) -> None:
    print("[3] figure file integrity")
    missing = []
    for path in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex):
        cand = [os.path.join(REPO, path)]
        if not os.path.splitext(path)[1]:
            cand += [os.path.join(REPO, path + e) for e in (".pdf", ".png", ".jpg")]
        if not any(os.path.exists(c) for c in cand):
            missing.append(path)
    if missing:
        _emit("FAIL", f"missing figure file(s): {', '.join(missing)}")
    else:
        _emit("ok", "all \\includegraphics targets exist")


def check_log(tex_name: str) -> None:
    print("[+] LaTeX log scan")
    log = os.path.join(REPO, os.path.splitext(tex_name)[0] + ".log")
    if not os.path.exists(log):
        _emit("WARN", f"{os.path.basename(log)} not found -- compile first to scan")
        return
    text = read(log)
    if re.search(r"There were undefined references", text) or \
       re.search(r"Citation `[^']+' on page .* undefined", text):
        _emit("FAIL", "log reports undefined references/citations")
    else:
        _emit("ok", "no undefined references in log")
    over = [int(m) for m in re.findall(r"Overfull \\hbox \((\d+)\.\d+pt", text)]
    big = [o for o in over if o >= 20]
    if big:
        _emit("WARN", f"{len(big)} Overfull \\hbox >=20pt (worst {max(big)}pt)")
    else:
        _emit("ok", f"no Overfull \\hbox >=20pt ({len(over)} minor)")


def _num(s: str) -> float:
    return float(s)


def check_metrics(tex: str, use_sim: bool) -> None:
    print("[4] number reconciliation (paper_metrics.json)")
    mpath = os.path.join(REPO, "scripts", "paper_metrics.json")
    if not os.path.exists(mpath):
        _emit("WARN", "scripts/paper_metrics.json not found -- skipping")
        return
    metrics = json.loads(read(mpath))["metrics"]
    sim = None
    if use_sim:
        sp = os.path.join(REPO, "build", "sim_output.txt")
        if os.path.exists(sp):
            sim = read(sp)
        else:
            _emit("WARN", "build/sim_output.txt missing -- run build.py figs "
                          "for the sim side (checking tex side only)")
    for m in metrics:
        name, lit = m["name"], m["tex"]
        # (a) tex side: the literal must appear in the manuscript
        if lit not in tex:
            _emit("FAIL", f"{name}: literal not found in tex -> {lit!r} "
                          f"(table/prose drifted?)")
            continue
        # (b) sim side: regex must match and value be within tol
        if sim is None or "sim" not in m:
            _emit("ok", f"{name}: tex literal present")
            continue
        mo = re.search(m["sim"], sim)
        if not mo:
            _emit("FAIL", f"{name}: sim regex no match -> {m['sim']!r} "
                          f"(print label changed?)")
            continue
        try:
            val = _num(mo.group(1))
        except (IndexError, ValueError):
            _emit("FAIL", f"{name}: sim value unparseable from {mo.group(0)!r}")
            continue
        exp, tol = m["expect"], m["tol"]
        bound = tol * abs(exp) if m.get("rel") else tol
        if abs(val - exp) <= bound:
            _emit("ok", f"{name}: tex+sim agree (sim={val:g}, expect={exp:g})")
        else:
            _emit("FAIL", f"{name}: sim={val:g} vs expect={exp:g} (tol {bound:g}) "
                          f"-- update paper_metrics.json AND the .tex")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tex", default="paper_zh.tex")
    ap.add_argument("--no-sim", action="store_true", help="skip simulation reconciliation")
    a = ap.parse_args()
    tex_path = os.path.join(REPO, a.tex)
    if not os.path.exists(tex_path):
        sys.exit(f"ERROR: {a.tex} not found in {REPO}")
    tex = read(tex_path)
    print(f"=== checking {a.tex} ===")
    check_refs(tex)
    check_cites(tex)
    check_figs(tex)
    check_metrics(tex, use_sim=not a.no_sim)
    check_log(a.tex)
    print(f"\nsummary: {G}{'no fails' if not _fails else ''}{X}"
          f"{R}{_fails} FAIL{X} / {Y}{_warns} WARN{X}")
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
