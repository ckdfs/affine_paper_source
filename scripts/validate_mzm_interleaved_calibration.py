#!/usr/bin/env python3
"""Read-only full replay for an MZM interleaved-calibration directory."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

import diagnose_mzm_interleaved_calibration as diag
import mzm_interleaved_truth as it


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native(value):
    return value.item() if isinstance(value, np.generic) else value


def _csv_value_matches(text, value):
    value = _native(value)
    if isinstance(value, bool):
        return text.strip().lower() == str(value).lower()
    if isinstance(value, (int, np.integer)):
        return int(text) == int(value)
    if isinstance(value, (float, np.floating)):
        return np.isclose(float(text), float(value), atol=1e-12, rtol=0)
    return text == str(value)


def _assert_equivalent(lhs, rhs, path="analysis"):
    if isinstance(lhs, dict) and isinstance(rhs, dict):
        if set(lhs) != set(rhs):
            raise RuntimeError(f"{path} keys differ")
        for key in lhs:
            _assert_equivalent(lhs[key], rhs[key], f"{path}.{key}")
        return
    if isinstance(lhs, (list, tuple)) and isinstance(rhs, (list, tuple)):
        if len(lhs) != len(rhs):
            raise RuntimeError(f"{path} length differs")
        for index, (left, right) in enumerate(zip(lhs, rhs)):
            _assert_equivalent(left, right, f"{path}[{index}]")
        return
    if isinstance(lhs, bool) or isinstance(rhs, bool):
        if bool(lhs) != bool(rhs):
            raise RuntimeError(f"{path} differs")
        return
    if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
        if not np.isclose(float(lhs), float(rhs), atol=1e-12, rtol=0):
            raise RuntimeError(f"{path} differs")
        return
    if lhs != rhs:
        raise RuntimeError(f"{path} differs")


def _load_csv(path, header):
    with open(path, newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != header:
            raise RuntimeError(f"CSV schema mismatch for {Path(path).name}")
        return list(reader)


def _load_npz(path, header, schedule_hash):
    with np.load(path, allow_pickle=False) as data:
        keys = [key for key in data.files if key != "schedule_sha256"]
        if keys != header:
            raise RuntimeError(f"NPZ schema mismatch for {Path(path).name}")
        if str(data["schedule_sha256"].item()) != schedule_hash:
            raise RuntimeError(f"NPZ schedule hash mismatch for {Path(path).name}")
        n = len(data[header[0]])
        return [{key: _native(data[key][index]) for key in header}
                for index in range(n)]


def _check_csv_npz(csv_rows, npz_rows, header, label):
    if len(csv_rows) != len(npz_rows):
        raise RuntimeError(f"{label} CSV/NPZ row count mismatch")
    for index, (csv_row, npz_row) in enumerate(zip(csv_rows, npz_rows)):
        if any(not _csv_value_matches(csv_row[key], npz_row[key])
               for key in header):
            raise RuntimeError(f"{label} CSV/NPZ mismatch at row {index}")


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
        raise RuntimeError(f"missing replay files: {missing}")
    checksums = json.loads((root / "checksums.json").read_text())
    if set(checksums) != required - {"checksums.json"}:
        raise RuntimeError("checksums.json file set differs from frozen contract")
    for name, expected in checksums.items():
        if _sha256(root / name) != expected:
            raise RuntimeError(f"checksum mismatch for {name}")

    protocol = json.loads((root / "protocol.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    recorded = json.loads((root / "analysis.json").read_text())
    pilot_verification = json.loads(
        (root / "pilot_verification.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("failure") is not None:
        raise RuntimeError("replay requires a complete, non-failed directory")
    if protocol.get("protocol_version") != it.PROTOCOL_VERSION:
        raise RuntimeError("unsupported protocol version")
    schedule = it.build_schedule()
    if protocol.get("schedule") != it.schedule_records(schedule):
        raise RuntimeError("protocol schedule differs from frozen implementation")
    schedule_hash = it.schedule_sha256(schedule)
    if protocol.get("schedule_sha256") != schedule_hash:
        raise RuntimeError("protocol schedule hash mismatch")
    if protocol.get("target_order") != it.target_order().tolist():
        raise RuntimeError("protocol target order mismatch")
    segmented = bool(protocol.get("segmented", False))
    segment_index = protocol.get("segment_index")
    if segmented:
        start, end = it.segment_bounds(segment_index)
        segment_records = it.schedule_records(schedule)[start:end]
        if (int(protocol.get("segment_start", -1)) != start or
                int(protocol.get("segment_end", -1)) != end or
                protocol.get("segment_schedule") != segment_records):
            raise RuntimeError("protocol segment schedule mismatch")
    else:
        start, end = 0, len(schedule["bias"])
        segment_records = it.schedule_records(schedule)
    expected_bridge_records = diag._expected_bridges(segment_records)
    if int(protocol.get("expected_bridge_rows", -1)) != len(
            expected_bridge_records):
        raise RuntimeError("protocol bridge count mismatch")
    source_paths = {
        "diagnose_mzm_interleaved_calibration.py": Path(diag.__file__).resolve(),
        "mzm_interleaved_truth.py": Path(diag.it.__file__).resolve(),
        "mzm_time_truth.py": Path(diag.tt.__file__).resolve(),
        "measure_bench.py": Path(diag.mb.__file__).resolve(),
        "exp_common.py": Path(diag.ec.__file__).resolve(),
        "mzm_interleaved_calibration_protocol.md": (
            Path(diag.ec.REPO) / "reviews" /
            "mzm_interleaved_calibration_protocol.md"),
        "analyze_mzm_interleaved_segments.py": (
            Path(diag.ec.REPO) / "scripts" /
            "analyze_mzm_interleaved_segments.py"),
        "validate_mzm_interleaved_bundle.py": (
            Path(diag.ec.REPO) / "scripts" /
            "validate_mzm_interleaved_bundle.py"),
    }
    if set(protocol.get("source_sha256", {})) != set(source_paths):
        raise RuntimeError("source hash file set differs")
    for name, path in source_paths.items():
        if protocol["source_sha256"][name] != _sha256(path):
            raise RuntimeError(f"source hash mismatch for {name}")

    main_csv = _load_csv(root / "interleaved_calibration.csv", diag.MAIN_HEADER)
    window_csv = _load_csv(root / "formal_windows.csv", diag.WINDOW_HEADER)
    discard_csv = _load_csv(root / "transition_discard.csv", diag.DISCARD_HEADER)
    conditioning_rows = _load_csv(
        root / "conditioning.csv", diag.CONDITIONING_HEADER)
    rows = _load_npz(
        root / "interleaved_calibration.npz", diag.MAIN_HEADER, schedule_hash)
    windows = _load_npz(
        root / "formal_windows.npz", diag.WINDOW_HEADER, schedule_hash)
    discards = _load_npz(
        root / "transition_discard.npz", diag.DISCARD_HEADER, schedule_hash)
    _check_csv_npz(main_csv, rows, diag.MAIN_HEADER, "main")
    _check_csv_npz(window_csv, windows, diag.WINDOW_HEADER, "window")
    _check_csv_npz(discard_csv, discards, diag.DISCARD_HEADER, "discard")

    discard_hashes = {name: _sha256(root / name) for name in (
        "transition_discard.csv", "transition_discard.npz")}
    if (recorded.get("transition_discard_file_sha256") != discard_hashes or
            any(checksums[name] != digest
                for name, digest in discard_hashes.items())):
        raise RuntimeError("discard file digest three-way contract failed")
    if segmented:
        replay = diag._analyze_segment(
            rows, windows, discards, conditioning_rows,
            pilot_verification, discard_hashes, segment_index)
    else:
        replay = diag._analyze(
            rows, windows, discards, conditioning_rows,
            pilot_verification, discard_hashes)
    _assert_equivalent(replay, recorded)

    expected = end - start
    expected_windows = expected * it.N_AVG
    expected_bridges = len(expected_bridge_records)
    if (not summary.get("complete") or
            int(summary.get("conditioning_rows", -1)) != expected_bridges or
            int(summary.get("expected_conditioning_rows", -1)) != expected_bridges or
            int(summary.get("acquired_observations", -1)) != expected or
            int(summary.get("expected_observations", -1)) != expected or
            int(summary.get("acquired_windows", -1)) != expected_windows or
            int(summary.get("expected_windows", -1)) != expected_windows or
            int(summary.get("acquired_discards", -1)) != expected or
            int(summary.get("expected_discards", -1)) != expected):
        raise RuntimeError("summary count contract failed")
    _assert_equivalent(summary.get("analysis"), recorded, "summary.analysis")
    for name, value in (
            ("conditioning_rows", expected_bridges),
            ("acquired_observations", expected),
            ("expected_observations", expected),
            ("acquired_windows", expected_windows),
            ("expected_windows", expected_windows),
            ("acquired_discards", expected),
            ("expected_discards", expected)):
        if int(manifest.get(name, -1)) != value:
            raise RuntimeError(f"manifest {name} mismatch")
    if bool(manifest.get("quality_gate_accepted")) != bool(
            recorded["quality_gate"]["accepted"]):
        raise RuntimeError("manifest quality decision mismatch")
    initial = manifest.get("board_initial_status") or {}
    final = manifest.get("board_final_status") or {}
    if protocol.get("simulated"):
        if initial.get("State") != "SIM" or final.get("State") != "SIM":
            raise RuntimeError("sim initial/final status contract failed")
    else:
        def safe(status):
            try:
                bias = float(str(status.get("Bias", "")).split()[0])
            except (TypeError, ValueError, IndexError):
                return False
            return bool(
                str(status.get("State", "")).upper() == "IDLE" and
                abs(bias) <= 5e-4 and
                str(status.get("Lock", "")).upper() == "NO" and
                str(status.get("Cal", "")).upper() == "INVALID")
        if not safe(initial) or not safe(final):
            raise RuntimeError("real initial/final safe-state contract failed")
    report = dict(
        accepted=replay["quality_gate"]["accepted"], rows=len(rows),
        windows=len(windows), discards=len(discards),
        conditioning_rows=len(conditioning_rows),
        checksums_verified=len(checksums),
        formal_max_abs_raw_V=replay["formal_max_abs_raw_V"])
    if segmented:
        report.update(segment_index=int(segment_index),
                      segment_start=start, segment_end=end)
    else:
        report.update(
            direction_split_phase_rad=replay["quality_gate"][
                "direction_split_phase_rad"],
            drift_30min_phase_rad=replay["quality_gate"][
                "drift_30min_phase_rad"],
            target_time_abs_corr=replay["target_time_abs_corr"])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
