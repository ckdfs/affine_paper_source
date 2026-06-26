#!/usr/bin/env python3
"""Hardware-in-the-loop driver for the single-MZM experimental validation.

Drives the bench through the three packaged skills' helper classes and runs the
PC-side affine + baseline controllers (the board is ONLY a pilot/bias generator
and harmonic acquirer; the on-board lock is never used as a baseline).

  biasboard  : pilot + bias generator, Goertzel harmonic acquirer (gen/acq)
  dm858e     : PD DC (optical power, unclipped) -> phase truth + gauge fixing
  sds824xhd  : TIA AC FFT cross-check of H1/H2

Run under an interpreter with numpy/scipy/pyserial (the build.py figure-python,
e.g. /opt/miniconda3/bin/python3).  Stages (CLAUDE.md rule #5: never fabricate;
unmeasured stays "待测"):

  bringup   sanity: board state, board-CH1 vs DMM (find the CH1 clip region)
  vpi       stage 0: slow bias sweep, DMM P(V_b) -> Vpi, V0
  calib     stage 1: full-period sweep, fit ellipse + gauge fix -> calib_fit.json, fig metric
  lock      stage 2: >=16 phi* grid, affine vs H1-match baseline -> lock_sweep
  pilot     stage 3: sweep pilot amplitude Ap -> kappa(A), residual vs phi
  drift     stage 4: inject step, residual-triggered recal -> latency, recovery
  rf        stage 5: arbitrary-point lock robustness under an applied out-of-band
            RF drive (DG922pro 50 MHz on the MZM RF port, FSV30 verifies the tone
            at DE2) -> lock rms RF-on vs RF-off + J0(m_RF) harmonic fading

  --sim     replace the bench with an analytic MZM model; writes ONLY to
            build/exp_sim/ (gitignored).  For tooling validation, NOT the paper.

Data (real runs) lands in data/exp/ ; see scripts/exp_common.py for the layout.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import csv
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as ec  # noqa: E402

# bench constants ----------------------------------------------------------- #
PILOT_HZ = 1000.0          # board default pilot
H2_HZ = 2000.0             # second harmonic
PILOT_V = 0.10             # default pilot amplitude (V on the bias line)
CH = "A"                   # default MZM bias DAC channel
BIAS_LIMIT = 9.0           # keep |bias|+|pilot| < 10 V (board clips otherwise)
ACQ_FREQS = (PILOT_HZ, H2_HZ)
RF_HZ = 50e6               # default applied RF tone (stage 5 robustness)
RF_CH = 1                  # DG922pro channel feeding the MZM RF port


def dbm_to_vpp(dbm: float, load_ohm: float = 50.0) -> float:
    """Sine power in dBm (into load_ohm) -> peak-to-peak volts (DG922pro units)."""
    vrms = np.sqrt(1e-3 * 10 ** (dbm / 10.0) * load_ohm)
    return float(2.0 * np.sqrt(2.0) * vrms)


def vpp_to_dbm(vpp: float, load_ohm: float = 50.0) -> float:
    vrms = vpp / (2.0 * np.sqrt(2.0))
    return float(10.0 * np.log10((vrms ** 2 / load_ohm) / 1e-3))


def rf_depth(vpp: float, vpi: float) -> float:
    """RF modulation depth m_RF = pi * V_peak / Vpi for a Vpp sine drive."""
    return float(np.pi * (vpp / 2.0) / vpi)

SKILL_ROOTS = (
    "/Users/ckdfs/.cc-switch/skills",
    "/Users/ckdfs/.claude/skills",
)


# --------------------------------------------------------------------------- #
#  lazy skill imports (only when talking to real hardware)                    #
# --------------------------------------------------------------------------- #
def _skill(mod):
    for root in SKILL_ROOTS:
        p = os.path.join(root, mod, "scripts")
        if os.path.isdir(p):
            break
    else:
        roots = ", ".join(SKILL_ROOTS)
        raise FileNotFoundError(f"Cannot find skill helper {mod!r} under {roots}")
    if p not in sys.path:
        sys.path.insert(0, p)


def open_board():
    _skill("biasboard")
    from biasboard import BiasBoard
    return BiasBoard()


def open_dmm():
    _skill("dm858e")
    from dm858e import DM858E
    return DM858E()


def open_scope():
    _skill("sds824xhd")
    from sds824xhd import SDS824XHD
    return SDS824XHD()


def open_siggen():
    _skill("dg922pro")
    from dg922pro import DG922Pro
    return DG922Pro()


def open_specan():
    _skill("fsv30")
    from fsv30 import FSV30
    return FSV30()


# --------------------------------------------------------------------------- #
#  observation vector  z = (X = comp@2k, Y = comp@1k)                          #
# --------------------------------------------------------------------------- #
def obs_vector(acq: dict, comps=("I", "I")) -> np.ndarray:
    """Build z=(X,Y) from an acq_run() result. comps[0] for H2(2k)->X,
    comps[1] for H1(1k)->Y; each 'I' or 'Q'."""
    t2 = acq["tones"][H2_HZ]
    t1 = acq["tones"][PILOT_HZ]
    return np.array([t2[comps[0]], t1[comps[1]]])


def choose_comps(I1, Q1, I2, Q2):
    """Pick, per harmonic, the lock-in component (I or Q) carrying the larger
    sweep variance — robust to the board's unknown reference phase."""
    c1 = "I" if np.var(I1) >= np.var(Q1) else "Q"
    c2 = "I" if np.var(I2) >= np.var(Q2) else "Q"
    return (c2, c1)  # (for X@2k, for Y@1k)


def configure_dc_fast(dmm):
    if dmm is not None and hasattr(dmm, "configure_dc_voltage"):
        dmm.configure_dc_voltage(vrange="AUTO", nplc=1)
        setattr(dmm, "_exp_dc_configured", True)


def read_dc(dmm):
    if dmm is None:
        return float("nan")
    if getattr(dmm, "_exp_dc_configured", False) and hasattr(dmm, "read"):
        return dmm.read()
    return dmm.measure_dc_voltage()


def prepare_mzm_frontend(board, pilot_v):
    """Configure the real board once for repeated MZM points. Subsequent points
    only update gen bias and run acq, avoiding acq_run_mzm's per-point reset.

    The acq_add commands occasionally get dropped on the USB-serial link right
    after a prior run, leaving the board with zero acq frequencies (then acq_run
    raises "no acquisition frequencies").  Verify they registered via acq_show and
    retry a couple of times so every stage is robust to that flaky drop."""
    if isinstance(board, SimBoard):
        return
    for _ in range(3):
        board.gen_reset()
        board.gen_bias(CH, 0.0)
        board.gen_pilot(CH, PILOT_HZ, pilot_v)
        board.acq_reset()
        for f in ACQ_FREQS:
            board.acq_add(f)
        time.sleep(0.4)
        try:
            if f"freqs: {len(ACQ_FREQS)}" in board.acq_show():
                return
        except Exception:
            return                     # acq_show unsupported -> assume it took
    print("[warn] prepare_mzm_frontend: acq freqs not confirmed after retries")


def acq_point_prepared(board, dmm, bias, pilot_v, n_blocks):
    if isinstance(board, SimBoard):
        return acq_point(board, dmm, bias, pilot_v, n_blocks)
    board.gen_bias(CH, bias)
    acq = board.acq_run(n_blocks)
    return acq, read_dc(dmm)


def _valid_acq(acq):
    return (acq and acq.get("dc") is not None and
            PILOT_HZ in acq.get("tones", {}) and H2_HZ in acq.get("tones", {}))


def average_acq_point(board, dmm, bias, pilot_v, n_blocks, n_avg=1,
                      max_retries=2):
    """Average several stable short acq windows. This avoids the board's
    long-window acq-run timing issue while improving H2 SNR."""
    if n_avg <= 1:
        acq, dc = acq_point_prepared(board, dmm, bias, pilot_v, n_blocks)
        if not _valid_acq(acq):
            raise RuntimeError(f"invalid acq at bias={bias:+.4f}: {acq!r}")
        return acq, dc
    acc = None; dcs = []
    tries = 0
    while len(dcs) < n_avg:
        acq, _ = acq_point_prepared(board, None, bias, pilot_v, n_blocks)
        tries += 1
        if not _valid_acq(acq):
            if tries <= n_avg + max_retries:
                continue
            raise RuntimeError(f"invalid acq at bias={bias:+.4f}: {acq!r}")
        dcs.append(acq["dc"])
        if acc is None:
            acc = {"blocks": acq.get("blocks"), "dc": 0.0, "tones": {
                PILOT_HZ: {"I": 0.0, "Q": 0.0},
                H2_HZ: {"I": 0.0, "Q": 0.0}}}
        acc["dc"] += acq["dc"]
        for f in (PILOT_HZ, H2_HZ):
            acc["tones"][f]["I"] += acq["tones"][f]["I"]
            acc["tones"][f]["Q"] += acq["tones"][f]["Q"]
    acc["dc"] /= n_avg
    for f in (PILOT_HZ, H2_HZ):
        t = acc["tones"][f]
        t["I"] /= n_avg; t["Q"] /= n_avg
        t["mag"] = float(np.hypot(t["I"], t["Q"]))
        t["phase"] = float(np.arctan2(t["Q"], t["I"]))
    return acc, read_dc(dmm)


