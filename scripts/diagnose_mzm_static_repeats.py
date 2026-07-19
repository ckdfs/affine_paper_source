#!/usr/bin/env python3
"""Acquire the preregistered static-repeat restart-isolation diagnostic."""
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
import mzm_static_repeat_truth as st
import mzm_time_truth as tt


RAW_FIELDS = (
    "version", "scope", "expected", "used", "read_fail", "blocks",
    "complete", "timeout", "gain", "fs_uv", "guard", "crc", "ch0_min",
    "ch0_max", "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo",
    "ch0_guard_hi", "windows",
)
MAIN_HEADER = [
    "repeat_sequence_index", "point_ordinal", "grid_index", "block_index",
    "condition", "condition_ordinal", "repeat_index", "bias",
    "approach_bias", "restart_gen", "restart_acq",
    "t_restart_start_unix", "t_restart_end_unix",
    "t_discard_start_unix", "t_discard_end_unix",
    "t_acq_first_attempt_start_unix",
    "discard_read_retries", "formal_read_retries",
    "t_dmm_pre1_start_unix", "t_dmm_pre1_end_unix", "dc_dmm_pre1",
    "t_dmm_pre2_start_unix", "t_dmm_pre2_end_unix", "dc_dmm_pre2",
    "t_acq_start_unix", "t_acq_end_unix", "t_acq_mid_unix",
    "t_dmm_post1_start_unix", "t_dmm_post1_end_unix", "dc_dmm_post1",
    "t_dmm_post2_start_unix", "t_dmm_post2_end_unix", "dc_dmm_post2",
    "dc_board", "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
WINDOW_HEADER = [
    "window_sequence_index", "source_repeat_index", "window_index",
    "point_ordinal", "grid_index", "block_index", "condition", "bias",
    "t_start_unix", "t_end_unix", "t_mid_unix", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
DISCARD_HEADER = [
    "transition_discard_index", "source_repeat_index", "point_ordinal",
    "grid_index", "block_index", "condition", "bias",
    "t_start_unix", "t_end_unix", "t_mid_unix", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
CONDITIONING_HEADER = [
    "sequence_index", "point_ordinal", "bridge_step_index", "is_target",
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


def _analyze(rows, windows, discards, conditioning_rows, pilot_verification,
             block_config, read_failures):
    schedule = st.build_schedule()
    schedule_contract_pass = False
    try:
        schedule_contract_pass = st.validate_schedule_arrays(
            point_ordinal=[row["point_ordinal"] for row in rows],
            grid_index=[row["grid_index"] for row in rows],
            block_index=[row["block_index"] for row in rows],
            condition=[row["condition"] for row in rows],
            condition_ordinal=[row["condition_ordinal"] for row in rows],
            repeat_index=[row["repeat_index"] for row in rows],
            bias=[row["bias"] for row in rows],
            approach_bias=[row["approach_bias"] for row in rows],
            restart_gen=[row["restart_gen"] for row in rows],
            restart_acq=[row["restart_acq"] for row in rows],
            repeat_sequence_index=[row["repeat_sequence_index"]
                                   for row in rows])
    except Exception:
        schedule_contract_pass = False

    expected_conditioning = st.expected_bridges()
    step = st.grid_step()
    conditioning_contract_pass = bool(
        len(conditioning_rows) == len(expected_conditioning) and
        all(all(int(row[name]) == int(expected[name]) for name in (
                    "sequence_index", "point_ordinal", "bridge_step_index",
                    "is_target")) and
            all(np.isclose(float(row[name]), float(expected[name]),
                           atol=1e-12, rtol=0) for name in (
                               "from_bias", "bias", "delta_bias")) and
            abs(float(row["delta_bias"])) <= step + 1e-12 and
            float(row["t_start_unix"]) < float(row["t_end_unix"]) and
            np.isclose(float(row["t_mid_unix"]),
                       0.5 * (float(row["t_start_unix"]) +
                              float(row["t_end_unix"])), atol=1e-9, rtol=0) and
            np.isfinite(float(row["dc_dmm"]))
            for row, expected in zip(conditioning_rows, expected_conditioning)))

    def _attempts_ok(attempts):
        return bool(
            isinstance(attempts, list) and
            1 <= len(attempts) <= st.ACQ_VERIFY_ATTEMPTS and
            attempts[-1].get("passed", False) and
            all(int(a.get("attempt_index", -1)) == i and
                float(a.get("t_start_unix", np.inf)) <
                float(a.get("t_end_unix", -np.inf)) and
                not a.get("passed", False)
                for i, a in enumerate(attempts[:-1])))

    block_config_contract_pass = bool(
        set(block_config) == {str(i) for i in range(st.TOTAL_BLOCKS)} and
        all(value.get("acq_show_pass", False) and
            value.get("gen_configured", False) and
            int(value.get("block_index", -1)) == int(key) and
            float(value.get("t_start_unix", np.inf)) <
            float(value.get("t_end_unix", -np.inf)) and
            _attempts_ok(value.get("acq_show_attempts"))
            for key, value in block_config.items()))

    expected_verification = {str(i) for i in range(st.TOTAL_REPEATS)}
    verification_pass = bool(
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
                       st.PILOT_V, atol=0, rtol=0) and
            int(value.get("repeat_sequence_index", -1)) == int(key) and
            (not schedule["restart_acq"][int(key)] or
             (value.get("restart_acq_show_pass", False) and
              _attempts_ok(value.get("restart_acq_attempts"))))
            for key, value in pilot_verification.items()))
    acq_restart_retry_total = int(
        sum(max(0, len(value.get("restart_acq_attempts") or []) - 1)
            for value in pilot_verification.values()) +
        sum(max(0, len(value.get("acq_show_attempts") or []) - 1)
            for value in block_config.values()))

    restart_contract_pass = bool(rows and all(
        int(row["restart_gen"]) == int(schedule["restart_gen"][i]) and
        int(row["restart_acq"]) == int(schedule["restart_acq"][i]) and
        float(row["t_restart_start_unix"]) <=
        float(row["t_restart_end_unix"]) <=
        float(row["t_discard_start_unix"]) and
        ((int(row["restart_gen"]) or int(row["restart_acq"])) ==
         (float(row["t_restart_end_unix"]) >
          float(row["t_restart_start_unix"])))
        for i, row in enumerate(rows)))

    discard_contract_pass = bool(
        len(rows) == st.TOTAL_REPEATS and len(discards) == len(rows) and all(
            int(discard["transition_discard_index"]) == i and
            int(discard["source_repeat_index"]) ==
            int(row["repeat_sequence_index"]) and
            str(discard["condition"]) == str(row["condition"]) and
            all(int(discard[name]) == int(row[name]) for name in (
                "point_ordinal", "grid_index", "block_index")) and
            np.isclose(float(discard["bias"]), float(row["bias"]),
                       atol=0, rtol=0) and
            np.isclose(float(discard["t_start_unix"]),
                       float(row["t_discard_start_unix"]), atol=0, rtol=0) and
            float(discard["t_start_unix"]) < float(discard["t_end_unix"]) <=
            float(row["t_acq_first_attempt_start_unix"]) <=
            float(row["t_acq_start_unix"]) and
            float(row["t_acq_first_attempt_start_unix"]) -
            float(discard["t_end_unix"]) <= st.DISCARD_TO_FORMAL_MAX_S
            for i, (discard, row) in enumerate(zip(discards, rows))))

    failure_counts = {}
    failures_valid = True
    for entry in read_failures:
        try:
            seq = int(entry["repeat_sequence_index"])
            phase = str(entry["phase"])
            attempt = int(entry["attempt_index"])
            ok = (phase in ("discard", "formal") and
                  0 <= seq < st.TOTAL_REPEATS and
                  0 <= attempt < st.ACQ_READ_ATTEMPTS and
                  float(entry["t_start_unix"]) < float(entry["t_end_unix"]) and
                  ((entry.get("window_index") is None) ==
                   (phase == "discard")))
        except Exception:
            ok = False
        if not ok:
            failures_valid = False
            break
        failure_counts[(seq, phase)] = failure_counts.get((seq, phase), 0) + 1
    read_failure_contract_pass = bool(failures_valid and rows and all(
        int(row["discard_read_retries"]) == failure_counts.get(
            (int(row["repeat_sequence_index"]), "discard"), 0) and
        int(row["formal_read_retries"]) == failure_counts.get(
            (int(row["repeat_sequence_index"]), "formal"), 0) and
        0 <= int(row["discard_read_retries"]) <= st.ACQ_READ_ATTEMPTS - 1 and
        0 <= int(row["formal_read_retries"]) <=
        st.N_WINDOWS * (st.ACQ_READ_ATTEMPTS - 1)
        for row in rows))
    discard_read_retry_total = int(sum(
        count for (seq, phase), count in failure_counts.items()
        if phase == "discard"))
    formal_read_retry_total = int(sum(
        count for (seq, phase), count in failure_counts.items()
        if phase == "formal"))
    discard_raw_gate = (tt.analyze_adc_raw_telemetry(**_raw_arrays(discards))
                        if discards else {"accepted": False})
    discard_capture_pass = bool(
        discards and discard_raw_gate.get("contract_pass", False) and
        discard_raw_gate.get("acquisition_complete_pass", False) and
        _exact_raw_capture_pass(discards, st.DISCARD_BLOCKS, 1))

    window_contract_pass = bool(
        len(windows) == len(rows) * st.N_WINDOWS and all(
            int(window["window_sequence_index"]) == i and
            int(window["source_repeat_index"]) == i // st.N_WINDOWS and
            int(window["window_index"]) == i % st.N_WINDOWS and
            str(window["condition"]) ==
            str(rows[i // st.N_WINDOWS]["condition"]) and
            all(int(window[name]) == int(rows[i // st.N_WINDOWS][name])
                for name in ("point_ordinal", "grid_index", "block_index")) and
            np.isclose(float(window["bias"]),
                       float(rows[i // st.N_WINDOWS]["bias"]),
                       atol=0, rtol=0) and
            float(window["t_start_unix"]) < float(window["t_end_unix"]) and
            np.isclose(float(window["t_mid_unix"]),
                       0.5 * (float(window["t_start_unix"]) +
                              float(window["t_end_unix"])), atol=1e-9, rtol=0)
            for i, window in enumerate(windows)) and
        all(all(float(group[j]["t_end_unix"]) <=
                float(group[j + 1]["t_start_unix"])
                for j in range(st.N_WINDOWS - 1))
            for group in (windows[start:start + st.N_WINDOWS]
                          for start in range(0, len(windows), st.N_WINDOWS))) and
        _exact_raw_capture_pass(windows, st.N_BLOCKS, 1) and
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
                rows, (windows[start:start + st.N_WINDOWS]
                       for start in range(0, len(windows), st.N_WINDOWS)))))
    window_raw_gate = (tt.analyze_adc_raw_telemetry(**_raw_arrays(windows))
                       if windows else {"accepted": False})
    formal_exact_capture_pass = _exact_raw_capture_pass(
        rows, st.N_BLOCKS * st.N_WINDOWS, st.N_WINDOWS)
    max_abs_code = int(max(max(abs(int(row["rawadc_ch0_min"])),
                               abs(int(row["rawadc_ch0_max"])))
                           for row in rows)) if rows else 0
    formal_headroom_pass = bool(rows and
                                max_abs_code <= st.HEADROOM_LIMIT_CODE)

    dmm_bracket_pass = bool(rows and all(
        float(row["t_dmm_pre1_start_unix"]) <
        float(row["t_dmm_pre1_end_unix"]) <=
        float(row["t_dmm_pre2_start_unix"]) <
        float(row["t_dmm_pre2_end_unix"]) <=
        float(row["t_acq_start_unix"]) <
        float(row["t_acq_mid_unix"]) <
        float(row["t_acq_end_unix"]) <=
        float(row["t_dmm_post1_start_unix"]) <
        float(row["t_dmm_post1_end_unix"]) <=
        float(row["t_dmm_post2_start_unix"]) <
        float(row["t_dmm_post2_end_unix"]) and
        all(np.isfinite(float(row[name])) for name in (
            "dc_dmm_pre1", "dc_dmm_pre2", "dc_dmm_post1", "dc_dmm_post2"))
        for row in rows))

    statistics = None
    statistics_pass = False
    if rows and len(windows) == len(rows) * st.N_WINDOWS:
        try:
            statistics = st.analyze_static_statistics(
                point_ordinal=[row["point_ordinal"] for row in rows],
                block_index=[row["block_index"] for row in rows],
                condition=[row["condition"] for row in rows],
                t_acq_mid=[row["t_acq_mid_unix"] for row in rows],
                I1=[row["I1"] for row in rows],
                Q1=[row["Q1"] for row in rows],
                I2=[row["I2"] for row in rows],
                Q2=[row["Q2"] for row in rows],
                dc_dmm_pre1=[row["dc_dmm_pre1"] for row in rows],
                dc_dmm_pre2=[row["dc_dmm_pre2"] for row in rows],
                dc_dmm_post1=[row["dc_dmm_post1"] for row in rows],
                dc_dmm_post2=[row["dc_dmm_post2"] for row in rows],
                win_source_repeat=[w["source_repeat_index"] for w in windows],
                win_index=[w["window_index"] for w in windows],
                win_I1=[w["I1"] for w in windows],
                win_Q1=[w["Q1"] for w in windows],
                win_I2=[w["I2"] for w in windows],
                win_Q2=[w["Q2"] for w in windows])
            statistics_pass = True
        except Exception:
            statistics = None
            statistics_pass = False

    gates = dict(
        schedule_contract_pass=schedule_contract_pass,
        conditioning_contract_pass=conditioning_contract_pass,
        block_config_contract_pass=block_config_contract_pass,
        restart_contract_pass=restart_contract_pass,
        single_pilot_configuration_verified=verification_pass,
        transition_discard_contract_pass=discard_contract_pass,
        transition_discard_capture_pass=discard_capture_pass,
        formal_window_contract_pass=window_contract_pass,
        formal_window_raw_pass=bool(window_raw_gate.get("accepted", False)),
        formal_exact_capture_pass=formal_exact_capture_pass,
        formal_headroom_pass=formal_headroom_pass,
        dmm_bracket_pass=dmm_bracket_pass,
        read_failure_contract_pass=read_failure_contract_pass,
        statistics_finite_pass=statistics_pass)
    gates["required_pass_fields"] = tuple(sorted(
        name for name in gates if name.endswith("_pass") or
        name.endswith("_verified")))
    gates["accepted"] = bool(all(
        gates[name] for name in gates["required_pass_fields"]))
    return dict(
        protocol_version=st.PROTOCOL_VERSION,
        quality_gate=gates,
        repeats=len(rows), windows=len(windows), discards=len(discards),
        conditioning_rows=len(conditioning_rows),
        acq_restart_retry_total=acq_restart_retry_total,
        discard_read_retry_total=discard_read_retry_total,
        formal_read_retry_total=formal_read_retry_total,
        formal_max_abs_raw_code=max_abs_code,
        formal_max_abs_raw_V=float(max_abs_code * 1.2 / 8388608.0),
        formal_window_raw_gate=window_raw_gate,
        transition_discard_raw_gate=discard_raw_gate,
        statistics=statistics,
        independent_optical_truth=False, headline_promotion=False,
        pilot_only_calibration=True, v1_4_authorization_ready=False)


def _verify_gen_show(response):
    return dict(
        pilot_count_pass="pilots: 1" in response,
        frequency_pass=f"f={mb.PILOT_HZ:.1f}Hz" in response,
        amplitude_pass=f"amp={st.PILOT_V:.4f}V" in response,
        acquisition_count_pass="freqs: 2" in response,
        acquisition_frequencies_pass=("f=1000.0Hz" in response and
                                      "f=2000.0Hz" in response))


def _acq_show_ok(response):
    return ("freqs: 2" in response and "f=1000.0Hz" in response and
            "f=2000.0Hz" in response)


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
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--sim-fail-after", type=int)
    parser.add_argument("--sim-fault", choices=(
        "none", "formal_rail", "formal_headroom", "formal_sample",
        "discard_missing", "dmm_order", "verify_fail", "schedule_break",
        "restart_missing", "acq_retry", "acq_retry_exhausted",
        "window_retry", "window_retry_exhausted", "discard_retry",
        "gen_phase", "all_phase", "dmm_step"),
        default="none")
    parser.add_argument("--i-understand-this-writes-real-hardware",
                        action="store_true")
    args = parser.parse_args()
    if not args.sim and not args.i_understand_this_writes_real_hardware:
        raise RuntimeError(
            "real diagnostic requires explicit hardware acknowledgement")
    if (args.sim_fail_after is not None or
            args.sim_fault != "none") and not args.sim:
        raise ValueError("simulation fault injection is valid only with --sim")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")

    schedule = st.build_schedule()
    records = st.schedule_records(schedule)
    bridges = st.expected_bridges()
    root = (os.path.join(ec.REPO, "build", "exp_sim", "static_repeats",
                         args.run_id)
            if args.sim else os.path.join(
                ec.DATA, "diagnostics", "static_repeats", args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    _write_json(os.path.join(root, "manifest.json"), dict(
        run_id=args.run_id, status="failed",
        failure="initialization incomplete",
        started_unix=started, ended_unix=None, conditioning_rows=0,
        acquired_repeats=0, expected_repeats=st.TOTAL_REPEATS,
        acquired_windows=0, expected_windows=st.TOTAL_REPEATS * st.N_WINDOWS,
        acquired_discards=0, expected_discards=st.TOTAL_REPEATS,
        board_final_status=None, quality_gate_accepted=None))
    _refresh_checksums(root)
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    source_paths = {
        "diagnose_mzm_static_repeats.py": os.path.abspath(__file__),
        "mzm_static_repeat_truth.py": os.path.abspath(st.__file__),
        "mzm_time_truth.py": os.path.abspath(tt.__file__),
        "measure_bench.py": os.path.abspath(mb.__file__),
        "exp_common.py": os.path.abspath(ec.__file__),
        "mzm_static_repeat_protocol.md": os.path.join(
            ec.REPO, "reviews", "mzm_static_repeat_protocol.md"),
        "validate_mzm_static_repeats.py": os.path.join(
            ec.REPO, "scripts", "validate_mzm_static_repeats.py"),
    }
    protocol = dict(
        protocol_version=st.PROTOCOL_VERSION, purpose="diagnostic_only",
        simulated=bool(args.sim), run_id=args.run_id,
        fixed_vpi_V=tt.VPI_V, coordinate_center_V=tt.CENTER_V,
        pilot_V=st.PILOT_V, pilot_Hz=mb.PILOT_HZ,
        point_grid=list(st.POINT_GRID), conditions=list(st.CONDITIONS),
        repeats_per_block=st.REPEATS_PER_BLOCK,
        discard_blocks=st.DISCARD_BLOCKS, formal_blocks=st.N_BLOCKS,
        formal_windows=st.N_WINDOWS, dmm_reads=st.DMM_READS,
        bias_settle_s=st.BIAS_SETTLE_S,
        discard_to_formal_max_s=st.DISCARD_TO_FORMAL_MAX_S,
        headroom_limit_V=st.HEADROOM_LIMIT_V,
        headroom_limit_code=st.HEADROOM_LIMIT_CODE,
        schedule_sha256=st.schedule_sha256(schedule), schedule=records,
        expected_bridge_rows=len(bridges),
        interpretation_thresholds=dict(
            restart_excess_min_rad=st.RESTART_EXCESS_MIN_RAD,
            restart_ratio_min=st.RESTART_RATIO_MIN,
            environment_h2_cstd_rad=st.ENVIRONMENT_H2_CSTD_RAD,
            points_required=st.POINTS_REQUIRED,
            dmm_bracket_norm_limit=tt.DC_NORMALIZED_RMSE_LIMIT),
        metadata=dict(
            device_id=args.device_id, firmware_rev=args.firmware_rev,
            ambient_c=float(args.ambient_c), operator=args.operator,
            session_id=args.session_id, instrument_ids=args.instrument_ids,
            notes=args.notes),
        repo_commit=repo_commit,
        source_sha256={name: _sha256(path)
                       for name, path in source_paths.items()},
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False)
    _write_json(os.path.join(root, "protocol.json"), protocol)

    paths = {
        "main": os.path.join(root, "static_repeats.csv"),
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
    block_config = {}
    read_failures = []
    _write_json(os.path.join(root, "acq_read_failures.json"), read_failures)
    status = "failed"
    failure = None
    board_final_status = None
    board_initial_status = None
    analysis = None
    caught = None
    sim_clock = 1_800_400_000.0
    sim_rng = np.random.default_rng(20260718)

    def checkpoint(complete=False):
        _write_json(os.path.join(root, "summary.json"), dict(
            complete=bool(complete),
            conditioning_rows=len(conditioning_rows),
            expected_conditioning_rows=len(bridges),
            acquired_repeats=len(rows), expected_repeats=st.TOTAL_REPEATS,
            acquired_windows=len(windows),
            expected_windows=st.TOTAL_REPEATS * st.N_WINDOWS,
            acquired_discards=len(discards),
            expected_discards=st.TOTAL_REPEATS, analysis=analysis))

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

                def now():
                    nonlocal sim_clock
                    if args.sim:
                        sim_clock += 0.001
                        return sim_clock
                    return time.time()

                def sim_advance(seconds):
                    nonlocal sim_clock
                    sim_clock += seconds

                def dmm_read(bias):
                    if args.sim:
                        t0 = now()
                        sim_advance(0.05)
                        board._last_dc_true = board.dc_true_at(bias)
                        value = mb.read_dc(dmm)
                        return t0, now(), float(value)
                    t0 = time.time()
                    value = mb.read_dc(dmm)
                    return t0, time.time(), float(value)

                sim_read_fail_plan = {}
                if args.sim and args.sim_fault == "window_retry":
                    sim_read_fail_plan[(2, "formal", 1)] = 1
                elif args.sim and args.sim_fault == "window_retry_exhausted":
                    sim_read_fail_plan[(2, "formal", 1)] = st.ACQ_READ_ATTEMPTS
                elif args.sim and args.sim_fault == "discard_retry":
                    sim_read_fail_plan[(3, "discard", None)] = 1

                def acq_read(n_blocks, sequence, phase, window_index, bias):
                    """Bounded retried acquisition; only no-data reads retry."""
                    key = (sequence, phase, window_index)
                    planned = sim_read_fail_plan.get(key, 0)
                    first_attempt_start = None
                    for attempt in range(st.ACQ_READ_ATTEMPTS):
                        t0 = now()
                        if args.sim:
                            if attempt < planned:
                                acq = {"dc": None, "tones": {}}
                            else:
                                acq = board.acq_run_mzm(
                                    bias, pilot_v=st.PILOT_V,
                                    n_blocks=n_blocks)
                            sim_advance(0.8 if phase == "discard" else 1.4)
                        else:
                            acq = mb.attach_rawadc_telemetry(
                                board.acq_run(n_blocks))
                        t1 = now()
                        if first_attempt_start is None:
                            first_attempt_start = t0
                        ok = bool(mb._valid_acq(acq) and
                                  acq.get("rawadc") is not None)
                        if ok:
                            return acq, t0, t1, attempt, first_attempt_start
                        read_failures.append(dict(
                            repeat_sequence_index=int(sequence),
                            phase=str(phase),
                            window_index=(None if window_index is None
                                          else int(window_index)),
                            attempt_index=int(attempt),
                            t_start_unix=float(t0), t_end_unix=float(t1)))
                        _write_json(os.path.join(
                            root, "acq_read_failures.json"), read_failures)
                    raise RuntimeError(
                        f"{phase} acquisition read failed after "
                        f"{st.ACQ_READ_ATTEMPTS} attempts at repeat "
                        f"{sequence}")

                sim_acq_fail_plan = {}
                if args.sim and args.sim_fault in ("acq_retry",
                                                   "acq_retry_exhausted"):
                    # sequence 24 is the first acq-restart repeat at point 0
                    sim_acq_fail_plan[24] = (
                        1 if args.sim_fault == "acq_retry"
                        else st.ACQ_VERIFY_ATTEMPTS)

                def restart_acq_subsystem(fail_key=None):
                    """One reset->add->add->show cycle per attempt, all logged."""
                    attempts = []
                    planned_failures = sim_acq_fail_plan.get(fail_key, 0)
                    for attempt in range(st.ACQ_VERIFY_ATTEMPTS):
                        t0 = now()
                        if args.sim:
                            sim_advance(0.6)
                            response = ("SIM freqs: 0"
                                        if attempt < planned_failures else
                                        "SIM freqs: 2 f=1000.0Hz f=2000.0Hz")
                            passed = attempt >= planned_failures
                        else:
                            board.acq_reset()
                            for frequency in mb.ACQ_FREQS:
                                board.acq_add(frequency)
                            time.sleep(0.4)
                            response = board.acq_show()
                            passed = _acq_show_ok(response)
                        attempts.append(dict(
                            attempt_index=attempt,
                            t_start_unix=float(t0), t_end_unix=float(now()),
                            response=str(response), passed=bool(passed)))
                        if passed:
                            break
                    return attempts

                def restart_gen_subsystem(bias):
                    if args.sim:
                        sim_advance(0.3)
                        return
                    board.gen_reset()
                    board.gen_bias(mb.CH, float(bias))
                    board.gen_pilot(mb.CH, mb.PILOT_HZ, st.PILOT_V)

                current_bias = 0.0
                bridge_cursor = 0
                for point, gi in enumerate(st.POINT_GRID):
                    point_bridges = [b for b in bridges
                                     if b["point_ordinal"] == point]
                    if not args.sim:
                        board.gen_reset()
                    for expected in point_bridges:
                        if args.sim:
                            t_start = now()
                            sim_advance(st.BIAS_SETTLE_S)
                            board._last_dc_true = board.dc_true_at(
                                expected["bias"])
                            dc_bridge = mb.read_dc(dmm)
                            response = "SIM dac"
                            t_end = now()
                        else:
                            t_start = time.time()
                            response = board.dac(expected["bias"])
                            time.sleep(st.BIAS_SETTLE_S)
                            dc_bridge = mb.read_dc(dmm)
                            t_end = time.time()
                        bridge_row = dict(
                            **expected, t_start_unix=t_start,
                            t_end_unix=t_end,
                            t_mid_unix=0.5 * (t_start + t_end),
                            dc_dmm=float(dc_bridge),
                            dac_response=str(response))
                        with open(paths["conditioning"], "a", newline="",
                                  encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [bridge_row[name]
                                 for name in CONDITIONING_HEADER])
                        conditioning_rows.append(bridge_row)
                        current_bias = expected["bias"]
                        bridge_cursor += 1
                    target_bias = float(current_bias)

                    for c_ord, condition in enumerate(
                            st.point_condition_order(point)):
                        block = point * st.BLOCKS_PER_POINT + c_ord
                        config_start = now()
                        acq_attempts = restart_acq_subsystem()
                        acq_ok = bool(acq_attempts[-1]["passed"])
                        restart_gen_subsystem(target_bias)
                        config_end = now()
                        block_config[str(block)] = dict(
                            block_index=block, point_ordinal=point,
                            condition=condition,
                            t_start_unix=float(config_start),
                            t_end_unix=float(config_end),
                            acq_show_pass=acq_ok,
                            acq_show_attempts=acq_attempts,
                            gen_configured=True)
                        _write_json(os.path.join(root, "block_config.json"),
                                    block_config)
                        if not acq_ok:
                            raise RuntimeError(
                                "block acquisition configuration failed")

                        for repeat in range(st.REPEATS_PER_BLOCK):
                            sequence = (block * st.REPEATS_PER_BLOCK + repeat)
                            item = records[sequence]
                            restart_gen = bool(item["restart_gen"])
                            restart_acq = bool(item["restart_acq"])
                            if (args.sim and
                                    args.sim_fault == "restart_missing" and
                                    sequence == 12):
                                restart_gen = False
                            restart_start = now()
                            restart_acq_attempts = None
                            if restart_acq:
                                restart_acq_attempts = restart_acq_subsystem(
                                    fail_key=sequence)
                                if not restart_acq_attempts[-1]["passed"]:
                                    raise RuntimeError(
                                        "acq restart verification failed "
                                        f"after {len(restart_acq_attempts)} "
                                        "attempts: " + repr(
                                            restart_acq_attempts[-1][
                                                "response"]))
                            if restart_gen:
                                restart_gen_subsystem(item["bias_V"])
                            restart_end = (now() if (restart_gen or
                                                     restart_acq)
                                           else restart_start)

                            if args.sim:
                                checks = dict(
                                    pilot_count_pass=True,
                                    frequency_pass=True,
                                    amplitude_pass=True,
                                    acquisition_count_pass=True,
                                    acquisition_frequencies_pass=True)
                                if (args.sim_fault == "verify_fail" and
                                        sequence == 5):
                                    checks["amplitude_pass"] = False
                                response = "SIM gen show"
                            else:
                                response = board.gen_show()
                                checks = _verify_gen_show(response)
                            entry = dict(
                                verified=bool(all(checks.values())),
                                simulated=bool(args.sim),
                                repeat_sequence_index=sequence,
                                expected_pilot_count=1,
                                expected_acquisition_count=2,
                                expected_frequency_Hz=mb.PILOT_HZ,
                                expected_amplitude_V=st.PILOT_V,
                                restart_acq_show_pass=(
                                    None if not restart_acq else
                                    bool(restart_acq_attempts[-1]["passed"])),
                                restart_acq_attempts=restart_acq_attempts,
                                restart_acq_attempt_count=(
                                    0 if restart_acq_attempts is None
                                    else len(restart_acq_attempts)),
                                response=str(response), **checks)
                            pilot_verification[str(sequence)] = entry
                            _write_json(os.path.join(
                                root, "pilot_verification.json"),
                                pilot_verification)
                            if not entry["verified"]:
                                raise RuntimeError(
                                    "single-pilot verification failed")

                            (discard_acq, discard_start, discard_end,
                             discard_attempt, _) = acq_read(
                                st.DISCARD_BLOCKS, sequence, "discard",
                                None, item["bias_V"])
                            discard_retries = int(discard_attempt)
                            raw = discard_acq["rawadc"]
                            discard_row = dict(
                                transition_discard_index=len(discards),
                                source_repeat_index=sequence,
                                point_ordinal=item["point_ordinal"],
                                grid_index=item["grid_index"],
                                block_index=item["block_index"],
                                condition=item["condition"],
                                bias=item["bias_V"],
                                t_start_unix=discard_start,
                                t_end_unix=discard_end,
                                t_mid_unix=0.5 * (discard_start +
                                                  discard_end),
                                dc_board=float(discard_acq["dc"]),
                                I1=float(discard_acq["tones"][
                                    mb.PILOT_HZ]["I"]),
                                Q1=float(discard_acq["tones"][
                                    mb.PILOT_HZ]["Q"]),
                                I2=float(discard_acq["tones"][mb.H2_HZ]["I"]),
                                Q2=float(discard_acq["tones"][mb.H2_HZ]["Q"]),
                                **{f"rawadc_{name}": raw[name]
                                   for name in RAW_FIELDS})
                            if not (args.sim and
                                    args.sim_fault == "discard_missing" and
                                    sequence == 0):
                                with open(paths["discard"], "a", newline="",
                                          encoding="utf-8") as stream:
                                    csv.writer(stream).writerow(
                                        [discard_row[name]
                                         for name in DISCARD_HEADER])
                                discards.append(discard_row)

                            pre1 = dmm_read(item["bias_V"])
                            pre2 = dmm_read(item["bias_V"])

                            sim_phase_jitter = 0.0
                            if args.sim and args.sim_fault == "gen_phase" and \
                                    item["restart_gen"]:
                                sim_phase_jitter = float(
                                    0.12 * sim_rng.standard_normal())
                            if args.sim and args.sim_fault == "all_phase":
                                sim_phase_jitter = float(
                                    0.12 * sim_rng.standard_normal())

                            observation_windows = []
                            formal_retries = 0
                            acq_first_attempt_start = None
                            for window_index in range(st.N_WINDOWS):
                                (acq, window_start, window_end, attempt,
                                 first_start) = acq_read(
                                    st.N_BLOCKS, sequence, "formal",
                                    window_index, item["bias_V"])
                                formal_retries += int(attempt)
                                if acq_first_attempt_start is None:
                                    acq_first_attempt_start = float(
                                        first_start)
                                if sim_phase_jitter:
                                    tone = acq["tones"][mb.H2_HZ]
                                    z = complex(tone["I"], tone["Q"]) * \
                                        np.exp(1j * sim_phase_jitter)
                                    tone["I"] = float(z.real)
                                    tone["Q"] = float(z.imag)
                                if (args.sim and sequence == 0 and
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
                                raw = acq["rawadc"]
                                window_row = dict(
                                    window_sequence_index=len(windows),
                                    source_repeat_index=sequence,
                                    window_index=window_index,
                                    point_ordinal=item["point_ordinal"],
                                    grid_index=item["grid_index"],
                                    block_index=item["block_index"],
                                    condition=item["condition"],
                                    bias=item["bias_V"],
                                    t_start_unix=window_start,
                                    t_end_unix=window_end,
                                    t_mid_unix=0.5 * (window_start +
                                                      window_end),
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
                                        [window_row[name]
                                         for name in WINDOW_HEADER])
                                windows.append(window_row)
                                observation_windows.append(window_row)

                            post1 = dmm_read(item["bias_V"])
                            post2 = dmm_read(item["bias_V"])
                            if (args.sim and args.sim_fault == "dmm_step" and
                                    item["condition"] == "none"):
                                shift = float(
                                    0.05 * sim_rng.standard_normal())
                                post1 = (post1[0], post1[1],
                                         post1[2] + shift)
                                post2 = (post2[0], post2[1],
                                         post2[2] + shift)
                            if (args.sim and args.sim_fault == "dmm_order" and
                                    sequence == 0):
                                pre2 = (pre2[0],
                                        observation_windows[0][
                                            "t_start_unix"] + 0.1,
                                        pre2[2])

                            acq_mid = float(np.mean([
                                w["t_mid_unix"]
                                for w in observation_windows]))
                            raw_records = [{name: w[f"rawadc_{name}"]
                                            for name in RAW_FIELDS}
                                           for w in observation_windows]
                            merged_raw = mb.merge_rawadc_telemetry(raw_records)
                            row = dict(
                                repeat_sequence_index=sequence,
                                point_ordinal=item["point_ordinal"],
                                grid_index=item["grid_index"],
                                block_index=item["block_index"],
                                condition=("both" if (
                                    args.sim and
                                    args.sim_fault == "schedule_break" and
                                    sequence == 0) else item["condition"]),
                                condition_ordinal=item["condition_ordinal"],
                                repeat_index=item["repeat_index"],
                                bias=item["bias_V"],
                                approach_bias=item["approach_bias_V"],
                                restart_gen=int(restart_gen),
                                restart_acq=int(restart_acq),
                                t_restart_start_unix=restart_start,
                                t_restart_end_unix=restart_end,
                                t_discard_start_unix=discard_start,
                                t_discard_end_unix=discard_end,
                                t_acq_first_attempt_start_unix=
                                acq_first_attempt_start,
                                discard_read_retries=discard_retries,
                                formal_read_retries=formal_retries,
                                t_dmm_pre1_start_unix=pre1[0],
                                t_dmm_pre1_end_unix=pre1[1],
                                dc_dmm_pre1=pre1[2],
                                t_dmm_pre2_start_unix=pre2[0],
                                t_dmm_pre2_end_unix=pre2[1],
                                dc_dmm_pre2=pre2[2],
                                t_acq_start_unix=observation_windows[0][
                                    "t_start_unix"],
                                t_acq_end_unix=observation_windows[-1][
                                    "t_end_unix"],
                                t_acq_mid_unix=acq_mid,
                                t_dmm_post1_start_unix=post1[0],
                                t_dmm_post1_end_unix=post1[1],
                                dc_dmm_post1=post1[2],
                                t_dmm_post2_start_unix=post2[0],
                                t_dmm_post2_end_unix=post2[1],
                                dc_dmm_post2=post2[2],
                                dc_board=float(np.mean([
                                    w["dc_board"]
                                    for w in observation_windows])),
                                I1=float(np.mean([
                                    w["I1"] for w in observation_windows])),
                                Q1=float(np.mean([
                                    w["Q1"] for w in observation_windows])),
                                I2=float(np.mean([
                                    w["I2"] for w in observation_windows])),
                                Q2=float(np.mean([
                                    w["Q2"] for w in observation_windows])),
                                **{f"rawadc_{name}": merged_raw[name]
                                   for name in RAW_FIELDS})
                            with open(paths["main"], "a", newline="",
                                      encoding="utf-8") as stream:
                                csv.writer(stream).writerow(
                                    [row[name] for name in MAIN_HEADER])
                            rows.append(row)
                            checkpoint(False)
                            if (args.sim_fail_after is not None and
                                    len(rows) >= args.sim_fail_after):
                                raise RuntimeError(
                                    f"injected failure after {len(rows)} "
                                    "repeats")
                            if (len(rows) == 1 or len(rows) % 24 == 0 or
                                    len(rows) == st.TOTAL_REPEATS):
                                print(
                                    f"[static-repeats] {len(rows):3d}/"
                                    f"{st.TOTAL_REPEATS} grid="
                                    f"{item['grid_index']:02d} "
                                    f"cond={item['condition']:<4} "
                                    f"rep={item['repeat_index']:02d}",
                                    flush=True)

                main_fields = {name: np.asarray([row[name] for row in rows])
                               for name in MAIN_HEADER}
                window_fields = {name: np.asarray([w[name] for w in windows])
                                 for name in WINDOW_HEADER}
                discard_fields = {name: np.asarray([d[name]
                                                    for d in discards])
                                  for name in DISCARD_HEADER}
                for filename, fields in (
                        ("static_repeats.npz", main_fields),
                        ("formal_windows.npz", window_fields),
                        ("transition_discard.npz", discard_fields)):
                    tmp = os.path.join(root, filename + ".tmp.npz")
                    np.savez(tmp, **fields,
                             schedule_sha256=st.schedule_sha256(schedule))
                    os.replace(tmp, os.path.join(root, filename))
                analysis = _analyze(rows, windows, discards,
                                    conditioning_rows, pilot_verification,
                                    block_config, read_failures)
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
                        if (str(board_final_status.get(
                                "State", "")).upper() != "IDLE" or
                                not str(board_final_status.get(
                                    "Bias", "")).strip().startswith(
                                        "0.000") or
                                str(board_final_status.get(
                                    "Lock", "NO")).upper() != "NO" or
                                str(board_final_status.get(
                                    "Cal", "INVALID")).upper() != "INVALID"):
                            raise RuntimeError(
                                "unsafe final board status: "
                                f"{board_final_status}")
                    except Exception as cleanup_exc:
                        text = (f"cleanup failed: "
                                f"{type(cleanup_exc).__name__}: {cleanup_exc}")
                        status = "failed"
                        failure = (text if failure is None
                                   else f"{failure}; {text}")
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
            acquired_repeats=len(rows), expected_repeats=st.TOTAL_REPEATS,
            acquired_windows=len(windows),
            expected_windows=st.TOTAL_REPEATS * st.N_WINDOWS,
            acquired_discards=len(discards),
            expected_discards=st.TOTAL_REPEATS,
            board_final_status=board_final_status,
            board_initial_status=board_initial_status,
            quality_gate_accepted=(None if analysis is None else
                                   analysis["quality_gate"]["accepted"])))
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(dict(
        accepted=analysis["quality_gate"]["accepted"],
        interpretation=(None if analysis["statistics"] is None else
                        analysis["statistics"]["interpretation"])),
        indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
