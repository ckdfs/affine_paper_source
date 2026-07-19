#!/usr/bin/env python3
"""Shared, hardware-free helpers for the EXPERIMENTAL validation of the affine
framework (single MZM).  Imported by both:

  * measure_bench.py  -- drives the bench, runs the PC affine/baseline loops
  * make_exp_figs.py  -- renders figs/fig_exp*.pdf from recorded data

Only numpy/scipy are required here (NO pyserial / sockets), so the figure
script and check.py can import this without any instrument present.

The affine calibration math (ellipse fit -> gauge fixing via the DC curve ->
demod matrix B) is ported 1:1 from scripts/make_figs.py:calibrate_mzm so the
experiment reconstructs phase exactly the way the simulation does.  The ONLY
difference is the input: here (X, Y, dc) are *measured* arrays, not generated.

Data layout under data/exp/ (all git-tracked, like figs/):
  vpi.csv          bias, DMM/board DC, direction, time/order (stage 0)
  calib.npz        bias, X/Y/DC/raw I/Q, time/order/direction (stage 1)
  lock_sweep.npz   phi_star, rms/static per controller      (stage 2)
  pilot_depth.csv  Ap[V], m, kappa, resid_mrad              (stage 3)
  drift.npz        t, err_mrad, rho_bar, recal_events       (stage 4)
  results.json     derived headline numbers (the number contract; see check.py)
"""
from __future__ import annotations
import json
import os
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data", "exp")


# --------------------------------------------------------------------------- #
#  small math utilities                                                       #
# --------------------------------------------------------------------------- #
def wrap(x):
    """Wrap angle(s) to (-pi, pi]."""
    return (np.asarray(x, float) + np.pi) % (2 * np.pi) - np.pi


# --------------------------------------------------------------------------- #
#  affine ellipse calibration on MEASURED data                                #
#  (geometry identical to make_figs.py:calibrate_mzm, lines 38-60)            #
# --------------------------------------------------------------------------- #
def calibrate_from_data(X, Y, dc, j0_sign: float = 1.0) -> dict:
    """Fit the observation ellipse and gauge-fix its phase origin from the DC
    transfer curve.

    Parameters
    ----------
    X, Y : 1-D arrays of the two demodulated observation channels over a
           (near) full-period bias sweep, sample order == sweep order.
    dc   : the *unclipped* DC power at the same samples (from DM858E).
    j0_sign : sign of J0(m); +1 for the small/typical pilot depths used here.

    Returns dict with c0 (center b_hat), B (demod matrix), M (shape matrix),
    A_hat = B^{-1} (the affine gain), kappa = cond(A_hat), and us (pulled-back
    unit-circle points, for plotting).
    """
    X = np.asarray(X, float); Y = np.asarray(Y, float); dc = np.asarray(dc, float)
    N = len(X)
    mx, my = X.mean(), Y.mean()
    sc = np.hypot(X - mx, Y - my).mean()
    x, y = (X - mx) / sc, (Y - my) / sc
    D = np.stack([x * x, x * y, y * y, x, y], 1)
    th = np.linalg.solve(D.T @ D, D.T @ np.ones(N))
    a, b, c, d, e = th
    det = 4 * a * c - b * b
    cx = (b * e - 2 * c * d) / det
    cy = (b * d - 2 * a * e) / det
    kq = 1 - (a * cx * cx + b * cx * cy + c * cy * cy + d * cx + e * cy)
    M = np.array([[a, b / 2], [b / 2, c]]) / kq
    c0 = np.array([mx + sc * cx, my + sc * cy])
    M = M / sc ** 2
    w, V = np.linalg.eigh(M)
    B = V @ np.diag(np.sqrt(w)) @ V.T
    us = (B @ np.stack([X - c0[0], Y - c0[1]])).T
    # winding direction -> reflection so phase advances right-handed
    cr = np.sum(us[:-1, 0] * us[1:, 1] - us[:-1, 1] * us[1:, 0])
    if cr < 0:
        B = np.diag([1, -1]) @ B
        us[:, 1] *= -1
    # gauge fixing: regress the DC curve on (1, cos th, sin th) to find origin
    th_i = np.arctan2(us[:, 1], us[:, 0])
    Dg = np.stack([np.ones(N), np.cos(th_i), np.sin(th_i)], 1)
    cf = np.linalg.solve(Dg.T @ Dg, Dg.T @ dc)
    sgn = 1 if j0_sign >= 0 else -1
    phc = np.arctan2(sgn * cf[2], sgn * cf[1])
    dphi = -phc
    R = np.array([[np.cos(dphi), -np.sin(dphi)], [np.sin(dphi), np.cos(dphi)]])
    B = R @ B
    A_hat = np.linalg.inv(B)
    us = (B @ np.stack([X - c0[0], Y - c0[1]])).T
    return dict(c0=c0, B=B, M=M, A_hat=A_hat,
                kappa=float(np.linalg.cond(A_hat)), us=us)


