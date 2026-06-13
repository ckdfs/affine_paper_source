# CLAUDE.md — AI maintenance guide

Research-paper repo: **MZM/DPMZM 任意点偏压控制的精确仿射框架** (IEEEtran journal draft).
Bilingual manuscript + Python figure scripts + HTML derivation notes.

## TL;DR commands

```bash
make figs     # regenerate figs/*.pdf  (+ capture sim stdout to build/sim_output.txt)
make pdf      # compile paper_zh.tex with latexmk -xelatex
make check    # doctor: refs / cites / figure files / NUMBER RECONCILIATION
make verify   # figs + pdf + check  (the full "regenerate and validate" loop)
```

No `make`? Call the scripts directly with any python3 — they re-dispatch to the
right interpreter themselves:
`python scripts/build.py figs|pdf|all` and `python scripts/check.py`.

**After any edit that touches a number, a figure, or the bibliography, run `make check`.**
A green `0 FAIL` is the bar for "done".

## Layout

```
paper_zh.tex        # PRIMARY manuscript (the one we maintain)
paper.tex           # English version — LAGS the Chinese (missing the algorithm
                    #   and experiment sections). Do not touch unless asked to sync.
figs/*.pdf          # rendered figures, committed on purpose (see RNG rule below)
scripts/
  make_figs.py        # fig_arch/ellipse/bessel/mzmloop/torus/obs/dploop/ahat
                      #   + the [V] validation suite at the very end
  make_extra_figs.py  # fig_gauge/mcdp/sweep
  make_algo_figs.py   # fig_acq/flow/recal/step
  build_exp_link.ps1  # fig_exp_mzm / fig_exp_dpmzm — EDITABLE VISIO, NOT matplotlib
                      #   (Visio COM reuses device shapes from a .vsdx stencil;
                      #    *.vsdx sources live in figs/. make_figs does NOT touch
                      #    these two PDFs — run this script to regenerate them.)
  build.py            # orchestrator (interpreter detection + stdout capture)
  check.py            # read-only doctor
  paper_metrics.json  # THE NUMBER CONTRACT (see below)
notes/*.html        # MZM / DPMZM affine derivations (source of truth for the math)
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
   in the manuscript (mostly Table `tab:results`) is listed there with: the
   literal `tex` string that must appear in `paper_zh.tex`, a `sim` regex over
   the captured stdout, an `expect` value and `tol`. `check.py` enforces **both
   directions** — the paper must contain the literal, and the simulation must
   reproduce it. This exists because stale hand-entered table numbers were a real
   bug. To change a number legitimately: `make figs` → read `build/sim_output.txt`
   → update `expect` in the JSON and the `tex` literal in the manuscript → add a
   reproducing print in the relevant script if one is missing → `make check`.

5. **Never fabricate experimental data.** Section `sec:exp` is a *plan* with
   placeholder figures (`\placeholderbox`) and "待测" cells. Strengthen the plan,
   metrics, and methodology, but do not invent measured numbers.

6. **PDF visual check.** Use `pdftoppm -png -r 90 paper_zh.pdf out` then read the
   PNG. poppler lacks the Adobe-GB1 pack, so **CJK glyphs render blank** — that is
   a viewer limitation, not a PDF defect. Layout, math, tables, and figures are
   still inspectable. (At higher dpi poppler floods stderr with Adobe-GB1 errors;
   ignore them.)

## Git

Solo-authored paper repo: **commit directly to `main`** — do not create a feature
branch (the usual "branch-first" default is unwanted here). Commit only when asked;
**never push** unless explicitly asked. Group related work into a few logical
commits rather than one giant blob. The LF→CRLF warnings on commit are normal on
Windows and harmless.

## What "good" looks like

- `make check` → `0 FAIL`. WARNs are advisory (e.g. an equation `\label` that is
  never `\ref`'d, or a figure reachable only through a `fig:a--fig:c` range) — read
  them, fix if they indicate a real omission, otherwise leave them.
- `latexmk -xelatex paper_zh.tex` → clean: no undefined references, no Overfull
  \hbox ≥ 20pt. The only expected warnings are benign `Font shape ... undefined`
  Times/Fandol substitutions.
- The math in the manuscript matches `notes/*.html` and the code in `scripts/`.

## Persisted facts

Longer-lived, cross-session notes live in the user memory under
`~/.claude/projects/.../memory/` (`affine-paper-build-env`,
`affine-paper-results-table`). This file is the in-repo, self-contained summary.
