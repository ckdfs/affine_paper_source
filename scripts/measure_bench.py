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
import exp_common_dp as ecdp  # noqa: E402

# bench constants ----------------------------------------------------------- #
PILOT_HZ = 1000.0          # board default pilot
H2_HZ = 2000.0             # second harmonic
PILOT_V = 0.10             # default pilot amplitude (V on the bias line)
CH = "A"                   # default MZM bias DAC channel
BIAS_LIMIT = 9.0           # keep |bias|+|pilot| < 10 V (board clips otherwise)
ACQ_FREQS = (PILOT_HZ, H2_HZ)
RF_HZ = 50e6               # default applied RF tone (stage 5 robustness)
RF_CH = 1                  # DG922pro channel feeding the MZM RF port

# DPMZM bench constants (device swapped in; A->phi1 sub-I, B->phi2 sub-Q,        #
# C->phi3 parent; single combined-output PD).  Three pilots, one per bias axis,  #
# chosen on the 50 Hz Goertzel grid so the 9 observation channels                #
# {wi, 2wi, |wi-wj|} are mutually leakage-free.                                   #
DP_CH = ("A", "B", "C")                       # sub-I, sub-Q, parent bias DACs
DP_PILOTS_HZ = (1100.0, 1400.0, 1900.0)       # w1, w2, w3
DP_PILOT_V = 0.12                             # per-axis pilot amplitude (V)
DP_MAX_ACQ_FREQS = 9                           # rebuilt firmware stores all DP bins
DP_MAX_BLOCKS = 10                             # 9 bins + 3 pilots stalls above this


def _dp_acq_freqs(pilots=DP_PILOTS_HZ):
    """The 9 lock-in demod frequencies in A0 row order: six harmonics
    {w1,2w1,w2,2w2,w3,2w3} then three IMD difference tones
    {|w1-w2|, |w1-w3|, |w2-w3|}  (rows Z-, Z13, Z23)."""
    w1, w2, w3 = pilots
    return (w1, 2 * w1, w2, 2 * w2, w3, 2 * w3,
            abs(w1 - w2), abs(w1 - w3), abs(w2 - w3))


DP_ACQ_FREQS = _dp_acq_freqs()
DP_ACQ_CHUNKS = tuple(tuple(DP_ACQ_FREQS[i:i + DP_MAX_ACQ_FREQS])
                      for i in range(0, len(DP_ACQ_FREQS), DP_MAX_ACQ_FREQS))


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
#  DPMZM: analytic model for --sim + real-board 3-pilot / 9-channel front end  #
# --------------------------------------------------------------------------- #
class SimBoardDP:
    """Stand-in for a DPMZM-wired BiasBoard.  Returns the 9-channel lock-in
    observation z = Atrue @ Phi(phi) + btrue + noise and the single combined-PD
    DC intensity (eq:dpmzm).  phi=(phi1,phi2,phi3) maps from the A/B/C bias lines
    by per-axis Vpi/V0.  For --sim tooling validation the AC observation uses a
    generous fixed pilot depth (m=1.2, like the paper simulation) and a low noise
    floor so the identify->demod->lock pipeline closes to ~mrad -- this is a CODE
    check, the honest shallow-pilot SNR story comes from the REAL bench."""
    VPI = (5.5, 5.3, 5.7)              # per-axis half-wave voltage (sub1, sub2, parent)
    V0 = (-1.3, -0.8, 0.6)             # per-axis bias at the cos maximum
    SIM_DEPTH = (1.2, 1.2, 1.2)        # effective pilot depths for A0 (sim only)
    SIGMA = 0.002                      # per-channel AC noise (matches make_figs)
    P0 = 1.49                          # PD DC peak (V), like the single-MZM bench
    CH1_FS = 1.20                      # board CH1 ADC full scale (clips)

    def __init__(self, seed=11):
        self.rng = np.random.default_rng(seed)
        A0 = ecdp.buildA0(*self.SIM_DEPTH)
        sc = 0.12 * np.linalg.norm(A0) / np.sqrt(A0.size)
        self.Atrue = A0 + sc * self.rng.standard_normal((9, 12))
        self.btrue = 0.5 * 0.02 * self.rng.standard_normal(9)
        self._last_dc_true = self.P0
        self.freqs = DP_ACQ_FREQS

    def phi_of(self, biases):
        return np.array([np.pi * (biases[i] - self.V0[i]) / self.VPI[i]
                         for i in range(3)])

    def dc_true_at(self, biases):
        """Unclipped combined-PD DC (what the DMM sees) at a 3-axis bias."""
        return float(self.P0 * ecdp.dp_intensity(self.phi_of(biases)))

    def acq_run_dp(self, biases, n_blocks=10):
        phi = self.phi_of(biases)
        s = self.SIGMA / np.sqrt(max(1, n_blocks))
        z = self.Atrue @ ecdp.feat(phi) + self.btrue + s * self.rng.standard_normal(9)
        dc_true = self.dc_true_at(biases)
        self._last_dc_true = dc_true
        dc_board = min(dc_true, self.CH1_FS)          # board CH1 clips like the MZM bench
        tones = {}
        for i, f in enumerate(self.freqs):
            I = float(z[i]); Q = float(0.05 * s * self.rng.standard_normal())
            tones[f] = {"I": I, "Q": Q, "mag": float(np.hypot(I, Q)),
                        "phase": float(np.arctan2(Q, I))}
        return {"blocks": n_blocks, "dc": dc_board, "tones": tones}


def _dp_write_biases(board, biases):
    """Stage the three DP bias voltages in one serial write."""
    cmd = "".join(f"gen bias {ch} {float(v):.4f}\r\n"
                  for ch, v in zip(DP_CH, biases))
    board._ser.reset_input_buffer()
    board._ser.write(cmd.encode()); board._ser.flush()
    board._read(settle=0.04, idle_gap=0.08, max_total=0.4)        # drain echoes


def _dp_config_acq_freqs(board, freqs, verify=False):
    """Configure one real-board acq frequency chunk.

    The rebuilt firmware used for the DPMZM experiment stores all nine Goertzel
    bins.  The chunk abstraction is kept only so older firmware can be tested by
    lowering DP_MAX_ACQ_FREQS without touching the measurement stages."""
    freqs = tuple(float(f) for f in freqs)
    if getattr(board, "_dp_acq_freqs", None) == freqs:
        return
    # Do not batch these lines: the board accepts 9 bins after the firmware
    # rebuild, but rapid multi-line acq_add writes can still drop commands over
    # USB CDC.  This setup is cached, so the per-point loop stays fast.
    board.acq_reset()
    for f in freqs:
        board.acq_add(f)
    board._dp_acq_freqs = freqs
    if verify:
        show = board.acq_show()
        if f"freqs: {len(freqs)}" not in show:
            raise RuntimeError(f"failed to configure {len(freqs)} acq freqs: {show!r}")


def prepare_dpmzm_frontend(board, pilots=DP_PILOTS_HZ, pilot_v=DP_PILOT_V):
    """Configure the real board once for repeated DPMZM points: three bias DACs
    and three pilots (one per axis), plus the nine DP acq frequencies."""
    if isinstance(board, SimBoardDP):
        return
    for _ in range(3):
        board.gen_reset()
        for ch in DP_CH:
            board.gen_bias(ch, 0.0)
        for ch, w in zip(DP_CH, pilots):
            board.gen_pilot(ch, w, pilot_v)
        try:
            for chunk in DP_ACQ_CHUNKS:
                _dp_config_acq_freqs(board, chunk, verify=True)
            board._dp_acq_freqs = None
            return
        except Exception:
            time.sleep(0.3)
    print("[warn] prepare_dpmzm_frontend: DP gen/acq chunks not confirmed after retries")


