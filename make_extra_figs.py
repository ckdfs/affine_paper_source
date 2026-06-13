#!/usr/bin/env python3
"""Extra result figures for the paper:
  fig_sweep  - static error vs target phase: closed-form curves for the
               conventional schemes (Table II / eqs. staticAM) against the
               affine loop's flat rms; plus the phase-resolved noise floor.
  fig_mcdp   - DPMZM Monte-Carlo static-error distributions over mismatch
               realizations (GN affine vs three independent loops).
  fig_gauge  - gauge fixing: DC-regression vs argmin fiducial, bias
               distribution at N=360 and median bias vs N (1/sqrt(N) law).
Machinery ported 1:1 from make_figs.py (validated)."""
import numpy as np
from scipy.special import jv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
rng = np.random.default_rng(20260613)
os.makedirs('figs', exist_ok=True)
plt.rcParams.update({
    'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8,
    'legend.fontsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
    'lines.linewidth': 1.0, 'figure.dpi': 150,
    'font.family': 'serif', 'mathtext.fontset': 'cm'})
GRN, RED, BLU, GLD, INK = '#1F6E52', '#BC4B2A', '#2E5FA3', '#A8801F', '#1E2A24'
CW = 3.45

# ---------------- MZM machinery (ported from make_figs.py) ----------------
P1 = dict(m=1.2, RP=1, gX=1.18, gY=0.88, delta=np.deg2rad(10), eps=0.10,
          bx=0.030, by=-0.022, sigma=0.005)
def measure_mzm(phi, p, noisy=True):
    k1 = p['RP']*jv(1, p['m']); k2 = p['RP']*jv(2, p['m'])
    X = p['bx'] + p['gX']*k2*np.cos(phi) + p['eps']*k1*np.sin(phi)
    Y = p['by'] - p['gY']*k1*(np.sin(phi)*np.cos(p['delta'])+np.cos(phi)*np.sin(p['delta']))
    if noisy:
        X = X + p['sigma']*rng.standard_normal(np.shape(phi))
        Y = Y + p['sigma']*rng.standard_normal(np.shape(phi))
    return X, Y
def measure_dc(phi, p):
    return 0.5*p['RP']*(1+jv(0,p['m'])*np.cos(phi)) + 0.6*p['sigma']*rng.standard_normal(np.shape(phi))
def calibrate_mzm(p, N=360, gauge='regression'):
    phis = np.arange(N)/N*2*np.pi
    X, Y = measure_mzm(phis, p); dc = measure_dc(phis, p)
    mx, my = X.mean(), Y.mean(); sc = np.hypot(X-mx, Y-my).mean()
    x, y = (X-mx)/sc, (Y-my)/sc
    D = np.stack([x*x, x*y, y*y, x, y], 1)
    th = np.linalg.solve(D.T@D, D.T@np.ones(N))
    a,b,c,d,e = th; det = 4*a*c-b*b
    cx = (b*e-2*c*d)/det; cy = (b*d-2*a*e)/det
    kq = 1-(a*cx*cx+b*cx*cy+c*cy*cy+d*cx+e*cy)
    M = np.array([[a, b/2],[b/2, c]])/kq
    c0 = np.array([mx+sc*cx, my+sc*cy]); M = M/sc**2
    w, V = np.linalg.eigh(M); B = V@np.diag(np.sqrt(w))@V.T
    us = (B@np.stack([X-c0[0], Y-c0[1]])).T
    cr = np.sum(us[:-1,0]*us[1:,1]-us[:-1,1]*us[1:,0])
    if cr < 0: B = np.diag([1,-1])@B; us[:,1] *= -1
    th_i = np.arctan2(us[:,1], us[:,0])
    if gauge == 'regression':
        Dg = np.stack([np.ones(N), np.cos(th_i), np.sin(th_i)],1)
        cf = np.linalg.solve(Dg.T@Dg, Dg.T@dc)
        sgn = 1 if jv(0,p['m'])>=0 else -1
        phc = np.arctan2(sgn*cf[2], sgn*cf[1])
    else:  # pathological argmin fiducial: DC minimum sits at phi = phc + pi
        phc = np.angle(np.exp(1j*(th_i[np.argmin(dc)] - np.pi)))
    dphi = -phc
    R = np.array([[np.cos(dphi),-np.sin(dphi)],[np.sin(dphi),np.cos(dphi)]])
    return {'c0':c0, 'B':R@B}
def demod(cal, X, Y):
    u = cal['B']@np.array([X-cal['c0'][0], Y-cal['c0'][1]])
    return np.arctan2(u[1], u[0])

