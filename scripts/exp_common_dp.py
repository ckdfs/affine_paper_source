#!/usr/bin/env python3
"""Shared, hardware-free helpers for the EXPERIMENTAL validation of the affine
framework on a **DPMZM** (dual-parallel MZM).  Companion to exp_common.py
(single MZM); imported by both:

  * measure_bench.py   -- drives the bench DPMZM stages (vpi/calib/obs/lock)
  * make_exp_figs.py   -- renders figs/fig_exp4-6.pdf from recorded data

Only numpy/scipy are required (NO pyserial / sockets), so the figure script and
check.py can import this without any instrument present.

The DPMZM feature map Phi, its Jacobian, the ideal observation matrix A0, the
linear-regression identification, the damped Gauss-Newton demodulator and the
observability singular value are ported 1:1 from scripts/make_figs.py (Part II,
lines 185-241 / 287-302) so the experiment reconstructs phase exactly the way
the simulation does.  The ONLY difference is the input: here z, the per-axis
phase truth PH, and the pilot depths are *measured*, not generated.

Data layout under data/exp/ (git-tracked, like the single-MZM files):
  dp_vpi.npz     per-axis Vpi/V0 + the 4*Vpi sub-axis scan (4-pi confirmation)
  dp_calib.npz   quasi-periodic scan {PH, Z}, identified Ah/bh, fit residual
  dp_obs.npz     sigma_min(6ch) vs sigma_min(9ch) maps + standard-point values
  dp_lock.npz    GN-affine vs three-loop error traces at arbitrary/standard pts
  results.json   shared with exp_common (the number contract; see check.py [5])

IO helpers (load_results / save_results / update_results / path / have) and the
angle wrap are re-exported from exp_common so there is a single results.json
writer and a single DATA root.
"""
from __future__ import annotations
import numpy as np
from scipy.special import jv

# single source of truth for results.json IO + DATA dir + angle wrap
from exp_common import (  # noqa: F401  (re-exported on purpose)
    wrap, ensure_data_dir, path, have,
    load_results, update_results, save_results,
)

# --------------------------------------------------------------------------- #
#  canonical target points (match make_figs.py:dp_loop)                       #
# --------------------------------------------------------------------------- #
# Targets use a NEGATIVE parent phase: on the real bench the parent transmission
# peak (V0_3) sits near the +rail, so only phi3 in ~[-5,0.7] is reachable within
# +-9 V.  phi3 = -pi/2 is the same QPSK quadrature/rank-degeneracy as +pi/2 (cos
# is even), and -1.0 rad is a reachable arbitrary parent phase; both are also
# reachable in --sim.
STD_POINT = (np.pi, np.pi, -np.pi / 2)     # standard QPSK bias (parent quadrature)
ARB_POINT = (2.0, 2.6, -1.0)               # an arbitrary interior target

HARM_ROWS = list(range(6))                 # 6 harmonic channels  Y1 X1 Y2 X2 Y3 X3
ALL_ROWS = list(range(9))                  # + 3 IMD channels     Z- Z13 Z23

# row / feature labels for the identified-A heatmap (fig:exp6, see fig:ahat)
CH_LABELS = ['$Y_1$', '$X_1$', '$Y_2$', '$X_2$', '$Y_3$', '$X_3$',
             '$Z_-$', '$Z_{13}$', '$Z_{23}$']
FEAT_LABELS = ['$c\\varphi_1$', '$s\\varphi_1$', '$c\\varphi_2$', '$s\\varphi_2$',
               '$ccC$', '$ccS$', '$csC$', '$csS$', '$scC$', '$scS$',
               '$ssC$', '$ssS$']


# --------------------------------------------------------------------------- #
#  12-D trigonometric feature map  Phi : T^3 -> R^12  and its Jacobian         #
#  (ported verbatim from make_figs.py:185-198; half-angle sub-axis structure) #
# --------------------------------------------------------------------------- #
def feat(p):
    c1, s1 = np.cos(p[0] / 2), np.sin(p[0] / 2)
    c2, s2 = np.cos(p[1] / 2), np.sin(p[1] / 2)
    C, S = np.cos(p[2]), np.sin(p[2])
    return np.array([c1 * c1 - s1 * s1, 2 * c1 * s1, c2 * c2 - s2 * s2, 2 * c2 * s2,
                     c1 * c2 * C, c1 * c2 * S, c1 * s2 * C, c1 * s2 * S,
                     s1 * c2 * C, s1 * c2 * S, s1 * s2 * C, s1 * s2 * S])