def choose_comps9(I9, Q9):
    """Per channel pick the lock-in component (I or Q) carrying the larger sweep
    variance -- the board's per-tone reference phase is unknown, the consistent
    dominant component is absorbed into the identified A (rows scale freely)."""
    I9 = np.asarray(I9); Q9 = np.asarray(Q9)
    return ["I" if np.var(I9[:, k]) >= np.var(Q9[:, k]) else "Q"
            for k in range(I9.shape[1])]


def dp_obs_vector(acq, comps9, freqs=DP_ACQ_FREQS):
    """Extract the 9-vector z from an acq result, one chosen component per tone."""
    return np.array([acq["tones"][f][comps9[k]] for k, f in enumerate(freqs)])


def _parse_acq(board, txt):
    import math
    out = {"blocks": None, "dc": None, "tones": {}, "_raw": txt}
    m = board._ACQ_RE.search(txt)
    if not m:
        return out
    out["blocks"] = int(m.group(1)); out["dc"] = float(m.group(2))
    for tok in m.group(3).split():
        p = tok.split(",")
        if len(p) == 3:
            f, I, Q = float(p[0]), float(p[1]), float(p[2])
            out["tones"][f] = {"I": I, "Q": Q,
                               "mag": math.hypot(I, Q), "phase": math.atan2(Q, I)}
    return out


def _dp_run_acq_chunk(board, freqs, n_blocks):
    _dp_config_acq_freqs(board, freqs)
    n_blocks = min(int(n_blocks), DP_MAX_BLOCKS)
    win = max(2.0, n_blocks * 0.025 + 1.5)
    txt = board.command(f"acq run {int(n_blocks)}", settle=0.4, idle_gap=0.3,
                        max_total=win)
    return _parse_acq(board, txt)


def _dp_acq_at(board, biases, n_blocks, _retry=True):
    """Real-board point: stage the three DP biases, acquire the 9 observation
    tones, and merge them back into one acq dict.  Retries once if the ACQ line
    came back truncated."""
    _dp_write_biases(board, biases)
    merged = {"blocks": int(n_blocks), "dc": None, "tones": {}, "_raw_chunks": []}
    dcs = []
    for chunk in DP_ACQ_CHUNKS:
        out = _dp_run_acq_chunk(board, chunk, n_blocks)
        merged["_raw_chunks"].append(out.get("_raw", ""))
        if out.get("dc") is not None:
            dcs.append(out["dc"])
        for f in chunk:
            if f in out["tones"]:
                merged["tones"][f] = out["tones"][f]
    merged["dc"] = float(np.mean(dcs)) if dcs else None
    if len(merged["tones"]) < len(DP_ACQ_FREQS) and _retry:
        board._dp_acq_freqs = None
        return _dp_acq_at(board, biases, n_blocks, _retry=False)
    if len(merged["tones"]) < len(DP_ACQ_FREQS):
        missing = [f for f in DP_ACQ_FREQS if f not in merged["tones"]]
        raise RuntimeError(f"truncated DP acq, missing {missing}")
    return merged


def _dp_apply_bias_for_dmm(board, biases, n_blocks=1):
    """Apply a DP bias on real hardware with the shortest useful acq run.

    The firmware commits gen-bias values during acq generation, so DMM-only
    sweeps only need one Goertzel bin, not the full 9-channel observation."""
    _dp_write_biases(board, biases)
    return _dp_run_acq_chunk(board, (DP_ACQ_FREQS[0],), n_blocks)


def acq_run_dp(board, biases, n_blocks, pilots=DP_PILOTS_HZ):
    """One raw 9-channel acquisition at a 3-axis bias (sim or real board)."""
    if isinstance(board, SimBoardDP):
        return board.acq_run_dp(biases, n_blocks=n_blocks)
    return _dp_acq_at(board, biases, n_blocks)


def dp_point(board, dmm, biases, n_blocks):
    """Acquire the raw 9-tone result + the unclipped DMM DC at a 3-axis bias."""
    if isinstance(board, SimBoardDP):
        board._last_dc_true = board.dc_true_at(biases)
        acq = board.acq_run_dp(biases, n_blocks=n_blocks)
        dc = dmm.measure_dc_voltage() if dmm else float("nan")
        return acq, dc
    acq = acq_run_dp(board, biases, n_blocks)
    return acq, read_dc(dmm)


def read_dc_at_dp_bias(board, dmm, biases, settle=0.15):
    """Set a 3-axis bias and read the unclipped DMM DC (controller-independent
    per-axis phase truth for the DPMZM lock/vpi stages).

    NB: the firmware writes the DAC only inside `acq run` -- `gen bias` alone
    stages the value but leaves the output unmoved (see app_main.c).  So apply
    the bias with a short acq_run before reading the DMM, mirroring the
    single-MZM stage_vpi (which sweeps via acq_point_prepared)."""
    if isinstance(board, SimBoardDP):
        board._last_dc_true = board.dc_true_at(biases)
        return (board.dc_true_at(biases) if dmm is None
                else dmm.measure_dc_voltage())
    _dp_apply_bias_for_dmm(board, biases, n_blocks=1)
    time.sleep(settle)
    return read_dc(dmm)


def _dp_complete(acq):
    return all(f in acq["tones"] for f in DP_ACQ_FREQS)


def _dp_point_complete(board, dmm, biases, n_blocks, tries=4):
    """A dp_point whose acq contains all 9 tones (retry the flaky USB drop)."""
    for _ in range(tries):
        acq, dc = dp_point(board, dmm, biases, n_blocks)
        if _dp_complete(acq):
            return acq, dc
    return acq, dc                                  # last attempt (caller tolerates)


def average_dp_point(board, dmm, biases, n_blocks, n_avg=1):
    """Average n_avg short 9-channel acquisitions (raises the weak IMD-channel
    SNR), returning (mean tones dict, dc).  Mirrors average_acq_point.  Each
    acquisition is retried until all nine tones are present."""
    if n_avg <= 1:
        return _dp_point_complete(board, dmm, biases, n_blocks)
    freqs = DP_ACQ_FREQS
    accI = np.zeros(9); accQ = np.zeros(9); dcs = []
    for _ in range(n_avg):
        acq, dc = _dp_point_complete(board, dmm, biases, n_blocks)
        accI += np.array([acq["tones"][f]["I"] for f in freqs])
        accQ += np.array([acq["tones"][f]["Q"] for f in freqs])
        dcs.append(dc)
    accI /= n_avg; accQ /= n_avg
    tones = {f: {"I": float(accI[k]), "Q": float(accQ[k]),
                 "mag": float(np.hypot(accI[k], accQ[k])),
                 "phase": float(np.arctan2(accQ[k], accI[k]))}
             for k, f in enumerate(freqs)}
    return ({"blocks": n_blocks, "dc": acq["dc"], "tones": tones},
            float(np.nanmean(dcs)))


