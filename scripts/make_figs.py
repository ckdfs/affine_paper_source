#!/usr/bin/env python3
"""Generate all figures for the IEEE paper. Math ported 1:1 from the
validated HTML simulations (MZM Part I, DPMZM Part II)."""
import numpy as np
from scipy.special import jv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow
import os
rng = np.random.default_rng(20260611)
os.makedirs('figs', exist_ok=True)

plt.rcParams.update({
    'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8,
    'legend.fontsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
    'lines.linewidth': 1.0, 'figure.dpi': 150,
    'font.family': 'serif', 'mathtext.fontset': 'cm'})
GRN, RED, BLU, GLD, INK = '#1F6E52', '#BC4B2A', '#2E5FA3', '#A8801F', '#1E2A24'
CW = 3.45   # IEEE column width in inches

# ================= Part I: single MZM =================
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
    mx, my = X.mean(), Y.mean()
    sc = np.hypot(X-mx, Y-my).mean()
    x, y = (X-mx)/sc, (Y-my)/sc
    D = np.stack([x*x, x*y, y*y, x, y], 1)
    th = np.linalg.solve(D.T@D, D.T@np.ones(N))
    a,b,c,d,e = th; det = 4*a*c-b*b
    cx = (b*e-2*c*d)/det; cy = (b*d-2*a*e)/det
    kq = 1-(a*cx*cx+b*cx*cy+c*cy*cy+d*cx+e*cy)
    M = np.array([[a, b/2],[b/2, c]])/kq
    c0 = np.array([mx+sc*cx, my+sc*cy]); M = M/sc**2
    w, V = np.linalg.eigh(M)
    B = V@np.diag(np.sqrt(w))@V.T
    us = (B@np.stack([X-c0[0], Y-c0[1]])).T
    cr = np.sum(us[:-1,0]*us[1:,1]-us[:-1,1]*us[1:,0])
    if cr < 0: B = np.diag([1,-1])@B; us[:,1] *= -1
    th_i = np.arctan2(us[:,1], us[:,0])
    Dg = np.stack([np.ones(N), np.cos(th_i), np.sin(th_i)],1)
    cf = np.linalg.solve(Dg.T@Dg, Dg.T@dc)
    sgn = 1 if jv(0,p['m'])>=0 else -1
    phc = np.arctan2(sgn*cf[2], sgn*cf[1]); dphi = -phc
    R = np.array([[np.cos(dphi),-np.sin(dphi)],[np.sin(dphi),np.cos(dphi)]])
    B = R@B
    return {'c0':c0, 'B':B, 'M':M, 'X':X, 'Y':Y, 'us':(B@np.stack([X-c0[0],Y-c0[1]])).T}

P1 = dict(m=1.2, RP=1, gX=1.18, gY=0.88, delta=np.deg2rad(10), eps=0.10,
          bx=0.030, by=-0.022, sigma=0.005)

# ---- Fig 1: architecture schematics (a) MZM (b) DPMZM ----
def box(ax,x,y,w,h,t,fs=6.5,fc='#F4F7F1'):
    ax.add_patch(Rectangle((x,y),w,h,fc=fc,ec=INK,lw=0.8))
    ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=fs)
def arr(ax,x0,y0,x1,y1):
    ax.annotate('',xy=(x1,y1),xytext=(x0,y0),
        arrowprops=dict(arrowstyle='->',lw=0.8,color=INK))
