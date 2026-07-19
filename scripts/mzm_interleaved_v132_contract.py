#!/usr/bin/env python3
"""Pure analysis contracts shared by the MZM interleaved v1.3.2 tools."""
from __future__ import annotations

import copy
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure_bench as mb  # noqa: E402
import diagnose_mzm_interleaved_calibration as legacy  # noqa: E402
import mzm_interleaved_truth as v12  # noqa: E402
import mzm_interleaved_v132_truth as v13  # noqa: E402
import mzm_time_truth as tt  # noqa: E402


RAW_FIELDS = (
    "version", "scope", "expected", "used", "read_fail", "blocks",
    "complete", "timeout", "gain", "fs_uv", "guard", "crc", "ch0_min",
    "ch0_max", "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo",
    "ch0_guard_hi", "windows",
)
MAIN_HEADER = list(__import__(
    "diagnose_mzm_interleaved_calibration").MAIN_HEADER) + [
        "dmm_pre_read_count", "dmm_post_read_count",
        "discard_read_attempt_count", "formal_read_retry_count",
        "t_acq_first_attempt_start_unix",
]
WINDOW_HEADER = list(__import__(
    "diagnose_mzm_interleaved_calibration").WINDOW_HEADER) + [
        "read_attempt_count", "t_first_attempt_start_unix",
]
DISCARD_HEADER = list(__import__(
    "diagnose_mzm_interleaved_calibration").DISCARD_HEADER) + [
        "read_attempt_count", "t_first_attempt_start_unix",
]
CONDITIONING_HEADER = list(legacy.CONDITIONING_HEADER)
DMM_HEADER = [
    "dmm_sequence_index", "source_sequence_index", "side", "read_index",
    "t_start_unix", "t_end_unix", "t_mid_unix", "dc_dmm",
]


def selected_xy(fields, components):
    if (not isinstance(components, (list, tuple, np.ndarray)) or
            len(components) != 2 or
            any(str(value) not in ("I", "Q") for value in components)):
        raise ValueError("v1.3 components must contain H2 then H1 I/Q choices")
    return (
        np.asarray(fields[f"{components[0]}2"], float),
        np.asarray(fields[f"{components[1]}1"], float),
    )


def _raw_arrays(rows):
    return {name: np.asarray([row[f"rawadc_{name}"] for row in rows])
            for name in RAW_FIELDS}


def _exact_raw_capture_pass(rows, blocks, windows):
    expected = int(blocks) * 1280
    return bool(rows and all(
        int(row["rawadc_version"]) == 1 and
        str(row["rawadc_scope"]) == "acq" and
        int(row["rawadc_expected"]) == expected and
        int(row["rawadc_used"]) == expected and
        int(row["rawadc_read_fail"]) == 0 and
        int(row["rawadc_blocks"]) == int(blocks) and
        bool(row["rawadc_complete"]) and
        not bool(row["rawadc_timeout"]) and
        int(row["rawadc_gain"]) == tt.ADC_RAW_GAIN and
        int(row["rawadc_fs_uv"]) == tt.ADC_RAW_FS_UV and
        int(row["rawadc_guard"]) == tt.ADC_RAW_GUARD_ABS_CODE and
        int(row["rawadc_windows"]) == int(windows) and
        -8388608 <= int(row["rawadc_ch0_min"]) <=
        int(row["rawadc_ch0_max"]) <= 8388607 and
        all(int(row[f"rawadc_{name}"]) >= 0 for name in (
            "ch0_rail_lo", "ch0_rail_hi", "ch0_guard_lo", "ch0_guard_hi"))
        for row in rows))