# --------------------------------------------------------------------------- #
#  Scope-FFT POWER acquisition (bypasses the board ADC's +-1.2 V clip).         #
#  The board only drives bias + a DEEP continuous pilot (`gen run`); the scope  #
#  reads the POWER at the 9 channel frequencies via its FFT (no phase).  This   #
#  matches the magnitude-only control path (exp_common_dp.calibrate_dp_mag /    #
#  gn_demod_mag) and a real deployment where the lock-in phase is uncontrolled. #
# --------------------------------------------------------------------------- #
DP_PILOT_V_SCOPE = 0.7              # deep pilot for the scope path (board ADC bypassed)
DP_FFT_CENTER = 2000.0
DP_FFT_SPAN = 4000.0


def prepare_scope_fft_dp(board, scope, pilots=DP_PILOTS_HZ, pilot_v=DP_PILOT_V_SCOPE):
    """Configure the board pilots once and the scope channel/timebase/edge trigger.
    The scope FFT MARKER readout proved unreliable (reads the noise floor); we
    capture the RAW waveform and do a PC Goertzel (the validated path) instead."""
    if isinstance(board, SimBoardDP):
        board._scope_pilot_v = pilot_v
        return
    board.gen_reset()
    for ch in DP_CH:
        board.gen_bias(ch, 0.0)
    for ch, w in zip(DP_CH, pilots):
        board.gen_pilot(ch, w, pilot_v)
    # turn OFF any FFT math function: a lingering FFT FREEZES get_waveform (it
    # returns the same stale frame at every bias).  Plain Y-T capture only.
    try:
        scope.fft_off()
    except Exception:
        pass
    scope.send(":FUNCtion1 OFF")
    scope.setup_channel(1, coupling="AC"); scope.setup_timebase(5e-2)


def _pc_goertzel9(t, v):
    """9-channel POWER magnitude (phase-invariant) from a raw scope waveform; the
    freqs are 100 Hz multiples so a 10 ms window is leakage-free."""
    t = np.asarray(t, float); v = np.asarray(v, float) - np.mean(v)
    dt = t[1] - t[0]; n = min(int(round(0.01 / dt)), len(v))
    tt = t[:n] - t[0]; vv = v[:n]
    return np.array([np.hypot((2 / n) * np.sum(vv * np.cos(2 * np.pi * f * tt)),
                              (2 / n) * np.sum(vv * np.sin(2 * np.pi * f * tt)))
                     for f in DP_ACQ_FREQS])


def _scope_capture(scope, timeout=2.0):
    """One SINGLE-triggered frame (poll TRIG:STATus until Stop, then read)."""
    scope.send(":TRIGger:MODE SINGle"); t0 = time.time()
    while time.time() - t0 < timeout:
        if "Stop" in scope.query(":TRIGger:STATus?"):
            break
        time.sleep(0.02)
    return scope.get_waveform(1, max_points=20000)


def scope_power_dp(board, scope, biases, settle=1.0, navg=3):
    """9-channel POWER magnitude at a 3-axis bias.  Real board: set bias, start a
    NON-BLOCKING continuous deep pilot (`gen start` -- runs until the next
    command, so it never overlaps the next point), let it settle, capture `navg`
    raw SINGLE frames + PC Goertzel, MEDIAN, then stop the pilot with a harmless
    `status` (keeps the pilot config).  Sim: |signed z| from the analytic model."""
    F = DP_ACQ_FREQS
    if isinstance(board, SimBoardDP):
        acq = board.acq_run_dp(biases, n_blocks=20)
        return np.array([abs(acq["tones"][f]["I"]) for f in F])
    for ch, v in zip(DP_CH, biases):
        board.gen_bias(ch, float(v))
    board._ser.reset_input_buffer()
    board._ser.write(b"gen start\r\n"); board._ser.flush()
    time.sleep(settle)                                  # pilot comes up (~1 s)
    mags = []
    for _ in range(navg):
        t, v = _scope_capture(scope)
        if len(v) > 10 and np.ptp(v) > 0.05:
            mags.append(_pc_goertzel9(np.array(t), np.array(v)))
        time.sleep(0.12)          # let the scope re-acquire; a back-to-back SINGLE
        #                           otherwise returns the prior frozen frame
    # stop the continuous pilot (any command breaks gen-start; `status` keeps the
    # pilot CONFIG so the next point's gen-start reuses it) and drain the replies.
    board._ser.write(b"status\r\n"); board._ser.flush()
    try:
        board._read(settle=0.0, idle_gap=0.2, max_total=1.5)
    except Exception:
        pass
    return np.median(mags, axis=0) if mags else np.full(9, np.nan)


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


# --------------------------------------------------------------------------- #
#  DPMZM stages (device swapped in: A->phi1 sub-I, B->phi2 sub-Q, C->phi3      #
#  parent; single combined PD).  See plan parsed-brewing-wadler.md.            #
#  Shared per-axis Vpi/V0 + identified (Ah,bh,comps) live in dp_fit.json.      #
# --------------------------------------------------------------------------- #
def _dp_load_fit(datadir):
    with open(os.path.join(datadir, "dp_fit.json")) as f:
        return json.load(f)


def _dp_save_fit(datadir, **kv):
    p = os.path.join(datadir, "dp_fit.json")
    cur = {}
    if os.path.exists(p):
        with open(p) as f:
            cur = json.load(f)
    cur.update(kv)
    with open(p, "w") as f:
        json.dump(cur, f, indent=2)
    return cur


def dp_bias_of_phi(phi, vpi, v0):
    """Per-axis phase -> bias (the controller commands bias)."""
    return np.array([v0[i] + phi[i] * vpi[i] / np.pi for i in range(3)])


def dp_phi_of_bias(bias, vpi, v0):
    return np.array([np.pi * (bias[i] - v0[i]) / vpi[i] for i in range(3)])


def _triwave(x, lo, hi):
    """Reflect an unbounded coordinate x into a triangle wave spanning [lo, hi]
    (keeps the quasi-periodic scan inside the reachable +-9 V bias window)."""
    p = hi - lo
    t = (x - lo) % (2 * p)
    return lo + (t if t <= p else 2 * p - t)


def _dp_build_Z(I9, Q9, comps):
    """Pick the chosen lock-in component per channel -> N x 9 observation."""
    return np.stack([I9[:, j] if comps[j] == "I" else Q9[:, j]
                     for j in range(9)], axis=1)


def _dp_sweep_axis(board, dmm, i, park, grid):
    """Sweep bias axis i over `grid` with the other axes held at `park` (3-vec);
    return the unclipped DMM DC array."""
    return np.array([read_dc_at_dp_bias(board, dmm, _with(park, i, V)) for V in grid])