def dfeat(p):
    c1, s1 = np.cos(p[0] / 2), np.sin(p[0] / 2)
    c2, s2 = np.cos(p[1] / 2), np.sin(p[1] / 2)
    C, S = np.cos(p[2]), np.sin(p[2])
    dc1, ds1, dc2, ds2 = -s1 / 2, c1 / 2, -s2 / 2, c2 / 2
    return np.array([
        [-2 * c1 * s1, 0, 0], [c1 * c1 - s1 * s1, 0, 0],
        [0, -2 * c2 * s2, 0], [0, c2 * c2 - s2 * s2, 0],
        [dc1 * c2 * C, c1 * dc2 * C, -c1 * c2 * S],
        [dc1 * c2 * S, c1 * dc2 * S, c1 * c2 * C],
        [dc1 * s2 * C, c1 * ds2 * C, -c1 * s2 * S],
        [dc1 * s2 * S, c1 * ds2 * S, c1 * s2 * C],
        [ds1 * c2 * C, s1 * dc2 * C, -s1 * c2 * S],
        [ds1 * c2 * S, s1 * dc2 * S, s1 * c2 * C],
        [ds1 * s2 * C, s1 * ds2 * C, -s1 * s2 * S],
        [ds1 * s2 * S, s1 * ds2 * S, s1 * s2 * C]])


def buildA0(m1, m2, m3):
    """Ideal 9x12 observation matrix (Bessel first-order coefficients) -- the
    sparse fingerprint the bench-identified A_hat is compared against, and the
    reference used for the sigma_min observability analysis.  The 9 rows are the
    lock-in outputs at {w1, 2w1, w2, 2w2, w3, 2w3, w1+-w2, w1+-w3, w2+-w3}."""
    A = np.zeros((9, 12))
    J11, J21, J12, J22, J13, J23 = (jv(1, m1), jv(2, m1), jv(1, m2),
                                    jv(2, m2), jv(1, m3), jv(2, m3))
    j01, j11, j21 = jv(0, m1 / 2), jv(1, m1 / 2), jv(2, m1 / 2)
    j02, j12, j22 = jv(0, m2 / 2), jv(1, m2 / 2), jv(2, m2 / 2)
    J03 = jv(0, m3)
    A[0, 1] = -J11 / 4; A[0, 8] = -j11 * j02 * J03
    A[1, 0] = J21 / 4;  A[1, 4] = j21 * j02 * J03
    A[2, 3] = -J12 / 4; A[2, 6] = -j01 * j12 * J03
    A[3, 2] = J22 / 4;  A[3, 4] = j01 * j22 * J03
    A[4, 5] = -j01 * j02 * J13; A[5, 4] = j01 * j02 * J23
    A[6, 10] = j11 * j12 * J03; A[7, 9] = j11 * j02 * J13
    A[8, 7] = j01 * j12 * J13
    return A


def dp_intensity(phi, p0=1.0):
    """Single combined-output PD intensity, eq:dpmzm (RF off):
        P = (P0/8)[2 + cos f1 + cos f2] + (P0/2) cos(f1/2) cos(f2/2) cos f3.
    Used for the controller-independent per-axis DC phase truth (DM858E)."""
    f1, f2, f3 = phi
    return (p0 / 8.0) * (2 + np.cos(f1) + np.cos(f2)) \
        + (p0 / 2.0) * np.cos(f1 / 2) * np.cos(f2 / 2) * np.cos(f3)


# --------------------------------------------------------------------------- #
#  linear-regression identification on MEASURED data                          #
#  (generalises make_figs.py:calibrate_dp -- here PH and Z are measured)       #
# --------------------------------------------------------------------------- #
def _design(PH):
    """Stack [Phi(p) | 1] rows -> N x 13 regression design matrix."""
    return np.stack([np.concatenate([feat(p), [1.0]]) for p in np.asarray(PH, float)])


