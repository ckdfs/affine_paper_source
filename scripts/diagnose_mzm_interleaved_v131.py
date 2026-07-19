#!/usr/bin/env python3
"""Acquire one preregistered MZM interleaved-v1.3.1 donor/recipient segment."""
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
import mzm_interleaved_truth as v12
import mzm_interleaved_v131_contract as contract
import mzm_interleaved_v131_truth as v13
import mzm_time_truth as tt


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
    values = {}
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path) and name != "checksums.json":
            values[name] = _sha256(path)
    _write_json(os.path.join(root, "checksums.json"), values)
    return values


def _write_npz(path, rows, header, schedule_hash):
    fields = {name: np.asarray([row[name] for row in rows]) for name in header}
    tmp = path + ".tmp.npz"
    np.savez(tmp, **fields, schedule_sha256=schedule_hash)
    os.replace(tmp, path)


def _load_donor_reference(root):
    root = os.path.abspath(root)
    required = ("analysis.json", "checksums.json", "spur_correction.json",
                "spur_correction.npz")
    if any(not os.path.isfile(os.path.join(root, name)) for name in required):
        raise RuntimeError("recipient donor bundle is incomplete")
    checksums = json.load(open(os.path.join(root, "checksums.json"), encoding="utf-8"))
    for name, digest in checksums.items():
        if _sha256(os.path.join(root, name)) != digest:
            raise RuntimeError(f"donor checksum mismatch: {name}")
    analysis = json.load(open(os.path.join(root, "analysis.json"), encoding="utf-8"))
    if not analysis.get("quality_gate", {}).get("accepted", False):
        raise RuntimeError("recipient donor bundle was not accepted")
    with np.load(os.path.join(root, "spur_correction.npz"), allow_pickle=False) as data:
        table = {name: data[name] for name in data.files}
    for name in ("protocol_version", "schedule_sha256", "table_sha256"):
        if isinstance(table[name], np.ndarray) and table[name].shape == ():
            table[name] = str(table[name].item())
    v13.validate_spur_table(table)
    return dict(
        path=root, table_sha256=table["table_sha256"],
        checksums_sha256=_sha256(os.path.join(root, "checksums.json")),
        correction_npz_sha256=_sha256(os.path.join(root, "spur_correction.npz")),
        correction_json_sha256=_sha256(os.path.join(root, "spur_correction.json")),
        components=np.asarray(table["components"]).astype("U1").tolist())


