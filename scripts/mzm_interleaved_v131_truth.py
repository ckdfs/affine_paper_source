#!/usr/bin/env python3
"""Pure donor-profile and recipient-correction helpers for MZM v1.3.1."""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as ec  # noqa: E402
import mzm_interleaved_truth as v12  # noqa: E402
import mzm_time_truth as tt  # noqa: E402


PROTOCOL_VERSION = "mzm-interleaved-calibration-v1.3.1"
DONOR_PROTOCOL_VERSION = "mzm-interleaved-spur-calibration-v1.3.1"
PILOT_V = 0.07
RECIPIENT_N_AVG = 4
DONOR_N_AVG = 8
DMM_READS_PER_SIDE = 8
ACQ_READ_ATTEMPTS = 3
DISCARD_BLOCKS = v12.DISCARD_BLOCKS
N_BLOCKS = v12.N_BLOCKS
BIAS_SETTLE_S = v12.BIAS_SETTLE_S
DISCARD_TO_FORMAL_MAX_S = v12.DISCARD_TO_FORMAL_MAX_S
HEADROOM_LIMIT_V = v12.HEADROOM_LIMIT_V
HEADROOM_LIMIT_CODE = v12.HEADROOM_LIMIT_CODE
PROFILE_CORR_MIN = 0.95
PROFILE_RELATIVE_RMS_MAX = 0.35
PROFILE_RMS_EPS = 1e-12


def build_schedule():
    return v12.build_schedule()


def schedule_records(schedule=None):
    return v12.schedule_records(build_schedule() if schedule is None else schedule)


def schedule_sha256(schedule=None):
    return v12.schedule_sha256(build_schedule() if schedule is None else schedule)


def segment_bounds(segment_index):
    return v12.segment_bounds(segment_index)


