# AGENTS.md — AI maintenance guide

Single source of truth for agent instructions in this repo — `CLAUDE.md` is a
one-line stub that imports this file (`@AGENTS.md`); edit HERE, never both.

Research-paper repo: **MZM/DPMZM 任意点偏压控制的精确仿射框架** (IEEEtran journal drafts).
Two Chinese manuscripts (single-MZM, submitted first; DPMZM, experiments pending)
+ Python figure scripts + HTML derivation notes.

## TL;DR commands

```bash
make figs     # regenerate matplotlib figs/*.pdf  (+ capture sim stdout to build/sim_output.txt)
make exp-figs # render experiment figures figs/fig_exp*.pdf from measured data/exp/ (matplotlib)
make pdf      # compile BOTH paper_mzm_zh.tex and paper_dpmzm_zh.tex with latexmk -xelatex
make check    # doctor: refs / cites / figure files / NUMBER RECONCILIATION, for BOTH papers
make verify   # figs + pdf + check  (the full "regenerate and validate" loop)
```

`make pdf`/`make check`/`make all` now cover both manuscripts by default (they
loop internally). Pass `MAIN=<one .tex>` to restrict any of them to a single
manuscript for debugging, e.g. `make check MAIN=paper_mzm_zh.tex`.

No `make`? Call the scripts directly with any python3 — they re-dispatch to the
right interpreter themselves:
`python scripts/build.py figs|pdf|all` (add `--tex <one .tex>` to restrict) and
`python scripts/check.py` (add `--tex <one .tex>` likewise).

**After any edit that touches a number, a figure, or the bibliography, run `make check`.**
A green `0 FAIL` is the bar for "done" — across both papers.

## Layout

```
paper_mzm_zh.tex    # Single-MZM manuscript — submitted first. Complete: theory,
                    #   simulation, AND real bench experiments (sec:exp backfilled
                    #   from data/exp/, gated by check.py [5]).
paper_dpmzm_zh.tex  # DPMZM manuscript — theory + simulation complete; the DPMZM
                    #   bench experiments are not yet run, so its sec:exp table
                    #   rows still read "计划"/"待测" (placeholder), by design.
                    #   References the MZM paper (\cite{mzmaffine}) for the
                    #   companion single-MZM results.
paper_zh.tex        # FROZEN pre-split reference (not built/checked; do not edit —
                    #   the two papers above supersede it)
                    # paper.tex (old English draft) has been deleted; history is
                    #   in git.
figs/*.pdf          # rendered figures, committed on purpose (see RNG rule below)
data/exp/           # measured single-MZM bench data, committed: vpi.csv, calib.npz,
                    #   lock_sweep.npz, pilot_depth.csv, drift.npz, stability.npz,
                    #   results.json (the EXPERIMENT number contract; see check.py [5]).
                    #   No dp_* top-level keys yet — the DPMZM experiment specs in
                    #   check.py [5] are present but all currently skipped.
scripts/
  make_figs.py        # fig_arch/ellipse/bessel/mzmloop/torus/obs/dploop/ahat
                      #   + the [V] validation suite at the very end
  make_extra_figs.py  # fig_gauge/mcdp/sweep
  make_algo_figs.py   # fig_acq/flow/recal/step
  make_exp_figs.py    # EXPERIMENT figs (fig_exp0-3, fig_expkappa, and the
                      #   fig_exp_mzm/dpmzm schematics) from data/exp/; `make exp-figs`.
                      #   Offline; a figure whose data is absent is skipped.
  measure_bench.py    # hardware-in-loop bench driver: stages bringup/vpi/calib/lock/
                      #   pilot/drift/stability via the /biasboard /dm858e /sds824xhd
                      #   skills; PC affine + baseline controllers. `--sim` -> build/exp_sim/.
  exp_common.py       # shared experiment math (ellipse cal, phase truth, IO); numpy-only
  export_exp_link.ps1 # LEGACY: Visio .vsdx -> fig_exp_{mzm,dpmzm}.pdf (`make exp-figs-vsdx`).
                      #   Superseded — those two figs now come from make_exp_figs.py.
  build_exp_link.ps1  # LEGACY/DESTRUCTIVE: rebuild the .vsdx from scratch via Visio COM.
  build.py            # orchestrator (interpreter detection; figs/exp-figs/pdf/all)
  check.py            # read-only doctor (incl. [5] experiment reconciliation)
  paper_metrics.json  # THE SIMULATION NUMBER CONTRACT (see below)
notes/*.html        # MZM / DPMZM affine derivations (source of truth for the math)
notes/diagrams/*.drawio # reading/review aids (思路/章节/算法/实验 flowcharts);
                    #   each laid out as one A4 page. NOT paper figures — not in figs/.
build/              # generated, git-ignored (captured sim stdout etc.)
```