def main():
    signal.signal(signal.SIGINT, _abort)
    signal.signal(signal.SIGTERM, _abort)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("donor", "recipient"), required=True)
    parser.add_argument("--segment-index", type=int, choices=range(3), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--donor-dir")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--firmware-rev", required=True)
    parser.add_argument("--ambient-c", type=float, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--instrument-ids", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--sim-fault", choices=(
        "none", "invalid_once", "formal_invalid_once", "invalid_exhausted", "formal_rail",
        "formal_headroom", "formal_sample", "discard_sample",
        "discard_missing", "discard_duplicate", "dmm_missing", "dmm_bracket",
        "dmm_mid_failure", "after_discard", "cleanup_failure",
        "profile_decorrelation", "profile_split", "sentinel_spur",
        "recipient_mismatch", "recipient_scaled", "recipient_replaced",
        "recipient_sentinel_spur"),
        default="none")
    parser.add_argument("--sim-fail-after", type=int)
    parser.add_argument("--i-understand-this-writes-real-hardware",
                        action="store_true")
    args = parser.parse_args()
    if not args.sim and not args.i_understand_this_writes_real_hardware:
        raise RuntimeError("real v1.3.1 segment requires explicit hardware acknowledgement")
    if args.stage == "recipient" and not args.donor_dir:
        raise RuntimeError("recipient segment requires --donor-dir")
    if args.stage == "donor" and args.donor_dir:
        raise RuntimeError("donor segment cannot load a donor table")
    if args.sim_fault != "none" and not args.sim:
        raise RuntimeError("fault injection is simulation-only")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("invalid run-id")

    donor_reference = (_load_donor_reference(args.donor_dir)
                       if args.stage == "recipient" else None)
    schedule = v13.build_schedule()
    start, end = v13.segment_bounds(args.segment_index)
    records = v13.schedule_records(schedule)[start:end]
    bridges = __import__("diagnose_mzm_interleaved_calibration")._expected_bridges(records)
    n_avg = v13.DONOR_N_AVG if args.stage == "donor" else v13.RECIPIENT_N_AVG
    family = ("interleaved_spur_calibration" if args.stage == "donor"
              else "interleaved_calibration_v131")
    root = (os.path.join(ec.REPO, "build", "exp_sim", family, args.run_id)
            if args.sim else os.path.join(ec.DATA, "diagnostics", family, args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    manifest_path = os.path.join(root, "manifest.json")
    _write_json(manifest_path, dict(
        run_id=args.run_id, status="failed", failure="initialization incomplete",
        stage=args.stage, segment_index=args.segment_index,
        started_unix=started, ended_unix=None, acquired_observations=0,
        expected_observations=len(records), acquired_windows=0,
        expected_windows=len(records) * n_avg, acquired_discards=0,
        expected_discards=len(records), acquired_dmm_reads=0,
        expected_dmm_reads=len(records) * 16, board_final_status=None,
        quality_gate_accepted=None))
    _refresh_checksums(root)
    protocol_version = (v13.DONOR_PROTOCOL_VERSION if args.stage == "donor"
                        else v13.PROTOCOL_VERSION)
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    source_paths = {
        "diagnose_mzm_interleaved_v131.py": os.path.abspath(__file__),
        "mzm_interleaved_v131_truth.py": os.path.abspath(v13.__file__),
        "mzm_interleaved_v131_contract.py": os.path.abspath(contract.__file__),
        "mzm_interleaved_truth.py": os.path.abspath(v12.__file__),
        "mzm_time_truth.py": os.path.abspath(tt.__file__),
        "measure_bench.py": os.path.abspath(mb.__file__),
        "exp_common.py": os.path.abspath(ec.__file__),
        "validate_mzm_interleaved_v131_segment.py": os.path.join(
            ec.REPO, "scripts", "validate_mzm_interleaved_v131_segment.py"),
        "analyze_mzm_interleaved_v131_segments.py": os.path.join(
            ec.REPO, "scripts", "analyze_mzm_interleaved_v131_segments.py"),
        "validate_mzm_interleaved_v131_bundle.py": os.path.join(
            ec.REPO, "scripts", "validate_mzm_interleaved_v131_bundle.py"),
        "protocol.md": os.path.join(
            ec.REPO, "reviews", "mzm_interleaved_calibration_protocol_v1.3.1.md")}
    protocol = dict(
        protocol_version=protocol_version, stage=args.stage,
        purpose="diagnostic_only", simulated=bool(args.sim), run_id=args.run_id,
        segmented=True, segment_index=args.segment_index,
        segment_start=start, segment_end=end, fixed_vpi_V=tt.VPI_V,
        coordinate_center_V=tt.CENTER_V, pilot_V=v13.PILOT_V,
        pilot_Hz=mb.PILOT_HZ, discard_blocks=v13.DISCARD_BLOCKS,
        formal_blocks=v13.N_BLOCKS, formal_windows=n_avg,
        dmm_reads_per_side=v13.DMM_READS_PER_SIDE,
        acq_read_attempts=v13.ACQ_READ_ATTEMPTS,
        bias_settle_s=v13.BIAS_SETTLE_S,
        discard_to_formal_max_s=v13.DISCARD_TO_FORMAL_MAX_S,
        headroom_limit_V=v13.HEADROOM_LIMIT_V,
        headroom_limit_code=v13.HEADROOM_LIMIT_CODE,
        schedule_sha256=v13.schedule_sha256(schedule),
        schedule=v13.schedule_records(schedule), segment_schedule=records,
        expected_bridge_rows=len(bridges), donor_reference=donor_reference,
        metadata=dict(device_id=args.device_id, firmware_rev=args.firmware_rev,
                      ambient_c=float(args.ambient_c), operator=args.operator,
                      session_id=args.session_id,
                      instrument_ids=args.instrument_ids, notes=args.notes),
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
        "dmm": os.path.join(root, "dmm_reads.csv")}
    for key, header in (("main", contract.MAIN_HEADER),
                        ("window", contract.WINDOW_HEADER),
                        ("discard", contract.DISCARD_HEADER),
                        ("conditioning", contract.CONDITIONING_HEADER),
                        ("dmm", contract.DMM_HEADER)):
        with open(paths[key], "w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(header)
    rows, windows, discards, conditioning, dmm_reads = [], [], [], [], []
    pilot_verification, read_failures = {}, []
    _write_json(os.path.join(root, "pilot_verification.json"), pilot_verification)
    _write_json(os.path.join(root, "acq_read_failures.json"), read_failures)
    analysis = None
    status, failure, caught = "failed", None, None
    board_initial_status = board_final_status = None
    sim_clock = 1_800_600_000.0 + 1200.0 * args.segment_index
    invalid_used = False

    def checkpoint(complete=False):
        _write_json(os.path.join(root, "summary.json"), dict(
            complete=bool(complete), stage=args.stage,
            segment_index=args.segment_index,
            acquired_observations=len(rows), expected_observations=len(records),
            acquired_windows=len(windows), expected_windows=len(records) * n_avg,
            acquired_discards=len(discards), expected_discards=len(records),
            acquired_dmm_reads=len(dmm_reads),
            expected_dmm_reads=len(records) * 16,
            conditioning_rows=len(conditioning),
            expected_conditioning_rows=len(bridges), analysis=analysis))

    try:
        with ExitStack() as stack:
            if args.sim:
                board = mb.SimBoard(seed=20260717 + args.segment_index)
                board.VPI, board.V0 = tt.VPI_V, tt.CENTER_V
                board.DC_A, board.DC_B = 0.60, 0.40
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
                    response = board.acq_show()
                    if not ("freqs: 2" in response and "f=1000.0Hz" in response and
                            "f=2000.0Hz" in response):
                        raise RuntimeError("acquisition frequency verification failed")

                def now():
                    nonlocal sim_clock
                    if args.sim:
                        sim_clock += 0.001
                        return sim_clock
                    return time.time()

                def advance(seconds):
                    nonlocal sim_clock
                    if args.sim:
                        sim_clock += seconds
                    else:
                        time.sleep(seconds)

                def dmm_read(observation, side, read_index, bias):
                    t0 = now()
                    if args.sim:
                        advance(0.05)
                        board._last_dc_true = board.dc_true_at(bias)
                    value = float(mb.read_dc(dmm))
                    if (args.sim and args.sim_fault == "dmm_bracket" and
                            observation == start and side == "post"):
                        value += 0.08
                    t1 = now()
                    row = dict(
                        dmm_sequence_index=len(dmm_reads),
                        source_sequence_index=observation, side=side,
                        read_index=read_index, t_start_unix=t0, t_end_unix=t1,
                        t_mid_unix=0.5 * (t0 + t1), dc_dmm=value)
                    if not (args.sim and args.sim_fault == "dmm_missing" and
                            observation == start and side == "post" and read_index == 7):
                        with open(paths["dmm"], "a", newline="", encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [row[name] for name in contract.DMM_HEADER])
                        dmm_reads.append(row)
                    if (args.sim and args.sim_fault == "dmm_mid_failure" and
                            observation == start and side == "pre" and read_index == 3):
                        raise RuntimeError("injected failure during DMM reads")
                    return row

                def acquire(blocks, observation, phase, window_index, bias):
                    nonlocal invalid_used
                    first_start = None
                    for attempt in range(v13.ACQ_READ_ATTEMPTS):
                        t0 = now()
                        if first_start is None:
                            first_start = t0
                        inject = False
                        if args.sim and args.sim_fault == "invalid_once" and not invalid_used:
                            inject = True
                            invalid_used = True
                        if (args.sim and args.sim_fault == "formal_invalid_once" and
                                phase == "formal" and not invalid_used):
                            inject = True
                            invalid_used = True
                        if args.sim and args.sim_fault == "invalid_exhausted" and \
                                observation == start and phase == "discard":
                            inject = True
                        if inject:
                            acq = {"dc": None, "tones": {}}
                        elif args.sim:
                            acq = board.acq_run_mzm(
                                bias, pilot_v=v13.PILOT_V, n_blocks=blocks)
                        else:
                            acq = mb.attach_rawadc_telemetry(board.acq_run(blocks))
                        advance(0.8 if phase == "discard" else 1.3)
                        t1 = now()
                        if mb._valid_acq(acq) and acq.get("rawadc") is not None:
                            return acq, t0, t1, attempt + 1, first_start
                        read_failures.append(dict(
                            source_sequence_index=observation, phase=phase,
                            window_index=window_index, attempt_index=attempt,
                            t_start_unix=t0, t_end_unix=t1,
                            reason="no usable tones/DC/RAWADC"))
                        _write_json(os.path.join(root, "acq_read_failures.json"),
                                    read_failures)
                    raise RuntimeError(f"{phase} acquisition exhausted retries")

                for item in records:
                    observation = int(item["sequence_index"])
                    if not args.sim:
                        board.gen_reset()
                    bridge_rows = [value for value in bridges
                                   if value["observation_sequence_index"] == observation]
                    t_approach_set = None
                    for expected in bridge_rows:
                        t0 = now()
                        if args.sim:
                            advance(v13.BIAS_SETTLE_S)
                            board._last_dc_true = board.dc_true_at(expected["bias"])
                            response = "SIM dac"
                        else:
                            response = board.dac(expected["bias"])
                            advance(v13.BIAS_SETTLE_S)
                        dc_bridge = float(mb.read_dc(dmm))
                        t1 = now()
                        bridge = dict(**expected, t_start_unix=t0, t_end_unix=t1,
                                      t_mid_unix=0.5 * (t0 + t1),
                                      dc_dmm=dc_bridge, dac_response=str(response))
                        with open(paths["conditioning"], "a", newline="",
                                  encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [bridge[name] for name in contract.CONDITIONING_HEADER])
                        conditioning.append(bridge)
                        t_approach_set = t0
                    t_target_set = now()
                    if args.sim:
                        advance(v13.BIAS_SETTLE_S)
                    else:
                        board.dac(item["bias_V"])
                        advance(v13.BIAS_SETTLE_S)
                    if args.sim:
                        response = (
                            f"SIM pilots: 1 f=1000.0Hz amp={v13.PILOT_V:.4f}V "
                            "freqs: 2 f=1000.0Hz f=2000.0Hz")
                    else:
                        board.gen_reset()
                        board.gen_bias(mb.CH, float(item["bias_V"]))
                        board.gen_pilot(mb.CH, mb.PILOT_HZ, v13.PILOT_V)
                        response = board.gen_show()
                    checks = dict(
                        pilot_count_pass="pilots: 1" in response,
                        frequency_pass="f=1000.0Hz" in response,
                        amplitude_pass=f"amp={v13.PILOT_V:.4f}V" in response,
                        acquisition_count_pass="freqs: 2" in response,
                        acquisition_frequencies_pass=("f=1000.0Hz" in response and
                                                      "f=2000.0Hz" in response))
                    verification = dict(
                        verified=bool(all(checks.values())), simulated=bool(args.sim),
                        source_sequence_index=observation, expected_pilot_count=1,
                        expected_acquisition_count=2,
                        expected_frequency_Hz=mb.PILOT_HZ,
                        expected_amplitude_V=v13.PILOT_V,
                        response=response, **checks)
                    pilot_verification[str(observation)] = verification
                    _write_json(os.path.join(root, "pilot_verification.json"),
                                pilot_verification)
                    if not verification["verified"]:
                        raise RuntimeError("single-pilot verification failed")

                    discard_acq, discard_start, discard_end, discard_attempts, \
                        discard_first = acquire(
                            v13.DISCARD_BLOCKS, observation, "discard", None,
                            item["bias_V"])
                    raw = discard_acq["rawadc"]
                    if (args.sim and args.sim_fault == "discard_sample" and
                            observation == start):
                        raw["used"] -= 1
                    discard = dict(
                        transition_discard_index=len(discards), role=item["role"],
                        direction=item["direction"], grid_index=item["grid_index"],
                        target_ordinal=item["target_ordinal"],
                        pair_position=item["pair_position"],
                        source_sequence_index=observation, bias=item["bias_V"],
                        approach_bias=item["approach_bias_V"],
                        t_target_set_unix=t_target_set,
                        t_start_unix=discard_start, t_end_unix=discard_end,
                        t_mid_unix=0.5 * (discard_start + discard_end),
                        dc_board=float(discard_acq["dc"]),
                        I1=float(discard_acq["tones"][mb.PILOT_HZ]["I"]),
                        Q1=float(discard_acq["tones"][mb.PILOT_HZ]["Q"]),
                        I2=float(discard_acq["tones"][mb.H2_HZ]["I"]),
                        Q2=float(discard_acq["tones"][mb.H2_HZ]["Q"]),
                        **{f"rawadc_{name}": raw[name] for name in contract.RAW_FIELDS},
                        read_attempt_count=discard_attempts,
                        t_first_attempt_start_unix=discard_first)
                    discard_copies = (0 if args.sim and
                                      args.sim_fault == "discard_missing" and
                                      observation == start else
                                      2 if args.sim and
                                      args.sim_fault == "discard_duplicate" and
                                      observation == start else 1)
                    for _ in range(discard_copies):
                        duplicate = dict(discard)
                        duplicate["transition_discard_index"] = len(discards)
                        with open(paths["discard"], "a", newline="",
                                  encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [duplicate[name] for name in contract.DISCARD_HEADER])
                        discards.append(duplicate)
                    if (args.sim and args.sim_fault == "after_discard" and
                            observation == start):
                        raise RuntimeError("injected failure after discard")
                    pre = [dmm_read(observation, "pre", index, item["bias_V"])
                           for index in range(v13.DMM_READS_PER_SIDE)]
                    observation_windows = []
                    formal_retries = 0
                    first_formal_attempt = None
                    for window_index in range(n_avg):
                        acq, t0, t1, attempts, first_attempt = acquire(
                            v13.N_BLOCKS, observation, "formal", window_index,
                            item["bias_V"])
                        formal_retries += attempts - 1
                        if first_formal_attempt is None:
                            first_formal_attempt = first_attempt
                        if args.sim:
                            gi = int(item["grid_index"])
                            profile_gi = gi
                            scale = 1.0
                            if (args.sim_fault == "profile_decorrelation" and
                                    window_index % 2 == 1):
                                profile_gi = 80 - gi
                            if (args.sim_fault == "profile_split" and
                                    window_index % 2 == 1):
                                scale = 0.4
                            if (args.sim_fault == "recipient_mismatch" and
                                    args.stage == "recipient"):
                                scale = -1.0
                            if (args.sim_fault == "recipient_scaled" and
                                    args.stage == "recipient"):
                                scale = 0.45
                            if (args.sim_fault == "recipient_replaced" and
                                    args.stage == "recipient"):
                                profile_gi = 80 - gi
                            spur = scale * 0.08 * np.sin(
                                2.0 * np.pi * profile_gi / 5.9 +
                                0.003 * profile_gi * profile_gi)
                            if (args.sim_fault == "sentinel_spur" and
                                    item["role"] == "sentinel" and
                                    window_index % 2 == 1):
                                spur += 0.20
                            if (args.sim_fault == "recipient_sentinel_spur" and
                                    args.stage == "recipient" and
                                    item["role"] == "sentinel"):
                                spur += 0.20
                            acq["tones"][mb.H2_HZ]["I"] += spur
                        if (args.sim and observation == start and window_index == 0):
                            if args.sim_fault == "formal_rail":
                                acq["rawadc"].update(
                                    ch0_max=8388607, ch0_rail_hi=1, ch0_guard_hi=1)
                            elif args.sim_fault == "formal_headroom":
                                acq["rawadc"].update(ch0_max=6710886)
                            elif args.sim_fault == "formal_sample":
                                acq["rawadc"]["used"] -= 1
                        raw = acq["rawadc"]
                        window = dict(
                            window_sequence_index=len(windows),
                            source_sequence_index=observation,
                            window_index=window_index, role=item["role"],
                            direction=item["direction"], grid_index=item["grid_index"],
                            target_ordinal=item["target_ordinal"],
                            pair_position=item["pair_position"], bias=item["bias_V"],
                            t_start_unix=t0, t_end_unix=t1,
                            t_mid_unix=0.5 * (t0 + t1), dc_board=float(acq["dc"]),
                            I1=float(acq["tones"][mb.PILOT_HZ]["I"]),
                            Q1=float(acq["tones"][mb.PILOT_HZ]["Q"]),
                            I2=float(acq["tones"][mb.H2_HZ]["I"]),
                            Q2=float(acq["tones"][mb.H2_HZ]["Q"]),
                            **{f"rawadc_{name}": raw[name] for name in contract.RAW_FIELDS},
                            read_attempt_count=attempts,
                            t_first_attempt_start_unix=first_attempt)
                        with open(paths["window"], "a", newline="", encoding="utf-8") as stream:
                            csv.writer(stream).writerow(
                                [window[name] for name in contract.WINDOW_HEADER])
                        windows.append(window)
                        observation_windows.append(window)
                    post = [dmm_read(observation, "post", index, item["bias_V"])
                            for index in range(v13.DMM_READS_PER_SIDE)]
                    pre_values = np.asarray([value["dc_dmm"] for value in pre])
                    post_values = np.asarray([value["dc_dmm"] for value in post])
                    pre_mid = float(np.mean([value["t_mid_unix"] for value in pre]))
                    post_mid = float(np.mean([value["t_mid_unix"] for value in post]))
                    acq_mid = float(np.mean([value["t_mid_unix"]
                                             for value in observation_windows]))
                    weight = float((acq_mid - pre_mid) / (post_mid - pre_mid))
                    merged_raw = mb.merge_rawadc_telemetry([{
                        name: value[f"rawadc_{name}"] for name in contract.RAW_FIELDS}
                        for value in observation_windows])
                    row = dict(
                        role=item["role"], direction=item["direction"],
                        grid_index=item["grid_index"],
                        target_ordinal=item["target_ordinal"],
                        pair_position=item["pair_position"],
                        sequence_index=observation, bias=item["bias_V"],
                        approach_bias=item["approach_bias_V"],
                        bias_settle_s=v13.BIAS_SETTLE_S,
                        t_approach_set_unix=t_approach_set,
                        t_target_set_unix=t_target_set,
                        transition_discard_index=len(discards) - 1,
                        transition_followed_without_reconfigure=True,
                        t_discard_start_unix=discard_start,
                        t_discard_end_unix=discard_end,
                        t_dmm_pre_start_unix=pre[0]["t_start_unix"],
                        t_dmm_pre_end_unix=pre[-1]["t_end_unix"],
                        t_dmm_pre_mid_unix=pre_mid,
                        dc_dmm_pre=float(np.mean(pre_values)),
                        t_acq_start_unix=observation_windows[0]["t_start_unix"],
                        t_acq_end_unix=observation_windows[-1]["t_end_unix"],
                        t_acq_mid_unix=acq_mid,
                        t_dmm_post_start_unix=post[0]["t_start_unix"],
                        t_dmm_post_end_unix=post[-1]["t_end_unix"],
                        t_dmm_post_mid_unix=post_mid,
                        dc_dmm_post=float(np.mean(post_values)),
                        dmm_interpolation_weight=weight,
                        dc_dmm_interp=float(np.mean(pre_values) + weight * (
                            np.mean(post_values) - np.mean(pre_values))),
                        dc_board=float(np.mean([value["dc_board"]
                                                for value in observation_windows])),
                        I1=float(np.mean([value["I1"] for value in observation_windows])),
                        Q1=float(np.mean([value["Q1"] for value in observation_windows])),
                        I2=float(np.mean([value["I2"] for value in observation_windows])),
                        Q2=float(np.mean([value["Q2"] for value in observation_windows])),
                        **{f"rawadc_{name}": merged_raw[name]
                           for name in contract.RAW_FIELDS},
                        dmm_pre_read_count=8, dmm_post_read_count=8,
                        discard_read_attempt_count=discard_attempts,
                        formal_read_retry_count=formal_retries,
                        t_acq_first_attempt_start_unix=first_formal_attempt)
                    with open(paths["main"], "a", newline="", encoding="utf-8") as stream:
                        csv.writer(stream).writerow(
                            [row[name] for name in contract.MAIN_HEADER])
                    rows.append(row)
                    checkpoint(False)
                    if args.sim_fail_after is not None and len(rows) >= args.sim_fail_after:
                        raise RuntimeError("injected observation failure")
                    if len(rows) == 1 or len(rows) % 10 == 0 or len(rows) == len(records):
                        print(f"[v13-{args.stage}] segment={args.segment_index} "
                              f"{len(rows)}/{len(records)}", flush=True)
                schedule_hash = v13.schedule_sha256(schedule)
                _write_npz(os.path.join(root, "interleaved_calibration.npz"),
                           rows, contract.MAIN_HEADER, schedule_hash)
                _write_npz(os.path.join(root, "formal_windows.npz"),
                           windows, contract.WINDOW_HEADER, schedule_hash)
                _write_npz(os.path.join(root, "transition_discard.npz"),
                           discards, contract.DISCARD_HEADER, schedule_hash)
                _write_npz(os.path.join(root, "dmm_reads.npz"),
                           dmm_reads, contract.DMM_HEADER, schedule_hash)
                analysis = contract.analyze_segment(
                    args.stage, args.segment_index, rows, windows, discards,
                    conditioning, dmm_reads, pilot_verification, read_failures)
                _write_json(os.path.join(root, "analysis.json"), analysis)
                status = "complete"
                checkpoint(True)
            except BaseException as exc:
                caught = exc
                failure = f"{type(exc).__name__}: {exc}"
            finally:
                if args.sim:
                    board_final_status = {"State": "SIM", "Bias": "SIM"}
                    if args.sim_fault == "cleanup_failure":
                        status = "failed"
                        raise RuntimeError("injected cleanup failure")
                else:
                    try:
                        board.gen_reset()
                        board.dac(0.0)
                        board_final_status = board.status()
                        if (str(board_final_status.get("State", "")).upper() != "IDLE" or
                                not str(board_final_status.get("Bias", "")).startswith("0.000") or
                                str(board_final_status.get("Lock", "NO")).upper() != "NO" or
                                str(board_final_status.get("Cal", "INVALID")).upper() != "INVALID"):
                            raise RuntimeError(f"unsafe final status: {board_final_status}")
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
        _write_json(manifest_path, dict(
            run_id=args.run_id, status=status, failure=failure,
            stage=args.stage, segment_index=args.segment_index,
            started_unix=started, ended_unix=time.time(),
            acquired_observations=len(rows), expected_observations=len(records),
            acquired_windows=len(windows), expected_windows=len(records) * n_avg,
            acquired_discards=len(discards), expected_discards=len(records),
            acquired_dmm_reads=len(dmm_reads), expected_dmm_reads=len(records) * 16,
            board_initial_status=board_initial_status,
            board_final_status=board_final_status,
            quality_gate_accepted=(None if analysis is None else
                                   analysis["quality_gate"]["accepted"])))
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(analysis["quality_gate"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
