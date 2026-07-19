#!/usr/bin/env python3
"""Pure schedule and observer-map helpers for local paired MZM calibration."""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as ec  # noqa: E402
import mzm_time_truth as tt  # noqa: E402


PROTOCOL_VERSION = "mzm-interleaved-calibration-v1.2"
PILOT_V = 0.08
N_BLOCKS = 16
N_AVG = 4
DISCARD_BLOCKS = 6
BIAS_SETTLE_S = 0.500
DISCARD_TO_FORMAL_MAX_S = 2.000
HEADROOM_LIMIT_V = 0.95
HEADROOM_LIMIT_CODE = 6_640_981
SEGMENT_COUNT = 3
TARGETS_PER_SEGMENT = 27
OBSERVATIONS_PER_SEGMENT = 2 * TARGETS_PER_SEGMENT


def segment_bounds(segment_index):
    index = int(segment_index)
    if index < 0 or index >= SEGMENT_COUNT:
        raise ValueError("segment index must be 0, 1, or 2")
    start = index * OBSERVATIONS_PER_SEGMENT
    return start, start + OBSERVATIONS_PER_SEGMENT


def target_order():
    rng = np.random.default_rng(20260717)
    permutation = rng.permutation(np.arange(1, 40))
    order = [0, 80]
    for ordinal, low in enumerate(permutation):
        pair = [int(low), int(80 - low)]
        order.extend(pair if ordinal % 2 == 0 else pair[::-1])
    order.append(40)
    if len(order) != 81 or len(set(order)) != 81:
        raise AssertionError("frozen target order is not a permutation")
    return np.asarray(order, dtype=int)


def build_schedule():
    grid = np.linspace(
        tt.CENTER_V - tt.VPI_V, tt.CENTER_V + tt.VPI_V,
        tt.POINTS_PER_LEG)
    step = float(grid[1] - grid[0])
    role = []
    direction = []
    grid_index = []
    bias = []
    approach_bias = []
    target_ordinal = []
    pair_position = []
    for ordinal, index in enumerate(target_order()):
        value = grid[index]
        point_role = ("sentinel" if index % tt.SENTINEL_MODULUS == 0
                      else "formal")
        names = (("up", -1.0), ("down", 1.0))
        if ordinal % 2 == 1:
            names = names[::-1]
        for position, (name, sign) in enumerate(names):
            role.append(point_role)
            direction.append(name)
            grid_index.append(index)
            bias.append(float(value))
            approach_bias.append(float(value + sign * step))
            target_ordinal.append(ordinal)
            pair_position.append(position)
    n = len(bias)
    return dict(
        role=np.asarray(role, dtype="U8"),
        direction=np.asarray(direction, dtype="U4"),
        grid_index=np.asarray(grid_index, dtype=int),
        target_ordinal=np.asarray(target_ordinal, dtype=int),
        pair_position=np.asarray(pair_position, dtype=int),
        bias=np.asarray(bias, dtype=float),
        approach_bias=np.asarray(approach_bias, dtype=float),
        sequence_index=np.arange(n, dtype=int),
    )


def schedule_records(schedule=None):
    schedule = build_schedule() if schedule is None else schedule
    return [dict(
        role=str(schedule["role"][index]),
        direction=str(schedule["direction"][index]),
        grid_index=int(schedule["grid_index"][index]),
        target_ordinal=int(schedule["target_ordinal"][index]),
        pair_position=int(schedule["pair_position"][index]),
        bias_V=float(schedule["bias"][index]),
        approach_bias_V=float(schedule["approach_bias"][index]),
        sequence_index=int(schedule["sequence_index"][index]),
    ) for index in range(len(schedule["bias"]))]