fig,axs=plt.subplots(2,1,figsize=(CW,3.0))
ax=axs[0]; ax.set_xlim(0,10); ax.set_ylim(0,3.2); ax.axis('off')
ax.text(0.1,3.0,'(a)',fontsize=8,weight='bold')
box(ax,0.2,1.6,1.2,0.8,'laser'); box(ax,2.0,1.4,2.0,1.2,'MZM\n$\\varphi_b$')
arr(ax,1.4,2.0,2.0,2.0); arr(ax,4.0,2.0,4.9,2.0)
box(ax,4.9,1.6,1.2,0.8,'tap/PD',6.0)
box(ax,6.6,2.0,1.5,0.7,'LIA $\\omega$: $Y$',6.0); box(ax,6.6,1.1,1.5,0.7,'LIA $2\\omega$: $X$',6.0)
arr(ax,6.1,2.0,6.6,2.35); arr(ax,6.1,2.0,6.6,1.45)
box(ax,8.4,1.3,1.5,1.4,'$\\hat{A}^{-1}(\\mathbf{z}-\\hat{\\mathbf{b}})$\natan2, PI',6.0)
arr(ax,8.1,2.35,8.4,2.2); arr(ax,8.1,1.45,8.4,1.6)
arr(ax,9.15,1.3,9.15,0.55); arr(ax,9.15,0.55,3.0,0.55); arr(ax,3.0,0.55,3.0,1.4)
ax.text(6.0,0.7,'bias DAC $V_b$ + dither $m\\sin\\omega t$',fontsize=6,ha='center')
ax=axs[1]; ax.set_xlim(0,10); ax.set_ylim(0,3.6); ax.axis('off')
ax.text(0.1,3.4,'(b)',fontsize=8,weight='bold')
box(ax,0.2,1.7,0.9,0.8,'laser',6)
box(ax,1.8,2.3,1.6,0.85,'child I: $\\varphi_1$',6); box(ax,1.8,0.8,1.6,0.85,'child Q: $\\varphi_2$',6)
box(ax,3.8,0.8,1.0,0.85,'$e^{j\\Theta_3}$',6)
arr(ax,1.1,2.1,1.8,2.7); arr(ax,1.1,2.1,1.8,1.2)
arr(ax,3.4,1.2,3.8,1.2); arr(ax,3.4,2.7,5.3,2.7); arr(ax,4.8,1.2,5.3,1.6)
box(ax,5.3,1.6,0.7,1.3,'+',8); arr(ax,6.0,2.25,6.7,2.25); box(ax,6.7,1.85,0.9,0.8,'PD',6)
arr(ax,7.6,2.25,8.2,2.25)
box(ax,8.2,1.5,1.7,1.5,'9-ch LIA\n$\\omega_i,2\\omega_i,$IMD\nGN demod, PI',5.6)
arr(ax,9.05,1.5,9.05,0.45); arr(ax,9.05,0.45,2.6,0.45)
arr(ax,2.6,0.45,2.6,0.8); ax.text(6.0,0.18,'$V_{1,2,3}$ + dithers $m_i\\sin\\omega_i t$',fontsize=6,ha='center')
plt.tight_layout(); plt.savefig('figs/fig_arch.pdf'); plt.close()

# ---- Fig 2: phase plane: raw ellipse + corrected circle ----
# (no legend: it covered the data; elements are annotated directly instead)
cal = calibrate_mzm(P1)
fig,axs=plt.subplots(1,2,figsize=(CW,2.05))
ax=axs[0]
ax.plot(cal['X'],cal['Y'],'.',ms=1.5,color='0.45')
t=np.linspace(0,2*np.pi,300); A_hat=np.linalg.inv(cal['B'])
ell=(A_hat@np.stack([np.cos(t),np.sin(t)]))+cal['c0'][:,None]
ax.plot(ell[0],ell[1],color=BLU,lw=1.1)
ax.plot(*cal['c0'],'+',color=BLU,ms=7,mew=1.3)
ax.annotate('$\\hat{\\mathbf{b}}$',cal['c0'],textcoords='offset points',
            xytext=(4,-10),fontsize=7,color=BLU)
zpi=cal['c0']+A_hat@np.array([-1,0])
ax.plot(*zpi,'o',mfc=GLD,mec=GLD,ms=4.5)
ax.annotate('$\\varphi{=}\\pi$',zpi,textcoords='offset points',
            xytext=(-7,4),fontsize=7,color=GLD,ha='right')
