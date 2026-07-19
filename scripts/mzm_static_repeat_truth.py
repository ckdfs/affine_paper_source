#!/usr/bin/env python3
"""Pure schedule and statistics helpers for the static-repeat MZM diagnostic.

Frozen by reviews/mzm_static_repeat_protocol.md (v1.0).  No instrument access,
no file I/O.  The diagnostic compares four restart conditions at fixed bias
points; acceptance covers only the capture contract, while the preregistered
interpretation rules emit implicate/exonerate conclusions for gen/acq restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mzm_time_truth as tt  # noqa: E402


PROTOCOL_VERSION = "mzm-static-repeat-v1.2"
ACQ_VERIFY_ATTEMPTS = 3
ACQ_READ_ATTEMPTS = 3
PILOT_V = 0.08
N_BLOCKS = 16
N_WINDOWS = 2
DISCARD_BLOCKS = 6
DMM_READS = 2
BIAS_SETTLE_S = 0.500
DISCARD_TO_FORMAL_MAX_S = 2.000
HEADROOM_LIMIT_V = 0.95
HEADROOM_LIMIT_CODE = 6_640_981

POINT_GRID = (40, 0, 60, 20, 80)
CONDITIONS = ("none", "gen", "acq", "both")
REPEATS_PER_BLOCK = 12
BLOCKS_PER_POINT = len(CONDITIONS)
TOTAL_BLOCKS = len(POINT_GRID) * BLOCKS_PER_POINT
TOTAL_REPEATS = TOTAL_BLOCKS * REPEATS_PER_BLOCK

RESTART_EXCESS_MIN_RAD = 0.02
RESTART_RATIO_MIN = 2.0
ENVIRONMENT_H2_CSTD_RAD = 0.05
POINTS_REQUIRED = 3


def grid_step():
    return float(2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1))


def point_condition_order(point_ordinal):
    p = int(point_ordinal)
    if p < 0 or p >= len(POINT_GRID):
        raise ValueError("point ordinal out of range")
    shift = p % len(CONDITIONS)
    return CONDITIONS[shift:] + CONDITIONS[:shift]


def build_schedule():
    grid = np.linspace(tt.CENTER_V - tt.VPI_V, tt.CENTER_V + tt.VPI_V,
                       tt.POINTS_PER_LEG)
    step = grid_step()
    fields = dict(point_ordinal=[], grid_index=[], block_index=[],
                  condition=[], condition_ordinal=[], repeat_index=[],
                  bias=[], approach_bias=[], restart_gen=[], restart_acq=[],
                  repeat_sequence_index=[])
    sequence = 0
    for p, gi in enumerate(POINT_GRID):
        value = float(grid[gi])
        for c_ord, condition in enumerate(point_condition_order(p)):
            block = p * BLOCKS_PER_POINT + c_ord
            for repeat in range(REPEATS_PER_BLOCK):
                fields["point_ordinal"].append(p)
                fields["grid_index"].append(int(gi))
                fields["block_index"].append(block)
                fields["condition"].append(condition)
                fields["condition_ordinal"].append(c_ord)
                fields["repeat_index"].append(repeat)
                fields["bias"].append(value)
                fields["approach_bias"].append(value - step)
                fields["restart_gen"].append(
                    1 if condition in ("gen", "both") else 0)
                fields["restart_acq"].append(
                    1 if condition in ("acq", "both") else 0)
                fields["repeat_sequence_index"].append(sequence)
                sequence += 1
    out = {}
    for name, values in fields.items():
        if name == "condition":
            out[name] = np.asarray(values, dtype="U4")
        elif name in ("bias", "approach_bias"):
            out[name] = np.asarray(values, dtype=float)
        else:
            out[name] = np.asarray(values, dtype=int)
    if len(out["bias"]) != TOTAL_REPEATS:
        raise AssertionError("frozen static-repeat schedule size differs")
    if np.max(np.abs(out["approach_bias"])) >= 0.995 * tt.BIAS_LIMIT_V:
        raise AssertionError("approach bias exceeds frozen rail")
    return out


def schedule_records(schedule=None):
    schedule = build_schedule() if schedule is None else schedule
    return [dict(
        point_ordinal=int(schedule["point_ordinal"][i]),
        grid_index=int(schedule["grid_index"][i]),
        block_index=int(schedule["block_index"][i]),
        condition=str(schedule["condition"][i]),
        condition_ordinal=int(schedule["condition_ordinal"][i]),
        repeat_index=int(schedule["repeat_index"][i]),
        bias_V=float(schedule["bias"][i]),
        approach_bias_V=float(schedule["approach_bias"][i]),
        restart_gen=int(schedule["restart_gen"][i]),
        restart_acq=int(schedule["restart_acq"][i]),
        repeat_sequence_index=int(schedule["repeat_sequence_index"][i]),
    ) for i in range(len(schedule["bias"]))]


def schedule_sha256(schedule=None):
    payload = json.dumps(
        schedule_records(schedule), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_schedule_arrays(point_ordinal, grid_index, block_index,
                             condition, condition_ordinal, repeat_index,
                             bias, approach_bias, restart_gen, restart_acq,
                             repeat_sequence_index):
    frozen = build_schedule()
    values = dict(
        point_ordinal=np.asarray(point_ordinal, int),
        grid_index=np.asarray(grid_index, int),
        block_index=np.asarray(block_index, int),
        condition=np.asarray(condition).astype("U4"),
        condition_ordinal=np.asarray(condition_ordinal, int),
        repeat_index=np.asarray(repeat_index, int),
        bias=np.asarray(bias, float),
        approach_bias=np.asarray(approach_bias, float),
        restart_gen=np.asarray(restart_gen, int),
        restart_acq=np.asarray(restart_acq, int),
        repeat_sequence_index=np.asarray(repeat_sequence_index, int),
    )
    failed = [name for name in frozen
              if not np.array_equal(values[name], frozen[name])]
    if failed:
        raise ValueError("recorded static-repeat schedule differs in " +
                         ", ".join(failed))
    return True


def expected_bridges():
    """Frozen conditioning path: bridge to each point's approach, then target."""
    grid = np.linspace(tt.CENTER_V - tt.VPI_V, tt.CENTER_V + tt.VPI_V,
                       tt.POINTS_PER_LEG)
    step = grid_step()
    current = 0.0
    records = []
    sequence = 0
    for p, gi in enumerate(POINT_GRID):
        target = float(grid[gi])
        approach = target - step
        delta = approach - current
        count = max(1, int(np.ceil(abs(delta) / step)))
        path = list(np.linspace(current, approach, count + 1)[1:]) + [target]
        for bridge_step, value in enumerate(path):
            records.append(dict(
                sequence_index=sequence, point_ordinal=p,
                bridge_step_index=bridge_step,
                from_bias=float(current), bias=float(value),
                delta_bias=float(value - current),
                is_target=int(bridge_step == len(path) - 1)))
            current = float(value)
            sequence += 1
    return records


