#!/usr/bin/env python3
"""Audit and aggregate independent single-MZM acceptance experiment sessions.

The acquisition driver writes one immutable directory per bench session under
``data/exp/acceptance/<run-id>``.  This script verifies file hashes, treats a
fresh calibration repetition as the experimental unit, performs a hierarchical
session/repetition/target bootstrap, and evaluates the preregistered evidence
gate.  It never edits measured data or the paper's headline results contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np


CONTROLLERS = ("full_affine", "calibrated_h1h2", "h1_match")


def _verify_hashes(root: Path):
    path = root / "checksums.json"
    if not path.exists():
        return False, ["missing checksums.json"]
    expected = json.loads(path.read_text())
    failures = []
    for rel, digest in expected.items():
        target = root / rel
        if not target.exists():
            failures.append(f"missing {rel}")
            continue
        h = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            failures.append(f"hash mismatch {rel}")
    return not failures, failures


def _calibration_audit(repdir: Path):
    fit = json.loads((repdir / "calib_fit.json").read_text())
    data = np.load(repdir / "calib.npz")
    B = np.asarray(fit["B"], float)
    A = np.linalg.inv(B)
    Z = np.stack([data["X"], data["Y"]], axis=1)
    center = np.asarray(fit["c0"], float)
    U = (B @ (Z - center).T).T
    radial = np.abs(np.linalg.norm(U, axis=1) - 1.0)
    theta = np.arctan2(U[:, 1], U[:, 0])
    D = np.stack([np.ones(len(theta)), np.cos(theta), np.sin(theta)], axis=1)
    dc = np.asarray(data["dc_dmm"], float)
    coef, *_ = np.linalg.lstsq(D, dc, rcond=None)
    resid = dc - D @ coef
    gauge_amp = float(np.hypot(coef[1], coef[2]))
    gauge_snr = gauge_amp / max(float(np.std(resid, ddof=3)), 1e-12)
    offdiag = A - np.diag(np.diag(A))
    return dict(
        method=fit.get("method"), kappa=float(np.linalg.cond(A)),
        sigma_min=float(np.linalg.svd(A, compute_uv=False)[-1]),
        radial_p95=float(np.percentile(radial, 95)), gauge_snr=float(gauge_snr),
        offdiag_fraction=float(np.linalg.norm(offdiag) / np.linalg.norm(A)))


def _discover(paths, root: Path):
    if paths:
        return [Path(p).resolve() for p in paths]
    if not root.exists():
        return []
    return sorted(p.resolve() for p in root.iterdir() if (p / "protocol.json").exists())


def _hierarchical_bootstrap(errors, session_ids, baseline, seed, draws):
    """Return baseline-minus-full RMS with session/repetition/target resampling."""
    errors = np.asarray(errors, float)
    session_ids = np.asarray(session_ids)
    unique = np.unique(session_ids)
    estimate = (np.sqrt(np.mean(errors[:, baseline] ** 2)) -
                np.sqrt(np.mean(errors[:, 0] ** 2))) * 1e3
    if len(unique) < 2:
        return dict(estimate_mrad=float(estimate), ci95_mrad=None,
                    session_count=int(len(unique)), repetition_count=len(errors))
    groups = {s: np.flatnonzero(session_ids == s) for s in unique}
    rng = np.random.default_rng(seed)
    values = np.empty(draws)
    for b in range(draws):
        sampled = []
        for session in rng.choice(unique, len(unique), replace=True):
            reps = groups[session]
            for rep in rng.choice(reps, len(reps), replace=True):
                n_target = errors.shape[2]
                target = rng.integers(0, n_target, n_target)
                sampled.append(np.take(errors[rep:rep + 1], target, axis=2))
        sample = np.concatenate(sampled, axis=0)
        values[b] = (np.sqrt(np.mean(sample[:, baseline] ** 2)) -
                     np.sqrt(np.mean(sample[:, 0] ** 2))) * 1e3
    return dict(estimate_mrad=float(estimate),
                ci95_mrad=[float(v) for v in np.percentile(values, [2.5, 97.5])],
                session_count=int(len(unique)), repetition_count=len(errors))


def analyze(run_roots, include_sim=False, seed=20260710, draws=8000):
    errors = []
    successes = []
    session_ids = []
    audits = []
    run_audits = []
    protocol_consistent = True
    attempted_blocks = 0
    failed_blocks = []
    for root in run_roots:
        protocol = json.loads((root / "protocol.json").read_text())
        if protocol.get("simulated") and not include_sim:
            continue
        ok, hash_failures = _verify_hashes(root)
        metadata = protocol.get("metadata", {})
        session = metadata.get("session_id") or root.name
        reps = sorted(root.glob("rep_*"))
        attempted_blocks += len(reps)
        run_audits.append(dict(root=str(root), hashes_ok=ok,
                               hash_failures=hash_failures, session_id=session,
                               repetitions=len(reps), simulated=protocol.get("simulated")))
        protocol_consistent &= bool(ok and protocol.get("calibration_method") == "ellipse")
        for repdir in reps:
            manifest_path = repdir / "manifest.json"
            manifest = (json.loads(manifest_path.read_text())
                        if manifest_path.exists() else {})
            required = (repdir / "acceptance_lock.npz", repdir / "calib_fit.json",
                        repdir / "calib.npz")
            if manifest.get("status", "complete") != "complete" or not all(
                    path.exists() for path in required):
                failed_blocks.append(dict(
                    path=str(repdir), status=manifest.get("status", "incomplete"),
                    failure=manifest.get("failure")))
                continue
            lock = np.load(repdir / "acceptance_lock.npz")
            names = tuple(str(x) for x in lock["controller_names"])
            protocol_consistent &= names == CONTROLLERS
            protocol_consistent &= str(lock["calibration_method"]) == "ellipse"
            e = np.asarray(lock["error_map"], float)
            s = np.asarray(lock["success"], bool)
            if e.shape[0] != len(CONTROLLERS) or e.ndim != 3:
                raise ValueError(f"unexpected error array shape {e.shape} in {repdir}")
            errors.append(e)
            successes.append(s)
            session_ids.append(session)
            audits.append(_calibration_audit(repdir))
    if not errors:
        if not attempted_blocks:
            raise RuntimeError("no eligible acceptance repetitions found")
        gate = dict(
            hashes_and_protocol=bool(protocol_consistent),
            complete_acquisition=False,
            at_least_two_sessions=False,
            at_least_six_calibration_blocks=False,
            calibration_success=False,
            full_success_fraction=False,
            every_target_success=False,
            full_rms_le_400_mrad=False,
            full_p95_le_750_mrad=False,
            no_block_rms_gt_500_mrad=False,
            full_noninferior_h1h2=False,
            full_beats_h1=False,
            independent_optical_truth=False,
            controller_evidence_passed=False,
            paper_acceptance_ready=False)
        return dict(
            design=dict(repetitions=0, attempted_repetitions=attempted_blocks,
                        failed_repetitions=len(failed_blocks), sessions=0,
                        targets=0, starts_per_target=0,
                        bootstrap_draws=int(draws), bootstrap_seed=int(seed)),
            runs=run_audits, failed_blocks=failed_blocks,
            calibration_audits=[], aggregate={}, contrasts={}, gate=gate,
            limitations=[
                "No complete calibration block was available for descriptive aggregation.",
                "Attempted but incomplete blocks are retained and force the evidence gates false.",
                "Independent optical truth remains false until isolated-channel acquisition and blind scoring are implemented.",
            ])
    errors = np.asarray(errors)
    successes = np.asarray(successes)
    session_ids = np.asarray(session_ids)
    n_rep, _, n_target, n_start = errors.shape

    aggregate = {}
    for j, name in enumerate(CONTROLLERS):
        x = errors[:, j]
        per_rep = np.sqrt(np.mean(x * x, axis=(1, 2))) * 1e3
        aggregate[name] = dict(
            rms_mrad=float(np.sqrt(np.mean(x * x)) * 1e3),
            median_abs_mrad=float(np.median(np.abs(x)) * 1e3),
            p95_abs_mrad=float(np.percentile(np.abs(x), 95) * 1e3),
            max_abs_mrad=float(np.max(np.abs(x)) * 1e3),
            success_fraction=float(np.mean(successes[:, j])),
            per_repeat_rms_mrad=[float(v) for v in per_rep])
    contrasts = dict(
        calibrated_h1h2_minus_full=_hierarchical_bootstrap(
            errors, session_ids, 1, seed + 10000, draws),
        h1_minus_full=_hierarchical_bootstrap(
            errors, session_ids, 2, seed + 20000, draws))

    audit_ok = [a["method"] == "ellipse" and a["radial_p95"] <= 0.15 and
                a["gauge_snr"] >= 10 for a in audits]
    full = aggregate["full_affine"]
    per_rep_full = np.asarray(full["per_repeat_rms_mrad"])
    per_target_success = np.mean(successes[:, 0], axis=(0, 2))
    ci_diag = contrasts["calibrated_h1h2_minus_full"]["ci95_mrad"]
    ci_h1 = contrasts["h1_minus_full"]["ci95_mrad"]
    gate = dict(
        hashes_and_protocol=bool(protocol_consistent),
        complete_acquisition=bool(not failed_blocks and n_rep == attempted_blocks),
        at_least_two_sessions=bool(len(np.unique(session_ids)) >= 2),
        at_least_six_calibration_blocks=bool(n_rep >= 6),
        calibration_success=bool(sum(audit_ok) >= max(5, n_rep - 1)),
        full_success_fraction=bool(full["success_fraction"] >= 92 / 96),
        every_target_success=bool(np.all(per_target_success >= 5 / 6)),
        full_rms_le_400_mrad=bool(full["rms_mrad"] <= 400),
        full_p95_le_750_mrad=bool(full["p95_abs_mrad"] <= 750),
        no_block_rms_gt_500_mrad=bool(np.max(per_rep_full) <= 500),
        full_noninferior_h1h2=bool(ci_diag is not None and ci_diag[0] > -50),
        full_beats_h1=bool(ci_h1 is not None and ci_h1[0] > 0),
        # Acquisition and blind scoring of an isolated validation channel are
        # intentionally not implemented yet.  File existence alone must never
        # be accepted as independent truth.
        independent_optical_truth=False)
    gate["controller_evidence_passed"] = bool(all(
        value for key, value in gate.items() if key != "independent_optical_truth"))
    gate["paper_acceptance_ready"] = bool(all(gate.values()))
    return dict(
        design=dict(repetitions=n_rep, attempted_repetitions=attempted_blocks,
                    failed_repetitions=len(failed_blocks),
                    sessions=int(len(np.unique(session_ids))),
                    targets=n_target, starts_per_target=n_start,
                    bootstrap_draws=int(draws), bootstrap_seed=int(seed)),
        runs=run_audits, failed_blocks=failed_blocks,
        calibration_audits=audits, aggregate=aggregate,
        contrasts=contrasts, gate=gate,
        limitations=[
            "The calibration block, not target/iteration samples, is the independent unit.",
            "Independent optical truth remains false until isolated-channel acquisition and blind scoring are implemented; file presence is insufficient.",
            "Simulation runs are excluded unless --include-sim is set and cannot pass the paper gate.",
        ])


def main():
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="*", help="acceptance run directories")
    ap.add_argument("--root", default=str(repo / "data" / "exp" / "acceptance"),
                    help="discover run directories here when none are listed")
    ap.add_argument("--include-sim", action="store_true",
                    help="include simulated sessions for tooling tests only")
    ap.add_argument("--seed", type=int, default=20260710)
    ap.add_argument("--bootstrap-draws", type=int, default=8000)
    ap.add_argument("--output", help="optional JSON output path; stdout is always printed")
    args = ap.parse_args()
    roots = _discover(args.runs, Path(args.root))
    report = analyze(roots, include_sim=args.include_sim, seed=args.seed,
                     draws=args.bootstrap_draws)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + os.linesep)


if __name__ == "__main__":
    main()