def stage_dp_vpi(board, dmm, datadir, lo=-9.0, hi=9.0, n=61, pilot_v=DP_PILOT_V,
                 n_blocks=12, n_avg=1):
    """DPMZM stage (6a): per-axis Vpi/V0 + sub-axis 4*pi confirmation + IMD
    purity control.

    The combined PD is cross-coupled, so a naive single-axis fit fails.  A stable
    bootstrap is: coarse-find the two sub-axis peaks, fit the parent with both
    subs near peak, place the parent at quadrature (cos T3 = 0) to kill the
    half-angle cross term, then fit each sub-axis as a clean single-cosine
    self-fringe.  This sequence is verified by the DPMZM --sim path before the
    real bench is used."""
    configure_dc_fast(dmm)
    prepare_dpmzm_frontend(board, pilot_v=pilot_v)
    vpi = [0.0, 0.0, 0.0]; v0 = [0.0, 0.0, 0.0]
    store = {}
    bias = np.linspace(lo, hi, n)

    # Step 1: coarse sub-I peak (others at 0).  The argmax is robust even though
    # the cross term distorts the fringe.
    dcI0 = _dp_sweep_axis(board, dmm, 0, [0.0, 0.0, 0.0], bias)
    store["I0_bias"] = bias; store["I0_dc"] = dcI0
    Ipk = float(bias[int(np.argmax(dcI0))])
    print(f"[dp-vpi] coarse sub-I peak@{Ipk:+.2f}", flush=True)

    # Step 2: coarse sub-Q peak with I parked near its peak.
    dcQ0 = _dp_sweep_axis(board, dmm, 1, [Ipk, 0.0, 0.0], bias)
    store["Q0_bias"] = bias; store["Q0_dc"] = dcQ0
    Qpk = float(bias[int(np.argmax(dcQ0))])
    print(f"[dp-vpi] coarse sub-Q peak@{Qpk:+.2f}", flush=True)

    # Step 3: parent fringe with both sub axes near their peaks.
    dcP = _dp_sweep_axis(board, dmm, 2, [Ipk, Qpk, 0.0], bias)
    _, _, vpi[2], v0[2] = ec.fit_dc_transfer(bias, dcP); vpi[2] = abs(vpi[2])
    store["P_bias"] = bias; store["P_dc"] = dcP
    Pquad = float(np.clip(v0[2] + 0.5 * vpi[2], lo, hi))
    print(f"[dp-vpi] parent (subs@peak): Vpi={vpi[2]:.3f} V  "
          f"V0={v0[2]:+.3f} V  quad@{Pquad:+.2f}", flush=True)

    # Step 4: sub axes cleanly fitted with parent at quadrature (cross term off).
    dcI = _dp_sweep_axis(board, dmm, 0, [0.0, Qpk, Pquad], bias)
    _, _, vpi[0], v0[0] = ec.fit_dc_transfer(bias, dcI); vpi[0] = abs(vpi[0])
    store["I_bias"] = bias; store["I_dc"] = dcI
    print(f"[dp-vpi] sub-I (P@quad): Vpi={vpi[0]:.3f} V  V0={v0[0]:+.3f} V",
          flush=True)

    dcQ = _dp_sweep_axis(board, dmm, 1, [v0[0], 0.0, Pquad], bias)
    _, _, vpi[1], v0[1] = ec.fit_dc_transfer(bias, dcQ); vpi[1] = abs(vpi[1])
    store["Q_bias"] = bias; store["Q_dc"] = dcQ
    print(f"[dp-vpi] sub-Q (P@quad): Vpi={vpi[1]:.3f} V  V0={v0[1]:+.3f} V",
          flush=True)

    # Optional parent refinement with the refined sub peaks.
    dcP2 = _dp_sweep_axis(board, dmm, 2, [v0[0], v0[1], 0.0], bias)
    _, _, vpi[2], v0[2] = ec.fit_dc_transfer(bias, dcP2); vpi[2] = abs(vpi[2])
    store["P2_bias"] = bias; store["P2_dc"] = dcP2
    print(f"[dp-vpi] parent refined: Vpi={vpi[2]:.3f} V  V0={v0[2]:+.3f} V",
          flush=True)

    # --- 4*pi confirmation: fine sweep the sub with the SMALLER Vpi (more period
    #     coverage in range), other sub + parent at peak (max half-angle cross term)
    si = 0 if vpi[0] <= vpi[1] else 1; oj = 1 - si
    fine = np.linspace(lo, hi, 4 * n)
    park = [v0[0], v0[1], v0[2]]                 # both subs + parent at peak
    dc_fine = np.array([read_dc_at_dp_bias(board, dmm, _with(park, si, V)) for V in fine])
    half = 2 * vpi[si]                           # +2*pi in Theta == +2*Vpi in bias
    contrast = 0.0
    for k, V in enumerate(fine):
        if V + half <= fine[-1]:
            contrast = max(contrast,
                           abs(dc_fine[k] - dc_fine[int(np.argmin(np.abs(fine - (V + half))))]))
    amp1 = (dc_fine.max() - dc_fine.min()) / 2
    contrast_rel = float(contrast / amp1) if amp1 > 0 else 0.0
    span_periods = (hi - lo) / (2 * vpi[si])     # how many 2*pi periods fit in range
    store["fine_bias"] = fine; store["fine_dc"] = dc_fine; store["fine_axis"] = si
    if span_periods < 1.0:
        print(f"[dp-vpi] 4*pi: sub-{si} Vpi={vpi[si]:.2f} V too large to span 2*pi "
              f"in +-9 V (only {span_periods:.2f} period) -- partial demo", flush=True)
    print(f"[dp-vpi] 4*pi distinguishability: max|P(Th1)-P(Th1+2pi)|/amp = "
          f"{contrast_rel:.3f}  ({'DISTINGUISHABLE' if contrast_rel > 0.1 else 'flat'})")
    # save the (critical) Vpi/V0 fit BEFORE the optional IMD purity control, so a
    # purity hiccup never discards the characterization
    _dp_save_fit(datadir, vpi=vpi, v0=v0, pilot_v=pilot_v)
    # --- IMD purity: |Z-| at mid-fringe vs at sub1 null (kills sin(Th1/2)) ---
    imd_mid = imd_nul = purity = float("nan")
    try:
        b_mid = np.clip(dp_bias_of_phi([np.pi / 2, np.pi / 2, 0.0], vpi, v0), lo, hi)
        b_nul = np.clip(dp_bias_of_phi([0.0, np.pi / 2, 0.0], vpi, v0), lo, hi)  # Th1=0
        f_imd = DP_ACQ_FREQS[6]                     # |w1-w2| channel
        acq_m, _ = average_dp_point(board, dmm, b_mid, n_blocks, max(n_avg, 2))
        acq_n, _ = average_dp_point(board, dmm, b_nul, n_blocks, max(n_avg, 2))
        imd_mid = acq_m["tones"][f_imd]["mag"]; imd_nul = acq_n["tones"][f_imd]["mag"]
        purity = float(imd_nul / imd_mid) if imd_mid > 0 else float("nan")
        print(f"[dp-vpi] IMD purity |Z-|(null)/|Z-|(mid) = {purity:.3f}  "
              f"({'optical (collapses)' if purity < 0.5 else 'check electrical pickup'})")
    except Exception as e:
        print(f"[dp-vpi] IMD purity skipped: {e}")
    np.savez(os.path.join(datadir, "dp_vpi.npz"), vpi=vpi, v0=v0,
             contrast_rel=contrast_rel, imd_mid=imd_mid, imd_nul=imd_nul,
             purity=purity, pilot_v=pilot_v, **store)
    res = ec.load_results()
    res["dp_vpi"] = dict(vpi=[round(x, 4) for x in vpi],
                         v0=[round(x, 4) for x in v0],
                         contrast_rel=round(contrast_rel, 3),
                         imd_purity=round(purity, 3))
    ec.save_results(res)
    return vpi, v0


def _with(b3, i, V):
    """Copy of the 3-axis bias b3 with axis i overridden to V."""
    b = list(b3); b[i] = V
    return b