def circular_std(angles):
    angles = np.asarray(angles, float)
    if angles.size == 0 or not np.all(np.isfinite(angles)):
        raise ValueError("circular std requires finite non-empty angles")
    r = abs(np.mean(np.exp(1j * angles)))
    r = min(max(float(r), 1e-300), 1.0)
    return float(np.sqrt(-2.0 * np.log(r)))


def _wrap(angles):
    return np.angle(np.exp(1j * np.asarray(angles, float)))


def _relative_std(values):
    values = np.asarray(values, float)
    scale = max(float(np.mean(np.abs(values))), np.finfo(float).eps)
    return float(np.std(values) / scale)


def analyze_static_statistics(point_ordinal, block_index, condition,
                              t_acq_mid, I1, Q1, I2, Q2,
                              dc_dmm_pre1, dc_dmm_pre2,
                              dc_dmm_post1, dc_dmm_post2,
                              win_source_repeat, win_index,
                              win_I1, win_Q1, win_I2, win_Q2):
    """Preregistered per-block statistics and interpretation rules."""
    n = TOTAL_REPEATS
    arrays = dict(
        point_ordinal=np.asarray(point_ordinal, int),
        block_index=np.asarray(block_index, int),
        condition=np.asarray(condition).astype("U4"),
        t=np.asarray(t_acq_mid, float),
        I1=np.asarray(I1, float), Q1=np.asarray(Q1, float),
        I2=np.asarray(I2, float), Q2=np.asarray(Q2, float),
        pre1=np.asarray(dc_dmm_pre1, float),
        pre2=np.asarray(dc_dmm_pre2, float),
        post1=np.asarray(dc_dmm_post1, float),
        post2=np.asarray(dc_dmm_post2, float))
    if any(len(value) != n for value in arrays.values()):
        raise ValueError("static-repeat statistic arrays must cover all repeats")
    for name, value in arrays.items():
        if name != "condition" and not np.all(np.isfinite(
                np.asarray(value, float))):
            raise ValueError(f"non-finite values in {name}")
    wins = dict(
        source=np.asarray(win_source_repeat, int),
        index=np.asarray(win_index, int),
        I1=np.asarray(win_I1, float), Q1=np.asarray(win_Q1, float),
        I2=np.asarray(win_I2, float), Q2=np.asarray(win_Q2, float))
    if any(len(value) != n * N_WINDOWS for value in wins.values()):
        raise ValueError("static-repeat window arrays must cover all windows")

    h1 = arrays["I1"] + 1j * arrays["Q1"]
    h2 = arrays["I2"] + 1j * arrays["Q2"]
    ph1 = np.angle(h1)
    ph2 = np.angle(h2)
    excess2 = _wrap(ph2 - 2.0 * ph1)
    pre_mean = 0.5 * (arrays["pre1"] + arrays["pre2"])
    post_mean = 0.5 * (arrays["post1"] + arrays["post2"])
    bracket_abs = np.abs(post_mean - pre_mean)

    dmm_all = np.concatenate([arrays["pre1"], arrays["pre2"],
                              arrays["post1"], arrays["post2"]])
    point_of_read = np.tile(arrays["point_ordinal"], 4)
    point_medians = [float(np.median(dmm_all[point_of_read == p]))
                     for p in range(len(POINT_GRID))]
    b_hat = 0.5 * (max(point_medians) - min(point_medians))
    if not (np.isfinite(b_hat) and b_hat > 0):
        raise ValueError("preregistered DMM normalizer is not positive")
    bracket_norm = bracket_abs / b_hat

    win_h1 = wins["I1"] + 1j * wins["Q1"]
    win_h2 = wins["I2"] + 1j * wins["Q2"]

    blocks = {}
    for block in range(TOTAL_BLOCKS):
        mask = arrays["block_index"] == block
        if np.count_nonzero(mask) != REPEATS_PER_BLOCK:
            raise ValueError(f"block {block} does not hold "
                             f"{REPEATS_PER_BLOCK} repeats")
        cond = str(arrays["condition"][mask][0])
        point = int(arrays["point_ordinal"][mask][0])
        t = arrays["t"][mask]
        tau = t - np.mean(t)
        span = max(float(np.max(tau) - np.min(tau)), np.finfo(float).eps)

        def trend(angles, tau=tau, span=span):
            dev = _wrap(np.asarray(angles) -
                        np.angle(np.mean(np.exp(1j * np.asarray(angles)))))
            return float(np.polyfit(tau, dev, 1)[0])

        repeat_ids = np.flatnonzero(mask)
        wmask = np.isin(wins["source"], repeat_ids)
        first = wmask & (wins["index"] == 0)
        second = wmask & (wins["index"] == 1)
        dwin_h1 = np.abs(_wrap(np.angle(win_h1[second]) -
                               np.angle(win_h1[first])))
        dwin_h2 = np.abs(_wrap(np.angle(win_h2[second]) -
                               np.angle(win_h2[first])))
        blocks[str(block)] = dict(
            block_index=block, point_ordinal=point, condition=cond,
            grid_index=int(POINT_GRID[point]),
            h1_phase_cstd_rad=circular_std(ph1[mask]),
            h2_phase_cstd_rad=circular_std(ph2[mask]),
            h2_minus_2h1_cstd_rad=circular_std(excess2[mask]),
            h1_mag_rel_std=_relative_std(np.abs(h1[mask])),
            h2_mag_rel_std=_relative_std(np.abs(h2[mask])),
            h1_phase_trend_rad_per_s=trend(ph1[mask]),
            h2_phase_trend_rad_per_s=trend(ph2[mask]),
            within_repeat_h1_dphase_median_rad=float(np.median(dwin_h1)),
            within_repeat_h2_dphase_median_rad=float(np.median(dwin_h2)),
            dmm_bracket_norm_median=float(np.median(bracket_norm[mask])),
            dmm_bracket_norm_p95=float(np.percentile(bracket_norm[mask], 95)),
            dmm_bracket_norm_max=float(np.max(bracket_norm[mask])),
            dmm_pair_spread_pre_max_V=float(np.max(np.abs(
                arrays["pre2"][mask] - arrays["pre1"][mask]))),
            dmm_pair_spread_post_max_V=float(np.max(np.abs(
                arrays["post2"][mask] - arrays["post1"][mask]))))

    def block_of(point, cond):
        for value in blocks.values():
            if value["point_ordinal"] == point and value["condition"] == cond:
                return value
        raise ValueError(f"missing block point={point} condition={cond}")

    def implicates(point, cond, metric):
        none = block_of(point, "none")[metric]
        this = block_of(point, cond)[metric]
        return bool(this >= RESTART_RATIO_MIN * none and
                    this - none >= RESTART_EXCESS_MIN_RAD)

    subsystem = {}
    for s in ("gen", "acq"):
        point_hits = []
        for point in range(len(POINT_GRID)):
            hit = any(
                implicates(point, s, metric)
                for metric in ("h2_phase_cstd_rad", "h2_minus_2h1_cstd_rad"))
            point_hits.append(bool(hit))
        subsystem[s] = dict(
            point_hits=point_hits,
            implicated=bool(sum(point_hits) >= POINTS_REQUIRED))
    both_hits = [bool(any(
        implicates(point, "both", metric)
        for metric in ("h2_phase_cstd_rad", "h2_minus_2h1_cstd_rad")))
        for point in range(len(POINT_GRID))]

    h1_hits = []
    for point in range(len(POINT_GRID)):
        hit = any(implicates(point, cond, "h1_phase_cstd_rad")
                  for cond in ("gen", "acq", "both"))
        h1_hits.append(bool(hit))
    h1_reference_review = bool(sum(h1_hits) >= POINTS_REQUIRED)

    none_h2 = [block_of(point, "none")["h2_phase_cstd_rad"]
               for point in range(len(POINT_GRID))]
    environment_implicated = bool(
        float(np.median(none_h2)) >= ENVIRONMENT_H2_CSTD_RAD)
    none_bracket_max = max(
        block_of(point, "none")["dmm_bracket_norm_max"]
        for point in range(len(POINT_GRID)))
    dmm_bracket_reproduced_without_restart = bool(
        none_bracket_max > tt.DC_NORMALIZED_RMSE_LIMIT)

    return dict(
        thresholds=dict(
            restart_excess_min_rad=RESTART_EXCESS_MIN_RAD,
            restart_ratio_min=RESTART_RATIO_MIN,
            environment_h2_cstd_rad=ENVIRONMENT_H2_CSTD_RAD,
            points_required=POINTS_REQUIRED,
            dmm_bracket_norm_limit=tt.DC_NORMALIZED_RMSE_LIMIT),
        b_hat_V=float(b_hat), point_dc_medians_V=point_medians,
        blocks=blocks,
        interpretation=dict(
            gen_restart_implicated=subsystem["gen"]["implicated"],
            gen_point_hits=subsystem["gen"]["point_hits"],
            acq_restart_implicated=subsystem["acq"]["implicated"],
            acq_point_hits=subsystem["acq"]["point_hits"],
            both_condition_point_hits=both_hits,
            h1_reference_review=h1_reference_review,
            h1_point_hits=h1_hits,
            environment_implicated=environment_implicated,
            none_h2_phase_cstd_median_rad=float(np.median(none_h2)),
            none_dmm_bracket_norm_max=float(none_bracket_max),
            dmm_bracket_reproduced_without_restart=
            dmm_bracket_reproduced_without_restart,
            firmware_change_authorized=bool(
                (subsystem["gen"]["implicated"] or
                 subsystem["acq"]["implicated"]) and
                not environment_implicated)))