## Non-negotiable conventions (these are where things break)

1. **Figure interpreter.** The scripts need `numpy/scipy/matplotlib`. The default
   system `python` on this machine has none. `build.py` auto-detects miniconda3;
   override with `PAPER_PYTHON=/path/to/python`. Never assume bare `python` works
   for the figure scripts.

2. **RNG order is load-bearing.** Every script fixes a seed and consumes the RNG
   in order, so inserting RNG-drawing code *upstream* shifts every downstream
   number (and the corresponding figures). Rule: **add new computation by
   APPENDING to the end of a script**, never mid-stream. Pure recording/printing
   of already-computed values is safe anywhere.

3. **Figures are committed.** Because of (2), re-running can perturb minor values,
   so `figs/*.pdf` live in git. Regenerate deliberately, then reconcile numbers.

4. **The number contract — `scripts/paper_metrics.json`.** Every headline number
   across BOTH manuscripts (mostly Table `tab:results`) is listed there with: a
   `paper` field (`"mzm"` or `"dpmzm"`) saying which manuscript owns it, the
   literal `tex` string that must appear in *that* manuscript
   (`paper_mzm_zh.tex` or `paper_dpmzm_zh.tex`), a `sim` regex over the captured
   stdout (shared — one `build/sim_output.txt` feeds both papers), an `expect`
   value and `tol`. `check.py [4]` enforces **both directions** per paper — the
   assigned manuscript must contain the literal, and the simulation must
   reproduce it. This exists because stale hand-entered table numbers were a real
   bug. To change a number legitimately: `make figs` → read `build/sim_output.txt`
   → update `expect` in the JSON and the `tex` literal in the owning manuscript →
   add a reproducing print in the relevant script if one is missing → `make check`.

5. **Never fabricate experimental data.** `paper_mzm_zh.tex`'s `sec:exp` reports
   REAL single-MZM bench measurements (calibration, arbitrary-point lock vs
   baseline, κ(m), 3h stability, recal recovery, RF-loaded robustness) backfilled
   from `data/exp/` and gated by `check.py [5]` (checked against
   `paper_mzm_zh.tex`). `paper_dpmzm_zh.tex`'s `sec:exp` rows remain
   plan/`\placeholderbox`/"计划" — `data/exp/results.json` carries no `dp_*`
   top-level keys yet, so the DPMZM specs in `check.py [5]` are defined but
   currently all skipped (this is expected, not a bug). Only backfill values
   that were actually measured and clear the quality gate — never invent
   numbers, and keep unmeasured cells "待测"/"计划". The measurement driver
   (`measure_bench.py --sim`) writes only to `build/exp_sim/`, never `data/exp/`.

6. **PDF visual check.** `pdftoppm -png -r 110 paper_mzm_zh.pdf out` (or
   `paper_dpmzm_zh.pdf`) then read the PNG. Fonts now load **by filename**
   (kpathsea-searched), so `make pdf` works on macOS/Linux as well as Windows,
   Fandol is embedded, and **CJK renders correctly in poppler** (the old
   Adobe-GB1 blank-glyph issue is gone). Layout, math, tables and figures are
   all inspectable.

## Git

Solo-authored paper repo: **commit directly to `main`** — do not create a feature
branch (the usual "branch-first" default is unwanted here). Commit only when asked;
**never push** unless explicitly asked. Group related work into a few logical
commits rather than one giant blob. The LF→CRLF warnings on commit are normal on
Windows and harmless.

## What "good" looks like

- `make check` → `0 FAIL` for BOTH `paper_mzm_zh.tex` and `paper_dpmzm_zh.tex`.
  WARNs are advisory (e.g. an equation `\label` that is never `\ref`'d, or a
  figure reachable only through a `fig:a--fig:c` range) — read them, fix if they
  indicate a real omission, otherwise leave them.
- `latexmk -xelatex paper_mzm_zh.tex` and `latexmk -xelatex paper_dpmzm_zh.tex`
  → both clean: no undefined references, no Overfull \hbox ≥ 20pt. The only
  expected warnings are benign `Font shape ... undefined` Times/Fandol
  substitutions.
- The math in each manuscript matches `notes/*.html` and the code in `scripts/`.

## Persisted facts

Longer-lived, cross-session notes live in the user memory under
`~/.claude/projects/.../memory/` (e.g. `affine-paper-experiment-bench` — bench
results, κ/drift limits, and the measurement pitfalls). This file is the in-repo,
self-contained summary.
