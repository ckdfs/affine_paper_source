#!/usr/bin/env python3
"""Hardware-free validation and historical replay for MZM time truth.

This command has no instrument path.  It either runs deterministic synthetic
contract tests or replays existing files read-only.  Optional JSON output is
restricted to ``build/`` so validation can never alter experimental evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os

import numpy as np

import exp_common as ec
import measure_bench as mb
import mzm_time_truth as tt


RAWADC_NAMES = (
    "version", "scope", "expected", "used", "read_fail", "blocks",
    "complete", "timeout", "gain", "fs_uv", "guard", "crc", "ch0_min",
    "ch0_max", "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo",
    "ch0_guard_hi", "windows",
)


def _summary(result, source, protocol, observer_mapping_stability=None):
    fit = result["fit"]
    return dict(
        source=source,
        protocol=protocol,
        accepted=bool(result["quality_gate"]["accepted"]),
        quality_gate=result["quality_gate"],
        parameters=fit["parameters"],
        optimizer=fit["optimizer"],
        time_midpoint_unix=float(fit["time_midpoint_unix"]),
        time_scale_s=float(fit["time_scale_s"]),
        formal_points=int(np.count_nonzero(fit["formal_mask"])),
        sentinel_points=int(np.count_nonzero(fit["sentinel_mask"])),
        selfcheck=result["selfcheck"],
        observer_mapping_stability=observer_mapping_stability,
        limitations=[
            "DMM truth shares the controlled optical branch and is not an "
            "independent optical validation channel",
            "historical dense-sweep replay validates only the DC time/direction "
            "model, not the frozen 16-block n_avg=4 ellipse contract",
        ],
    )


def _replay_dense(path):
    with open(path, newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream)
                if row.get("kind") == "formal"]
    required = {"direction", "index", "bias", "timestamp_unix", "dc_dmm",
                "dc_board"}
    if not rows or not required.issubset(rows[0]):
        missing = sorted(required - (set(rows[0]) if rows else set()))
        raise ValueError(f"dense replay is empty or missing fields: {missing}")
    grid_index = np.asarray([int(row["index"]) for row in rows], int)
    role = np.where(grid_index % tt.SENTINEL_MODULUS == 0,
                    "sentinel", "formal")
    result = tt.analyze_time_truth(
        time_unix=np.asarray([float(row["timestamp_unix"]) for row in rows]),
        bias=np.asarray([float(row["bias"]) for row in rows]),
        dc=np.asarray([float(row["dc_dmm"]) for row in rows]),
        role=role,
        direction=np.asarray([row["direction"] for row in rows]),
        sequence_index=np.arange(len(rows), dtype=int),
        dc_board=np.asarray([float(row["dc_board"]) for row in rows]),
    )
    return _summary(
        result, os.path.abspath(path),
        "historical-dense-replay-with-v1.1-analysis")


def _replay_calib(path):
    path = os.path.abspath(path)
    root = os.path.dirname(path)
    filename = os.path.basename(path)
    metadata_paths = {
        name: os.path.join(root, name)
        for name in ("checksums.json", "protocol.json", "manifest.json")}
    missing_metadata = [name for name, value in metadata_paths.items()
                        if not os.path.isfile(value)]
    if missing_metadata:
        raise ValueError("calibration replay requires sibling " +
                         ", ".join(missing_metadata))
    with open(metadata_paths["checksums.json"], encoding="utf-8") as stream:
        checksums = json.load(stream)
    if filename not in checksums:
        raise ValueError(f"checksums.json does not cover {filename}")
    for checked_name, expected in checksums.items():
        checked_path = os.path.join(root, checked_name)
        if not os.path.isfile(checked_path):
            raise ValueError(f"checksummed file is missing: {checked_name}")
        digest = hashlib.sha256()
        with open(checked_path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch for {checked_name}")
    with open(metadata_paths["protocol.json"], encoding="utf-8") as stream:
        protocol = json.load(stream)
    with open(metadata_paths["manifest.json"], encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("status") != "complete":
        raise ValueError("calibration replay requires manifest.status=complete")
    protocol_version = protocol.get("protocol_version")
    supported_versions = {
        "mzm-time-resolved-calibration-v1.0",
        "mzm-time-resolved-calibration-v1.1",
        "mzm-time-resolved-calibration-v1.2",
        "mzm-time-resolved-calibration-v1.3",
    }
    if protocol_version not in supported_versions:
        raise ValueError("calibration replay protocol version mismatch")
    frozen_hash = tt.schedule_sha256()
    if protocol.get("schedule_sha256") != frozen_hash:
        raise ValueError("protocol schedule SHA-256 does not match frozen ABA schedule")
    if protocol.get("schedule") != tt.schedule_records():
        raise ValueError("protocol schedule content does not match frozen ABA schedule")

    with np.load(path, allow_pickle=False) as data:
        required = {
            "bias", "dc_dmm", "dc_board", "sequence_index",
            "schedule_sequence_index", "role", "leg", "grid_index",
            "I1", "Q1", "I2", "Q2", "X", "Y", "comps",
            "schedule_sha256",
        }
        if protocol_version == "mzm-time-resolved-calibration-v1.3":
            required.update(f"rawadc_{name}" for name in RAWADC_NAMES)
        missing = sorted(required - set(data.files))
        time_key = ("t_mid_unix" if "t_mid_unix" in data.files else
                    "timestamp_unix" if "timestamp_unix" in data.files else None)
        direction_key = ("direction" if "direction" in data.files else
                         "sweep_direction" if "sweep_direction" in data.files else None)
        if time_key is None:
            missing.append("t_mid_unix/timestamp_unix")
        if direction_key is None:
            missing.append("direction/sweep_direction")
        if missing:
            raise ValueError(
                "calibration is not eligible for time-truth replay; missing "
                + ", ".join(missing))
        stored_hash = str(np.asarray(data["schedule_sha256"]).item()) if (
            "schedule_sha256" in data.files) else None
        if stored_hash != frozen_hash:
            raise ValueError("NPZ schedule SHA-256 does not match frozen ABA schedule")
        frozen = tt.build_aba_schedule()
        schedule_sequence = (data["schedule_sequence_index"]
                             if "schedule_sequence_index" in data.files else
                             data["sequence_index"])
        comparisons = {
            "role": np.array_equal(data["role"].astype("U16"), frozen["role"]),
            "direction": np.array_equal(
                data[direction_key].astype("U16"), frozen["direction"]),
            "bias": np.array_equal(np.asarray(data["bias"], float), frozen["bias"]),
            "sequence": np.array_equal(
                np.asarray(schedule_sequence, int), frozen["sequence_index"]),
        }
        for optional in ("leg", "grid_index"):
            if optional in data.files:
                comparisons[optional] = np.array_equal(
                    np.asarray(data[optional], int), frozen[optional])
        failed = sorted(name for name, passed in comparisons.items() if not passed)
        if failed:
            raise ValueError("recorded calibration differs from frozen schedule: " +
                             ", ".join(failed))
        formal = data["role"].astype("U16") == "formal"
        chosen = (
            "I" if np.var(data["I2"][formal]) >= np.var(data["Q2"][formal]) else "Q",
            "I" if np.var(data["I1"][formal]) >= np.var(data["Q1"][formal]) else "Q",
        )
        stored_comps = tuple(data["comps"].astype("U4").tolist())
        if stored_comps != chosen:
            raise ValueError("stored components do not match formal-only selection")
        expected_x = data["I2"] if chosen[0] == "I" else data["Q2"]
        expected_y = data["I1"] if chosen[1] == "I" else data["Q1"]
        if not np.array_equal(data["X"], expected_x) or not np.array_equal(
                data["Y"], expected_y):
            raise ValueError("stored X/Y do not match raw I/Q and selected components")
        kwargs = dict(
            time_unix=data[time_key], bias=data["bias"],
            dc=data["dc_dmm"], role=data["role"],
            direction=data[direction_key],
            sequence_index=data["sequence_index"],
        )
        kwargs.update(X=data["X"], Y=data["Y"], dc_board=data["dc_board"])
        result = tt.analyze_time_truth(**kwargs)
        mapping = tt.analyze_direction_mapping_stability(
            data["X"], data["Y"], result["fit"]["phase_truth"],
            data["role"], data["leg"], data[direction_key])
        if protocol_version in {
                "mzm-time-resolved-calibration-v1.2",
                "mzm-time-resolved-calibration-v1.3"}:
            result = tt.require_observer_mapping_stability(result, mapping)
        if protocol_version == "mzm-time-resolved-calibration-v1.3":
            csv_path = os.path.join(root, "time_calibration.csv")
            if not os.path.isfile(csv_path):
                raise ValueError("v1.3 replay requires sibling time_calibration.csv")
            with open(csv_path, newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            expected_rows = int(protocol.get("conditioning_points", -1)) + len(
                frozen["bias"])
            if len(rows) != expected_rows:
                raise ValueError(
                    f"v1.3 raw CSV row count {len(rows)} does not match {expected_rows}")
            raw_fields = {}
            raw_bool_names = {"complete", "timeout", "crc"}

            def parse_raw_value(name, value):
                if name in raw_bool_names:
                    lowered = str(value).strip().lower()
                    if lowered not in {"0", "1", "false", "true"}:
                        raise ValueError(f"invalid boolean {name}={value!r}")
                    return int(lowered in {"1", "true"})
                return int(value)

            for name in RAWADC_NAMES:
                column = f"rawadc_{name}"
                if not rows or column not in rows[0]:
                    raise ValueError(f"v1.3 raw CSV missing {column}")
                if name == "scope":
                    raw_fields[name] = np.asarray([row[column] for row in rows])
                else:
                    raw_fields[name] = np.asarray(
                        [parse_raw_value(name, row[column]) for row in rows])
            formal_csv = [row for row in rows if row["role"] != "conditioning"]
            if len(formal_csv) != len(data["bias"]):
                raise ValueError("v1.3 raw CSV formal row count mismatch")
            for name in RAWADC_NAMES:
                column = f"rawadc_{name}"
                expected_values = np.asarray(
                    [row[column] for row in formal_csv] if name == "scope" else
                    [parse_raw_value(name, row[column]) for row in formal_csv])
                stored_values = np.asarray(data[column])
                if not np.array_equal(stored_values.astype(expected_values.dtype),
                                      expected_values):
                    raise ValueError(f"NPZ/CSV mismatch for {column}")
            rawadc = tt.analyze_adc_raw_telemetry(**raw_fields)
            result = tt.require_adc_raw_telemetry(result, rawadc)
    return _summary(
        result, os.path.abspath(path), protocol_version,
        observer_mapping_stability=mapping)


def _write_output(path, payload):
    build = os.path.realpath(os.path.join(ec.REPO, "build"))
    output = os.path.realpath(path)
    if not output.startswith(build + os.sep):
        raise ValueError("validation output must be inside build/")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--replay-dense", metavar="CSV")
    mode.add_argument("--replay-calib", metavar="NPZ")
    parser.add_argument("--output", help="optional JSON path below build/")
    args = parser.parse_args()

    if args.self_test:
        payload = dict(source="deterministic_self_test", **tt.self_test())
        payload["rawadc_parser"] = mb.self_test_rawadc_parser()
    elif args.simulate:
        schedule = tt.build_aba_schedule()
        result = tt.analyze_time_truth(**tt._synthetic_record(schedule))
        payload = _summary(
            result, "deterministic_synthetic_ABA",
            "deterministic-synthetic-time-truth")
        payload["target_balance"] = {
            key: (value.tolist() if isinstance(value, np.ndarray) else value)
            for key, value in tt.balanced_target_orders().items()
        }
    elif args.replay_dense:
        payload = _replay_dense(args.replay_dense)
    else:
        payload = _replay_calib(args.replay_calib)

    if args.output:
        _write_output(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