def fit_AB(PH, Z):
    """Ordinary least squares z = A Phi(phi) + b.  Returns (Ah 9x12, bh 9)."""
    F = _design(PH)
    Z = np.asarray(Z, float)
    TH = np.linalg.lstsq(F, Z, rcond=None)[0]      # 13 x 9
    return TH[:12].T, TH[12]


def predict_resid_pct(Ah, bh, PH, Z):
    """Relative model residual ||Z - (A Phi + b)||_F / ||Z||_F  in percent.
    This is the experiment-measurable counterpart of the simulation's
    identification error: small residual == the 9-channel observation really is
    an affine image of the 12-D feature map (Theorem dpmzm)."""
    F = np.stack([feat(p) for p in np.asarray(PH, float)])
    Zh = F @ np.asarray(Ah).T + np.asarray(bh)
    Z = np.asarray(Z, float)
    return float(np.linalg.norm(Z - Zh) / np.linalg.norm(Z) * 100.0)


def calibrate_dp_from_data(PH, Z, holdout_frac=0.3, seed=0):
    """Identify (Ah, bh) by OLS and report fit quality.

    Because the bench has no known ground-truth A, the reported figure of merit
    is the *prediction residual* on a held-out fraction of the quasi-periodic
    scan (generalisation error), alongside the in-sample residual.  A small
    held-out residual is the honest experimental evidence for the affine
    structure -- it is NOT the simulation's ||A_hat - A_true|| (no A_true here).

    Returns dict(Ah, bh, relF_insample_pct, relF_holdout_pct, n_fit, n_test).
    """
    PH = np.asarray(PH, float)
    Z = np.asarray(Z, float)
    N = len(PH)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(N)
    ntest = int(round(holdout_frac * N)) if 0 < holdout_frac < 1 else 0
    test, fit = idx[:ntest], idx[ntest:]
    Ah, bh = fit_AB(PH[fit], Z[fit])
    res_in = predict_resid_pct(Ah, bh, PH[fit], Z[fit])
    res_out = (predict_resid_pct(Ah, bh, PH[test], Z[test])
               if ntest > 0 else res_in)
    # the headline Ah/bh use ALL samples (best estimate for downstream demod)
    Ah_all, bh_all = fit_AB(PH, Z)
    return dict(Ah=Ah_all, bh=bh_all,
                relF_insample_pct=res_in, relF_holdout_pct=res_out,
                n_fit=int(len(fit)), n_test=int(ntest))


def calibrate_dp_joint(bias, Z, vpi0, v0, holdout_frac=0.3, seed=0,
                       vpi_bounds=(2.0, 11.0)):
    """Fit the per-axis Vpi scaling (phi_i = pi*(V - v0_i)/Vpi_i) jointly with the
    affine (A, b), with the phase ORIGIN v0 held FIXED to the physically-anchored
    DC maxima (Theta_i = 0, the reliable argmax of each axis' combined-PD sweep).

    Fixing v0 keeps the identified frame physical -- so the standard QPSK point
    and the lock targets are meaningful -- while the 3 Vpi scalings (which the
    half-angle combined-PD fringe and a dim arm make unreliable to read off a
    single-axis fit) are pinned by the whole 9-channel response.

    The scaling is found by a BOUNDED global search (differential evolution over
    `vpi_bounds`), NOT an unconstrained local descent: a weakly-excited axis
    (e.g. the parent, whose IMD channels sit near the noise floor) would otherwise
    let Vpi drift to a non-physical value (making the axis look frozen/
    unobservable) just to shave the residual via the gauge.  Bounding to the
    physical Vpi range keeps the identified frame honest.

    Returns dict(Ah, bh, vpi, v0, relF_insample_pct, relF_holdout_pct).
    """
    from scipy.optimize import differential_evolution
    bias = np.asarray(bias, float); Z = np.asarray(Z, float); N = len(bias)
    v0 = np.asarray(v0, float)
    rng = np.random.default_rng(seed); idx = rng.permutation(N)
    ntest = int(round(holdout_frac * N)) if 0 < holdout_frac < 1 else 0
    test, fit = idx[:ntest], idx[ntest:]

    def _phase(vpi3, B):
        return np.pi * (B - v0[None, :]) / np.asarray(vpi3)[None, :]

    def _obj(vpi3):
        PH = _phase(vpi3, bias[fit])
        Ah, bh = fit_AB(PH, Z[fit])
        return predict_resid_pct(Ah, bh, PH, Z[fit])

    res = differential_evolution(_obj, bounds=[vpi_bounds] * 3, seed=seed,
                                 maxiter=60, tol=1e-3, polish=True)
    vpi3 = res.x
    Ah, bh = fit_AB(_phase(vpi3, bias), Z)
    r_in = predict_resid_pct(Ah, bh, _phase(vpi3, bias[fit]), Z[fit])
    r_out = (predict_resid_pct(Ah, bh, _phase(vpi3, bias[test]), Z[test])
             if ntest > 0 else r_in)
    return dict(Ah=Ah, bh=bh, vpi=[float(x) for x in vpi3],
                v0=[float(x) for x in v0],
                relF_insample_pct=float(r_in), relF_holdout_pct=float(r_out))


