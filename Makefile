# Affine-framework paper -- maintenance entry points.
# Thin wrappers over scripts/build.py and scripts/check.py so that a human or
# an AI agent has one obvious command per task. See CLAUDE.md for details.
#
# The figure scripts need numpy/scipy/matplotlib; build.py auto-detects a
# suitable interpreter (override with PAPER_PYTHON=...). PY is only the driver
# for build.py/check.py themselves and may be any python3.
#
# NOTE: the manuscript variable is MAIN, not TEX -- TeX Live exports TEX=tex
# into the environment, which would shadow a variable named TEX.

PY   ?= python
MAIN ?= paper_zh.tex

.PHONY: all figs exp-figs exp-figs-vsdx pdf check verify clean help

help:
	@echo "make figs   - regenerate matplotlib figs/*.pdf and capture sim stdout"
	@echo "make exp-figs - render experiment figures (figs/fig_exp*.pdf) from data/exp/"
	@echo "make pdf    - compile $(MAIN) with latexmk -xelatex"
	@echo "make all    - figs + pdf"
	@echo "make check  - run the doctor (refs/cites/figs/number reconciliation)"
	@echo "make verify - figs + pdf + check  (full regenerate-and-validate)"
	@echo "make clean  - remove LaTeX aux files and build/"
	@echo "vars: MAIN=$(MAIN)  PY=$(PY)  (PAPER_PYTHON overrides the figure interpreter)"

figs:
	$(PY) scripts/build.py figs

# Experiment figures (fig_exp0-3, fig_expkappa, and the fig_exp_mzm/dpmzm
# schematics) are rendered by make_exp_figs.py from the measured data in
# data/exp/. Offline; a figure whose data is absent is skipped. Kept separate
# from `figs` (the fixed-seed simulation scripts) and from `verify`.
exp-figs:
	$(PY) scripts/build.py exp-figs

# LEGACY: fig_exp_mzm/dpmzm were once hand-edited Visio drawings (figs/*.vsdx)
# re-exported here; they are now generated programmatically by `make exp-figs`.
# Retained for reference -- run by hand only if reverting to the Visio source.
exp-figs-vsdx:
	pwsh -NoProfile -File scripts/export_exp_link.ps1

pdf:
	$(PY) scripts/build.py pdf --tex $(MAIN)

all:
	$(PY) scripts/build.py all --tex $(MAIN)

check:
	$(PY) scripts/check.py --tex $(MAIN)

verify: all check

clean:
	latexmk -C $(MAIN) || true
	rm -rf build
