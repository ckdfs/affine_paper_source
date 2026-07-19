#!/usr/bin/env python3
"""Algorithm-level figures: supervisory flowchart, acquisition transients,
setpoint stepping, residual-triggered recalibration. Math identical to
make_figs.py (validated)."""
import glob
import numpy as np
from scipy.special import jv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Polygon
import os
rng = np.random.default_rng(20260612)
os.makedirs('figs', exist_ok=True)


def _configure_fonts():
    """CJK-capable serif stack (ported from make_exp_figs.py) so any Chinese
    text in these figures renders correctly instead of as tofu boxes."""
    cands = []
    env = os.environ.get('PAPER_CJK_FONT')
    if env:
        cands.append(env)
    cands += glob.glob(
        '/usr/local/texlive/*/texmf-dist/fonts/opentype/public/fandol/'
        'FandolSong-Regular.otf')
    cands += [
        '/System/Library/Fonts/Supplemental/Songti.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        os.path.expanduser('~/Library/Fonts/msyh.ttc'),
    ]
    cjk_name = None
    for p in cands:
        if p and os.path.exists(p):
            font_manager.fontManager.addfont(p)
            cjk_name = font_manager.FontProperties(fname=p).get_name()
            break
    serif = []
    if cjk_name:
        serif.append(cjk_name)
    serif += ['TeX Gyre Termes', 'Times New Roman', 'DejaVu Serif']
    plt.rcParams.update({
        'font.size': 8, 'axes.labelsize': 8, 'legend.fontsize': 7,
        'xtick.labelsize': 7, 'ytick.labelsize': 7, 'lines.linewidth': 1.0,
        'figure.dpi': 150, 'font.family': 'serif', 'font.serif': serif,
        'mathtext.fontset': 'cm', 'axes.unicode_minus': False})


_configure_fonts()
# log-tick labels are wrapped in \mathdefault, whose minus sign is looked up in
# the first serif font (FandolSong has no U+2212 -> tofu); route them through
# \mathrm so the CM math fonts supply the glyph. Formatting only, no data effect.
import matplotlib.ticker as _mticker
_lfsn_call = _mticker.LogFormatterSciNotation.__call__
def _lfsn_fix(self, x, pos=None):
    return _lfsn_call(self, x, pos).replace(r'\mathdefault', r'\mathrm')
_mticker.LogFormatterSciNotation.__call__ = _lfsn_fix
GRN, RED, BLU, GLD, INK = '#1F6E52', '#BC4B2A', '#2E5FA3', '#A8801F', '#1E2A24'
CW = 3.45

# ---------- shared MZM machinery (ported, validated) ----------
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
def calibrate_mzm(p, N=360):
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
    Dg = np.stack([np.ones(N), np.cos(th_i), np.sin(th_i)],1)
    cf = np.linalg.solve(Dg.T@Dg, Dg.T@dc)
    sgn = 1 if jv(0,p['m'])>=0 else -1
    phc = np.arctan2(sgn*cf[2], sgn*cf[1]); dphi = -phc
    R = np.array([[np.cos(dphi),-np.sin(dphi)],[np.sin(dphi),np.cos(dphi)]])
    return {'c0':c0, 'B':R@B}
def demod(cal, X, Y):
    u = cal['B']@np.array([X-cal['c0'][0], Y-cal['c0'][1]])
    return np.arctan2(u[1], u[0]), np.hypot(u[0], u[1])

# ---------- DPMZM machinery (ported, validated) ----------
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
    J11,J21,J12,J22,J13,J23=jv(1,m1),jv(2,m1),jv(1,m2),jv(2,m2),jv(1,m3),jv(2,m3)
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
sc=0.12*np.linalg.norm(A0)/np.sqrt(108)
Atrue=A0+sc*rng.standard_normal((9,12)); btrue=0.5*0.02*rng.standard_normal(9)
SIG=0.002
def measure_dp(p,noisy=True):
    z=Atrue@feat(p)+btrue
    return z+(SIG*rng.standard_normal(9) if noisy else 0)
def calibrate_dp(N=3000):
    D=np.array([0.04241,0.05317,0.06789]); PH=np.outer(np.arange(N),D)
    F=np.stack([np.concatenate([feat(p),[1]]) for p in PH])
    Z=np.stack([measure_dp(p) for p in PH])
    TH=np.linalg.solve(F.T@F,F.T@Z)
    return TH[:12].T, TH[12]