# --------------------------------------------------------------------------- #
#  MAGNITUDE-only (power) identification + demodulation                        #
#  The scope FFT gives per-frequency POWER (no phase), and a free-running       #
#  multi-tone capture has no usable common phase reference anyway -- which also  #
#  matches a real deployment where the lock-in phase is uncontrolled.  The      #
#  squared power is m_k^2 = (A_k.Phi)^2 = <A_k A_k^T, Phi Phi^T>, LINEAR in the  #
#  quadratic features Phi_i Phi_j, so A_k A_k^T is identified by ordinary least  #
#  squares and A_k recovered by a rank-1 (PSD) factorisation (PhaseLift-style).  #
#  Observability (sigma_min) is unchanged: the |.| only flips row signs, which   #
#  does not change singular values.                                             #
# --------------------------------------------------------------------------- #
def _quad_feat(phi):
    """[ Phi_i*Phi_j (i<=j, 78) | Phi_i (12, absorbs any AC offset) | 1 ]."""
    F = feat(phi)
    q = [F[i] * F[j] for i in range(12) for j in range(i, 12)]
    return np.array(q + list(F) + [1.0])


def _unvech12(w):
    """Inverse of the upper-triangle stack -> symmetric 12x12 (off-diag halved)."""
    M = np.zeros((12, 12)); c = 0
    for i in range(12):
        for j in range(i, 12):
            M[i, j] = M[j, i] = w[c] if i == j else w[c] / 2.0
            c += 1
    return M


def calibrate_dp_mag(PH, MAG, holdout_frac=0.3, seed=0):
    """Identify A (9x12) from per-channel POWER magnitudes MAG (N x 9) measured
    over a scan with known phases PH (N x 3).  Per channel: OLS for the 91-vector
    (quadratic feats + linear + const), rebuild the symmetric M_k, take its
    leading PSD eigenpair as A_k (sign by convention).  Returns the held-out
    magnitude-prediction residual (the bench figure of merit)."""
    from scipy.optimize import least_squares
    PH = np.asarray(PH, float); MAG = np.asarray(MAG, float); N = len(PH)
    Psi = np.stack([_quad_feat(p) for p in PH])           # N x 91
    P2 = MAG ** 2                                          # N x 9 (power)
    rng = np.random.default_rng(seed); idx = rng.permutation(N)
    nt = int(round(holdout_frac * N)) if 0 < holdout_frac < 1 else 0
    test, fitn = idx[:nt], idx[nt:]
    # PhaseLift seed: OLS for A_k A_k^T, then refine A_k DIRECTLY (12 params) by
    # nonlinear least squares on the power residual (the lifted 78-D problem is
    # rank-deficient, so the seed is only a starting point).
    W = np.linalg.lstsq(Psi[fitn], P2[fitn], rcond=None)[0]   # 91 x 9
    Fmat = np.stack([feat(p) for p in PH[fitn]])             # nfit x 12
    Ah = np.zeros((9, 12))
    for k in range(9):
        ev, evec = np.linalg.eigh(_unvech12(W[:78, k]))
        a0 = np.sqrt(max(ev[-1], 0.0)) * evec[:, -1]
        tgt = P2[fitn, k]

        def _r(a):
            g = Fmat @ a; return g * g - tgt

        def _j(a):
            g = Fmat @ a; return 2.0 * g[:, None] * Fmat
        a = least_squares(_r, a0, jac=_j, max_nfev=300).x
        if a[int(np.argmax(np.abs(a)))] < 0:
            a = -a
        Ah[k] = a

    def _predmag(P):
        return np.stack([np.abs(Ah @ feat(p)) for p in P])
    res_out = (float(np.linalg.norm(_predmag(PH[test]) - MAG[test]) /
                     np.linalg.norm(MAG[test]) * 100) if nt > 0 else 0.0)
    res_in = float(np.linalg.norm(_predmag(PH[fitn]) - MAG[fitn]) /
                   np.linalg.norm(MAG[fitn]) * 100)
    return dict(Ah=Ah, relF_insample_pct=res_in, relF_holdout_pct=res_out)


