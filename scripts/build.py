#!/usr/bin/env python3
"""Build orchestrator for the affine-framework paper(s).

The manuscript is split into two papers: paper_mzm_zh.tex (single-MZM,
submitted first) and paper_dpmzm_zh.tex (DPMZM, experiments pending). One
command to regenerate figures and/or compile the manuscript(s), with the
right Python interpreter and with simulation stdout captured for the number
reconciliation check (see scripts/check.py).

Usage (run from anywhere; paths are resolved relative to the repo root):
    python scripts/build.py figs     # run the 3 figure scripts -> figs/*.pdf
    python scripts/build.py pdf       # latexmk -xelatex BOTH manuscripts
    python scripts/build.py all       # figs + pdf (both manuscripts)
    python scripts/build.py pdf --tex paper_mzm_zh.tex   # single manuscript

Interpreter: the figure scripts need numpy/scipy/matplotlib. If the running
interpreter has them, it is used. Otherwise set $PAPER_PYTHON to a suitable
python, or rely on the auto-detected miniconda3 fallback. The default system
python on this machine does NOT have numpy -- see CLAUDE.md.
"""
from __future__ import annotations
import os, sys, subprocess, shutil, argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "build")
FIG_SCRIPTS = ["make_figs.py", "make_extra_figs.py", "make_algo_figs.py"]
DEFAULT_MANUSCRIPTS = ["paper_mzm_zh.tex", "paper_dpmzm_zh.tex"]


def _has_numpy(py: str) -> bool:
    try:
        return subprocess.run([py, "-c", "import numpy,scipy,matplotlib"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def figure_python() -> str:
    """Resolve an interpreter that can import numpy/scipy/matplotlib."""
    if _has_numpy(sys.executable):
        return sys.executable
    env = os.environ.get("PAPER_PYTHON")
    if env and _has_numpy(env):
        return env
    candidates = [
        os.path.expanduser("~/miniconda3/python.exe"),
        os.path.expanduser("~/miniconda3/bin/python"),
        os.path.expanduser("~/anaconda3/python.exe"),
        shutil.which("python3") or "", shutil.which("python") or "",
    ]
    for c in candidates:
        if c and os.path.exists(c) and _has_numpy(c):
            return c
    sys.exit("ERROR: no interpreter with numpy/scipy/matplotlib found.\n"
             "       Set $PAPER_PYTHON to your scientific python (e.g. "
             "~/miniconda3/python.exe). See CLAUDE.md.")


def run_figs() -> int:
    py = figure_python()
    os.makedirs(BUILD, exist_ok=True)
    log_path = os.path.join(BUILD, "sim_output.txt")
    print(f"[build] figure interpreter: {py}")
    captured = []
    for s in FIG_SCRIPTS:
        path = os.path.join("scripts", s)
        print(f"[build] running {path} ...")
        # cwd=REPO so the scripts' relative 'figs/' output path resolves
        p = subprocess.run([py, path], cwd=REPO, capture_output=True, text=True)
        sys.stdout.write(p.stdout)
        if p.returncode != 0:
            sys.stderr.write(p.stderr)
            return p.returncode
        captured.append(f"### {s}\n{p.stdout}")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(captured))
    print(f"[build] simulation stdout captured -> {os.path.relpath(log_path, REPO)}")
    return 0


def run_exp_figs() -> int:
    """Render the EXPERIMENT figures (figs/fig_exp*.pdf, fig_expkappa.pdf) from
    the measured data in data/exp/ via make_exp_figs.py. Offline, no hardware;
    figures with missing data are skipped. Separate from run_figs() because it
    reads measured data, not the fixed-seed simulation (no sim stdout capture)."""
    py = figure_python()
    print(f"[build] experiment-figure interpreter: {py}")
    return subprocess.run([py, os.path.join("scripts", "make_exp_figs.py")],
                          cwd=REPO).returncode


def run_pdf(tex: str) -> int:
    print(f"[build] latexmk -xelatex {tex}")
    return subprocess.run(
        ["latexmk", "-xelatex", "-interaction=nonstopmode", tex], cwd=REPO).returncode


def run_pdf_all(manuscripts: list[str]) -> int:
    """Compile each manuscript in turn; stop at the first failure."""
    for tex in manuscripts:
        rc = run_pdf(tex)
        if rc:
            print(f"[build] latexmk FAILED on {tex} (rc={rc})")
            return rc
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", choices=["figs", "exp-figs", "pdf", "all"])
    ap.add_argument("--tex", default=None,
                     help="compile a single manuscript (pdf/all); default is "
                          "to compile both paper_mzm_zh.tex and paper_dpmzm_zh.tex")
    a = ap.parse_args()
    manuscripts = [a.tex] if a.tex else DEFAULT_MANUSCRIPTS
    rc = 0
    if a.target == "exp-figs":
        return run_exp_figs()
    if a.target in ("figs", "all"):
        rc = run_figs()
        if rc:
            return rc
    if a.target in ("pdf", "all"):
        rc = run_pdf_all(manuscripts)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
