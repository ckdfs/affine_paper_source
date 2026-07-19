#!/usr/bin/env python3
"""Frozen real-bench short-term MZM V0 stability diagnostic.

No closed loop, no acceptance promotion, and no writes to data/exp/results.json.
See reviews/mzm_v0_stability_protocol_v1.1.md.
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


PROTOCOL_VERSION = "v0-stability-v1.1"
VPI = 5.222139048043948
V0_REFERENCE = 0.8147635714861232
OFFSETS = np.array([-0.75, -0.25, 0.25, 0.75])
EPOCHS = 6
EPOCH_INTERVAL_S = 120.0
DIRECTION_LIMIT_RAD = 0.05
TAIL_PTP_LIMIT_RAD = 0.05
EXTRAPOLATED_30MIN_LIMIT_RAD = 0.05
RMSE_OVER_AMPLITUDE_LIMIT = float(np.sin(0.05))
POST_DAC_WAIT_S = 0.75
CONFIRM_DELTA_OVER_AMPLITUDE_LIMIT = float(np.sin(0.05))


def _abort_on_signal(signum, _frame):
    raise KeyboardInterrupt(f"received signal {signum}")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fit_fixed_vpi(bias, dc, vpi=VPI, reference=V0_REFERENCE):
    """Linear sinusoid fit at fixed Vpi; return V0 on reference's branch."""
    bias = np.asarray(bias, float)
    dc = np.asarray(dc, float)
    if len(bias) < 4 or len(bias) != len(dc):
        raise ValueError("fixed-Vpi fit requires at least four paired points")
    k = np.pi / float(vpi)
    design = np.column_stack([np.ones(len(bias)), np.cos(k * bias),
                              np.sin(k * bias)])
    coef, _, rank, _ = np.linalg.lstsq(design, dc, rcond=None)
    if rank < 3:
        raise RuntimeError("fixed-Vpi design is rank deficient")
    model = design @ coef
    amp = float(np.hypot(coef[1], coef[2]))
    if not np.isfinite(amp) or amp <= 0:
        raise RuntimeError("fixed-Vpi fit has non-positive amplitude")
    v0_raw = float(np.arctan2(coef[2], coef[1]) / k)
    v0, shift = ec.align_periodic_origin(v0_raw, reference, vpi)
    rmse = float(np.sqrt(np.mean((dc - model) ** 2)))
    return dict(a=float(coef[0]), amplitude=amp, v0_V=v0,
                branch_shift_periods=int(shift), rmse_V=rmse,
                rmse_over_amplitude=float(rmse / amp))


