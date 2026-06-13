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

.PHONY: all figs pdf check verify clean help

help:
	@echo "make figs   - regenerate figs/*.pdf and capture sim stdout"
	@echo "make pdf    - compile $(MAIN) with latexmk -xelatex"
	@echo "make all    - figs + pdf"
	@echo "make check  - run the doctor (refs/cites/figs/number reconciliation)"
	@echo "make verify - figs + pdf + check  (full regenerate-and-validate)"
	@echo "make clean  - remove LaTeX aux files and build/"
	@echo "vars: MAIN=$(MAIN)  PY=$(PY)  (PAPER_PYTHON overrides the figure interpreter)"

figs:
	$(PY) scripts/build.py figs

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