def schedule_sha256(schedule=None):
    payload = json.dumps(
        schedule_records(schedule), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_schedule_arrays(role, direction, grid_index, target_ordinal,
                             pair_position, bias, approach_bias,
                             sequence_index, start=0, end=None):
    frozen = build_schedule()
    end = len(frozen["bias"]) if end is None else int(end)
    start = int(start)
    if start < 0 or end > len(frozen["bias"]) or start >= end:
        raise ValueError("invalid schedule slice")
    frozen = {name: value[start:end] for name, value in frozen.items()}
    values = dict(
        role=np.asarray(role).astype("U8"),
        direction=np.asarray(direction).astype("U4"),
        grid_index=np.asarray(grid_index, int),
        target_ordinal=np.asarray(target_ordinal, int),
        pair_position=np.asarray(pair_position, int),
        bias=np.asarray(bias, float),
        approach_bias=np.asarray(approach_bias, float),
        sequence_index=np.asarray(sequence_index, int),
    )
    failed = [name for name in frozen
              if not np.array_equal(values[name], frozen[name])]
    if failed:
        raise ValueError("recorded interleaved schedule differs in " +
                         ", ".join(failed))
    step = float(2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1))
    signed = values["bias"] - values["approach_bias"]
    expected = np.where(values["direction"] == "up", step, -step)
    if not np.allclose(signed, expected, atol=1e-12, rtol=0):
        raise ValueError("approach direction or step differs from frozen contract")
    if np.max(np.abs(values["approach_bias"])) >= 0.995 * tt.BIAS_LIMIT_V:
        raise ValueError("approach bias exceeds frozen rail")
    if start == 0 and end == len(build_schedule()["bias"]):
        formal = values["role"] == "formal"
        direction_code = np.where(values["direction"] == "up", 1.0, -1.0)
        if (np.count_nonzero(formal & (values["pair_position"] == 0) &
                             (values["direction"] == "up")) != 36 or
                np.count_nonzero(formal & (values["pair_position"] == 0) &
                                 (values["direction"] == "down")) != 36):
            raise ValueError("formal up-first/down-first balance differs")
        if not np.isclose(np.corrcoef(
                direction_code[formal], values["pair_position"][formal])[0, 1],
                0.0, atol=1e-15, rtol=0):
            raise ValueError("direction and pair position are not orthogonal")
        if not np.isclose(np.corrcoef(
                direction_code[formal], values["bias"][formal])[0, 1],
                0.0, atol=1e-15, rtol=0):
            raise ValueError("direction and target bias are not orthogonal")
    return True