def stage_dp_calib(board, dmm, datadir, pilot_v=DP_PILOT_V, N=1500,
                   n_blocks=14, n_avg=1, incr=(0.04241, 0.05317, 0.06789),
                   reprocess=False):
    """DPMZM stage (6b): quasi-periodic 3-axis scan -> bounded joint identification
    of (Ah,bh) + the per-axis Vpi scaling, and the held-out model-prediction
    residual (the bench-measurable counterpart of the simulation's identification
    error; no ground-truth A on the bench).  Also reports sigma_min(6->9) from the
    *measured* Ah.  reprocess=True re-fits the SAVED raw scan (dp_calib.npz)
    without re-acquiring -- used to re-analyse a scan after a fit-method fix."""
    fit = _dp_load_fit(datadir)
    vpi = fit["vpi"]; v0 = fit["v0"]
    if reprocess:
        d = np.load(os.path.join(datadir, "dp_calib.npz"))
        BIASES = d["biases"]; I9 = d["I9"]; Q9 = d["Q9"]; DC = d["dc"]
        N = len(BIASES)
        print(f"[dp-calib] reprocessing saved scan: {N} points (no re-acquire)", flush=True)
    else:
        configure_dc_fast(dmm)
        prepare_dpmzm_frontend(board, pilot_v=pilot_v)
        # Quasi-periodic trajectory confined to the reachable bias box: the
        # unbounded phase walk would drive bias past +-9 V, so reflect
        # (triangle-wave) the per-axis bias within [-9+m, 9-m] V with
        # incommensurate increments.  This densely covers the *reachable* phase
        # region -- enough excitation for the identification.
        margin = 0.4
        blo, bhi = -BIAS_LIMIT + margin, BIAS_LIMIT - margin
        step = np.array([max(0.05, incr[i] * vpi[i] / np.pi) for i in range(3)])
        BIASES = np.zeros((N, 3)); I9 = np.zeros((N, 9)); Q9 = np.zeros((N, 9))
        DC = np.zeros(N)
        for k in range(N):
            bias = np.array([_triwave(k * step[i], blo, bhi) for i in range(3)])
            BIASES[k] = bias
            acq, dc = average_dp_point(board, dmm, bias, n_blocks, n_avg)
            for j, f in enumerate(DP_ACQ_FREQS):
                I9[k, j] = acq["tones"][f]["I"]; Q9[k, j] = acq["tones"][f]["Q"]
            DC[k] = dc
            if k == 0 or (k + 1) % 50 == 0 or k == N - 1:
                print(f"[dp-calib] {k + 1:4d}/{N}", flush=True)
    comps = choose_comps9(I9, Q9)
    Z = _dp_build_Z(I9, Q9, comps)
    # JOINT identification: refine the per-axis bias->phase scaling together with
    # (A,b).  The per-axis Vpi from dp-vpi is only a seed -- the combined-PD
    # half-angle period and the dim Q arm make the isolated single-axis fits
    # unreliable, so we pin the scaling from the whole 9-channel response.
    cal = ecdp.calibrate_dp_joint(BIASES, Z, vpi, v0)
    Ah, bh = cal["Ah"], cal["bh"]
    vpi = [round(x, 4) for x in cal["vpi"]]; v0 = [round(x, 4) for x in cal["v0"]]
    PH = np.stack([dp_phi_of_bias(BIASES[k], cal["vpi"], cal["v0"]) for k in range(N)])
    m = [float(np.pi * pilot_v / max(0.2, cal["vpi"][i])) for i in range(3)]
    A0 = ecdp.buildA0(*m)
    relF_struct = ecdp.relF(Ah, A0)
    s6 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.HARM_ROWS)
    s9 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.ALL_ROWS)
    print(f"[dp-calib] joint-refined Vpi={[round(x,2) for x in cal['vpi']]} "
          f"V0={[round(x,2) for x in cal['v0']]}", flush=True)
    np.savez(os.path.join(datadir, "dp_calib.npz"), PH=PH, Z=Z, I9=I9, Q9=Q9,
             dc=DC, biases=BIASES, Ah=Ah, bh=bh, A0=A0, comps=np.array(comps),
             vpi=cal["vpi"], v0=cal["v0"], m=m, pilots=DP_PILOTS_HZ,
             n_blocks=n_blocks, n_avg=n_avg)
    _dp_save_fit(datadir, Ah=Ah.tolist(), bh=bh.tolist(), comps=list(comps),
                 vpi=cal["vpi"], v0=cal["v0"], m=m, pilots=list(DP_PILOTS_HZ),
                 pilot_v=pilot_v, relF_holdout_pct=cal["relF_holdout_pct"])
    accepted = bool(cal["relF_holdout_pct"] <= 25.0)
    print(f"[dp-calib] relF holdout={cal['relF_holdout_pct']:.3f}%  "
          f"in-sample={cal['relF_insample_pct']:.3f}%  structF={relF_struct:.2f}%  "
          f"sigma_min 6ch={s6:.2e} 9ch={s9:.4f}  accepted={accepted}")
    summary = dict(relF_holdout_pct=round(cal["relF_holdout_pct"], 3),
                   relF_insample_pct=round(cal["relF_insample_pct"], 3),
                   relF_struct_pct=round(relF_struct, 2),
                   sigmin_6ch=round(s6, 5), sigmin_9ch=round(s9, 5),
                   N=int(N), n_blocks=int(n_blocks), n_avg=int(n_avg),
                   accepted=accepted)
    res = ec.load_results()
    res["dp_calib_headline"] = summary
    if accepted:
        res["dp_relF_pct"] = round(cal["relF_holdout_pct"], 3)
    else:
        res.pop("dp_relF_pct", None)
        print("[dp-calib] diagnostic only: residual above gate; dp_relF_pct not set")
    ec.save_results(res)
    return Ah, bh, comps