def _theil_sen_slope(t, y):
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    slopes = [(y[j] - y[i]) / (t[j] - t[i])
              for i in range(len(t)) for j in range(i + 1, len(t))
              if t[j] > t[i]]
    return float(np.median(slopes))


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)


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

    root = os.path.join(ec.DATA, "diagnostics", "v0_stability", args.run_id)
    os.makedirs(root, exist_ok=False)
    points = V0_REFERENCE + VPI * OFFSETS
    if np.max(np.abs(points)) > mb.BIAS_LIMIT:
        raise RuntimeError("frozen diagnostic point exceeds evidence bias limit")
    started = time.time()
    status = "failed"
    failure = None
    rows = []
    epoch_metrics = []
    quality_status = None
    board_final_status = None
    try:
        repo_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ec.REPO, text=True).strip()
    except Exception:
        repo_commit = "unknown"
    protocol = dict(
        protocol_version=PROTOCOL_VERSION, purpose="diagnostic_only",
        excluded_from_primary_analysis=True, run_id=args.run_id,
        vpi_V=VPI, v0_reference_V=V0_REFERENCE, offsets_vpi=OFFSETS.tolist(),
        biases_V=points.tolist(), sequence="forward4_reverse4",
        epochs=EPOCHS, epoch_interval_s=EPOCH_INTERVAL_S,
        direction_limit_rad=DIRECTION_LIMIT_RAD,
        tail_epoch_count=5, tail_ptp_limit_rad=TAIL_PTP_LIMIT_RAD,
        extrapolation_s=1800.0,
        extrapolated_drift_limit_rad=EXTRAPOLATED_30MIN_LIMIT_RAD,
        rmse_over_amplitude_limit=RMSE_OVER_AMPLITUDE_LIMIT,
        post_dac_wait_s=POST_DAC_WAIT_S,
        readings_per_visit=["priming", "confirm_1", "confirm_2"],
        scored_reading="mean(confirm_1, confirm_2)",
        confirm_delta_over_amplitude_limit=CONFIRM_DELTA_OVER_AMPLITUDE_LIMIT,
        metadata=dict(device_id=args.device_id, firmware_rev=args.firmware_rev,
                      ambient_c=args.ambient_c, operator=args.operator,
                      session_id=args.session_id,
                      instrument_ids=args.instrument_ids, notes=args.notes),
        repo_commit=repo_commit,
        controller_source_sha256=mb._controller_source_hashes(),
        diagnostic_source_sha256=_sha256(os.path.abspath(__file__)))
    _write_json(os.path.join(root, "protocol.json"), protocol)
    csv_path = os.path.join(root, "v0_monitor.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(
            ["epoch", "order", "direction", "bias", "timestamp_unix",
             "dc_priming", "dc_confirm_1", "dc_confirm_2", "dc_scored",
             "confirm_delta"])

    def save_summary(complete=False):
        nonlocal quality_status
        summary = dict(complete=bool(complete), epochs_completed=len(epoch_metrics),
                       epoch_metrics=epoch_metrics)
        if complete and len(epoch_metrics) == EPOCHS:
            t = np.array([e["midpoint_unix"] for e in epoch_metrics])
            v0 = np.array([e["v0_V"] for e in epoch_metrics])
            tail = v0[-5:]
            tail_ptp_phase = float(np.pi * np.ptp(tail) / VPI)
            slope_v_s = _theil_sen_slope(t, v0)
            drift_30_phase = float(np.pi * abs(slope_v_s) * 1800.0 / VPI)
            gates = dict(
                all_direction_splits_pass=bool(all(
                    e["direction_split_phase_rad"] <= DIRECTION_LIMIT_RAD
                    for e in epoch_metrics)),
                all_fit_residuals_pass=bool(all(
                    e["rmse_over_amplitude"] <= RMSE_OVER_AMPLITUDE_LIMIT
                    for e in epoch_metrics)),
                all_confirmations_pass=bool(all(
                    e["max_confirm_delta_over_amplitude"] <=
                    CONFIRM_DELTA_OVER_AMPLITUDE_LIMIT
                    for e in epoch_metrics)),
                tail_ptp_phase_rad=tail_ptp_phase,
                tail_ptp_limit_rad=TAIL_PTP_LIMIT_RAD,
                tail_ptp_pass=bool(tail_ptp_phase <= TAIL_PTP_LIMIT_RAD),
                theil_sen_slope_V_per_s=slope_v_s,
                extrapolated_30min_phase_rad=drift_30_phase,
                extrapolated_30min_limit_rad=EXTRAPOLATED_30MIN_LIMIT_RAD,
                extrapolated_30min_pass=bool(
                    drift_30_phase <= EXTRAPOLATED_30MIN_LIMIT_RAD))
            gates["accepted"] = bool(all(gates[k] for k in (
                "all_direction_splits_pass", "all_fit_residuals_pass",
                "all_confirmations_pass",
                "tail_ptp_pass", "extrapolated_30min_pass")))
            summary["quality_gate"] = gates
            quality_status = gates
        _write_json(os.path.join(root, "summary.json"), summary)

    try:
        with ExitStack() as stack:
            board = stack.enter_context(mb.open_board())
            dmm = stack.enter_context(mb.open_dmm())
            try:
                mb.assert_board_ready_for_evidence(board)
                mb.configure_dc_fast(dmm)
                board.gen_reset()
                board.dac(0.0)
                for epoch in range(EPOCHS):
                    due = started + epoch * EPOCH_INTERVAL_S
                    while time.time() < due:
                        time.sleep(min(1.0, due - time.time()))
                    epoch_start = len(rows)
                    visits = [("forward", float(v)) for v in points]
                    visits += [("reverse", float(v)) for v in points[::-1]]
                    for order, (direction, bias) in enumerate(visits):
                        # This diagnostic deliberately has no pilot/acq run.
                        # ``gen bias`` only updates the waveform-generator
                        # configuration; the direct DAC command is required to
                        # apply a static voltage without starting acquisition.
                        board.dac(bias)
                        time.sleep(POST_DAC_WAIT_S)
                        dc_priming = float(mb.read_dc(dmm))
                        dc_confirm_1 = float(mb.read_dc(dmm))
                        dc_confirm_2 = float(mb.read_dc(dmm))
                        dc_scored = 0.5 * (dc_confirm_1 + dc_confirm_2)
                        confirm_delta = abs(dc_confirm_2 - dc_confirm_1)
                        row = (epoch, order, direction, bias, time.time(),
                               dc_priming, dc_confirm_1, dc_confirm_2,
                               dc_scored, confirm_delta)
                        rows.append(row)
                        with open(csv_path, "a", newline="", encoding="utf-8") as stream:
                            csv.writer(stream).writerow(row)
                    block = rows[epoch_start:]
                    all_fit = fit_fixed_vpi([r[3] for r in block],
                                            [r[8] for r in block])
                    fwd_fit = fit_fixed_vpi([r[3] for r in block[:4]],
                                            [r[8] for r in block[:4]])
                    rev_fit = fit_fixed_vpi([r[3] for r in block[4:]],
                                            [r[8] for r in block[4:]])
                    rev_aligned, _ = ec.align_periodic_origin(
                        rev_fit["v0_V"], fwd_fit["v0_V"], VPI)
                    split = float(np.pi * abs(fwd_fit["v0_V"] - rev_aligned) / VPI)
                    metric = dict(
                        epoch=epoch, midpoint_unix=float(np.mean([r[4] for r in block])),
                        v0_V=all_fit["v0_V"], amplitude_V=all_fit["amplitude"],
                        rmse_over_amplitude=all_fit["rmse_over_amplitude"],
                        max_confirm_delta_V=float(max(r[9] for r in block)),
                        max_confirm_delta_over_amplitude=float(
                            max(r[9] for r in block) / all_fit["amplitude"]),
                        forward_v0_V=fwd_fit["v0_V"], reverse_v0_V=rev_aligned,
                        direction_split_phase_rad=split)
                    epoch_metrics.append(metric)
                    save_summary(complete=False)
                    print(f"[v0] epoch {epoch + 1}/{EPOCHS}  V0={metric['v0_V']:+.4f} V  "
                          f"dir={split:.4f} rad  "
                          f"RMSE/amp={metric['rmse_over_amplitude']:.5f}  "
                          f"confirm/amp={metric['max_confirm_delta_over_amplitude']:.5f}",
                          flush=True)
                status = "complete"
                save_summary(complete=True)
                print(f"[v0] accepted={quality_status['accepted']}  "
                      f"tail_pp={quality_status['tail_ptp_phase_rad']:.4f} rad  "
                      f"30min={quality_status['extrapolated_30min_phase_rad']:.4f} rad",
                      flush=True)
            except BaseException as exc:
                failure = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                try:
                    board.gen_reset()
                    board.dac(0.0)
                    board_final_status = board.status()
                except Exception as exc:
                    print(f"[cleanup] bias reset failed: {exc}", flush=True)
    finally:
        save_summary(complete=(status == "complete"))
        _write_json(os.path.join(root, "manifest.json"), dict(
            run_id=args.run_id, status=status, failure=failure,
            started_unix=started, ended_unix=time.time(), row_count=len(rows),
            epoch_count=len(epoch_metrics), board_final_status=board_final_status))
        hashes = {}
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name != "checksums.json":
                hashes[name] = _sha256(path)
        _write_json(os.path.join(root, "checksums.json"), hashes)


if __name__ == "__main__":
    main()