# true affine parameters implied by P1 (for the closed-form curves)
k1 = jv(1, P1['m']); k2 = jv(2, P1['m'])
A11 =  P1['gX']*k2;                 A12 = P1['eps']*k1
A21 = -P1['gY']*k1*np.sin(P1['delta']); A22 = -P1['gY']*k1*np.cos(P1['delta'])
bX, bY = P1['bx'], P1['by']
Atrue2 = np.array([[A11, A12],[A21, A22]])

# =================== Fig E1: error vs target phase ===================
# (a) closed-form static error of the conventional arbitrary-point schemes
#     vs the affine loop's measured closed-loop rms
ph = np.linspace(0.02, 2*np.pi-0.02, 600)
# amplitude matching (eq. staticAM), nominal slope k1
dAM = -(A21*np.cos(ph) + (A22+k1)*np.sin(ph) + bY) / (A22*np.cos(ph) - A21*np.sin(ph))
dAM = np.minimum(np.abs(dAM), np.pi)*1e3
# harmonic ratio: root of  c(phi) = X(phi)*k1*sin(ph*) + Y(phi)*k2*cos(ph*) = 0
# nearest to the target (charitable branch choice), no noise
def ratio_static(pstar):
    grid = np.linspace(0, 2*np.pi, 4001)
    X, Y = measure_mzm(grid, P1, noisy=False)
    c = X*k1*np.sin(pstar) + Y*k2*np.cos(pstar)
    s = np.where(np.diff(np.sign(c)) != 0)[0]
    roots = []
    for i in s:
        lo, hi = grid[i], grid[i+1]
        for _ in range(40):
            mid = 0.5*(lo+hi)
            Xm, Ym = measure_mzm(mid, P1, noisy=False)
            cm = Xm*k1*np.sin(pstar) + Ym*k2*np.cos(pstar)
            Xl, Yl = measure_mzm(lo, P1, noisy=False)
            cl = Xl*k1*np.sin(pstar) + Yl*k2*np.cos(pstar)
            if np.sign(cm) == np.sign(cl): lo = mid
            else: hi = mid
        roots.append(0.5*(lo+hi))
    if not roots: return np.pi
    err = [abs(np.angle(np.exp(1j*(r-pstar)))) for r in roots]
    return min(err)
ph_r = np.linspace(0.02, 2*np.pi-0.02, 240)
dRT = np.array([ratio_static(ps) for ps in ph_r])*1e3
# affine closed loop at 16 targets (drift + noise, same generator as fig_mzmloop)
def affine_loop_rms(p, phi_ref, cal, n=700, G=0.18):
    phi = phi_ref + 0.3; es = []
    for t in range(n):
        d = 0.004*rng.standard_normal() + 0.0022*np.sin(t*0.045)
        phi += d
        X, Y = measure_mzm(phi, p)
        e = np.angle(np.exp(1j*(demod(cal, X, Y) - phi_ref)))
        phi -= G*e
        es.append(np.angle(np.exp(1j*(phi - phi_ref))))
    return np.sqrt(np.mean((np.array(es[200:])*1e3)**2))
cal0 = calibrate_mzm(P1)
tgts16 = np.linspace(0.2, 2*np.pi-0.2, 16)
rms16 = np.array([affine_loop_rms(P1, t, cal0) for t in tgts16])
print('[sweep] affine closed-loop rms over 16 targets: '
      f'min={rms16.min():.1f} med={np.median(rms16):.1f} max={rms16.max():.1f} mrad')
# (b) phase-resolved demodulation noise floor: theory vs Monte Carlo
Mq = np.linalg.inv(Atrue2@Atrue2.T)          # ellipse matrix (AA^T)^-1, for B
Gq = np.linalg.inv(Atrue2.T@Atrue2)          # variance Gram (A^T A)^-1, eq. (var)
tv = lambda f: np.array([-np.sin(f), np.cos(f)])
sig_th = np.array([np.sqrt(tv(f)@Gq@tv(f)) for f in ph])*P1['sigma']*1e3
smin = np.linalg.svd(Atrue2, compute_uv=False)[-1]
# validate eq. (var) with the true-parameter demodulator (calibration error is
# a separate, second-order effect; see fig_gauge)
wq, Vq = np.linalg.eigh(Mq); Btrue = Vq@np.diag(np.sqrt(wq))@Vq.T
ctrue = np.array([bX, bY])
def demod_true(X, Y):
    u = Btrue@np.array([X-ctrue[0], Y-ctrue[1]])
    return np.arctan2(u[1], u[0])