def analyze_direction_mapping(X, Y, phase_truth, role, direction):
    x = np.asarray(X, float)
    y = np.asarray(Y, float)
    phi = np.asarray(phase_truth, float)
    roles = np.asarray(role).astype("U16")
    directions = np.char.lower(np.asarray(direction).astype("U16"))
    n = len(x)
    if any(len(value) != n for value in (y, phi, roles, directions)):
        raise ValueError("interleaved mapping arrays must have equal length")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and
            np.all(np.isfinite(phi))):
        raise ValueError("mapping inputs must be finite")
    if not np.all(np.isin(roles, ("formal", "sentinel"))):
        raise ValueError("invalid role in interleaved mapping")
    if not np.all(np.isin(directions, ("up", "down"))):
        raise ValueError("invalid direction in interleaved mapping")
    for name in ("up", "down"):
        mask = directions == name
        if (np.count_nonzero(mask & (roles == "formal")) != 72 or
                np.count_nonzero(mask & (roles == "sentinel")) != 9):
            raise ValueError(
                f"{name} must contain 72 formal and 9 sentinel points")

    raw = {}
    calibrations = {}
    for source in ("up", "down"):
        mask = (directions == source) & (roles == "formal")
        cal = ec.calibrate_phase_ref(x[mask], y[mask], phi[mask])
        if not (np.all(np.isfinite(cal["c0"])) and
                np.all(np.isfinite(cal["A_hat"])) and
                np.all(np.isfinite(cal["B"])) and
                np.isfinite(cal["kappa"]) and cal["kappa"] > 0):
            raise ValueError(f"{source} affine calibration is not finite")
        raw[source] = cal
        calibrations[source] = dict(
            c0=np.asarray(cal["c0"], float).tolist(),
            A_hat=np.asarray(cal["A_hat"], float).tolist(),
            B=np.asarray(cal["B"], float).tolist(),
            kappa=float(cal["kappa"]),
        )

    evaluations = {}
    own_passes = []
    cross_passes = []
    for source in ("up", "down"):
        for target in ("up", "down"):
            for target_role in ("formal", "sentinel"):
                mask = ((directions == target) & (roles == target_role))
                metrics = ec.self_check_mrad(
                    x[mask], y[mask], raw[source], phi[mask])
                passed = bool(
                    metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD and
                    metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD)
                key = f"{source}_to_{target}_{target_role}"
                evaluations[key] = dict(
                    source_direction=source, target_direction=target,
                    target_role=target_role,
                    median_mrad=float(metrics["median"]),
                    p95_mrad=float(metrics["p95"]),
                    rms_mrad=float(metrics["rms"]), passed=passed)
                (own_passes if source == target else cross_passes).append(passed)

    up = raw["up"]
    down = raw["down"]
    pairwise = dict(
        relative_A_frobenius=float(
            np.linalg.norm(up["A_hat"] - down["A_hat"]) /
            np.linalg.norm(up["A_hat"])),
        center_l2=float(np.linalg.norm(up["c0"] - down["c0"])),
    )
    own_pass = bool(all(own_passes))
    cross_pass = bool(all(cross_passes))
    return dict(
        accepted=bool(own_pass and cross_pass),
        own_direction_mapping_pass=own_pass,
        cross_direction_mapping_pass=cross_pass,
        median_limit_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
        p95_limit_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
        calibrations=calibrations, evaluations=evaluations,
        pairwise=pairwise)