# --------------------------------------------------------------------------- #
#  analytic MZM model for --sim (tooling validation only; build/exp_sim/)     #
# --------------------------------------------------------------------------- #
class SimBoard:
    """Stand-in for BiasBoard returning model H1/H2/DC. Mirrors the affine
    structure of make_figs.py (gain mismatch, ref-phase skew, offsets, noise)."""
    VPI, V0 = 5.5, -1.3
    A1, A2 = 0.42, 0.27           # H1/H2 amplitudes
    DELTA = np.deg2rad(12)        # reference-phase skew (lands some signal in Q)
    BX, BY = 0.018, -0.011        # observation offsets
    SIGMA = 0.004
    DC_A, DC_B = 0.80, 0.69       # PD DC: a + b cos(phi) (peak ~1.49 V)
    CH1_FS = 1.20                 # board CH1 ADC full scale (clips)

    def __init__(self, seed=7):
        self.rng = np.random.default_rng(seed)
        self._gx, self._gy = 1.0, 1.0
        self._j0 = 1.0          # out-of-band RF fading factor J0(m_RF) (stage 5)
        self._rf_dbm = -120.0   # last RF drive level the sig-gen reported

    def _phi(self, bias):
        return np.pi * (bias - self.V0) / self.VPI

    def _fringe(self, phi):
        """Slow-detected fringe amplitude. An out-of-band RF tone is averaged by
        the PD to J0(m_RF) (theorem: only the cos(phi) term fades, the DC pedestal
        does not), so the visibility scales by self._j0 while the phase is intact."""
        return self.DC_B * self._j0 * np.cos(phi)

    def acq_run_mzm(self, bias, pilot_hz=PILOT_HZ, pilot_v=PILOT_V, ch=CH,
                    acq_freqs=ACQ_FREQS, n_blocks=10):
        phi = self._phi(bias)
        m = np.pi * pilot_v / self.VPI            # pilot depth scales amplitudes
        a1 = self.A1 * min(1.0, m / 0.06) * self._j0   # RF fades the AC harmonics
        a2 = self.A2 * min(1.0, (m / 0.06) ** 2) * self._j0
        s = self.SIGMA / np.sqrt(max(1, n_blocks))
        # H1 ~ sin(phi+delta), split into I/Q by the skew; H2 ~ cos(phi)
        Y = self.BY + self._gy * a1 * np.sin(phi)
        X = self.BX + self._gx * a2 * np.cos(phi)
        I1 = Y * np.cos(self.DELTA) + s * self.rng.standard_normal()
        Q1 = Y * np.sin(self.DELTA) + s * self.rng.standard_normal()
        I2 = X + s * self.rng.standard_normal()
        Q2 = 0.20 * X + s * self.rng.standard_normal()
        dc_true = self.DC_A + self._fringe(phi)
        dc_board = min(dc_true, self.CH1_FS)      # board CH1 clips
        return {"blocks": n_blocks, "dc": dc_board, "tones": {
            PILOT_HZ: {"I": I1, "Q": Q1, "mag": float(np.hypot(I1, Q1)),
                       "phase": float(np.arctan2(Q1, I1))},
            H2_HZ: {"I": I2, "Q": Q2, "mag": float(np.hypot(I2, Q2)),
                    "phase": float(np.arctan2(Q2, I2))}}}

    def dc_true_at(self, bias):
        """Unclipped PD DC (what the DMM sees) at an arbitrary bias."""
        return float(self.DC_A + self._fringe(self._phi(bias)))

    def set_drift(self, gx=None, gy=None):
        if gx is not None: self._gx = gx
        if gy is not None: self._gy = gy

    def set_rf(self, m_rf, dbm=-120.0):
        """Apply an out-of-band RF tone of modulation depth m_rf -> J0(m_rf)."""
        from scipy.special import j0 as _besselj0
        self._j0 = float(_besselj0(m_rf))
        self._rf_dbm = float(dbm)


class SimSigGen:
    """Stand-in for DG922Pro driving the MZM RF port: a sine on the RF port
    averages to a J0(m_RF) fade of the slow MZM observation (set on the board)."""
    def __init__(self, board: SimBoard, vpi=None):
        self.b = board
        self.vpi = vpi or board.VPI
        self._on = False
        self._vpp = 0.0

    def set_load(self, channel, load):
        pass

    def setup_waveform(self, channel=RF_CH, waveform="SINusoid", freq=RF_HZ,
                       amp=1.0, offset=0.0, phase=0.0):
        self._vpp = float(amp)

    def set_amplitude(self, channel, amp):
        self._vpp = float(amp)
        if self._on:
            self._apply()

    def output_on(self, channel=RF_CH):
        self._on = True
        self._apply()

    def output_off(self, channel=RF_CH):
        self._on = False
        self.b.set_rf(0.0)

    def _apply(self):
        m_rf = rf_depth(self._vpp, self.vpi)
        self.b.set_rf(m_rf, dbm=vpp_to_dbm(self._vpp) if self._vpp > 0 else -120.0)


class SimSpecAn:
    """Stand-in for FSV30 reading the applied tone at DE2 (a fixed insertion loss
    below the electrical drive level the sig-gen put out)."""
    IL_DB = 6.0

    def __init__(self, board: SimBoard):
        self.b = board

    def setup_frequency(self, center, span):
        pass

    def single_sweep(self):
        pass

    def wait_for_sweep(self, timeout_s=30.0):
        return True

    def marker_on(self, marker=1):
        pass

    def marker_set_freq(self, freq, marker=1):
        pass

    def marker_read(self, marker=1):
        lvl = (self.b._rf_dbm - self.IL_DB) if self.b._rf_dbm > -100 else -120.0
        return (RF_HZ, float(lvl))


class SimDMM:
    """Stand-in for DM858E: unclipped PD DC (= optical power)."""
    def __init__(self, board: SimBoard):
        self.b = board

    def measure_dc_voltage(self):
        # the DMM sees the unclipped DC at the current sim bias (set by caller)
        return self.b._last_dc_true

    def configure_dc_voltage(self, **k):
        pass

    def read(self):
        return self.measure_dc_voltage()


# --------------------------------------------------------------------------- #
#  acquisition helpers that work for both real and sim board                  #
# --------------------------------------------------------------------------- #
def read_dc_at_bias(board, dmm, bias, settle=0.15):
    """Set the bias and read the (unclipped) DMM DC there. Used for the
    drift-robust, controller-independent per-point phase truth in stage_lock."""
    if isinstance(board, SimBoard):
        board._last_dc_true = board.dc_true_at(bias)
        return board.dc_true_at(bias) if dmm is None else dmm.measure_dc_voltage()
    board.gen_bias(CH, bias)
    time.sleep(settle)
    return read_dc(dmm)


def acq_point(board, dmm, bias, pilot_v, n_blocks):
    """One measurement point: set bias+pilot, acquire H1/H2/board-DC, read DMM
    DC. Returns (acq_dict, dc_dmm)."""
    if isinstance(board, SimBoard):
        board._last_dc_true = board.dc_true_at(bias)
        acq = board.acq_run_mzm(bias=bias, pilot_v=pilot_v, n_blocks=n_blocks)
        dc_dmm = dmm.measure_dc_voltage() if dmm else float("nan")
        return acq, dc_dmm
    acq = board.acq_run_mzm(bias=bias, pilot_hz=PILOT_HZ, pilot_v=pilot_v,
                            ch=CH, acq_freqs=ACQ_FREQS, n_blocks=n_blocks)
    dc_dmm = read_dc(dmm)
    return acq, dc_dmm