def stage_dp_obs(board, dmm, datadir, pilot_v=DP_PILOT_V, n_blocks=16, n_avg=4,
                 grid=41, n_probe=24):
    """DPMZM stage (7): IMD observability recovery.  (i) sigma_min maps over
    (phi1,phi2) at phi3=pi/2 with 6 vs 9 channels, from the *measured* Ah; (ii) a
    measured parent-axis test near the standard point -- command small parent
    dithers and reconstruct them with 6 vs 9 channels (6ch is near-blind)."""
    fit = _dp_load_fit(datadir)
    Ah = np.array(fit["Ah"]); bh = np.array(fit["bh"]); comps = fit["comps"]
    vpi = fit["vpi"]; v0 = fit["v0"]
    configure_dc_fast(dmm)
    prepare_dpmzm_frontend(board, pilot_v=pilot_v)
    f = np.linspace(0, 4 * np.pi, grid)

    def smap(rows, phi3):
        M = np.zeros((grid, grid))
        for i, a in enumerate(f):
            for j, b in enumerate(f):
                M[j, i] = ecdp.sigmin(Ah, [a, b, phi3], rows)
        return M
    M6 = smap(ecdp.HARM_ROWS, np.pi / 2); M9 = smap(ecdp.ALL_ROWS, np.pi / 2)
    s6 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.HARM_ROWS)
    s9 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.ALL_ROWS)
    # measured parent-axis observability: reconstruct commanded parent dithers
    base = np.array(ecdp.STD_POINT)
    J = Ah @ ecdp.dfeat(base)
    rng = np.random.default_rng(0)
    d3 = rng.uniform(-0.25, 0.25, n_probe)
    e6 = []; e9 = []
    for dd in d3:
        bias = np.clip(dp_bias_of_phi(base + np.array([0, 0, dd]), vpi, v0),
                       -BIAS_LIMIT, BIAS_LIMIT)
        acq, _ = average_dp_point(board, dmm, bias, n_blocks, n_avg)
        z = dp_obs_vector(acq, comps)
        r = z - (Ah @ ecdp.feat(base) + bh)
        d9 = np.linalg.lstsq(J[ecdp.ALL_ROWS], r[ecdp.ALL_ROWS], rcond=None)[0]
        d6 = np.linalg.lstsq(J[ecdp.HARM_ROWS], r[ecdp.HARM_ROWS], rcond=None)[0]
        e9.append(abs(d9[2] - dd)); e6.append(abs(d6[2] - dd))
    err6 = float(np.sqrt(np.mean(np.square(e6))))
    err9 = float(np.sqrt(np.mean(np.square(e9))))
    print(f"[dp-obs] sigma_min @std  6ch={s6:.2e}  9ch={s9:.4f}  "
          f"(recovery x{s9 / max(s6, 1e-9):.1f})")
    print(f"[dp-obs] parent-dither recon rms  6ch={err6 * 1e3:.0f} mrad  "
          f"9ch={err9 * 1e3:.0f} mrad")
    np.savez(os.path.join(datadir, "dp_obs.npz"), f=f, M6=M6, M9=M9, s6=s6, s9=s9,
             d3=d3, e6=np.array(e6), e9=np.array(e9), err6=err6, err9=err9)
    res = ec.load_results()
    res["dp_sigmin_6ch"] = round(s6, 4)
    res["dp_sigmin_9ch"] = round(s9, 4)
    res["dp_obs_headline"] = dict(sigmin_6ch=round(s6, 5), sigmin_9ch=round(s9, 5),
                                  parent_recon_6ch_mrad=round(err6 * 1e3, 1),
                                  parent_recon_9ch_mrad=round(err9 * 1e3, 1),
                                  n_avg=int(n_avg))
    ec.save_results(res)
    return s6, s9


def _dp_audit_from_z(z, Ah, bh):
    """Controller-independent phase readout from one already-acquired 9-channel z:
    multi-seed cold-start GN, pick the minimum-residual solution.  No extra
    acquisition -- the control loop already measured z this iteration.  For the
    three-loop baseline this is fully independent of its scalar control law, so
    the GN-vs-baseline comparison is fair (same operator on each achieved state).
    """
    seeds = [(0, 0, 0), ecdp.STD_POINT, ecdp.ARB_POINT,
             (np.pi, 0, 0), (0, np.pi, np.pi)]
    best = None; bestr = np.inf
    for s in seeds:
        est = ecdp.gn_demod(z, np.array(s, float), Ah, bh, iters=10)
        r = np.linalg.norm(z - (Ah @ ecdp.feat(est) + bh))
        if r < bestr:
            bestr = r; best = est
    return best


def stage_dp_lock(board, dmm, datadir, pilot_v=DP_PILOT_V, iters=40, n_blocks=14,
                  n_avg=1, gain=0.3, audit_navg=4):
    """DPMZM stage (8): three-axis arbitrary-point lock.  GN-affine controller
    vs three independent scalar loops, both sharing the same gen/acq path, at an
    arbitrary target and at the standard QPSK target.  Per-iteration error is the
    controller-independent audit phase (cold multi-seed GN on the iteration's own
    z) vs target; in --sim the exact phi_of is used instead."""
    fit = _dp_load_fit(datadir)
    Ah = np.array(fit["Ah"]); bh = np.array(fit["bh"]); comps = fit["comps"]
    vpi = fit["vpi"]; v0 = fit["v0"]
    configure_dc_fast(dmm)
    prepare_dpmzm_frontend(board, pilot_v=pilot_v)

    def truth(bias, z):
        if isinstance(board, SimBoardDP):
            return board.phi_of(bias)
        return _dp_audit_from_z(z, Ah, bh)

    def run_gn(tgt):
        tgt = np.array(tgt, float); est = tgt + 0.3; phi_cmd = tgt + 0.3
        errs = []
        for _ in range(iters):
            bias = np.clip(dp_bias_of_phi(phi_cmd, vpi, v0), -BIAS_LIMIT, BIAS_LIMIT)
            acq, _ = average_dp_point(board, dmm, bias, n_blocks, n_avg)
            z = dp_obs_vector(acq, comps)
            est = ecdp.gn_demod(z, est, Ah, bh, iters=3)
            phi_cmd = phi_cmd - gain * ecdp.wrap(est - tgt)
            errs.append(1e3 * np.linalg.norm(ecdp.wrap(truth(bias, z) - tgt)))
        return np.array(errs)

    def run_3loop(tgt):
        tgt = np.array(tgt, float)
        ref = Ah[[0, 2, 6]] @ ecdp.feat(tgt)
        Jd = Ah @ ecdp.dfeat(tgt)
        slopes = np.array([Jd[0, 0], Jd[2, 1], Jd[6, 2]])
        fl = np.array([abs(Ah[0, 1]), abs(Ah[2, 3]), abs(Ah[6, 10])])
        slopes = np.sign(np.where(slopes == 0, 1, slopes)) * \
            np.maximum(np.abs(slopes), 0.15 * fl)
        phi_cmd = tgt + 0.3; errs = []
        for _ in range(iters):
            bias = np.clip(dp_bias_of_phi(phi_cmd, vpi, v0), -BIAS_LIMIT, BIAS_LIMIT)
            acq, _ = average_dp_point(board, dmm, bias, n_blocks, n_avg)
            z = dp_obs_vector(acq, comps)
            e = np.clip((z[[0, 2, 6]] - ref) / slopes, -1, 1)
            phi_cmd = phi_cmd - gain * e
            errs.append(1e3 * np.linalg.norm(ecdp.wrap(truth(bias, z) - tgt)))
        return np.array(errs)

    tail = slice(int(0.6 * iters), None)
    out = {}
    for name, tgt in [("arb", ecdp.ARB_POINT), ("std", ecdp.STD_POINT)]:
        eG = run_gn(tgt); eT = run_3loop(tgt)
        rG = float(np.sqrt(np.mean(eG[tail] ** 2)))
        rT = float(np.sqrt(np.mean(np.clip(eT[tail], 0, 3142) ** 2)))
        out[name] = dict(eG=eG, eT=eT, rG=rG, rT=rT)
        print(f"[dp-lock] {name}: GN rms={rG:.1f} mrad  three-loop rms={rT:.1f} mrad",
              flush=True)
    np.savez(os.path.join(datadir, "dp_lock.npz"),
             arb_eG=out["arb"]["eG"], arb_eT=out["arb"]["eT"],
             std_eG=out["std"]["eG"], std_eT=out["std"]["eT"],
             arb_target=ecdp.ARB_POINT, std_target=ecdp.STD_POINT,
             gain=gain, iters=iters, n_avg=n_avg)
    res = ec.load_results()
    res["dp_lock_rms_arb_gn_mrad"] = round(out["arb"]["rG"], 1)
    res["dp_lock_rms_arb_3loop_mrad"] = round(out["arb"]["rT"], 1)
    res["dp_lock_rms_std_gn_mrad"] = round(out["std"]["rG"], 1)
    res["dp_lock_rms_std_3loop_mrad"] = round(out["std"]["rT"], 1)
    res["dp_lock_headline"] = dict(gain=gain, iters=int(iters), n_avg=int(n_avg),
                                   audit_navg=int(audit_navg))
    ec.save_results(res)
    return out