Ah,bh=calibrate_dp()
def gn(z,est,iters=2):
    est=np.array(est,float)
    for _ in range(iters):
        J=Ah@dfeat(est); r=z-Ah@feat(est)-bh
        d=np.linalg.solve(J.T@J+1e-6*np.eye(3),J.T@r)
        n=np.linalg.norm(d); est=est+d*(0.5/n if n>0.5 else 1)
    return est

# ============ Fig F1: supervisory flowchart ============
# exact-geometry boxes: boxstyle 'round,pad=0' makes the drawn rect equal the
# nominal rect (a nonzero pad*mutation_scale halo previously made neighbouring
# boxes overlap and arrows pierce the borders); all arrows use shrinkA=B=0 so
# shafts and heads land exactly on box edges with no gaps
def fbox(ax,x,y,w,h,t,fs=7,fc='#FBFDFB',ec=INK,lw=0.9,rs=0.16):
    ax.add_patch(FancyBboxPatch((x,y),w,h,
                 boxstyle='round,pad=0,rounding_size=%.2f'%rs,
                 fc=fc,ec=ec,lw=lw,mutation_scale=1,zorder=2))
    ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=fs,zorder=4,
            linespacing=1.25)
def fdiamond(ax,cx,cy,w,h,t,fs=6.2,fc='#FBF3E3',ec=INK,lw=0.9):
    """Decision node with exact vertices for clean branch attachment."""
    ax.add_patch(Polygon([(cx,cy+h/2),(cx+w/2,cy),
                          (cx,cy-h/2),(cx-w/2,cy)],
                         closed=True,fc=fc,ec=ec,lw=lw,zorder=2))
    ax.text(cx,cy,t,ha='center',va='center',fontsize=fs,zorder=4,
            linespacing=1.18)
def fa(ax,x0,y0,x1,y1,lbl=None,fs=6,lxy=None):
    ax.annotate('',xy=(x1,y1),xytext=(x0,y0),zorder=3,
        arrowprops=dict(arrowstyle='-|>',lw=0.9,color=INK,mutation_scale=8,
                        shrinkA=0,shrinkB=0))
    if lbl: ax.text(lxy[0],lxy[1],lbl,fontsize=fs,color=INK,ha='center',zorder=4)
def elbow(ax,pts,lbl=None,lxy=None,fs=6,rot=0):
    xs=[p[0] for p in pts[:-1]]; ys=[p[1] for p in pts[:-1]]
    ax.plot(xs,ys,color=INK,lw=0.9,solid_capstyle='projecting',zorder=3)
    fa(ax,pts[-2][0],pts[-2][1],pts[-1][0],pts[-1][1])
    if lbl: ax.text(lxy[0],lxy[1],lbl,fontsize=fs,color=INK,ha='center',
                    rotation=rot,zorder=4)
def flabel(ax,x,y,t,fs=5.8,fc='#F7F8F7'):
    """Place an edge label at the geometric midpoint, masking the shaft."""
    ax.text(x,y,t,fontsize=fs,color=INK,ha='center',va='center',zorder=5,
            bbox=dict(boxstyle='square,pad=0.10',fc=fc,ec='none'))
AMB,RDT='#FBF3E3','#F6E8E4'
fig,ax=plt.subplots(figsize=(2*CW,3.1)); ax.set_xlim(0,20); ax.set_ylim(0,8.4); ax.axis('off')
# phase lanes (exact rects, light borders)
ax.add_patch(FancyBboxPatch((0.35,0.4),7.05,7.6,
             boxstyle='round,pad=0,rounding_size=0.3',
             fc='#EFF4EE',ec='#C9D6C9',lw=0.8,mutation_scale=1,zorder=1))
ax.add_patch(FancyBboxPatch((7.95,0.4),11.75,7.6,
             boxstyle='round,pad=0,rounding_size=0.3',
             fc='#F2F4F7',ec='#CBD2DC',lw=0.8,mutation_scale=1,zorder=1))
