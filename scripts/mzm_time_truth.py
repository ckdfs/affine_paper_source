#!/usr/bin/env python3
"""Pure offline time-resolved truth helpers for the single-MZM bench.

This module contains no instrument access and performs no file I/O.  It builds
the frozen ABA calibration schedule, fits the preregistered point-level DMM
model on formal points only, evaluates held-out sentinel points, and optionally
checks an affine X/Y calibration against the resulting time-resolved phase.

The time coordinate used by the model is

    tau = (t - mean(t_formal)) /
          (0.5 * (max(t_formal) - min(t_formal))),

so formal-sample tau spans [-1, 1].  The reported physical drift converts the fitted
coefficient back to volts/second before making the frozen 30 minute projection.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as ec  # noqa: E402


CENTER_V = 0.8147635714861232
VPI_V = 5.222139048043948
POINTS_PER_LEG = 81
SENTINEL_MODULUS = 10

DESIGN_CORR_LIMIT = 0.05
DESIGN_COND_LIMIT = 3.0
PHASE_LIMIT_RAD = 0.05
DC_NORMALIZED_RMSE_LIMIT = float(np.sin(PHASE_LIMIT_RAD))
SELFCHECK_MEDIAN_LIMIT_MRAD = 50.0
SELFCHECK_P95_LIMIT_MRAD = 200.0
BIAS_LIMIT_V = 9.0
BOARD_DC_RAIL_V = 1.199
ADC_RAW_VERSION = 1
ADC_RAW_GAIN = 1
ADC_RAW_FS_UV = 1_200_000
ADC_RAW_GUARD_ABS_CODE = 8_381_618


def build_aba_schedule(center=CENTER_V, vpi=VPI_V,
                       points_per_leg=POINTS_PER_LEG):
    """Return the frozen up/down/up calibration schedule.

    Each leg visits the same ascending 81-point grid.  The down leg executes
    that grid in reverse.  Points whose *ascending-grid* index is divisible by
    ten are held-out sentinels in every leg; all other points are formal fit
    samples.
    """
    center = float(center)
    vpi = float(vpi)
    points_per_leg = int(points_per_leg)
    if not (np.isfinite(center) and np.isfinite(vpi) and vpi > 0):
        raise ValueError("center must be finite and vpi must be finite and positive")
    if points_per_leg != POINTS_PER_LEG:
        raise ValueError(f"frozen ABA schedule requires {POINTS_PER_LEG} points per leg")

    grid = np.linspace(center - vpi, center + vpi, points_per_leg)
    roles = []
    legs = []
    directions = []
    grid_indices = []
    biases = []
    for leg, direction in enumerate(("up", "down", "up")):
        indices = (np.arange(points_per_leg) if direction == "up"
                   else np.arange(points_per_leg - 1, -1, -1))
        for grid_index in indices:
            roles.append("sentinel" if grid_index % SENTINEL_MODULUS == 0
                         else "formal")
            legs.append(leg)
            directions.append(direction)
            grid_indices.append(int(grid_index))
            biases.append(float(grid[grid_index]))
    n = len(biases)
    return dict(
        role=np.asarray(roles, dtype="U8"),
        leg=np.asarray(legs, dtype=int),
        direction=np.asarray(directions, dtype="U4"),
        grid_index=np.asarray(grid_indices, dtype=int),
        bias=np.asarray(biases, dtype=float),
        sequence_index=np.arange(n, dtype=int),
    )


def schedule_records(schedule=None):
    """Return the canonical JSON-ready representation of the frozen schedule."""
    schedule = build_aba_schedule() if schedule is None else schedule
    return [dict(
        role=str(schedule["role"][index]),
        leg=int(schedule["leg"][index]),
        direction=str(schedule["direction"][index]),
        grid_index=int(schedule["grid_index"][index]),
        bias_V=float(schedule["bias"][index]),
        sequence_index=int(schedule["sequence_index"][index]),
    ) for index in range(len(schedule["bias"]))]


def schedule_sha256(schedule=None):
    payload = json.dumps(
        schedule_records(schedule), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def balanced_target_orders(n_targets=16, seed=20260710):
    """Return a deterministic permutation and its reverse, with balance proof.

    Every target appears once in each order and its mean zero-based execution
    position is exactly ``(n_targets - 1) / 2``.
    """
    n_targets = int(n_targets)
    if n_targets < 2:
        raise ValueError("n_targets must be at least two")
    rng = np.random.default_rng(int(seed))
    permutation = rng.permutation(n_targets)
    reverse = permutation[::-1].copy()
    orders = np.stack([permutation, reverse])
    positions = np.empty((2, n_targets), dtype=float)
    for row, order in enumerate(orders):
        positions[row, order] = np.arange(n_targets, dtype=float)
    mean_position = positions.mean(axis=0)
    expected = 0.5 * (n_targets - 1)
    balanced = bool(np.all(mean_position == expected))
    return dict(permutation=permutation, reverse=reverse, orders=orders,
                mean_position=mean_position, expected_mean_position=expected,
                balanced=balanced, seed=int(seed))


def _as_1d(name, value, n=None, dtype=float):
    out = np.asarray(value, dtype=dtype)
    if out.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if n is not None and len(out) != n:
        raise ValueError(f"{name} length {len(out)} does not match {n}")
    return out


def _direction_code(direction, n):
    raw = np.asarray(direction)
    if raw.ndim != 1 or len(raw) != n:
        raise ValueError(f"direction must be one-dimensional with length {n}")
    if raw.dtype.kind in "USO":
        text = np.char.lower(raw.astype("U16"))
        valid = np.isin(text, ("up", "down"))
        if not np.all(valid):
            raise ValueError("direction values must be 'up' or 'down'")
        return np.where(text == "up", 1.0, -1.0)
    numeric = np.asarray(raw, dtype=float)
    if not np.all(np.isin(numeric, (-1.0, 1.0))):
        raise ValueError("numeric direction values must be -1 or +1")
    return numeric


def _validated_inputs(time_unix, bias, dc, role, direction, sequence_index,
                      X=None, Y=None):
    t = _as_1d("time_unix", time_unix)
    n = len(t)
    bias = _as_1d("bias", bias, n=n)
    dc = _as_1d("dc", dc, n=n)
    role = _as_1d("role", role, n=n, dtype="U16")
    sequence = _as_1d("sequence_index", sequence_index, n=n, dtype=int)
    direction_code = _direction_code(direction, n)

    if n < 12:
        raise ValueError("time-truth fit requires at least 12 points")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(bias)) or not np.all(
            np.isfinite(dc)):
        raise ValueError("time, bias, and DC values must all be finite")
    if not np.all(np.diff(t) > 0):
        raise ValueError("time_unix must be strictly increasing")
    if len(np.unique(sequence)) != n or not np.all(np.diff(sequence) > 0):
        raise ValueError("sequence_index must be unique and strictly increasing")
    if not np.all(np.isin(role, ("formal", "sentinel"))):
        raise ValueError("role values must be 'formal' or 'sentinel'")
    formal = role == "formal"
    sentinel = role == "sentinel"
    if not np.any(formal):
        raise ValueError("at least one formal point is required")
    if not np.any(sentinel):
        raise ValueError("at least one held-out sentinel point is required")
    if t[formal].min() < t[sentinel].min() or t[formal].max() > t[sentinel].max():
        raise ValueError("formal points must be covered by the sentinel time range")
    if len(np.unique(direction_code[formal])) != 2:
        raise ValueError("formal points must include both scan directions")

    x = y = None
    if (X is None) != (Y is None):
        raise ValueError("X and Y must be supplied together")
    if X is not None:
        x = _as_1d("X", X, n=n)
        y = _as_1d("Y", Y, n=n)
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("X and Y values must all be finite")
    return t, bias, dc, role, direction_code, sequence, formal, sentinel, x, y


def _time_coordinate(t, reference_mask=None):
    reference = t if reference_mask is None else t[np.asarray(reference_mask, bool)]
    if len(reference) < 2:
        raise ValueError("time coordinate requires at least two reference points")
    midpoint = float(np.mean(reference))
    scale = 0.5 * (float(np.max(reference)) - float(np.min(reference)))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("time span must be finite and positive")
    return (t - midpoint) / scale, midpoint, scale


def _initial_parameters(bias, dc, formal, vpi, center):
    k = np.pi / vpi
    design = np.column_stack([
        np.ones(np.count_nonzero(formal)),
        np.cos(k * bias[formal]),
        np.sin(k * bias[formal]),
    ])
    coef, _, rank, _ = np.linalg.lstsq(design, dc[formal], rcond=None)
    if rank < 3:
        raise ValueError("formal fixed-Vpi DC design is rank deficient")
    amplitude = float(np.hypot(coef[1], coef[2]))
    if not np.isfinite(amplitude) or amplitude <= np.finfo(float).eps:
        raise ValueError("formal DC data have non-positive fitted amplitude")
    v0_raw = float(np.arctan2(coef[2], coef[1]) / k)
    v00, _ = ec.align_periodic_origin(v0_raw, center, vpi)
    return np.array([float(coef[0]), 0.0, np.log(amplitude), 0.0,
                     v00, 0.0, 0.0])


def _evaluate_model(parameters, tau, bias, direction_code, vpi):
    a0, a1, lb0, lb1, v00, v1, history = parameters
    a = a0 + a1 * tau
    log_b = lb0 + lb1 * tau
    # Avoid numerical overflow during an unsuccessful optimizer trial while
    # retaining a smooth residual throughout the physically useful range.
    b = np.exp(np.clip(log_b, -40.0, 40.0))
    v0 = v00 + v1 * tau + history * direction_code
    phase = np.pi * (bias - v0) / vpi
    model = a + b * np.cos(phase)
    return model, a, b, v0, phase


def fit_point_dc_model(time_unix, bias, dc, role, direction, sequence_index,
                       vpi=VPI_V, center=CENTER_V):
    """Fit the frozen point-level DC model on formal samples only.

    The fitted model is ``a=a0+a1*tau``, ``b=exp(lb0+lb1*tau)``, and
    ``V0=v00+v1*tau+h*direction`` with up=+1 and down=-1.  Sentinels are never
    passed to the optimizer and are evaluated strictly out of sample.
    """
    vpi = float(vpi)
    center = float(center)
    if not (np.isfinite(vpi) and vpi > 0 and np.isfinite(center)):
        raise ValueError("vpi must be positive and center must be finite")
    (t, bias, dc, role, direction_code, sequence, formal, sentinel,
     _, _) = _validated_inputs(time_unix, bias, dc, role, direction,
                               sequence_index)
    tau, time_midpoint, time_scale = _time_coordinate(t, formal)
    design = np.column_stack([np.ones(np.count_nonzero(formal)),
                              tau[formal], direction_code[formal]])
    rank = int(np.linalg.matrix_rank(design))
    if rank != 3:
        raise ValueError("formal design [1,tau,direction] must have rank three")
    design_corr = float(np.corrcoef(tau[formal], direction_code[formal])[0, 1])
    design_cond = float(np.linalg.cond(design))
    if not (np.isfinite(design_corr) and np.isfinite(design_cond)):
        raise ValueError("formal time/direction design metrics must be finite")

    p0 = _initial_parameters(bias, dc, formal, vpi, center)

    def residual(parameters):
        model, _, _, _, _ = _evaluate_model(
            parameters, tau[formal], bias[formal], direction_code[formal], vpi)
        return dc[formal] - model

    fit = least_squares(residual, p0, method="trf", x_scale="jac",
                        max_nfev=50000, ftol=1e-12, xtol=1e-12, gtol=1e-12)
    if not fit.success or not np.all(np.isfinite(fit.x)):
        raise RuntimeError(f"point-level DC fit failed: {fit.message}")

    parameters = fit.x.copy()
    parameters[4], branch_shift = ec.align_periodic_origin(
        parameters[4], center, vpi)
    model, a, b, v0, phase_truth = _evaluate_model(
        parameters, tau, bias, direction_code, vpi)
    normalized_residual = (dc - model) / b
    train_rmse = float(np.sqrt(np.mean(normalized_residual[formal] ** 2)))
    sentinel_rmse = float(np.sqrt(np.mean(normalized_residual[sentinel] ** 2)))
    h = float(parameters[6])
    v1_per_tau = float(parameters[5])
    v0_rate_v_per_s = v1_per_tau / time_scale
    direction_split_phase = float(2.0 * np.pi * abs(h) / vpi)
    drift_30min_phase = float(np.pi * abs(v0_rate_v_per_s) * 1800.0 / vpi)
    names = ("a0", "a1_per_tau", "lb0", "lb1_per_tau", "v00_V",
             "v1_V_per_tau", "history_h_V")
    return dict(
        parameters={name: float(value) for name, value in zip(names, parameters)},
        optimizer=dict(success=bool(fit.success), status=int(fit.status),
                       message=str(fit.message), nfev=int(fit.nfev),
                       cost=float(fit.cost)),
        time_midpoint_unix=time_midpoint,
        time_scale_s=time_scale,
        tau=tau,
        formal_mask=formal,
        sentinel_mask=sentinel,
        direction_code=direction_code,
        sequence_index=sequence,
        model_dc=model,
        normalized_residual=normalized_residual,
        train_normalized_rmse=train_rmse,
        sentinel_normalized_rmse=sentinel_rmse,
        design_abs_corr=float(abs(design_corr)),
        design_corr=design_corr,
        design_condition_number=design_cond,
        design_rank=rank,
        branch_shift_periods=int(branch_shift),
        direction_split_phase_rad=direction_split_phase,
        v0_rate_V_per_s=float(v0_rate_v_per_s),
        drift_30min_phase_rad=drift_30min_phase,
        phase_truth=phase_truth,
        a=a,
        b=b,
        V0=v0,
        dc_normalized=(dc - a) / b,
    )


def analyze_time_truth(time_unix, bias, dc, role, direction, sequence_index,
                       X=None, Y=None, dc_board=None, vpi=VPI_V,
                       center=CENTER_V):
    """Fit time truth and evaluate all frozen quality gates.

    When X/Y are supplied, the affine calibration is fit on formal points only,
    using the time-normalized DMM DC.  Formal and held-out sentinel phase
    self-checks are then evaluated separately against the same point-level
    time-truth array.
    """
    (t, bias, dc, role, direction_code, sequence, formal, sentinel,
     x, y) = _validated_inputs(time_unix, bias, dc, role, direction,
                               sequence_index, X=X, Y=Y)
    fit = fit_point_dc_model(t, bias, dc, role, direction_code, sequence,
                             vpi=vpi, center=center)
    finite_model = bool(
        all(np.isfinite(value) for value in fit["parameters"].values()) and
        np.all(np.isfinite(fit["a"])) and np.all(np.isfinite(fit["b"])) and
        np.all(fit["b"] > 0) and np.all(np.isfinite(fit["V0"])))
    bias_rail = bool(np.any(np.abs(bias) >= 0.995 * BIAS_LIMIT_V))
    gates = dict(
        finite_positive_model_pass=finite_model,
        bias_max_abs_V=float(np.max(np.abs(bias))),
        bias_rail_limit_V=float(0.995 * BIAS_LIMIT_V),
        bias_rail_pass=bool(not bias_rail),
        design_abs_corr=float(fit["design_abs_corr"]),
        design_abs_corr_limit=DESIGN_CORR_LIMIT,
        design_corr_pass=bool(fit["design_abs_corr"] <= DESIGN_CORR_LIMIT),
        design_condition_number=float(fit["design_condition_number"]),
        design_condition_limit=DESIGN_COND_LIMIT,
        design_condition_pass=bool(
            fit["design_condition_number"] <= DESIGN_COND_LIMIT),
        train_normalized_rmse=float(fit["train_normalized_rmse"]),
        train_normalized_rmse_limit=DC_NORMALIZED_RMSE_LIMIT,
        train_dc_pass=bool(
            fit["train_normalized_rmse"] <= DC_NORMALIZED_RMSE_LIMIT),
        sentinel_normalized_rmse=float(fit["sentinel_normalized_rmse"]),
        sentinel_normalized_rmse_limit=DC_NORMALIZED_RMSE_LIMIT,
        sentinel_dc_pass=bool(
            fit["sentinel_normalized_rmse"] <= DC_NORMALIZED_RMSE_LIMIT),
        direction_split_phase_rad=float(fit["direction_split_phase_rad"]),
        direction_split_phase_limit_rad=PHASE_LIMIT_RAD,
        direction_split_pass=bool(
            fit["direction_split_phase_rad"] <= PHASE_LIMIT_RAD),
        drift_30min_phase_rad=float(fit["drift_30min_phase_rad"]),
        drift_30min_phase_limit_rad=PHASE_LIMIT_RAD,
        drift_30min_pass=bool(
            fit["drift_30min_phase_rad"] <= PHASE_LIMIT_RAD),
    )
    if dc_board is not None:
        board = _as_1d("dc_board", dc_board, n=len(t))
        board_finite = bool(np.all(np.isfinite(board)))
        board_rail = bool(board_finite and np.any(board >= BOARD_DC_RAIL_V))
        gates.update(
            board_dc_finite_pass=board_finite,
            board_dc_max_V=(float(np.max(board)) if board_finite else float("nan")),
            board_dc_rail_limit_V=BOARD_DC_RAIL_V,
            board_dc_rail_pass=bool(board_finite and not board_rail),
            board_dc_monitor_only=True,
            board_dc_rail_advisory=board_rail,
        )
    calibration = None
    selfcheck = None
    if x is not None:
        calibration = ec.calibrate_from_data(
            x[formal], y[formal], fit["dc_normalized"][formal])
        formal_check = ec.self_check_mrad(
            x[formal], y[formal], calibration, fit["phase_truth"][formal])
        sentinel_check = ec.self_check_mrad(
            x[sentinel], y[sentinel], calibration, fit["phase_truth"][sentinel])
        static_phase = ec.bias_to_phase(bias, vpi, center)
        static_formal_check = ec.self_check_mrad(
            x[formal], y[formal], calibration, static_phase[formal])
        static_sentinel_check = ec.self_check_mrad(
            x[sentinel], y[sentinel], calibration, static_phase[sentinel])
        selfcheck = dict(
            formal=formal_check,
            sentinel=sentinel_check,
            static_coordinate_map_counterfactual=dict(
                formal=static_formal_check, sentinel=static_sentinel_check),
        )
        calibration_finite_positive = bool(
            np.all(np.isfinite(calibration["c0"])) and
            np.all(np.isfinite(calibration["B"])) and
            np.all(np.isfinite(calibration["A_hat"])) and
            np.isfinite(calibration["kappa"]) and calibration["kappa"] > 0 and
            np.all(np.linalg.eigvalsh(calibration["M"]) > 0))
        gates["calibration_finite_positive_pass"] = calibration_finite_positive
        for prefix, check in (("formal", formal_check),
                              ("sentinel", sentinel_check)):
            gates[f"{prefix}_selfcheck_median_mrad"] = float(check["median"])
            gates[f"{prefix}_selfcheck_median_limit_mrad"] = (
                SELFCHECK_MEDIAN_LIMIT_MRAD)
            gates[f"{prefix}_selfcheck_median_pass"] = bool(
                check["median"] <= SELFCHECK_MEDIAN_LIMIT_MRAD)
            gates[f"{prefix}_selfcheck_p95_mrad"] = float(check["p95"])
            gates[f"{prefix}_selfcheck_p95_limit_mrad"] = (
                SELFCHECK_P95_LIMIT_MRAD)
            gates[f"{prefix}_selfcheck_p95_pass"] = bool(
                check["p95"] <= SELFCHECK_P95_LIMIT_MRAD)

    required = [
        "finite_positive_model_pass", "bias_rail_pass",
        "design_corr_pass", "design_condition_pass", "train_dc_pass",
        "sentinel_dc_pass", "direction_split_pass", "drift_30min_pass",
    ]
    if dc_board is not None:
        # CH1 is a separate, monitor-only ADC channel.  The unclipped DMM is
        # the DC truth source and CH0 supplies H1/H2, so a CH1 rail cannot be
        # used as a proxy for either truth failure or CH0 clipping.  Retain
        # finite CH1 telemetry as a file-integrity check, but make its rail an
        # advisory until CH0 raw extrema/clip counts are recorded directly.
        required.append("board_dc_finite_pass")
    if x is not None:
        required.extend([
            "calibration_finite_positive_pass",
            "formal_selfcheck_median_pass", "formal_selfcheck_p95_pass",
            "sentinel_selfcheck_median_pass", "sentinel_selfcheck_p95_pass",
        ])
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    gates["adc_raw_extrema_available"] = False
    gates["v1_4_authorization_ready"] = False
    return dict(fit=fit, calibration=calibration, selfcheck=selfcheck,
                quality_gate=gates)


def analyze_direction_mapping_stability(X, Y, phase_truth, role, leg,
                                        direction):
    """Cross-predict the frozen ABA legs with contemporaneous affine maps.

    Each source-leg map is fit from that leg's formal points only using the
    time-resolved DMM phase labels.  It is then scored on every target leg's
    formal and held-out sentinel points.  This is a diagnostic of the static
    observer-map assumption, not an independent optical truth channel.
    """
    x = _as_1d("X", X)
    n = len(x)
    y = _as_1d("Y", Y, n=n)
    phi = _as_1d("phase_truth", phase_truth, n=n)
    roles = _as_1d("role", role, n=n, dtype="U16")
    legs = _as_1d("leg", leg, n=n, dtype=int)
    directions = _as_1d("direction", direction, n=n, dtype="U16")
    directions = np.char.lower(directions)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and
            np.all(np.isfinite(phi))):
        raise ValueError("X, Y, and phase_truth must all be finite")
    if not np.all(np.isin(roles, ("formal", "sentinel"))):
        raise ValueError("role values must be 'formal' or 'sentinel'")
    if not np.array_equal(np.unique(legs), np.arange(3)):
        raise ValueError("frozen mapping audit requires exactly legs 0, 1, 2")
    expected_direction = {0: "up", 1: "down", 2: "up"}
    for leg_index, expected in expected_direction.items():
        mask = legs == leg_index
        if np.count_nonzero(mask & (roles == "formal")) != 72 or np.count_nonzero(
                mask & (roles == "sentinel")) != 9:
            raise ValueError(
                f"leg {leg_index} must contain 72 formal and 9 sentinel points")
        if not np.all(directions[mask] == expected):
            raise ValueError(
                f"leg {leg_index} direction must be consistently {expected}")

    calibrations = {}
    raw_calibrations = {}
    for source in range(3):
        source_formal = (legs == source) & (roles == "formal")
        cal = ec.calibrate_phase_ref(
            x[source_formal], y[source_formal], phi[source_formal])
        if not (np.all(np.isfinite(cal["c0"])) and
                np.all(np.isfinite(cal["A_hat"])) and
                np.all(np.isfinite(cal["B"])) and
                np.isfinite(cal["kappa"]) and cal["kappa"] > 0):
            raise ValueError(f"leg {source} affine calibration is not finite")
        raw_calibrations[source] = cal
        calibrations[str(source)] = dict(
            c0=np.asarray(cal["c0"], float).tolist(),
            A_hat=np.asarray(cal["A_hat"], float).tolist(),
            B=np.asarray(cal["B"], float).tolist(),
            kappa=float(cal["kappa"]),
        )

    evaluations = {}

    def evaluate(source, target, target_role):
        mask = (legs == target) & (roles == target_role)
        metrics = ec.self_check_mrad(
            x[mask], y[mask], raw_calibrations[source], phi[mask])
        passed = bool(
            metrics["median"] <= SELFCHECK_MEDIAN_LIMIT_MRAD and
            metrics["p95"] <= SELFCHECK_P95_LIMIT_MRAD)
        key = f"{source}_to_{target}_{target_role}"
        evaluations[key] = dict(
            source_leg=int(source), target_leg=int(target),
            target_role=str(target_role),
            median_mrad=float(metrics["median"]),
            p95_mrad=float(metrics["p95"]),
            rms_mrad=float(metrics["rms"]), passed=passed,
        )
        return passed

    own_passes = []
    for source in range(3):
        own_passes.extend([
            evaluate(source, source, "formal"),
            evaluate(source, source, "sentinel"),
        ])
    same_direction_pairs = ((0, 2), (2, 0))
    cross_direction_pairs = ((0, 1), (2, 1), (1, 0), (1, 2))
    same_passes = [
        evaluate(source, target, target_role)
        for source, target in same_direction_pairs
        for target_role in ("formal", "sentinel")
    ]
    cross_passes = [
        evaluate(source, target, target_role)
        for source, target in cross_direction_pairs
        for target_role in ("formal", "sentinel")
    ]

    pairwise = {}
    for source in range(3):
        for target in range(source + 1, 3):
            A_source = raw_calibrations[source]["A_hat"]
            A_target = raw_calibrations[target]["A_hat"]
            pairwise[f"{source}_vs_{target}"] = dict(
                relative_A_frobenius=float(
                    np.linalg.norm(A_source - A_target) /
                    np.linalg.norm(A_source)),
                center_l2=float(np.linalg.norm(
                    raw_calibrations[source]["c0"] -
                    raw_calibrations[target]["c0"])),
            )

    own_pass = bool(all(own_passes))
    same_pass = bool(all(same_passes))
    cross_pass = bool(all(cross_passes))
    return dict(
        accepted=bool(own_pass and same_pass and cross_pass),
        own_leg_mapping_pass=own_pass,
        same_direction_mapping_pass=same_pass,
        cross_direction_mapping_pass=cross_pass,
        median_limit_mrad=SELFCHECK_MEDIAN_LIMIT_MRAD,
        p95_limit_mrad=SELFCHECK_P95_LIMIT_MRAD,
        calibrations=calibrations,
        evaluations=evaluations,
        pairwise=pairwise,
    )


def require_observer_mapping_stability(result, mapping):
    """Attach the preregistered mapping audit as a required quality gate."""
    if not isinstance(result, dict) or "quality_gate" not in result:
        raise ValueError("time-truth result with quality_gate is required")
    if not isinstance(mapping, dict) or "accepted" not in mapping:
        raise ValueError("observer mapping result with accepted is required")
    result["observer_mapping_stability"] = mapping
    gates = result["quality_gate"]
    gates["observer_mapping_stability_pass"] = bool(mapping["accepted"])
    required = list(gates["required_pass_fields"])
    if "observer_mapping_stability_pass" not in required:
        required.append("observer_mapping_stability_pass")
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    return result


def analyze_adc_raw_telemetry(**fields):
    """Validate aggregated same-window CH0 raw-code telemetry point by point."""
    required = (
        "version", "scope", "expected", "used", "read_fail", "blocks",
        "complete", "timeout", "gain", "fs_uv", "guard", "crc",
        "ch0_min", "ch0_max", "ch0_rail_lo", "ch0_rail_hi",
        "ch0_guard_lo", "ch0_guard_hi", "windows",
    )
    missing = [name for name in required if name not in fields]
    if missing:
        raise ValueError("raw ADC telemetry missing fields: " + ", ".join(missing))
    arrays = {name: np.asarray(fields[name]) for name in required}
    lengths = {len(value) for value in arrays.values() if value.ndim == 1}
    if any(value.ndim != 1 for value in arrays.values()) or len(lengths) != 1:
        raise ValueError("raw ADC telemetry fields must be equal-length vectors")
    n = lengths.pop()
    if n < 1:
        raise ValueError("raw ADC telemetry requires at least one point")
    numeric_names = tuple(name for name in required if name != "scope")
    if any(not np.all(np.isfinite(np.asarray(arrays[name], dtype=float)))
           for name in numeric_names):
        raise ValueError("raw ADC telemetry numeric fields must be finite")

    version = np.asarray(arrays["version"], int)
    scope = np.asarray(arrays["scope"], dtype="U16")
    expected = np.asarray(arrays["expected"], int)
    used = np.asarray(arrays["used"], int)
    read_fail = np.asarray(arrays["read_fail"], int)
    complete = np.asarray(arrays["complete"], bool)
    timeout = np.asarray(arrays["timeout"], bool)
    gain = np.asarray(arrays["gain"], int)
    fs_uv = np.asarray(arrays["fs_uv"], int)
    guard = np.asarray(arrays["guard"], int)
    ch0_min = np.asarray(arrays["ch0_min"], int)
    ch0_max = np.asarray(arrays["ch0_max"], int)
    counts = [np.asarray(arrays[name], int) for name in (
        "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo", "ch0_guard_hi")]
    windows = np.asarray(arrays["windows"], int)

    contract = (
        (version == ADC_RAW_VERSION) & (scope == "acq") &
        (gain == ADC_RAW_GAIN) & (fs_uv == ADC_RAW_FS_UV) &
        (guard == ADC_RAW_GUARD_ABS_CODE) & (windows > 0))
    acquisition = (complete & ~timeout & (read_fail == 0) &
                   (expected > 0) & (used == expected))
    count_values_nonnegative = bool(all(np.all(value >= 0) for value in counts))
    no_near_rail = np.ones(n, dtype=bool)
    for value in counts:
        no_near_rail &= value == 0
    extrema = ((ch0_min <= ch0_max) &
               (ch0_min > -ADC_RAW_GUARD_ABS_CODE) &
               (ch0_max < ADC_RAW_GUARD_ABS_CODE))
    point_pass = contract & acquisition & no_near_rail & extrema
    return dict(
        accepted=bool(count_values_nonnegative and np.all(point_pass)),
        points=int(n),
        contract_pass=bool(np.all(contract)),
        acquisition_complete_pass=bool(np.all(acquisition)),
        count_values_nonnegative_pass=count_values_nonnegative,
        no_near_rail_pass=bool(np.all(no_near_rail)),
        extrema_guard_pass=bool(np.all(extrema)),
        failed_point_indices=np.flatnonzero(~point_pass).astype(int).tolist(),
        ch0_min_code=int(np.min(ch0_min)),
        ch0_max_code=int(np.max(ch0_max)),
        total_rail_lo=int(np.sum(counts[0])),
        total_rail_hi=int(np.sum(counts[1])),
        total_guard_lo=int(np.sum(counts[2])),
        total_guard_hi=int(np.sum(counts[3])),
        crc_checked_all=bool(np.all(np.asarray(arrays["crc"], bool))),
    )


def require_adc_raw_telemetry(result, rawadc):
    """Attach same-window CH0 telemetry as a required quality gate."""
    if not isinstance(rawadc, dict) or "accepted" not in rawadc:
        raise ValueError("raw ADC telemetry result with accepted is required")
    result["adc_raw_telemetry"] = rawadc
    gates = result["quality_gate"]
    gates["adc_raw_extrema_available"] = bool(rawadc["accepted"])
    gates["adc_raw_telemetry_pass"] = bool(rawadc["accepted"])
    required = list(gates["required_pass_fields"])
    if "adc_raw_telemetry_pass" not in required:
        required.append("adc_raw_telemetry_pass")
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    gates["v1_4_authorization_ready"] = False
    return result


def _synthetic_record(schedule, *, sentinel_offset=0.0, history_h=0.008,
                      v1_per_tau=0.004, seed=20260716):
    sequence = schedule["sequence_index"]
    t = 1_800_000_000.0 + 2.0 * sequence
    tau, _, _ = _time_coordinate(t, schedule["role"] == "formal")
    direction = np.where(schedule["direction"] == "up", 1.0, -1.0)
    a = 0.80 + 0.018 * tau
    b = np.exp(np.log(0.69) + 0.025 * tau)
    v0 = CENTER_V + float(v1_per_tau) * tau + history_h * direction
    phase = np.pi * (schedule["bias"] - v0) / VPI_V
    rng = np.random.default_rng(seed)
    dc = a + b * np.cos(phase) + 2e-4 * rng.standard_normal(len(t))
    dc[schedule["role"] == "sentinel"] += float(sentinel_offset)
    affine = np.array([[0.31, 0.047], [-0.038, 0.44]])
    center = np.array([0.018, -0.011])
    unit = np.column_stack([np.cos(phase), np.sin(phase)])
    xy = unit @ affine.T + center
    xy += 2e-4 * rng.standard_normal(xy.shape)
    return dict(time_unix=t, bias=schedule["bias"], dc=dc,
                role=schedule["role"], direction=schedule["direction"],
                sequence_index=sequence, X=xy[:, 0], Y=xy[:, 1],
                dc_board=np.minimum(dc, 1.10))


def self_test():
    """Run deterministic, hardware-free contract and gate checks."""
    def expect_value_error(values, fragment):
        try:
            analyze_time_truth(**values)
        except ValueError as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(f"invalid input was not rejected: {fragment}")

    def expect_mapping_error(X, Y, phase_truth, role, leg, direction, fragment):
        try:
            analyze_direction_mapping_stability(
                X, Y, phase_truth, role, leg, direction)
        except ValueError as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(
                f"invalid mapping input was not rejected: {fragment}")

    schedule = build_aba_schedule()
    assert len(schedule["bias"]) == 3 * POINTS_PER_LEG
    assert np.count_nonzero(schedule["role"] == "sentinel") == 27
    assert np.count_nonzero(schedule["role"] == "formal") == 216
    assert np.array_equal(np.unique(schedule["leg"]), np.arange(3))
    assert np.all(np.diff(schedule["sequence_index"]) == 1)
    assert np.all(np.diff(schedule["bias"][:POINTS_PER_LEG]) > 0)
    assert np.all(np.diff(schedule["bias"][POINTS_PER_LEG:2 * POINTS_PER_LEG]) < 0)

    balance = balanced_target_orders(seed=73)
    balance_repeat = balanced_target_orders(seed=73)
    assert balance["balanced"]
    assert np.all(balance["mean_position"] == balance["expected_mean_position"])
    assert np.array_equal(balance["reverse"], balance["permutation"][::-1])
    assert np.array_equal(balance["orders"], balance_repeat["orders"])

    record = _synthetic_record(schedule)
    result = analyze_time_truth(**record)
    assert result["quality_gate"]["accepted"]
    assert result["fit"]["design_abs_corr"] < 1e-12
    assert result["fit"]["design_condition_number"] < DESIGN_COND_LIMIT
    assert result["selfcheck"]["formal"]["p95"] < SELFCHECK_P95_LIMIT_MRAD
    assert result["selfcheck"]["sentinel"]["p95"] < SELFCHECK_P95_LIMIT_MRAD
    mapping = analyze_direction_mapping_stability(
        record["X"], record["Y"], result["fit"]["phase_truth"],
        schedule["role"], schedule["leg"], schedule["direction"])
    assert mapping["accepted"]
    gated_result = require_observer_mapping_stability(result, mapping)
    assert gated_result["quality_gate"]["observer_mapping_stability_pass"]
    assert gated_result["quality_gate"]["accepted"]

    # A direction-specific observer perturbation must leave DMM truth intact
    # while failing the cross-direction mapping gate.
    changed_observer = dict(record)
    changed_xy = np.column_stack([record["X"], record["Y"]]).copy()
    down = schedule["leg"] == 1
    transform = np.array([[1.20, 0.15], [-0.10, 0.90]])
    changed_xy[down] = changed_xy[down] @ transform.T + np.array([0.08, -0.10])
    changed_observer["X"] = changed_xy[:, 0]
    changed_observer["Y"] = changed_xy[:, 1]
    changed_truth = analyze_time_truth(**changed_observer)
    assert np.allclose(
        list(changed_truth["fit"]["parameters"].values()),
        list(result["fit"]["parameters"].values()))
    changed_mapping = analyze_direction_mapping_stability(
        changed_observer["X"], changed_observer["Y"],
        changed_truth["fit"]["phase_truth"], schedule["role"],
        schedule["leg"], schedule["direction"])
    assert not changed_mapping["cross_direction_mapping_pass"]
    assert not changed_mapping["accepted"]
    changed_gated = require_observer_mapping_stability(
        changed_truth, changed_mapping)
    assert not changed_gated["quality_gate"]["observer_mapping_stability_pass"]
    assert not changed_gated["quality_gate"]["accepted"]

    # Sentinel-only I/Q corruption cannot change source calibrations and must
    # be caught by a sentinel evaluation.
    bad_xy = np.column_stack([record["X"], record["Y"]]).copy()
    bad_xy[schedule["role"] == "sentinel", 0] += 0.10
    bad_iq_mapping = analyze_direction_mapping_stability(
        bad_xy[:, 0], bad_xy[:, 1], result["fit"]["phase_truth"],
        schedule["role"], schedule["leg"], schedule["direction"])
    for source in ("0", "1", "2"):
        assert np.array_equal(
            np.asarray(mapping["calibrations"][source]["A_hat"]),
            np.asarray(bad_iq_mapping["calibrations"][source]["A_hat"]))
    assert not bad_iq_mapping["own_leg_mapping_pass"]
    assert not bad_iq_mapping["accepted"]

    missing_leg = schedule["leg"].copy()
    missing_leg[missing_leg == 2] = 1
    expect_mapping_error(
        record["X"], record["Y"], result["fit"]["phase_truth"],
        schedule["role"], missing_leg, schedule["direction"],
        "exactly legs 0, 1, 2")
    wrong_direction = schedule["direction"].copy()
    wrong_direction[schedule["leg"] == 1] = "up"
    expect_mapping_error(
        record["X"], record["Y"], result["fit"]["phase_truth"],
        schedule["role"], schedule["leg"], wrong_direction,
        "direction must be consistently down")
    wrong_count_role = schedule["role"].copy()
    wrong_count_role[0] = "formal"
    expect_mapping_error(
        record["X"], record["Y"], result["fit"]["phase_truth"],
        wrong_count_role, schedule["leg"], schedule["direction"],
        "72 formal and 9 sentinel")
    nonfinite_mapping_x = record["X"].copy()
    nonfinite_mapping_x[30] = np.nan
    expect_mapping_error(
        nonfinite_mapping_x, record["Y"], result["fit"]["phase_truth"],
        schedule["role"], schedule["leg"], schedule["direction"],
        "must all be finite")

    raw_fields = dict(
        version=np.full(3, ADC_RAW_VERSION), scope=np.full(3, "acq"),
        expected=np.full(3, 81920), used=np.full(3, 81920),
        read_fail=np.zeros(3), blocks=np.full(3, 64),
        complete=np.ones(3), timeout=np.zeros(3),
        gain=np.full(3, ADC_RAW_GAIN), fs_uv=np.full(3, ADC_RAW_FS_UV),
        guard=np.full(3, ADC_RAW_GUARD_ABS_CODE), crc=np.zeros(3),
        ch0_min=np.full(3, -5000000), ch0_max=np.full(3, 5000000),
        ch0_rail_lo=np.zeros(3), ch0_rail_hi=np.zeros(3),
        ch0_guard_lo=np.zeros(3), ch0_guard_hi=np.zeros(3),
        windows=np.full(3, 4),
    )
    raw_ok = analyze_adc_raw_telemetry(**raw_fields)
    assert raw_ok["accepted"] and not raw_ok["crc_checked_all"]
    raw_gated = require_adc_raw_telemetry(gated_result, raw_ok)
    assert raw_gated["quality_gate"]["adc_raw_telemetry_pass"]
    assert raw_gated["quality_gate"]["accepted"]
    for field, value, failed_check in (
            ("read_fail", 1, "acquisition_complete_pass"),
            ("timeout", 1, "acquisition_complete_pass"),
            ("ch0_rail_hi", 1, "no_near_rail_pass"),
            ("ch0_guard_lo", 1, "no_near_rail_pass"),
            ("ch0_max", ADC_RAW_GUARD_ABS_CODE, "extrema_guard_pass")):
        bad_raw = {name: np.asarray(values).copy()
                   for name, values in raw_fields.items()}
        bad_raw[field][1] = value
        bad_raw_result = analyze_adc_raw_telemetry(**bad_raw)
        assert not bad_raw_result["accepted"]
        assert not bad_raw_result[failed_check]
    try:
        analyze_adc_raw_telemetry(**{
            name: values for name, values in raw_fields.items()
            if name != "ch0_max"})
    except ValueError as exc:
        assert "missing fields" in str(exc)
    else:
        raise AssertionError("missing raw ADC telemetry field was not rejected")

    # CH1 DC rail is monitor-only: it cannot reject a valid DMM-truth/CH0-IQ
    # record or stand in for unavailable CH0 raw-extrema telemetry.
    ch1_rail_record = dict(record)
    ch1_rail_record["dc_board"] = np.full(len(schedule["bias"]), 1.2)
    ch1_rail_result = analyze_time_truth(**ch1_rail_record)
    assert ch1_rail_result["quality_gate"]["accepted"]
    assert not ch1_rail_result["quality_gate"]["board_dc_rail_pass"]
    assert ch1_rail_result["quality_gate"]["board_dc_rail_advisory"]
    assert "board_dc_rail_pass" not in ch1_rail_result["quality_gate"][
        "required_pass_fields"]

    # Sentinel-only corruption must not change the training residual, and must
    # be caught by the held-out DC gate.
    bad_sentinel = analyze_time_truth(**_synthetic_record(
        schedule, sentinel_offset=0.08))
    assert bad_sentinel["quality_gate"]["train_dc_pass"]
    assert np.isclose(bad_sentinel["fit"]["train_normalized_rmse"],
                      result["fit"]["train_normalized_rmse"], atol=1e-10)
    assert not bad_sentinel["quality_gate"]["sentinel_dc_pass"]
    assert not bad_sentinel["quality_gate"]["accepted"]

    # A direction split above 0.05 rad is an unconditional failure.
    bad_history = analyze_time_truth(**_synthetic_record(
        schedule, history_h=0.050))
    assert not bad_history["quality_gate"]["direction_split_pass"]
    assert not bad_history["quality_gate"]["accepted"]

    # A deliberately drifting record must still recover contemporaneous truth
    # even though the frozen physical drift gate correctly rejects the run.
    drift_record = _synthetic_record(schedule, v1_per_tau=0.120)
    drift_result = analyze_time_truth(**drift_record)
    drift_tau, _, _ = _time_coordinate(
        drift_record["time_unix"], schedule["role"] == "formal")
    drift_direction = np.where(schedule["direction"] == "up", 1.0, -1.0)
    true_phase = np.pi * (
        schedule["bias"] - (CENTER_V + 0.120 * drift_tau
                            + 0.008 * drift_direction)) / VPI_V
    dynamic_rms = float(np.sqrt(np.mean(ec.wrap(
        drift_result["fit"]["phase_truth"] - true_phase) ** 2)))
    static_rms = float(np.sqrt(np.mean(ec.wrap(
        ec.bias_to_phase(schedule["bias"], VPI_V, CENTER_V) - true_phase) ** 2)))
    assert dynamic_rms < 0.005
    assert static_rms > 0.02
    assert not drift_result["quality_gate"]["drift_30min_pass"]

    # Frozen input invariants reject timestamp and sequence corruption.
    bad_time = dict(record)
    bad_time["time_unix"] = record["time_unix"].copy()
    bad_time["time_unix"][20] = bad_time["time_unix"][19]
    expect_value_error(bad_time, "strictly increasing")

    bad_sequence = dict(record)
    bad_sequence["sequence_index"] = record["sequence_index"].copy()
    bad_sequence["sequence_index"][20] = bad_sequence["sequence_index"][19]
    expect_value_error(bad_sequence, "unique and strictly increasing")

    missing_sentinel = dict(record)
    missing_sentinel["role"] = np.full(len(schedule["role"]), "formal", dtype="U8")
    expect_value_error(missing_sentinel, "held-out sentinel")

    uncovered = dict(record)
    uncovered["role"] = schedule["role"].copy()
    uncovered["role"][0] = "formal"
    expect_value_error(uncovered, "covered by the sentinel time range")

    nonfinite = dict(record)
    nonfinite["dc"] = record["dc"].copy()
    nonfinite["dc"][30] = np.nan
    expect_value_error(nonfinite, "must all be finite")

    return dict(schedule_points=len(schedule["bias"]),
                formal_points=int(np.count_nonzero(schedule["role"] == "formal")),
                sentinel_points=int(np.count_nonzero(
                    schedule["role"] == "sentinel")),
                balanced_targets=bool(balance["balanced"]),
                passing_quality_gate=bool(result["quality_gate"]["accepted"]),
                ch1_monitor_rail_is_advisory=bool(
                    ch1_rail_result["quality_gate"]["accepted"]),
                stable_observer_mapping_pass=bool(mapping["accepted"]),
                direction_observer_perturbation_rejected=bool(
                    not changed_mapping["accepted"]),
                sentinel_iq_corruption_rejected=bool(
                    not bad_iq_mapping["accepted"]),
                raw_adc_telemetry_pass=bool(raw_ok["accepted"]),
                sentinel_corruption_rejected=bool(
                    not bad_sentinel["quality_gate"]["accepted"]),
                direction_split_rejected=bool(
                    not bad_history["quality_gate"]["accepted"]),
                time_truth_recovers_drift=bool(dynamic_rms < 0.005 and
                                               static_rms > 0.02))


if __name__ == "__main__":
    print(self_test())