def _synthetic_arrays(rng, gen_h2_jitter_rad=0.0, all_h2_jitter_rad=0.0,
                      none_dmm_step_V=0.0):
    """Simple physics for the self-test: tight noise unless jitter injected."""
    schedule = build_schedule()
    n = TOTAL_REPEATS
    phi = np.pi * (schedule["bias"] - tt.CENTER_V) / tt.VPI_V
    base_h1 = 0.40 * np.sin(phi) + 0.05
    base_h2 = 0.25 * np.cos(phi) + 0.04
    t = 1_800_300_000.0 + 8.0 * np.arange(n, dtype=float)
    win = dict(source=np.repeat(np.arange(n), N_WINDOWS),
               index=np.tile(np.arange(N_WINDOWS), n))
    out = dict(schedule=schedule, t=t)
    for tag, base in (("1", base_h1), ("2", base_h2)):
        mag = np.abs(base) + 0.02
        phase = np.where(base >= 0, 0.15, 0.15 + np.pi)
        phase = phase + 0.001 * rng.standard_normal(n)
        restart_gen = schedule["restart_gen"] == 1
        if tag == "2":
            phase = phase + all_h2_jitter_rad * rng.standard_normal(n)
            phase = phase + np.where(
                restart_gen, gen_h2_jitter_rad, 0.0) * rng.standard_normal(n)
        mag = mag * (1.0 + 0.004 * rng.standard_normal(n))
        out[f"I{tag}"] = mag * np.cos(phase)
        out[f"Q{tag}"] = mag * np.sin(phase)
        wmag = np.repeat(mag, N_WINDOWS) * (
            1.0 + 0.004 * rng.standard_normal(n * N_WINDOWS))
        wphase = np.repeat(phase, N_WINDOWS) + 0.001 * rng.standard_normal(
            n * N_WINDOWS)
        win[f"I{tag}"] = wmag * np.cos(wphase)
        win[f"Q{tag}"] = wmag * np.sin(wphase)
    dc = 0.60 + 0.40 * np.cos(phi)
    none_mask = schedule["condition"] == "none"
    for name in ("pre1", "pre2", "post1", "post2"):
        noise = 0.0002 * rng.standard_normal(n)
        value = dc + noise
        if name.startswith("post") and none_dmm_step_V:
            value = value + np.where(none_mask, none_dmm_step_V, 0.0)
        out[name] = value
    out["win"] = win
    return out


