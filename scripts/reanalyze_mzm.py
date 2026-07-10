#!/usr/bin/env python3
"""Read-only sensitivity analysis for the measured single-MZM data.

Reports five-fold interleaved calibration-scan cross-validation, the two saved
lock-error conventions, and descriptive statistics for the 60 DMM samples in
the 3 h run.  It never writes data/exp or changes the headline number contract.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import exp_common as ec  # noqa: E402


def _summarize_mrad(values):
    x = np.asarray(values, float)
    return {
        "mean_mrad": float(np.mean(x)),
        "median_abs_mrad": float(np.median(np.abs(x))),
        "p95_abs_mrad": float(np.percentile(np.abs(x), 95)),
        "rms_mrad": float(np.sqrt(np.mean(x * x))),
        "max_abs_mrad": float(np.max(np.abs(x))),
    }


def calibration_cross_validation(data, folds=5):
    bias = np.asarray(data["bias"])
    X = np.asarray(data["X"])
    Y = np.asarray(data["Y"])
    dc = np.asarray(data["dc_dmm"])
    index = np.arange(len(X))
    out = {}
    for mode in ("phase-ref", "ellipse"):
        errors = []
        for fold in range(folds):
            test = index % folds == fold
            train = ~test
            _, _, vpi, v0_fit = ec.fit_dc_transfer(bias[train], dc[train])
            v0 = ec.canonical_period_center(v0_fit, vpi)
            phi_train = ec.bias_to_phase(bias[train], vpi, v0)
            phi_test = ec.bias_to_phase(bias[test], vpi, v0)
            if mode == "phase-ref":
                cal = ec.calibrate_phase_ref(X[train], Y[train], phi_train)
            else:
                cal = ec.calibrate_from_data(X[train], Y[train], dc[train])
            U = cal["B"] @ np.stack(
                [X[test] - cal["c0"][0], Y[test] - cal["c0"][1]]
            )
            phi_hat = np.arctan2(U[1], U[0])
            errors.extend(ec.wrap(phi_hat - phi_test) * 1e3)
        out[mode] = _summarize_mrad(errors)
    return out


def stability_summary(data):
    t_h = np.asarray(data["dmm_t"], float) / 3600.0
    e = np.asarray(data["dmm_err_mrad"], float)
    centered = e - np.mean(e)
    ac = np.correlate(centered, centered, mode="full")[len(e) - 1 :]
    ac /= np.arange(len(e), 0, -1)
    ac /= ac[0]
    return {
        "n_dmm": int(len(e)),
        "lag1_autocorrelation": float(ac[1]),
        "linear_slope_mrad_per_h": float(np.polyfit(t_h, e, 1)[0]),
        **_summarize_mrad(e),
    }


def main():
    exp = os.path.join(REPO, "data", "exp")
    calib = np.load(os.path.join(exp, "calib.npz"))
    lock = np.load(os.path.join(exp, "lock_sweep.npz"))
    stability = np.load(os.path.join(exp, "stability.npz"))
    report = {
        "calibration_5fold_interleaved": calibration_cross_validation(calib),
        "lock_error_conventions": {
            key: _summarize_mrad(np.asarray(lock[key]) * 1e3)
            for key in (
                "affine_err",
                "affine_err_map",
                "baseline_err",
                "baseline_err_map",
            )
        },
        "stability_dmm": stability_summary(stability),
        "limitations": [
            "Cross-validation folds share one physical calibration scan.",
            "The 60 DMM samples are time samples from one run, not repetitions.",
        ],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