def calibrate_phase_ref(X, Y, phase_truth) -> dict:
    """Fit z = A [cos(phi), sin(phi)] + b using DC-derived phase labels.

    The slow Vpi scan and the AC harmonics share one optical branch.  The DC
    labels are independent of the board ADC/Goertzel electronics, but are not
    an independent optical phase reference.
    """
    X = np.asarray(X, float); Y = np.asarray(Y, float)
    phi = np.asarray(phase_truth, float)
    F = np.stack([np.cos(phi), np.sin(phi), np.ones_like(phi)], 1)
    Z = np.stack([X, Y], 1)
    C = np.linalg.lstsq(F, Z, rcond=None)[0]
    A_hat = C[:2, :].T
    c0 = C[2, :]
    B = np.linalg.inv(A_hat)
    us = (B @ (Z - c0).T).T
    return dict(c0=c0, B=B, M=B.T @ B, A_hat=A_hat,
                kappa=float(np.linalg.cond(A_hat)), us=us)


def demod_phase(z, cal: dict) -> float:
    """Phase estimate from one observation z=(X,Y) using a calibration dict."""
    u = cal["B"] @ (np.asarray(z, float) - cal["c0"])
    return float(np.arctan2(u[1], u[0]))


def circle_residual(z, cal: dict) -> float:
    """Runtime residual rho = | ||B(z-b)|| - 1 |  (the recal monitor)."""
    u = cal["B"] @ (np.asarray(z, float) - cal["c0"])
    return float(abs(np.hypot(u[0], u[1]) - 1.0))


def self_check_mrad(X, Y, cal: dict, phase_truth) -> dict:
    """Compare a calibration sweep with its same-scan DC-derived phase labels.

    Return {median, p95, rms} of |error| in mrad.  This is an in-sample
    consistency check, not an independent test error.
    """
    U = cal["B"] @ np.stack([np.asarray(X) - cal["c0"][0],
                             np.asarray(Y) - cal["c0"][1]])
    phi_hat = np.arctan2(U[1], U[0])
    e = np.abs(wrap(phi_hat - phase_truth)) * 1e3
    return dict(median=float(np.median(e)), p95=float(np.percentile(e, 95)),
                rms=float(np.sqrt(np.mean(e ** 2))))


# --------------------------------------------------------------------------- #
#  DC transfer curve  ->  auxiliary phase labels  phi(V_b)                     #
# --------------------------------------------------------------------------- #
def align_periodic_origin(v0, reference, vpi):
    """Move an equivalent cosine maximum onto the branch nearest reference.

    ``V0`` is defined only modulo the full optical period ``2*Vpi``.  Directly
    averaging two independently fitted representatives can therefore land at
    the intervening minimum.  Return the aligned representative and the signed
    integer number of full periods applied.
    """
    period = 2.0 * abs(float(vpi))
    if not np.isfinite(period) or period <= 0:
        raise ValueError("vpi must be finite and positive for V0 alignment")
    shift_periods = int(np.rint((float(reference) - float(v0)) / period))
    return float(v0 + shift_periods * period), shift_periods