def _mag_phaselift_resid(PH, MAG):
    """Fast PhaseLift-only identification residual (no per-channel refine) -- used
    as the inner objective of the Vpi search."""
    Psi = np.stack([_quad_feat(p) for p in PH])
    W = np.linalg.lstsq(Psi, MAG ** 2, rcond=None)[0]
    Ah = np.zeros((9, 12))
    for k in range(9):
        ev, evec = np.linalg.eigh(_unvech12(W[:78, k]))
        Ah[k] = np.sqrt(max(ev[-1], 0.0)) * evec[:, -1]
    pred = np.stack([np.abs(Ah @ feat(p)) for p in PH])
    return float(np.linalg.norm(pred - MAG) / np.linalg.norm(MAG) * 100)


def calibrate_dp_mag_joint(bias, MAG, vpi0, v0, holdout_frac=0.3, seed=0,
                           vpi_bounds=(3.0, 11.0)):
    """Magnitude-only identification WITH a per-axis Vpi search (v0 fixed to the
    physical DC maxima).  The Vpi objective is the FULL calibrate_dp_mag in-sample
    residual evaluated on a COARSE grid (the lifted PhaseLift residual is
    ill-conditioned and mis-picks Vpi), then the headline (Ah, holdout) come from
    the full fit at the best Vpi.  Returns dict(Ah, vpi, v0, relF_*_pct)."""
    bias = np.asarray(bias, float); MAG = np.asarray(MAG, float)
    v0 = np.asarray(v0, float)

    def _phase(vpi3):
        return np.pi * (bias - v0[None, :]) / np.asarray(vpi3)[None, :]

    def _full_resid(vpi3):
        Ah, _ = fit_AB_mag(_phase(vpi3), MAG)
        pred = np.stack([np.abs(Ah @ feat(p)) for p in _phase(vpi3)])
        return float(np.linalg.norm(pred - MAG) / np.linalg.norm(MAG) * 100)

    lo, hi = vpi_bounds
    grid = np.linspace(lo, hi, 7)
    best_vpi = None; best_r = np.inf
    for a in grid:                       # isotropic coarse pass (axes share scale)
        r = _full_resid([a, a, a])
        if r < best_r:
            best_r = r; best_vpi = np.array([a, a, a])
    for i in range(3):                   # per-axis refine around the best
        for a in np.linspace(max(lo, best_vpi[i] - 1.5), min(hi, best_vpi[i] + 1.5), 7):
            cand = best_vpi.copy(); cand[i] = a
            r = _full_resid(cand)
            if r < best_r:
                best_r = r; best_vpi = cand
    cal = calibrate_dp_mag(_phase(best_vpi), MAG, holdout_frac=holdout_frac, seed=seed)
    cal["vpi"] = [float(x) for x in best_vpi]; cal["v0"] = [float(x) for x in v0]
    return cal