ax.text(0.75,7.45,'Calibration phase',fontsize=8,weight='bold',color=INK,zorder=4)
ax.text(8.35,7.45,'Run phase (per control cycle)',fontsize=8,weight='bold',color=INK,zorder=4)
# calibration chain (one column; arrows span the exact 0.55 gaps)
fbox(ax,0.7,5.95,3.4,0.95,'power-up /\nrecal request',6.8)
fbox(ax,0.7,4.45,3.4,0.95,'pre-sweep:\n$V_\\pi$ period estimate',6.8)
fbox(ax,0.7,2.95,3.4,0.95,'full-period sweep\n($4\\pi$ for DPMZM children)',6.4)
fbox(ax,0.7,1.45,3.4,0.95,'fit + gauge fixing\n(ellipse / LS regression)',6.4)
fa(ax,2.4,5.95,2.4,5.40); fa(ax,2.4,4.45,2.4,3.90); fa(ax,2.4,2.95,2.4,2.40)
fbox(ax,4.85,1.45,2.4,0.95,'self-check\n$\\|\\hat A\\Phi+\\hat{b}-z\\|$ ok?',6.0,fc=AMB)
fa(ax,4.1,1.92,4.85,1.92)
elbow(ax,[(6.05,2.40),(6.05,6.42),(4.10,6.42)],'fail: re-sweep',(6.28,4.2),rot=90)
fa(ax,7.25,1.92,8.70,1.92,'pass',6,(7.98,2.08))
# run pipeline (bottom row) with monitor branch above
fbox(ax,8.70,1.45,2.8,0.95,'lock-in readout\n$\\mathbf{z}_k$ (2 or 9 ch.)',6.4)
fbox(ax,12.30,1.45,3.0,0.95,'demodulate\natan2 / 2-step GN',6.4)
fbox(ax,16.00,1.45,3.0,0.95,'PI update\n$V \\leftarrow V - G\\,e$',6.4)
fa(ax,11.50,1.92,12.30,1.92); fa(ax,15.30,1.92,16.00,1.92)
fbox(ax,12.30,3.65,3.0,0.95,'residual monitor\n$\\rho_k$, EWMA',6.4,fc=AMB)
fa(ax,13.80,2.40,13.80,3.65)
fbox(ax,16.00,3.65,3.0,0.95,'$\\bar\\rho>\\rho_{\\rm th}$ for\n$N_{\\rm p}$ cycles?',6.4,fc=AMB)
fa(ax,15.30,4.12,16.00,4.12)
fa(ax,17.50,4.60,17.50,5.85,'yes',6,(17.78,5.12))
fbox(ax,16.00,5.85,3.0,0.95,'trigger recal\n(micro-arc sweep)',6.4,fc=RDT)
elbow(ax,[(17.50,6.80),(17.50,7.15),(2.40,7.15),(2.40,6.90)],
      'recalibrate',(5.2,7.27))
elbow(ax,[(17.50,1.45),(17.50,0.80),(10.10,0.80),(10.10,1.45)],
      'next cycle ($<10^3$ MAC)',(13.8,0.52))
plt.tight_layout(); plt.savefig('figs/fig_flow.pdf'); plt.close()

# ---- MZM-only variant of the flowchart above for paper_mzm_zh: identical
#      deterministic patches/annotate drawing code, just with the three
#      DPMZM-specific box labels swapped for their single-MZM equivalents
#      (full 2Vpi sweep instead of 4pi for DPMZM children; 2-channel lock-in
#      instead of "2 or 9 ch."; atan2-only demod instead of atan2/2-step GN).
#      No RNG, no new computation -- pure re-draw of the same box geometry. ----
# ---- vertical single-column redraw for paper_mzm_zh. The two decisions use
#      diamonds. A threshold violation returns directly to power-up along the
#      left rail; the next-cycle branch uses the right rail. Edge labels sit at
#      the geometric midpoint of their line segments. Pure drawing only: no RNG
#      and no new computation. ----
fig,ax=plt.subplots(figsize=(CW,4.6)); ax.set_xlim(0,10); ax.set_ylim(0,26); ax.axis('off')
# two phase lanes stacked vertically
ax.add_patch(FancyBboxPatch((0.30,14.15),9.4,11.5,
             boxstyle='round,pad=0,rounding_size=0.3',
             fc='#EFF4EE',ec='#C9D6C9',lw=0.8,mutation_scale=1,zorder=1))
ax.add_patch(FancyBboxPatch((0.30,0.35),9.4,13.35,
             boxstyle='round,pad=0,rounding_size=0.3',
             fc='#F2F4F7',ec='#CBD2DC',lw=0.8,mutation_scale=1,zorder=1))
ax.text(0.60,24.90,'标定阶段',fontsize=7.5,weight='bold',color=INK,zorder=4)
# Keep the run title clear of the left recalibration rail.
ax.text(1.30,13.45,'运行阶段\n（每控制周期）',fontsize=7.0,weight='bold',
        color=INK,zorder=4,va='top',linespacing=1.3)
