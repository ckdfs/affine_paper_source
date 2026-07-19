#!/usr/bin/env python3
"""Read-only pure-contract fault matrix for frozen MZM interleaved v1.3.1 bundles."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import diagnose_mzm_interleaved_v131 as acquire
import mzm_interleaved_v131_contract as contract
import mzm_interleaved_v131_truth as v13
import validate_mzm_interleaved_calibration as legacy


def _expect_error(function, label):
    try:
        function()
    except Exception:
        return True
    raise AssertionError(f"fault was accepted: {label}")


def _rehash(table):
    value = copy.deepcopy(table)
    serializable = {
        name: (np.asarray(item).tolist() if isinstance(item, np.ndarray)
               else item)
        for name, item in value.items() if name != "table_sha256"}
    value["table_sha256"] = v13._json_sha256(serializable)
    v13.validate_spur_table(value)
    return value


def _table(path):
    with np.load(path, allow_pickle=False) as data:
        value = {name: data[name] for name in data.files}
    for name in ("protocol_version", "schedule_sha256", "table_sha256"):
        if isinstance(value[name], np.ndarray) and value[name].shape == ():
            value[name] = str(value[name].item())
    v13.validate_spur_table(value)
    return value


def _replay(script, root):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(script)),
         "--replay-dir", str(root)], text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"healthy replay failed: {root}\n{result.stderr}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor-bundle", required=True)
    parser.add_argument("--recipient-bundle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    donor = Path(args.donor_bundle).resolve()
    recipient = Path(args.recipient_bundle).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(output)
    _replay("validate_mzm_interleaved_v131_bundle.py", donor)
    _replay("validate_mzm_interleaved_v131_bundle.py", recipient)

    table = _table(donor / "spur_correction.npz")
    protocol = json.loads((recipient / "protocol.json").read_text())
    analysis = json.loads((recipient / "analysis.json").read_text())
    rows = legacy._load_npz(
        recipient / "interleaved_calibration.npz", contract.MAIN_HEADER,
        v13.schedule_sha256())
    components = tuple(analysis["components"])
    fields = {name: np.asarray([row[name] for row in rows])
              for name in contract.MAIN_HEADER}
    raw_x, raw_y = contract.selected_xy(fields, components)

    grid_bad = copy.deepcopy(table)
    grid_bad["grid_index"] = np.asarray(grid_bad["grid_index"]).copy()
    grid_bad["grid_index"][3] = 4
    finite_bad = copy.deepcopy(table)
    finite_bad["d_V"] = np.asarray(finite_bad["d_V"], float).copy()
    finite_bad["d_V"][3] = np.nan
    hash_bad = copy.deepcopy(table)
    hash_bad["d_V"] = np.asarray(hash_bad["d_V"], float).copy()
    hash_bad["d_V"][3] += 1e-6
    component_bad = copy.deepcopy(table)
    component_bad["components"] = np.asarray(("X", "Q"))

    bias_bad = fields["bias"].astype(float).copy()
    bias_bad[3] = np.nextafter(bias_bad[3], np.inf)
    pure = dict(
        table_grid_rejected=_expect_error(
            lambda: v13.validate_spur_table(grid_bad), "table grid"),
        table_finite_rejected=_expect_error(
            lambda: v13.validate_spur_table(finite_bad), "table finite"),
        table_hash_rejected=_expect_error(
            lambda: v13.validate_spur_table(hash_bad), "table hash"),
        table_component_rejected=_expect_error(
            lambda: v13.validate_spur_table(component_bad), "table component"),
        recipient_component_mismatch_rejected=_expect_error(
            lambda: v13.apply_spur_correction(
                raw_x, raw_y, fields["grid_index"], fields["bias"], table,
                ("I" if components[0] == "Q" else "Q", components[1])),
            "recipient component"),
        recipient_bias_mismatch_rejected=_expect_error(
            lambda: v13.apply_spur_correction(
                raw_x, raw_y, fields["grid_index"], bias_bad, table,
                components), "recipient bias"),
        recipient_uncorrected_mapping_rejected=bool(
            not analysis["uncorrected_mapping"]["accepted"]),
    )

    for label, transform in (
            ("wrong_sign", lambda value: -value),
            ("scaled", lambda value: 0.45 * value),
            ("replaced", lambda value: value[::-1])):
        changed = copy.deepcopy(table)
        changed["d_V"] = transform(np.asarray(changed["d_V"], float).copy())
        changed = _rehash(changed)
        science = contract.recipient_science(rows, components, changed)
        pure[f"recipient_{label}_science_rejected"] = bool(
            not science["corrected_mapping"]["accepted"])

    with tempfile.TemporaryDirectory(prefix="mzm-v13-fault-") as tmp:
        tampered = Path(tmp) / "donor"
        shutil.copytree(donor, tampered)
        correction = tampered / "spur_correction.json"
        correction.write_bytes(correction.read_bytes() + b"\n")
        pure["donor_checksum_tamper_rejected"] = _expect_error(
            lambda: acquire._load_donor_reference(str(tampered)),
            "donor checksum")

    with tempfile.TemporaryDirectory(prefix="mzm-v13-fault-") as tmp:
        rejected = Path(tmp) / "donor"
        shutil.copytree(donor, rejected)
        donor_analysis = json.loads((rejected / "analysis.json").read_text())
        donor_analysis["quality_gate"]["accepted"] = False
        acquire._write_json(str(rejected / "analysis.json"), donor_analysis)
        checksums = json.loads((rejected / "checksums.json").read_text())
        checksums["analysis.json"] = acquire._sha256(str(rejected / "analysis.json"))
        acquire._write_json(str(rejected / "checksums.json"), checksums)
        pure["rejected_donor_reference_rejected"] = _expect_error(
            lambda: acquire._load_donor_reference(str(rejected)),
            "rejected donor")

    if not all(pure.values()):
        raise AssertionError({name: value for name, value in pure.items()
                              if not value})
    report = dict(
        accepted=True,
        validator_sha256=acquire._sha256(str(Path(__file__).resolve())),
        donor_bundle=str(donor), recipient_bundle=str(recipient),
        donor_checksums_sha256=acquire._sha256(str(donor / "checksums.json")),
        recipient_checksums_sha256=acquire._sha256(
            str(recipient / "checksums.json")),
        donor_reference=protocol.get("donor_reference"), checks=pure)
    output.parent.mkdir(parents=True, exist_ok=True)
    acquire._write_json(str(output), report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