ax.set_xlabel('$X$'); ax.set_ylabel('$Y$')
ax.set_title('(a) raw observable plane',fontsize=7.5)
ax.set_aspect('equal'); ax.margins(0.22)
ax=axs[1]
ax.plot(cal['us'][:,0],cal['us'][:,1],'.',ms=1.5,color=GRN)
ax.add_patch(plt.Circle((0,0),1,fill=False,ec=INK,lw=0.8,ls='--'))
ax.set_xlabel('$\\hat u_x$'); ax.set_ylabel('$\\hat u_y$')
ax.set_title('(b) after affine inversion',fontsize=7.5)
ax.set_aspect('equal'); ax.set_xlim(-1.35,1.35); ax.set_ylim(-1.35,1.35)
plt.tight_layout(); plt.savefig('figs/fig_ellipse.pdf'); plt.close()

# ---- Fig 3: J1, J2, kappa vs m ----
# legend moved above the axes (it used to cover the J1 peak); kappa is a
# condition number, so plot max-ratio (J1/J2 flips to J2/J1 past m~2.63)
m=np.linspace(0.05,3,400)
fig,ax=plt.subplots(figsize=(CW,1.95))
ax.plot(m,jv(1,m),color=GRN,label='$J_1(m)$')
ax.plot(m,jv(2,m),color=RED,label='$J_2(m)$')
ax.set_xlabel('dither depth $m$ (rad)'); ax.set_ylabel('$J_n(m)$')
ax2=ax.twinx()
kap=np.maximum(jv(1,m),jv(2,m))/np.maximum(np.minimum(jv(1,m),jv(2,m)),1e-9)
ax2.semilogy(m,kap,color=BLU,ls='--',label='$\\kappa(A)$')
ax2.semilogy(m,4/m,color=BLU,ls=':',lw=0.8,label='$4/m$')
ax2.set_ylabel('$\\kappa(A)$'); ax2.set_ylim(1,200)
ax.axvline(1.2,color=GLD,lw=0.8)
k12=jv(1,1.2)/jv(2,1.2)
ax2.plot(1.2,k12,'o',color=GLD,ms=4)
ax2.annotate('$J_1/J_2{=}%.2f$'%k12,(1.2,k12),textcoords='offset points',
             xytext=(6,3),fontsize=6.5,color=GLD)
l1,la1=ax.get_legend_handles_labels(); l2,la2=ax2.get_legend_handles_labels()
ax.legend(l1+l2,la1+la2,loc='lower center',bbox_to_anchor=(0.5,0.99),ncol=4,
          frameon=False,borderpad=0.2,handlelength=1.4,columnspacing=0.9)
plt.tight_layout(); plt.savefig('figs/fig_bessel.pdf'); plt.close()

# ---- Fig 4: MZM closed loop ----
def mzm_loop(p, phi_ref, n=2600, G=0.18):
    cal = calibrate_mzm(p)
    k1n = p['RP']*jv(1,p['m'])
    slope = -k1n*np.cos(phi_ref); Yref = -k1n*np.sin(phi_ref)
    sl = np.sign(slope if slope!=0 else 1)*max(abs(slope),0.08*k1n)
    phiA = phi_ref+0.4; phiN = phi_ref+0.4
    eA=[]; eN=[]
    for t in range(n):
        d = 0.004*rng.standard_normal()+0.0022*np.sin(t*0.045)
        phiA += d; phiN += d
        X,Y = measure_mzm(phiA,p)
        u = cal['B']@np.array([X-cal['c0'][0],Y-cal['c0'][1]])
        e = np.angle(np.exp(1j*(np.arctan2(u[1],u[0])-phi_ref)))
        phiA -= G*e; eA.append(np.angle(np.exp(1j*(phiA-phi_ref)))*1e3)
        X2,Y2 = measure_mzm(phiN,p)
        e2 = np.clip((Y2-Yref)/sl,-1,1); phiN -= G*e2
        eN.append(np.angle(np.exp(1j*(phiN-phi_ref)))*1e3)
    return np.array(eA), np.array(eN)
