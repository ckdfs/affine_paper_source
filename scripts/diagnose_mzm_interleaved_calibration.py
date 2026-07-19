#!/usr/bin/env python3
"""Acquire the preregistered local paired MZM calibration diagnostic."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import subprocess
import time
from contextlib import ExitStack

import numpy as np

import exp_common as ec
import measure_bench as mb
import mzm_interleaved_truth as it
import mzm_time_truth as tt


RAW_FIELDS = (
    "version", "scope", "expected", "used", "read_fail", "blocks",
    "complete", "timeout", "gain", "fs_uv", "guard", "crc", "ch0_min",
    "ch0_max", "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo",
    "ch0_guard_hi", "windows",
)
MAIN_HEADER = [
    "role", "direction", "grid_index", "target_ordinal", "pair_position",
    "sequence_index", "bias",
    "approach_bias", "bias_settle_s", "t_approach_set_unix",
    "t_target_set_unix", "transition_discard_index",
    "transition_followed_without_reconfigure", "t_discard_start_unix",
    "t_discard_end_unix", "t_dmm_pre_start_unix", "t_dmm_pre_end_unix",
    "t_dmm_pre_mid_unix", "dc_dmm_pre", "t_acq_start_unix",
    "t_acq_end_unix", "t_acq_mid_unix", "t_dmm_post_start_unix",
    "t_dmm_post_end_unix", "t_dmm_post_mid_unix", "dc_dmm_post",
    "dmm_interpolation_weight", "dc_dmm_interp", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
DISCARD_HEADER = [
    "transition_discard_index", "role", "direction", "grid_index",
    "target_ordinal", "pair_position",
    "source_sequence_index", "bias", "approach_bias", "t_target_set_unix",
    "t_start_unix", "t_end_unix", "t_mid_unix", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
WINDOW_HEADER = [
    "window_sequence_index", "source_sequence_index", "window_index",
    "role", "direction", "grid_index", "target_ordinal", "pair_position",
    "bias", "t_start_unix", "t_end_unix", "t_mid_unix", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
CONDITIONING_HEADER = [
    "sequence_index", "observation_sequence_index", "bridge_step_index",
    "from_bias", "bias", "delta_bias", "t_start_unix", "t_end_unix",
    "t_mid_unix", "dc_dmm", "dac_response",
]


def _abort(signum, _frame):
    raise KeyboardInterrupt(f"received signal {signum}")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _refresh_checksums(root):
    hashes = {}
    for filename in sorted(os.listdir(root)):
        path = os.path.join(root, filename)
        if os.path.isfile(path) and filename != "checksums.json":
            hashes[filename] = _sha256(path)
    _write_json(os.path.join(root, "checksums.json"), hashes)
    return hashes


def _expected_bridges(records=None):
    source_records = (it.schedule_records(it.build_schedule()) if records is None
                      else list(records))
    step = float(2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1))
    current = 0.0
    records = []
    sequence = 0
    for item in source_records:
        observation = int(item["sequence_index"])
        target = float(item["approach_bias_V"])
        delta = float(target - current)
        count = max(1, int(np.ceil(abs(delta) / step)))
        path = np.linspace(current, float(target), count + 1)[1:]
        for bridge_step, value in enumerate(path):
            records.append(dict(
                sequence_index=sequence,
                observation_sequence_index=observation,
                bridge_step_index=bridge_step,
                from_bias=float(current), bias=float(value),
                delta_bias=float(value - current)))
            current = float(value)
            sequence += 1
        current = float(item["bias_V"])
    return records


def _raw_arrays(rows):
    return {name: np.asarray([row[f"rawadc_{name}"] for row in rows])
            for name in RAW_FIELDS}


def _exact_raw_capture_pass(rows, blocks, windows):
    expected = int(blocks) * 1280
    return bool(rows and all(
        int(row["rawadc_version"]) == 1 and
        str(row["rawadc_scope"]) == "acq" and
        int(row["rawadc_expected"]) == expected and
        int(row["rawadc_used"]) == expected and
        int(row["rawadc_read_fail"]) == 0 and
        int(row["rawadc_blocks"]) == int(blocks) and
        bool(row["rawadc_complete"]) and
        not bool(row["rawadc_timeout"]) and
        int(row["rawadc_gain"]) == tt.ADC_RAW_GAIN and
        int(row["rawadc_fs_uv"]) == tt.ADC_RAW_FS_UV and
        int(row["rawadc_guard"]) == tt.ADC_RAW_GUARD_ABS_CODE and
        int(row["rawadc_windows"]) == int(windows) and
        -8388608 <= int(row["rawadc_ch0_min"]) <=
        int(row["rawadc_ch0_max"]) <= 8388607 and
        all(int(row[f"rawadc_{name}"]) >= 0 for name in (
            "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo", "ch0_guard_hi"))
        for row in rows))


def _calibration_json(calibration):
    if calibration is None:
        return None
    return dict(
        c0=np.asarray(calibration["c0"], float).tolist(),
        B=np.asarray(calibration["B"], float).tolist(),
        A_hat=np.asarray(calibration["A_hat"], float).tolist(),
        kappa=float(calibration["kappa"]))


def _analyze(rows, windows, discards, conditioning_rows, pilot_verification,
             discard_file_sha256, expected_conditioning=None):
    schedule = it.build_schedule()
    schedule_contract_pass = False
    try:
        schedule_contract_pass = it.validate_schedule_arrays(
            role=[row["role"] for row in rows],
            direction=[row["direction"] for row in rows],
            grid_index=[row["grid_index"] for row in rows],
            target_ordinal=[row["target_ordinal"] for row in rows],
            pair_position=[row["pair_position"] for row in rows],
            bias=[row["bias"] for row in rows],
            approach_bias=[row["approach_bias"] for row in rows],
            sequence_index=[row["sequence_index"] for row in rows])
    except Exception:
        schedule_contract_pass = False

    expected_conditioning = (_expected_bridges() if expected_conditioning is None
                             else list(expected_conditioning))
    conditioning_contract_pass = bool(
        len(conditioning_rows) == len(expected_conditioning) and
        all(all(int(row[name]) == int(expected[name]) for name in (
                    "sequence_index", "observation_sequence_index",
                    "bridge_step_index")) and
            all(np.isclose(float(row[name]), float(expected[name]),
                           atol=1e-12, rtol=0) for name in (
                               "from_bias", "bias", "delta_bias")) and
            abs(float(row["delta_bias"])) <=
            2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1) + 1e-12 and
            float(row["t_start_unix"]) < float(row["t_end_unix"]) and
            np.isclose(float(row["t_mid_unix"]),
                       0.5 * (float(row["t_start_unix"]) +
                              float(row["t_end_unix"])), atol=1e-9, rtol=0) and
            np.isfinite(float(row["dc_dmm"]))
            for row, expected in zip(conditioning_rows, expected_conditioning)))

    expected_verification = {str(index) for index in range(len(schedule["bias"]))}
    configuration_verified = bool(
        set(pilot_verification) == expected_verification and
        all(value.get("verified", False) and
            value.get("pilot_count_pass", False) and
            value.get("frequency_pass", False) and
            value.get("amplitude_pass", False) and
            value.get("acquisition_count_pass", False) and
            value.get("acquisition_frequencies_pass", False) and
            int(value.get("expected_pilot_count", 0)) == 1 and
            int(value.get("expected_acquisition_count", 0)) == 2 and
            np.isclose(float(value.get("expected_frequency_Hz", np.nan)),
                       mb.PILOT_HZ, atol=0, rtol=0) and
            np.isclose(float(value.get("expected_amplitude_V", np.nan)),
                       it.PILOT_V, atol=0, rtol=0) and
            int(value.get("source_sequence_index", -1)) == int(key)
            for key, value in pilot_verification.items()))

    discard_contract_pass = bool(
        len(rows) == len(schedule["bias"]) and len(discards) == len(rows) and
        all(
            int(discard["transition_discard_index"]) == index and
            int(discard["source_sequence_index"]) == int(row["sequence_index"]) and
            str(discard["role"]) == str(row["role"]) and
            str(discard["direction"]) == str(row["direction"]) and
            int(discard["grid_index"]) == int(row["grid_index"]) and
            int(discard["target_ordinal"]) == int(row["target_ordinal"]) and
            int(discard["pair_position"]) == int(row["pair_position"]) and
            np.isclose(float(discard["bias"]), float(row["bias"]), atol=0, rtol=0) and
            np.isclose(float(discard["approach_bias"]),
                       float(row["approach_bias"]), atol=0, rtol=0) and
            np.isclose(float(discard["t_target_set_unix"]),
                       float(row["t_target_set_unix"]), atol=0, rtol=0) and
            int(row["transition_discard_index"]) == index and
            bool(row["transition_followed_without_reconfigure"]) and
            float(discard["t_start_unix"]) >=
            float(row["t_target_set_unix"]) + it.BIAS_SETTLE_S - 1e-3 and
            float(discard["t_start_unix"]) < float(discard["t_end_unix"]) <=
            float(row["t_acq_start_unix"]) and
            float(row["t_acq_start_unix"]) - float(discard["t_end_unix"]) <=
            it.DISCARD_TO_FORMAL_MAX_S
            for index, (discard, row) in enumerate(zip(discards, rows))))
    discard_raw_gate = (tt.analyze_adc_raw_telemetry(**_raw_arrays(discards))
                        if discards else {"accepted": False})
    discard_capture_pass = bool(
        discards and discard_raw_gate.get("contract_pass", False) and
        discard_raw_gate.get("acquisition_complete_pass", False) and
        _exact_raw_capture_pass(discards, it.DISCARD_BLOCKS, 1))
    discard_hash_contract_pass = bool(
        set(discard_file_sha256) == {
            "transition_discard.csv", "transition_discard.npz"} and
        all(isinstance(value, str) and len(value) == 64 and
            all(ch in "0123456789abcdef" for ch in value)
            for value in discard_file_sha256.values()))

    window_contract_pass = bool(
        len(windows) == len(rows) * it.N_AVG and all(
            int(window["window_sequence_index"]) == index and
            int(window["source_sequence_index"]) == index // it.N_AVG and
            int(window["window_index"]) == index % it.N_AVG and
            str(window["role"]) == str(rows[index // it.N_AVG]["role"]) and
            str(window["direction"]) ==
            str(rows[index // it.N_AVG]["direction"]) and
            int(window["grid_index"]) ==
            int(rows[index // it.N_AVG]["grid_index"]) and
            int(window["target_ordinal"]) ==
            int(rows[index // it.N_AVG]["target_ordinal"]) and
            int(window["pair_position"]) ==
            int(rows[index // it.N_AVG]["pair_position"]) and
            np.isclose(float(window["bias"]),
                       float(rows[index // it.N_AVG]["bias"]), atol=0, rtol=0) and
            float(window["t_start_unix"]) < float(window["t_end_unix"]) and
            np.isclose(float(window["t_mid_unix"]),
                       0.5 * (float(window["t_start_unix"]) +
                              float(window["t_end_unix"])), atol=1e-9, rtol=0)
            for index, window in enumerate(windows)) and
        all(all(float(group[index]["t_end_unix"]) <=
                    float(group[index + 1]["t_start_unix"])
                    for index in range(it.N_AVG - 1))
            for group in (windows[start:start + it.N_AVG]
                          for start in range(0, len(windows), it.N_AVG))) and
        _exact_raw_capture_pass(windows, it.N_BLOCKS, 1) and
        all(
            np.isclose(float(row["t_acq_start_unix"]),
                       float(group[0]["t_start_unix"]), atol=0, rtol=0) and
            np.isclose(float(row["t_acq_end_unix"]),
                       float(group[-1]["t_end_unix"]), atol=0, rtol=0) and
            all(np.isclose(float(row[name]), np.mean([
                    float(window[name]) for window in group]),
                    atol=1e-12, rtol=0)
                for name in ("dc_board", "I1", "Q1", "I2", "Q2")) and
            all(row[f"rawadc_{name}"] ==
                mb.merge_rawadc_telemetry([{
                    raw_name: window[f"rawadc_{raw_name}"]
                    for raw_name in RAW_FIELDS} for window in group])[name]
                for name in RAW_FIELDS)
            for row, group in zip(
                rows, (windows[start:start + it.N_AVG]
                       for start in range(0, len(windows), it.N_AVG)))))
    window_raw_gate = (tt.analyze_adc_raw_telemetry(**_raw_arrays(windows))
                       if windows else {"accepted": False})

    dmm_bracket_pass = bool(rows and len(windows) == len(rows) * it.N_AVG and all(
        float(row["t_dmm_pre_start_unix"]) <
        float(row["t_dmm_pre_mid_unix"]) <
        float(row["t_dmm_pre_end_unix"]) <=
        float(row["t_acq_start_unix"]) <
        float(row["t_acq_mid_unix"]) <
        float(row["t_acq_end_unix"]) <=
        float(row["t_dmm_post_start_unix"]) <
        float(row["t_dmm_post_mid_unix"]) <
        float(row["t_dmm_post_end_unix"]) and
        np.isfinite(float(row["dc_dmm_pre"])) and
        np.isfinite(float(row["dc_dmm_post"])) and
        np.isfinite(float(row["dc_dmm_interp"])) and
        0.0 <= float(row["dmm_interpolation_weight"]) <= 1.0 and
        np.isclose(float(row["t_acq_mid_unix"]), np.mean([
            float(window["t_mid_unix"]) for window in
            windows[index * it.N_AVG:(index + 1) * it.N_AVG]]),
            atol=1e-9, rtol=0) and
        np.isclose(float(row["dc_dmm_interp"]),
                   float(row["dc_dmm_pre"]) +
                   float(row["dmm_interpolation_weight"]) *
                   (float(row["dc_dmm_post"]) -
                    float(row["dc_dmm_pre"])), atol=1e-12, rtol=0)
        for index, row in enumerate(rows)))
    preposition_settle_pass = bool(rows and all(
        np.isclose(float(row["bias_settle_s"]), it.BIAS_SETTLE_S,
                   atol=0, rtol=0) and
        float(row["t_target_set_unix"]) -
        float(row["t_approach_set_unix"]) >= it.BIAS_SETTLE_S - 1e-3 and
        float(row["t_discard_start_unix"]) -
        float(row["t_target_set_unix"]) >= it.BIAS_SETTLE_S - 1e-3
        for row in rows))

    fields = {name: np.asarray([row[name] for row in rows])
              for name in MAIN_HEADER}
    formal = fields["role"] == "formal"
    components = mb.choose_comps(
        fields["I1"][formal], fields["Q1"][formal],
        fields["I2"][formal], fields["Q2"][formal])
    X = fields["I2"] if components[0] == "I" else fields["Q2"]
    Y = fields["I1"] if components[1] == "I" else fields["Q1"]
    result = tt.analyze_time_truth(
        time_unix=fields["t_acq_mid_unix"], bias=fields["bias"],
        dc=fields["dc_dmm_interp"], role=fields["role"],
        direction=fields["direction"],
        sequence_index=fields["sequence_index"],
        dc_board=fields["dc_board"])
    result = it.attach_shared_phase_reference(
        result, X, Y, fields["role"], fields["bias"])
    mapping = it.analyze_all_mapping_stability(
        X, Y, result["fit"]["phase_truth"], fields["role"],
        fields["direction"], fields["pair_position"],
        fields["target_ordinal"])
    result = it.require_direction_mapping(result, mapping)
    formal_raw_gate = tt.analyze_adc_raw_telemetry(**_raw_arrays(rows))
    result = tt.require_adc_raw_telemetry(result, formal_raw_gate)
    formal_exact_capture_pass = _exact_raw_capture_pass(
        rows, it.N_BLOCKS * it.N_AVG, it.N_AVG)
    max_abs_code = int(max(max(abs(int(row["rawadc_ch0_min"])),
                                   abs(int(row["rawadc_ch0_max"])))
                               for row in rows))
    max_abs_raw_V = float(max_abs_code * 1.2 / 8388608.0)
    formal_headroom_pass = bool(max_abs_code <= it.HEADROOM_LIMIT_CODE)

    prepost = np.asarray([
        abs(float(row["dc_dmm_post"]) - float(row["dc_dmm_pre"]))
        for row in rows])
    amplitude = np.asarray(result["fit"]["b"], float)
    normalized_prepost = prepost / np.maximum(amplitude, np.finfo(float).eps)
    dmm_prepost_advisory = dict(
        median=float(np.median(normalized_prepost)),
        p95=float(np.percentile(normalized_prepost, 95)),
        maximum=float(np.max(normalized_prepost)))
    dmm_bracket_stability_pass = bool(
        np.max(normalized_prepost) <= tt.DC_NORMALIZED_RMSE_LIMIT)
    direction_code = np.where(fields["direction"] == "up", 1.0, -1.0)
    target_time_abs_corr = float(abs(np.corrcoef(
        fields["t_acq_mid_unix"][formal], fields["bias"][formal])[0, 1]))
    target_time_corr_pass = bool(target_time_abs_corr <= tt.DESIGN_CORR_LIMIT)
    direction_pair_position_corr = float(np.corrcoef(
        direction_code[formal], fields["pair_position"][formal])[0, 1])
    target_direction_corr = float(np.corrcoef(
        fields["bias"][formal], direction_code[formal])[0, 1])
    pair_orthogonality_pass = bool(
        abs(direction_pair_position_corr) <= 1e-12 and
        abs(target_direction_corr) <= 1e-12)

    gates = result["quality_gate"]
    extra = dict(
        schedule_contract_pass=schedule_contract_pass,
        conditioning_contract_pass=conditioning_contract_pass,
        single_pilot_configuration_verified=configuration_verified,
        transition_discard_contract_pass=discard_contract_pass,
        transition_discard_capture_pass=discard_capture_pass,
        transition_discard_hash_contract_pass=discard_hash_contract_pass,
        dmm_bracket_pass=dmm_bracket_pass,
        dmm_bracket_stability_pass=dmm_bracket_stability_pass,
        target_time_corr_pass=target_time_corr_pass,
        pair_orthogonality_pass=pair_orthogonality_pass,
        preposition_settle_pass=preposition_settle_pass,
        formal_window_contract_pass=window_contract_pass,
        formal_window_raw_pass=bool(window_raw_gate.get("accepted", False)),
        formal_exact_capture_pass=formal_exact_capture_pass,
        formal_headroom_pass=formal_headroom_pass)
    gates.update(extra)
    required = list(gates["required_pass_fields"])
    for name in extra:
        if name not in required:
            required.append(name)
    gates["required_pass_fields"] = tuple(required)
    gates["accepted"] = bool(all(gates[name] for name in required))
    gates["v1_4_authorization_ready"] = False
    return dict(
        protocol_version=it.PROTOCOL_VERSION,
        quality_gate=gates,
        dc_parameters=result["fit"]["parameters"],
        optimizer=result["fit"]["optimizer"],
        time_midpoint_unix=float(result["fit"]["time_midpoint_unix"]),
        time_scale_s=float(result["fit"]["time_scale_s"]),
        formal_points=int(np.count_nonzero(formal)),
        sentinel_points=int(np.count_nonzero(~formal)),
        components=list(components), selfcheck=result["selfcheck"],
        calibration=_calibration_json(result["calibration"]),
        interleaved_direction_mapping=mapping,
        target_time_abs_corr=target_time_abs_corr,
        direction_pair_position_corr=direction_pair_position_corr,
        target_direction_corr=target_direction_corr,
        formal_window_raw_gate=window_raw_gate,
        formal_raw_gate=formal_raw_gate,
        formal_max_abs_raw_code=max_abs_code,
        formal_max_abs_raw_V=max_abs_raw_V,
        transition_discard_records=len(discards),
        transition_discard_raw_gate=discard_raw_gate,
        transition_discard_file_sha256=dict(discard_file_sha256),
        dmm_prepost_normalized_advisory=dmm_prepost_advisory,
        independent_optical_truth=False, headline_promotion=False,
        pilot_only_calibration=True, v1_4_authorization_ready=False)


def _analyze_segment(rows, windows, discards, conditioning_rows,
                     pilot_verification, discard_file_sha256,
                     segment_index):
    start, end = it.segment_bounds(segment_index)
    expected_records = it.schedule_records(it.build_schedule())[start:end]
    expected_bridges = _expected_bridges(expected_records)
    schedule_pass = False
    try:
        schedule_pass = it.validate_schedule_arrays(
            role=[row["role"] for row in rows],
            direction=[row["direction"] for row in rows],
            grid_index=[row["grid_index"] for row in rows],
            target_ordinal=[row["target_ordinal"] for row in rows],
            pair_position=[row["pair_position"] for row in rows],
            bias=[row["bias"] for row in rows],
            approach_bias=[row["approach_bias"] for row in rows],
            sequence_index=[row["sequence_index"] for row in rows],
            start=start, end=end)
    except Exception:
        schedule_pass = False
    conditioning_pass = bool(
        len(conditioning_rows) == len(expected_bridges) and
        all(
            int(row["sequence_index"]) == index and
            int(row["observation_sequence_index"]) ==
            int(expected["observation_sequence_index"]) and
            int(row["bridge_step_index"]) == int(expected["bridge_step_index"]) and
            all(np.isclose(float(row[name]), float(expected[name]),
                           atol=1e-12, rtol=0) for name in
                ("from_bias", "bias", "delta_bias")) and
            float(row["t_start_unix"]) < float(row["t_end_unix"]) and
            np.isfinite(float(row["dc_dmm"]))
            for index, (row, expected) in enumerate(zip(
                conditioning_rows, expected_bridges))))
    expected_keys = {str(index) for index in range(start, end)}
    pilot_pass = bool(
        set(pilot_verification) == expected_keys and
        all(value.get("verified", False) and
            int(value.get("source_sequence_index", -1)) == int(key) and
            int(value.get("expected_pilot_count", 0)) == 1 and
            value.get("pilot_count_pass", False) and
            value.get("frequency_pass", False) and
            value.get("amplitude_pass", False) and
            value.get("acquisition_count_pass", False) and
            value.get("acquisition_frequencies_pass", False) and
            int(value.get("expected_acquisition_count", 0)) == 2
            for key, value in pilot_verification.items()))
    discard_contract_pass = bool(
        len(rows) == end - start and len(discards) == len(rows) and all(
            int(discard["transition_discard_index"]) == local and
            int(row["transition_discard_index"]) == local and
            int(discard["source_sequence_index"]) ==
            int(row["sequence_index"]) and
            all(str(discard[name]) == str(row[name]) for name in
                ("role", "direction")) and
            all(int(discard[name]) == int(row[name]) for name in
                ("grid_index", "target_ordinal", "pair_position")) and
            bool(row["transition_followed_without_reconfigure"]) and
            float(discard["t_end_unix"]) <= float(row["t_acq_start_unix"]) and
            float(row["t_acq_start_unix"]) -
            float(discard["t_end_unix"]) <= it.DISCARD_TO_FORMAL_MAX_S
            for local, (discard, row) in enumerate(zip(discards, rows))))
    window_contract_pass = bool(
        len(windows) == len(rows) * it.N_AVG and all(
            int(window["window_sequence_index"]) == local and
            int(window["source_sequence_index"]) ==
            int(rows[local // it.N_AVG]["sequence_index"]) and
            int(window["window_index"]) == local % it.N_AVG and
            all(str(window[name]) == str(rows[local // it.N_AVG][name])
                for name in ("role", "direction")) and
            all(int(window[name]) == int(rows[local // it.N_AVG][name])
                for name in ("grid_index", "target_ordinal", "pair_position")) and
            float(window["t_start_unix"]) < float(window["t_end_unix"])
            for local, window in enumerate(windows)))
    bracket_pass = bool(rows and all(
        float(row["t_dmm_pre_start_unix"]) <
        float(row["t_dmm_pre_end_unix"]) <=
        float(row["t_acq_start_unix"]) < float(row["t_acq_end_unix"]) <=
        float(row["t_dmm_post_start_unix"]) <
        float(row["t_dmm_post_end_unix"]) and
        0.0 <= float(row["dmm_interpolation_weight"]) <= 1.0 and
        all(np.isfinite(float(row[name])) for name in
            ("dc_dmm_pre", "dc_dmm_post", "dc_dmm_interp"))
        for row in rows))
    settle_pass = bool(rows and all(
        float(row["t_target_set_unix"]) -
        float(row["t_approach_set_unix"]) >= it.BIAS_SETTLE_S - 1e-3 and
        float(row["t_discard_start_unix"]) -
        float(row["t_target_set_unix"]) >= it.BIAS_SETTLE_S - 1e-3
        for row in rows))
    discard_raw = (tt.analyze_adc_raw_telemetry(**_raw_arrays(discards))
                   if discards else {"accepted": False})
    window_raw = (tt.analyze_adc_raw_telemetry(**_raw_arrays(windows))
                  if windows else {"accepted": False})
    row_raw = (tt.analyze_adc_raw_telemetry(**_raw_arrays(rows))
               if rows else {"accepted": False})
    discard_capture_pass = bool(
        discard_raw.get("contract_pass", False) and
        discard_raw.get("acquisition_complete_pass", False) and
        _exact_raw_capture_pass(discards, it.DISCARD_BLOCKS, 1))
    formal_capture_pass = bool(
        window_raw.get("accepted", False) and row_raw.get("accepted", False) and
        _exact_raw_capture_pass(windows, it.N_BLOCKS, 1) and
        _exact_raw_capture_pass(rows, it.N_BLOCKS * it.N_AVG, it.N_AVG))
    max_code = max(max(abs(int(row["rawadc_ch0_min"])),
                       abs(int(row["rawadc_ch0_max"]))) for row in rows)
    headroom_pass = bool(max_code <= it.HEADROOM_LIMIT_CODE)
    hash_pass = bool(set(discard_file_sha256) == {
        "transition_discard.csv", "transition_discard.npz"} and
        all(len(value) == 64 for value in discard_file_sha256.values()))
    gates = dict(
        schedule_contract_pass=schedule_pass,
        conditioning_contract_pass=conditioning_pass,
        single_pilot_configuration_verified=pilot_pass,
        transition_discard_contract_pass=discard_contract_pass,
        transition_discard_capture_pass=discard_capture_pass,
        transition_discard_hash_contract_pass=hash_pass,
        formal_window_contract_pass=window_contract_pass,
        formal_capture_pass=formal_capture_pass,
        dmm_bracket_pass=bracket_pass,
        preposition_settle_pass=settle_pass,
        formal_headroom_pass=headroom_pass)
    gates["accepted"] = bool(all(gates.values()))
    return dict(
        protocol_version=it.PROTOCOL_VERSION,
        segment_index=int(segment_index), segment_start=start, segment_end=end,
        quality_gate=gates, observations=len(rows), windows=len(windows),
        discards=len(discards), conditioning_rows=len(conditioning_rows),
        formal_max_abs_raw_code=int(max_code),
        formal_max_abs_raw_V=float(max_code * 1.2 / 8388608.0),
        transition_discard_file_sha256=dict(discard_file_sha256),
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False)


def _configure_single_pilot(board, bias):
    board.gen_reset()
    board.gen_bias(mb.CH, float(bias))
    board.gen_pilot(mb.CH, mb.PILOT_HZ, it.PILOT_V)


def main():
    signal.signal(signal.SIGINT, _abort)
    signal.signal(signal.SIGTERM, _abort)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--firmware-rev", required=True)
    parser.add_argument("--ambient-c", type=float, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--instrument-ids", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--segment-index", type=int,
                        choices=range(it.SEGMENT_COUNT))
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--sim-fail-after", type=int)
    parser.add_argument("--sim-fault", choices=(
        "none", "formal_rail", "formal_headroom", "formal_sample",
        "discard_missing", "discard_duplicate", "discard_sample",
        "discard_rail", "dmm_bracket", "approach", "mapping",
        "sentinel", "dmm_direction", "acq_frequency", "after_discard"),
        default="none")
    parser.add_argument("--i-understand-this-writes-real-hardware",
                        action="store_true")
    args = parser.parse_args()
    if not args.sim and not args.i_understand_this_writes_real_hardware:
        raise RuntimeError("real diagnostic requires explicit hardware acknowledgement")
    if not args.sim and args.segment_index is None:
        raise RuntimeError("v1.1 real diagnostic requires --segment-index")
    if (args.sim_fail_after is not None or args.sim_fault != "none") and not args.sim:
        raise ValueError("simulation fault injection is valid only with --sim")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")

    schedule = it.build_schedule()
    all_schedule_records = it.schedule_records(schedule)
    if args.segment_index is None:
        segment_start, segment_end = 0, len(all_schedule_records)
    else:
        segment_start, segment_end = it.segment_bounds(args.segment_index)
    schedule_records = all_schedule_records[segment_start:segment_end]
    bridges = _expected_bridges(schedule_records)
    root = (os.path.join(ec.REPO, "build", "exp_sim",
                         "interleaved_calibration", args.run_id)
            if args.sim else os.path.join(
                ec.DATA, "diagnostics", "interleaved_calibration", args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    _write_json(os.path.join(root, "manifest.json"), dict(
        run_id=args.run_id, status="failed", failure="initialization incomplete",
        started_unix=started, ended_unix=None, conditioning_rows=0,
        acquired_observations=0, expected_observations=len(schedule_records),
        acquired_windows=0, expected_windows=len(schedule_records) * it.N_AVG,
        acquired_discards=0, expected_discards=len(schedule_records),
        board_final_status=None, quality_gate_accepted=None))
    _refresh_checksums(root)
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    source_paths = {
        "diagnose_mzm_interleaved_calibration.py": os.path.abspath(__file__),
        "mzm_interleaved_truth.py": os.path.abspath(it.__file__),
        "mzm_time_truth.py": os.path.abspath(tt.__file__),
        "measure_bench.py": os.path.abspath(mb.__file__),
        "exp_common.py": os.path.abspath(ec.__file__),
        "mzm_interleaved_calibration_protocol.md": os.path.join(
            ec.REPO, "reviews", "mzm_interleaved_calibration_protocol.md"),
        "analyze_mzm_interleaved_segments.py": os.path.join(
            ec.REPO, "scripts", "analyze_mzm_interleaved_segments.py"),
        "validate_mzm_interleaved_bundle.py": os.path.join(
            ec.REPO, "scripts", "validate_mzm_interleaved_bundle.py"),
    }
    protocol = dict(
        protocol_version=it.PROTOCOL_VERSION, purpose="diagnostic_only",
        simulated=bool(args.sim), run_id=args.run_id,
        segmented=args.segment_index is not None,
        segment_index=args.segment_index, segment_start=segment_start,
        segment_end=segment_end,
        fixed_vpi_V=tt.VPI_V, coordinate_center_V=tt.CENTER_V,
        pilot_V=it.PILOT_V, pilot_Hz=mb.PILOT_HZ,
        discard_blocks=it.DISCARD_BLOCKS, formal_blocks=it.N_BLOCKS,
        formal_windows=it.N_AVG, bias_settle_s=it.BIAS_SETTLE_S,
        discard_to_formal_max_s=it.DISCARD_TO_FORMAL_MAX_S,
        headroom_limit_V=it.HEADROOM_LIMIT_V,
        headroom_limit_code=it.HEADROOM_LIMIT_CODE,
        target_order=it.target_order().tolist(),
        schedule_sha256=it.schedule_sha256(schedule), schedule=all_schedule_records,
        segment_schedule=schedule_records,
        expected_bridge_rows=len(bridges),
        quality_gates=dict(
            design_abs_corr=tt.DESIGN_CORR_LIMIT,
            target_time_abs_corr=tt.DESIGN_CORR_LIMIT,
            design_condition_number=tt.DESIGN_COND_LIMIT,
            dc_normalized_rmse=tt.DC_NORMALIZED_RMSE_LIMIT,
            dmm_bracket_normalized_max=tt.DC_NORMALIZED_RMSE_LIMIT,
            direction_split_phase_rad=tt.PHASE_LIMIT_RAD,
            drift_30min_phase_rad=tt.PHASE_LIMIT_RAD,
            mapping_median_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
            mapping_p95_mrad=tt.SELFCHECK_P95_LIMIT_MRAD),
        metadata=dict(
            device_id=args.device_id, firmware_rev=args.firmware_rev,
            ambient_c=float(args.ambient_c), operator=args.operator,
            session_id=args.session_id, instrument_ids=args.instrument_ids,
            notes=args.notes),
        repo_commit=repo_commit,
        source_sha256={name: _sha256(path) for name, path in source_paths.items()},
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False)
    _write_json(os.path.join(root, "protocol.json"), protocol)

    paths = {
        "main": os.path.join(root, "interleaved_calibration.csv"),
        "window": os.path.join(root, "formal_windows.csv"),
        "discard": os.path.join(root, "transition_discard.csv"),
        "conditioning": os.path.join(root, "conditioning.csv"),
    }
    for key, header in (("main", MAIN_HEADER), ("window", WINDOW_HEADER),
                        ("discard", DISCARD_HEADER),
                        ("conditioning", CONDITIONING_HEADER)):
        with open(paths[key], "w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(header)
    _refresh_checksums(root)

    rows = []
    windows = []
    discards = []
    conditioning_rows = []
    pilot_verification = {}
    status = "failed"
    failure = None
    board_final_status = None
    board_initial_status = None
    analysis = None
    caught = None
    sim_clock = (1_800_200_000.0 +
                 900.0 * (0 if args.segment_index is None
                          else args.segment_index))
    current_bias = 0.0
    discard_attempts = 0

    def checkpoint(complete=False):
        _write_json(os.path.join(root, "summary.json"), dict(
            complete=bool(complete), conditioning_rows=len(conditioning_rows),
            expected_conditioning_rows=len(bridges),
            acquired_observations=len(rows),
            expected_observations=len(schedule_records),
            acquired_windows=len(windows),
            expected_windows=len(schedule_records) * it.N_AVG,
            acquired_discards=len(discards),
            expected_discards=len(schedule_records), analysis=analysis))

    def persist_discard(acq, timing, item):
        nonlocal discard_attempts
        attempt = discard_attempts
        discard_attempts += 1
        raw = acq.get("rawadc")
        if raw is None:
            raise RuntimeError("transition-discard RAWADC telemetry missing")
        index = len(discards)
        row = dict(
            transition_discard_index=index, role=item["role"],
            direction=item["direction"], grid_index=item["grid_index"],
            target_ordinal=item["target_ordinal"],
            pair_position=item["pair_position"],
            source_sequence_index=item["sequence_index"], bias=item["bias_V"],
            approach_bias=item["approach_bias_V"],
            t_target_set_unix=item["t_target_set_unix"],
            t_start_unix=timing[0], t_end_unix=timing[1],
            t_mid_unix=0.5 * sum(timing), dc_board=float(acq["dc"]),
            I1=float(acq["tones"][mb.PILOT_HZ]["I"]),
            Q1=float(acq["tones"][mb.PILOT_HZ]["Q"]),
            I2=float(acq["tones"][mb.H2_HZ]["I"]),
            Q2=float(acq["tones"][mb.H2_HZ]["Q"]),
            **{f"rawadc_{name}": raw[name] for name in RAW_FIELDS})
        if args.sim and args.sim_fault == "discard_missing" and attempt == 0:
            return index
        with open(paths["discard"], "a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow([row[name] for name in DISCARD_HEADER])
        discards.append(row)
        if args.sim and args.sim_fault == "discard_duplicate" and attempt == 0:
            duplicate = dict(row)
            duplicate["transition_discard_index"] = 1
            with open(paths["discard"], "a", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(
                    [duplicate[name] for name in DISCARD_HEADER])
            discards.append(duplicate)
        return index

    try:
        with ExitStack() as stack:
            if args.sim:
                board = mb.SimBoard(seed=20260717)
                board.VPI = tt.VPI_V
                board.V0 = tt.CENTER_V
                board.DC_A = 0.60
                board.DC_B = 0.40
                dmm = mb.SimDMM(board)
            else:
                board = stack.enter_context(mb.open_board())
                dmm = stack.enter_context(mb.open_dmm())
            try:
                board_initial_status = ({"State": "SIM", "Bias": "SIM"}
                                        if args.sim else board.status())
                mb.assert_board_ready_for_evidence(board)
                mb.configure_dc_fast(dmm)
                if not args.sim:
                    board.acq_reset()
                    for frequency in mb.ACQ_FREQS:
                        board.acq_add(frequency)
                    time.sleep(0.4)
                    acquisition_response = board.acq_show()
                    if ("freqs: 2" not in acquisition_response or
                            "f=1000.0Hz" not in acquisition_response or
                            "f=2000.0Hz" not in acquisition_response):
                        raise RuntimeError(
                            "two-frequency acquisition configuration failed")
                for item in schedule_records:
                    observation = int(item["sequence_index"])
                    local_observation = observation - segment_start
                    if not args.sim:
                        board.gen_reset()
                    expected_bridge = [record for record in bridges
                                       if record["observation_sequence_index"] == observation]
                    t_approach_set = None
                    for expected in expected_bridge:
                        if args.sim:
                            t_start = sim_clock
                            sim_clock += it.BIAS_SETTLE_S
                            board._last_dc_true = board.dc_true_at(expected["bias"])
                            dc_bridge = mb.read_dc(dmm)
                            response = "SIM dac"
                            t_end = sim_clock
                        else:
                            t_start = time.time()
                            response = board.dac(expected["bias"])
                            time.sleep(it.BIAS_SETTLE_S)
                            dc_bridge = mb.read_dc(dmm)
                            t_end = time.time()
                        bridge_row = dict(
                            **expected, t_start_unix=t_start, t_end_unix=t_end,
                            t_mid_unix=0.5 * (t_start + t_end),
                            dc_dmm=float(dc_bridge), dac_response=str(response))
                        with open(paths["conditioning"], "a", newline="",
                                  encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [bridge_row[name] for name in CONDITIONING_HEADER])
                        conditioning_rows.append(bridge_row)
                        current_bias = expected["bias"]
                        t_approach_set = t_start

                    if args.sim:
                        t_target_set = sim_clock
                        sim_clock += it.BIAS_SETTLE_S
                    else:
                        t_target_set = time.time()
                        board.dac(item["bias_V"])
                        time.sleep(it.BIAS_SETTLE_S)
                    current_bias = item["bias_V"]
                    item_runtime = dict(item, t_target_set_unix=t_target_set)

                    if args.sim:
                        key = str(observation)
                        pilot_verification[key] = dict(
                            verified=(args.sim_fault != "acq_frequency" or
                                      local_observation != 0), simulated=True,
                            source_sequence_index=observation,
                            pilot_count_pass=True, frequency_pass=True,
                            amplitude_pass=True, expected_pilot_count=1,
                            acquisition_count_pass=(
                                args.sim_fault != "acq_frequency" or
                                local_observation != 0),
                            acquisition_frequencies_pass=(
                                args.sim_fault != "acq_frequency" or
                                local_observation != 0),
                            expected_acquisition_count=2,
                            expected_frequency_Hz=mb.PILOT_HZ,
                            expected_amplitude_V=it.PILOT_V,
                            response="SIM single pilot")
                        _write_json(os.path.join(
                            root, "pilot_verification.json"), pilot_verification)
                        discard_start = sim_clock
                        discard_acq = board.acq_run_mzm(
                            item["bias_V"], pilot_v=it.PILOT_V,
                            n_blocks=it.DISCARD_BLOCKS)
                        sim_clock += 1.0
                        discard_end = sim_clock
                    else:
                        _configure_single_pilot(board, item["bias_V"])
                        key = str(observation)
                        response = board.gen_show()
                        count_ok = "pilots: 1" in response
                        frequency_ok = f"f={mb.PILOT_HZ:.1f}Hz" in response
                        amplitude_ok = f"amp={it.PILOT_V:.4f}V" in response
                        acquisition_count_ok = "freqs: 2" in response
                        acquisition_frequencies_ok = (
                            "f=1000.0Hz" in response and
                            "f=2000.0Hz" in response)
                        pilot_verification[key] = dict(
                            verified=bool(count_ok and frequency_ok and amplitude_ok and
                                          acquisition_count_ok and
                                          acquisition_frequencies_ok),
                            simulated=False, source_sequence_index=observation,
                            pilot_count_pass=count_ok,
                            frequency_pass=frequency_ok,
                            amplitude_pass=amplitude_ok,
                            acquisition_count_pass=acquisition_count_ok,
                            acquisition_frequencies_pass=
                            acquisition_frequencies_ok,
                            expected_pilot_count=1,
                            expected_acquisition_count=2,
                            expected_frequency_Hz=mb.PILOT_HZ,
                            expected_amplitude_V=it.PILOT_V, response=response)
                        _write_json(os.path.join(
                            root, "pilot_verification.json"), pilot_verification)
                        if not pilot_verification[key]["verified"]:
                            raise RuntimeError("single-pilot verification failed")
                        discard_start = time.time()
                        discard_acq = mb.attach_rawadc_telemetry(
                            board.acq_run(it.DISCARD_BLOCKS))
                        discard_end = time.time()
                    if (args.sim and args.sim_fault == "discard_sample" and
                            local_observation == 0):
                        raw = discard_acq["rawadc"]
                        raw.update(used=raw["expected"] - 1, complete=False)
                    if (args.sim and args.sim_fault == "discard_rail" and
                            local_observation == 0):
                        discard_acq["rawadc"].update(
                            ch0_max=8388607, ch0_rail_hi=1, ch0_guard_hi=1)
                    discard_index = persist_discard(
                        discard_acq, (discard_start, discard_end), item_runtime)
                    if (args.sim and args.sim_fault == "after_discard" and
                            local_observation == 0):
                        raise RuntimeError("injected failure after persisted discard")

                    if args.sim:
                        pre_start = sim_clock
                        sim_clock += 0.05
                        board._last_dc_true = board.dc_true_at(item["bias_V"])
                        dc_pre = mb.read_dc(dmm)
                        pre_end = sim_clock
                    else:
                        pre_start = time.time()
                        dc_pre = mb.read_dc(dmm)
                        pre_end = time.time()

                    observation_windows = []
                    for window_index in range(it.N_AVG):
                        if args.sim:
                            window_start = sim_clock
                            acq = board.acq_run_mzm(
                                item["bias_V"], pilot_v=it.PILOT_V,
                                n_blocks=it.N_BLOCKS)
                            sim_clock += 1.0
                            window_end = sim_clock
                        else:
                            window_start = time.time()
                            acq = mb.attach_rawadc_telemetry(
                                board.acq_run(it.N_BLOCKS))
                            window_end = time.time()
                        if not mb._valid_acq(acq) or acq.get("rawadc") is None:
                            raise RuntimeError("invalid formal acquisition window")
                        if (args.sim and local_observation == 0 and
                                window_index == 0):
                            if args.sim_fault == "formal_rail":
                                acq["rawadc"].update(
                                    ch0_max=8388607, ch0_rail_hi=1,
                                    ch0_guard_hi=1)
                            elif args.sim_fault == "formal_headroom":
                                acq["rawadc"].update(ch0_max=6710886)
                            elif args.sim_fault == "formal_sample":
                                raw = acq["rawadc"]
                                raw.update(used=raw["expected"] - 1,
                                           complete=False)
                        if args.sim and args.sim_fault == "mapping" and item[
                                "direction"] == "down":
                            acq["tones"][mb.PILOT_HZ]["I"] += 0.05
                            acq["tones"][mb.H2_HZ]["I"] += (
                                0.12 * acq["tones"][mb.PILOT_HZ]["I"])
                        raw = acq["rawadc"]
                        window_row = dict(
                            window_sequence_index=len(windows),
                            source_sequence_index=observation,
                            window_index=window_index, role=item["role"],
                            direction=item["direction"],
                            grid_index=item["grid_index"],
                            target_ordinal=item["target_ordinal"],
                            pair_position=item["pair_position"],
                            bias=item["bias_V"], t_start_unix=window_start,
                            t_end_unix=window_end,
                            t_mid_unix=0.5 * (window_start + window_end),
                            dc_board=float(acq["dc"]),
                            I1=float(acq["tones"][mb.PILOT_HZ]["I"]),
                            Q1=float(acq["tones"][mb.PILOT_HZ]["Q"]),
                            I2=float(acq["tones"][mb.H2_HZ]["I"]),
                            Q2=float(acq["tones"][mb.H2_HZ]["Q"]),
                            **{f"rawadc_{name}": raw[name]
                               for name in RAW_FIELDS})
                        with open(paths["window"], "a", newline="",
                                  encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [window_row[name] for name in WINDOW_HEADER])
                        windows.append(window_row)
                        observation_windows.append(window_row)

                    if args.sim:
                        post_start = sim_clock
                        sim_clock += 0.05
                        board._last_dc_true = board.dc_true_at(item["bias_V"])
                        dc_post = mb.read_dc(dmm)
                        post_end = sim_clock
                    else:
                        post_start = time.time()
                        dc_post = mb.read_dc(dmm)
                        post_end = time.time()
                    if args.sim and args.sim_fault == "sentinel" and item[
                            "role"] == "sentinel" and local_observation == 0:
                        dc_pre += 0.12
                        dc_post += 0.12
                    if args.sim and args.sim_fault == "dmm_direction" and item[
                            "direction"] == "down":
                        shifted = board.dc_true_at(item["bias_V"] - 0.10)
                        dc_pre = dc_post = shifted

                    pre_mid = 0.5 * (pre_start + pre_end)
                    post_mid = 0.5 * (post_start + post_end)
                    acq_mid = float(np.mean([
                        row["t_mid_unix"] for row in observation_windows]))
                    weight = float((acq_mid - pre_mid) / (post_mid - pre_mid))
                    dc_interp = float(dc_pre + weight * (dc_post - dc_pre))
                    if (args.sim and args.sim_fault == "dmm_bracket" and
                            local_observation == 0):
                        pre_end = observation_windows[0]["t_start_unix"] + 0.1

                    raw_records = [{name: row[f"rawadc_{name}"]
                                    for name in RAW_FIELDS}
                                   for row in observation_windows]
                    merged_raw = mb.merge_rawadc_telemetry(raw_records)
                    row = dict(
                        role=item["role"], direction=item["direction"],
                        grid_index=item["grid_index"],
                        target_ordinal=item["target_ordinal"],
                        pair_position=item["pair_position"],
                        sequence_index=observation, bias=item["bias_V"],
                        approach_bias=(item["bias_V"] if args.sim and
                                       args.sim_fault == "approach" and
                                       local_observation == 0
                                       else item["approach_bias_V"]),
                        bias_settle_s=it.BIAS_SETTLE_S,
                        t_approach_set_unix=t_approach_set,
                        t_target_set_unix=t_target_set,
                        transition_discard_index=discard_index,
                        transition_followed_without_reconfigure=True,
                        t_discard_start_unix=discard_start,
                        t_discard_end_unix=discard_end,
                        t_dmm_pre_start_unix=pre_start,
                        t_dmm_pre_end_unix=pre_end,
                        t_dmm_pre_mid_unix=0.5 * (pre_start + pre_end),
                        dc_dmm_pre=float(dc_pre),
                        t_acq_start_unix=observation_windows[0]["t_start_unix"],
                        t_acq_end_unix=observation_windows[-1]["t_end_unix"],
                        t_acq_mid_unix=acq_mid,
                        t_dmm_post_start_unix=post_start,
                        t_dmm_post_end_unix=post_end,
                        t_dmm_post_mid_unix=post_mid,
                        dc_dmm_post=float(dc_post),
                        dmm_interpolation_weight=weight,
                        dc_dmm_interp=dc_interp,
                        dc_board=float(np.mean([
                            value["dc_board"] for value in observation_windows])),
                        I1=float(np.mean([value["I1"] for value in observation_windows])),
                        Q1=float(np.mean([value["Q1"] for value in observation_windows])),
                        I2=float(np.mean([value["I2"] for value in observation_windows])),
                        Q2=float(np.mean([value["Q2"] for value in observation_windows])),
                        **{f"rawadc_{name}": merged_raw[name]
                           for name in RAW_FIELDS})
                    with open(paths["main"], "a", newline="", encoding="utf-8") as stream:
                        csv.writer(stream).writerow([row[name] for name in MAIN_HEADER])
                    rows.append(row)
                    checkpoint(False)
                    if (args.sim_fail_after is not None and
                            len(rows) >= args.sim_fail_after):
                        raise RuntimeError(
                            f"injected failure after {len(rows)} observations")
                    if len(rows) == 1 or len(rows) % 10 == 0 or len(rows) == len(
                            schedule_records):
                        print(
                            f"[interleaved-cal] {len(rows):3d}/{len(schedule_records)} "
                            f"target={item['grid_index']:02d} {item['direction']:>4} "
                            f"role={item['role']:<8} DMM={dc_interp:.4f}", flush=True)

                main_fields = {name: np.asarray([row[name] for row in rows])
                               for name in MAIN_HEADER}
                window_fields = {name: np.asarray([row[name] for row in windows])
                                 for name in WINDOW_HEADER}
                discard_fields = {name: np.asarray([row[name] for row in discards])
                                  for name in DISCARD_HEADER}
                for filename, fields in (
                        ("interleaved_calibration.npz", main_fields),
                        ("formal_windows.npz", window_fields),
                        ("transition_discard.npz", discard_fields)):
                    tmp = os.path.join(root, filename + ".tmp.npz")
                    np.savez(tmp, **fields,
                             schedule_sha256=it.schedule_sha256(schedule))
                    os.replace(tmp, os.path.join(root, filename))
                discard_hashes = {
                    name: _sha256(os.path.join(root, name)) for name in (
                        "transition_discard.csv", "transition_discard.npz")}
                if args.segment_index is None:
                    analysis = _analyze(
                        rows, windows, discards, conditioning_rows,
                        pilot_verification, discard_hashes)
                else:
                    analysis = _analyze_segment(
                        rows, windows, discards, conditioning_rows,
                        pilot_verification, discard_hashes,
                        args.segment_index)
                _write_json(os.path.join(root, "analysis.json"), analysis)
                status = "complete"
                checkpoint(True)
            except BaseException as exc:
                caught = exc
                failure = f"{type(exc).__name__}: {exc}"
            finally:
                if args.sim:
                    board_final_status = {"State": "SIM", "Bias": "SIM"}
                else:
                    try:
                        board.gen_reset()
                        board.dac(0.0)
                        board_final_status = board.status()
                        if (str(board_final_status.get("State", "")).upper() != "IDLE" or
                                not str(board_final_status.get("Bias", "")).strip().startswith(
                                    "0.000") or
                                str(board_final_status.get("Lock", "NO")).upper() != "NO" or
                                str(board_final_status.get("Cal", "INVALID")).upper() !=
                                "INVALID"):
                            raise RuntimeError(
                                f"unsafe final board status: {board_final_status}")
                    except Exception as cleanup_exc:
                        text = f"cleanup failed: {type(cleanup_exc).__name__}: {cleanup_exc}"
                        status = "failed"
                        failure = text if failure is None else f"{failure}; {text}"
                        if caught is None:
                            caught = RuntimeError(text)
    except BaseException as exc:
        if caught is None:
            caught = exc
            failure = f"{type(exc).__name__}: {exc}"
    finally:
        checkpoint(status == "complete")
        _write_json(os.path.join(root, "manifest.json"), dict(
            run_id=args.run_id, status=status, failure=failure,
            started_unix=started, ended_unix=time.time(),
            conditioning_rows=len(conditioning_rows),
            acquired_observations=len(rows),
            expected_observations=len(schedule_records),
            acquired_windows=len(windows),
            expected_windows=len(schedule_records) * it.N_AVG,
            acquired_discards=len(discards),
            expected_discards=len(schedule_records),
            board_final_status=board_final_status,
            board_initial_status=board_initial_status,
            quality_gate_accepted=(None if analysis is None else
                                   analysis["quality_gate"]["accepted"])))
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(analysis["quality_gate"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
