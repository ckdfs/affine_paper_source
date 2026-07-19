#!/usr/bin/env python3
"""Production-path dense-sweep MZM V0 stability diagnostic (real bench)."""
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
from monitor_mzm_v0 import fit_fixed_vpi


PROTOCOL_VERSION = "v0-dense-sweep-v1.0"
VPI = 5.222139048043948
V0_REFERENCE = 0.8147635714861232
LO = V0_REFERENCE - VPI
HI = V0_REFERENCE + VPI
N_POINTS = 81
EPOCHS = 3
PILOT_V = 0.15
N_BLOCKS = 6
PHASE_LIMIT = 0.05
FIT_LIMIT = float(np.sin(0.05))


def _abort(signum, _frame):
    raise KeyboardInterrupt(f"received signal {signum}")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)


def _slope(t, y):
    slopes = [(y[j] - y[i]) / (t[j] - t[i])
              for i in range(len(t)) for j in range(i + 1, len(t))]
    return float(np.median(slopes))


def main():
    signal.signal(signal.SIGINT, _abort)
    signal.signal(signal.SIGTERM, _abort)
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
    root = os.path.join(ec.DATA, "diagnostics", "v0_dense", args.run_id)
    os.makedirs(root, exist_ok=False)
    started = time.time()
    status, failure = "failed", None
    rows, metrics = [], []
    board_final_status = None
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    step = (HI - LO) / (N_POINTS - 1)
    conditioning = np.linspace(0.0, LO, int(np.ceil(abs(LO) / step)) + 1)[1:]
    protocol = dict(
        protocol_version=PROTOCOL_VERSION, purpose="diagnostic_only",
        excluded_from_primary_analysis=True, run_id=args.run_id,
        vpi_V=VPI, v0_reference_V=V0_REFERENCE, lo_V=LO, hi_V=HI,
        points_per_direction=N_POINTS, step_V=step, epochs=EPOCHS,
        conditioning_points=len(conditioning), pilot_V=PILOT_V,
        pilot_Hz=mb.PILOT_HZ, n_blocks=N_BLOCKS,
        fit_rmse_over_amplitude_limit=FIT_LIMIT,
        direction_split_phase_limit_rad=PHASE_LIMIT,
        epoch_v0_ptp_phase_limit_rad=PHASE_LIMIT,
        extrapolated_30min_phase_limit_rad=PHASE_LIMIT,
        metadata=dict(device_id=args.device_id, firmware_rev=args.firmware_rev,
                      ambient_c=args.ambient_c, operator=args.operator,
                      session_id=args.session_id,
                      instrument_ids=args.instrument_ids, notes=args.notes),
        repo_commit=repo_commit,
        controller_source_sha256=mb._controller_source_hashes(),
        diagnostic_source_sha256=_sha256(os.path.abspath(__file__)))
    _write_json(os.path.join(root, "protocol.json"), protocol)
    csv_path = os.path.join(root, "dense_sweep.csv")
    header = ["kind", "epoch", "direction", "index", "bias",
              "timestamp_unix", "dc_dmm", "dc_board", "I1", "Q1", "I2", "Q2"]
    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(header)

    def append_row(kind, epoch, direction, index, bias, acq, dmm):
        t1, t2 = acq["tones"][mb.PILOT_HZ], acq["tones"][mb.H2_HZ]
        row = (kind, epoch, direction, index, float(bias), time.time(),
               float(dmm), float(acq["dc"]), float(t1["I"]), float(t1["Q"]),
               float(t2["I"]), float(t2["Q"]))
        rows.append(row)
        with open(csv_path, "a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(row)

    def save_summary(complete=False):
        summary = dict(complete=bool(complete), row_count=len(rows),
                       epoch_metrics=metrics)
        if complete and len(metrics) == EPOCHS:
            epoch_v0 = np.array([m["v0_V"] for m in metrics])
            epoch_t = np.array([m["midpoint_unix"] for m in metrics])
            ptp_phase = float(np.pi * np.ptp(epoch_v0) / VPI)
            slope_v_s = _slope(epoch_t, epoch_v0)
            extrap = float(np.pi * abs(slope_v_s) * 1800.0 / VPI)
            gates = dict(
                all_direction_fits_pass=bool(all(
                    d["rmse_over_amplitude"] <= FIT_LIMIT
                    for m in metrics for d in m["directions"])),
                all_direction_splits_pass=bool(all(
                    m["direction_split_phase_rad"] <= PHASE_LIMIT
                    for m in metrics)),
                epoch_v0_ptp_phase_rad=ptp_phase,
                epoch_v0_ptp_limit_rad=PHASE_LIMIT,
                epoch_v0_ptp_pass=bool(ptp_phase <= PHASE_LIMIT),
                theil_sen_slope_V_per_s=slope_v_s,
                extrapolated_30min_phase_rad=extrap,
                extrapolated_30min_limit_rad=PHASE_LIMIT,
                extrapolated_30min_pass=bool(extrap <= PHASE_LIMIT))
            gates["accepted"] = bool(all(gates[k] for k in (
                "all_direction_fits_pass", "all_direction_splits_pass",
                "epoch_v0_ptp_pass", "extrapolated_30min_pass")))
            summary["quality_gate"] = gates
        _write_json(os.path.join(root, "summary.json"), summary)

    try:
        with ExitStack() as stack:
            board = stack.enter_context(mb.open_board())
            dmm = stack.enter_context(mb.open_dmm())
            try:
                mb.assert_board_ready_for_evidence(board)
                mb.configure_dc_fast(dmm)
                mb.prepare_mzm_frontend(board, PILOT_V)
                for i, bias in enumerate(conditioning):
                    acq, dc = mb.acq_point_prepared(
                        board, dmm, float(bias), PILOT_V, N_BLOCKS)
                    append_row("conditioning", -1, "conditioning", i, bias, acq, dc)
                grid = np.linspace(LO, HI, N_POINTS)
                for epoch in range(EPOCHS):
                    direction_metrics = []
                    epoch_rows = []
                    for direction, seq in (("up", grid), ("down", grid[::-1])):
                        dir_rows = []
                        for i, bias in enumerate(seq):
                            acq, dc = mb.acq_point_prepared(
                                board, dmm, float(bias), PILOT_V, N_BLOCKS)
                            append_row("formal", epoch, direction, i, bias, acq, dc)
                            dir_rows.append(rows[-1]); epoch_rows.append(rows[-1])
                            if i == 0 or (i + 1) % 20 == 0 or i + 1 == N_POINTS:
                                print(f"[dense] epoch {epoch + 1}/{EPOCHS} {direction:>4} "
                                      f"{i + 1:2d}/{N_POINTS} bias={bias:+.3f} "
                                      f"DMM={dc:.4f}", flush=True)
                        fit = fit_fixed_vpi([r[4] for r in dir_rows],
                                            [r[6] for r in dir_rows],
                                            vpi=VPI, reference=V0_REFERENCE)
                        direction_metrics.append(dict(
                            direction=direction, v0_V=fit["v0_V"],
                            amplitude_V=fit["amplitude"],
                            rmse_over_amplitude=fit["rmse_over_amplitude"]))
                    down_v0, _ = ec.align_periodic_origin(
                        direction_metrics[1]["v0_V"], direction_metrics[0]["v0_V"], VPI)
                    split = float(np.pi * abs(direction_metrics[0]["v0_V"] - down_v0) / VPI)
                    mean_v0 = 0.5 * (direction_metrics[0]["v0_V"] + down_v0)
                    mean_v0, _ = ec.align_periodic_origin(mean_v0, V0_REFERENCE, VPI)
                    metric = dict(epoch=epoch,
                                  midpoint_unix=float(np.mean([r[5] for r in epoch_rows])),
                                  v0_V=mean_v0,
                                  direction_split_phase_rad=split,
                                  directions=direction_metrics)
                    metrics.append(metric); save_summary(False)
                    print(f"[dense] epoch {epoch + 1}/{EPOCHS} V0={mean_v0:+.4f} V "
                          f"dir={split:.4f} rad fits="
                          f"{direction_metrics[0]['rmse_over_amplitude']:.5f}/"
                          f"{direction_metrics[1]['rmse_over_amplitude']:.5f}", flush=True)
                status = "complete"
                save_summary(True)
            except BaseException as exc:
                failure = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                try:
                    board.gen_reset(); board.dac(0.0)
                    board_final_status = board.status()
                except Exception as exc:
                    print(f"[cleanup] bias reset failed: {exc}", flush=True)
    finally:
        save_summary(status == "complete")
        _write_json(os.path.join(root, "manifest.json"), dict(
            run_id=args.run_id, status=status, failure=failure,
            started_unix=started, ended_unix=time.time(), row_count=len(rows),
            epoch_count=len(metrics), board_final_status=board_final_status))
        hashes = {}
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name != "checksums.json":
                hashes[name] = _sha256(path)
        _write_json(os.path.join(root, "checksums.json"), hashes)


if __name__ == "__main__":
    main()