def self_test():
    rng = np.random.default_rng(20260717)
    schedule = build_schedule()
    assert len(schedule["bias"]) == TOTAL_REPEATS == 240
    assert len(set(schedule["block_index"].tolist())) == TOTAL_BLOCKS == 20
    validate_schedule_arrays(**schedule)
    bridges = expected_bridges()
    step = grid_step()
    assert all(abs(b["delta_bias"]) <= step + 1e-12 for b in bridges)
    assert sum(b["is_target"] for b in bridges) == len(POINT_GRID)

    def run(**kwargs):
        data = _synthetic_arrays(rng, **kwargs)
        s = data["schedule"]
        return analyze_static_statistics(
            s["point_ordinal"], s["block_index"], s["condition"], data["t"],
            data["I1"], data["Q1"], data["I2"], data["Q2"],
            data["pre1"], data["pre2"], data["post1"], data["post2"],
            data["win"]["source"], data["win"]["index"],
            data["win"]["I1"], data["win"]["Q1"],
            data["win"]["I2"], data["win"]["Q2"])

    healthy = run()
    verdict = healthy["interpretation"]
    assert not verdict["gen_restart_implicated"]
    assert not verdict["acq_restart_implicated"]
    assert not verdict["environment_implicated"]
    assert not verdict["dmm_bracket_reproduced_without_restart"]
    assert not verdict["firmware_change_authorized"]

    gen_bad = run(gen_h2_jitter_rad=0.12)["interpretation"]
    assert gen_bad["gen_restart_implicated"]
    assert not gen_bad["acq_restart_implicated"]
    assert sum(gen_bad["both_condition_point_hits"]) >= POINTS_REQUIRED
    assert gen_bad["firmware_change_authorized"]

    common = run(all_h2_jitter_rad=0.12)["interpretation"]
    assert not common["gen_restart_implicated"]
    assert not common["acq_restart_implicated"]
    assert common["environment_implicated"]
    assert not common["firmware_change_authorized"]

    dmm_bad = run(none_dmm_step_V=0.05)["interpretation"]
    assert dmm_bad["dmm_bracket_reproduced_without_restart"]

    corrupted = build_schedule()
    corrupted["condition"] = corrupted["condition"].copy()
    corrupted["condition"][0] = "gen"
    try:
        validate_schedule_arrays(**corrupted)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted condition schedule was accepted")
    return dict(
        schedule_repeats=TOTAL_REPEATS, blocks=TOTAL_BLOCKS,
        bridge_rows=len(bridges), schedule_sha256=schedule_sha256(),
        healthy_clean=True, gen_injection_implicated=True,
        common_injection_exonerated=True, dmm_injection_detected=True,
        corrupted_schedule_rejected=True)


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, sort_keys=True))