eA,eN = mzm_loop(P1, 1.9)
# log |error| axis: the old +/-400 mrad clip rendered the ~1.3 rad wrong-branch
# error as a fake rail-to-rail square wave
fig,ax=plt.subplots(figsize=(CW,1.95))
t=np.arange(len(eA))
ax.semilogy(t,np.maximum(np.abs(eN),1.0),color=RED,lw=0.7,label='H1 amplitude matching')
ax.semilogy(t,np.maximum(np.abs(eA),1.0),color=GRN,lw=0.7,label='affine demod (proposed)')
ax.set_xlabel('control step'); ax.set_ylabel('$|\\varphi_b-\\varphi^*|$ (mrad)')
ax.set_ylim(1,4000)
# legend above the axes: the traces span the full panel, any inside placement
# would cover them
ax.legend(loc='lower center',bbox_to_anchor=(0.5,0.99),ncol=2,frameon=False,
          borderpad=0.2,handlelength=1.4,columnspacing=1.0,fontsize=6.5)
rmsA=np.sqrt(np.mean(eA[300:]**2)); rmsN=np.sqrt(np.mean(np.clip(eN[300:],-3142,3142)**2))
print(f'[Fig4] MZM loop  affine RMS={rmsA:.1f} mrad   H1 RMS={rmsN:.1f} mrad')
plt.tight_layout(); plt.savefig('figs/fig_mzmloop.pdf'); plt.close()

# ================= Part II: DPMZM =================
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
Atrue=A0+sc*rng.standard_normal((9,12))
btrue=0.5*0.02*rng.standard_normal(9)
SIG=0.002
def measure_dp(p,noisy=True):
    z=Atrue@feat(p)+btrue
    if noisy: z=z+SIG*rng.standard_normal(9)
    return z
def calibrate_dp(N=3000):
    D=np.array([0.04241,0.05317,0.06789])
    PH=np.outer(np.arange(N),D)
    F=np.stack([np.concatenate([feat(p),[1]]) for p in PH])
    Z=np.stack([measure_dp(p) for p in PH])
    TH=np.linalg.solve(F.T@F,F.T@Z)   # 13x9
    return TH[:12].T, TH[12]
Ah,bh=calibrate_dp()
relF=np.linalg.norm(Ah-Atrue)/np.linalg.norm(Atrue)*100
print(f'[cal] DPMZM identification relF={relF:.3e} %')
def gn(z,est,iters=2,Am=None,bm=None):
    Am=Ah if Am is None else Am; bm=bh if bm is None else bm
    est=np.array(est,float)
    for _ in range(iters):
        J=Am@dfeat(est); r=z-Am@feat(est)-bm
        d=np.linalg.solve(J.T@J+1e-6*np.eye(3),J.T@r)
        n=np.linalg.norm(d); est=est+d*(0.5/n if n>0.5 else 1)
    return est
def sigmin(Am,p,rows):
    J=(Am@dfeat(p))[rows]
    return np.sqrt(max(np.linalg.eigvalsh(J.T@J)[0],0))

# ---- Fig 5: intensity map with Klein points ----
f1=np.linspace(0,4*np.pi,240); f2=np.linspace(0,4*np.pi,240)
F1,F2=np.meshgrid(f1,f2)
Pm=(2+np.cos(F1)+np.cos(F2))/8+0.5*np.cos(F1/2)*np.cos(F2/2)*np.cos(np.pi/2)
fig,ax=plt.subplots(figsize=(CW,2.6))
im=ax.pcolormesh(F1,F2,Pm,cmap='Greens_r',shading='auto',rasterized=True)
plt.colorbar(im,ax=ax,label='$P/P_0$',pad=0.02)
for a in [np.pi,3*np.pi]:
    for b in [np.pi,3*np.pi]:
        mk='o' if (a==np.pi and b==np.pi) else 'o'
        ax.plot(a,b,mk,mfc=GLD if (a==np.pi and b==np.pi) else 'none',
                mec=GLD,ms=7,mew=1.5)
