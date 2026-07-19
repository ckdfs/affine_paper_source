#!/usr/bin/env python3
"""Acquire the preregistered full-cycle CH0 RAWADC pilot bracket."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import time
from contextlib import ExitStack

import numpy as np

import exp_common as ec
import measure_bench as mb
import mzm_time_truth as tt


PROTOCOL_VERSION = "mzm-ch0-dynamic-range-v1.3"
PILOTS_V = (0.06, 0.08, 0.10)
N_BLOCKS = 6
BIAS_SETTLE_S = 0.500
HEADROOM_LIMIT_V = 0.95
HEADROOM_LIMIT_CODE = 6640981
STARTUP_TO_FORMAL_MAX_S = 0.250
RAW_FIELDS = (
    "version", "scope", "expected", "used", "read_fail", "blocks",
    "complete", "timeout", "gain", "fs_uv", "guard", "crc", "ch0_min",
    "ch0_max", "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo",
    "ch0_guard_hi", "windows",
)
MAIN_HEADER = [
    "role", "grid_index", "sequence_index", "candidate_order_index",
    "bias", "pilot_V", "bias_prepositioned", "bias_settle_s",
    "startup_discard_required", "startup_discard_index",
    "startup_discard_followed_without_reconfigure",
    "t_bias_set_unix", "t_start_unix", "t_end_unix", "t_mid_unix",
    "dc_board", "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]
STARTUP_HEADER = [
    "startup_discard_index", "role", "grid_index",
    "source_sequence_index", "bias", "pilot_V", "t_bias_set_unix",
    "t_start_unix", "t_end_unix", "t_mid_unix", "dc_board",
    "I1", "Q1", "I2", "Q2",
] + [f"rawadc_{name}" for name in RAW_FIELDS]


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


def _schedule():
    lo = float(tt.CENTER_V - tt.VPI_V)
    hi = float(tt.CENTER_V + tt.VPI_V)
    bias = np.linspace(lo, hi, tt.POINTS_PER_LEG)
    grid_step = float(bias[1] - bias[0])
    conditioning = np.linspace(
        0.0, lo, int(np.ceil(abs(lo) / grid_step)) + 1)[1:]
    records = []
    sequence = 0
    for index, value in enumerate(conditioning):
        records.append(dict(
            role="conditioning", grid_index=-1, sequence_index=sequence,
            candidate_order_index=-1, bias_V=float(value),
            pilot_V=max(PILOTS_V)))
        sequence += 1
    for grid_index, value in enumerate(bias):
        order = PILOTS_V[grid_index % len(PILOTS_V):] + PILOTS_V[:grid_index % len(PILOTS_V)]
        for order_index, pilot_v in enumerate(order):
            records.append(dict(
                role="formal", grid_index=int(grid_index),
                sequence_index=sequence, candidate_order_index=int(order_index),
                bias_V=float(value), pilot_V=float(pilot_v)))
            sequence += 1
    return records


def _schedule_sha256(records):
    payload = json.dumps(
        records, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _raw_arrays(rows):
    return {name: np.asarray([row[f"rawadc_{name}"] for row in rows])
            for name in RAW_FIELDS}


def _exact_raw_capture_pass(rows):
    return bool(rows and all(
        int(row["rawadc_version"]) == 1 and
        str(row["rawadc_scope"]) == "acq" and
        int(row["rawadc_expected"]) == N_BLOCKS * 1280 and
        int(row["rawadc_used"]) == N_BLOCKS * 1280 and
        int(row["rawadc_read_fail"]) == 0 and
        int(row["rawadc_blocks"]) == N_BLOCKS and
        bool(row["rawadc_complete"]) and
        not bool(row["rawadc_timeout"]) and
        int(row["rawadc_gain"]) == 1 and
        int(row["rawadc_fs_uv"]) == 1200000 and
        int(row["rawadc_guard"]) == 8381618 and
        int(row["rawadc_windows"]) == 1 and
        -8388608 <= int(row["rawadc_ch0_min"]) <=
        int(row["rawadc_ch0_max"]) <= 8388607 and
        np.all(np.isfinite([float(row[name]) for name in (
            "t_bias_set_unix", "t_start_unix", "t_end_unix", "t_mid_unix",
            "dc_board", "I1", "Q1", "I2", "Q2")])) and
        all(int(row[f"rawadc_{name}"]) >= 0 for name in (
            "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo", "ch0_guard_hi"))
        for row in rows))


def _configure_single_pilot(board, bias, pilot_v):
    """Replace, rather than append, the prepared generator pilot."""
    board.gen_reset()
    board.gen_bias(mb.CH, float(bias))
    board.gen_pilot(mb.CH, mb.PILOT_HZ, float(pilot_v))


def _preposition_bias(board, bias, sleep_fn=time.sleep):
    board.gen_reset()
    t_bias_set_unix = time.time()
    board.dac(float(bias))
    sleep_fn(BIAS_SETTLE_S)
    return t_bias_set_unix


def _acquire_real_candidate(board, startup_discard_required,
                            startup_callback=None):
    """Acquire a preserved startup window, then the scored window unchanged."""
    startup = None
    startup_timing = None
    startup_callback_result = None
    if startup_discard_required:
        t_start = time.time()
        startup = mb.attach_rawadc_telemetry(board.acq_run(N_BLOCKS))
        startup_timing = (t_start, time.time())
        if startup_callback is not None:
            startup_callback_result = startup_callback(startup, startup_timing)
    t_start = time.time()
    formal = mb.attach_rawadc_telemetry(board.acq_run(N_BLOCKS))
    return (startup, startup_timing, startup_callback_result,
            formal, (t_start, time.time()))


def _single_pilot_regression_selftest():
    class FakeBoard:
        def __init__(self):
            self.calls = []

        def gen_reset(self):
            self.calls.append(("reset",))

        def gen_bias(self, channel, bias):
            self.calls.append(("bias", channel, bias))

        def gen_pilot(self, channel, frequency, amplitude):
            self.calls.append(("pilot", channel, frequency, amplitude))

        def dac(self, bias):
            self.calls.append(("dac", bias))

        def acq_run(self, blocks):
            self.calls.append(("acq", blocks))
            return {"rawadc": {}}

    board = FakeBoard()
    _configure_single_pilot(board, -1.0, 0.06)
    _configure_single_pilot(board, -1.0, 0.08)
    assert [call[0] for call in board.calls] == [
        "reset", "bias", "pilot", "reset", "bias", "pilot"]
    assert sum(call[0] == "pilot" for call in board.calls[:3]) == 1
    assert sum(call[0] == "pilot" for call in board.calls[3:]) == 1
    board.calls.clear()
    slept = []
    _preposition_bias(board, -2.0, slept.append)
    assert [call[0] for call in board.calls] == ["reset", "dac"]
    assert slept == [BIAS_SETTLE_S]
    board.calls.clear()
    _preposition_bias(board, -2.0, lambda _seconds: None)
    _configure_single_pilot(board, -2.0, 0.10)
    _acquire_real_candidate(board, True)
    assert [call[0] for call in board.calls] == [
        "reset", "dac", "reset", "bias", "pilot", "acq", "acq"]
    assert board.calls[-2:] == [("acq", N_BLOCKS), ("acq", N_BLOCKS)]
    board.calls.clear()
    _configure_single_pilot(board, -2.0, 0.08)
    _acquire_real_candidate(board, False)
    assert [call[0] for call in board.calls] == [
        "reset", "bias", "pilot", "acq"]
    return True


def _analyze(rows, pilot_verification, startup_discards, startup_file_sha256):
    expected_verification = {f"{pilot:.2f}" for pilot in PILOTS_V}
    configuration_verified = bool(
        set(pilot_verification) == expected_verification and
        all(
            value.get("verified", False) and
            value.get("pilot_count_pass", False) and
            value.get("frequency_pass", False) and
            value.get("amplitude_pass", False) and
            int(value.get("expected_pilot_count", 0)) == 1 and
            np.isclose(float(value.get("expected_frequency_Hz", np.nan)),
                       mb.PILOT_HZ, atol=0, rtol=0) and
            np.isclose(float(value.get("expected_amplitude_V", np.nan)),
                       float(key), atol=0, rtol=0)
            for key, value in pilot_verification.items()))
    schedule = _schedule()
    schedule_contract_pass = bool(
        len(rows) == len(schedule) and all(
            str(row["role"]) == item["role"] and
            int(row["grid_index"]) == item["grid_index"] and
            int(row["sequence_index"]) == item["sequence_index"] and
            int(row["candidate_order_index"]) == item["candidate_order_index"] and
            np.isclose(float(row["bias"]), item["bias_V"], atol=0, rtol=0) and
            np.isclose(float(row["pilot_V"]), item["pilot_V"], atol=0, rtol=0) and
            float(row["t_start_unix"]) < float(row["t_end_unix"]) and
            np.isclose(float(row["t_mid_unix"]),
                       0.5 * (float(row["t_start_unix"]) +
                              float(row["t_end_unix"])),
                       atol=1e-9, rtol=0)
            for row, item in zip(rows, schedule)))
    expected_prepositioned = [
        row["role"] == "conditioning" or
        (row["role"] == "formal" and int(row["candidate_order_index"]) == 0)
        for row in rows]
    preposition_contract_pass = bool(
        len(rows) == len(_schedule()) and
        all(bool(row["bias_prepositioned"]) == expected
            for row, expected in zip(rows, expected_prepositioned)) and
        all(np.isclose(float(row["bias_settle_s"]), BIAS_SETTLE_S,
                       atol=0, rtol=0) for row in rows) and
        all(np.isfinite(float(row["t_bias_set_unix"])) and
            float(row["t_start_unix"]) - float(row["t_bias_set_unix"]) >=
            BIAS_SETTLE_S - 1e-3 for row in rows))
    expected_groups = [
        (index, row) for index, row in enumerate(rows)
        if row["role"] == "conditioning" or
        (row["role"] == "formal" and int(row["candidate_order_index"]) == 0)]
    startup_discard_contract_pass = bool(
        len(rows) == len(_schedule()) and
        len(startup_discards) == len(expected_groups) and
        all(
            int(discard["startup_discard_index"]) == discard_index and
            int(discard["source_sequence_index"]) == int(row["sequence_index"]) and
            str(discard["role"]) == str(row["role"]) and
            int(discard["grid_index"]) == int(row["grid_index"]) and
            np.isclose(float(discard["bias"]), float(row["bias"]), atol=0, rtol=0) and
            np.isclose(float(discard["pilot_V"]), float(row["pilot_V"]), atol=0, rtol=0) and
            np.isclose(float(discard["t_bias_set_unix"]),
                       float(row["t_bias_set_unix"]), atol=0, rtol=0) and
            int(row["startup_discard_index"]) == discard_index and
            bool(row["startup_discard_required"]) and
            bool(row["startup_discard_followed_without_reconfigure"]) and
            np.isfinite(float(discard["t_start_unix"])) and
            np.isfinite(float(discard["t_end_unix"])) and
            np.isclose(float(discard["t_mid_unix"]),
                       0.5 * (float(discard["t_start_unix"]) +
                              float(discard["t_end_unix"])),
                       atol=1e-9, rtol=0) and
            float(discard["t_start_unix"]) >=
            float(row["t_bias_set_unix"]) + BIAS_SETTLE_S - 1e-3 and
            float(discard["t_start_unix"]) < float(discard["t_end_unix"]) <=
            float(row["t_start_unix"]) and
            float(row["t_start_unix"]) - float(discard["t_end_unix"]) <=
            STARTUP_TO_FORMAL_MAX_S
            for discard_index, (discard, (_, row)) in enumerate(
                zip(startup_discards, expected_groups))) and
        all(
            (bool(row["startup_discard_required"]) and
             int(row["startup_discard_index"]) >= 0) ==
            (row["role"] == "conditioning" or
             (row["role"] == "formal" and
              int(row["candidate_order_index"]) == 0)) and
            (bool(row["startup_discard_followed_without_reconfigure"]) ==
             bool(row["startup_discard_required"]))
            for row in rows))
    startup_discard_raw_gate = (
        tt.analyze_adc_raw_telemetry(**_raw_arrays(startup_discards))
        if startup_discards else {"accepted": False})
    startup_discard_capture_pass = bool(
        startup_discards and
        startup_discard_raw_gate.get("contract_pass", False) and
        startup_discard_raw_gate.get("acquisition_complete_pass", False) and
        _exact_raw_capture_pass(startup_discards))
    startup_discard_hash_contract_pass = bool(
        set(startup_file_sha256) == {
            "startup_discard.csv", "startup_discard.npz"} and
        all(isinstance(value, str) and len(value) == 64 and
            all(ch in "0123456789abcdef" for ch in value)
            for value in startup_file_sha256.values()))
    result = dict(
        protocol_version=PROTOCOL_VERSION,
        headroom_limit_V=HEADROOM_LIMIT_V,
        headroom_limit_code=HEADROOM_LIMIT_CODE,
        candidates={}, selected_pilot_V=None, accepted=False,
        schedule_contract_pass=schedule_contract_pass,
        single_pilot_configuration_verified=configuration_verified,
        bias_preposition_contract_pass=preposition_contract_pass,
        startup_discard_expected=len(expected_groups),
        startup_discard_records=len(startup_discards),
        startup_discard_contract_pass=startup_discard_contract_pass,
        startup_discard_capture_pass=startup_discard_capture_pass,
        startup_discard_hash_contract_pass=startup_discard_hash_contract_pass,
        startup_discard_file_sha256=dict(startup_file_sha256),
        startup_discard_raw_gate=startup_discard_raw_gate,
        pilot_only_aba_ready=False, headline_promotion=False,
        v1_4_authorization_ready=False)
    formal = [row for row in rows if row["role"] == "formal"]
    conditioning = [row for row in rows if row["role"] == "conditioning"]
    accepted_pilots = []
    for pilot_v in PILOTS_V:
        candidate = [row for row in formal if np.isclose(row["pilot_V"], pilot_v)]
        grid = [int(row["grid_index"]) for row in candidate]
        schedule_pass = bool(
            len(candidate) == tt.POINTS_PER_LEG and
            grid == list(range(tt.POINTS_PER_LEG)))
        finite_pass = bool(candidate and np.all(np.isfinite([
            row[name] for row in candidate
            for name in ("bias", "pilot_V", "dc_board", "I1", "Q1", "I2", "Q2")
        ])))
        raw = tt.analyze_adc_raw_telemetry(**_raw_arrays(candidate)) if candidate else {
            "accepted": False}
        raw_exact_capture_pass = _exact_raw_capture_pass(candidate)
        max_abs_code = int(max(
            [max(abs(int(row["rawadc_ch0_min"])),
                 abs(int(row["rawadc_ch0_max"]))) for row in candidate],
            default=2**31 - 1))
        max_abs_V = float(max_abs_code * 1.2 / 8388608.0)
        headroom_pass = bool(max_abs_code <= HEADROOM_LIMIT_CODE)
        conditioning_gate = None
        conditioning_headroom_pass = True
        conditioning_exact_capture_pass = True
        conditioning_max_abs_V = None
        if np.isclose(pilot_v, max(PILOTS_V)):
            conditioning_gate = tt.analyze_adc_raw_telemetry(
                **_raw_arrays(conditioning)) if conditioning else {"accepted": False}
            conditioning_code = int(max(
                [max(abs(int(row["rawadc_ch0_min"])),
                     abs(int(row["rawadc_ch0_max"]))) for row in conditioning],
                default=2**31 - 1))
            conditioning_max_abs_V = float(conditioning_code * 1.2 / 8388608.0)
            conditioning_headroom_pass = bool(
                conditioning and conditioning_code <= HEADROOM_LIMIT_CODE)
            conditioning_exact_capture_pass = _exact_raw_capture_pass(conditioning)
        ellipse = None
        ellipse_pass = False
        try:
            I1 = np.asarray([row["I1"] for row in candidate], float)
            Q1 = np.asarray([row["Q1"] for row in candidate], float)
            I2 = np.asarray([row["I2"] for row in candidate], float)
            Q2 = np.asarray([row["Q2"] for row in candidate], float)
            bias = np.asarray([row["bias"] for row in candidate], float)
            comps = mb.choose_comps(I1, Q1, I2, Q2)
            X = I2 if comps[0] == "I" else Q2
            Y = I1 if comps[1] == "I" else Q1
            phase = ec.bias_to_phase(bias, tt.VPI_V, tt.CENTER_V)
            cal = ec.calibrate_phase_ref(X, Y, phase)
            sc = ec.self_check_mrad(X, Y, cal, phase)
            h1 = np.hypot(I1, Q1)
            h2 = np.hypot(I2, Q2)
            ellipse_pass = bool(np.all(np.isfinite(
                np.r_[cal["c0"], cal["A_hat"].ravel(), cal["kappa"]])) and
                np.linalg.det(cal["A_hat"]) != 0)
            ellipse = dict(
                components=list(comps), kappa=float(cal["kappa"]),
                c0=np.asarray(cal["c0"]).tolist(),
                A_hat=np.asarray(cal["A_hat"]).tolist(),
                static_coordinate_concurrence_mrad=sc,
                h1_magnitude_min=float(np.min(h1)),
                h1_magnitude_max=float(np.max(h1)),
                h2_magnitude_min=float(np.min(h2)),
                h2_magnitude_max=float(np.max(h2)))
        except Exception as exc:
            ellipse = {"failure": f"{type(exc).__name__}: {exc}"}
        accepted = bool(
            schedule_pass and finite_pass and raw.get("accepted", False) and
            raw_exact_capture_pass and
            headroom_pass and conditioning_headroom_pass and
            conditioning_exact_capture_pass and
            (conditioning_gate is None or conditioning_gate.get("accepted", False)) and
            ellipse_pass)
        if accepted:
            accepted_pilots.append(float(pilot_v))
        result["candidates"][f"{pilot_v:.2f}"] = dict(
            accepted=accepted, schedule_pass=schedule_pass,
            finite_pass=finite_pass, formal_points=len(candidate),
            raw_gate=raw, raw_exact_capture_pass=raw_exact_capture_pass,
            max_abs_raw_code=max_abs_code,
            max_abs_raw_V=max_abs_V, headroom_pass=headroom_pass,
            conditioning_raw_gate=conditioning_gate,
            conditioning_max_abs_raw_V=conditioning_max_abs_V,
            conditioning_headroom_pass=conditioning_headroom_pass,
            conditioning_exact_capture_pass=conditioning_exact_capture_pass,
            ellipse_finite_pass=ellipse_pass, ellipse=ellipse)
    if (accepted_pilots and schedule_contract_pass and configuration_verified and
            preposition_contract_pass and startup_discard_contract_pass and
            startup_discard_capture_pass and
            startup_discard_hash_contract_pass):
        result["selected_pilot_V"] = max(accepted_pilots)
        result["accepted"] = True
    return result


def _inject_sim_fault(item, acq, fault, formal_count, conditioning_count):
    raw = acq.get("rawadc")
    hit_formal = item["role"] == "formal" and formal_count == 0
    hit_conditioning = item["role"] == "conditioning" and conditioning_count == 0
    if fault == "missing" and hit_formal:
        acq.pop("rawadc", None)
    elif fault == "rail" and hit_formal:
        raw.update(ch0_max=8388607, ch0_rail_hi=1, ch0_guard_hi=1)
    elif fault == "guard" and hit_formal:
        raw.update(ch0_max=8381618, ch0_guard_hi=1)
    elif fault == "headroom" and hit_formal:
        raw.update(ch0_max=6710886)
    elif fault == "sample" and hit_formal:
        raw.update(used=raw["expected"] - 1, complete=False)
    elif fault == "conditioning" and hit_conditioning:
        raw.update(ch0_max=6710886)
    return acq


def _inject_startup_sim_fault(acq, fault, startup_count):
    if fault == "warmup_sample" and startup_count == 0:
        raw = acq["rawadc"]
        raw.update(used=raw["expected"] - 1, complete=False)
    elif fault == "warmup_rail" and startup_count == 0:
        raw = acq["rawadc"]
        raw.update(ch0_max=8388607, ch0_rail_hi=1, ch0_guard_hi=1)
    elif fault == "warmup_raw_missing" and startup_count == 0:
        acq.pop("rawadc", None)
    return acq


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
        "none", "rail", "guard", "headroom", "missing", "sample",
        "conditioning", "preposition", "settle", "warmup_missing",
        "warmup_duplicate", "warmup_sample", "warmup_reconfigure",
        "warmup_rail", "warmup_raw_missing", "warmup_gap",
        "after_warmup"),
        default="none")
    parser.add_argument("--i-understand-this-writes-real-hardware",
                        action="store_true")
    args = parser.parse_args()
    _single_pilot_regression_selftest()
    if not args.sim and not args.i_understand_this_writes_real_hardware:
        raise RuntimeError("real diagnostic requires explicit hardware acknowledgement")
    if (args.sim_fail_after is not None or args.sim_fault != "none") and not args.sim:
        raise ValueError("simulation fault injection is valid only with --sim")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")

    schedule = _schedule()
    expected_startup_discards = sum(
        item["role"] == "conditioning" or
        (item["role"] == "formal" and item["candidate_order_index"] == 0)
        for item in schedule)
    root = (os.path.join(ec.REPO, "build", "exp_sim", "ch0_dynamic_range", args.run_id)
            if args.sim else os.path.join(
                ec.DATA, "diagnostics", "ch0_dynamic_range", args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    _write_json(os.path.join(root, "manifest.json"), dict(
        run_id=args.run_id, status="failed", failure="initialization incomplete",
        started_unix=started, ended_unix=None, acquired_rows=0,
        expected_rows=len(schedule), acquired_startup_discards=0,
        expected_startup_discards=expected_startup_discards,
        board_final_status=None,
        quality_gate_accepted=None))
    _refresh_checksums(root)
    protocol = dict(
        protocol_version=PROTOCOL_VERSION, purpose="diagnostic_only",
        simulated=bool(args.sim), run_id=args.run_id,
        fixed_vpi_V=tt.VPI_V, coordinate_center_V=tt.CENTER_V,
        pilots_V=list(PILOTS_V), n_blocks=N_BLOCKS,
        startup_discard_blocks=N_BLOCKS,
        startup_discard_expected=expected_startup_discards,
        bias_settle_s=BIAS_SETTLE_S,
        headroom_limit_V=HEADROOM_LIMIT_V,
        headroom_limit_code=HEADROOM_LIMIT_CODE,
        schedule_sha256=_schedule_sha256(schedule), schedule=schedule,
        headline_promotion=False, v1_4_authorization_ready=False,
        metadata=dict(
            device_id=args.device_id, firmware_rev=args.firmware_rev,
            ambient_c=float(args.ambient_c), operator=args.operator,
            session_id=args.session_id, instrument_ids=args.instrument_ids,
            notes=args.notes),
        source_sha256={
            "diagnose_mzm_ch0_dynamic_range.py": _sha256(os.path.abspath(__file__)),
            "measure_bench.py": _sha256(os.path.abspath(mb.__file__)),
            "mzm_time_truth.py": _sha256(os.path.abspath(tt.__file__)),
            "exp_common.py": _sha256(os.path.abspath(ec.__file__)),
            "mzm_ch0_dynamic_range_protocol.md": _sha256(os.path.join(
                ec.REPO, "reviews", "mzm_ch0_dynamic_range_protocol.md"))})
    _write_json(os.path.join(root, "protocol.json"), protocol)
    _refresh_checksums(root)

    header = MAIN_HEADER
    csv_path = os.path.join(root, "ch0_dynamic_range.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(header)
    startup_header = STARTUP_HEADER
    startup_csv_path = os.path.join(root, "startup_discard.csv")
    with open(startup_csv_path, "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(startup_header)
    _refresh_checksums(root)
    rows = []
    startup_discards = []
    status = "failed"
    failure = None
    board_final_status = None
    analysis = None
    pilot_verification = {}
    caught = None
    formal_count = 0
    conditioning_count = 0
    last_bias = None
    last_bias_set_unix = None
    sim_clock = 1_800_100_000.0
    startup_attempts = 0

    def persist_startup(acq, timing, item):
        nonlocal startup_attempts
        attempt_index = startup_attempts
        startup_attempts += 1
        raw = acq.get("rawadc")
        if raw is None:
            raise RuntimeError("startup-discard CH0 RAWADC telemetry missing")
        discard_index = len(startup_discards)
        row = dict(
            startup_discard_index=discard_index,
            role=item["role"], grid_index=item["grid_index"],
            source_sequence_index=item["sequence_index"],
            bias=item["bias_V"], pilot_V=item["pilot_V"],
            t_bias_set_unix=last_bias_set_unix,
            t_start_unix=timing[0], t_end_unix=timing[1],
            t_mid_unix=0.5 * sum(timing), dc_board=float(acq["dc"]),
            I1=float(acq["tones"][mb.PILOT_HZ]["I"]),
            Q1=float(acq["tones"][mb.PILOT_HZ]["Q"]),
            I2=float(acq["tones"][mb.H2_HZ]["I"]),
            Q2=float(acq["tones"][mb.H2_HZ]["Q"]),
            **{f"rawadc_{name}": raw[name] for name in RAW_FIELDS})
        if (args.sim and args.sim_fault == "warmup_missing" and
                attempt_index == 0):
            return discard_index
        with open(startup_csv_path, "a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow([row[name] for name in STARTUP_HEADER])
        startup_discards.append(row)
        if (args.sim and args.sim_fault == "warmup_duplicate" and
                len(startup_discards) == 1):
            duplicate = dict(row)
            duplicate["startup_discard_index"] = 1
            with open(startup_csv_path, "a", newline="",
                      encoding="utf-8") as stream:
                csv.writer(stream).writerow(
                    [duplicate[name] for name in STARTUP_HEADER])
            startup_discards.append(duplicate)
        return discard_index

    try:
        with ExitStack() as stack:
            if args.sim:
                board = mb.SimBoard(seed=20260717)
                board.VPI = tt.VPI_V
                board.V0 = tt.CENTER_V
            else:
                board = stack.enter_context(mb.open_board())
            try:
                mb.assert_board_ready_for_evidence(board)
                mb.prepare_mzm_frontend(board, max(PILOTS_V))
                for item in schedule:
                    bias_prepositioned = bool(
                        item["role"] == "conditioning" or
                        (item["role"] == "formal" and
                         item["candidate_order_index"] == 0))
                    if bias_prepositioned:
                        if args.sim:
                            last_bias_set_unix = sim_clock
                            sim_clock += BIAS_SETTLE_S
                        else:
                            last_bias_set_unix = _preposition_bias(
                                board, item["bias_V"])
                        last_bias = item["bias_V"]
                    startup_discard_index = -1
                    startup_followed_without_reconfigure = False
                    if args.sim:
                        if bias_prepositioned:
                            startup_t_start = sim_clock
                            startup_acq = board.acq_run_mzm(
                                item["bias_V"], pilot_v=item["pilot_V"],
                                n_blocks=N_BLOCKS)
                            startup_acq = _inject_startup_sim_fault(
                                startup_acq, args.sim_fault,
                                len(startup_discards))
                            sim_clock += 1.0
                            startup_timing = (startup_t_start, sim_clock)
                            startup_discard_index = persist_startup(
                                startup_acq, startup_timing, item)
                            if (args.sim_fault == "after_warmup" and
                                    len(startup_discards) == 1):
                                raise RuntimeError(
                                    "injected failure after persisted startup discard")
                            startup_followed_without_reconfigure = not (
                                args.sim and
                                args.sim_fault == "warmup_reconfigure" and
                                formal_count == 0 and conditioning_count == 0)
                            sim_clock += (0.500 if args.sim_fault == "warmup_gap"
                                          else 0.001)
                        t_start = sim_clock
                        acq = board.acq_run_mzm(
                            item["bias_V"], pilot_v=item["pilot_V"],
                            n_blocks=N_BLOCKS)
                        sim_clock += 1.0
                        t_end = sim_clock
                        sim_clock += 0.1
                        acq = _inject_sim_fault(
                            item, acq, args.sim_fault, formal_count,
                            conditioning_count)
                        key = f"{item['pilot_V']:.2f}"
                        if key not in pilot_verification:
                            pilot_verification[key] = dict(
                                verified=True, simulated=True,
                                pilot_count_pass=True,
                                frequency_pass=True,
                                amplitude_pass=True,
                                expected_pilot_count=1,
                                expected_frequency_Hz=mb.PILOT_HZ,
                                expected_amplitude_V=item["pilot_V"],
                                response="SIM single pilot")
                            _write_json(os.path.join(
                                root, "pilot_verification.json"), pilot_verification)
                            _refresh_checksums(root)
                    else:
                        _configure_single_pilot(
                            board, item["bias_V"], item["pilot_V"])
                        key = f"{item['pilot_V']:.2f}"
                        if key not in pilot_verification:
                            response = board.gen_show()
                            count_ok = "pilots: 1" in response
                            frequency_ok = f"f={mb.PILOT_HZ:.1f}Hz" in response
                            amplitude_ok = f"amp={item['pilot_V']:.4f}V" in response
                            verified = bool(count_ok and frequency_ok and amplitude_ok)
                            pilot_verification[key] = dict(
                                verified=verified, simulated=False,
                                pilot_count_pass=count_ok,
                                frequency_pass=frequency_ok,
                                amplitude_pass=amplitude_ok,
                                expected_pilot_count=1,
                                expected_frequency_Hz=mb.PILOT_HZ,
                                expected_amplitude_V=item["pilot_V"],
                                response=response)
                            _write_json(os.path.join(
                                root, "pilot_verification.json"), pilot_verification)
                            _refresh_checksums(root)
                            if not verified:
                                raise RuntimeError(
                                    f"single-pilot generator verification failed: {response!r}")
                        callback = lambda startup, timing, current=item: (
                            persist_startup(startup, timing, current))
                        (_, _, callback_result, acq,
                         (t_start, t_end)) = _acquire_real_candidate(
                            board, bias_prepositioned, callback)
                        if bias_prepositioned:
                            startup_discard_index = callback_result
                            startup_followed_without_reconfigure = True
                    raw = acq.get("rawadc")
                    raw_missing = raw is None
                    if raw_missing:
                        raw = dict(
                            version=0, scope="missing", expected=0, used=0,
                            read_fail=1, blocks=0, complete=False, timeout=False,
                            gain=0, fs_uv=0, guard=0, crc=False, ch0_min=0,
                            ch0_max=0, ch0_rail_lo=0, ch0_rail_hi=0,
                            ch0_guard_lo=0, ch0_guard_hi=0, windows=0)
                    row = dict(
                        role=item["role"], grid_index=item["grid_index"],
                        sequence_index=item["sequence_index"],
                        candidate_order_index=item["candidate_order_index"],
                        bias=item["bias_V"], pilot_V=item["pilot_V"],
                        bias_prepositioned=(
                            False if args.sim and args.sim_fault == "preposition" and
                            item["role"] == "formal" and formal_count == 0
                            else bias_prepositioned),
                        bias_settle_s=(
                            0.4 if args.sim and args.sim_fault == "settle" and
                            item["role"] == "formal" and formal_count == 0
                            else BIAS_SETTLE_S),
                        startup_discard_required=bias_prepositioned,
                        startup_discard_index=startup_discard_index,
                        startup_discard_followed_without_reconfigure=(
                            startup_followed_without_reconfigure),
                        t_bias_set_unix=last_bias_set_unix,
                        t_start_unix=t_start, t_end_unix=t_end,
                        t_mid_unix=0.5 * (t_start + t_end),
                        dc_board=float(acq["dc"]),
                        I1=float(acq["tones"][mb.PILOT_HZ]["I"]),
                        Q1=float(acq["tones"][mb.PILOT_HZ]["Q"]),
                        I2=float(acq["tones"][mb.H2_HZ]["I"]),
                        Q2=float(acq["tones"][mb.H2_HZ]["Q"]),
                        **{f"rawadc_{name}": raw[name] for name in RAW_FIELDS})
                    with open(csv_path, "a", newline="", encoding="utf-8") as stream:
                        csv.writer(stream).writerow([row[name] for name in header])
                    rows.append(row)
                    _write_json(os.path.join(root, "summary.json"), dict(
                        complete=False, acquired_rows=len(rows),
                        expected_rows=len(schedule),
                        acquired_startup_discards=len(startup_discards),
                        expected_startup_discards=protocol["startup_discard_expected"],
                        analysis=None))
                    if item["role"] == "formal":
                        formal_count += 1
                    else:
                        conditioning_count += 1
                    if raw_missing:
                        raise RuntimeError("same-window CH0 RAWADC telemetry missing")
                    if (args.sim_fail_after is not None and
                            len(rows) >= args.sim_fail_after):
                        raise RuntimeError(
                            f"injected simulation failure after {len(rows)} rows")
                    if len(rows) == 1 or len(rows) % 30 == 0 or len(rows) == len(schedule):
                        print(
                            f"[ch0-range] {len(rows):3d}/{len(schedule)} "
                            f"{item['role']:<12} bias={item['bias_V']:+.3f} "
                            f"pilot={item['pilot_V']:.2f}", flush=True)

                fields = {name: np.asarray([row[name] for row in rows])
                          for name in header}
                tmp_npz = os.path.join(root, "ch0_dynamic_range.npz.tmp.npz")
                np.savez(tmp_npz, **fields,
                         schedule_sha256=_schedule_sha256(schedule))
                os.replace(tmp_npz, os.path.join(root, "ch0_dynamic_range.npz"))
                startup_fields = {
                    name: np.asarray([row[name] for row in startup_discards])
                    for name in startup_header}
                startup_tmp_npz = os.path.join(
                    root, "startup_discard.npz.tmp.npz")
                np.savez(startup_tmp_npz, **startup_fields,
                         schedule_sha256=_schedule_sha256(schedule))
                os.replace(startup_tmp_npz,
                           os.path.join(root, "startup_discard.npz"))
                startup_file_sha256 = {
                    name: _sha256(os.path.join(root, name)) for name in (
                        "startup_discard.csv", "startup_discard.npz")}
                analysis = _analyze(
                    rows, pilot_verification, startup_discards,
                    startup_file_sha256)
                _write_json(os.path.join(root, "analysis.json"), analysis)
                _write_json(os.path.join(root, "summary.json"), dict(
                    complete=True, acquired_rows=len(rows),
                    expected_rows=len(schedule),
                    acquired_startup_discards=len(startup_discards),
                    expected_startup_discards=protocol["startup_discard_expected"],
                    analysis=analysis))
                status = "complete"
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
                        lock = str(board_final_status.get("Lock", "NO")).upper()
                        if (str(board_final_status.get("State", "")).upper() != "IDLE" or
                                not str(board_final_status.get("Bias", "")).strip().startswith(
                                    "0.000") or lock not in {"NO", "OFF", "DISABLED"}):
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
        _write_json(os.path.join(root, "manifest.json"), dict(
            run_id=args.run_id, status=status, failure=failure,
            started_unix=started, ended_unix=time.time(),
            acquired_rows=len(rows), expected_rows=len(schedule),
            acquired_startup_discards=len(startup_discards),
            expected_startup_discards=protocol["startup_discard_expected"],
            board_final_status=board_final_status,
            quality_gate_accepted=(None if analysis is None else analysis["accepted"])))
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