# Centred main chain; branch rails run along the lane margins.
BW=4.4; CXc=5.0; BX=CXc-BW/2
DW=5.2; DH=1.65
# --- calibration chain (top lane, descending) ---
fbox(ax,BX,23.15,BW,1.30,'上电 / 重定标请求',6.8)
fbox(ax,BX,21.05,BW,1.30,'预扫描：$V_\\pi$ 周期估计',6.8)
fbox(ax,BX,18.95,BW,1.30,'全周期扫描 ($2V_\\pi$)',6.6)
fbox(ax,BX,16.85,BW,1.30,'拟合与规范固定\n（椭圆/最小二乘）',6.4)
fdiamond(ax,CXc,15.35,DW,DH,'自检：径向/直流\n残差达标?',6.1,fc=AMB)
fa(ax,CXc,23.15,CXc,22.35); fa(ax,CXc,21.05,CXc,20.25)
fa(ax,CXc,18.95,CXc,18.15); fa(ax,CXc,16.85,CXc,15.35+DH/2)
# no -> re-sweep on the right rail
elbow(ax,[(CXc+DW/2,15.35),(8.95,15.35),(8.95,19.60),(BX+BW,19.60)])
flabel(ax,(CXc+DW/2+8.95)/2,15.35,'否',fc='#EFF4EE')
flabel(ax,8.95,(15.35+19.60)/2,'重扫',fc='#EFF4EE')
# yes -> hand over to the run phase
fa(ax,CXc,15.35-DH/2,CXc,11.95)
flabel(ax,CXc,(15.35-DH/2+11.95)/2,'是')
# --- run phase loop (bottom lane, descending then back-edge) ---
fbox(ax,BX,10.65,BW,1.30,'锁相读出\n$\\mathbf{z}_k$（2 通道）',6.4)
fbox(ax,BX,8.55,BW,1.30,'解调 atan2',6.6)
fbox(ax,BX,6.45,BW,1.30,'积分更新\n$V \\leftarrow V - G\\,e$',6.4)
fbox(ax,BX,4.35,BW,1.30,'残差监测\n$\\rho_k$（EWMA）',6.4,fc=AMB)
fdiamond(ax,CXc,2.75,DW,DH,'$\\bar\\rho>\\rho_{\\rm th}$ 持续\n$N_{\\rm p}$ 周期?',6.2,fc=AMB)
fa(ax,CXc,10.65,CXc,9.85); fa(ax,CXc,8.55,CXc,7.75)
fa(ax,CXc,6.45,CXc,5.65); fa(ax,CXc,4.35,CXc,2.75+DH/2)
# no -> next cycle on the right rail
elbow(ax,[(CXc+DW/2,2.75),(9.15,2.75),(9.15,11.30),(BX+BW,11.30)])
flabel(ax,(CXc+DW/2+9.15)/2,2.75,'否',fc='#F2F4F7')
flabel(ax,9.15,(2.75+11.30)/2,'下一周期',fc='#F2F4F7')
# yes -> return directly to power-up along the left rail
elbow(ax,[(CXc-DW/2,2.75),(0.75,2.75),(0.75,23.80),(BX,23.80)])
flabel(ax,(CXc-DW/2+0.75)/2,2.75,'是',fc='#F2F4F7')
plt.tight_layout(); plt.savefig('figs/fig_flow_mzm.pdf'); plt.close()

# ============ Fig F2: acquisition transients ============
fig,axs=plt.subplots(1,2,figsize=(2*CW,1.9))
# (a) MZM: four targets, same offset, log-error overlay + theory
cal=calibrate_mzm(P1); G=0.18
ax=axs[0]
for tgt,col in zip([0.6,1.9,3.6,5.2],[GRN,RED,BLU,GLD]):
    phi=tgt+1.5; errs=[]
    for k in range(60):
        X,Y=measure_mzm(phi,P1); ph,_=demod(cal,X,Y)
        e=np.angle(np.exp(1j*(ph-tgt))); phi-=G*e
        errs.append(abs(np.angle(np.exp(1j*(phi-tgt)))))
    ax.semilogy(np.maximum(np.array(errs),1e-4),color=col,label=f'$\\varphi^*={tgt}$')
