# MZM manuscript claim--evidence map

Date: 2026-07-10

This map treats Abstract/Introduction claims as hard contracts. “Supported”
means the current repository contains direct proof or data; “bounded” means the
claim is valid only with the manuscript's explicit qualification; “needs new
evidence” means prose or reanalysis cannot close it.

| Claim | Authoritative evidence | Status |
|---|---|---|
| Any periodic pilot followed by linear receive/demodulation yields `z=A u(phi)+b+n`. | Theorem 1 and Appendix A; symbolic/fixed-seed numerical closure in `scripts/make_figs.py`. | Supported within the declared linear-chain model. |
| Full-cycle phase is identifiable iff `rank(A)=2` and the `O(2)` gauge is fixed. | Proposition 2 and its necessity/sufficiency proof. | Supported theoretically. |
| Ellipse+DC gauge recovers the label-free demodulator. | Zero-noise/noisy simulation, gauge sweep and same-scan measured offline diagnostic. | Bounded: no end-to-end label-free hardware loop yet. |
| Full affine correction removes offset and non-diagonal mixing missed by diagonal H1/H2 decoding. | Controlled simulation in Fig. 5; `measure_bench.py acceptance --sim` tooling stress. | Supported in model; needs live paired hardware evidence for an engineering claim. |
| The measured controller locks 16 targets with 246 mrad RMS. | `data/exp/lock_sweep.npz`, `results.json`, and `check.py [5]`. | Supported descriptively for phase-reference regression and the local-DMM convention. |
| The same measured result is 342 mrad under the wide-scan map. | `affine_err_map` in `lock_sweep.npz`; `reanalyze_mzm.py`. | Supported as a sensitivity convention; neither convention is independent optical truth. |
| H1-only amplitude matching suffers branch/dead-zone failures. | Measured 16-target H1 trace and two truth conventions; model equations and simulations. | Supported for this reconstructed weak baseline; not a SOTA superiority result. |
| `kappa(A)` determines anisotropy, while absolute noise also depends on `sigma_min(A)`. | Eq. (11), singular-value bound, Bessel asymptotics, and Fig. 1(c). | Supported. |
| A residual trigger detects the tested pilot-amplitude step. | One `drift.npz` run, six-cycle trigger and full-period recalibration. | Bounded: no false-alarm/miss probability or micro-arc recovery evidence. |
| RF-loaded states remain identifiable after per-state recalibration. | `rf_lock.npz`, J0 fit and eight targets per RF state. | Bounded: not fixed-calibration online RF robustness. |
| The 3 h record did not diverge. | One `stability.npz` run and 60 DMM evaluations. | Bounded: not cross-run reliability or a failure-rate estimate. |
| Runtime arithmetic is suitable for an embedded controller. | Operation count for one 2x2 multiply plus atan2. | Bounded: board latency, fixed-point error and rescan interruption remain unmeasured. |
| The contribution differs from DLA2C. | DLA2C primary paper, DOI `10.3788/COL202624.011201`; current theorem and algorithm. | Supported as a methodological distinction; no accuracy comparison is claimed. |

## Five-dimension self-review

### Contribution

- **Pass:** exact affine factorization, explicit rank/gauge identifiability and
  separation of anisotropy from absolute noise are clear knowledge claims.
- **Needs new evidence:** the engineering value of label-free calibration must be
  demonstrated live rather than inferred from simulation/offline pullback.

### Writing clarity

- **Pass:** phase-reference, ellipse, truth conventions, recalibration and RF
  procedures are now named consistently in text, scripts and captions.
- **Author input:** English conversion and final author/funding declarations are
  still required for JLT submission.

### Experimental strength

- **Pass within scope:** current real data support a supervised feasibility study.
- **Needs new evidence:** independent label-free blocks, paired calibrated-H1/H2
  baseline, opposite-side starts and independent optical validation.

### Evaluation completeness

- **Pass:** simulations include scalar, ratio and diagonal 2-D ablations; current
  measurements expose limitations and retain both truth conventions.
- **Needs new evidence:** execute the frozen acceptance protocol across sessions.

### Method soundness

- **Pass:** full-rank and gauge requirements, nonlinear receiver boundary and
  residual rotation blindness are explicit.
- **Needs new evidence:** quantify calibration failure, settling, temporal jitter
  and computation/rescan time on the live platform.