# --------------------------------------------------------------------------- #
#  MAGNITUDE-MODE DPMZM stages (scope-FFT power; bypasses the board ADC clip)   #
# --------------------------------------------------------------------------- #
def stage_dp_calib_mag(board, scope, dmm, datadir, pilot_v=DP_PILOT_V_SCOPE,
                       N=400, incr=(0.04241, 0.05317, 0.06789)):
    """DPMZM calib (magnitude mode): quasi-periodic 3-axis scan read by the scope
    FFT (POWER only), bounded-Vpi magnitude identification (v0 fixed to the DC
    maxima from dp-vpi).  Deep pilot -> strong IMD, unclipped."""
    fit = _dp_load_fit(datadir)
    vpi = fit["vpi"]; v0 = fit["v0"]
    prepare_scope_fft_dp(board, scope, pilot_v=pilot_v)
    margin = 0.4; blo, bhi = -BIAS_LIMIT + margin, BIAS_LIMIT - margin
    step = np.array([max(0.05, incr[i] * vpi[i] / np.pi) for i in range(3)])
    BIASES = np.zeros((N, 3)); MAG = np.zeros((N, 9))
    for k in range(N):
        bias = np.array([_triwave(k * step[i], blo, bhi) for i in range(3)])
        BIASES[k] = bias
        MAG[k] = scope_power_dp(board, scope, bias)
        if k == 0 or (k + 1) % 25 == 0 or k == N - 1:
            print(f"[dp-calib-mag] {k + 1:4d}/{N}", flush=True)
    # mask channels that read nan too often (noise floor); fill nan per channel
    good = np.isfinite(MAG)
    for j in range(9):
        col = MAG[:, j]
        col[~np.isfinite(col)] = np.nanmin(col[np.isfinite(col)]) if good[:, j].any() else 0.0
    cal = ecdp.calibrate_dp_mag_joint(BIASES, MAG, vpi, v0)
    Ah = cal["Ah"]; vpi = cal["vpi"]
    PH = np.stack([dp_phi_of_bias(BIASES[k], vpi, v0) for k in range(N)])
    s6 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.HARM_ROWS)
    s9 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.ALL_ROWS)
    print(f"[dp-calib-mag] holdout={cal['relF_holdout_pct']:.2f}%  Vpi={[round(x,2) for x in vpi]}  "
          f"sigma_min 6ch={s6:.3f} 9ch={s9:.3f} (x{s9/max(s6,1e-9):.1f})", flush=True)
    np.savez(os.path.join(datadir, "dp_calib.npz"), biases=BIASES, MAG=MAG, PH=PH,
             Ah=Ah, A0=ecdp.buildA0(1.0, 1.0, 1.0), vpi=vpi, v0=v0,
             pilots=DP_PILOTS_HZ, mode="mag", pilot_v=pilot_v)
    _dp_save_fit(datadir, Ah=Ah.tolist(), vpi=list(vpi), v0=list(v0),
                 pilots=list(DP_PILOTS_HZ), pilot_v=pilot_v, mode="mag",
                 relF_holdout_pct=cal["relF_holdout_pct"])
    accepted = bool(cal["relF_holdout_pct"] <= 25.0)
    res = ec.load_results()
    res["dp_calib_headline"] = dict(relF_holdout_pct=round(cal["relF_holdout_pct"], 3),
                                    sigmin_6ch=round(s6, 5), sigmin_9ch=round(s9, 5),
                                    N=int(N), mode="mag", pilot_v=pilot_v,
                                    accepted=accepted)
    if accepted:
        res["dp_relF_pct"] = round(cal["relF_holdout_pct"], 3)
    ec.save_results(res)
    return Ah, vpi, v0


def stage_dp_obs_mag(board, scope, datadir, pilot_v=DP_PILOT_V_SCOPE, grid=41,
                     n_probe=24):
    """DPMZM observability (magnitude mode): sigma_min(6 vs 9) maps from the
    measured Ah, and a measured parent-dither reconstruction (6 vs 9 channels)
    via the magnitude Jacobian near the standard point."""
    fit = _dp_load_fit(datadir)
    Ah = np.array(fit["Ah"]); vpi = fit["vpi"]; v0 = fit["v0"]
    prepare_scope_fft_dp(board, scope, pilot_v=pilot_v)
    f = np.linspace(0, 4 * np.pi, grid)

    def smap(rows, phi3):
        M = np.zeros((grid, grid))
        for i, a in enumerate(f):
            for j, b in enumerate(f):
                M[j, i] = ecdp.sigmin(Ah, [a, b, phi3], rows)
        return M
    M6 = smap(ecdp.HARM_ROWS, np.pi / 2); M9 = smap(ecdp.ALL_ROWS, np.pi / 2)
    s6 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.HARM_ROWS)
    s9 = ecdp.sigmin(Ah, ecdp.STD_POINT, ecdp.ALL_ROWS)
    base = np.array(ecdp.STD_POINT)
    g0 = Ah @ ecdp.feat(base); Jm = np.sign(g0)[:, None] * (Ah @ ecdp.dfeat(base))
    m0 = np.abs(g0)
    rng = np.random.default_rng(0); d3 = rng.uniform(-0.25, 0.25, n_probe)
    e6 = []; e9 = []
    for dd in d3:
        bias = np.clip(dp_bias_of_phi(base + np.array([0, 0, dd]), vpi, v0),
                       -BIAS_LIMIT, BIAS_LIMIT)
        m = scope_power_dp(board, scope, bias)
        dm = m - m0
        d9 = np.linalg.lstsq(Jm[ecdp.ALL_ROWS], dm[ecdp.ALL_ROWS], rcond=None)[0]
        d6 = np.linalg.lstsq(Jm[ecdp.HARM_ROWS], dm[ecdp.HARM_ROWS], rcond=None)[0]
        e9.append(abs(d9[2] - dd)); e6.append(abs(d6[2] - dd))
    err6 = float(np.sqrt(np.mean(np.square(e6))))
    err9 = float(np.sqrt(np.mean(np.square(e9))))
    print(f"[dp-obs-mag] sigma_min std 6ch={s6:.4f} 9ch={s9:.4f} (x{s9/max(s6,1e-9):.1f}); "
          f"parent recon 6ch={err6*1e3:.0f} 9ch={err9*1e3:.0f} mrad", flush=True)
    np.savez(os.path.join(datadir, "dp_obs.npz"), f=f, M6=M6, M9=M9, s6=s6, s9=s9,
             d3=d3, e6=np.array(e6), e9=np.array(e9), err6=err6, err9=err9, mode="mag")
    res = ec.load_results()
    res["dp_sigmin_6ch"] = round(s6, 4); res["dp_sigmin_9ch"] = round(s9, 4)
    res["dp_obs_headline"] = dict(sigmin_6ch=round(s6, 5), sigmin_9ch=round(s9, 5),
                                  parent_recon_6ch_mrad=round(err6 * 1e3, 1),
                                  parent_recon_9ch_mrad=round(err9 * 1e3, 1), mode="mag")
    ec.save_results(res)
    return s6, s9