n=np.arange(60); ax.semilogy(1.5*(1-G)**(n+1),'k--',lw=0.8,label='$(1-G)^n$ theory')
ax.set_xlabel('control step'); ax.set_ylabel('$|e|$ (rad)')
ax.set_title('(a) MZM acquisition, 4 targets',fontsize=7.5)
# lower left is the empty corner (the decay runs diagonally to the noisy tail)
ax.legend(ncol=1,borderpad=0.2,handlelength=1.2,loc='lower left',fontsize=6)
ax.set_ylim(1e-3,2)
# (b) DPMZM: arbitrary + standard target
ax=axs[1]
for tgt,col,lab in [(np.array([2.0,2.6,1.1]),GRN,'arbitrary'),
                    (np.array([np.pi,np.pi,np.pi/2]),RED,'standard QPSK')]:
    phi=tgt+np.array([0.6,-0.5,0.55]); est=tgt.copy(); errs=[]
    for k in range(60):
        est=gn(measure_dp(phi),est,2); phi-=0.16*(est-tgt)
        errs.append(np.linalg.norm(phi-tgt))
    ax.semilogy(np.maximum(np.array(errs),1e-4),color=col,label=lab)
ax.semilogy(0.96*(1-0.16)**(n+1),'k--',lw=0.8,label='$(1-G)^n$ theory')
ax.set_xlabel('control step'); ax.set_title('(b) DPMZM acquisition',fontsize=7.5)
ax.legend(borderpad=0.2,handlelength=1.2,loc='lower left',fontsize=6)
ax.set_ylim(1e-3,2)
# capture panel (a)'s already-plotted line data (xdata/ydata/color/label) and
# axis limits *before* saving/closing, so the single-panel variant below is a
# pure re-plot of already-computed arrays — no recomputation, no RNG draws
acq_a_lines = [(ln.get_xdata(), ln.get_ydata(), ln.get_color(), ln.get_linestyle(),
                ln.get_linewidth(), ln.get_label()) for ln in axs[0].get_lines()]
acq_a_ylim = axs[0].get_ylim()
plt.tight_layout(); plt.savefig('figs/fig_acq.pdf'); plt.close()
print('[acq] time constant 1/G: MZM %.1f steps, DPMZM %.1f steps'%(1/G,1/0.16))

# ---- single-panel MZM-only variant for paper_mzm_zh: re-plots the captured
#      line data from panel (a) above verbatim (no new computation/RNG) ----
fig,ax=plt.subplots(1,1,figsize=(CW,2.15))
for xd,yd,col,ls,lw,lab in acq_a_lines:
    ax.semilogy(xd,yd,color=col,linestyle=ls,linewidth=lw,label=lab)
ax.set_xlabel('control step'); ax.set_ylabel('$|e|$ (rad)')
ax.legend(ncol=1,borderpad=0.2,handlelength=1.2,loc='lower left',fontsize=6)
ax.set_ylim(acq_a_ylim)
plt.tight_layout(); plt.savefig('figs/fig_acq_mzm.pdf'); plt.close()

# ============ Fig F3: setpoint stepping ============
fig,axs=plt.subplots(2,1,figsize=(2*CW,2.6),sharex=True)
# (a) MZM staircase
tgts=[0.7,2.4,4.1,5.5,1.3]; seg=350
phi=tgts[0]; tr=[]; ref=[]
for i,tg in enumerate(tgts):
    for k in range(seg):
        d=0.004*rng.standard_normal()+0.0022*np.sin((i*seg+k)*0.045)
        phi+=d
        X,Y=measure_mzm(phi,P1); ph,_=demod(cal,X,Y)
        e=np.angle(np.exp(1j*(ph-tg))); phi-=G*e
        tr.append(phi%(2*np.pi)); ref.append(tg)
axs[0].plot(ref,'k--',lw=0.8,label='target $\\varphi^*$')
axs[0].plot(tr,color=GRN,lw=0.8,label='$\\varphi_b$ (affine loop)')
axs[0].set_ylabel('$\\varphi_b$ (rad)'); axs[0].legend(loc='upper right',borderpad=0.2)
axs[0].set_title('(a) MZM setpoint staircase across arbitrary points',fontsize=7.5)
# settling per step
def settle(tr,ref,seg,tol=0.02):
    ts=[]
    for i in range(1,len(tgts)):
        e=np.abs(np.angle(np.exp(1j*(np.array(tr[i*seg:i*seg+120])-tgts[i]))))
        idx=np.argmax(e<tol) if np.any(e<tol) else -1
        ts.append(idx)
    return ts
print('[step] MZM settling to 20 mrad per step:',settle(tr,ref,seg),'steps')
# (b) DPMZM 3-axis staircase (5 segments to match panel (a)'s 1750-step span)
tgseq=[np.array([np.pi,np.pi,np.pi/2]),np.array([2.0,2.6,1.1]),
       np.array([4.4,1.6,2.4]),np.array([2.8,4.9,0.6]),
       np.array([1.4,3.3,2.0])]