def analyze_segment(stage, segment_index, rows, windows, discards,
                    conditioning, dmm_reads, pilot_verification,
                    read_failures):
    """Replay the acquisition-only contract for one v1.3.2 segment."""
    if stage not in ("donor", "recipient"):
        raise ValueError("v1.3 stage must be donor or recipient")
    start, end = v13.segment_bounds(segment_index)
    n_avg = (v13.DONOR_N_AVG if stage == "donor"
             else v13.RECIPIENT_N_AVG)
    schedule = v13.build_schedule()
    schedule_pass = False
    try:
        schedule_pass = v12.validate_schedule_arrays(
            role=[row["role"] for row in rows],
            direction=[row["direction"] for row in rows],
            grid_index=[row["grid_index"] for row in rows],
            target_ordinal=[row["target_ordinal"] for row in rows],
            pair_position=[row["pair_position"] for row in rows],
            bias=[row["bias"] for row in rows],
            approach_bias=[row["approach_bias"] for row in rows],
            sequence_index=[row["sequence_index"] for row in rows],
            start=start, end=end)
    except Exception:
        schedule_pass = False
    records = v13.schedule_records(schedule)[start:end]
    expected_bridges = legacy._expected_bridges(records)
    conditioning_pass = bool(
        len(conditioning) == len(expected_bridges) and all(
            all(int(row[name]) == int(expected[name]) for name in (
                "sequence_index", "observation_sequence_index",
                "bridge_step_index")) and
            all(np.isclose(float(row[name]), float(expected[name]),
                           atol=1e-12, rtol=0) for name in (
                               "from_bias", "bias", "delta_bias")) and
            abs(float(row["delta_bias"])) <=
            2.0 * tt.VPI_V / (tt.POINTS_PER_LEG - 1) + 1e-12 and
            float(row["t_start_unix"]) < float(row["t_end_unix"]) and
            np.isfinite(float(row["dc_dmm"]))
            for row, expected in zip(conditioning, expected_bridges)))
    expected_keys = {str(value) for value in range(start, end)}
    pilot_pass = bool(
        set(pilot_verification) == expected_keys and all(
            value.get("verified", False) and
            value.get("pilot_count_pass", False) and
            value.get("frequency_pass", False) and
            value.get("amplitude_pass", False) and
            value.get("acquisition_count_pass", False) and
            value.get("acquisition_frequencies_pass", False) and
            int(value.get("source_sequence_index", -1)) == int(key) and
            np.isclose(float(value.get("expected_amplitude_V", np.nan)),
                       v13.PILOT_V, atol=0, rtol=0)
            for key, value in pilot_verification.items()))
    discard_pass = bool(
        len(rows) == end - start and len(discards) == len(rows) and all(
            int(discard["transition_discard_index"]) == index and
            int(discard["source_sequence_index"]) == int(row["sequence_index"]) and
            all(str(discard[name]) == str(row[name]) for name in
                ("role", "direction")) and
            all(int(discard[name]) == int(row[name]) for name in
                ("grid_index", "target_ordinal", "pair_position")) and
            np.isclose(float(discard["bias"]), float(row["bias"]),
                       atol=0, rtol=0) and
            int(row["transition_discard_index"]) == index and
            bool(row["transition_followed_without_reconfigure"]) and
            float(discard["t_start_unix"]) < float(discard["t_end_unix"]) <=
            float(row["t_acq_start_unix"]) and
            float(row["t_acq_first_attempt_start_unix"]) -
            float(discard["t_end_unix"]) <= v13.DISCARD_TO_FORMAL_MAX_S
            for index, (discard, row) in enumerate(zip(discards, rows))))
    discard_capture_pass = bool(
        _exact_raw_capture_pass(discards, v13.DISCARD_BLOCKS, 1) and
        tt.analyze_adc_raw_telemetry(**_raw_arrays(discards)).get(
            "contract_pass", False))
    window_pass = bool(
        len(windows) == len(rows) * n_avg and all(
            int(window["window_sequence_index"]) == index and
            int(window["source_sequence_index"]) ==
            int(rows[index // n_avg]["sequence_index"]) and
            int(window["window_index"]) == index % n_avg and
            all(str(window[name]) == str(rows[index // n_avg][name])
                for name in ("role", "direction")) and
            all(int(window[name]) == int(rows[index // n_avg][name])
                for name in ("grid_index", "target_ordinal", "pair_position")) and
            np.isclose(float(window["bias"]),
                       float(rows[index // n_avg]["bias"]), atol=0, rtol=0) and
            float(window["t_start_unix"]) < float(window["t_end_unix"])
            for index, window in enumerate(windows)) and
        _exact_raw_capture_pass(windows, v13.N_BLOCKS, 1))
    formal_raw = (tt.analyze_adc_raw_telemetry(**_raw_arrays(windows))
                  if windows else {"accepted": False})
    formal_raw_pass = bool(formal_raw.get("accepted", False))
    max_code = (max(max(abs(int(row["rawadc_ch0_min"])),
                        abs(int(row["rawadc_ch0_max"]))) for row in windows)
                if windows else 8388608)
    headroom_pass = bool(max_code <= v13.HEADROOM_LIMIT_CODE)
    dmm_result = validate_dmm_reads(rows, dmm_reads)
    retry_result = validate_read_failures(
        rows, windows, discards, read_failures)
    timing_pass = bool(rows and all(
        np.isclose(float(row["bias_settle_s"]), v13.BIAS_SETTLE_S,
                   atol=0, rtol=0) and
        float(row["t_target_set_unix"]) -
        float(row["t_approach_set_unix"]) >= v13.BIAS_SETTLE_S - 1e-3 and
        float(row["t_discard_start_unix"]) -
        float(row["t_target_set_unix"]) >= v13.BIAS_SETTLE_S - 1e-3
        for row in rows))
    gates = dict(
        schedule_contract_pass=bool(schedule_pass),
        conditioning_contract_pass=conditioning_pass,
        pilot_configuration_pass=pilot_pass,
        discard_contract_pass=discard_pass,
        discard_capture_pass=discard_capture_pass,
        formal_window_contract_pass=window_pass,
        formal_raw_pass=formal_raw_pass,
        formal_headroom_pass=headroom_pass,
        dmm_read_contract_pass=bool(dmm_result["accepted"]),
        read_failure_contract_pass=bool(retry_result["accepted"]),
        timing_contract_pass=timing_pass)
    required = tuple(gates)
    gates["required_pass_fields"] = required
    gates["accepted"] = bool(all(gates[name] for name in required))
    return dict(
        protocol_version=(v13.DONOR_PROTOCOL_VERSION if stage == "donor"
                          else v13.PROTOCOL_VERSION),
        stage=stage, segment_index=int(segment_index),
        quality_gate=gates, dmm_read_statistics=dmm_result,
        read_failure_statistics=retry_result,
        observations=len(rows), windows=len(windows), discards=len(discards),
        conditioning_rows=len(conditioning), dmm_reads=len(dmm_reads),
        formal_max_abs_raw_V=float(max_code * 1.2 / 8388608.0),
        independent_optical_truth=False, headline_promotion=False,
        v1_4_authorization_ready=False)


def validate_dmm_reads(rows, dmm_reads):
    """Replay all 8+8 readings and their observation-level means/times."""
    n = len(rows)
    if len(dmm_reads) != n * 2 * v13.DMM_READS_PER_SIDE:
        return dict(accepted=False, reason="DMM read count differs")
    expected_sequence = 0
    side_std = []
    side_range = []
    adjacent = []
    try:
        for row in rows:
            observation = int(row["sequence_index"])
            groups = {}
            for side in ("pre", "post"):
                group = [value for value in dmm_reads
                         if int(value["source_sequence_index"]) == observation and
                         str(value["side"]) == side]
                group.sort(key=lambda value: int(value["read_index"]))
                if len(group) != v13.DMM_READS_PER_SIDE:
                    raise ValueError(f"observation {observation} {side} count differs")
                if [int(value["read_index"]) for value in group] != list(
                        range(v13.DMM_READS_PER_SIDE)):
                    raise ValueError(f"observation {observation} {side} order differs")
                for value in group:
                    if int(value["dmm_sequence_index"]) != expected_sequence:
                        raise ValueError("DMM global sequence differs")
                    expected_sequence += 1
                    start = float(value["t_start_unix"])
                    end = float(value["t_end_unix"])
                    midpoint = float(value["t_mid_unix"])
                    dc = float(value["dc_dmm"])
                    if not (np.isfinite(dc) and start < end and np.isclose(
                            midpoint, 0.5 * (start + end), atol=1e-9, rtol=0)):
                        raise ValueError("DMM read value/time is invalid")
                values = np.asarray([float(value["dc_dmm"]) for value in group])
                times = np.asarray([float(value["t_mid_unix"]) for value in group])
                side_std.append(float(np.std(values, ddof=1)))
                side_range.append(float(np.ptp(values)))
                adjacent.extend(np.abs(np.diff(values)).tolist())
                groups[side] = (group, values, times)
            pre, post = groups["pre"], groups["post"]
            if not (max(float(value["t_end_unix"]) for value in pre[0]) <=
                    float(row["t_acq_start_unix"]) and
                    float(row["t_acq_end_unix"]) <=
                    min(float(value["t_start_unix"]) for value in post[0])):
                raise ValueError("DMM reads do not bracket formal acquisition")
            expected = dict(
                dc_dmm_pre=float(np.mean(pre[1])),
                dc_dmm_post=float(np.mean(post[1])),
                t_dmm_pre_mid_unix=float(np.mean(pre[2])),
                t_dmm_post_mid_unix=float(np.mean(post[2])),
                t_dmm_pre_start_unix=float(pre[0][0]["t_start_unix"]),
                t_dmm_pre_end_unix=float(pre[0][-1]["t_end_unix"]),
                t_dmm_post_start_unix=float(post[0][0]["t_start_unix"]),
                t_dmm_post_end_unix=float(post[0][-1]["t_end_unix"]),
            )
            if any(not np.isclose(float(row[name]), value, atol=1e-12, rtol=0)
                   for name, value in expected.items()):
                raise ValueError("observation DMM mean/time differs from raw reads")
            if (int(row["dmm_pre_read_count"]) != v13.DMM_READS_PER_SIDE or
                    int(row["dmm_post_read_count"]) !=
                    v13.DMM_READS_PER_SIDE):
                raise ValueError("observation DMM count mirror differs")
    except Exception as exc:
        return dict(accepted=False, reason=str(exc))
    return dict(
        accepted=True, reason=None,
        side_std_median_V=float(np.median(side_std)),
        side_std_p95_V=float(np.percentile(side_std, 95)),
        side_range_median_V=float(np.median(side_range)),
        side_range_p95_V=float(np.percentile(side_range, 95)),
        adjacent_abs_diff_median_V=float(np.median(adjacent)),
        adjacent_abs_diff_p95_V=float(np.percentile(adjacent, 95)),
    )


def validate_read_failures(rows, windows, discards, failures):
    """Reconcile all invalid-read attempts with successful-record counters."""
    expected = []
    try:
        sequence_values = {int(row["sequence_index"]) for row in rows}
        for value in failures:
            phase = str(value["phase"])
            observation = int(value["source_sequence_index"])
            window = value.get("window_index")
            attempt = int(value["attempt_index"])
            start = float(value["t_start_unix"])
            end = float(value["t_end_unix"])
            reason = str(value["reason"])
            if phase not in ("discard", "formal") or observation not in sequence_values:
                raise ValueError("read failure identity differs")
            if not (0 <= attempt < v13.ACQ_READ_ATTEMPTS - 1 and start < end and reason):
                raise ValueError("read failure attempt/time/reason is invalid")
            if phase == "discard":
                if window is not None:
                    raise ValueError("discard read failure has a window index")
            elif window is None or not (0 <= int(window) < v13.DONOR_N_AVG):
                raise ValueError("formal read failure window is invalid")
            expected.append((observation, phase, None if window is None else int(window)))
        for row in rows:
            observation = int(row["sequence_index"])
            discard_count = sum(1 for item in expected if item == (
                observation, "discard", None))
            formal_count = sum(1 for item in expected
                               if item[0] == observation and item[1] == "formal")
            if int(row["discard_read_attempt_count"]) != discard_count + 1:
                raise ValueError("discard retry mirror differs")
            if int(row["formal_read_retry_count"]) != formal_count:
                raise ValueError("formal retry mirror differs")
        for record in discards:
            key = (int(record["source_sequence_index"]), "discard", None)
            if int(record["read_attempt_count"]) != expected.count(key) + 1:
                raise ValueError("discard record attempt count differs")
            if not np.isclose(float(record["t_first_attempt_start_unix"]),
                              min([float(value["t_start_unix"]) for value in failures
                                   if (int(value["source_sequence_index"]),
                                       str(value["phase"]), value.get("window_index")) == key]
                                  + [float(record["t_start_unix"])]),
                              atol=0, rtol=0):
                raise ValueError("discard first-attempt time differs")
        for record in windows:
            key = (int(record["source_sequence_index"]), "formal",
                   int(record["window_index"]))
            if int(record["read_attempt_count"]) != expected.count(key) + 1:
                raise ValueError("formal record attempt count differs")
    except Exception as exc:
        return dict(accepted=False, reason=str(exc), failures=len(failures))
    return dict(
        accepted=True, reason=None, failures=len(failures),
        discard_retries=sum(1 for value in failures
                            if str(value["phase"]) == "discard"),
        formal_retries=sum(1 for value in failures
                           if str(value["phase"]) == "formal"),
    )


def _time_truth(fields):
    return tt.analyze_time_truth(
        time_unix=np.asarray(fields["t_acq_mid_unix"], float),
        bias=np.asarray(fields["bias"], float),
        dc=np.asarray(fields["dc_dmm_interp"], float),
        role=np.asarray(fields["role"]),
        direction=np.asarray(fields["direction"]),
        sequence_index=np.asarray(fields["sequence_index"], int),
        dc_board=np.asarray(fields["dc_board"], float))


def donor_science(rows, windows, components):
    fields = {name: np.asarray([row[name] for row in rows])
              for name in MAIN_HEADER if name in rows[0]}
    window_fields = {name: np.asarray([row[name] for row in windows])
                     for name in WINDOW_HEADER if name in windows[0]}
    result = _time_truth(fields)
    phase_truth = np.asarray(result["fit"]["phase_truth"], float)
    window_x, window_y = selected_xy(window_fields, components)
    halves = v13.donor_half_means(
        window_fields["source_sequence_index"], window_fields["window_index"],
        window_x, window_y)
    correction = v13.derive_spur_correction(
        halves["X_A"], halves["Y_A"], halves["X_B"], halves["Y_B"],
        phase_truth, fields["role"], fields["direction"],
        fields["grid_index"], fields["bias"], components)
    return dict(time_truth=result, spur_correction=correction)


def recipient_science(rows, components, table):
    fields = {name: np.asarray([row[name] for row in rows])
              for name in MAIN_HEADER if name in rows[0]}
    raw_x, raw_y = selected_xy(fields, components)
    corrected_x, corrected_y = v13.apply_spur_correction(
        raw_x, raw_y, fields["grid_index"], fields["bias"], table,
        components)
    base = _time_truth(fields)
    uncorrected = v12.attach_shared_phase_reference(
        copy.deepcopy(base), raw_x, raw_y, fields["role"], fields["bias"])
    uncorrected_mapping = v12.analyze_all_mapping_stability(
        raw_x, raw_y, uncorrected["fit"]["phase_truth"], fields["role"],
        fields["direction"], fields["pair_position"],
        fields["target_ordinal"])
    corrected = v12.attach_shared_phase_reference(
        copy.deepcopy(base), corrected_x, corrected_y, fields["role"],
        fields["bias"])
    corrected_mapping = v12.analyze_all_mapping_stability(
        corrected_x, corrected_y, corrected["fit"]["phase_truth"],
        fields["role"], fields["direction"], fields["pair_position"],
        fields["target_ordinal"])
    corrected = v12.require_direction_mapping(corrected, corrected_mapping)
    return dict(
        corrected=corrected, corrected_mapping=corrected_mapping,
        uncorrected=uncorrected, uncorrected_mapping=uncorrected_mapping,
        correction_table_sha256=str(table["table_sha256"]))


def self_test():
    schedule = v13.build_schedule()
    dmm_rows = []
    rows = []
    clock = 1_800_500_000.0
    for observation in range(162):
        pre_values = []
        post_values = []
        pre_times = []
        post_times = []
        for side, target, times in (("pre", pre_values, pre_times),
                                    ("post", post_values, post_times)):
            if side == "post":
                clock += 4.0
            for read_index in range(v13.DMM_READS_PER_SIDE):
                start = clock
                end = start + 0.05
                value = 0.6 + 0.4 * np.cos(
                    np.pi * (schedule["bias"][observation] - tt.CENTER_V) /
                    tt.VPI_V) + (read_index - 3.5) * 1e-4
                dmm_rows.append(dict(
                    dmm_sequence_index=len(dmm_rows),
                    source_sequence_index=observation, side=side,
                    read_index=read_index, t_start_unix=start,
                    t_end_unix=end, t_mid_unix=0.5 * (start + end),
                    dc_dmm=value))
                target.append(value)
                times.append(0.5 * (start + end))
                clock = end
        acq_start = pre_times[-1] + 0.1
        acq_end = post_times[0] - 0.1
        acq_mid = 0.5 * (acq_start + acq_end)
        pre_mid = float(np.mean(pre_times))
        post_mid = float(np.mean(post_times))
        weight = (acq_mid - pre_mid) / (post_mid - pre_mid)
        rows.append(dict(
            sequence_index=observation, bias=schedule["bias"][observation],
            t_dmm_pre_start_unix=dmm_rows[-16]["t_start_unix"],
            t_dmm_pre_end_unix=dmm_rows[-9]["t_end_unix"],
            t_dmm_pre_mid_unix=pre_mid, dc_dmm_pre=np.mean(pre_values),
            t_acq_start_unix=acq_start, t_acq_end_unix=acq_end,
            t_acq_mid_unix=acq_mid,
            t_dmm_post_start_unix=dmm_rows[-8]["t_start_unix"],
            t_dmm_post_end_unix=dmm_rows[-1]["t_end_unix"],
            t_dmm_post_mid_unix=post_mid, dc_dmm_post=np.mean(post_values),
            dmm_pre_read_count=8, dmm_post_read_count=8,
            dmm_interpolation_weight=weight,
            dc_dmm_interp=np.mean(pre_values) + weight * (
                np.mean(post_values) - np.mean(pre_values))))
        clock += 0.1
    result = validate_dmm_reads(rows, dmm_rows)
    assert result["accepted"]
    broken = list(dmm_rows)
    broken.pop()
    assert not validate_dmm_reads(rows, broken)["accepted"]
    return dict(
        healthy_dmm_contract=True, missing_dmm_read_rejected=True,
        dmm_rows=len(dmm_rows), side_std_median_V=result["side_std_median_V"])


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, sort_keys=True))
