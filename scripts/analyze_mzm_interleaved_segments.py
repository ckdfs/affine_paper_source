#!/usr/bin/env python3
"""Validate three immutable v1.1 segments and build a derived full bundle."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

import diagnose_mzm_interleaved_calibration as diag
import mzm_interleaved_truth as it
import validate_mzm_interleaved_calibration as replay


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows([[row[name] for name in header] for row in rows])


def _write_npz(path, header, rows, schedule_hash):
    fields = {name: np.asarray([row[name] for row in rows]) for name in header}
    tmp = str(path) + ".tmp.npz"
    np.savez(tmp, **fields, schedule_sha256=schedule_hash)
    os.replace(tmp, path)


def _validate_segment_subprocess(root):
    command = [sys.executable, str(Path(replay.__file__).resolve()),
               "--replay-dir", str(root)]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"segment replay rejected {root}: {result.stderr or result.stdout}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segment-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if len(args.segment_dir) != it.SEGMENT_COUNT:
        raise RuntimeError("exactly three --segment-dir arguments are required")
    roots = [Path(value).resolve() for value in args.segment_dir]
    for root in roots:
        _validate_segment_subprocess(root)

    loaded = []
    schedule = it.build_schedule()
    schedule_hash = it.schedule_sha256(schedule)
    for root in roots:
        protocol = json.loads((root / "protocol.json").read_text())
        manifest = json.loads((root / "manifest.json").read_text())
        checksums = json.loads((root / "checksums.json").read_text())
        index = int(protocol.get("segment_index", -1))
        if not protocol.get("segmented") or index not in range(it.SEGMENT_COUNT):
            raise RuntimeError(f"not a frozen v1.1 segment: {root}")
        if (manifest.get("status") != "complete" or
                not manifest.get("quality_gate_accepted")):
            raise RuntimeError(f"segment is not complete and accepted: {root}")
        loaded.append((index, root, protocol, manifest, checksums))
    if [value[0] for value in loaded] != list(range(it.SEGMENT_COUNT)):
        raise RuntimeError("segment indices are missing, duplicated, or out of order")
    source_hashes = [value[2].get("source_sha256") for value in loaded]
    if any(value != source_hashes[0] for value in source_hashes[1:]):
        raise RuntimeError("segment source/protocol hashes differ")
    metadata_keys = ("device_id", "firmware_rev", "instrument_ids")
    reference_metadata = loaded[0][2].get("metadata", {})
    if any(any(value[2].get("metadata", {}).get(key) !=
                   reference_metadata.get(key) for key in metadata_keys)
           for value in loaded[1:]):
        raise RuntimeError("segment hardware metadata differ")
    simulated = bool(loaded[0][2].get("simulated"))
    if any(bool(value[2].get("simulated")) != simulated for value in loaded):
        raise RuntimeError("segment simulation flags differ")

    def safe_status(status, sim):
        if not isinstance(status, dict):
            return False
        if sim:
            return status.get("State") == "SIM"
        try:
            bias = float(str(status.get("Bias", "")).split()[0])
        except (TypeError, ValueError, IndexError):
            return False
        return bool(
            str(status.get("State", "")).upper() == "IDLE" and
            abs(bias) <= 5e-4 and
            str(status.get("Lock", "")).upper() == "NO" and
            str(status.get("Cal", "")).upper() == "INVALID")
    if any(not safe_status(value[3].get("board_initial_status"), simulated) or
           not safe_status(value[3].get("board_final_status"), simulated)
           for value in loaded):
        raise RuntimeError("segment initial/final safe-state contract failed")
    if not simulated and any(
            float(loaded[index][3]["ended_unix"]) >=
            float(loaded[index + 1][3]["started_unix"])
            for index in range(it.SEGMENT_COUNT - 1)):
        raise RuntimeError("real segment wall-clock order overlaps or reverses")

    rows = []
    windows = []
    discards = []
    conditioning = []
    expected_conditioning = []
    pilot = {}
    conditioning_offset = 0
    previous_acq_end = None
    for index, root, protocol, manifest, checksums in loaded:
        start, end = it.segment_bounds(index)
        segment_records = it.schedule_records(schedule)[start:end]
        segment_rows = replay._load_npz(
            root / "interleaved_calibration.npz", diag.MAIN_HEADER,
            schedule_hash)
        segment_windows = replay._load_npz(
            root / "formal_windows.npz", diag.WINDOW_HEADER, schedule_hash)
        segment_discards = replay._load_npz(
            root / "transition_discard.npz", diag.DISCARD_HEADER,
            schedule_hash)
        segment_conditioning = replay._load_csv(
            root / "conditioning.csv", diag.CONDITIONING_HEADER)
        segment_pilot = json.loads(
            (root / "pilot_verification.json").read_text())
        segment_acq_start = min(float(row["t_acq_start_unix"])
                                for row in segment_rows)
        segment_acq_end = max(float(row["t_acq_end_unix"])
                              for row in segment_rows)
        if previous_acq_end is not None and previous_acq_end >= segment_acq_start:
            raise RuntimeError("segment acquisition times overlap or reverse")
        previous_acq_end = segment_acq_end
        for local, row in enumerate(segment_rows):
            row["transition_discard_index"] = start + local
        for row in segment_windows:
            row["window_sequence_index"] = (
                int(row["source_sequence_index"]) * it.N_AVG +
                int(row["window_index"]))
        for local, row in enumerate(segment_discards):
            row["transition_discard_index"] = start + local
        plan = diag._expected_bridges(segment_records)
        if len(plan) != len(segment_conditioning):
            raise RuntimeError(f"segment {index} conditioning count differs")
        for local, (row, expected) in enumerate(zip(
                segment_conditioning, plan)):
            row["sequence_index"] = conditioning_offset + local
            expected = dict(expected)
            expected["sequence_index"] = conditioning_offset + local
            expected_conditioning.append(expected)
        conditioning_offset += len(plan)
        overlap = set(pilot).intersection(segment_pilot)
        if overlap:
            raise RuntimeError(f"duplicate pilot verification keys: {overlap}")
        pilot.update(segment_pilot)
        rows.extend(segment_rows)
        windows.extend(segment_windows)
        discards.extend(segment_discards)
        conditioning.extend(segment_conditioning)

    if [int(row["sequence_index"]) for row in rows] != list(range(162)):
        raise RuntimeError("merged observation sequence is not exactly 0..161")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    _write_csv(output / "interleaved_calibration.csv", diag.MAIN_HEADER, rows)
    _write_csv(output / "formal_windows.csv", diag.WINDOW_HEADER, windows)
    _write_csv(output / "transition_discard.csv", diag.DISCARD_HEADER, discards)
    _write_csv(output / "conditioning.csv", diag.CONDITIONING_HEADER, conditioning)
    _write_npz(output / "interleaved_calibration.npz", diag.MAIN_HEADER,
               rows, schedule_hash)
    _write_npz(output / "formal_windows.npz", diag.WINDOW_HEADER,
               windows, schedule_hash)
    _write_npz(output / "transition_discard.npz", diag.DISCARD_HEADER,
               discards, schedule_hash)
    _write_json(output / "pilot_verification.json", pilot)
    discard_hashes = {name: _sha256(output / name) for name in (
        "transition_discard.csv", "transition_discard.npz")}
    analysis = diag._analyze(
        rows, windows, discards, conditioning, pilot, discard_hashes,
        expected_conditioning=expected_conditioning)
    _write_json(output / "analysis.json", analysis)
    source_segments = [dict(
        segment_index=index, path=str(root),
        checksums_sha256=_sha256(root / "checksums.json"),
        checksums=checksums,
        board_final_status=manifest.get("board_final_status"))
        for index, root, protocol, manifest, checksums in loaded]
    _write_json(output / "protocol.json", dict(
        protocol_version=it.PROTOCOL_VERSION,
        purpose="derived_segment_bundle", segmented_bundle=True,
        schedule=it.schedule_records(schedule), schedule_sha256=schedule_hash,
        target_order=it.target_order().tolist(),
        expected_bridge_rows=len(expected_conditioning),
        source_sha256=source_hashes[0], source_segments=source_segments,
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False))
    _write_json(output / "summary.json", dict(
        complete=True, conditioning_rows=len(conditioning),
        acquired_observations=len(rows), acquired_windows=len(windows),
        acquired_discards=len(discards), analysis=analysis))
    _write_json(output / "manifest.json", dict(
        status="complete", failure=None, quality_gate_accepted=
        analysis["quality_gate"]["accepted"], source_segments=source_segments))
    checksums = {path.name: _sha256(path) for path in sorted(output.iterdir())
                 if path.is_file() and path.name != "checksums.json"}
    _write_json(output / "checksums.json", checksums)
    print(json.dumps(dict(
        accepted=analysis["quality_gate"]["accepted"],
        rows=len(rows), windows=len(windows), discards=len(discards),
        conditioning_rows=len(conditioning),
        target_time_abs_corr=analysis["target_time_abs_corr"],
        direction_split_phase_rad=analysis["quality_gate"][
            "direction_split_phase_rad"],
        drift_30min_phase_rad=analysis["quality_gate"][
            "drift_30min_phase_rad"]), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