def fit_dc_transfer(bias, dc, vpi_hint=None, v0_hint=None,
                    vpi_rel_bound=0.15):
    """Fit P(V_b) = a + b*cos(pi*(V_b - V0)/Vpi) to the slow DC sweep.

    Returns (a, b, vpi, v0).  Initial guesses come from the data span and the
    dominant FFT period, then refined by scipy least squares.  Phase truth is
    then  phi(V_b) = pi*(V_b - V0)/Vpi  (V0 = a bias where P is maximal).
    """
    from scipy.optimize import curve_fit
    bias = np.asarray(bias, float); dc = np.asarray(dc, float)
    a0 = dc.mean(); b0 = (dc.max() - dc.min()) / 2
    # crude Vpi guess: half the bias span over the number of half-periods seen
    span = bias.max() - bias.min()
    # count sign changes of the de-meaned, lightly smoothed curve
    s = np.sign(dc - a0)
    halfper = max(1, np.count_nonzero(np.diff(s) != 0))
    vpi0 = span / halfper if halfper else span
    v00 = bias[np.argmax(dc)]

    def model(v, a, b, vpi, v0):
        return a + b * np.cos(np.pi * (v - v0) / vpi)

    try:
        if vpi_hint is not None or v0_hint is not None:
            if vpi_hint is None or v0_hint is None:
                raise ValueError("vpi_hint and v0_hint must be supplied together")
            vpi0 = abs(float(vpi_hint))
            v00 = float(v0_hint)
            if not (np.isfinite(vpi0) and vpi0 > 0 and
                    0 < float(vpi_rel_bound) < 1):
                raise ValueError("invalid constrained DC-fit hint or bound")
            # A one-period calibration sweep is vulnerable to noisy sign-change
            # counting.  The immediately preceding bidirectional scan supplies
            # the physically relevant basin; b>0 keeps V0 on a maximum branch.
            b0 = max(float(b0), np.finfo(float).eps)
            lo = [-np.inf, 0.0, (1.0 - vpi_rel_bound) * vpi0, v00 - vpi0]
            hi = [np.inf, np.inf, (1.0 + vpi_rel_bound) * vpi0, v00 + vpi0]
            p, _ = curve_fit(model, bias, dc, p0=[a0, b0, vpi0, v00],
                             bounds=(lo, hi), maxfev=50000)
        else:
            p, _ = curve_fit(model, bias, dc,
                             p0=[a0, b0, vpi0, v00], maxfev=20000)
        a, b, vpi, v0 = p
        vpi = abs(vpi)
        if b < 0:                      # keep b>0: V0 marks a maximum
            b = -b; v0 = v0 + vpi
    except Exception:
        if vpi_hint is not None or v0_hint is not None:
            raise
        a, b, vpi, v0 = a0, b0, vpi0, v00
    return float(a), float(b), float(vpi), float(v0)


def bias_to_phase(bias, vpi, v0):
    """Auxiliary phase labels from the fitted DC transfer curve."""
    return np.pi * (np.asarray(bias, float) - v0) / vpi


def phase_truth_from_dc(dc, a, b, sin_sign):
    """Drift-robust DC-derived phase estimate at a single point.

    From the DC transfer P = a + b cos(phi):  |phi| = acos((P-a)/b).  The
    sign of sin(phi) (which branch) is supplied externally from the LOCAL DC
    slope sign (dP/dV = -b*(pi/Vpi)*sin(phi)), so this does not depend on V0 and
    survives slow drift of the operating point between calibration and locking.
    It is independent of the controller electronics, but shares the same optical
    path and therefore is not an independent optical truth reference.
    """
    c = float(np.clip((dc - a) / b, -1.0, 1.0))
    mag = float(np.arccos(c))
    return float(wrap((1.0 if sin_sign >= 0 else -1.0) * mag))


def canonical_period_center(v0, vpi, lo=-9.0, hi=9.0):
    """Shift the equivalent DC maximum V0 by integer optical periods (2*Vpi)
    so that [V0-Vpi, V0+Vpi] fits the available bias window when possible."""
    v0 = float(v0); vpi = abs(float(vpi))
    centers = [v0 + 2 * k * vpi for k in range(-8, 9)]
    safe = [c for c in centers if c - vpi >= lo and c + vpi <= hi]
    if safe:
        return float(min(safe, key=abs))
    def violation(c):
        return max(0.0, lo - (c - vpi)) + max(0.0, (c + vpi) - hi)
    return float(min(centers, key=lambda c: (violation(c), abs(c))))


# --------------------------------------------------------------------------- #
#  data IO                                                                    #
# --------------------------------------------------------------------------- #
def ensure_data_dir():
    os.makedirs(DATA, exist_ok=True)
    return DATA


def path(name: str) -> str:
    return os.path.join(DATA, name)


def have(name: str) -> bool:
    return os.path.exists(path(name))


def load_results() -> dict:
    p = path("results.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def update_results(**kv):
    """Merge derived numbers into data/exp/results.json (the experiment number
    contract enforced by check.py [5])."""
    ensure_data_dir()
    cur = load_results()
    cur.update(kv)
    save_results(cur)
    return cur


def save_results(cur: dict):
    ensure_data_dir()
    with open(path("results.json"), "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2, sort_keys=True)
    return cur
