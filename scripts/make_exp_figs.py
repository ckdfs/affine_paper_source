#!/usr/bin/env python3
"""Render the EXPERIMENTAL figures from recorded bench data.

  fig_exp_mzm.pdf    single-MZM bench schematic   (data-free, always)
  fig_exp_dpmzm.pdf  planned DPMZM schematic       (data-free, always)
  fig_exp1.pdf       calibration ellipse + circle  (needs calib.npz/_fit.json)
  fig_exp2.pdf       lock rms vs phi*: affine/H1   (needs lock_sweep.npz)
  fig_exp3.pdf       drift + recal record          (needs drift.npz)

Offline (no hardware). Missing measured data -> that figure is SKIPPED with a
warning, never an error, so `make figs`-style runs stay green before the bench
campaign.  Run under the build.py figure-python (numpy/matplotlib).

  python scripts/make_exp_figs.py                       # data/exp -> figs/
  python scripts/make_exp_figs.py --data-dir build/exp_sim --out-dir build/exp_sim
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt              # noqa: E402
from matplotlib import font_manager          # noqa: E402
from matplotlib.patches import Rectangle, Circle  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_common as ec  # noqa: E402


def _configure_fonts():
    cands = []
    env = os.environ.get("PAPER_CJK_FONT")
    if env:
        cands.append(env)
    cands += glob.glob(
        "/usr/local/texlive/*/texmf-dist/fonts/opentype/public/fandol/"
        "FandolSong-Regular.otf")
    cands += [
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        os.path.expanduser("~/Library/Fonts/msyh.ttc"),
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
    serif += ["TeX Gyre Termes", "Times New Roman", "DejaVu Serif"]
    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "lines.linewidth": 1.0, "figure.dpi": 150,
        "font.family": "serif", "font.serif": serif,
        "mathtext.fontset": "cm", "axes.unicode_minus": False})


_configure_fonts()
GRN, RED, BLU, GLD, INK = "#1F6E52", "#BC4B2A", "#2E5FA3", "#A8801F", "#1E2A24"
CW = 3.45            # IEEE column width (in)
TW = 7.16            # IEEE text width (in)


def _box(ax, x, y, w, h, t, fs=6.0, fc="#F4F7F1"):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=INK, lw=0.8))
    ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=fs)


def _arr(ax, x0, y0, x1, y1, color=INK, ls="-"):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", lw=0.8, color=color, ls=ls))


# --------------------------------------------------------------------------- #
#  data-free schematics                                                       #
# --------------------------------------------------------------------------- #
def fig_setup_mzm(out):
    fig, ax = plt.subplots(figsize=(TW, 2.35)); ax.set_xlim(0, 16)
    ax.set_ylim(0, 5.0); ax.axis("off")
    _box(ax, 0.2, 2.4, 1.5, 0.9, "DFB 激光\n~9 dBm")
    _box(ax, 2.2, 2.2, 1.9, 1.3, "MZM\n$V_\\pi{\\approx}5.5$V\nRF 接地")
    _box(ax, 4.6, 2.4, 1.6, 0.9, "1:9\n耦合器")
    _box(ax, 6.7, 2.4, 1.2, 0.9, "PD")
    _box(ax, 8.3, 2.4, 1.2, 0.9, "TIA")
    _box(ax, 10.0, 1.5, 3.0, 2.6,
         "STM32H523 板\nDAC8568→×4 减法→偏压\nADS131M02 (CH0/CH1)\nGoertzel: H1/H2/DC", 5.6,
         fc="#EAF1F7")
    _box(ax, 13.6, 2.4, 2.2, 1.0, "上位机\n仿射 + 基线\n(gen/acq)", 5.8, fc="#F7F0EA")
    for (x0, x1) in [(1.7, 2.2), (4.1, 4.6), (6.2, 6.7), (7.9, 8.3),
                     (9.5, 10.0), (13.0, 13.6)]:
        _arr(ax, x0, 2.85, x1, 2.85)
    # feedback bias board -> MZM
    _arr(ax, 11.5, 1.5, 11.5, 0.7); _arr(ax, 11.5, 0.7, 3.15, 0.7)
    _arr(ax, 3.15, 0.7, 3.15, 2.2, color=BLU)
    ax.text(7.3, 0.5, "偏置 $V_b$ + 导频 $m\\sin\\omega t$ (写回)", fontsize=5.8,
            ha="center", color=BLU)
    # cross-validation taps
    _box(ax, 6.4, 4.0, 2.0, 0.8, "DM858E (DE4)\nPD 直流", 5.6, fc="#F2F2F2")
    _box(ax, 8.7, 4.0, 2.4, 0.8, "SDS824X HD (DE2)\nTIA 交流 FFT", 5.6, fc="#F2F2F2")
    _arr(ax, 7.3, 3.3, 7.3, 4.0, color="0.5", ls=":")
    _arr(ax, 8.9, 3.3, 9.7, 4.0, color="0.5", ls=":")
    ax.text(8.0, 4.95, "LAN/SCPI 独立交叉验证", fontsize=5.8, ha="center",
            color="0.4")
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp_mzm.pdf"))
    plt.close(fig); print("[fig] fig_exp_mzm.pdf")


def fig_setup_dpmzm(out):
    fig, ax = plt.subplots(figsize=(TW, 2.2)); ax.set_xlim(0, 16)
    ax.set_ylim(0, 4.6); ax.axis("off")
    ax.text(0.1, 4.3, "（计划/未来工作）", fontsize=7, color="0.4")
    _box(ax, 0.2, 2.0, 1.4, 0.9, "DFB 激光")
    _box(ax, 2.1, 1.4, 2.2, 2.1,
         "DPMZM\n子I:$\\varphi_1$ 子Q:$\\varphi_2$\n父:$\\varphi_3$", 5.8)
    _box(ax, 4.7, 2.0, 1.2, 0.9, "PD")
    _box(ax, 6.1, 2.0, 1.2, 0.9, "TIA")
    _box(ax, 7.8, 1.2, 3.2, 2.6,
         "STM32H523 板\nDAC8568 八路偏置\ngen: 三音导频 $\\omega_{1,2,3}$\n"
         "acq: 6 谐波 + 3 IMD", 5.6, fc="#EAF1F7")
    _box(ax, 11.6, 2.0, 2.4, 1.1, "上位机\n仿射标定\nGauss–Newton", 5.8, fc="#F7F0EA")
    for (x0, x1) in [(1.6, 2.1), (4.3, 4.7), (5.9, 6.1), (7.3, 7.8), (11.0, 11.6)]:
        _arr(ax, x0, 2.45, x1, 2.45)
    _arr(ax, 9.4, 1.2, 9.4, 0.6); _arr(ax, 9.4, 0.6, 3.2, 0.6)
    _arr(ax, 3.2, 0.6, 3.2, 1.4, color=BLU)
    ax.text(6.3, 0.35, "三路偏置 $V_{1,2,3}$ + 三音导频 (写回)", fontsize=5.8,
            ha="center", color=BLU)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp_dpmzm.pdf"))
    plt.close(fig); print("[fig] fig_exp_dpmzm.pdf")


# --------------------------------------------------------------------------- #
#  measured-data figures                                                      #
# --------------------------------------------------------------------------- #
def _read_csv(p):
    import csv as _csv
    return list(_csv.DictReader(open(p)))


def fig_vpi(data, out):
    """fig:exp0 — stage-0 DC transfer P(V_b) (bidirectional, shows drift) and
    the DC-vs-phase cosine."""
    p = os.path.join(data, "vpi.csv")
    if not os.path.exists(p):
        print("[skip] fig_exp0: vpi.csv not found"); return
    rows = _read_csv(p)
    has_dir = bool(rows) and "dir" in rows[0]

    def sel(d):
        b = np.array([float(r["bias"]) for r in rows if not has_dir or r["dir"] == d])
        y = np.array([float(r["dc_dmm"]) for r in rows if not has_dir or r["dir"] == d])
        return b, y
    if has_dir:
        bu, du = sel("up"); bd, dd = sel("down")
        au, bbu, vpu, v0u = ec.fit_dc_transfer(bu, du)
        ad, bbd, vpd, v0d = ec.fit_dc_transfer(bd, dd)
        a, b = 0.5 * (au + ad), 0.5 * (bbu + bbd)
        vpi, v0 = 0.5 * (vpu + vpd), 0.5 * (v0u + v0d)
        ttl = (f"(a) 直流传递曲线  $V_\\pi{{=}}{vpi:.3f}$ V"
               f"（上/下 ${vpu:.3f}/{vpd:.3f}$）")
    else:
        bu, du = sel(None); bd, dd = np.array([]), np.array([])
        a, b, vpi, v0 = ec.fit_dc_transfer(bu, du)
        ttl = f"(a) 直流传递曲线  $V_\\pi{{=}}{vpi:.3f}$ V"
    fig, axs = plt.subplots(1, 2, figsize=(TW, 2.2))
    ax = axs[0]
    ax.plot(bu, du, ".", ms=2, color=GRN, label="上行")
    if has_dir:
        ax.plot(bd, dd, ".", ms=2, color=RED, label="下行")
    allb = np.concatenate([bu, bd]) if has_dir else bu
    vv = np.linspace(allb.min(), allb.max(), 400)
    ax.plot(vv, a + b * np.cos(np.pi * (vv - v0) / vpi), color=BLU, lw=1.0,
            label="拟合")
    ax.set_xlabel("偏压 $V_b$ (V)"); ax.set_ylabel("PD 直流 (V)")
    ax.set_title(ttl, fontsize=7); ax.legend(fontsize=6, loc="best")
    ax = axs[1]
    ph = lambda bb: ((np.pi * (bb - v0) / vpi + np.pi) % (2 * np.pi)) - np.pi
    ax.plot(ph(bu), du, ".", ms=2, color=GRN)
    if has_dir:
        ax.plot(ph(bd), dd, ".", ms=2, color=RED)
    pp = np.linspace(-np.pi, np.pi, 300)
    ax.plot(pp, a + b * np.cos(pp), color=BLU, lw=1.0)
    ax.set_xlabel("偏置相位 $\\varphi$ (rad)"); ax.set_ylabel("PD 直流 (V)")
    ax.set_title("(b) 直流–相位曲线", fontsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp0.pdf"))
    plt.close(fig); print("[fig] fig_exp0.pdf")


def fig_pilot(data, out):
    """fig:expkappa — kappa(A) vs pilot depth m, overlaid with the Bessel-ratio
    trend J1(m)/J2(m)."""
    p = os.path.join(data, "pilot_depth.csv")
    if not os.path.exists(p):
        print("[skip] fig_expkappa: pilot_depth.csv not found"); return
    from scipy.special import jv
    rows = _read_csv(p)
    m = np.array([float(r["m"]) for r in rows])
    kap = np.array([float(r["kappa"]) for r in rows])
    order = np.argsort(m); m = m[order]; kap = kap[order]
    fig, ax = plt.subplots(figsize=(CW, 2.1))
    mm = np.linspace(max(0.02, m.min() * 0.8), m.max() * 1.12, 300)
    ax.plot(mm, np.abs(jv(1, mm) / jv(2, mm)), color=BLU, lw=1.1,
            label="$J_1(m)/J_2(m)$（理想）")
    ax.plot(m, kap, "o-", color=GRN, ms=4, lw=0.8, label="实测 $\\kappa(\\hat A)$")
    ax.set_yscale("log"); ax.set_xlabel("导频深度 $m=\\pi A_p/V_\\pi$")
    ax.set_ylabel("$\\kappa(\\hat A)$")
    ax.legend(fontsize=6.5, loc="best"); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_expkappa.pdf"))
    plt.close(fig); print("[fig] fig_expkappa.pdf")


def fig_calib(data, out):
    npz = os.path.join(data, "calib.npz"); fjs = os.path.join(data, "calib_fit.json")
    if not (os.path.exists(npz) and os.path.exists(fjs)):
        print("[skip] fig_exp1: calib.npz / calib_fit.json not found"); return
    d = np.load(npz, allow_pickle=True)
    with open(fjs) as f:
        fit = json.load(f)
    X, Y = d["X"], d["Y"]; c0 = np.array(fit["c0"]); B = np.array(fit["B"])
    cal = {"c0": c0, "B": B}
    us = (B @ np.stack([X - c0[0], Y - c0[1]])).T
    A_hat = np.linalg.inv(B)
    fig, axs = plt.subplots(1, 2, figsize=(CW, 2.05))
    ax = axs[0]
    ax.plot(X, Y, ".", ms=1.5, color="0.45")
    t = np.linspace(0, 2 * np.pi, 300)
    ell = (A_hat @ np.stack([np.cos(t), np.sin(t)])) + c0[:, None]
    ax.plot(ell[0], ell[1], color=BLU, lw=1.1)
    ax.plot(*c0, "+", color=BLU, ms=7, mew=1.3)
    ax.annotate("$\\hat{\\mathbf{b}}$", c0, textcoords="offset points",
                xytext=(4, -10), fontsize=7, color=BLU)
    ax.set_xlabel("$X$ (H2)"); ax.set_ylabel("$Y$ (H1)")
    ax.set_title("(a) 实测观测平面", fontsize=7.5)
    ax.ticklabel_format(axis="x", style="sci", scilimits=(-2, 2))
    ax.margins(x=0.22, y=0.12)
    ax = axs[1]
    ax.plot(us[:, 0], us[:, 1], ".", ms=1.5, color=GRN)
    ax.add_patch(Circle((0, 0), 1, fill=False, ec=INK, lw=0.8, ls="--"))
    ax.set_xlabel("$\\hat u_x$"); ax.set_ylabel("$\\hat u_y$")
    ax.set_title(f"(b) 回拉单位圆  $\\kappa(\\hat A){{=}}{fit['kappa']:.2f}$",
                 fontsize=7.5)
    ax.set_aspect("equal"); ax.margins(0.22)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp1.pdf"))
    plt.close(fig); print("[fig] fig_exp1.pdf")


def fig_lock(data, out):
    npz = os.path.join(data, "lock_sweep.npz")
    if not os.path.exists(npz):
        print("[skip] fig_exp2: lock_sweep.npz not found"); return
    d = np.load(npz)
    ps = d["phi_star"]; aff = np.abs(d["affine_err"]) * 1e3
    base = np.abs(d["baseline_err"]) * 1e3
    fig, ax = plt.subplots(figsize=(CW, 2.1))
    ax.semilogy(ps, base, "s-", color=RED, ms=3, label="H1 幅值匹配 (基线)")
    ax.semilogy(ps, np.maximum(aff, 1e-1), "o-", color=GRN, ms=3, label="仿射")
    ax.set_xlabel("目标相位 $\\varphi^\\ast$ (rad)")
    ax.set_ylabel("$|\\varphi_{\\rm lock}-\\varphi^\\ast|$ (mrad)")
    ax.legend(loc="best"); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp2.pdf"))
    plt.close(fig); print("[fig] fig_exp2.pdf")


def _panel_stability(ax1, sp):
    d = np.load(sp)
    th = d["t"] / 3600.0; V = d["V"]
    dt = d["dmm_t"] / 3600.0; de = np.abs(d["dmm_err_mrad"])
    rec = int(d["recal_events"]); hrs = float(d["t"][-1]) / 3600
    vdrift = float(V.max() - V.min())
    ax1.plot(th, V, color=BLU, lw=0.8)
    ax1.set_ylabel("偏置 $V_b$ (V)", color=BLU); ax1.set_xlabel("时间 (h)")
    ax1.set_title(f"(a) 长期稳定性 ${hrs:.1f}$ h：偏置跟踪 ${vdrift:.2f}$ V 漂移，"
                  f"重定标 ${rec}$ 次", fontsize=7.0)
    ax2 = ax1.twinx()
    ax2.plot(dt, de, "o", color=GRN, ms=2.5)
    ax2.set_ylabel("锁定误差 (mrad)", color=GRN)
    ax2.set_ylim(0, max(800.0, float(de.max()) * 1.25))


def _panel_drift(ax1, dp):
    d = np.load(dp)
    err = np.abs(d["err_mrad"]); rho = d["rho_bar"]
    step = int(d["step_at"]); lat = int(d["latency"])
    recal = int(d["recal_at"]) if "recal_at" in d.files else (
        step + lat if lat >= 0 else -1)
    ax1.plot(err, color=GRN, lw=0.9)
    ax1.set_xlabel("控制周期"); ax1.set_ylabel("误差 (mrad)", color=GRN)
    ax1.axvline(step, color=RED, ls="--", lw=0.8)
    ax1.text(step, ax1.get_ylim()[1] * 0.9, " 突变", color=RED, fontsize=6)
    if recal >= 0:
        ax1.axvline(recal, color=GLD, ls=":", lw=0.9)
        ax1.text(recal, ax1.get_ylim()[1] * 0.55,
                 f" 检测+{lat}\n →重定标", color=GLD, fontsize=6)
    ax1.set_title("(b) 残差触发检测与恢复重定标", fontsize=7.5)
    ax2 = ax1.twinx()
    ax2.plot(rho, color=BLU, lw=0.8, alpha=0.7)
    ax2.set_ylabel("残差 $\\bar\\rho$", color=BLU)


def fig_drift(data, out):
    """fig:exp3 — (a) 3 h long-term stability + (b) residual-triggered detection.
    Either panel is drawn only if its data exists; missing -> skipped."""
    sp = os.path.join(data, "stability.npz"); dp = os.path.join(data, "drift.npz")
    has_s, has_d = os.path.exists(sp), os.path.exists(dp)
    if not (has_s or has_d):
        print("[skip] fig_exp3: stability.npz / drift.npz not found"); return
    nrows = int(has_s) + int(has_d)
    fig, axs = plt.subplots(nrows, 1, figsize=(CW, 1.95 * nrows), squeeze=False)
    r = 0
    if has_s:
        _panel_stability(axs[r, 0], sp); r += 1
    if has_d:
        _panel_drift(axs[r, 0], dp)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp3.pdf"))
    plt.close(fig); print("[fig] fig_exp3.pdf")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=ec.DATA)
    ap.add_argument("--out-dir", default=os.path.join(ec.REPO, "figs"))
    ap.add_argument("--no-schematics", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if not a.no_schematics:
        fig_setup_mzm(a.out_dir)
        fig_setup_dpmzm(a.out_dir)
    fig_vpi(a.data_dir, a.out_dir)
    fig_calib(a.data_dir, a.out_dir)
    fig_lock(a.data_dir, a.out_dir)
    fig_pilot(a.data_dir, a.out_dir)
    fig_drift(a.data_dir, a.out_dir)


if __name__ == "__main__":
    main()