tk=[0,np.pi,2*np.pi,3*np.pi,4*np.pi]; tl=['0','$\\pi$','$2\\pi$','$3\\pi$','$4\\pi$']
ax.set_xticks(tk); ax.set_xticklabels(tl); ax.set_yticks(tk); ax.set_yticklabels(tl)
ax.set_xlabel('$\\varphi_1$'); ax.set_ylabel('$\\varphi_2$')
plt.tight_layout(); plt.savefig('figs/fig_torus.pdf'); plt.close()

# ---- Fig 6: observability maps ----
# grid must contain phi=pi exactly (73 points: step 4pi/72, pi = 18 steps),
# otherwise the singular points are sampled off-center and look shallow
g=73; f=np.linspace(0,4*np.pi,g)
def smap(rows,phi3):
    M=np.zeros((g,g))
    for i,a in enumerate(f):
        for j,b in enumerate(f):
            M[j,i]=sigmin(A0,[a,b,phi3],rows)
    return np.log10(np.maximum(M,1e-6))
maps=[(list(range(6)),np.pi/2,'(a) 6 harmonic ch., $\\varphi_3=\\pi/2$'),
      (list(range(9)),np.pi/2,'(b) +IMD (9 ch.), $\\varphi_3=\\pi/2$'),
      (list(range(9)),0.0,'(c) 9 ch., $\\varphi_3=0$')]
fig,axs=plt.subplots(1,3,figsize=(2*CW,2.1),sharey=True)
for ax,(rows,p3,tt) in zip(axs,maps):
    im=ax.pcolormesh(f,f,smap(rows,p3),cmap='viridis',vmin=-6,vmax=-0.8,shading='auto',rasterized=True)
    ax.set_xticks(tk); ax.set_xticklabels(tl); ax.set_yticks(tk); ax.set_yticklabels(tl)
    ax.set_title(tt,fontsize=7.5); ax.set_xlabel('$\\varphi_1$')
axs[0].set_ylabel('$\\varphi_2$')
fig.colorbar(im,ax=axs,label='$\\log_{10}\\sigma_{\\min}(\\mathcal{J})$',fraction=0.02,pad=0.01)
plt.savefig('figs/fig_obs.pdf',bbox_inches='tight'); plt.close()
s6=sigmin(A0,[np.pi,np.pi,np.pi/2],list(range(6)))
s9=sigmin(A0,[np.pi,np.pi,np.pi/2],list(range(9)))
sd=sigmin(A0,[np.pi,np.pi,0.0],list(range(9)))
print(f'[obs] sigma_min: 6ch@std={s6:.2e}  9ch@std={s9:.3f}  9ch@(pi,pi,0)={sd:.2e}')

# ---- Fig 7: DPMZM closed loop, arbitrary + standard targets ----
def dp_loop(tgt,n=2600,G=0.16):
    F=feat(tgt); ref=A0[[0,2,6]]@F
    Jd=(A0@dfeat(tgt)); slopes=np.array([Jd[0,0],Jd[2,1],Jd[6,2]])
    fl=np.array([abs(A0[0,1]),abs(A0[2,3]),abs(A0[6,10])])
    slopes=np.sign(np.where(slopes==0,1,slopes))*np.maximum(np.abs(slopes),0.15*fl)
    phiA=np.array(tgt)+0.25; phiT=np.array(tgt)+0.25; est=np.array(tgt,float)
    eA=[];eT=[]
    for t in range(n):
        d=1.0*(0.0028*rng.standard_normal(3)+0.0016*np.sin(t*0.045+np.arange(3)*2.1))
        phiA+=d; phiT+=d
        est=gn(measure_dp(phiA),est,2)
        phiA-=G*(est-tgt); eA.append(1e3*np.linalg.norm(phiA-tgt))
        z2=measure_dp(phiT)
        e=np.clip((z2[[0,2,6]]-ref)/slopes,-1,1); phiT-=G*e
        eT.append(1e3*np.linalg.norm(phiT-tgt))
    return np.array(eA),np.array(eT)
