# Experimental-data manifest

This directory contains the processed bench records used by
`paper_mzm_zh.tex`.  All phase-like arrays are in radians unless their key ends
in `_mrad`; voltages are in volts, time is in seconds, frequencies are in hertz,
and RF powers are in dBm.  These files are real measurements, not output from
`measure_bench.py --sim` (simulation output is written under `build/exp_sim/`).

## Measurement and evaluation provenance

- Optical device: one LiNbO3 MZM at room conditions.
- Controller front end: STM32H523 board, DAC8568 bias output and ADS131M02
  acquisition at 64 kS/s; 1 kHz pilot and 2 kHz second harmonic.
- DC instrument: RIGOL DM858E at DE4.  It supplies the unclipped DC scan used
  to generate the phase labels for the reported `phase-ref` calibration.
- AC cross-check: Siglent SDS824X HD at DE2.
- RF stage: 50 MHz tone; each RF power state was recalibrated separately.
- The board/PD and DMM share one optical branch.  The DMM is independent of the
  board ADC electronics, not an independent optical phase reference.
- Device serial numbers, firmware commit, ambient-temperature log, schematic,
  and the laboratory helper packages are not present in this snapshot.  The
  data can reproduce the paper figures but cannot by itself reproduce a new
  hardware acquisition.

## Files used by the single-MZM paper

| File | Content and interpretation |
|---|---|
| `vpi.csv` | Bidirectional DC bias sweep used to estimate the headline (V_\pi). |
| `calib.npz` | 181-point full-period calibration scan: bias, H1/H2 I/Q, DMM DC, board DC, selected (X,Y), pilot and averaging metadata. |
| `calib_fit.json` | Reported `phase-ref` fit plus the ellipse-only offline diagnostic.  The 27.3 mrad result is in-sample; it is not held-out accuracy. |
| `lock_sweep.npz` | Sixteen target phases.  `affine_err`/`baseline_err` use the hybrid local-DMM convention; `*_err_map` use the wide-sweep bias-to-phase map.  Each target contributes one final steady-state error, so the headline RMS is across target points, not time-sample jitter. |
| `pilot_depth.csv` | Pilot-depth scan and fitted ellipse condition number. |
| `drift.npz` | One pilot-amplitude step, circle-residual trace, six-cycle trigger and post-trigger record.  Recalibration was a 121-point full-period phase-reference sweep. |
| `stability.npz` | One 3 h run: 6078 controller samples and 60 DMM evaluation samples.  These correlated samples are not independent experimental repetitions. |
| `rf_lock.npz` | Six static RF states and eight target phases per state.  Every state was recalibrated before locking; the file does not test fixed-calibration RF switching. |
| `results.json` | Literal headline-number contract checked by `scripts/check.py`; it is a summary, not an independent provenance record. |

`pilot_diag.csv` is a diagnostic scan not used for a headline result.  Files
whose names begin with `dp_` belong to the separate DPMZM work and do not support
claims in `paper_mzm_zh.tex`.

## Reproduction

```bash
make exp-figs
make pdf MAIN=paper_mzm_zh.tex
make check MAIN=paper_mzm_zh.tex
/opt/miniconda3/bin/python scripts/reanalyze_mzm.py
```

The first command rebuilds the experimental figures from these records; the
second compiles the manuscript; the third checks citations, figure paths,
simulation-number contracts, and the literal experiment-number contract.  The
last command prints the read-only cross-validation, paired truth-convention,
and 3 h descriptive sensitivity analysis used in the revised discussion.

## Acceptance experiment contract (not yet measured)

The current snapshot contains no `acceptance/` directory. New label-free
hardware evidence must be written to a new immutable
`data/exp/acceptance/<run-id>/` directory with:

- a fresh bidirectional Vpi scan and ellipse+DC-gauge calibration per repetition;
- randomized target order and balanced controller/start-side order;
- paired full-affine, calibrated-H1/H2 and H1-only traces;
- at least six calibration blocks across at least two bench sessions;
- a separate optical validation-channel pre/post scan (`truth_prepost.npz`).

The analyzer deliberately keeps the independent-truth gate false until the
isolated-channel acquisition and blind scoring schema are implemented. Merely
placing a file with this name cannot pass the paper gate. Interrupted repetitions
remain in their immutable session directory and count as failed/incomplete blocks.

The preregistered acquisition and analysis are implemented by:

```bash
/opt/miniconda3/bin/python scripts/measure_bench.py acceptance --help
/opt/miniconda3/bin/python scripts/analyze_mzm_acceptance.py --help
```

Simulated smoke runs are isolated under `build/exp_sim/acceptance/`, are marked
`simulated=true`, and cannot set `paper_acceptance_ready=true`. The full frozen
protocol and thresholds are recorded in
`reviews/mzm_acceptance_experiment_protocol.md`.

## SHA-256 snapshot

```text
3fcbcc3c19ed6afcf15e7cd9affb84427ddcc110ff6fe0d20f8e8261b80eaea2  calib.npz
01617700e5fb805e7ff391951eeac92100706ad047e51e29e1b5e497ae26720a  lock_sweep.npz
c4abb6f7cf7c3bc2e2970a5ca98667a7d9b3bef3b4ab74017d69d71193e2099b  drift.npz
98ae0cffd8a922ad99476e87252c687f3d03aad2ebb8b5c75b1a189a7a4ae29e  rf_lock.npz
6f24c3c7c5915e76ad9a3dd42a2bb0c123bb8d122183afca50283611cad6feaa  stability.npz
2548a7a368bde6db898895024bb3e419d4632dcb151d61cb4f13ab5500e2796e  results.json
```