ph24 = np.linspace(0.15, 2*np.pi-0.15, 24)
sig_mc = []
for f in ph24:
    ests = []
    for _ in range(300):
        X, Y = measure_mzm(f, P1)
        ests.append(demod_true(X, Y))
    ests = np.unwrap(np.array(ests))
    sig_mc.append(np.std(ests)*1e3)
# panel tags inside the top-left corner; legends above the axes so they never
# cover the curves
fig, axs = plt.subplots(1, 2, figsize=(2*CW, 2.0))
ax = axs[0]
ax.semilogy(ph, np.maximum(dAM, 1e-1), color=RED, label='amplitude matching')
ax.semilogy(ph_r, np.maximum(dRT, 1e-1), color=GLD, ls='-.', label='harmonic ratio')
ax.semilogy(tgts16, rms16, 'o', color=GRN, ms=3.5, label='affine loop rms')
ax.axhline(np.median(rms16), color=GRN, lw=0.7, ls=':')
ax.set_xlabel('target phase $\\varphi^*$ (rad)')
ax.set_ylabel('$|$static error$|$ (mrad)')
ax.set_xticks([0, np.pi/2, np.pi, 3*np.pi/2, 2*np.pi])
ax.set_xticklabels(['0', '$\\pi/2$', '$\\pi$', '$3\\pi/2$', '$2\\pi$'])
ax.set_ylim(0.5, 4000)
ax.text(0.02, 0.93, '(a)', transform=ax.transAxes, fontsize=8, weight='bold')
ax.legend(loc='lower center', bbox_to_anchor=(0.5, 0.99), ncol=3, frameon=False,
          borderpad=0.1, handlelength=1.2, columnspacing=0.8, fontsize=6)
ax = axs[1]
ax.plot(ph, sig_th, color=INK, lw=0.9,
        label='$\\sigma\\sqrt{\\mathbf{t}^{\\mathsf{T}}(A^{\\mathsf{T}}A)^{-1}\\mathbf{t}}$')
ax.plot(ph24, sig_mc, 'o', color=GRN, ms=3.5, label='Monte Carlo')
ax.axhline(P1['sigma']/smin*1e3, color=BLU, lw=0.8, ls='--',
           label='$\\sigma/\\sigma_{\\min}(A)$')
ax.set_xlabel('bias phase $\\varphi_b$ (rad)')
ax.set_ylabel('$\\sigma_{\\hat\\varphi}$ (mrad)')
ax.set_xticks([0, np.pi/2, np.pi, 3*np.pi/2, 2*np.pi])
ax.set_xticklabels(['0', '$\\pi/2$', '$\\pi$', '$3\\pi/2$', '$2\\pi$'])
ax.set_ylim(0, 1.05*P1['sigma']/smin*1e3*1.15)
ax.text(0.02, 0.93, '(b)', transform=ax.transAxes, fontsize=8, weight='bold')
ax.legend(loc='lower center', bbox_to_anchor=(0.5, 0.99), ncol=3, frameon=False,
          borderpad=0.1, handlelength=1.2, columnspacing=0.8, fontsize=6)
plt.tight_layout(); plt.savefig('figs/fig_sweep.pdf'); plt.close()

# =================== DPMZM machinery (ported) ===================
def feat(p):
    c1,s1=np.cos(p[0]/2),np.sin(p[0]/2); c2,s2=np.cos(p[1]/2),np.sin(p[1]/2)
    C,S=np.cos(p[2]),np.sin(p[2])
    return np.array([c1*c1-s1*s1,2*c1*s1,c2*c2-s2*s2,2*c2*s2,
        c1*c2*C,c1*c2*S,c1*s2*C,c1*s2*S,s1*c2*C,s1*c2*S,s1*s2*C,s1*s2*S])
def dfeat(p):
    c1,s1=np.cos(p[0]/2),np.sin(p[0]/2); c2,s2=np.cos(p[1]/2),np.sin(p[1]/2)
    C,S=np.cos(p[2]),np.sin(p[2])
    dc1,ds1,dc2,ds2=-s1/2,c1/2,-s2/2,c2/2
    return np.array([
        [-2*c1*s1,0,0],[c1*c1-s1*s1,0,0],[0,-2*c2*s2,0],[0,c2*c2-s2*s2,0],
        [dc1*c2*C,c1*dc2*C,-c1*c2*S],[dc1*c2*S,c1*dc2*S,c1*c2*C],
        [dc1*s2*C,c1*ds2*C,-c1*s2*S],[dc1*s2*S,c1*ds2*S,c1*s2*C],
        [ds1*c2*C,s1*dc2*C,-s1*c2*S],[ds1*c2*S,s1*dc2*S,s1*c2*C],
        [ds1*s2*C,s1*ds2*C,-s1*s2*S],[ds1*s2*S,s1*ds2*S,s1*s2*C]])
