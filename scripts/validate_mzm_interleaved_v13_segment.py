#!/usr/bin/env python3
"""Read-only full replay for one MZM interleaved-v1.3 segment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import mzm_interleaved_v13_contract as contract
import mzm_interleaved_v13_truth as v13
import validate_mzm_interleaved_calibration as legacy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", required=True)
    args = parser.parse_args()
    root = Path(args.replay_dir).resolve()
    required = {
        "acq_read_failures.json", "analysis.json", "checksums.json",
        "conditioning.csv", "dmm_reads.csv", "dmm_reads.npz",
        "formal_windows.csv", "formal_windows.npz",
        "interleaved_calibration.csv", "interleaved_calibration.npz",
        "manifest.json", "pilot_verification.json", "protocol.json",
        "summary.json", "transition_discard.csv", "transition_discard.npz"}
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError(f"missing v1.3 segment files: {missing}")
    checksums = json.loads((root / "checksums.json").read_text())
    if set(checksums) != required - {"checksums.json"}:
        raise RuntimeError("v1.3 segment checksum file set differs")
    for name, digest in checksums.items():
        if legacy._sha256(root / name) != digest:
            raise RuntimeError(f"v1.3 segment checksum mismatch: {name}")
    protocol = json.loads((root / "protocol.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    recorded = json.loads((root / "analysis.json").read_text())
    stage = protocol.get("stage")
    expected_version = (v13.DONOR_PROTOCOL_VERSION if stage == "donor"
                        else v13.PROTOCOL_VERSION)
    if protocol.get("protocol_version") != expected_version:
        raise RuntimeError("v1.3 segment protocol/stage differs")
    segment = int(protocol.get("segment_index", -1))
    if segment not in range(3):
        raise RuntimeError("v1.3 segment index differs")
    if manifest.get("status") != "complete" or manifest.get("failure") is not None:
        raise RuntimeError("v1.3 segment manifest is not complete")
    schedule = v13.build_schedule()
    start, end = v13.segment_bounds(segment)
    if (protocol.get("schedule_sha256") != v13.schedule_sha256(schedule) or
            protocol.get("schedule") != v13.schedule_records(schedule) or
            protocol.get("segment_schedule") !=
            v13.schedule_records(schedule)[start:end]):
        raise RuntimeError("v1.3 segment frozen schedule differs")
    source_hashes = protocol.get("source_sha256", {})
    repo = Path(__file__).resolve().parents[1]
    source_files = {
        "diagnose_mzm_interleaved_v13.py": Path(__file__).with_name(
            "diagnose_mzm_interleaved_v13.py"),
        "mzm_interleaved_v13_truth.py": Path(v13.__file__).resolve(),
        "mzm_interleaved_v13_contract.py": Path(contract.__file__).resolve(),
        "mzm_interleaved_truth.py": Path(__file__).with_name(
            "mzm_interleaved_truth.py"),
        "mzm_time_truth.py": Path(__file__).with_name("mzm_time_truth.py"),
        "measure_bench.py": Path(__file__).with_name("measure_bench.py"),
        "exp_common.py": Path(__file__).with_name("exp_common.py"),
        "validate_mzm_interleaved_v13_segment.py": Path(__file__).resolve(),
        "analyze_mzm_interleaved_v13_segments.py": Path(__file__).with_name(
            "analyze_mzm_interleaved_v13_segments.py"),
        "validate_mzm_interleaved_v13_bundle.py": Path(__file__).with_name(
            "validate_mzm_interleaved_v13_bundle.py"),
        "protocol.md": repo / "reviews" /
            "mzm_interleaved_calibration_protocol_v1.3.md",
    }
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(source_files):
        raise RuntimeError("v1.3 segment frozen source file set differs")
    for name, path in source_files.items():
        if legacy._sha256(path) != source_hashes[name]:
            raise RuntimeError(f"v1.3 segment source hash differs: {name}")
    schedule_hash = v13.schedule_sha256(schedule)
    rows = legacy._load_npz(
        root / "interleaved_calibration.npz", contract.MAIN_HEADER,
        schedule_hash)
    windows = legacy._load_npz(
        root / "formal_windows.npz", contract.WINDOW_HEADER, schedule_hash)
    discards = legacy._load_npz(
        root / "transition_discard.npz", contract.DISCARD_HEADER, schedule_hash)
    dmm_reads = legacy._load_npz(
        root / "dmm_reads.npz", contract.DMM_HEADER, schedule_hash)
    conditioning = legacy._load_csv(
        root / "conditioning.csv", contract.CONDITIONING_HEADER)
    for filename, header, values in (
            ("interleaved_calibration.csv", contract.MAIN_HEADER, rows),
            ("formal_windows.csv", contract.WINDOW_HEADER, windows),
            ("transition_discard.csv", contract.DISCARD_HEADER, discards),
            ("dmm_reads.csv", contract.DMM_HEADER, dmm_reads)):
        csv_rows = legacy._load_csv(root / filename, header)
        legacy._check_csv_npz(csv_rows, values, header, filename)
    pilot = json.loads((root / "pilot_verification.json").read_text())
    failures = json.loads((root / "acq_read_failures.json").read_text())
    result = contract.analyze_segment(
        stage, segment, rows, windows, discards, conditioning, dmm_reads,
        pilot, failures)
    legacy._assert_equivalent(result, recorded)
    if (not summary.get("complete") or summary.get("analysis") != recorded or
            bool(manifest.get("quality_gate_accepted")) !=
            bool(recorded["quality_gate"]["accepted"])):
        raise RuntimeError("v1.3 segment summary/manifest contract differs")
    if not protocol.get("simulated", False):
        final = manifest.get("board_final_status", {})
        if (str(final.get("State", "")).upper() != "IDLE" or
                not str(final.get("Bias", "")).startswith("0.000") or
                str(final.get("Lock", "NO")).upper() != "NO" or
                str(final.get("Cal", "INVALID")).upper() != "INVALID"):
            raise RuntimeError("v1.3 segment final hardware state is unsafe")
    print(json.dumps(dict(
        accepted=result["quality_gate"]["accepted"], stage=stage,
        segment_index=segment, observations=len(rows), windows=len(windows),
        discards=len(discards), dmm_reads=len(dmm_reads),
        read_failures=len(failures),
        formal_max_abs_raw_V=result["formal_max_abs_raw_V"]),
        indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