def fit_AB_mag(PH, MAG):
    """Per-channel direct 12-param A_k fit on the power residual (no offset).
    Lighter than calibrate_dp_mag (no holdout/refit) for the Vpi search."""
    from scipy.optimize import least_squares
    PH = np.asarray(PH, float); MAG = np.asarray(MAG, float)
    Psi = np.stack([_quad_feat(p) for p in PH])
    W = np.linalg.lstsq(Psi, MAG ** 2, rcond=None)[0]
    Fmat = np.stack([feat(p) for p in PH])
    Ah = np.zeros((9, 12))
    for k in range(9):
        ev, evec = np.linalg.eigh(_unvech12(W[:78, k]))
        a0 = np.sqrt(max(ev[-1], 0.0)) * evec[:, -1]
        tgt = MAG[:, k] ** 2
        Ah[k] = least_squares(lambda a: (Fmat @ a) ** 2 - tgt, a0,
                              jac=lambda a: 2.0 * (Fmat @ a)[:, None] * Fmat,
                              max_nfev=200).x
    return Ah, None


def gn_demod_mag(mag, est, Ah, iters=6):
    """Warm-start demod from POWER magnitudes only.  Each iteration ASSIGNS the
    sign of every channel from the current model (z_k = sign(A_k.Phi(est))*m_k),
    turning the magnitudes into a pseudo-signed observation, then takes a stable
    signed Gauss-Newton step.  Far more robust than minimising the (multi-modal)
    squared-power residual -- the sign assignment is correct once warm-started
    near the target, which is exactly the closed-loop regime."""
    Ah = np.asarray(Ah, float); est = np.array(est, float)
    mag = np.asarray(mag, float)
    # weight by relative magnitude: a channel near a zero-crossing reads the FFT
    # noise floor (not 0), so its sign and value are unreliable -- down-weight it.
    w = mag / (mag.max() + 1e-12)
    for _ in range(iters):
        g = Ah @ feat(est)                               # signed model values
        z = np.sign(g) * mag                             # sign-assigned observation
        J = Ah @ dfeat(est)
        r = z - g                                        # signed residual (b=0, AC)
        Jw = J * w[:, None]
        d = np.linalg.solve(Jw.T @ Jw + 1e-9 * np.eye(3), Jw.T @ (w * r))
        n = np.linalg.norm(d)
        est = est + d * (0.5 / n if n > 0.5 else 1.0)
    return est


def relF(Ah, A0):
    """Relative Frobenius distance to the ideal sparse fingerprint A0 (percent),
    after the best diagonal +-1 column-sign gauge alignment.  Reported as a
    qualitative structure-match, not the headline identification metric."""
    Ah = np.asarray(Ah, float); A0 = np.asarray(A0, float)
    return float(np.linalg.norm(Ah - A0) / np.linalg.norm(A0) * 100.0)


# --------------------------------------------------------------------------- #
#  warm-start damped Gauss-Newton demodulation  (make_figs.py:231-238)         #
# --------------------------------------------------------------------------- #
def gn_demod(z, est, Ah, bh, iters=4):
    """One demod call: refine the phase estimate `est` (3-vector) from one
    9-channel observation z using the identified (Ah, bh).  Levenberg-style
    damping + 0.5-rad step limiting, identical to the simulation."""
    Ah = np.asarray(Ah, float); bh = np.asarray(bh, float)
    est = np.array(est, float)
    z = np.asarray(z, float)
    for _ in range(iters):
        J = Ah @ dfeat(est)
        r = z - Ah @ feat(est) - bh
        d = np.linalg.solve(J.T @ J + 1e-6 * np.eye(3), J.T @ r)
        n = np.linalg.norm(d)
        est = est + d * (0.5 / n if n > 0.5 else 1.0)
    return est


def sigmin(Am, p, rows):
    """Smallest singular value of the observation Jacobian J = (A dPhi)[rows] at
    bias p -- the local observability margin (make_figs.py:239-241)."""
    J = (np.asarray(Am, float) @ dfeat(p))[rows]
    return float(np.linalg.svd(J, compute_uv=False)[-1])