phi=tgseq[0].copy(); est=tgseq[0].copy(); trd=[]; refd=[]
for i,tg in enumerate(tgseq):
    for k in range(seg):
        d=0.0028*rng.standard_normal(3)+0.0016*np.sin((i*seg+k)*0.045+np.arange(3)*2.1)
        phi+=d
        est=gn(measure_dp(phi),est,2); phi-=0.16*(est-tg)
        trd.append(1e3*np.linalg.norm(phi-tg)); refd.append(0)
axs[1].semilogy(np.maximum(np.array(trd),0.5),color=GRN,lw=0.8)
for i in range(1,len(tgseq)): axs[1].axvline(i*seg,color=GLD,lw=0.8,ls=':')
axs[1].set_ylabel('$\\|e\\|$ (mrad)'); axs[1].set_xlabel('control step')
axs[1].set_title('(b) DPMZM: three-axis setpoint steps (dotted: step instants)',fontsize=7.5)
# capture panel (a)'s already-plotted line data before saving/closing, for a
# pure re-plot single-panel variant below (no recomputation, no RNG draws)
step_a_lines = [(ln.get_xdata(), ln.get_ydata(), ln.get_color(), ln.get_linestyle(),
                  ln.get_linewidth(), ln.get_label()) for ln in axs[0].get_lines()]
step_a_ylim = axs[0].get_ylim()
plt.tight_layout(); plt.savefig('figs/fig_step.pdf'); plt.close()

# ---- single-panel MZM-only variant for paper_mzm_zh: re-plots the captured
#      line data from panel (a) above verbatim (no new computation/RNG) ----
fig,ax=plt.subplots(1,1,figsize=(CW,1.9))
for xd,yd,col,ls,lw,lab in step_a_lines:
    ax.plot(xd,yd,color=col,linestyle=ls,linewidth=lw,label=lab)
ax.set_ylabel('$\\varphi_b$ (rad)'); ax.set_xlabel('control step')
ax.legend(loc='upper right',borderpad=0.2)
ax.set_ylim(step_a_ylim)
plt.tight_layout(); plt.savefig('figs/fig_step_mzm.pdf'); plt.close()

# ---- composite 1x2 MZM panel for paper_mzm_zh: (a) acquisition convergence,
#      (b) setpoint-step tracking. Pure re-plot of acq_a_lines/step_a_lines
#      (captured above from the already-drawn panel (a) axes of fig_acq.pdf
#      and fig_step.pdf); no new computation, no RNG draws.
#      Redraw (v3, legend fix): panel (a) previously had no legend entry at
#      all for the four per-target curves (incomplete legend) -- now they
#      get one merged grey representative-color handle ("各目标相位") plus
#      the "(1-G)^n theory" line, 2 entries total, placed upper right (the
#      curves decay toward the lower-right/noisy tail, so upper right is the
#      empty corner -- confirmed by rendering before/after). Panel (b)'s
#      legend previously sat upper right, covering the phi_b response curve
#      near its first step transition -- moved to lower left, an empty
#      corner for this staircase (first step target is low, ~0.7 rad, and
#      the curve only rises after settling), frameon=False so it doesn't
#      add a box over data. Tick/label fonts trimmed to <=6.5pt and margins
#      tightened via subplots_adjust so the axes occupy most of the frame. ----
fig,axs=plt.subplots(1,2,figsize=(CW,1.35))
ax=axs[0]
# list every target phase individually (user request): each per-target curve
# keeps its own colour + $\varphi^*$ label; theory line drawn last. Curves decay
# to the lower-right noisy tail, so the upper-right corner holds the 5-entry
# legend without covering data.
for xd,yd,col,ls,lw,lab in acq_a_lines:
    if 'theory' in lab:
        ax.semilogy(xd,yd,color='k',linestyle=ls,linewidth=lw,label='$(1-G)^n$ 理论',zorder=5)
    else:
        ax.semilogy(xd,yd,color=col,linestyle='-',linewidth=0.8,zorder=3,label=lab)
ax.set_xlabel('控制周期',fontsize=7,labelpad=1)
ax.set_ylabel('$|e|$ (rad)',fontsize=7,labelpad=1)
ax.tick_params(labelsize=6.5,pad=1)
# two legends stacked in the empty upper-right corner: the four target phases
# as a 2x2 block, the theory line on its own row below it (user request)
_h,_l=ax.get_legend_handles_labels()
_th=[(h,l) for h,l in zip(_h,_l) if '理论' in l]
_tg=[(h,l) for h,l in zip(_h,_l) if '理论' not in l]
_leg1=ax.legend([h for h,_ in _tg],[l for _,l in _tg],loc='upper right',ncol=2,
                bbox_to_anchor=(1.0,1.0),borderpad=0.2,handlelength=1.0,
                labelspacing=0.25,columnspacing=0.8,handletextpad=0.4,
                fontsize=5.6,frameon=False)
