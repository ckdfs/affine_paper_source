#!/usr/bin/env python3
"""Read-only replay of a three-segment interleaved-calibration bundle."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import diagnose_mzm_interleaved_calibration as diag
import mzm_interleaved_truth as it
import validate_mzm_interleaved_calibration as replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", required=True)
    args = parser.parse_args()
    root = Path(args.replay_dir).resolve()
    required = {
        "analysis.json", "checksums.json", "conditioning.csv",
        "formal_windows.csv", "formal_windows.npz",
        "interleaved_calibration.csv", "interleaved_calibration.npz",
        "manifest.json", "pilot_verification.json", "protocol.json",
        "summary.json", "transition_discard.csv", "transition_discard.npz"}
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError(f"missing bundle files: {missing}")
    checksums = json.loads((root / "checksums.json").read_text())
    if set(checksums) != required - {"checksums.json"}:
        raise RuntimeError("bundle checksum file set differs")
    for name, digest in checksums.items():
        if replay._sha256(root / name) != digest:
            raise RuntimeError(f"bundle checksum mismatch for {name}")
    protocol = json.loads((root / "protocol.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    recorded = json.loads((root / "analysis.json").read_text())
    if (protocol.get("protocol_version") != it.PROTOCOL_VERSION or
            protocol.get("segmented_bundle") is not True):
        raise RuntimeError("unsupported bundle protocol")
    if manifest.get("status") != "complete" or manifest.get("failure") is not None:
        raise RuntimeError("bundle manifest is not complete")
    schedule = it.build_schedule()
    schedule_hash = it.schedule_sha256(schedule)
    if (protocol.get("schedule") != it.schedule_records(schedule) or
            protocol.get("schedule_sha256") != schedule_hash or
            protocol.get("target_order") != it.target_order().tolist()):
        raise RuntimeError("bundle frozen schedule differs")

    sources = protocol.get("source_segments")
    if not isinstance(sources, list) or len(sources) != it.SEGMENT_COUNT:
        raise RuntimeError("bundle source segment count differs")
    source_protocols = []
    expected_conditioning = []
    conditioning_offset = 0
    previous_end = None
    for expected_index, source in enumerate(sources):
        if int(source.get("segment_index", -1)) != expected_index:
            raise RuntimeError("bundle source segment order differs")
        segment_root = Path(source["path"]).resolve()
        result = subprocess.run(
            [sys.executable, str(Path(replay.__file__).resolve()),
             "--replay-dir", str(segment_root)], text=True,
            capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"source segment replay rejected: {segment_root}")
        source_checksums = json.loads(
            (segment_root / "checksums.json").read_text())
        if (source.get("checksums") != source_checksums or
                source.get("checksums_sha256") !=
                replay._sha256(segment_root / "checksums.json")):
            raise RuntimeError("source segment digest contract differs")
        segment_protocol = json.loads(
            (segment_root / "protocol.json").read_text())
        source_protocols.append(segment_protocol)
        start, end = it.segment_bounds(expected_index)
        plan = diag._expected_bridges(
            it.schedule_records(schedule)[start:end])
        for row in plan:
            row = dict(row)
            row["sequence_index"] += conditioning_offset
            expected_conditioning.append(row)
        conditioning_offset += len(plan)
        segment_rows = replay._load_npz(
            segment_root / "interleaved_calibration.npz", diag.MAIN_HEADER,
            schedule_hash)
        segment_start = min(float(row["t_acq_start_unix"])
                            for row in segment_rows)
        segment_end = max(float(row["t_acq_end_unix"])
                          for row in segment_rows)
        if previous_end is not None and previous_end >= segment_start:
            raise RuntimeError("source segment acquisition times overlap")
        previous_end = segment_end
    hashes = [value.get("source_sha256") for value in source_protocols]
    if any(value != hashes[0] for value in hashes[1:]) or \
            protocol.get("source_sha256") != hashes[0]:
        raise RuntimeError("bundle source hashes differ")
    metadata_keys = ("device_id", "firmware_rev", "instrument_ids")
    reference = source_protocols[0].get("metadata", {})
    if any(any(value.get("metadata", {}).get(key) != reference.get(key)
               for key in metadata_keys) for value in source_protocols[1:]):
        raise RuntimeError("bundle hardware metadata differ")

    rows = replay._load_npz(
        root / "interleaved_calibration.npz", diag.MAIN_HEADER, schedule_hash)
    windows = replay._load_npz(
        root / "formal_windows.npz", diag.WINDOW_HEADER, schedule_hash)
    discards = replay._load_npz(
        root / "transition_discard.npz", diag.DISCARD_HEADER, schedule_hash)
    conditioning = replay._load_csv(
        root / "conditioning.csv", diag.CONDITIONING_HEADER)
    for filename, header, values in (
            ("interleaved_calibration.csv", diag.MAIN_HEADER, rows),
            ("formal_windows.csv", diag.WINDOW_HEADER, windows),
            ("transition_discard.csv", diag.DISCARD_HEADER, discards)):
        csv_rows = replay._load_csv(root / filename, header)
        replay._check_csv_npz(csv_rows, values, header, filename)
    pilot = json.loads((root / "pilot_verification.json").read_text())
    discard_hashes = {name: replay._sha256(root / name) for name in (
        "transition_discard.csv", "transition_discard.npz")}
    result = diag._analyze(
        rows, windows, discards, conditioning, pilot, discard_hashes,
        expected_conditioning=expected_conditioning)
    replay._assert_equivalent(result, recorded)
    if (recorded.get("transition_discard_file_sha256") != discard_hashes or
            not summary.get("complete") or
            summary.get("analysis") != recorded or
            bool(manifest.get("quality_gate_accepted")) !=
            bool(recorded["quality_gate"]["accepted"])):
        raise RuntimeError("bundle analysis/summary/manifest contract differs")
    if (len(rows), len(windows), len(discards), len(conditioning)) != (
            162, 648, 162, len(expected_conditioning)):
        raise RuntimeError("bundle count contract differs")
    print(json.dumps(dict(
        accepted=result["quality_gate"]["accepted"], rows=len(rows),
        windows=len(windows), discards=len(discards),
        conditioning_rows=len(conditioning),
        target_time_abs_corr=result["target_time_abs_corr"],
        direction_split_phase_rad=result["quality_gate"][
            "direction_split_phase_rad"],
        drift_30min_phase_rad=result["quality_gate"][
            "drift_30min_phase_rad"]), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
