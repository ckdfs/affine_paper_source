#!/usr/bin/env python3
"""Aggregate three MZM interleaved-v1.3.1 donor or recipient segments."""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import diagnose_mzm_interleaved_v131 as acquire
import exp_common as ec
import measure_bench as mb
import mzm_interleaved_v131_contract as contract
import mzm_interleaved_v131_truth as v13
import mzm_time_truth as tt
import validate_mzm_interleaved_calibration as legacy


def _native(value):
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _load_segment(root):
    root = Path(root).resolve()
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(
            "validate_mzm_interleaved_v131_segment.py")),
         "--replay-dir", str(root)], text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"v1.3.1 source segment replay failed: {root}\n{result.stderr}")
    protocol = json.loads((root / "protocol.json").read_text())
    analysis = json.loads((root / "analysis.json").read_text())
    checksums = json.loads((root / "checksums.json").read_text())
    schedule_hash = v13.schedule_sha256()
    return dict(
        root=root, protocol=protocol, analysis=analysis, checksums=checksums,
        rows=legacy._load_npz(root / "interleaved_calibration.npz",
                              contract.MAIN_HEADER, schedule_hash),
        windows=legacy._load_npz(root / "formal_windows.npz",
                                 contract.WINDOW_HEADER, schedule_hash),
        discards=legacy._load_npz(root / "transition_discard.npz",
                                  contract.DISCARD_HEADER, schedule_hash),
        dmm=legacy._load_npz(root / "dmm_reads.npz", contract.DMM_HEADER,
                             schedule_hash),
        conditioning=legacy._load_csv(root / "conditioning.csv",
                                      contract.CONDITIONING_HEADER),
        pilot=json.loads((root / "pilot_verification.json").read_text()),
        failures=json.loads((root / "acq_read_failures.json").read_text()))


def _combine(segments):
    rows, windows, discards, dmm, conditioning, failures = [], [], [], [], [], []
    pilot = {}
    for segment in segments:
        discard_offset = len(discards)
        window_offset = len(windows)
        dmm_offset = len(dmm)
        conditioning_offset = len(conditioning)
        for value in segment["rows"]:
            value = dict(value)
            value["transition_discard_index"] = int(
                value["transition_discard_index"]) + discard_offset
            rows.append(value)
        for value in segment["windows"]:
            value = dict(value)
            value["window_sequence_index"] = int(
                value["window_sequence_index"]) + window_offset
            windows.append(value)
        for value in segment["discards"]:
            value = dict(value)
            value["transition_discard_index"] = int(
                value["transition_discard_index"]) + discard_offset
            discards.append(value)
        for value in segment["dmm"]:
            value = dict(value)
            value["dmm_sequence_index"] = int(value["dmm_sequence_index"]) + dmm_offset
            dmm.append(value)
        for value in segment["conditioning"]:
            value = dict(value)
            value["sequence_index"] = int(value["sequence_index"]) + conditioning_offset
            conditioning.append(value)
        failures.extend(segment["failures"])
        overlap = set(pilot) & set(segment["pilot"])
        if overlap:
            raise RuntimeError(f"duplicate pilot verification keys: {sorted(overlap)}")
        pilot.update(segment["pilot"])
    return dict(rows=rows, windows=windows, discards=discards, dmm=dmm,
                conditioning=conditioning, failures=failures, pilot=pilot)


def _write_csv_npz(root, name, rows, header):
    csv_path = root / f"{name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows([[row[field] for field in header] for row in rows])
    tmp = root / f"{name}.tmp.npz"
    np.savez(tmp, **{field: np.asarray([row[field] for row in rows])
                    for field in header}, schedule_sha256=v13.schedule_sha256())
    os.replace(tmp, root / f"{name}.npz")


def _table_json(table):
    return {name: (value.tolist() if isinstance(value, np.ndarray) else value)
            for name, value in table.items()}


