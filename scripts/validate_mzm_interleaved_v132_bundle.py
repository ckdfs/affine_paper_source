#!/usr/bin/env python3
"""Read-only full replay for a MZM interleaved-v1.3.2 derived bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import analyze_mzm_interleaved_v132_segments as aggregate
import diagnose_mzm_interleaved_v132 as acquire
import measure_bench as mb
import mzm_interleaved_v132_contract as contract
import mzm_interleaved_v132_truth as v13
import validate_mzm_interleaved_calibration as legacy


def _table_from_npz(path):
    with np.load(path, allow_pickle=False) as data:
        table = {name: data[name] for name in data.files}
    for name in ("protocol_version", "schedule_sha256", "table_sha256"):
        if isinstance(table[name], np.ndarray) and table[name].shape == ():
            table[name] = str(table[name].item())
    return table


def _recompute(stage, segments, values, donor_dir=None):
    fields = {name: np.asarray([row[name] for row in values["rows"]])
              for name in contract.MAIN_HEADER}
    formal = fields["role"].astype("U16") == "formal"
    components = mb.choose_comps(
        fields["I1"][formal].astype(float), fields["Q1"][formal].astype(float),
        fields["I2"][formal].astype(float), fields["Q2"][formal].astype(float))
    if stage == "donor":
        science = contract.donor_science(values["rows"], values["windows"], components)
        common = aggregate._global_common(values["rows"], science["time_truth"])
        required = dict(
            all_segments_pass=all(value["analysis"]["quality_gate"]["accepted"]
                                  for value in segments),
            time_truth_pass=bool(science["time_truth"]["quality_gate"]["accepted"]),
            target_time_corr_pass=common["target_time_corr_pass"],
            dmm_bracket_stability_pass=common["dmm_bracket_stability_pass"],
            spur_correction_pass=bool(
                science["spur_correction"]["quality_gate"]["accepted"]))
        analysis = dict(
            protocol_version=v13.DONOR_PROTOCOL_VERSION, stage=stage,
            quality_gate=dict(**required, required_pass_fields=tuple(required),
                              accepted=bool(all(required.values()))),
            common=common, components=list(components),
            time_truth=science["time_truth"],
            spur_correction={key: value for key, value in
                             science["spur_correction"].items() if key != "table"})
        return aggregate._native(analysis), science["spur_correction"]["table"]
    table = _table_from_npz(Path(donor_dir) / "spur_correction.npz")
    science = contract.recipient_science(values["rows"], components, table)
    common = aggregate._global_common(values["rows"], science["corrected"])
    required = dict(
        all_segments_pass=all(value["analysis"]["quality_gate"]["accepted"]
                              for value in segments),
        corrected_science_pass=bool(
            science["corrected"]["quality_gate"]["accepted"]),
        target_time_corr_pass=common["target_time_corr_pass"],
        dmm_bracket_stability_pass=common["dmm_bracket_stability_pass"])
    analysis = dict(
        protocol_version=v13.PROTOCOL_VERSION, stage=stage,
        quality_gate=dict(**required, required_pass_fields=tuple(required),
                          accepted=bool(all(required.values()))),
        common=common, components=list(components),
        corrected=science["corrected"],
        corrected_mapping=science["corrected_mapping"],
        uncorrected=science["uncorrected"],
        uncorrected_mapping=science["uncorrected_mapping"],
        correction_table_sha256=science["correction_table_sha256"])
    return aggregate._native(analysis), None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", required=True)
    args = parser.parse_args()
    root = Path(args.replay_dir).resolve()
    protocol = json.loads((root / "protocol.json").read_text())
    stage = protocol.get("stage")
    if stage not in ("donor", "recipient"):
        raise RuntimeError("v1.3 bundle stage differs")
    common_files = {
        "acq_read_failures.json", "analysis.json", "checksums.json",
        "conditioning.csv", "dmm_reads.csv", "dmm_reads.npz",
        "formal_windows.csv", "formal_windows.npz",
        "interleaved_calibration.csv", "interleaved_calibration.npz",
        "manifest.json", "pilot_verification.json", "protocol.json",
        "summary.json", "transition_discard.csv", "transition_discard.npz"}
    required = set(common_files)
    recorded_preview = json.loads((root / "analysis.json").read_text())
    donor_accepted = bool(recorded_preview.get("quality_gate", {}).get("accepted", False))
    if stage == "donor" and donor_accepted:
        required.update(("spur_correction.json", "spur_correction.npz"))
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError(f"v1.3 bundle missing files: {missing}")
    checksums = json.loads((root / "checksums.json").read_text())
    if set(checksums) != required - {"checksums.json"}:
        raise RuntimeError("v1.3 bundle checksum file set differs")
    for name, digest in checksums.items():
        if legacy._sha256(root / name) != digest:
            raise RuntimeError(f"v1.3 bundle checksum mismatch: {name}")
    manifest = json.loads((root / "manifest.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    recorded = json.loads((root / "analysis.json").read_text())
    if (manifest.get("status") != "complete" or manifest.get("failure") is not None or
            protocol.get("segmented_bundle") is not True):
        raise RuntimeError("v1.3 bundle manifest/protocol is incomplete")
    if (protocol.get("schedule") != v13.schedule_records() or
            protocol.get("schedule_sha256") != v13.schedule_sha256()):
        raise RuntimeError("v1.3 bundle schedule differs")
    sources = protocol.get("source_segments")
    if not isinstance(sources, list) or len(sources) != 3:
        raise RuntimeError("v1.3 bundle source count differs")
    segments = []
    for index, source in enumerate(sources):
        if int(source.get("segment_index", -1)) != index:
            raise RuntimeError("v1.3 bundle source order differs")
        value = aggregate._load_segment(source["path"])
        if (source.get("checksums") != value["checksums"] or
                source.get("checksums_sha256") !=
                legacy._sha256(value["root"] / "checksums.json")):
            raise RuntimeError("v1.3 bundle source checksum contract differs")
        segments.append(value)
    expected = aggregate._combine(segments)
    schedule_hash = v13.schedule_sha256()
    rows = legacy._load_npz(root / "interleaved_calibration.npz",
                            contract.MAIN_HEADER, schedule_hash)
    windows = legacy._load_npz(root / "formal_windows.npz",
                               contract.WINDOW_HEADER, schedule_hash)
    discards = legacy._load_npz(root / "transition_discard.npz",
                                contract.DISCARD_HEADER, schedule_hash)
    dmm = legacy._load_npz(root / "dmm_reads.npz", contract.DMM_HEADER,
                           schedule_hash)
    conditioning = legacy._load_csv(root / "conditioning.csv",
                                    contract.CONDITIONING_HEADER)
    for filename, header, values in (
            ("interleaved_calibration.csv", contract.MAIN_HEADER, rows),
            ("formal_windows.csv", contract.WINDOW_HEADER, windows),
            ("transition_discard.csv", contract.DISCARD_HEADER, discards),
            ("dmm_reads.csv", contract.DMM_HEADER, dmm)):
        csv_rows = legacy._load_csv(root / filename, header)
        legacy._check_csv_npz(csv_rows, values, header, filename)
    actual = dict(
        rows=rows, windows=windows, discards=discards, dmm=dmm,
        conditioning=conditioning,
        failures=json.loads((root / "acq_read_failures.json").read_text()),
        pilot=json.loads((root / "pilot_verification.json").read_text()))
    for key in ("rows", "windows", "discards", "dmm", "failures", "pilot"):
        legacy._assert_equivalent(actual[key], expected[key], f"bundle.{key}")
    if (len(actual["conditioning"]) != len(expected["conditioning"]) or
            any(not all(legacy._csv_value_matches(row[name], reference[name])
                        for name in contract.CONDITIONING_HEADER)
                for row, reference in zip(actual["conditioning"],
                                          expected["conditioning"]))):
        raise RuntimeError("bundle.conditioning differs")
    donor_dir = (protocol.get("donor_reference") or {}).get("path")
    recomputed, table = _recompute(stage, segments, actual, donor_dir)
    legacy._assert_equivalent(recomputed, recorded)
    if stage == "donor" and donor_accepted:
        recorded_table = _table_from_npz(root / "spur_correction.npz")
        v13.validate_spur_table(recorded_table)
        legacy._assert_equivalent(
            aggregate._table_json(table),
            json.loads((root / "spur_correction.json").read_text()),
            "spur_correction.json")
        legacy._assert_equivalent(
            aggregate._table_json(table), aggregate._table_json(recorded_table),
            "spur_correction.npz")
    elif stage == "donor" and ((root / "spur_correction.json").exists() or
                                (root / "spur_correction.npz").exists()):
        raise RuntimeError("rejected donor bundle must not publish a correction table")
    if (not summary.get("complete") or summary.get("analysis") != recorded or
            bool(manifest.get("quality_gate_accepted")) !=
            bool(recorded["quality_gate"]["accepted"])):
        raise RuntimeError("v1.3 bundle summary/manifest differs")
    print(json.dumps(dict(
        accepted=recorded["quality_gate"]["accepted"], stage=stage,
        observations=len(rows), windows=len(windows), discards=len(discards),
        dmm_reads=len(dmm), read_failures=len(actual["failures"])),
        indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
