#!/usr/bin/env python3
"""Read-only file-contract replay for an MZM CH0 dynamic-range directory."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

import diagnose_mzm_ch0_dynamic_range as dr


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
    if isinstance(lhs, list) and isinstance(rhs, list):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", required=True)
    args = parser.parse_args()
    root = Path(args.replay_dir).resolve()
    required = {
        "analysis.json", "checksums.json", "ch0_dynamic_range.csv",
        "ch0_dynamic_range.npz", "manifest.json", "protocol.json",
        "pilot_verification.json", "startup_discard.csv",
        "startup_discard.npz", "summary.json"}
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError(f"missing replay files: {missing}")

    checksums = json.loads((root / "checksums.json").read_text())
    if set(checksums) != required - {"checksums.json"}:
        raise RuntimeError("checksums.json file set differs from frozen contract")
    for filename, expected in checksums.items():
        actual = _sha256(root / filename)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch for {filename}")
    manifest = json.loads((root / "manifest.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    recorded = json.loads((root / "analysis.json").read_text())
    pilot_verification = json.loads(
        (root / "pilot_verification.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("failure") is not None:
        raise RuntimeError("replay requires a complete, non-failed directory")
    if protocol.get("protocol_version") != dr.PROTOCOL_VERSION:
        raise RuntimeError("unsupported protocol version")
    expected_schedule = dr._schedule()
    if protocol.get("schedule") != expected_schedule:
        raise RuntimeError("protocol schedule differs from frozen implementation")
    if protocol.get("schedule_sha256") != dr._schedule_sha256(expected_schedule):
        raise RuntimeError("schedule hash mismatch")
    if (int(protocol.get("startup_discard_expected", -1)) != 115 or
            int(protocol.get("startup_discard_blocks", -1)) != dr.N_BLOCKS or
            not np.isclose(float(protocol.get("bias_settle_s", np.nan)),
                           dr.BIAS_SETTLE_S, atol=0, rtol=0)):
        raise RuntimeError("protocol constants differ from frozen implementation")
    source_paths = {
        "diagnose_mzm_ch0_dynamic_range.py": Path(dr.__file__).resolve(),
        "measure_bench.py": Path(dr.mb.__file__).resolve(),
        "mzm_time_truth.py": Path(dr.tt.__file__).resolve(),
        "exp_common.py": Path(dr.ec.__file__).resolve(),
        "mzm_ch0_dynamic_range_protocol.md": (
            Path(dr.ec.REPO) / "reviews" / "mzm_ch0_dynamic_range_protocol.md"),
    }
    if set(protocol.get("source_sha256", {})) != set(source_paths):
        raise RuntimeError("source hash file set differs")
    for name, path in source_paths.items():
        if protocol["source_sha256"][name] != _sha256(path):
            raise RuntimeError(f"source hash mismatch for {name}")

    with open(root / "ch0_dynamic_range.csv", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != dr.MAIN_HEADER:
            raise RuntimeError("main CSV schema mismatch")
        csv_rows = list(reader)
    if len(csv_rows) != len(expected_schedule):
        raise RuntimeError("CSV row count mismatch")
    with np.load(root / "ch0_dynamic_range.npz", allow_pickle=False) as npz:
        keys = [key for key in npz.files if key != "schedule_sha256"]
        if keys != dr.MAIN_HEADER:
            raise RuntimeError("main NPZ schema mismatch")
        if str(npz["schedule_sha256"].item()) != protocol["schedule_sha256"]:
            raise RuntimeError("NPZ schedule hash mismatch")
        rows = [
            {key: _native(npz[key][index]) for key in keys}
            for index in range(len(expected_schedule))]
    with open(root / "startup_discard.csv", newline="",
              encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != dr.STARTUP_HEADER:
            raise RuntimeError("startup CSV schema mismatch")
        startup_csv_rows = list(reader)
    with np.load(root / "startup_discard.npz", allow_pickle=False) as npz:
        startup_keys = [key for key in npz.files if key != "schedule_sha256"]
        if startup_keys != dr.STARTUP_HEADER:
            raise RuntimeError("startup NPZ schema mismatch")
        if str(npz["schedule_sha256"].item()) != protocol["schedule_sha256"]:
            raise RuntimeError("startup NPZ schedule hash mismatch")
        startup_rows = [
            {key: _native(npz[key][index]) for key in startup_keys}
            for index in range(len(npz[startup_keys[0]]))]
    if len(startup_rows) != len(startup_csv_rows):
        raise RuntimeError("startup CSV/NPZ row count mismatch")
    for index, (row, csv_row) in enumerate(zip(startup_rows, startup_csv_rows)):
        if any(not _csv_value_matches(csv_row[key], row[key])
               for key in dr.STARTUP_HEADER):
            raise RuntimeError(f"startup CSV/NPZ mismatch at row {index}")
    for index, (item, row, csv_row) in enumerate(zip(expected_schedule, rows, csv_rows)):
        if (str(row["role"]) != item["role"] or
                int(row["grid_index"]) != item["grid_index"] or
                int(row["sequence_index"]) != item["sequence_index"] or
                int(row["candidate_order_index"]) !=
                item["candidate_order_index"] or
                not np.isclose(float(row["bias"]), item["bias_V"], atol=0, rtol=0) or
                not np.isclose(float(row["pilot_V"]), item["pilot_V"], atol=0, rtol=0)):
            raise RuntimeError(f"NPZ schedule mismatch at row {index}")
        if any(not _csv_value_matches(csv_row[key], row[key])
               for key in dr.MAIN_HEADER):
            raise RuntimeError(f"CSV/NPZ mismatch at row {index}")

    startup_file_sha256 = {
        name: _sha256(root / name) for name in (
            "startup_discard.csv", "startup_discard.npz")}
    if (recorded.get("startup_discard_file_sha256") != startup_file_sha256 or
            any(checksums[name] != digest
                for name, digest in startup_file_sha256.items())):
        raise RuntimeError("startup file digest three-way contract failed")
    replay = dr._analyze(
        rows, pilot_verification, startup_rows, startup_file_sha256)
    _assert_equivalent(replay, recorded)
    summary = json.loads((root / "summary.json").read_text())
    if (not summary.get("complete") or
            int(summary.get("acquired_rows", -1)) != len(rows) or
            int(summary.get("expected_rows", -1)) != len(expected_schedule) or
            int(summary.get("acquired_startup_discards", -1)) != len(startup_rows) or
            int(summary.get("expected_startup_discards", -1)) != 115):
        raise RuntimeError("summary count contract failed")
    _assert_equivalent(summary.get("analysis"), recorded, "summary.analysis")
    if (int(manifest.get("acquired_rows", -1)) != len(rows) or
            int(manifest.get("expected_rows", -1)) != len(expected_schedule) or
            int(manifest.get("acquired_startup_discards", -1)) != len(startup_rows) or
            int(manifest.get("expected_startup_discards", -1)) != 115 or
            bool(manifest.get("quality_gate_accepted")) != bool(recorded["accepted"])):
        raise RuntimeError("manifest count/decision contract failed")
    final = manifest.get("board_final_status") or {}
    if protocol.get("simulated"):
        if final.get("State") != "SIM":
            raise RuntimeError("sim final status contract failed")
    elif (str(final.get("State", "")).upper() != "IDLE" or
          not str(final.get("Bias", "")).strip().startswith("0.000") or
          str(final.get("Lock", "")).upper() != "NO" or
          str(final.get("Cal", "")).upper() != "INVALID"):
        raise RuntimeError("real final safe-state contract failed")
    print(json.dumps(dict(
        accepted=replay["accepted"],
        selected_pilot_V=replay["selected_pilot_V"],
        rows=len(rows), checksums_verified=len(checksums),
        startup_discard_records=len(startup_rows),
        startup_discard_contract_pass=replay["startup_discard_contract_pass"],
        startup_discard_capture_pass=replay["startup_discard_capture_pass"],
        candidates={key: dict(
            accepted=value["accepted"],
            max_abs_raw_V=value["max_abs_raw_V"],
            kappa=value["ellipse"]["kappa"])
            for key, value in replay["candidates"].items()}),
        ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