def buildA0(m1,m2,m3):
    A=np.zeros((9,12))
    J11,J21,J12,J22=jv(1,m1),jv(2,m1),jv(1,m2),jv(2,m2)
    J13,J23=jv(1,m3),jv(2,m3)
    j01,j11,j21=jv(0,m1/2),jv(1,m1/2),jv(2,m1/2)
    j02,j12,j22=jv(0,m2/2),jv(1,m2/2),jv(2,m2/2); J03=jv(0,m3)
    A[0,1]=-J11/4; A[0,8]=-j11*j02*J03
    A[1,0]= J21/4; A[1,4]= j21*j02*J03
    A[2,3]=-J12/4; A[2,6]=-j01*j12*J03
    A[3,2]= J22/4; A[3,4]= j01*j22*J03
    A[4,5]=-j01*j02*J13; A[5,4]= j01*j02*J23
    A[6,10]= j11*j12*J03; A[7,9]= j11*j02*J13; A[8,7]= j01*j12*J13
    return A
A0=buildA0(1.2,1.2,1.2)
SC=0.12*np.linalg.norm(A0)/np.sqrt(108)
SIG=0.002

# ============ Fig E2: DPMZM Monte-Carlo static-error distributions ============
def mc_realization(nstep=1600, G=0.16):
    Atr = A0 + SC*rng.standard_normal((9,12))
    btr = 0.5*0.02*rng.standard_normal(9)
    def meas(p, noisy=True):
        z = Atr@feat(p) + btr
        return z + (SIG*rng.standard_normal(9) if noisy else 0)
    # calibration (quasi-periodic trajectory regression)
    D = np.array([0.04241,0.05317,0.06789]); N=3000
    PH = np.outer(np.arange(N), D)
    F = np.stack([np.concatenate([feat(p),[1]]) for p in PH])
    Z = np.stack([meas(p) for p in PH])
    TH = np.linalg.solve(F.T@F, F.T@Z)
    Ah, bh = TH[:12].T, TH[12]
    def gn(z, est, iters=2):
        est = np.array(est, float)
        for _ in range(iters):
            J = Ah@dfeat(est); r = z - Ah@feat(est) - bh
            d = np.linalg.solve(J.T@J + 1e-6*np.eye(3), J.T@r)
            n = np.linalg.norm(d); est = est + d*(0.5/n if n > 0.5 else 1)
        return est
    out = {}
    for key, tgt in [('arb', np.array([2.0,2.6,1.1])),
                     ('std', np.array([np.pi,np.pi,np.pi/2]))]:
        Ftg = feat(tgt); ref = A0[[0,2,6]]@Ftg
        Jd = A0@dfeat(tgt); slopes = np.array([Jd[0,0],Jd[2,1],Jd[6,2]])
        fl = np.array([abs(A0[0,1]),abs(A0[2,3]),abs(A0[6,10])])
        slopes = np.sign(np.where(slopes==0,1,slopes))*np.maximum(np.abs(slopes),0.15*fl)
        phiA = tgt+0.25; phiT = tgt+0.25; est = tgt.astype(float).copy()
        eA = []; eT = []
        for t in range(nstep):
            d = 0.0028*rng.standard_normal(3)+0.0016*np.sin(t*0.045+np.arange(3)*2.1)
            phiA = phiA + d; phiT = phiT + d
            est = gn(meas(phiA), est, 2)
            phiA = phiA - G*(est-tgt); eA.append(1e3*np.linalg.norm(phiA-tgt))
            z2 = meas(phiT)
            e = np.clip((z2[[0,2,6]]-ref)/slopes, -1, 1); phiT = phiT - G*e
            eT.append(1e3*np.linalg.norm(phiT-tgt))
        out[('GN',key)] = np.sqrt(np.mean(np.array(eA[-400:])**2))
        out[('TL',key)] = np.sqrt(np.mean(np.minimum(np.array(eT[-400:]),4000)**2))
    return out
NREAL = 30
runs = [mc_realization() for _ in range(NREAL)]
groups = [('GN','arb'), ('GN','std'), ('TL','arb'), ('TL','std')]
labels = ['GN\narb.', 'GN\nstd.', '3-loop\narb.', '3-loop\nstd.']
data = [np.array([r[g] for r in runs]) for g in groups]
for g, d in zip(groups, data):
    conv = d[d <= 2500]
    extra = (f'  conv_median={np.median(conv):.0f} conv_IQR=[{np.percentile(conv,25):.0f},'
             f'{np.percentile(conv,75):.0f}]') if len(conv) else ''
    print(f'[mcdp] {g}: median={np.median(d):.0f}  IQR=[{np.percentile(d,25):.0f},'
          f'{np.percentile(d,75):.0f}] mrad  diverged(>2500)={np.sum(d>2500)}{extra}')