ax.add_artist(_leg1)
ax.legend([h for h,_ in _th],[l for _,l in _th],loc='upper right',ncol=1,
          bbox_to_anchor=(1.0,0.70),borderpad=0.2,handlelength=1.0,
          handletextpad=0.4,fontsize=5.6,frameon=False)
ax.set_ylim(acq_a_ylim)
ax.set_title('(a) 捕获（4 目标点）',fontsize=7,pad=2)
ax=axs[1]
for xd,yd,col,ls,lw,lab in step_a_lines:
    nice = '目标 $\\varphi^*$' if 'target' in lab else '$\\varphi_b$'
    ax.plot(xd,yd,color=col,linestyle=ls,linewidth=lw,label=nice)
ax.set_xlabel('控制周期',fontsize=7,labelpad=1)
ax.set_ylabel('$\\varphi_b$ (rad)',fontsize=7,labelpad=1)
ax.tick_params(labelsize=6.5,pad=1)
ax.legend(loc='upper left',borderpad=0.25,handlelength=1.2,
          handletextpad=0.4,fontsize=6.5,frameon=False)
ax.set_ylim(step_a_ylim)
ax.set_title('(b) 设定点阶跃',fontsize=7,pad=2)
fig.subplots_adjust(left=0.115,right=0.985,top=0.87,bottom=0.20,wspace=0.38)
plt.savefig('figs/fig_acqstep_mzm.pdf'); plt.close()

# ============ Fig F4: residual-triggered recalibration ============
Ptr=dict(P1); cal2=calibrate_mzm(Ptr); tgt=1.9
phi=tgt; rho_buf=[]; err_buf=[]; ev=None; rho_ew=0; lam=0.05
RHO_TH=0.06; Mreq=25; cnt=0
NTOT=3200
for k in range(NTOT):
    if k==1200:   # sudden drift jump: gain & offset change (e.g., power/m step)
        Ptr['gX']=0.85; Ptr['bx']=0.062
    d=0.004*rng.standard_normal()+0.0022*np.sin(k*0.045)
    phi+=d
    X,Y=measure_mzm(phi,Ptr); ph,r=demod(cal2,X,Y)
    rho=abs(r-1.0); rho_ew=(1-lam)*rho_ew+lam*rho
    e=np.angle(np.exp(1j*(ph-tgt))); phi-=G*e
    cnt = cnt+1 if rho_ew>RHO_TH else 0
    if cnt>=Mreq and ev is None:
        ev=k; cal2=calibrate_mzm(Ptr); cnt=0   # recal (sweep assumed executed)
    rho_buf.append(rho_ew); err_buf.append(1e3*abs(np.angle(np.exp(1j*(phi-tgt)))))
fig,axs=plt.subplots(2,1,figsize=(2*CW,2.5),sharex=True)
axs[0].plot(err_buf,color=GRN,lw=0.7)
axs[0].axvline(1200,color=RED,lw=0.9,ls='--'); axs[0].axvline(ev,color=BLU,lw=0.9)
axs[0].set_ylabel('$|e|$ (mrad)'); axs[0].set_ylim(0,1.05*max(err_buf))
axs[0].set_title('(a) locking error: drift jump at $k{=}1200$ (red), recal at $k{=}%d$ (blue)'%ev,fontsize=7.5)
axs[1].semilogy(rho_buf,color=INK,lw=0.7)
axs[1].axhline(RHO_TH,color=GLD,lw=0.9,ls='--')
axs[1].axvline(1200,color=RED,lw=0.9,ls='--'); axs[1].axvline(ev,color=BLU,lw=0.9)
axs[1].set_ylabel('$\\bar\\rho$ (EWMA)'); axs[1].set_xlabel('control step')
axs[1].set_title('(b) circle-residual monitor and threshold $\\rho_{\\rm th}{=}0.06$',fontsize=7.5)
plt.tight_layout(); plt.savefig('figs/fig_recal.pdf'); plt.close()

