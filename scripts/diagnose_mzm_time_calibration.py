#!/usr/bin/env python3
"""Acquire the preregistered MZM ABA time-calibration diagnostic.

This is a real-bench, diagnostic-only entry point.  It never runs a controller,
never loads a preflight, and never writes the manuscript results contract.
Invocation requires an explicit real-hardware acknowledgement flag.
"""
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
import mzm_time_truth as tt


PROTOCOL_VERSION = "mzm-time-resolved-calibration-v1.3"
PILOT_V = 0.15
N_BLOCKS = 16
N_AVG = 4
CONDITIONING_BLOCKS = 6


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


def _analysis_summary(result):
    fit = result["fit"]
    calibration = result["calibration"]
    cal_json = None if calibration is None else dict(
        c0=np.asarray(calibration["c0"], float).tolist(),
        B=np.asarray(calibration["B"], float).tolist(),
        A_hat=np.asarray(calibration["A_hat"], float).tolist(),
        kappa=float(calibration["kappa"]),
    )
    return dict(
        protocol_version=PROTOCOL_VERSION,
        quality_gate=result["quality_gate"],
        dc_parameters=fit["parameters"],
        optimizer=fit["optimizer"],
        time_midpoint_unix=float(fit["time_midpoint_unix"]),
        time_scale_s=float(fit["time_scale_s"]),
        formal_points=int(np.count_nonzero(fit["formal_mask"])),
        sentinel_points=int(np.count_nonzero(fit["sentinel_mask"])),
        selfcheck=result["selfcheck"],
        observer_mapping_stability=result.get("observer_mapping_stability"),
        calibration=cal_json,
        adc_raw_telemetry=result.get("adc_raw_telemetry"),
        adc_raw_extrema_available=bool(
            result["quality_gate"].get("adc_raw_extrema_available", False)),
        v1_4_authorization_ready=False,
        independent_optical_truth=False,
        headline_promotion=False,
    )


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
    parser.add_argument(
        "--sim", action="store_true",
        help="hardware-free file-contract smoke test; writes only below build/exp_sim")
    parser.add_argument(
        "--sim-fail-after", type=int,
        help="simulation-only failure injection after this many ABA rows")
    parser.add_argument(
        "--sim-cleanup-fail", action="store_true",
        help="simulation-only cleanup failure injection")
    parser.add_argument(
        "--i-understand-this-writes-real-hardware", action="store_true",
        help="required acknowledgement; without it the program exits before "
             "creating a directory or opening instruments")
    args = parser.parse_args()
    if not args.sim and not args.i_understand_this_writes_real_hardware:
        raise RuntimeError("real diagnostic requires explicit hardware acknowledgement")
    if (args.sim_fail_after is not None or args.sim_cleanup_fail) and not args.sim:
        raise ValueError("simulation failure injection is valid only with --sim")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")

    schedule = tt.build_aba_schedule()
    schedule_records = tt.schedule_records(schedule)
    schedule_hash = tt.schedule_sha256(schedule)
    grid_step = float(2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1))
    lo = float(tt.CENTER_V - tt.VPI_V)
    conditioning = np.linspace(
        0.0, lo, int(np.ceil(abs(lo) / grid_step)) + 1)[1:]
    conditioning_records = [dict(
        role="conditioning", leg=-1, direction="conditioning",
        grid_index=-1, bias_V=float(value), sequence_index=int(index))
        for index, value in enumerate(conditioning)]

    root = (os.path.join(ec.REPO, "build", "exp_sim", "time_calibration", args.run_id)
            if args.sim else
            os.path.join(ec.DATA, "diagnostics", "time_calibration", args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    # Establish the audit envelope immediately.  Any initialization failure
    # before the acquisition try/finally leaves an explicit failed manifest
    # instead of an unaccounted directory.
    _write_json(os.path.join(root, "manifest.json"), dict(
        run_id=args.run_id, status="failed",
        failure="initialization did not complete", started_unix=started,
        ended_unix=None, conditioning_rows=0, acquired_schedule_rows=0,
        expected_schedule_rows=len(schedule_records),
        board_final_status=None, quality_gate_accepted=None))
    _refresh_checksums(root)
    status = "failed"
    failure = None
    board_final_status = None
    formal_rows = []
    all_rows = []
    conditioning_count = 0
    analysis_summary = None
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    source_hashes = mb._controller_source_hashes()
    source_hashes.update({
        "mzm_time_truth.py": _sha256(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mzm_time_truth.py")),
        "diagnose_mzm_time_calibration.py": _sha256(os.path.abspath(__file__)),
    })
    protocol = dict(
        protocol_version=PROTOCOL_VERSION,
        purpose="diagnostic_only",
        excluded_from_primary_analysis=True,
        simulated=bool(args.sim),
        run_id=args.run_id,
        fixed_vpi_V=tt.VPI_V,
        coordinate_center_V=tt.CENTER_V,
        lo_V=lo,
        hi_V=float(tt.CENTER_V + tt.VPI_V),
        points_per_leg=tt.POINTS_PER_LEG,
        leg_order=["up", "down", "up"],
        pilot_V=PILOT_V,
        pilot_Hz=mb.PILOT_HZ,
        n_blocks=N_BLOCKS,
        n_avg=N_AVG,
        conditioning_blocks=CONDITIONING_BLOCKS,
        grid_step_V=grid_step,
        conditioning_points=len(conditioning),
        schedule_sha256=schedule_hash,
        schedule=schedule_records,
        conditioning_schedule=conditioning_records,
        quality_gates=dict(
            design_abs_corr=tt.DESIGN_CORR_LIMIT,
            design_condition_number=tt.DESIGN_COND_LIMIT,
            dc_normalized_rmse=tt.DC_NORMALIZED_RMSE_LIMIT,
            direction_split_phase_rad=tt.PHASE_LIMIT_RAD,
            drift_30min_phase_rad=tt.PHASE_LIMIT_RAD,
            selfcheck_median_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
            selfcheck_p95_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
            bias_rail_V=0.995 * tt.BIAS_LIMIT_V,
            board_dc_monitor_rail_advisory_V=tt.BOARD_DC_RAIL_V,
            observer_mapping_median_mrad=tt.SELFCHECK_MEDIAN_LIMIT_MRAD,
            observer_mapping_p95_mrad=tt.SELFCHECK_P95_LIMIT_MRAD,
            adc_raw_version=tt.ADC_RAW_VERSION,
            adc_raw_gain=tt.ADC_RAW_GAIN,
            adc_raw_fs_uv=tt.ADC_RAW_FS_UV,
            adc_raw_guard_abs_code=tt.ADC_RAW_GUARD_ABS_CODE,
        ),
        independent_optical_truth=False,
        headline_promotion=False,
        metadata=dict(
            device_id=args.device_id, firmware_rev=args.firmware_rev,
            ambient_c=float(args.ambient_c), operator=args.operator,
            session_id=args.session_id, instrument_ids=args.instrument_ids,
            notes=args.notes,
        ),
        repo_commit=repo_commit,
        source_sha256=source_hashes,
    )
    _write_json(os.path.join(root, "protocol.json"), protocol)
    _refresh_checksums(root)

    csv_path = os.path.join(root, "time_calibration.csv")
    header = [
        "role", "leg", "direction", "grid_index", "sequence_index",
        "schedule_sequence_index", "bias",
        "t_start_unix", "t_end_unix", "t_mid_unix", "dc_dmm", "dc_board",
        "I1", "Q1", "I2", "Q2",
        "rawadc_version", "rawadc_scope", "rawadc_expected", "rawadc_used",
        "rawadc_read_fail", "rawadc_blocks", "rawadc_complete",
        "rawadc_timeout", "rawadc_gain", "rawadc_fs_uv", "rawadc_guard",
        "rawadc_crc", "rawadc_ch0_min", "rawadc_ch0_max",
        "rawadc_ch0_rail_lo", "rawadc_ch0_rail_hi",
        "rawadc_ch0_guard_lo", "rawadc_ch0_guard_hi", "rawadc_windows",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(header)
    _refresh_checksums(root)

    def append_row(role, leg, direction, grid_index, sequence_index,
                   schedule_sequence_index,
                   bias, started_point, ended_point, acq, dc_dmm):
        tone1 = acq["tones"][mb.PILOT_HZ]
        tone2 = acq["tones"][mb.H2_HZ]
        rawadc = acq.get("rawadc")
        raw_missing = rawadc is None
        if raw_missing:
            rawadc = dict(
                version=0, scope="missing", expected=0, used=0, read_fail=1,
                blocks=0, complete=False, timeout=False, gain=0, fs_uv=0,
                guard=0, crc=False, ch0_min=0, ch0_max=0, ch0_rail_lo=0,
                ch0_rail_hi=0, ch0_guard_lo=0, ch0_guard_hi=0, windows=0)
        row = dict(
            role=str(role), leg=int(leg), direction=str(direction),
            grid_index=int(grid_index), sequence_index=int(sequence_index),
            schedule_sequence_index=int(schedule_sequence_index),
            bias=float(bias), t_start_unix=float(started_point),
            t_end_unix=float(ended_point),
            t_mid_unix=float(0.5 * (started_point + ended_point)),
            dc_dmm=float(dc_dmm), dc_board=float(acq["dc"]),
            I1=float(tone1["I"]), Q1=float(tone1["Q"]),
            I2=float(tone2["I"]), Q2=float(tone2["Q"]),
            **{f"rawadc_{name}": value for name, value in rawadc.items()},
        )
        with open(csv_path, "a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow([row[name] for name in header])
        all_rows.append(row)
        if raw_missing:
            raise RuntimeError(
                "same-window CH0 RAWADC telemetry missing; v1.3 requires new firmware")
        return row

    def checkpoint_summary(complete=False):
        value = dict(
            complete=bool(complete),
            conditioning_rows=int(conditioning_count),
            acquired_schedule_rows=len(formal_rows),
            expected_schedule_rows=len(schedule_records),
            analysis=analysis_summary,
        )
        _write_json(os.path.join(root, "summary.json"), value)

    caught = None
    try:
        with ExitStack() as stack:
            if args.sim:
                board = mb.SimBoard(seed=20260716)
                board.VPI = tt.VPI_V
                board.V0 = tt.CENTER_V
                board.DC_A = 0.60
                board.DC_B = 0.40
                dmm = mb.SimDMM(board)
            else:
                board = stack.enter_context(mb.open_board())
                dmm = stack.enter_context(mb.open_dmm())
            try:
                mb.assert_board_ready_for_evidence(board)
                mb.configure_dc_fast(dmm)
                mb.prepare_mzm_frontend(board, PILOT_V)
                for index, bias in enumerate(conditioning):
                    t_start = (1_800_000_000.0 + 2.0 * index
                               if args.sim else time.time())
                    acq, dc = mb.acq_point_prepared(
                        board, dmm, float(bias), PILOT_V, CONDITIONING_BLOCKS)
                    t_end = t_start + 1.0 if args.sim else time.time()
                    append_row("conditioning", -1, "conditioning", -1, index, -1,
                               bias, t_start, t_end, acq, dc)
                    conditioning_count += 1
                    checkpoint_summary(False)

                for index, item in enumerate(schedule_records):
                    t_start = (1_800_000_000.0 +
                               2.0 * (len(conditioning) + index)
                               if args.sim else time.time())
                    acq, dc = mb.average_acq_point(
                        board, dmm, item["bias_V"], PILOT_V, N_BLOCKS, N_AVG)
                    t_end = t_start + 1.0 if args.sim else time.time()
                    row = append_row(
                        item["role"], item["leg"], item["direction"],
                        item["grid_index"], len(conditioning) + item["sequence_index"],
                        item["sequence_index"],
                        item["bias_V"], t_start, t_end, acq, dc)
                    formal_rows.append(row)
                    checkpoint_summary(False)
                    if (args.sim_fail_after is not None and
                            len(formal_rows) >= args.sim_fail_after):
                        raise RuntimeError(
                            f"injected simulation failure after {len(formal_rows)} rows")
                    if index == 0 or (index + 1) % 20 == 0 or index + 1 == len(
                            schedule_records):
                        print(
                            f"[time-cal] {index + 1:3d}/{len(schedule_records)} "
                            f"leg={item['leg']} {item['direction']:>4} "
                            f"role={item['role']:<8} bias={item['bias_V']:+.3f} "
                            f"DMM={dc:.4f}", flush=True)

                fields = {name: np.asarray([row[name] for row in formal_rows])
                          for name in header}
                formal_mask = fields["role"] == "formal"
                components = mb.choose_comps(
                    fields["I1"][formal_mask], fields["Q1"][formal_mask],
                    fields["I2"][formal_mask], fields["Q2"][formal_mask])
                X = fields["I2"] if components[0] == "I" else fields["Q2"]
                Y = fields["I1"] if components[1] == "I" else fields["Q1"]
                tmp_npz = os.path.join(root, "time_calibration.npz.tmp.npz")
                np.savez(tmp_npz, **fields, X=X, Y=Y,
                         comps=np.asarray(components), fixed_vpi=tt.VPI_V,
                         coordinate_center=tt.CENTER_V,
                         schedule_sha256=schedule_hash)
                os.replace(tmp_npz, os.path.join(root, "time_calibration.npz"))

                result = tt.analyze_time_truth(
                    time_unix=fields["t_mid_unix"], bias=fields["bias"],
                    dc=fields["dc_dmm"], role=fields["role"],
                    direction=fields["direction"],
                    sequence_index=fields["schedule_sequence_index"], X=X, Y=Y,
                    dc_board=fields["dc_board"])
                mapping = tt.analyze_direction_mapping_stability(
                    X, Y, result["fit"]["phase_truth"], fields["role"],
                    fields["leg"], fields["direction"])
                result = tt.require_observer_mapping_stability(result, mapping)
                raw_fields = {
                    name: np.asarray([row[f"rawadc_{name}"] for row in all_rows])
                    for name in (
                        "version", "scope", "expected", "used", "read_fail",
                        "blocks", "complete", "timeout", "gain", "fs_uv",
                        "guard", "crc", "ch0_min", "ch0_max", "ch0_rail_lo",
                        "ch0_rail_hi", "ch0_guard_lo", "ch0_guard_hi", "windows")
                }
                rawadc_result = tt.analyze_adc_raw_telemetry(**raw_fields)
                result = tt.require_adc_raw_telemetry(result, rawadc_result)
                analysis_summary = _analysis_summary(result)
                analysis_summary["components"] = list(components)
                _write_json(os.path.join(root, "analysis.json"), analysis_summary)
                status = "complete"
                checkpoint_summary(True)
            except BaseException as exc:
                caught = exc
                failure = f"{type(exc).__name__}: {exc}"
            finally:
                if args.sim:
                    if args.sim_cleanup_fail:
                        cleanup_failure = "cleanup failed: injected simulation failure"
                        status = "failed"
                        failure = (cleanup_failure if failure is None else
                                   f"{failure}; {cleanup_failure}")
                        if caught is None:
                            caught = RuntimeError(cleanup_failure)
                        board_final_status = {"State": "SIM-UNSAFE", "Bias": "SIM"}
                    else:
                        board_final_status = {"State": "SIM", "Bias": "SIM"}
                else:
                    try:
                        board.gen_reset()
                        board.dac(0.0)
                        board_final_status = board.status()
                        final_lock = str(board_final_status.get("Lock", "NO")).upper()
                        if (str(board_final_status.get("State", "")).upper() != "IDLE" or
                                not str(board_final_status.get("Bias", "")).strip().startswith(
                                    "0.000") or final_lock not in {"NO", "OFF", "DISABLED"}):
                            raise RuntimeError(
                                f"unsafe final board status: {board_final_status}")
                    except Exception as cleanup_exc:
                        cleanup_failure = (
                            f"cleanup failed: {type(cleanup_exc).__name__}: "
                            f"{cleanup_exc}")
                        print(f"[cleanup] {cleanup_failure}", flush=True)
                        status = "failed"
                        failure = (cleanup_failure if failure is None else
                                   f"{failure}; {cleanup_failure}")
                        if caught is None:
                            caught = RuntimeError(cleanup_failure)
    except BaseException as exc:
        if caught is None:
            caught = exc
            failure = f"{type(exc).__name__}: {exc}"
    finally:
        checkpoint_summary(status == "complete")
        _write_json(os.path.join(root, "manifest.json"), dict(
            run_id=args.run_id, status=status, failure=failure,
            started_unix=started, ended_unix=time.time(),
            conditioning_rows=int(conditioning_count),
            acquired_schedule_rows=len(formal_rows),
            expected_schedule_rows=len(schedule_records),
            board_final_status=board_final_status,
            quality_gate_accepted=(None if analysis_summary is None else
                                   analysis_summary["quality_gate"]["accepted"]),
        ))
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(analysis_summary["quality_gate"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