def _json_sha256(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_observation_arrays(phase_truth, role, direction, grid_index,
                                 bias, *arrays):
    schedule = build_schedule()
    values = dict(
        phase_truth=np.asarray(phase_truth, float),
        role=np.asarray(role).astype("U16"),
        direction=np.char.lower(np.asarray(direction).astype("U16")),
        grid_index=np.asarray(grid_index, int),
        bias=np.asarray(bias, float),
    )
    n = len(schedule["bias"])
    if any(len(value) != n for value in values.values()):
        raise ValueError("v1.3 donor arrays must contain all 162 observations")
    if any(len(np.asarray(value)) != n for value in arrays):
        raise ValueError("v1.3 donor observation arrays differ in length")
    if not all(np.all(np.isfinite(value)) for value in
               (values["phase_truth"], values["bias"], *arrays)):
        raise ValueError("v1.3 donor numeric arrays must be finite")
    if not np.array_equal(values["role"], schedule["role"]):
        raise ValueError("v1.3 donor role differs from frozen schedule")
    if not np.array_equal(values["direction"], schedule["direction"]):
        raise ValueError("v1.3 donor direction differs from frozen schedule")
    if not np.array_equal(values["grid_index"], schedule["grid_index"]):
        raise ValueError("v1.3 donor grid differs from frozen schedule")
    if not np.array_equal(values["bias"], schedule["bias"]):
        raise ValueError("v1.3 donor bias differs from frozen schedule")
    return values


def donor_half_means(source_sequence_index, window_index, X, Y):
    """Return fixed even/odd four-window observation means."""
    source = np.asarray(source_sequence_index, int)
    window = np.asarray(window_index, int)
    x = np.asarray(X, float)
    y = np.asarray(Y, float)
    expected = len(build_schedule()["bias"]) * DONOR_N_AVG
    if not (len(source) == len(window) == len(x) == len(y) == expected):
        raise ValueError("donor window arrays do not have the frozen size")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("donor window observations must be finite")
    if not np.array_equal(source, np.repeat(np.arange(162), DONOR_N_AVG)):
        raise ValueError("donor source sequence differs from frozen order")
    if not np.array_equal(window, np.tile(np.arange(DONOR_N_AVG), 162)):
        raise ValueError("donor window index differs from frozen order")
    x_group = x.reshape(162, DONOR_N_AVG)
    y_group = y.reshape(162, DONOR_N_AVG)
    return dict(
        X_A=np.mean(x_group[:, 0::2], axis=1),
        Y_A=np.mean(y_group[:, 0::2], axis=1),
        X_B=np.mean(x_group[:, 1::2], axis=1),
        Y_B=np.mean(y_group[:, 1::2], axis=1),
    )


def _grid_means(values, grid_index):
    values = np.asarray(values, float)
    grid_index = np.asarray(grid_index, int)
    result = np.empty(81, float)
    for index in range(81):
        mask = grid_index == index
        if np.count_nonzero(mask) != 2:
            raise ValueError(f"grid {index} must have exactly two donor observations")
        result[index] = float(np.mean(values[mask]))
    return result


def _orthogonalize_profile(profile, phase_grid):
    profile = np.asarray(profile, float)
    phase_grid = np.asarray(phase_grid, float)
    if len(profile) != 81 or len(phase_grid) != 81:
        raise ValueError("spur profile must cover exactly 81 grids")
    basis = np.stack([
        np.ones(81), np.cos(phase_grid), np.sin(phase_grid)], axis=1)
    projected = basis @ np.linalg.lstsq(basis, profile, rcond=None)[0]
    corrected = profile - projected
    if not np.all(np.isfinite(corrected)):
        raise ValueError("orthogonalized spur profile is not finite")
    return corrected


def _profile_from_half(X, Y, phase_truth, role, grid_index):
    formal = np.asarray(role).astype("U16") == "formal"
    calibration = ec.calibrate_phase_ref(
        np.asarray(X, float)[formal], np.asarray(Y, float)[formal],
        np.asarray(phase_truth, float)[formal])
    phase = np.asarray(phase_truth, float)
    predicted_x = (float(calibration["c0"][0]) +
                   calibration["A_hat"][0, 0] * np.cos(phase) +
                   calibration["A_hat"][0, 1] * np.sin(phase))
    residual = np.asarray(X, float) - predicted_x
    phase_grid = _grid_means(phase, grid_index)
    profile = _orthogonalize_profile(
        _grid_means(residual, grid_index), phase_grid)
    return calibration, profile, phase_grid


def _cross_half_metrics(X, Y, phase_truth, role, grid_index, profile):
    corrected = np.asarray(X, float) - np.asarray(profile, float)[
        np.asarray(grid_index, int)]
    roles = np.asarray(role).astype("U16")
    phase = np.asarray(phase_truth, float)
    formal = roles == "formal"
    sentinel = roles == "sentinel"
    calibration = ec.calibrate_phase_ref(
        corrected[formal], np.asarray(Y, float)[formal], phase[formal])
    formal_metrics = ec.self_check_mrad(
        corrected[formal], np.asarray(Y, float)[formal], calibration,
        phase[formal])
    sentinel_metrics = ec.self_check_mrad(
        corrected[sentinel], np.asarray(Y, float)[sentinel], calibration,
        phase[sentinel])
    passed = bool(
        formal_metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD and
        formal_metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD and
        sentinel_metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD and
        sentinel_metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD)
    return dict(
        passed=passed, formal=formal_metrics, sentinel=sentinel_metrics)


def derive_spur_correction(X_A, Y_A, X_B, Y_B, phase_truth, role,
                           direction, grid_index, bias, components):
    """Derive the preregistered independent A/B weak-axis correction table."""
    arrays = _validate_observation_arrays(
        phase_truth, role, direction, grid_index, bias,
        np.asarray(X_A, float), np.asarray(Y_A, float),
        np.asarray(X_B, float), np.asarray(Y_B, float))
    if (not isinstance(components, (list, tuple)) or len(components) != 2 or
            any(value not in ("I", "Q") for value in components)):
        raise ValueError("components must freeze one I/Q H2 and one I/Q H1 choice")
    cal_a, profile_a, phase_grid_a = _profile_from_half(
        X_A, Y_A, arrays["phase_truth"], arrays["role"],
        arrays["grid_index"])
    cal_b, profile_b, phase_grid_b = _profile_from_half(
        X_B, Y_B, arrays["phase_truth"], arrays["role"],
        arrays["grid_index"])
    if not np.allclose(phase_grid_a, phase_grid_b, atol=0, rtol=0):
        raise ValueError("donor A/B phase grids differ")
    profile = 0.5 * (profile_a + profile_b)
    profile_rms = float(np.sqrt(np.mean(profile ** 2)))
    split_rms = float(np.sqrt(np.mean((profile_a - profile_b) ** 2)))
    correlation = float(np.corrcoef(profile_a, profile_b)[0, 1])
    relative_rms = float(split_rms / max(profile_rms, PROFILE_RMS_EPS))
    a_to_b = _cross_half_metrics(
        X_B, Y_B, arrays["phase_truth"], arrays["role"],
        arrays["grid_index"], profile_a)
    b_to_a = _cross_half_metrics(
        X_A, Y_A, arrays["phase_truth"], arrays["role"],
        arrays["grid_index"], profile_b)
    finite_positive = bool(
        np.all(np.isfinite(profile_a)) and np.all(np.isfinite(profile_b)) and
        np.all(np.isfinite(profile)) and np.isfinite(correlation) and
        np.isfinite(relative_rms) and profile_rms > PROFILE_RMS_EPS)
    gates = dict(
        profile_finite_positive_pass=finite_positive,
        profile_correlation=correlation,
        profile_correlation_min=PROFILE_CORR_MIN,
        profile_correlation_pass=bool(correlation >= PROFILE_CORR_MIN),
        profile_rms_V=profile_rms,
        profile_split_rms_V=split_rms,
        profile_relative_rms=relative_rms,
        profile_relative_rms_max=PROFILE_RELATIVE_RMS_MAX,
        profile_relative_rms_pass=bool(
            relative_rms <= PROFILE_RELATIVE_RMS_MAX),
        a_to_b_cross_half_pass=bool(a_to_b["passed"]),
        b_to_a_cross_half_pass=bool(b_to_a["passed"]),
    )
    required = (
        "profile_finite_positive_pass", "profile_correlation_pass",
        "profile_relative_rms_pass", "a_to_b_cross_half_pass",
        "b_to_a_cross_half_pass")
    gates["required_pass_fields"] = required
    gates["accepted"] = bool(all(gates[name] for name in required))
    grid = np.linspace(tt.CENTER_V - tt.VPI_V, tt.CENTER_V + tt.VPI_V, 81)
    table = dict(
        protocol_version=DONOR_PROTOCOL_VERSION,
        schedule_sha256=schedule_sha256(),
        grid_index=np.arange(81, dtype=int),
        bias_V=np.asarray(grid, float),
        phase_grid=np.asarray(phase_grid_a, float),
        d_A_V=np.asarray(profile_a, float),
        d_B_V=np.asarray(profile_b, float),
        d_V=np.asarray(profile, float),
        components=np.asarray(components).astype("U1"),
    )
    serializable = {
        name: value.tolist() if isinstance(value, np.ndarray) else value
        for name, value in table.items()}
    table["table_sha256"] = _json_sha256(serializable)
    return dict(
        quality_gate=gates, cross_half=dict(a_to_b=a_to_b, b_to_a=b_to_a),
        calibration_A=dict(
            c0=np.asarray(cal_a["c0"]).tolist(),
            A_hat=np.asarray(cal_a["A_hat"]).tolist(),
            kappa=float(cal_a["kappa"])),
        calibration_B=dict(
            c0=np.asarray(cal_b["c0"]).tolist(),
            A_hat=np.asarray(cal_b["A_hat"]).tolist(),
            kappa=float(cal_b["kappa"])),
        table=table)


def validate_spur_table(table, components=None):
    required = {
        "protocol_version", "schedule_sha256", "grid_index", "bias_V",
        "phase_grid", "d_A_V", "d_B_V", "d_V", "components",
        "table_sha256"}
    if not isinstance(table, dict) or set(table) != required:
        raise ValueError("spur table field set differs from v1.3 contract")
    if table["protocol_version"] != DONOR_PROTOCOL_VERSION:
        raise ValueError("spur table protocol differs")
    if table["schedule_sha256"] != schedule_sha256():
        raise ValueError("spur table schedule hash differs")
    grid = np.linspace(tt.CENTER_V - tt.VPI_V, tt.CENTER_V + tt.VPI_V, 81)
    arrays = {
        name: np.asarray(table[name]) for name in
        ("grid_index", "bias_V", "phase_grid", "d_A_V", "d_B_V", "d_V",
         "components")}
    if not np.array_equal(arrays["grid_index"].astype(int), np.arange(81)):
        raise ValueError("spur table grid index differs")
    if not np.array_equal(arrays["bias_V"].astype(float), grid):
        raise ValueError("spur table bias differs")
    for name in ("phase_grid", "d_A_V", "d_B_V", "d_V"):
        if arrays[name].shape != (81,) or not np.all(np.isfinite(
                arrays[name].astype(float))):
            raise ValueError(f"spur table {name} is invalid")
    frozen_components = arrays["components"].astype("U1")
    if frozen_components.shape != (2,) or not np.all(np.isin(
            frozen_components, ("I", "Q"))):
        raise ValueError("spur table components are invalid")
    if components is not None and not np.array_equal(
            frozen_components, np.asarray(components).astype("U1")):
        raise ValueError("recipient components differ from donor table")
    serializable = {
        name: (np.asarray(table[name]).tolist()
               if isinstance(table[name], np.ndarray) else table[name])
        for name in required - {"table_sha256"}}
    if _json_sha256(serializable) != table["table_sha256"]:
        raise ValueError("spur table internal hash differs")
    return True


def apply_spur_correction(X, Y, grid_index, bias, table, components):
    validate_spur_table(table, components=components)
    x = np.asarray(X, float)
    y = np.asarray(Y, float)
    indices = np.asarray(grid_index, int)
    biases = np.asarray(bias, float)
    if not (len(x) == len(y) == len(indices) == len(biases)):
        raise ValueError("recipient correction arrays differ in length")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and
            np.all(np.isfinite(biases))):
        raise ValueError("recipient correction arrays must be finite")
    if np.any((indices < 0) | (indices > 80)):
        raise ValueError("recipient grid index is outside the correction table")
    expected_bias = np.asarray(table["bias_V"], float)[indices]
    if not np.array_equal(biases, expected_bias):
        raise ValueError("recipient bias does not exactly match donor grid")
    corrected = x - np.asarray(table["d_V"], float)[indices]
    if not np.all(np.isfinite(corrected)):
        raise ValueError("corrected recipient weak axis is not finite")
    return corrected, y.copy()


