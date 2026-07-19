#!/usr/bin/env python3
"""Frozen, no-feedback MZM gauge/settling audit (real bench only).

This diagnostic is excluded from acceptance evidence.  It performs a fresh
Vpi scan and ellipse calibration, then records raw I/Q plus synchronous DMM DC
at four fixed calibration-derived biases under continuous/reset/delay
conditions.  See reviews/mzm_gauge_audit_protocol.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack

import numpy as np

import exp_common as ec
import measure_bench as mb


PROTOCOL_VERSION = "gauge-audit-v1.0"
TARGETS = np.array([0.0, 0.5 * np.pi, np.pi, 1.5 * np.pi])
APPROACHES = np.array([-1.0, 1.0])
CONDITIONS = ("continuous", "frontend_reset", "post_reset_delay60")
REPEATS = 6
DELAY_S = 60.0


def _abort_on_signal(signum, _frame):
    """Route normal termination signals through the manifest/checksum finally."""
    raise KeyboardInterrupt(f"received signal {signum}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def target_biases_from_calibration(root, fit):
    with np.load(os.path.join(root, "calib.npz")) as data:
        bias = np.asarray(data["bias"], float)
        X = np.asarray(data["X"], float)
        Y = np.asarray(data["Y"], float)
    B = np.asarray(fit["B"], float)
    c0 = np.asarray(fit["c0"], float)
    U = B @ np.stack([X - c0[0], Y - c0[1]])
    phase = np.unwrap(np.arctan2(U[1], U[0]))
    if phase[-1] < phase[0]:
        phase = phase[::-1]
        bias = bias[::-1]
    out = []
    center = 0.5 * (phase[0] + phase[-1])
    for target in TARGETS:
        equiv = np.array([target + 2 * np.pi * k for k in range(-3, 4)])
        valid = equiv[(equiv >= phase[0]) & (equiv <= phase[-1])]
        if len(valid) == 0:
            raise RuntimeError(f"target {target:.6f} is outside calibration phase span")
        q = float(valid[np.argmin(abs(valid - center))])
        out.append(float(np.interp(q, phase, bias)))
    return np.asarray(out, float)


def main():
    signal.signal(signal.SIGTERM, _abort_on_signal)
    signal.signal(signal.SIGINT, _abort_on_signal)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--firmware-rev", required=True)
    ap.add_argument("--ambient-c", type=float, required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--instrument-ids", required=True)
    ap.add_argument("--notes", default="")
    args = ap.parse_args()
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")

    root = os.path.join(ec.DATA, "diagnostics", "gauge_audit", args.run_id)
    os.makedirs(root, exist_ok=False)
    old_data = ec.DATA
    started = time.time()
    status = "failed"
    failure = None
    rows = []
    pre_rows = []
    target_bias = np.full(len(TARGETS), np.nan)
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    protocol = dict(
        protocol_version=PROTOCOL_VERSION, purpose="diagnostic_only",
        excluded_from_primary_analysis=True, run_id=args.run_id,
        targets_rad=TARGETS.tolist(), approaches_rad=APPROACHES.tolist(),
        conditions=list(CONDITIONS), repeats=REPEATS, delay_s=DELAY_S,
        vpi_points=151, calibration_points=181, n_blocks=16, cal_n_avg=4,
        sample_n_avg=1, pilot_v=0.15, calibration_method="ellipse",
        metadata=dict(device_id=args.device_id, firmware_rev=args.firmware_rev,
                      ambient_c=args.ambient_c, operator=args.operator,
                      session_id=args.session_id,
                      instrument_ids=args.instrument_ids, notes=args.notes),
        repo_commit=repo_commit,
        controller_source_sha256=mb._controller_source_hashes())
    with open(os.path.join(root, "protocol.json"), "w") as f:
        json.dump(protocol, f, indent=2)

    def save_partial():
        np.savez(
            os.path.join(root, "gauge_audit.npz"),
            targets=TARGETS, approaches=APPROACHES,
            conditions=np.asarray(CONDITIONS), target_bias=target_bias,
            condition=np.asarray([r[0] for r in rows], dtype="U32"),
            target_index=np.asarray([r[1] for r in rows], int),
            approach=np.asarray([r[2] for r in rows], float),
            repeat=np.asarray([r[3] for r in rows], int),
            timestamp_unix=np.asarray([r[4] for r in rows], float),
            bias=np.asarray([r[5] for r in rows], float),
            dmm_dc=np.asarray([r[6] for r in rows], float),
            board_dc=np.asarray([r[7] for r in rows], float),
            I1=np.asarray([r[8] for r in rows], float),
            Q1=np.asarray([r[9] for r in rows], float),
            I2=np.asarray([r[10] for r in rows], float),
            Q2=np.asarray([r[11] for r in rows], float),
            pre_condition=np.asarray([r[0] for r in pre_rows], dtype="U32"),
            pre_target_index=np.asarray([r[1] for r in pre_rows], int),
            pre_approach=np.asarray([r[2] for r in pre_rows], float),
            pre_timestamp_unix=np.asarray([r[3] for r in pre_rows], float),
            pre_bias=np.asarray([r[4] for r in pre_rows], float),
            pre_dmm_dc=np.asarray([r[5] for r in pre_rows], float),
            pre_board_dc=np.asarray([r[6] for r in pre_rows], float),
            pre_I1=np.asarray([r[7] for r in pre_rows], float),
            pre_Q1=np.asarray([r[8] for r in pre_rows], float),
            pre_I2=np.asarray([r[9] for r in pre_rows], float),
            pre_Q2=np.asarray([r[10] for r in pre_rows], float))

    ec.DATA = root
    try:
        with ExitStack() as stack:
            board = stack.enter_context(mb.open_board())
            dmm = stack.enter_context(mb.open_dmm())
            try:
                mb.assert_board_ready_for_evidence(board)
                mb.configure_dc_fast(dmm)
                vpi, v0 = mb.stage_vpi(
                    board, dmm, root, pilot_v=0.15, require_valid=True)
                mb.stage_calib(
                    board, dmm, root, vpi, v0, n=181, pilot_v=0.15,
                    n_blocks=16, n_avg=4, cal_method="ellipse",
                    require_valid=True)
                fit = mb._load_fit(root)
                target_bias[:] = target_biases_from_calibration(root, fit)
                with np.load(os.path.join(root, "calib.npz")) as data:
                    scan_truth = ec.bias_to_phase(
                        data["bias"], fit["scan_vpi"], fit["scan_v0"])
                    scan_check = ec.self_check_mrad(
                        data["X"], data["Y"], fit, scan_truth)
                with open(os.path.join(root, "audit_setup.json"), "w") as f:
                    json.dump(dict(target_bias_V=target_bias.tolist(),
                                   primary_scan_map_selfcheck_mrad=scan_check),
                              f, indent=2)

                for condition in CONDITIONS:
                    if condition == "frontend_reset":
                        mb.prepare_mzm_frontend(board, fit["pilot_v"])
                    elif condition == "post_reset_delay60":
                        mb.prepare_mzm_frontend(board, fit["pilot_v"])
                        print(f"[gauge-audit] fixed delay {DELAY_S:.0f} s", flush=True)
                        time.sleep(DELAY_S)
                    for ti, target in enumerate(TARGETS):
                        for approach in APPROACHES:
                            prebias = float(target_bias[ti] +
                                            fit["scan_vpi"] * approach / np.pi)
                            if abs(prebias) > mb.BIAS_LIMIT:
                                raise RuntimeError(
                                    f"audit prebias {prebias:+.3f} V exceeds rail")
                            acq, p = mb.acq_point_prepared(
                                board, dmm, prebias, fit["pilot_v"], 16)
                            t1, t2 = acq["tones"][mb.PILOT_HZ], acq["tones"][mb.H2_HZ]
                            pre_rows.append((condition, ti, approach, time.time(),
                                             prebias, p, acq["dc"],
                                             t1["I"], t1["Q"], t2["I"], t2["Q"]))
                            for rep in range(REPEATS):
                                acq, p = mb.acq_point_prepared(
                                    board, dmm, float(target_bias[ti]),
                                    fit["pilot_v"], 16)
                                t1 = acq["tones"][mb.PILOT_HZ]
                                t2 = acq["tones"][mb.H2_HZ]
                                rows.append((condition, ti, approach, rep,
                                             time.time(), float(target_bias[ti]),
                                             p, acq["dc"], t1["I"], t1["Q"],
                                             t2["I"], t2["Q"]))
                                save_partial()
                            print(f"[gauge-audit] {condition:>18} target={target:.2f} "
                                  f"approach={approach:+.1f} complete", flush=True)
                status = "complete"
            except BaseException as exc:
                failure = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                save_partial()
                try:
                    board.gen_reset()
                    board.dac(0.0)
                except Exception as exc:
                    print(f"[cleanup] bias reset failed: {exc}", file=sys.stderr)
    finally:
        ec.DATA = old_data
        with open(os.path.join(root, "manifest.json"), "w") as f:
            json.dump(dict(run_id=args.run_id, status=status, failure=failure,
                           started_unix=started, ended_unix=time.time(),
                           row_count=len(rows), pre_row_count=len(pre_rows)),
                      f, indent=2)
        hashes = {}
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name != "checksums.json":
                hashes[name] = sha256(path)
        with open(os.path.join(root, "checksums.json"), "w") as f:
            json.dump(hashes, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