fig,axs=plt.subplots(1,2,figsize=(2*CW,2.05),sharey=True)
for ax,(tgt,tt) in zip(axs,[(np.array([2.0,2.6,1.1]),'(a) arbitrary target $(2.0,2.6,1.1)$'),
                            (np.array([np.pi,np.pi,np.pi/2]),'(b) standard QPSK target $(\\pi,\\pi,\\pi/2)$')]):
    eA,eT=dp_loop(tgt)
    # log axis: on the old 0-800 linear axis the ~18 mrad GN trace was
    # squashed invisibly against the x-axis
    ax.semilogy(np.maximum(eT,1.0),color=RED,lw=0.7,label='three independent loops')
    ax.semilogy(np.maximum(eA,1.0),color=GRN,lw=0.7,label='GN affine (proposed)')
    ax.set_xlabel('control step'); ax.set_title(tt,fontsize=7.5); ax.set_ylim(1,1200)
    rA=np.sqrt(np.mean(eA[300:]**2)); rT=np.sqrt(np.mean(np.clip(eT[300:],0,800)**2))
    print(f'[Fig7] {tt}: GN RMS={rA:.1f} mrad  trad RMS={rT:.1f} mrad')
axs[0].set_ylabel('$\\|\\boldsymbol{\\varphi}-\\boldsymbol{\\varphi}^*\\|$ (mrad)')
# figure-level legend above both panels (the red trace sits near the top of
# the log axis, leaving no clean inside spot)
h,l=axs[0].get_legend_handles_labels()
fig.legend(h,l,loc='upper center',ncol=2,frameon=False,fontsize=7,
           bbox_to_anchor=(0.5,1.01),handlelength=1.4,columnspacing=1.2)
plt.tight_layout(rect=(0,0,1,0.90)); plt.savefig('figs/fig_dploop.pdf'); plt.close()

# ---- Fig 8: identified A heatmap with A0 sparsity boxes ----
fig,ax=plt.subplots(figsize=(CW,1.9))
v=np.max(np.abs(Ah))
im=ax.imshow(Ah,cmap='RdYlGn',vmin=-v,vmax=v,aspect='auto')
for r in range(9):
    for c in range(12):
        if A0[r,c]!=0:
            ax.add_patch(Rectangle((c-0.5,r-0.5),1,1,fill=False,ec=INK,lw=1.0))
ax.set_yticks(range(9)); ax.set_yticklabels(['$Y_1$','$X_1$','$Y_2$','$X_2$','$Y_3$','$X_3$','$Z_-$','$Z_{13}$','$Z_{23}$'])
ax.set_xticks(range(12))
ax.set_xticklabels(['$c\\varphi_1$','$s\\varphi_1$','$c\\varphi_2$','$s\\varphi_2$','$ccC$','$ccS$','$csC$','$csS$','$scC$','$scS$','$ssC$','$ssS$'],rotation=60,fontsize=6)
plt.colorbar(im,ax=ax,label='$\\hat A$ entry',pad=0.02)
plt.tight_layout(); plt.savefig('figs/fig_ahat.pdf'); plt.close()

# ---- Monte Carlo stats for the results table ----
errs=[]
for k in range(60):
    cal=calibrate_mzm(P1)
    phi=rng.uniform(0,2*np.pi)
    X,Y=measure_mzm(phi,P1,noisy=False)
    u=cal['B']@np.array([X-cal['c0'][0],Y-cal['c0'][1]])
    errs.append(abs(np.angle(np.exp(1j*(np.arctan2(u[1],u[0])-phi))))*1e3)
errs=np.sort(errs)
print(f'[MC] MZM noisy-cal demod error: median={errs[30]:.2f} mrad  P95={errs[57]:.2f} mrad')
# GN cold-ish start recovery
mx=0
for k in range(40):
    p=rng.uniform(0.3,5.8,3); z=measure_dp(p,noisy=False)
    rec=gn(z,p+np.array([0.3,-0.3,0.3]),10)
    mx=max(mx,np.linalg.norm(rec-p))
print(f'[GN] zero-noise recovery from 0.3 rad offsets: max={mx*1e3:.2e} mrad')
print('figures done:',sorted(os.listdir('figs')))