def _analyze_partition_mapping(X, Y, phase_truth, role, labels,
                               label_names, partition_name):
    x = np.asarray(X, float)
    y = np.asarray(Y, float)
    phi = np.asarray(phase_truth, float)
    roles = np.asarray(role).astype("U16")
    labels = np.asarray(labels).astype("U16")
    n = len(x)
    if any(len(value) != n for value in (y, phi, roles, labels)):
        raise ValueError(f"{partition_name} mapping arrays must have equal length")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and
            np.all(np.isfinite(phi))):
        raise ValueError(f"{partition_name} mapping inputs must be finite")
    if set(np.unique(labels)) != set(label_names):
        raise ValueError(f"{partition_name} labels differ from frozen groups")
    raw = {}
    calibrations = {}
    for source in label_names:
        formal = (labels == source) & (roles == "formal")
        sentinel = (labels == source) & (roles == "sentinel")
        if np.count_nonzero(formal) < 20 or np.count_nonzero(sentinel) < 2:
            raise ValueError(f"{partition_name} {source} lacks coverage")
        cal = ec.calibrate_phase_ref(x[formal], y[formal], phi[formal])
        raw[source] = cal
        calibrations[source] = dict(
            c0=np.asarray(cal["c0"], float).tolist(),
            A_hat=np.asarray(cal["A_hat"], float).tolist(),
            B=np.asarray(cal["B"], float).tolist(),
            kappa=float(cal["kappa"]))
    evaluations = {}
    own = []
    cross = []
    for source in label_names:
        for target in label_names:
            for target_role in ("formal", "sentinel"):
                mask = (labels == target) & (roles == target_role)
                metrics = ec.self_check_mrad(
                    x[mask], y[mask], raw[source], phi[mask])
                passed = bool(
                    metrics["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD and
                    metrics["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD)
                key = f"{source}_to_{target}_{target_role}"
                evaluations[key] = dict(
                    source_group=source, target_group=target,
                    target_role=target_role,
                    median_mrad=float(metrics["median"]),
                    p95_mrad=float(metrics["p95"]),
                    rms_mrad=float(metrics["rms"]), passed=passed)
                (own if source == target else cross).append(passed)
    first, second = label_names
    pairwise = dict(
        relative_A_frobenius=float(
            np.linalg.norm(raw[first]["A_hat"] - raw[second]["A_hat"]) /
            np.linalg.norm(raw[first]["A_hat"])),
        center_l2=float(np.linalg.norm(
            raw[first]["c0"] - raw[second]["c0"])))
    own_pass = bool(all(own))
    cross_pass = bool(all(cross))
    return dict(
        partition=partition_name, accepted=bool(own_pass and cross_pass),
        own_mapping_pass=own_pass, cross_mapping_pass=cross_pass,
        median_limit_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
        p95_limit_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
        calibrations=calibrations, evaluations=evaluations,
        pairwise=pairwise)


def analyze_all_mapping_stability(X, Y, phase_truth, role, direction,
                                  pair_position, target_ordinal):
    direction_result = analyze_direction_mapping(
        X, Y, phase_truth, role, direction)
    positions = np.where(np.asarray(pair_position, int) == 0,
                         "first", "second")
    pair_result = _analyze_partition_mapping(
        X, Y, phase_truth, role, positions, ("first", "second"),
        "pair_position")
    epochs = np.where(np.asarray(target_ordinal, int) < 40,
                      "early", "late")
    time_result = _analyze_partition_mapping(
        X, Y, phase_truth, role, epochs, ("early", "late"),
        "target_ordinal_epoch")
    return dict(
        accepted=bool(direction_result["accepted"] and
                      pair_result["accepted"] and time_result["accepted"]),
        direction_mapping=direction_result,
        pair_position_mapping=pair_result,
        early_late_mapping=time_result)


def require_direction_mapping(result, mapping):
    if not isinstance(result, dict) or "quality_gate" not in result:
        raise ValueError("time-truth result is required")
    if not isinstance(mapping, dict) or "accepted" not in mapping:
        raise ValueError("interleaved mapping result is required")
    result["interleaved_direction_mapping"] = mapping
    gates = result["quality_gate"]
    gates["interleaved_mapping_stability_pass"] = bool(mapping["accepted"])
    required = list(gates["required_pass_fields"])
    if "interleaved_mapping_stability_pass" not in required:
        required.append("interleaved_mapping_stability_pass")
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    return result


def attach_shared_phase_reference(result, X, Y, role, bias):
    """Fit the shared map from formal contemporaneous phase labels.

    The target order is deliberately non-monotonic, so the winding heuristic in
    an unlabelled ellipse fit is not applicable here.  This diagnostic is the
    supervised/time-truth calibration path; the separate gauge audit remains
    unauthorized.
    """
    if not isinstance(result, dict) or "fit" not in result:
        raise ValueError("time-truth result is required")
    x = np.asarray(X, float)
    y = np.asarray(Y, float)
    roles = np.asarray(role).astype("U16")
    bias = np.asarray(bias, float)
    phi = np.asarray(result["fit"]["phase_truth"], float)
    n = len(phi)
    if any(len(value) != n for value in (x, y, roles, bias)):
        raise ValueError("shared phase-reference arrays must have equal length")
    formal = roles == "formal"
    sentinel = roles == "sentinel"
    calibration = ec.calibrate_phase_ref(
        x[formal], y[formal], phi[formal])
    formal_check = ec.self_check_mrad(
        x[formal], y[formal], calibration, phi[formal])
    sentinel_check = ec.self_check_mrad(
        x[sentinel], y[sentinel], calibration, phi[sentinel])
    static = ec.bias_to_phase(bias, tt.VPI_V, tt.CENTER_V)
    static_formal = ec.self_check_mrad(
        x[formal], y[formal], calibration, static[formal])
    static_sentinel = ec.self_check_mrad(
        x[sentinel], y[sentinel], calibration, static[sentinel])
    finite = bool(
        np.all(np.isfinite(calibration["c0"])) and
        np.all(np.isfinite(calibration["A_hat"])) and
        np.all(np.isfinite(calibration["B"])) and
        np.isfinite(calibration["kappa"]) and calibration["kappa"] > 0)
    gates = result["quality_gate"]
    gates.update(
        calibration_finite_positive_pass=finite,
        formal_selfcheck_median_mrad=float(formal_check["median"]),
        formal_selfcheck_median_limit_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
        formal_selfcheck_median_pass=bool(
            formal_check["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD),
        formal_selfcheck_p95_mrad=float(formal_check["p95"]),
        formal_selfcheck_p95_limit_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
        formal_selfcheck_p95_pass=bool(
            formal_check["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD),
        sentinel_selfcheck_median_mrad=float(sentinel_check["median"]),
        sentinel_selfcheck_median_limit_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
        sentinel_selfcheck_median_pass=bool(
            sentinel_check["median"] <= tt.SELFCHECK_MEDIAN_LIMIT_MRAD),
        sentinel_selfcheck_p95_mrad=float(sentinel_check["p95"]),
        sentinel_selfcheck_p95_limit_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
        sentinel_selfcheck_p95_pass=bool(
            sentinel_check["p95"] <= tt.SELFCHECK_P95_LIMIT_MRAD))
    required = list(gates["required_pass_fields"])
    for name in (
            "calibration_finite_positive_pass",
            "formal_selfcheck_median_pass", "formal_selfcheck_p95_pass",
            "sentinel_selfcheck_median_pass", "sentinel_selfcheck_p95_pass"):
        if name not in required:
            required.append(name)
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    result["calibration"] = calibration
    result["selfcheck"] = dict(
        formal=formal_check, sentinel=sentinel_check,
        frozen_coordinate_map_formal=static_formal,
        frozen_coordinate_map_sentinel=static_sentinel)
    return result


def self_test():
    schedule = build_schedule()
    assert len(schedule["bias"]) == 162
    assert np.count_nonzero(schedule["role"] == "formal") == 144
    assert np.count_nonzero(schedule["role"] == "sentinel") == 18
    validate_schedule_arrays(**schedule)
    record = tt._synthetic_record(
        schedule, history_h=0.008, v1_per_tau=0.003)
    result = tt.analyze_time_truth(**{
        key: value for key, value in record.items() if key not in {"X", "Y"}})
    result = attach_shared_phase_reference(
        result, record["X"], record["Y"], schedule["role"],
        schedule["bias"])
    mapping = analyze_all_mapping_stability(
        record["X"], record["Y"], result["fit"]["phase_truth"],
        schedule["role"], schedule["direction"],
        schedule["pair_position"], schedule["target_ordinal"])
    result = require_direction_mapping(result, mapping)
    assert result["quality_gate"]["accepted"]
    formal = schedule["role"] == "formal"
    target_time_corr = float(abs(np.corrcoef(
        record["time_unix"][formal], schedule["bias"][formal])[0, 1]))
    assert target_time_corr <= 0.05

    changed_x = record["X"].copy()
    changed_y = record["Y"].copy()
    down = schedule["direction"] == "down"
    changed_x[down] += 0.12 * changed_y[down] + 0.05
    changed_y[down] *= 0.82
    changed = analyze_direction_mapping(
        changed_x, changed_y, result["fit"]["phase_truth"],
        schedule["role"], schedule["direction"])
    assert not changed["cross_direction_mapping_pass"]

    corrupted = build_schedule()
    corrupted["approach_bias"] = corrupted["approach_bias"].copy()
    corrupted["approach_bias"][20] = corrupted["bias"][20]
    try:
        validate_schedule_arrays(**corrupted)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted approach schedule was accepted")
    return dict(
        schedule_points=162, formal_points=144, sentinel_points=18,
        design_abs_corr=float(result["fit"]["design_abs_corr"]),
        design_condition_number=float(result["fit"]["design_condition_number"]),
        target_time_abs_corr=target_time_corr,
        healthy_pass=True, direction_perturbation_rejected=True,
        approach_corruption_rejected=True)


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, sort_keys=True))