def _global_common(rows, time_truth):
    fields = {name: np.asarray([row[name] for row in rows])
              for name in contract.MAIN_HEADER}
    formal = fields["role"].astype("U16") == "formal"
    target_time_abs_corr = float(abs(np.corrcoef(
        fields["t_acq_mid_unix"][formal].astype(float),
        fields["bias"][formal].astype(float))[0, 1]))
    prepost = np.abs(fields["dc_dmm_post"].astype(float) -
                     fields["dc_dmm_pre"].astype(float))
    amplitude = np.asarray(time_truth["fit"]["b"], float)
    normalized = prepost / np.maximum(amplitude, np.finfo(float).eps)
    return dict(
        target_time_abs_corr=target_time_abs_corr,
        target_time_corr_pass=bool(target_time_abs_corr <= tt.DESIGN_CORR_LIMIT),
        dmm_bracket_median=float(np.median(normalized)),
        dmm_bracket_p95=float(np.percentile(normalized, 95)),
        dmm_bracket_max=float(np.max(normalized)),
        dmm_bracket_stability_pass=bool(
            np.max(normalized) <= tt.DC_NORMALIZED_RMSE_LIMIT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("donor", "recipient"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--donor-dir")
    parser.add_argument("segments", nargs=3)
    args = parser.parse_args()
    if args.stage == "recipient" and not args.donor_dir:
        raise RuntimeError("recipient bundle requires --donor-dir")
    segments = [_load_segment(value) for value in args.segments]
    if [int(value["protocol"]["segment_index"]) for value in segments] != [0, 1, 2]:
        raise RuntimeError("v1.3.1 source segment order differs")
    if any(value["protocol"]["stage"] != args.stage for value in segments):
        raise RuntimeError("v1.3.1 source segment stage differs")
    hashes = [value["protocol"]["source_sha256"] for value in segments]
    if any(value != hashes[0] for value in hashes[1:]):
        raise RuntimeError("v1.3.1 source hashes differ across segments")
    reference = segments[0]["protocol"]["metadata"]
    for value in segments[1:]:
        for key in ("device_id", "firmware_rev", "instrument_ids"):
            if value["protocol"]["metadata"].get(key) != reference.get(key):
                raise RuntimeError("v1.3.1 source hardware metadata differ")
    previous_end = None
    for value in segments:
        start = min(float(row["t_acq_start_unix"]) for row in value["rows"])
        end = max(float(row["t_acq_end_unix"]) for row in value["rows"])
        if previous_end is not None and previous_end >= start:
            raise RuntimeError("v1.3.1 source segment acquisition times overlap")
        previous_end = end
    donor_reference = (acquire._load_donor_reference(args.donor_dir)
                       if args.stage == "recipient" else None)
    if args.stage == "recipient" and any(
            value["protocol"].get("donor_reference") != donor_reference
            for value in segments):
        raise RuntimeError("recipient segments do not freeze the same donor")
    values = _combine(segments)
    family = ("interleaved_spur_calibration" if args.stage == "donor"
              else "interleaved_calibration_v131")
    simulated = all(value["protocol"].get("simulated", False) for value in segments)
    root = Path(ec.REPO, "build", "exp_sim", family, args.run_id) if simulated \
        else Path(ec.DATA, "diagnostics", family, args.run_id)
    root.mkdir(parents=True, exist_ok=False)
    for name, rows, header in (
            ("interleaved_calibration", values["rows"], contract.MAIN_HEADER),
            ("formal_windows", values["windows"], contract.WINDOW_HEADER),
            ("transition_discard", values["discards"], contract.DISCARD_HEADER),
            ("dmm_reads", values["dmm"], contract.DMM_HEADER)):
        _write_csv_npz(root, name, rows, header)
    with (root / "conditioning.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(contract.CONDITIONING_HEADER)
        writer.writerows([[row[name] for name in contract.CONDITIONING_HEADER]
                          for row in values["conditioning"]])
    acquire._write_json(str(root / "pilot_verification.json"), values["pilot"])
    acquire._write_json(str(root / "acq_read_failures.json"), values["failures"])
    protocol = dict(
        protocol_version=(v13.DONOR_PROTOCOL_VERSION if args.stage == "donor"
                          else v13.PROTOCOL_VERSION),
        stage=args.stage, segmented_bundle=True, simulated=simulated,
        run_id=args.run_id, schedule=v13.schedule_records(),
        schedule_sha256=v13.schedule_sha256(), donor_reference=donor_reference,
        source_sha256=hashes[0], metadata=reference,
        source_segments=[dict(
            segment_index=index, path=str(value["root"]),
            checksums=value["checksums"],
            checksums_sha256=legacy._sha256(value["root"] / "checksums.json"))
            for index, value in enumerate(segments)],
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False)
    acquire._write_json(str(root / "protocol.json"), protocol)
    fields = {name: np.asarray([row[name] for row in values["rows"]])
              for name in contract.MAIN_HEADER}
    formal = fields["role"].astype("U16") == "formal"
    components = mb.choose_comps(
        fields["I1"][formal].astype(float), fields["Q1"][formal].astype(float),
        fields["I2"][formal].astype(float), fields["Q2"][formal].astype(float))
    if args.stage == "donor":
        science = contract.donor_science(values["rows"], values["windows"], components)
        common = _global_common(values["rows"], science["time_truth"])
        base_pass = bool(science["time_truth"]["quality_gate"]["accepted"])
        correction_pass = bool(science["spur_correction"]["quality_gate"]["accepted"])
        required = dict(
            all_segments_pass=all(value["analysis"]["quality_gate"]["accepted"]
                                  for value in segments),
            time_truth_pass=base_pass,
            target_time_corr_pass=common["target_time_corr_pass"],
            dmm_bracket_stability_pass=common["dmm_bracket_stability_pass"],
            spur_correction_pass=correction_pass)
        accepted = bool(all(required.values()))
        analysis = dict(
            protocol_version=v13.DONOR_PROTOCOL_VERSION, stage=args.stage,
            quality_gate=dict(**required, required_pass_fields=tuple(required),
                              accepted=accepted),
            common=common, components=list(components),
            time_truth=science["time_truth"],
            spur_correction={key: value for key, value in
                             science["spur_correction"].items() if key != "table"})
        if accepted:
            table = science["spur_correction"]["table"]
            tmp = root / "spur_correction.tmp.npz"
            np.savez(tmp, **table)
            os.replace(tmp, root / "spur_correction.npz")
            acquire._write_json(str(root / "spur_correction.json"), _table_json(table))
    else:
        with np.load(Path(args.donor_dir) / "spur_correction.npz",
                     allow_pickle=False) as data:
            table = {name: data[name] for name in data.files}
        for name in ("protocol_version", "schedule_sha256", "table_sha256"):
            if isinstance(table[name], np.ndarray) and table[name].shape == ():
                table[name] = str(table[name].item())
        science = contract.recipient_science(values["rows"], components, table)
        common = _global_common(values["rows"], science["corrected"])
        required = dict(
            all_segments_pass=all(value["analysis"]["quality_gate"]["accepted"]
                                  for value in segments),
            corrected_science_pass=bool(
                science["corrected"]["quality_gate"]["accepted"]),
            target_time_corr_pass=common["target_time_corr_pass"],
            dmm_bracket_stability_pass=common["dmm_bracket_stability_pass"])
        accepted = bool(all(required.values()))
        analysis = dict(
            protocol_version=v13.PROTOCOL_VERSION, stage=args.stage,
            quality_gate=dict(**required, required_pass_fields=tuple(required),
                              accepted=accepted),
            common=common, components=list(components),
            corrected=science["corrected"],
            corrected_mapping=science["corrected_mapping"],
            uncorrected=science["uncorrected"],
            uncorrected_mapping=science["uncorrected_mapping"],
            correction_table_sha256=science["correction_table_sha256"])
    analysis = _native(analysis)
    acquire._write_json(str(root / "analysis.json"), analysis)
    acquire._write_json(str(root / "summary.json"), dict(
        complete=True, stage=args.stage, observations=len(values["rows"]),
        windows=len(values["windows"]), discards=len(values["discards"]),
        dmm_reads=len(values["dmm"]), conditioning_rows=len(values["conditioning"]),
        read_failures=len(values["failures"]), analysis=analysis))
    acquire._write_json(str(root / "manifest.json"), dict(
        run_id=args.run_id, status="complete", failure=None, stage=args.stage,
        derived_bundle=True, created_unix=time.time(),
        quality_gate_accepted=analysis["quality_gate"]["accepted"]))
    acquire._refresh_checksums(root)
    print(json.dumps(analysis["quality_gate"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