# ---- single-column MZM-only variant for paper_mzm_zh: pure re-plot of the
#      already-computed err_buf/rho_buf/ev/RHO_TH arrays above (no new
#      computation, no RNG draws). Narrowed to CW; fonts trimmed to <=7pt,
#      x-axis ticks thinned via MaxNLocator, titles shortened to (a)/(b)
#      short captions so the drift-jump / recal verticals, the threshold
#      dashed line and the EWMA curve all stay legible at column width. ----
fig,axs=plt.subplots(2,1,figsize=(CW,2.3),sharex=True)
axs[0].plot(err_buf,color=GRN,lw=0.6)
axs[0].axvline(1200,color=RED,lw=0.8,ls='--')
axs[0].axvline(ev,color=BLU,lw=0.8)
axs[0].set_ylabel('$|e|$ (mrad)',fontsize=7,labelpad=1)
axs[0].set_ylim(0,1.05*max(err_buf))
axs[0].tick_params(labelsize=6.5,pad=1)
axs[0].set_title('(a) 锁定误差（第1200周期注入突变）',fontsize=6.8,pad=2)
# Local zoom: at full 3200-step span the drift-jump line (k=1200, red)
# and the recal line (k=1231, blue) visually merge.  Keep the zoom fully
# inside the axes; connector artists are deliberately avoided because their
# automatic paths can cross the top boundary after single-column scaling.
_ax0=axs[0]
_axins=_ax0.inset_axes([0.58,0.42,0.40,0.54])
# tight window: only ~20 cycles of flat lead-in/lead-out around the
# 1200->1231 transient, so the spike fills the inset instead of drowning
_win_lo,_win_hi=1180,1260
_axins.plot(np.arange(_win_lo,_win_hi),err_buf[_win_lo:_win_hi],color=GRN,lw=0.7)
_axins.axvline(1200,color=RED,lw=0.9,ls='--')
_axins.axvline(ev,color=BLU,lw=0.9)
_axins.set_xlim(_win_lo,_win_hi)
_ymax_ins=max(err_buf[_win_lo:_win_hi])
# extra headroom: with the tight window the spike fills the inset, so the
# 31-cycle callout must live in a reserved band ABOVE the trace
_axins.set_ylim(0,1.42*_ymax_ins)
_axins.set_xticks([1200,ev])
_axins.tick_params(labelsize=5.0,pad=1,length=2)
_axins.set_yticks([])
for _sp in _axins.spines.values(): _sp.set_linewidth(0.6)
# annotate the 31-cycle gap with a double-headed arrow + label (Hu-style
# in-figure callout) between the two verticals, near the inset's top
_ins_y=1.12*_ymax_ins
_axins.annotate('',xy=(ev,_ins_y),xytext=(1200,_ins_y),
    arrowprops=dict(arrowstyle='<->',lw=0.7,color=INK,mutation_scale=6))
_axins.text(0.5*(1200+ev),_ins_y,'31 周期',fontsize=5.0,color=INK,
            ha='center',va='bottom')
_ax0.axvspan(_win_lo,_win_hi,facecolor=GLD,edgecolor=GLD,alpha=0.10,
             linewidth=0.55,zorder=0,clip_on=True)
axs[1].semilogy(rho_buf,color=INK,lw=0.6)
axs[1].axhline(RHO_TH,color=GLD,lw=0.8,ls='--')
axs[1].axvline(1200,color=RED,lw=0.8,ls='--')
axs[1].axvline(ev,color=BLU,lw=0.8)
axs[1].set_ylabel('$\\bar\\rho$ (EWMA)',fontsize=7,labelpad=1)
axs[1].set_xlabel('控制周期',fontsize=7,labelpad=1)
axs[1].tick_params(labelsize=6.5,pad=1)
axs[1].xaxis.set_major_locator(plt.MaxNLocator(nbins=5))
axs[1].set_title('(b) 圆残差监测与阈值 $\\rho_{\\rm th}{=}0.06$',fontsize=6.8,pad=2)
fig.subplots_adjust(left=0.155,right=0.98,top=0.90,bottom=0.13,hspace=0.55)
plt.savefig('figs/fig_recal_mzm.pdf'); plt.close()

pre=np.sqrt(np.mean(np.array(err_buf[800:1200])**2))
dur=np.sqrt(np.mean(np.array(err_buf[1200:ev])**2))
post=np.sqrt(np.mean(np.array(err_buf[ev+150:])**2))
print('[recal] detect latency=%d steps; RMS pre=%.1f, mismatch=%.1f, post=%.1f mrad'%(ev-1200,pre,dur,post))
print('figs:',sorted(f for f in os.listdir('figs') if f.startswith('fig_')))