def self_test():
    schedule = build_schedule()
    phase = np.pi * (schedule["bias"] - tt.CENTER_V) / tt.VPI_V
    spur_grid = 0.0018 * np.sin(
        2.0 * np.pi * np.arange(81) / 5.9 +
        0.003 * np.arange(81) ** 2)
    spur = spur_grid[schedule["grid_index"]]
    rng = np.random.default_rng(20260717)
    c0 = np.array([0.002, 0.63])
    affine = np.array([[0.0062, 0.0011], [0.54, -0.23]])
    ideal = (np.stack([np.cos(phase), np.sin(phase)], axis=1) @
             affine.T + c0)
    X_A = ideal[:, 0] + spur + rng.normal(0.0, 2e-5, len(phase))
    X_B = ideal[:, 0] + spur + rng.normal(0.0, 2e-5, len(phase))
    Y_A = ideal[:, 1] + rng.normal(0.0, 2e-5, len(phase))
    Y_B = ideal[:, 1] + rng.normal(0.0, 2e-5, len(phase))
    result = derive_spur_correction(
        X_A, Y_A, X_B, Y_B, phase, schedule["role"],
        schedule["direction"], schedule["grid_index"], schedule["bias"],
        ("I", "Q"))
    assert result["quality_gate"]["accepted"]
    formal = schedule["role"] == "formal"
    sentinel = ~formal
    uncorrected_cal = ec.calibrate_phase_ref(
        X_B[formal], Y_B[formal], phase[formal])
    uncorrected_metrics = ec.self_check_mrad(
        X_B[formal], Y_B[formal], uncorrected_cal, phase[formal])
    assert (uncorrected_metrics["median"] >
            tt.SELFCHECK_MEDIAN_LIMIT_MRAD)
    corrected_x, corrected_y = apply_spur_correction(
        X_B, Y_B, schedule["grid_index"], schedule["bias"],
        result["table"], ("I", "Q"))
    cal = ec.calibrate_phase_ref(
        corrected_x[formal], corrected_y[formal], phase[formal])
    formal_metrics = ec.self_check_mrad(
        corrected_x[formal], corrected_y[formal], cal, phase[formal])
    sentinel_metrics = ec.self_check_mrad(
        corrected_x[sentinel], corrected_y[sentinel], cal, phase[sentinel])
    assert formal_metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD
    assert formal_metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD
    assert sentinel_metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD
    assert sentinel_metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD
    corrupted = dict(result["table"])
    corrupted["grid_index"] = np.asarray(corrupted["grid_index"]).copy()
    corrupted["grid_index"][3] = 4
    try:
        validate_spur_table(corrupted)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted spur grid was accepted")
    decorrelated = derive_spur_correction(
        X_A, Y_A, ideal[:, 0] + spur[::-1] + rng.normal(
            0.0, 2e-5, len(phase)), Y_B, phase, schedule["role"],
        schedule["direction"], schedule["grid_index"], schedule["bias"],
        ("I", "Q"))
    assert not decorrelated["quality_gate"]["profile_correlation_pass"]
    changed_hash = dict(result["table"])
    changed_hash["d_V"] = np.asarray(changed_hash["d_V"]).copy()
    changed_hash["d_V"][0] += 1e-6
    for bad_table, bad_components in (
            (changed_hash, ("I", "Q")),
            (result["table"], ("Q", "Q"))):
        try:
            apply_spur_correction(
                X_B, Y_B, schedule["grid_index"], schedule["bias"],
                bad_table, bad_components)
        except ValueError:
            pass
        else:
            raise AssertionError("corrupted donor contract was accepted")
    return dict(
        healthy_pass=True,
        uncorrected_formal_median_mrad=uncorrected_metrics["median"],
        profile_correlation=result["quality_gate"]["profile_correlation"],
        profile_relative_rms=result["quality_gate"]["profile_relative_rms"],
        formal_median_mrad=formal_metrics["median"],
        formal_p95_mrad=formal_metrics["p95"],
        sentinel_median_mrad=sentinel_metrics["median"],
        sentinel_p95_mrad=sentinel_metrics["p95"],
        corrupted_grid_rejected=True, decorrelated_profile_rejected=True,
        corrupted_hash_rejected=True, component_mismatch_rejected=True)


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, sort_keys=True))
