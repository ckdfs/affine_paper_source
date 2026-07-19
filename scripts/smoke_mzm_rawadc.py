#!/usr/bin/env python3
"""Flash and audit the preregistered 0 V CH0 RAWADC telemetry smoke test."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from contextlib import ExitStack

import exp_common as ec
import measure_bench as mb
import mzm_time_truth as tt


PROTOCOL_VERSION = "mzm-rawadc-smoke-v1.0"
PILOT_V = 0.15
N_BLOCKS = 2
PROBE_UID = "066FFF505754675087091823"
TARGET = "stm32h523cetx"


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


def _raw_fields(rawadc):
    return {name: [rawadc[name]] for name in (
        "version", "scope", "expected", "used", "read_fail", "blocks",
        "complete", "timeout", "gain", "fs_uv", "guard", "crc",
        "ch0_min", "ch0_max", "ch0_rail_lo", "ch0_rail_hi",
        "ch0_guard_lo", "ch0_guard_hi", "windows")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--firmware-elf", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--i-understand-this-flashes-and-writes-real-hardware",
                        action="store_true")
    args = parser.parse_args()
    if not args.sim and not args.i_understand_this_flashes_and_writes_real_hardware:
        raise RuntimeError("real smoke requires explicit flash/hardware acknowledgement")
    if not all(ch.isalnum() or ch in "-_" for ch in args.run_id):
        raise ValueError("run-id may contain only letters, digits, '-' and '_'")
    elf = os.path.abspath(args.firmware_elf)
    if not os.path.isfile(elf):
        raise FileNotFoundError(elf)

    root = (os.path.join(ec.REPO, "build", "exp_sim", "rawadc_smoke", args.run_id)
            if args.sim else
            os.path.join(ec.DATA, "diagnostics", "rawadc_smoke", args.run_id))
    os.makedirs(root, exist_ok=False)
    started = time.time()
    manifest = dict(
        run_id=args.run_id, status="failed", failure="initialization incomplete",
        started_unix=started, ended_unix=None, flash_returncode=None,
        quality_gate_accepted=None, board_initial_status=None,
        board_final_status=None)
    _write_json(os.path.join(root, "manifest.json"), manifest)
    _refresh_checksums(root)

    protocol = dict(
        protocol_version=PROTOCOL_VERSION, simulated=bool(args.sim),
        purpose="diagnostic_only", headline_promotion=False,
        firmware_elf=elf, firmware_elf_sha256=_sha256(elf),
        firmware_base_commit="8b1b1c292dd1e06257a93a4a07f3088e96b1d2cf",
        probe_uid=PROBE_UID, target=TARGET, bias_V=0.0, pilot_V=PILOT_V,
        pilot_Hz=mb.PILOT_HZ, n_blocks=N_BLOCKS,
        expected_samples=N_BLOCKS * 1280,
        operator=args.operator, notes=args.notes,
        source_sha256=dict(
            smoke_mzm_rawadc_py=_sha256(os.path.abspath(__file__)),
            measure_bench_py=_sha256(os.path.abspath(mb.__file__)),
            mzm_time_truth_py=_sha256(os.path.abspath(tt.__file__)),
            firmware_app_main_c=_sha256(
                "/Users/ckdfs/code/biascontrol_h523/src/app/app_main.c")),
    )
    _write_json(os.path.join(root, "protocol.json"), protocol)
    _refresh_checksums(root)

    caught = None
    flash_returncode = None
    initial_status = None
    final_status = None
    analysis = None
    raw_response = None
    try:
        if args.sim:
            board = mb.SimBoard(seed=20260717)
            acq = board.acq_run_mzm(0.0, pilot_v=PILOT_V, n_blocks=N_BLOCKS)
            initial_status = {"State": "SIM", "Bias": "0.000 V", "Lock": "NO"}
            final_status = dict(initial_status)
            flash_returncode = 0
        else:
            flash = subprocess.run(
                ["pyocd", "flash", "-u", PROBE_UID, "-t", TARGET, elf],
                text=True, capture_output=True, timeout=180, check=False)
            flash_returncode = int(flash.returncode)
            _write_json(os.path.join(root, "flash.json"), dict(
                command=["pyocd", "flash", "-u", PROBE_UID, "-t", TARGET, elf],
                returncode=flash_returncode, stdout=flash.stdout,
                stderr=flash.stderr))
            _refresh_checksums(root)
            if flash_returncode != 0:
                raise RuntimeError(f"pyocd flash failed with {flash_returncode}")
            time.sleep(2.0)
            with ExitStack() as stack:
                board = stack.enter_context(mb.open_board())
                initial_status = board.status()
                try:
                    mb.assert_board_ready_for_evidence(board)
                    mb.prepare_mzm_frontend(board, PILOT_V)
                    board.gen_bias(mb.CH, 0.0)
                    acq = mb.attach_rawadc_telemetry(board.acq_run(N_BLOCKS))
                    raw_response = acq.get("_raw", "")
                finally:
                    board.gen_reset()
                    board.dac(0.0)
                    final_status = board.status()

        rawadc = acq.get("rawadc")
        if rawadc is None:
            raise RuntimeError("RAWADC telemetry missing from smoke acquisition")
        raw_gate = tt.analyze_adc_raw_telemetry(**_raw_fields(rawadc))
        tones_complete = bool(
            mb.PILOT_HZ in acq.get("tones", {}) and
            mb.H2_HZ in acq.get("tones", {}) and
            acq.get("blocks") == N_BLOCKS)
        safe_final = bool(
            args.sim or (
                str(final_status.get("State", "")).upper() == "IDLE" and
                str(final_status.get("Bias", "")).strip().startswith("0.000") and
                str(final_status.get("Lock", "NO")).upper() in
                {"NO", "OFF", "DISABLED"}))
        accepted = bool(raw_gate["accepted"] and tones_complete and safe_final)
        analysis = dict(
            accepted=accepted, rawadc=rawadc, rawadc_gate=raw_gate,
            acq_blocks=acq.get("blocks"), dc_board=acq.get("dc"),
            tones_complete=tones_complete, safe_final=safe_final,
            adc_raw_extrema_available=bool(raw_gate["accepted"]),
            v1_4_authorization_ready=False,
            headline_promotion=False)
        _write_json(os.path.join(root, "analysis.json"), analysis)
        if raw_response is not None:
            _write_json(os.path.join(root, "raw_response.json"),
                        {"response": raw_response})
        if not accepted:
            raise RuntimeError("RAWADC smoke quality gate failed")
    except BaseException as exc:
        caught = exc
    finally:
        failure = None if caught is None else f"{type(caught).__name__}: {caught}"
        manifest = dict(
            run_id=args.run_id,
            status="complete" if caught is None else "failed",
            failure=failure, started_unix=started, ended_unix=time.time(),
            flash_returncode=flash_returncode,
            quality_gate_accepted=(None if analysis is None else analysis["accepted"]),
            board_initial_status=initial_status, board_final_status=final_status)
        _write_json(os.path.join(root, "manifest.json"), manifest)
        _refresh_checksums(root)
    if caught is not None:
        raise caught
    print(json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