fig, ax = plt.subplots(figsize=(CW, 2.1))
CAP = 3000.0
for i, (d, col) in enumerate(zip(data, [GRN, GRN, RED, RED])):
    xj = i + 0.16*rng.standard_normal(len(d))
    dc_ = np.minimum(d, CAP)
    ax.semilogy(xj[d <= 2500], dc_[d <= 2500], 'o', color=col, ms=2.8, alpha=0.7)
    if np.any(d > 2500):
        ax.semilogy(xj[d > 2500], dc_[d > 2500], '^', color=col, ms=4.0,
                    mfc='none', mew=1.0)
    ax.hlines(np.median(d), i-0.28, i+0.28, color=INK, lw=1.3)
ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=7)
ax.set_ylabel('steady-state rms $\\|e\\|$ (mrad)')
ax.set_ylim(5, 5000)
ax.text(0.02, 0.965, '$\\triangle$: diverged (capped)', transform=ax.transAxes,
        fontsize=6, va='top')
plt.tight_layout(); plt.savefig('figs/fig_mcdp.pdf'); plt.close()

# ============ Fig E3: gauge fixing, regression vs argmin ============
def gauge_bias(p, N, gauge):
    cal = calibrate_mzm(p, N=N, gauge=gauge)
    f = rng.uniform(0, 2*np.pi)
    X, Y = measure_mzm(f, p, noisy=False)
    return abs(np.angle(np.exp(1j*(demod(cal, X, Y) - f))))*1e3
R0 = 60
bias_reg = np.array([gauge_bias(P1, 360, 'regression') for _ in range(R0)])
bias_arg = np.array([gauge_bias(P1, 360, 'argmin') for _ in range(R0)])
print(f'[gauge] N=360: regression median={np.median(bias_reg):.2f} mrad, '
      f'argmin median={np.median(bias_arg):.2f} mrad')
Ns = np.array([90, 180, 360, 720, 1440])
med_reg, med_arg = [], []
for N in Ns:
    med_reg.append(np.median([gauge_bias(P1, N, 'regression') for _ in range(40)]))
    med_arg.append(np.median([gauge_bias(P1, N, 'argmin') for _ in range(40)]))
med_reg = np.array(med_reg); med_arg = np.array(med_arg)
print('[gauge] medians vs N:', list(zip(Ns, np.round(med_reg,2), np.round(med_arg,1))))
fig, axs = plt.subplots(1, 2, figsize=(2*CW, 1.95))
ax = axs[0]
for i, (d, col, lab) in enumerate([(bias_reg, GRN, 'DC regression (proposed)'),
                                   (bias_arg, RED, 'argmin fiducial')]):
    xj = i + 0.13*rng.standard_normal(len(d))
    ax.semilogy(xj, np.maximum(d, 0.05), 'o', color=col, ms=2.8, alpha=0.7)
    ax.hlines(np.median(d), i-0.25, i+0.25, color=INK, lw=1.3)
ax.set_xticks([0,1]); ax.set_xticklabels(['DC regression\n(proposed)','argmin\nfiducial'],fontsize=7)
ax.set_ylabel('$|$demod bias$|$ (mrad)'); ax.set_xlim(-0.6,1.6)
ax.set_title('(a) calibration-induced bias, $N{=}360$', fontsize=7.5)
ax = axs[1]
ax.loglog(Ns, med_reg, 'o-', color=GRN, ms=3.5, label='DC regression')
ax.loglog(Ns, med_arg, 's-', color=RED, ms=3.5, label='argmin fiducial')
ax.loglog(Ns, med_reg[2]*np.sqrt(360/Ns), 'k:', lw=0.8, label='$N^{-1/2}$')
ax.set_xlabel('sweep samples $N$'); ax.set_ylabel('median bias (mrad)')
ax.set_xticks(Ns); ax.set_xticklabels([str(n) for n in Ns])
ax.set_title('(b) gauge variance vs $N$', fontsize=7.5)
ax.legend(borderpad=0.25, handlelength=1.4, fontsize=6)
plt.tight_layout(); plt.savefig('figs/fig_gauge.pdf'); plt.close()
print('extra figures done:', sorted(f for f in os.listdir('figs') if f.startswith('fig_')))