# --------------------------------------------------------------------------- #
#  stages                                                                     #
# --------------------------------------------------------------------------- #
def stage_vpi(board, dmm, datadir, lo=-9.0, hi=9.0, n=151, pilot_v=PILOT_V):
    """Stage 0: BIDIRECTIONAL slow DC sweep (up then down).

    Bias drift during a one-way sweep biases the measured Vpi by the drift over
    a half-period (V_pi,meas = V_pi - dD); sweeping up AND down and averaging
    cancels it exactly (up: V_pi-dD, down: V_pi+dD), while the up/down Vpi/V0
    split directly quantifies the drift. The DMM P(V_b) feeds fig:exp0."""
    configure_dc_fast(dmm)
    prepare_mzm_frontend(board, pilot_v)
    up = np.linspace(lo, hi, n)
    csv_path = os.path.join(datadir, "vpi.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    rows = []
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bias", "dc_dmm", "dc_board", "dir"])
        for label, seq in (("up", up), ("down", up[::-1])):
            for i, V in enumerate(seq, 1):
                acq, dc_dmm = acq_point_prepared(board, dmm, float(V), pilot_v,
                                                 n_blocks=6)
                row = (float(V), float(dc_dmm), float(acq["dc"]), label)
                rows.append(row); w.writerow(row); f.flush()
                if i == 1 or i % 25 == 0 or i == n:
                    print(f"[vpi] {label:>4} {i:3d}/{n}  bias={V:+.2f}  "
                          f"DMM={dc_dmm:.4f}", flush=True)
    print(f"[io] wrote {os.path.relpath(csv_path, ec.REPO)} ({len(rows)} rows)")
    sel = lambda d, k: np.array([r[k] for r in rows if r[3] == d])
    au, bu, vpu, v0u = ec.fit_dc_transfer(sel("up", 0), sel("up", 1))
    ad, bd, vpd, v0d = ec.fit_dc_transfer(sel("down", 0), sel("down", 1))
    vpi = 0.5 * (vpu + vpd)                       # drift-unbiased
    v0_fit = 0.5 * (v0u + v0d)
    v0 = ec.canonical_period_center(v0_fit, vpi, lo=lo, hi=hi)
    print(f"[vpi] up Vpi={vpu:.4f}  down Vpi={vpd:.4f}  -> avg={vpi:.4f} V "
          f"(dir split={vpu - vpd:+.4f} V, V0 split={v0u - v0d:+.4f} V)")
    print(f"[vpi] drift-unbiased Vpi={vpi:.4f} V  V0={v0:.4f} V")
    ec.update_results(vpi_V=round(vpi, 4), v0_V=round(v0, 4),
                      v0_fit_V=round(v0_fit, 4), vpi_up_V=round(vpu, 4),
                      vpi_down_V=round(vpd, 4), vpi_dir_split_V=round(vpu - vpd, 4))
    return vpi, v0


def stage_calib(board, dmm, datadir, vpi, v0, n=181, pilot_v=PILOT_V,
                n_blocks=16, n_avg=1, cal_method="phase-ref"):
    """Stage 1: full-period sweep -> ellipse fit + gauge fixing + self-check."""
    v0 = ec.canonical_period_center(v0, vpi, lo=-BIAS_LIMIT, hi=BIAS_LIMIT)
    configure_dc_fast(dmm)
    prepare_mzm_frontend(board, pilot_v)
    bias = np.linspace(v0 - vpi, v0 + vpi, n)        # one full optical period
    I1 = []; Q1 = []; I2 = []; Q2 = []; dcd = []; dcb = []
    for i, V in enumerate(bias, 1):
        acq, dc_dmm = average_acq_point(board, dmm, V, pilot_v, n_blocks, n_avg)
        t1, t2 = acq["tones"][PILOT_HZ], acq["tones"][H2_HZ]
        I1.append(t1["I"]); Q1.append(t1["Q"])
        I2.append(t2["I"]); Q2.append(t2["Q"])
        dcd.append(dc_dmm); dcb.append(acq["dc"])
        if i == 1 or i % 10 == 0 or i == n:
            print(f"[calib] {i:3d}/{n}  bias={V:+.3f}  "
                  f"DMM={dc_dmm:.4f}  board={acq['dc']:.4f}", flush=True)
    I1, Q1, I2, Q2 = map(np.array, (I1, Q1, I2, Q2))
    dcd, dcb = np.array(dcd), np.array(dcb)
    comps = choose_comps(I1, Q1, I2, Q2)
    X = I2 if comps[0] == "I" else Q2
    Y = I1 if comps[1] == "I" else Q1
    np.savez(os.path.join(datadir, "calib.npz"), bias=bias, I1=I1, Q1=Q1,
             I2=I2, Q2=Q2, dc_dmm=dcd, dc_board=dcb, X=X, Y=Y,
             comps=np.array(comps), vpi=vpi, v0=v0, pilot_v=pilot_v,
             n_blocks=n_blocks, n_avg=n_avg)

    a_dc, b_dc, vpi_ref, v0_fit_ref = ec.fit_dc_transfer(bias, dcd)
    v0_ref = ec.canonical_period_center(v0_fit_ref, vpi_ref,
                                        lo=-BIAS_LIMIT, hi=BIAS_LIMIT)
    phase_truth = ec.bias_to_phase(bias, vpi_ref, v0_ref)
    cal_ellipse = ec.calibrate_from_data(X, Y, dcd)
    sc_ellipse = ec.self_check_mrad(X, Y, cal_ellipse, phase_truth)
    if cal_method == "phase-ref":
        cal = ec.calibrate_phase_ref(X, Y, phase_truth)
    elif cal_method == "ellipse":
        cal = cal_ellipse
    else:
        raise ValueError(f"unknown cal_method={cal_method!r}")
    sc = ec.self_check_mrad(X, Y, cal, phase_truth)
    # demod-phase slope vs bias (rad/V) for the affine PI loop
    U = cal["B"] @ np.stack([X - cal["c0"][0], Y - cal["c0"][1]])
    phi_hat = np.unwrap(np.arctan2(U[1], U[0]))
    slope = float(np.polyfit(bias, phi_hat, 1)[0])
    fit = dict(c0=cal["c0"].tolist(), B=cal["B"].tolist(),
               comps=list(comps), kappa=cal["kappa"], slope=slope,
               vpi=vpi_ref, v0=v0_ref, pilot_v=pilot_v, method=cal_method,
               a_dc=float(a_dc), b_dc=float(b_dc),
               scan_vpi=vpi, scan_v0=v0, v0_fit=v0_fit_ref,
               ellipse_diag=dict(kappa=cal_ellipse["kappa"],
                                 selfcheck_median_mrad=sc_ellipse["median"],
                                 selfcheck_p95_mrad=sc_ellipse["p95"]))
    with open(os.path.join(datadir, "calib_fit.json"), "w") as f:
        json.dump(fit, f, indent=2)
    print(f"[calib] kappa(A)={cal['kappa']:.3f}  self-check median="
          f"{sc['median']:.3f} mrad  P95={sc['p95']:.3f}  slope={slope:.4f} rad/V")
    summary = dict(selfcheck_median_mrad=round(sc["median"], 3),
                   selfcheck_p95_mrad=round(sc["p95"], 3),
                   kappa_A=round(cal["kappa"], 3),
                   pilot_v=round(pilot_v, 4), n_blocks=int(n_blocks),
                   n_avg=int(n_avg), method=cal_method,
                   vpi_V=round(vpi_ref, 4), v0_V=round(v0_ref, 4),
                   accepted=bool(sc["median"] <= 50.0 and sc["p95"] <= 200.0))
    res = ec.load_results()
    if summary["accepted"]:
        res.update({k: summary[k] for k in
                    ("selfcheck_median_mrad", "selfcheck_p95_mrad", "kappa_A")})
        res["calib_headline"] = summary
    else:
        for k in ("selfcheck_median_mrad", "selfcheck_p95_mrad", "kappa_A"):
            res.pop(k, None)
        res["calib_diagnostic"] = summary
        print("[calib] diagnostic only: quality threshold not met; "
              "tab:exp headline keys were not updated")
    ec.save_results(res)
    return fit


def _load_fit(datadir):
    with open(os.path.join(datadir, "calib_fit.json")) as f:
        d = json.load(f)
    d["c0"] = np.array(d["c0"]); d["B"] = np.array(d["B"])
    d["comps"] = tuple(d["comps"])
    return d


def lock_affine(board, dmm, fit, phi_star, G=0.35, iters=40, n_blocks=16,
                n_avg=1, v_start=None, settle_frac=0.4):
    """PC affine controller: demod via B, PI on bias. The locked operating point
    is the STEADY-STATE mean bias over the last settle_frac of iterations (so
    per-iteration demod jitter at large kappa averages out), not a single noisy
    final sample. Returns trace dict."""
    V = fit["v0"] if v_start is None else v_start
    slope = fit["slope"] if abs(fit["slope"]) > 1e-6 else np.pi / fit["vpi"]
    cal = {"c0": fit["c0"], "B": fit["B"]}
    errs = []; rhos = []; Vs = []
    for _ in range(iters):
        acq, _ = average_acq_point(board, None, V, fit["pilot_v"], n_blocks, n_avg)
        z = obs_vector(acq, fit["comps"])
        phi_hat = ec.demod_phase(z, cal)
        e = float(ec.wrap(phi_hat - phi_star))
        rho = ec.circle_residual(z, cal)
        errs.append(e); rhos.append(rho)
        V = float(np.clip(V - G * e / slope, -BIAS_LIMIT, BIAS_LIMIT))
        Vs.append(V)
    K = max(5, int(iters * settle_frac))
    V_ss = float(np.mean(Vs[-K:]))
    truth = float(ec.bias_to_phase(V_ss, fit["vpi"], fit["v0"]))
    return dict(V=V_ss, V_final=float(V), V_trace=np.array(Vs),
                err=np.array(errs), rho=np.array(rhos),
                lock_err=float(ec.wrap(truth - phi_star)))


def lock_h1match(board, dmm, fit, phi_star, G=0.35, iters=40, n_blocks=16,
                 n_avg=1, v_start=None, A1=None, Yc=None, settle_frac=0.4):
    """Classic H1 amplitude-matching baseline (PC). Drives the signed H1
    in-phase channel Y to Yc + A1*sin(phi*) with a fixed-gain integrator —
    inherits the dead-zone/branch failure of single-channel amplitude matching.
    Scored by the same steady-state-mean-bias rule as the affine controller."""
    V = fit["v0"] if v_start is None else v_start
    cal = {"c0": fit["c0"], "B": fit["B"]}
    # nominal H1 amplitude/center from calibration if not supplied
    if A1 is None or Yc is None:
        A1 = float(np.hypot(*fit["B"][1])) ** -1  # rough scale from B row
        Yc = float(fit["c0"][1])
    y_set = Yc + A1 * np.sin(phi_star)
    slope = fit["slope"] if abs(fit["slope"]) > 1e-6 else np.pi / fit["vpi"]
    errs = []; Vs = []
    for _ in range(iters):
        acq, _ = average_acq_point(board, None, V, fit["pilot_v"], n_blocks, n_avg)
        z = obs_vector(acq, fit["comps"])
        y = z[1]                                   # H1 in-phase channel
        # match amplitude; the |sin| ambiguity & nominal gain cause the error
        dy = y_set - y
        V = float(np.clip(V + G * dy / (A1 * abs(slope) + 1e-9),
                          -BIAS_LIMIT, BIAS_LIMIT))
        Vs.append(V)
        phi_hat = ec.demod_phase(z, cal)
        errs.append(float(ec.wrap(phi_hat - phi_star)))
    K = max(5, int(iters * settle_frac))
    V_ss = float(np.mean(Vs[-K:]))
    truth = float(ec.bias_to_phase(V_ss, fit["vpi"], fit["v0"]))
    return dict(V=V_ss, V_final=float(V), V_trace=np.array(Vs),
                err=np.array(errs), lock_err=float(ec.wrap(truth - phi_star)))


def eval_lock_err_dmm(board, dmm, fit, v_lock, phi_star):
    """Drift-immune per-point lock error by LOCAL LINEARIZATION of the DC
    transfer at the KNOWN target phi*.

    Read the live DC at the locked bias, P_lock; the target DC is
    P* = a + b cos(phi*) and the local slope is dP/dphi = -b sin(phi*), both from
    the freshly-fit calibration.  Then  delta_phi = (P_lock - P*)/(dP/dphi).  The
    sign comes from the KNOWN phi* (no phase-sign reconstruction -> no branch/sign
    flips), it uses only the drift-stable DC amplitudes (a,b), and it is exact to
    first order for the small errors of a working loop.  Near the DC extrema
    (|sin phi*|<0.15) the slope vanishes, so it falls back to the bias->phase map.
    Returns (lock_err, used_dmm, p_lock)."""
    a_dc, b_dc = fit.get("a_dc"), fit.get("b_dc")
    if dmm is None or a_dc is None or b_dc is None or abs(b_dc) < 1e-9:
        truth = float(ec.bias_to_phase(v_lock, fit["vpi"], fit["v0"]))
        return float(ec.wrap(truth - phi_star)), False, float("nan")
    s = float(np.sin(phi_star))
    p_lock = float(read_dc_at_bias(board, dmm, v_lock))
    if abs(s) < 0.15:                               # extremum: slope ~0, ill-cond
        truth = float(ec.bias_to_phase(v_lock, fit["vpi"], fit["v0"]))
        return float(ec.wrap(truth - phi_star)), False, p_lock
    p_star = a_dc + b_dc * float(np.cos(phi_star))
    dphi = (p_lock - p_star) / (-b_dc * s)
    return float(ec.wrap(dphi)), True, p_lock


def stage_lock(board, dmm, datadir, n_grid=16, iters=40, n_blocks=16, n_avg=1,
               gain=0.6):
    """Stage 2: lock both controllers across a phi* grid; record rms/static.

    Each locked point is scored by the drift-robust DMM truth (independent of
    the controller) AND, as a cross-check, the calibration bias->phase map."""
    fit = _load_fit(datadir)
    configure_dc_fast(dmm)             # speed up the per-point DMM truth reads
    prepare_mzm_frontend(board, fit["pilot_v"])
    grid = np.linspace(0, 2 * np.pi, n_grid, endpoint=False)
    aff = []; base = []; aff_map = []; base_map = []; tr_a = []; tr_b = []
    va = []; vb = []; pa = []; pb = []
    for ps in grid:
        ra = lock_affine(board, dmm, fit, ps, G=gain, iters=iters,
                         n_blocks=n_blocks, n_avg=n_avg)
        ea, _, p_a = eval_lock_err_dmm(board, dmm, fit, ra["V"], ps)
        rb = lock_h1match(board, dmm, fit, ps, G=gain, iters=iters,
                          n_blocks=n_blocks, n_avg=n_avg)
        eb, _, p_b = eval_lock_err_dmm(board, dmm, fit, rb["V"], ps)
        aff.append(ea); base.append(eb)
        aff_map.append(ra["lock_err"]); base_map.append(rb["lock_err"])
        tr_a.append(ra["err"]); tr_b.append(rb["err"])
        va.append(ra["V"]); vb.append(rb["V"]); pa.append(p_a); pb.append(p_b)
        print(f"[lock] phi*={ps:5.2f}  affine={ea*1e3:7.1f} mrad  "
              f"H1={eb*1e3:8.1f} mrad  (map: {ra['lock_err']*1e3:.1f}/"
              f"{rb['lock_err']*1e3:.1f})")
    aff = np.array(aff); base = np.array(base)             # live-DMM (drift-immune) truth
    aff_map = np.array(aff_map); base_map = np.array(base_map)  # bias->phase map (V0-ref'd)
    out_name = "lock_sweep.npz" if n_grid >= 16 else "lock_sweep_smoke.npz"
    # Headline error = the drift-IMMUNE live-DMM truth (map fallback only at the
    # DC extrema); the V0-referenced map truth is kept as a cross-check.
    np.savez(os.path.join(datadir, out_name),
             phi_star=grid, affine_err=aff, baseline_err=base,
             affine_err_map=aff_map, baseline_err_map=base_map,
             affine_trace=np.array(tr_a), baseline_trace=np.array(tr_b),
             v_affine=np.array(va), v_baseline=np.array(vb),
             p_affine=np.array(pa), p_baseline=np.array(pb),
             pilot_v=fit["pilot_v"], kappa=fit["kappa"], iters=iters)
    rms_a = float(np.sqrt(np.mean((aff * 1e3) ** 2)))
    rms_b = float(np.sqrt(np.mean((base * 1e3) ** 2)))
    rms_a_map = float(np.sqrt(np.mean((aff_map * 1e3) ** 2)))
    # auto-promote to the tab:exp headline ONLY when the measurement is
    # trustworthy: full grid, affine clearly beats the baseline, and the two
    # independent truths (linearization headline vs bias->phase map) concur.
    beats = rms_a < 0.5 * rms_b
    concur = max(rms_a, rms_a_map) <= 2.5 * max(min(rms_a, rms_a_map), 1e-9)
    accepted = bool(n_grid >= 16 and beats and concur)
    print(f"[lock] affine RMS={rms_a:.1f} mrad   H1-match RMS={rms_b:.1f} mrad"
          f"   (map x-check affine={rms_a_map:.1f} mrad)  "
          f"beats={beats} concur={concur} accepted={accepted}")
    summary = dict(lock_affine_rms_mrad=round(rms_a, 1),
                   lock_h1match_rms_mrad=round(rms_b, 1),
                   lock_affine_rms_map_xcheck_mrad=round(rms_a_map, 1),
                   n_grid=int(n_grid), iters=int(iters),
                   n_blocks=int(n_blocks), n_avg=int(n_avg),
                   gain=float(gain), accepted=accepted)
    res = ec.load_results()
    if accepted:
        res.update({k: summary[k] for k in
                    ("lock_affine_rms_mrad", "lock_h1match_rms_mrad")})
        res["lock_headline"] = summary
    else:
        for k in ("lock_affine_rms_mrad", "lock_h1match_rms_mrad"):
            res.pop(k, None)
        res["lock_diagnostic"] = summary
        print("[lock] diagnostic only (not trustworthy enough to auto-promote); "
              "tab:exp lock row stays 待测")
    ec.save_results(res)


def stage_pilot(board, dmm, datadir, amps=(0.05, 0.10, 0.20, 0.40),
                vpi=None, v0=None, n=121, n_blocks=16, n_avg=1):
    """Stage 3: sweep pilot amplitude Ap -> kappa(A) trend, residual vs phi."""
    fit = _load_fit(datadir)
    vpi = vpi or fit["vpi"]; v0 = v0 or fit["v0"]
    v0 = ec.canonical_period_center(v0, vpi, lo=-BIAS_LIMIT, hi=BIAS_LIMIT)
    rows = []
    for Ap in amps:
        configure_dc_fast(dmm)
        prepare_mzm_frontend(board, Ap)
        bias = np.linspace(v0 - vpi, v0 + vpi, n)
        I1 = []; Q1 = []; I2 = []; Q2 = []; dcd = []
        for i, V in enumerate(bias, 1):
            acq, dc = average_acq_point(board, dmm, V, Ap, n_blocks, n_avg)
            t1, t2 = acq["tones"][PILOT_HZ], acq["tones"][H2_HZ]
            I1.append(t1["I"]); Q1.append(t1["Q"])
            I2.append(t2["I"]); Q2.append(t2["Q"]); dcd.append(dc)
            if i == 1 or i % 20 == 0 or i == n:
                print(f"[pilot] Ap={Ap:.3f}  {i:3d}/{n}  bias={V:+.3f}",
                      flush=True)
        I1, Q1, I2, Q2, dcd = map(np.array, (I1, Q1, I2, Q2, dcd))
        comps = choose_comps(I1, Q1, I2, Q2)
        X = I2 if comps[0] == "I" else Q2
        Y = I1 if comps[1] == "I" else Q1
        cal = ec.calibrate_from_data(X, Y, dcd)
        sc = ec.self_check_mrad(X, Y, cal, ec.bias_to_phase(bias, vpi, v0))
        m = np.pi * Ap / vpi
        rows.append((float(Ap), float(m), float(cal["kappa"]),
                     float(sc["median"])))
        print(f"[pilot] Ap={Ap:.3f} V  m={m:.3f}  kappa={cal['kappa']:.3f}  "
              f"resid={sc['median']:.2f} mrad")
    _write_csv(os.path.join(datadir, "pilot_depth.csv"),
               ["Ap", "m", "kappa", "resid_mrad"], rows)


def _recalibrate(board, dmm, pilot_v, vpi, v0, n=121, n_blocks=16, n_avg=2,
                 label=None):
    """Quick re-calibration sweep (no file output) -> fresh demod dict; used by
    the drift-recovery to re-identify the ellipse at the CURRENT pilot depth.
    Pass `label` to print sweep progress (long silent sweeps look hung)."""
    configure_dc_fast(dmm)
    prepare_mzm_frontend(board, pilot_v)
    bias = np.linspace(v0 - vpi, v0 + vpi, n)
    I1 = []; Q1 = []; I2 = []; Q2 = []; dcd = []
    for i, V in enumerate(bias, 1):
        acq, dc = average_acq_point(board, dmm, float(V), pilot_v, n_blocks, n_avg)
        t1, t2 = acq["tones"][PILOT_HZ], acq["tones"][H2_HZ]
        I1.append(t1["I"]); Q1.append(t1["Q"])
        I2.append(t2["I"]); Q2.append(t2["Q"]); dcd.append(dc)
        if label and (i == 1 or i % 30 == 0 or i == n):
            print(f"[rf]   {label}: recal {i:3d}/{n}  bias={V:+.3f}  dc={dc:.3f}",
                  flush=True)
    I1, Q1, I2, Q2, dcd = map(np.array, (I1, Q1, I2, Q2, dcd))
    comps = choose_comps(I1, Q1, I2, Q2)
    X = I2 if comps[0] == "I" else Q2
    Y = I1 if comps[1] == "I" else Q1
    a_dc, b_dc, vpi_r, v0f = ec.fit_dc_transfer(bias, dcd)
    v0_r = ec.canonical_period_center(v0f, vpi_r, lo=-BIAS_LIMIT, hi=BIAS_LIMIT)
    cal = ec.calibrate_phase_ref(X, Y, ec.bias_to_phase(bias, vpi_r, v0_r))
    U = cal["B"] @ np.stack([X - cal["c0"][0], Y - cal["c0"][1]])
    slope = float(np.polyfit(bias, np.unwrap(np.arctan2(U[1], U[0])), 1)[0])
    return dict(c0=cal["c0"], B=cal["B"], comps=tuple(comps), slope=slope,
                a_dc=float(a_dc), b_dc=float(b_dc), vpi=vpi_r, v0=v0_r,
                kappa=float(cal["kappa"]))


def stage_drift(board, dmm, datadir, iters=120, step_at=None, n_blocks=12,
                n_avg=1, phi_star=1.9, lam=0.05, k_sigma=5.0, upset=0.6,
                recal_consec=4, recover=True):
    """Stage 4: lock at phi*, inject a gain upset, let the residual monitor
    TRIGGER a recalibration that re-identifies the ellipse and RESTORES the lock.
    Records detection latency and the recovered (post-recal) rms.

    The upset is a real AC-gain change: on hardware the pilot amplitude is
    stepped to `upset`x (changing the J1/J2 ratio -> ellipse shape -> demod
    bias + residual rise); in --sim a child-arm gain is dropped."""
    fit = _load_fit(datadir)
    prepare_mzm_frontend(board, fit["pilot_v"])
    comps = fit["comps"]; cal = {"c0": fit["c0"], "B": fit["B"]}
    slope = fit["slope"] if abs(fit["slope"]) > 1e-6 else np.pi / fit["vpi"]
    vpi, v0c = fit["vpi"], fit["v0"]
    step_at = iters // 2 if step_at is None else step_at
    step_at = int(max(2, min(step_at, iters - 2)))
    win = max(4, iters // 8)
    V = fit["v0"]; rho_bar = None; rho_hist = []; err_hist = []
    cur_pilot = fit["pilot_v"]; baseline = []; thr = None
    consec = 0; recal_at = -1
    for k in range(iters):
        if k == step_at:
            if isinstance(board, SimBoard):
                board.set_drift(gx=0.82)
            else:
                board.gen_pilot(CH, PILOT_HZ, fit["pilot_v"] * upset)
                time.sleep(0.2)
            cur_pilot = fit["pilot_v"] * upset
        acq, _ = average_acq_point(board, None, V, cur_pilot, n_blocks, n_avg)
        z = obs_vector(acq, comps)
        e = float(ec.wrap(ec.demod_phase(z, cal) - phi_star))
        rho = ec.circle_residual(z, cal)
        rho_bar = rho if rho_bar is None else (1 - lam) * rho_bar + lam * rho
        rho_hist.append(rho_bar); err_hist.append(e * 1e3)
        if k < step_at:
            baseline.append(rho_bar)
        elif thr is None:
            thr = float(np.mean(baseline) + k_sigma * (np.std(baseline) + 1e-9))
        if recover and recal_at < 0 and thr is not None and rho_bar > thr:
            consec += 1
            if consec >= recal_consec:                # residual-triggered recal
                recal_at = k
                print(f"[drift] residual tripped at k={k} (latency {k-step_at}); "
                      f"recalibrating at pilot={cur_pilot:.3f} V ...", flush=True)
                nf = _recalibrate(board, dmm, cur_pilot, vpi, v0c)
                comps = nf["comps"]; cal = {"c0": nf["c0"], "B": nf["B"]}
                slope = nf["slope"] if abs(nf["slope"]) > 1e-6 else slope
                rho_bar = None                         # re-baseline after recal
                prepare_mzm_frontend(board, cur_pilot)
        elif recal_at < 0:
            consec = 0
        V = float(np.clip(V - 0.3 * e / slope, -BIAS_LIMIT, BIAS_LIMIT))
    rho_hist = np.array(rho_hist); err_hist = np.array(err_hist)
    latency = (recal_at - step_at) if recal_at >= 0 else -1
    pre_rms = float(np.sqrt(np.mean(err_hist[max(0, step_at - win):step_at] ** 2)))
    post_rms = float(np.sqrt(np.mean(err_hist[-win:] ** 2)))
    if thr is None:
        thr = float("nan")
    np.savez(os.path.join(datadir, "drift.npz"), err_mrad=err_hist,
             rho_bar=rho_hist, step_at=step_at, thr=thr, latency=latency,
             recal_at=recal_at)
    print(f"[drift] latency={latency} cyc  pre-rms={pre_rms:.1f}  "
          f"recovered(post-recal)-rms={post_rms:.1f} mrad")
    res = ec.load_results()
    res["drift_diagnostic"] = dict(
        latency_cyc=latency, pre_rms_mrad=round(pre_rms, 1),
        post_rms_mrad=round(post_rms, 1), recal_at=int(recal_at), thr=thr,
        iters=int(iters), step_at=step_at, n_blocks=int(n_blocks),
        n_avg=int(n_avg), recovered=bool(recal_at >= 0))
    ec.save_results(res)


def stage_stability(board, dmm, datadir, duration_s=10800.0, phi_star=1.9,
                    n_blocks=16, n_avg=1, dmm_every_s=180.0, lam=0.05,
                    k_sigma=6.0, recal_consec=5, warmup=40, gain=0.3):
    """Long-term stability: hold the arbitrary-point lock for duration_s while
    logging lock error, the residual monitor rho_bar (counting recal-TRIGGER
    events), bias drift V(t), and periodic drift-immune DMM-truth error samples.

    The closed loop tracks the slow thermal/charge bias-point drift on its own
    (that is the bias controller's job); the residual monitor only trips on a
    *gain*-type change that would invalidate the demod calibration.  Recal-
    RECOVERY is future work, so triggers are counted, not acted on.  Robust to
    occasional bad acquisitions over the long run (skip + continue)."""
    fit = _load_fit(datadir)
    configure_dc_fast(dmm)
    prepare_mzm_frontend(board, fit["pilot_v"])
    cal = {"c0": fit["c0"], "B": fit["B"]}
    slope = fit["slope"] if abs(fit["slope"]) > 1e-6 else np.pi / fit["vpi"]
    V = fit["v0"]

    def step():
        nonlocal V
        acq, _ = average_acq_point(board, None, V, fit["pilot_v"], n_blocks, n_avg)
        z = obs_vector(acq, fit["comps"])
        e = float(ec.wrap(ec.demod_phase(z, cal) - phi_star))
        rho = ec.circle_residual(z, cal)
        V = float(np.clip(V - gain * e / slope, -BIAS_LIMIT, BIAS_LIMIT))
        return e, rho

    for _ in range(warmup):                          # acquire lock
        try:
            step()
        except Exception:
            pass
    t0 = time.time()
    ts = []; errs = []; rhos = []; Vs = []; dmm_ts = []; dmm_errs = []
    rho_bar = None; base = []; thr = None; recal = 0; consec = 0
    next_dmm = 0.0; nbad = 0; last_print = -1e9
    while True:
        t = time.time() - t0
        if t >= duration_s:
            break
        try:
            e, rho = step()
        except Exception:
            nbad += 1; time.sleep(0.2); continue
        rho_bar = rho if rho_bar is None else (1 - lam) * rho_bar + lam * rho
        ts.append(t); errs.append(e * 1e3); rhos.append(rho_bar); Vs.append(V)
        if thr is None:
            base.append(rho_bar)
            if t > 60:
                thr = float(np.mean(base) + k_sigma * (np.std(base) + 1e-9))
        elif rho_bar > thr:
            consec += 1
            if consec == recal_consec:
                recal += 1
        else:
            consec = 0
        if t >= next_dmm:
            try:
                de, _, _ = eval_lock_err_dmm(board, dmm, fit, V, phi_star)
                dmm_ts.append(t); dmm_errs.append(de * 1e3)
            except Exception:
                pass
            next_dmm += dmm_every_s
        if t - last_print > 300:
            last_print = t
            print(f"[stab] t={t/60:5.1f} min  err={e*1e3:6.0f} mrad  "
                  f"rho_bar={rho_bar:.3f}  recal={recal}  V={V:+.3f}", flush=True)
    ts = np.array(ts); errs = np.array(errs); rhos = np.array(rhos); Vs = np.array(Vs)
    dmm_ts = np.array(dmm_ts); dmm_errs = np.array(dmm_errs)
    np.savez(os.path.join(datadir, "stability.npz"), t=ts, err_mrad=errs,
             rho_bar=rhos, V=Vs, dmm_t=dmm_ts, dmm_err_mrad=dmm_errs,
             thr=(thr if thr is not None else float("nan")),
             recal_events=recal, phi_star=phi_star, duration_s=duration_s)
    dmm_rms = float(np.sqrt(np.mean(dmm_errs ** 2))) if len(dmm_errs) else float("nan")
    dmm_max = float(np.max(np.abs(dmm_errs))) if len(dmm_errs) else float("nan")
    vdrift = float(Vs.max() - Vs.min()) if len(Vs) else float("nan")
    hrs = ts[-1] / 3600 if len(ts) else 0.0
    print(f"[stab] done: {hrs:.2f} h  DMM-truth rms={dmm_rms:.0f} mrad "
          f"max={dmm_max:.0f}  recal triggers={recal}  Vdrift={vdrift:.3f} V "
          f"(bad acq={nbad})")
    res = ec.load_results()
    res["stability_diagnostic"] = dict(
        duration_h=round(hrs, 2), dmm_rms_mrad=round(dmm_rms, 1),
        dmm_max_mrad=round(dmm_max, 1), recal_events=int(recal),
        vdrift_V=round(vdrift, 3), n_samples=int(len(ts)), bad_acq=int(nbad))
    res["stability_recal_events_3h"] = int(recal)
    res["stability_dmm_rms_mrad"] = round(dmm_rms, 1)
    ec.save_results(res)


# --------------------------------------------------------------------------- #
#  stage 5: arbitrary-point lock robustness under an applied out-of-band RF    #
# --------------------------------------------------------------------------- #
def _specan_tone(specan, rf_hz, span=2e6, settle_s=0.6):
    """Read the applied-tone level (dBm) at DE2 via the spectrum analyzer."""
    if specan is None:
        return float("nan")
    specan.setup_frequency(center=rf_hz, span=span)
    specan.single_sweep()
    specan.wait_for_sweep()
    specan.marker_on(1)
    specan.marker_set_freq(rf_hz, 1)
    time.sleep(settle_s)
    _, lvl = specan.marker_read(1)
    return float(lvl)


def _rf_apply(siggen, specan, vpp, rf_hz, rf_ch):
    """Drive (vpp>0) or disable (vpp<=0) the MZM RF port; return the verified
    tone level at DE2 (NaN if no spectrum analyzer)."""
    if siggen is None:
        return float("nan")
    if vpp <= 0:
        siggen.output_off(rf_ch)
        time.sleep(0.3)
        return _specan_tone(specan, rf_hz)
    siggen.set_load(rf_ch, 50)
    siggen.setup_waveform(rf_ch, "SINusoid", freq=rf_hz, amp=vpp, offset=0.0)
    siggen.output_on(rf_ch)
    time.sleep(0.5)
    return _specan_tone(specan, rf_hz)


def _rf_load(datadir):
    """Load any previously measured RF rows (resume across interrupted runs)."""
    p = os.path.join(datadir, "rf_lock.npz")
    rows = []; saved = {}
    if not os.path.exists(p):
        return rows, saved
    try:
        d = np.load(p)
        for i, pw in enumerate(d["powers_dbm"]):
            pdv = None if not np.isfinite(pw) else float(pw)
            tag = "off" if pdv is None else f"{pdv:+.0f}dBm"
            rows.append(dict(tag=tag, power_dbm=pdv, m_rf=float(d["m_rf"][i]),
                             tone_dbm=float(d["tone_dbm"][i]),
                             kappa=float(d["kappa"][i]), h1=float(d["h1"][i]),
                             h2=float(d["h2"][i]), h1_fade=float(d["h1_fade"][i]),
                             rms_mrad=float(d["rms_mrad"][i])))
            if f"err_{tag}" in d.files:
                saved[f"err_{tag}"] = d[f"err_{tag}"]
    except Exception:
        return [], {}
    return rows, saved


def _rf_save(datadir, rows, saved, grid, rf_hz, n_grid, meta):
    """Write rf_lock.npz + reconcile results.json from the merged rows.  Called
    after EVERY power state so an interrupted run keeps its completed states."""
    rows = sorted(rows, key=lambda r: (-1e9 if r["power_dbm"] is None
                                        else r["power_dbm"]))
    off = [r for r in rows if r["power_dbm"] is None]
    h1_off = off[0]["h1"] if off else None
    for r in rows:                       # fade is relative to the RF-off row
        r["h1_fade"] = (r["h1"] / h1_off) if h1_off else float("nan")
    arr = lambda k: np.array([r[k] for r in rows], float)
    powers = np.array([np.nan if r["power_dbm"] is None else r["power_dbm"]
                       for r in rows], float)
    np.savez(os.path.join(datadir, "rf_lock.npz"), powers_dbm=powers,
             m_rf=arr("m_rf"), tone_dbm=arr("tone_dbm"), kappa=arr("kappa"),
             h1=arr("h1"), h2=arr("h2"), h1_fade=arr("h1_fade"),
             rms_mrad=arr("rms_mrad"), phi_grid=grid, rf_hz=float(rf_hz),
             n_grid=int(n_grid),
             **{f"err_{r['tag']}": saved[f"err_{r['tag']}"]
                for r in rows if f"err_{r['tag']}" in saved})
    rms_off = next((r["rms_mrad"] for r in off), float("nan"))
    on0 = [r for r in rows if r["power_dbm"] is not None
           and abs(r["power_dbm"]) < 1e-6]
    rms_on = on0[0]["rms_mrad"] if on0 else float("nan")
    accepted = bool(n_grid >= 8 and np.isfinite(rms_on) and np.isfinite(rms_off)
                    and rms_on < 700.0 and rms_on < 3.0 * rms_off + 50.0)
    summary = dict(rf_hz=float(rf_hz), n_grid=int(n_grid),
                   rms_off_mrad=rms_off, rms_on_mrad=rms_on, rows=rows,
                   accepted=accepted, **meta)
    res = ec.load_results()
    if accepted:
        res["rf_lock_rms_on_mrad"] = round(rms_on, 1)
        res["rf_lock_rms_off_mrad"] = round(rms_off, 1)
        res["rf_headline"] = summary
        res.pop("rf_diagnostic", None)
    else:
        for k in ("rf_lock_rms_on_mrad", "rf_lock_rms_off_mrad"):
            res.pop(k, None)
        res["rf_diagnostic"] = summary
    ec.save_results(res)
    return rms_off, rms_on, accepted


def stage_rf(board, dmm, siggen, specan, datadir, rf_hz=RF_HZ, rf_ch=RF_CH,
             powers_dbm=(None, 0.0), n_grid=8, iters=40, n_blocks=16, n_avg=1,
             gain=0.3):
    """Stage 5: hold the affine arbitrary-point lock while an out-of-band RF tone
    is applied to the MZM RF port, and compare to the RF-off reference.

    Theory (Sec. affine): a 50 MHz drive sits far above the PD/ADC band, so the
    detector averages it to a J0(m_RF) factor multiplying the WHOLE harmonic
    observation,  z = A u(phi)+b  ->  (J0 A) u(phi)+b.  The affine structure and
    the phase u(phi) are untouched (J0 is reabsorbed by calibration); only the
    SNR drops, so kappa(A) rises ~1/J0(m_RF).  Expectation: the lock holds with an
    RF-on rms close to RF-off, and H1/H2 fade together by J0(m_RF).

    For each RF power (None = RF off): set + verify the tone, RE-IDENTIFY the
    ellipse under that RF state (so calibration and DC-truth share the same J0
    fade), affine-lock across a phi* grid, and score each point by the drift-
    immune DMM truth.  Records lock rms, the verified tone, kappa and the H1/H2
    fade per power."""
    from scipy.special import j0 as bessel_j0
    fit = _load_fit(datadir)
    configure_dc_fast(dmm)
    vpi = fit["vpi"]
    grid = np.linspace(0, 2 * np.pi, n_grid, endpoint=False)
    meta = dict(iters=int(iters), n_blocks=int(n_blocks), n_avg=int(n_avg),
                gain=float(gain))
    rows, saved = _rf_load(datadir)      # resume across interrupted runs
    if rows:
        print(f"[rf] resuming: {len(rows)} power state(s) already on file "
              f"({', '.join(r['tag'] for r in rows)})", flush=True)
    for p in powers_dbm:
        vpp = 0.0 if p is None else dbm_to_vpp(float(p))
        m_rf = 0.0 if p is None else rf_depth(vpp, vpi)
        tag = "off" if p is None else f"{p:+.0f}dBm"
        print(f"[rf] === power {tag} (Vpp={vpp:.3f}, m_RF~{m_rf:.3f}): "
              f"setting RF + re-identifying ellipse ...", flush=True)
        tone = _rf_apply(siggen, specan, vpp, rf_hz, rf_ch)
        prepare_mzm_frontend(board, fit["pilot_v"])
        nf = _recalibrate(board, dmm, fit["pilot_v"], vpi, fit["v0"],
                          n_blocks=n_blocks, n_avg=max(2, n_avg), label=tag)
        rf_fit = dict(fit); rf_fit.update(
            c0=nf["c0"], B=nf["B"], comps=nf["comps"], slope=nf["slope"],
            a_dc=nf["a_dc"], b_dc=nf["b_dc"], vpi=nf["vpi"], v0=nf["v0"])
        print(f"[rf]   {tag}: recal done (kappa={nf['kappa']:.1f}, tone={tone:.1f} "
              f"dBm); locking {n_grid} phi* points ...", flush=True)
        errs = []
        for j, ps in enumerate(grid, 1):
            ra = lock_affine(board, dmm, rf_fit, ps, G=gain, iters=iters,
                             n_blocks=n_blocks, n_avg=n_avg)
            ea, _, _ = eval_lock_err_dmm(board, dmm, rf_fit, ra["V"], ps)
            errs.append(ea)
            print(f"[rf]   {tag}: lock {j}/{n_grid}  phi*={ps:4.2f}  "
                  f"err={ea*1e3:6.1f} mrad", flush=True)
        errs = np.array(errs)
        rms = float(np.sqrt(np.mean((errs * 1e3) ** 2)))
        # H1/H2 fade probe at quadrature (both harmonics well above noise there)
        vq = ec.canonical_period_center(nf["v0"], nf["vpi"], lo=-BIAS_LIMIT,
                                        hi=BIAS_LIMIT) + 0.5 * nf["vpi"]
        acq, _ = average_acq_point(board, None, float(vq), fit["pilot_v"],
                                   n_blocks, max(2, n_avg))
        h1 = acq["tones"][PILOT_HZ]["mag"]; h2 = acq["tones"][H2_HZ]["mag"]
        rows = [r for r in rows if r["tag"] != tag]      # replace same-tag
        rows.append(dict(tag=tag, power_dbm=(None if p is None else float(p)),
                         m_rf=float(m_rf), tone_dbm=float(tone),
                         kappa=float(nf["kappa"]), h1=float(h1), h2=float(h2),
                         h1_fade=float("nan"), rms_mrad=round(rms, 1)))
        saved[f"err_{tag}"] = errs
        rms_off, rms_on, accepted = _rf_save(datadir, rows, saved, grid, rf_hz,
                                             n_grid, meta)   # checkpoint NOW
        print(f"[rf] {tag:>8}  m_RF={m_rf:.3f}  J0={bessel_j0(m_rf):.4f}  "
              f"tone={tone:6.1f} dBm  kappa={nf['kappa']:.2f}  H1={h1:.4g} "
              f"H2={h2:.4g}  lock rms={rms:.1f} mrad  [saved {len(rows)} states]",
              flush=True)
    if siggen is not None:
        siggen.output_off(rf_ch)
    rms_off, rms_on, accepted = _rf_save(datadir, rows, saved, grid, rf_hz,
                                         n_grid, meta)
    print(f"[rf] RF-off rms={rms_off:.1f}  RF-on(0 dBm) rms={rms_on:.1f} mrad  "
          f"accepted={accepted}"
          + ("" if accepted else "  (diagnostic only; tab:exp RF row stays 待测)"))


def _scope_fft(scope, settle_s=3.0):
    if scope is None:
        return {PILOT_HZ: float("nan"), H2_HZ: float("nan")}
    scope.setup_channel(1, coupling="AC", scale=0.5, offset=0.0)
    scope.setup_timebase(5e-2)
    scope.set_mdepth("1M")
    scope.setup_fft(source_channel=1, unit="DBVrms", window="HANNing",
                    center=1.5e3, span=3.0e3, points="1M", average=4)
    vals = scope.fft_marker_dbm([PILOT_HZ, H2_HZ], settle_s=settle_s)
    scope.fft_off()
    return vals


def stage_pilotdiag(board, dmm, scope, datadir, vpi, v0,
                    amps=(0.05, 0.10, 0.15, 0.20, 0.30, 0.40),
                    n_blocks=16, n_avg=4, scope_every=False):
    """Quick AC-chain diagnostic across pilot depths and three phase points."""
    v0 = ec.canonical_period_center(v0, vpi, lo=-BIAS_LIMIT, hi=BIAS_LIMIT)
    pts = [
        ("peak", v0),
        ("quad", v0 + 0.5 * vpi),
        ("null", v0 + vpi),
    ]
    configure_dc_fast(dmm)
    p = os.path.join(datadir, "pilot_diag.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    header = ["Ap", "m", "point", "bias", "dc_dmm", "dc_board",
              "board_H1_mag", "board_H2_mag", "board_H2_over_H1",
              "board_H1_I", "board_H1_Q", "board_H2_I", "board_H2_Q",
              "scope_H1_dBVrms", "scope_H2_dBVrms", "scope_H2_minus_H1_dB"]
    rows = []
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header)
        for Ap in amps:
            prepare_mzm_frontend(board, Ap)
            m = np.pi * Ap / vpi
            for point, bias in pts:
                acq, dc = average_acq_point(board, dmm, bias, Ap, n_blocks, n_avg)
                h1 = acq["tones"][PILOT_HZ]; h2 = acq["tones"][H2_HZ]
                use_scope = scope is not None and (scope_every or point == "quad")
                sv = _scope_fft(scope, settle_s=3.0) if use_scope else {
                    PILOT_HZ: float("nan"), H2_HZ: float("nan")}
                ratio = h2["mag"] / h1["mag"] if h1["mag"] else float("nan")
                sdiff = sv[H2_HZ] - sv[PILOT_HZ] if np.isfinite(
                    sv[H2_HZ]) and np.isfinite(sv[PILOT_HZ]) else float("nan")
                row = [Ap, m, point, bias, dc, acq["dc"],
                       h1["mag"], h2["mag"], ratio,
                       h1["I"], h1["Q"], h2["I"], h2["Q"],
                       sv[PILOT_HZ], sv[H2_HZ], sdiff]
                rows.append(row); w.writerow(row); f.flush()
                print(f"[pilotdiag] Ap={Ap:.3f} m={m:.3f} {point:>4} "
                      f"bias={bias:+.3f} H1={h1['mag']:.4g} H2={h2['mag']:.4g} "
                      f"H2/H1={ratio:.4g} scopeΔ={sdiff:.1f}dB", flush=True)
    print(f"[io] wrote {os.path.relpath(p, ec.REPO)} ({len(rows)} rows)")


def stage_bringup(board, dmm, scope):
    """Sanity: board state; compare board CH1 vs DMM to find the clip region."""
    if isinstance(board, SimBoard):
        print("[bringup] SIM board — no real hardware.")
    else:
        st = board.status()
        print(f"[bringup] state={st.get('State')} bias={st.get('Bias')} "
              f"lock={st.get('Lock')} cal={st.get('Cal')}")
    if dmm and hasattr(dmm, "identify"):
        print(f"[bringup] DMM: {dmm.identify()}")
    if scope and hasattr(scope, "identify"):
        print(f"[bringup] scope: {scope.identify()}")
    for V in (-6.0, -3.0, 0.0, 3.0):
        acq, dc_dmm = acq_point(board, dmm, V, PILOT_V, n_blocks=8)
        print(f"  bias={V:+.1f}  board_DC={acq['dc']:.4f} V  DMM_DC={dc_dmm:.4f} V"
              f"  {'(CH1 CLIP)' if acq['dc'] >= SimBoard.CH1_FS - 1e-3 else ''}")


# --------------------------------------------------------------------------- #
def _write_csv(p, header, rows):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"[io] wrote {os.path.relpath(p, ec.REPO)} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["bringup", "vpi", "calib", "pilotdiag",
                                       "lock", "pilot", "drift", "stability",
                                       "rf", "all"])
    ap.add_argument("--sim", action="store_true",
                    help="analytic model instead of hardware; writes build/exp_sim/")
    ap.add_argument("--no-dmm", action="store_true", help="skip DM858E")
    ap.add_argument("--no-scope", action="store_true", help="skip SDS824X HD")
    ap.add_argument("--no-specan", action="store_true",
                    help="skip FSV30 tone verification in the rf stage")
    ap.add_argument("--vpi", type=float, help="override Vpi (skip stage 0 fit)")
    ap.add_argument("--v0", type=float, help="override V0")
    ap.add_argument("--pilot-v", type=float, default=PILOT_V,
                    help=f"pilot amplitude on the bias line (default {PILOT_V} V)")
    ap.add_argument("--n-blocks", type=int,
                    help="Goertzel blocks per point for calib/lock/drift")
    ap.add_argument("--n-points", type=int,
                    help="number of bias points for calib/pilot sweeps")
    ap.add_argument("--n-avg", type=int, default=1,
                    help="repeat stable short acq windows and average them")
    ap.add_argument("--n-grid", type=int, default=16,
                    help="target phase grid size for lock stage")
    ap.add_argument("--iters", type=int, default=40,
                    help="control iterations per target for the lock stage")
    ap.add_argument("--drift-iters", type=int, default=400,
                    help="control iterations for the drift stage (>= ~40)")
    ap.add_argument("--drift-upset", type=float, default=0.5,
                    help="pilot-amplitude factor of the injected gain upset")
    ap.add_argument("--duration-h", type=float, default=3.0,
                    help="stability stage duration in hours (default 3)")
    ap.add_argument("--gain", type=float, default=0.6,
                    help="PC controller proportional gain for lock stage")
    ap.add_argument("--pilot-list", default="0.05,0.10,0.15,0.20,0.30,0.40",
                    help="comma-separated pilot amplitudes for pilotdiag")
    ap.add_argument("--cal-method", choices=["phase-ref", "ellipse"],
                    default="phase-ref",
                    help="calibration gauge method for stage calib")
    ap.add_argument("--scope-every", action="store_true",
                    help="in pilotdiag, take scope FFT at every point, not just quad")
    ap.add_argument("--rf-hz", type=float, default=RF_HZ,
                    help=f"applied RF tone frequency for the rf stage (default {RF_HZ:g} Hz)")
    ap.add_argument("--rf-ch", type=int, default=RF_CH,
                    help=f"DG922pro channel feeding the MZM RF port (default {RF_CH})")
    ap.add_argument("--rf-powers", default="off,0",
                    help="comma-separated RF drive levels in dBm for the rf stage; "
                         "the token 'off' is the RF-off reference (default 'off,0')")
    ap.add_argument("--rf-grid", type=int, default=8,
                    help="phi* grid size for the rf-stage lock comparison (default 8)")
    a = ap.parse_args()

    def _pilot_list():
        return tuple(float(x) for x in a.pilot_list.split(",") if x.strip())

    def _rf_powers():
        out = []
        for x in a.rf_powers.split(","):
            x = x.strip()
            if not x:
                continue
            out.append(None if x.lower() in ("off", "none") else float(x))
        return tuple(out)

    def run_selected(board, dmm, scope, siggen, specan, datadir):
        vpi, v0 = a.vpi, a.v0
        if a.stage in ("bringup",):
            stage_bringup(board, dmm, scope)
        if a.stage in ("vpi", "all"):
            vpi, v0 = stage_vpi(board, dmm, datadir, pilot_v=a.pilot_v)
        if a.stage in ("calib", "all"):
            if vpi is None:
                fit_prev = _load_fit(datadir) if os.path.exists(
                    os.path.join(datadir, "calib_fit.json")) else None
                res_prev = ec.load_results()
                vpi = (fit_prev or {}).get("vpi") or res_prev.get("vpi_V")
                v0 = (fit_prev or {}).get("v0") or res_prev.get("v0_V")
            if vpi is None:
                vpi, v0 = stage_vpi(board, dmm, datadir, pilot_v=a.pilot_v)
            stage_calib(board, dmm, datadir, vpi, v0, pilot_v=a.pilot_v,
                        n=a.n_points or 181, n_blocks=a.n_blocks or 16,
                        n_avg=a.n_avg, cal_method=a.cal_method)
        if a.stage in ("pilotdiag",):
            if vpi is None:
                res_prev = ec.load_results()
                vpi = res_prev.get("vpi_V"); v0 = res_prev.get("v0_V")
            if vpi is None:
                raise RuntimeError("pilotdiag needs vpi/v0; run stage vpi first")
            stage_pilotdiag(board, dmm, scope, datadir, vpi, v0,
                            amps=_pilot_list(), n_blocks=a.n_blocks or 16,
                            n_avg=a.n_avg, scope_every=a.scope_every)
        if a.stage in ("lock", "all"):
            stage_lock(board, dmm, datadir, n_grid=a.n_grid, iters=a.iters,
                       n_blocks=a.n_blocks or 16, n_avg=a.n_avg, gain=a.gain)
        if a.stage in ("pilot", "all"):
            stage_pilot(board, dmm, datadir, amps=_pilot_list(), vpi=vpi, v0=v0,
                        n=a.n_points or 121, n_blocks=a.n_blocks or 16,
                        n_avg=a.n_avg)
        if a.stage in ("drift", "all"):
            stage_drift(board, dmm, datadir, iters=a.drift_iters,
                        n_blocks=a.n_blocks or 12,
                        n_avg=a.n_avg, upset=a.drift_upset)
        if a.stage in ("stability",):
            stage_stability(board, dmm, datadir, duration_s=a.duration_h * 3600,
                            n_blocks=a.n_blocks or 16, n_avg=a.n_avg)
        if a.stage in ("rf",):
            stage_rf(board, dmm, siggen, specan, datadir, rf_hz=a.rf_hz,
                     rf_ch=a.rf_ch, powers_dbm=_rf_powers(), n_grid=a.rf_grid,
                     iters=a.iters, n_blocks=a.n_blocks or 16, n_avg=a.n_avg,
                     gain=a.gain)

    if a.sim:
        datadir = os.path.join(ec.REPO, "build", "exp_sim")
        os.makedirs(datadir, exist_ok=True)
        # redirect exp_common's results.json into the sim dir too
        ec.DATA = datadir
        board = SimBoard(); dmm = None if a.no_dmm else SimDMM(board); scope = None
        siggen = SimSigGen(board, vpi=board.VPI); specan = SimSpecAn(board)
        print(f"[sim] writing to {os.path.relpath(datadir, ec.REPO)} (gitignored)")
        run_selected(board, dmm, scope, siggen, specan, datadir)
    else:
        datadir = ec.ensure_data_dir()
        with ExitStack() as stack:
            board = stack.enter_context(open_board())
            dmm = None if a.no_dmm else stack.enter_context(open_dmm())
            scope = None if a.no_scope else stack.enter_context(open_scope())
            siggen = specan = None
            if a.stage == "rf":            # only this stage needs the RF gear
                siggen = stack.enter_context(open_siggen())
                specan = None if a.no_specan else stack.enter_context(open_specan())
            run_selected(board, dmm, scope, siggen, specan, datadir)


if __name__ == "__main__":
    main()