def stage_dp_lock_mag(board, scope, datadir, pilot_v=DP_PILOT_V_SCOPE, iters=40,
                      gain=0.3):
    """DPMZM three-axis lock (magnitude mode): GN-affine (gn_demod_mag) vs three
    independent scalar-magnitude loops, at an arbitrary and the standard target.
    Truth = cold multi-seed gn_demod_mag on the iteration's own power vector."""
    fit = _dp_load_fit(datadir)
    Ah = np.array(fit["Ah"]); vpi = fit["vpi"]; v0 = fit["v0"]
    prepare_scope_fft_dp(board, scope, pilot_v=pilot_v)
    seeds = [(0, 0, 0), ecdp.STD_POINT, ecdp.ARB_POINT, (np.pi, 0, -np.pi / 2)]

    def truth(bias, m):
        if isinstance(board, SimBoardDP):
            return board.phi_of(bias)
        best = None; br = np.inf
        for s in seeds:
            est = ecdp.gn_demod_mag(m, np.array(s, float), Ah, iters=12)
            r = np.linalg.norm(m ** 2 - (Ah @ ecdp.feat(est)) ** 2)
            if r < br:
                br = r; best = est
        return best

    def run_gn(tgt):
        tgt = np.array(tgt, float); est = tgt + 0.3; phi_cmd = tgt + 0.3; errs = []
        for _ in range(iters):
            bias = np.clip(dp_bias_of_phi(phi_cmd, vpi, v0), -BIAS_LIMIT, BIAS_LIMIT)
            m = scope_power_dp(board, scope, bias)
            est = ecdp.gn_demod_mag(m, phi_cmd, Ah, iters=8)   # seed from command
            phi_cmd = phi_cmd - gain * ecdp.wrap(est - tgt)
            errs.append(1e3 * np.linalg.norm(ecdp.wrap(truth(bias, m) - tgt)))
        return np.array(errs)

    def run_3loop(tgt):
        tgt = np.array(tgt, float)
        rows = [0, 2, 6]
        mref = np.abs(Ah[rows] @ ecdp.feat(tgt))
        Jd = np.sign(Ah @ ecdp.feat(tgt))[:, None] * (Ah @ ecdp.dfeat(tgt))
        slopes = np.array([Jd[0, 0], Jd[2, 1], Jd[6, 2]])
        slopes = np.sign(np.where(slopes == 0, 1, slopes)) * np.maximum(np.abs(slopes), 1e-3)
        phi_cmd = tgt + 0.3; errs = []
        for _ in range(iters):
            bias = np.clip(dp_bias_of_phi(phi_cmd, vpi, v0), -BIAS_LIMIT, BIAS_LIMIT)
            m = scope_power_dp(board, scope, bias)
            e = np.clip((m[rows] - mref) / slopes, -1, 1)
            phi_cmd = phi_cmd - gain * e
            errs.append(1e3 * np.linalg.norm(ecdp.wrap(truth(bias, m) - tgt)))
        return np.array(errs)

    tail = slice(int(0.6 * iters), None); out = {}
    for name, tgt in [("arb", ecdp.ARB_POINT), ("std", ecdp.STD_POINT)]:
        eG = run_gn(tgt); eT = run_3loop(tgt)
        rG = float(np.sqrt(np.mean(eG[tail] ** 2)))
        rT = float(np.sqrt(np.mean(np.clip(eT[tail], 0, 3142) ** 2)))
        out[name] = dict(eG=eG, eT=eT, rG=rG, rT=rT)
        print(f"[dp-lock-mag] {name}: GN rms={rG:.1f}  three-loop rms={rT:.1f} mrad", flush=True)
    np.savez(os.path.join(datadir, "dp_lock.npz"),
             arb_eG=out["arb"]["eG"], arb_eT=out["arb"]["eT"],
             std_eG=out["std"]["eG"], std_eT=out["std"]["eT"],
             arb_target=ecdp.ARB_POINT, std_target=ecdp.STD_POINT,
             gain=gain, iters=iters, mode="mag")
    res = ec.load_results()
    res["dp_lock_rms_arb_gn_mrad"] = round(out["arb"]["rG"], 1)
    res["dp_lock_rms_arb_3loop_mrad"] = round(out["arb"]["rT"], 1)
    res["dp_lock_rms_std_gn_mrad"] = round(out["std"]["rG"], 1)
    res["dp_lock_rms_std_3loop_mrad"] = round(out["std"]["rT"], 1)
    res["dp_lock_headline"] = dict(gain=gain, iters=int(iters), mode="mag")
    ec.save_results(res)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["bringup", "vpi", "calib", "pilotdiag",
                                       "lock", "pilot", "drift", "stability",
                                       "rf", "all",
                                       "dp-vpi", "dp-calib", "dp-obs", "dp-lock",
                                       "dp-all"])
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
    ap.add_argument("--dp-n", type=int, default=1500,
                    help="quasi-periodic scan length for dp-calib (default 1500)")
    ap.add_argument("--dp-pilot-v", type=float, default=None,
                    help=f"per-axis DPMZM pilot amplitude (default {DP_PILOT_V} V board "
                         f"path, {DP_PILOT_V_SCOPE} V scope path)")
    ap.add_argument("--scope-acq", action="store_true",
                    help="DPMZM calib/obs/lock: read POWER via the scope FFT (deep "
                         "pilot, bypasses the board ADC clip) + magnitude-only math")
    a = ap.parse_args()
    if a.dp_pilot_v is None:
        a.dp_pilot_v = DP_PILOT_V_SCOPE if a.scope_acq else DP_PILOT_V

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
        if a.stage in ("dp-vpi", "dp-all"):
            stage_dp_vpi(board, dmm, datadir, pilot_v=a.dp_pilot_v,
                         n=a.n_points or 181, n_blocks=a.n_blocks or DP_MAX_BLOCKS,
                         n_avg=a.n_avg)
        if a.stage in ("dp-calib", "dp-all"):
            if a.scope_acq:
                stage_dp_calib_mag(board, scope, dmm, datadir,
                                   pilot_v=a.dp_pilot_v, N=a.dp_n)
            else:
                stage_dp_calib(board, dmm, datadir, pilot_v=a.dp_pilot_v, N=a.dp_n,
                               n_blocks=a.n_blocks or DP_MAX_BLOCKS, n_avg=a.n_avg)
        if a.stage in ("dp-obs", "dp-all"):
            if a.scope_acq:
                stage_dp_obs_mag(board, scope, datadir, pilot_v=a.dp_pilot_v)
            else:
                stage_dp_obs(board, dmm, datadir, pilot_v=a.dp_pilot_v,
                             n_blocks=a.n_blocks or DP_MAX_BLOCKS,
                             n_avg=a.n_avg if a.n_avg > 1 else 4)
        if a.stage in ("dp-lock", "dp-all"):
            if a.scope_acq:
                stage_dp_lock_mag(board, scope, datadir, pilot_v=a.dp_pilot_v,
                                  iters=a.iters, gain=a.gain)
            else:
                stage_dp_lock(board, dmm, datadir, pilot_v=a.dp_pilot_v,
                              iters=a.iters, n_blocks=a.n_blocks or DP_MAX_BLOCKS,
                              n_avg=a.n_avg, gain=a.gain)

    if a.sim:
        datadir = os.path.join(ec.REPO, "build", "exp_sim")
        os.makedirs(datadir, exist_ok=True)
        # redirect exp_common's results.json into the sim dir too
        ec.DATA = datadir
        if a.stage.startswith("dp"):
            board = SimBoardDP(); scope = siggen = specan = None
            dmm = None if a.no_dmm else SimDMM(board)
        else:
            board = SimBoard(); scope = None
            dmm = None if a.no_dmm else SimDMM(board)
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
