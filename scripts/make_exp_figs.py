#!/usr/bin/env python3
"""Render the EXPERIMENTAL figures from recorded bench data.

  fig_exp_mzm.pdf    complete single-MZM bench platform (data-free, always)
  fig_exp_dpmzm.pdf  DPMZM bench schematic         (data-free, always)
  fig_exp1.pdf       calibration ellipse + circle  (needs calib.npz/_fit.json)
  fig_exp2.pdf       lock rms vs phi*: affine/H1   (needs lock_sweep.npz)
  fig_exp3.pdf       drift + recal record          (needs drift.npz)
  fig_exprepeat_mzm.pdf static acquisition repeatability
                                                   (needs frozen v1.2 analysis)

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
from matplotlib.patches import (Rectangle, Circle, FancyBboxPatch,  # noqa: E402
                                Ellipse, Polygon, PathPatch)
from matplotlib.path import Path             # noqa: E402
from matplotlib.lines import Line2D          # noqa: E402

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
# log-tick labels are wrapped in \mathdefault, whose minus sign is looked up in
# the first serif font (FandolSong has no U+2212 -> tofu); route them through
# \mathrm so the CM math fonts supply the glyph. Formatting only, no data effect.
import matplotlib.ticker as _mticker
_lfsn_call = _mticker.LogFormatterSciNotation.__call__
def _lfsn_fix(self, x, pos=None):
    return _lfsn_call(self, x, pos).replace(r'\mathdefault', r'\mathrm')
_mticker.LogFormatterSciNotation.__call__ = _lfsn_fix
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
#  data-free schematics                                                        #
# --------------------------------------------------------------------------- #
#  Skeuomorphic icon primitives (matplotlib patches only, deterministic).      #
#  Each draws inside an axis-data cell centred at (cx, cy) with half-size s;    #
#  a rounded "chip" frame is drawn by _chip, the icon glyph on top.            #
OPT = "#2C7FB8"          # optical path: journal-style blue
ELEC = "#D95F02"         # analog receive chain: orange
CTRL = "#6A51A3"         # digital control and bias feedback: purple
CIRC = INK


def _chip(ax, cx, cy, w, h, fc="#F5F8F4", ec=INK, lw=0.8, r=0.10):
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0,rounding_size={r}",
        fc=fc, ec=ec, lw=lw, mutation_aspect=1.0, zorder=2))


def _label(ax, cx, cy, t, fs=5.4, color=INK, va="center"):
    ax.text(cx, cy, t, ha="center", va=va, fontsize=fs, color=color, zorder=5)


def _ic_laser(ax, cx, cy, s=0.30, color=CIRC):
    """Laser diode: triangle + bar (diode) with slanted emission arrows."""
    ax.add_patch(Polygon([(cx - s, cy - s * 0.7), (cx - s, cy + s * 0.7),
                          (cx + s * 0.1, cy)], closed=True, fc="none",
                         ec=color, lw=0.9, zorder=4))
    ax.plot([cx + s * 0.1, cx + s * 0.1], [cy - s * 0.7, cy + s * 0.7],
            color=color, lw=0.9, zorder=4)
    for dy in (0.35, -0.05):
        ax.annotate("", xy=(cx + s * 0.95, cy + s * (dy + 0.35)),
                    xytext=(cx + s * 0.35, cy + s * (dy - 0.05)),
                    arrowprops=dict(arrowstyle="->", lw=0.7, color=color),
                    zorder=4)


def _ic_pd(ax, cx, cy, s=0.30, color=CIRC):
    """Photodiode: triangle + bar with two incoming (received-light) arrows."""
    ax.add_patch(Polygon([(cx + s, cy - s * 0.7), (cx + s, cy + s * 0.7),
                          (cx - s * 0.1, cy)], closed=True, fc="none",
                         ec=color, lw=0.9, zorder=4))
    ax.plot([cx - s * 0.1, cx - s * 0.1], [cy - s * 0.7, cy + s * 0.7],
            color=color, lw=0.9, zorder=4)
    for dy in (0.4, -0.1):
        ax.annotate("", xy=(cx - s * 0.15, cy + s * (dy - 0.1)),
                    xytext=(cx - s * 0.95, cy + s * (dy + 0.4)),
                    arrowprops=dict(arrowstyle="->", lw=0.7, color=OPT),
                    zorder=4)


def _ic_opamp(ax, cx, cy, s=0.32, color=CIRC):
    """Operational amplifier: right-pointing triangle with +/- inputs."""
    ax.add_patch(Polygon([(cx - s, cy - s), (cx - s, cy + s), (cx + s, cy)],
                         closed=True, fc="none", ec=color, lw=0.9, zorder=4))
    ax.text(cx - s * 0.55, cy + s * 0.42, "$-$", ha="center", va="center",
            fontsize=5.0, color=color, zorder=5)
    ax.text(cx - s * 0.55, cy - s * 0.42, "$+$", ha="center", va="center",
            fontsize=5.0, color=color, zorder=5)


def _ic_lpf(ax, cx, cy, s=0.32, color=CIRC):
    """Low-pass response glyph: flat plateau then roll-off."""
    xr = np.linspace(0, 1, 60)
    yy = cy + s * (0.9 / (1 + (xr / 0.5) ** 6) - 0.45)
    ax.plot(cx - s + 2 * s * xr, yy, color=color, lw=0.9, zorder=4)


def _ic_hpf(ax, cx, cy, s=0.32, color=CIRC):
    """High-pass response glyph: rise then flat plateau."""
    xr = np.linspace(0, 1, 60)
    yy = cy + s * (0.9 * (xr ** 6 / (xr ** 6 + 0.5 ** 6)) - 0.45)
    ax.plot(cx - s + 2 * s * xr, yy, color=color, lw=0.9, zorder=4)


def _ic_cap(ax, cx, cy, s=0.30, color=CIRC):
    """DC-block capacitor: two parallel plates with leads."""
    g = s * 0.28
    ax.plot([cx - g, cx - g], [cy - s * 0.75, cy + s * 0.75], color=color,
            lw=1.1, zorder=4)
    ax.plot([cx + g, cx + g], [cy - s * 0.75, cy + s * 0.75], color=color,
            lw=1.1, zorder=4)
    ax.plot([cx - s, cx - g], [cy, cy], color=color, lw=0.8, zorder=4)
    ax.plot([cx + g, cx + s], [cy, cy], color=color, lw=0.8, zorder=4)


def _ic_adc(ax, cx, cy, s=0.30, color=CTRL):
    """ADC: sampled staircase, readable at IEEE single-column scale."""
    xx = np.array([-1.0, -0.55, -0.55, 0.0, 0.0, 0.55, 0.55, 1.0]) * s
    yy = np.array([-0.60, -0.60, -0.15, -0.15, 0.25, 0.25, 0.60, 0.60]) * s
    ax.plot(cx + xx, cy + yy, color=color, lw=0.9, zorder=4)


def _ic_mcu(ax, cx, cy, s=0.30, color=CTRL):
    """Processor: compact IC body and pins."""
    ax.add_patch(Rectangle((cx - 0.65*s, cy - 0.55*s), 1.3*s, 1.1*s,
                           fill=False, ec=color, lw=0.9, zorder=4))
    for u in (-0.38, 0.0, 0.38):
        ax.plot([cx + u*s, cx + u*s], [cy + 0.55*s, cy + 0.82*s],
                color=color, lw=0.7, zorder=4)
        ax.plot([cx + u*s, cx + u*s], [cy - 0.55*s, cy - 0.82*s],
                color=color, lw=0.7, zorder=4)


def _ic_dac(ax, cx, cy, s=0.30, color=CTRL):
    """DAC: smooth reconstruction curve following digital samples."""
    x = np.linspace(-1, 1, 60)
    ax.plot(cx + s*x, cy + 0.55*s*np.sin(0.9*np.pi*x),
            color=color, lw=0.9, zorder=4)


def _ic_coupler(ax, cx, cy, s=0.30, color=OPT):
    """One-input/two-output optical splitter: lead, ring, and fork."""
    r = 0.34 * s
    ax.plot([cx - 1.10*s, cx - r], [cy, cy], color=color, lw=0.9, zorder=4)
    ax.add_patch(Circle((cx, cy), r, fill=False, ec=color, lw=0.9, zorder=4))
    ax.plot([cx + r, cx + 1.08*s], [cy + 0.10*s, cy + 0.62*s],
            color=color, lw=0.9, zorder=4)
    ax.plot([cx + r, cx + 1.08*s], [cy - 0.10*s, cy - 0.62*s],
            color=color, lw=0.9, zorder=4)


def _ic_mzm(ax, cx, cy, s=0.34, color=OPT):
    """Mach–Zehnder waveguide: split into two arms and recombine."""
    x = np.array([-1.0, -0.55, 0.0, 0.55, 1.0]) * s
    yt = np.array([0.0, 0.55, 0.55, 0.55, 0.0]) * s
    yb = np.array([0.0, -0.55, -0.55, -0.55, 0.0]) * s
    ax.plot(cx + x, cy + yt, color=color, lw=0.9, zorder=4)
    ax.plot(cx + x, cy + yb, color=color, lw=0.9, zorder=4)
    ax.plot([cx - s, cx - 1.35 * s], [cy, cy], color=color, lw=0.9, zorder=4)
    ax.plot([cx + s, cx + 1.35 * s], [cy, cy], color=color, lw=0.9, zorder=4)
    # bias electrode over the lower arm
    ax.plot([cx - 0.55 * s, cx + 0.55 * s], [cy - 0.78 * s, cy - 0.78 * s],
            color=CIRC, lw=1.2, zorder=4)


def _ic_pc(ax, cx, cy, s=0.30, color=CTRL):
    """PC/upper-computer monitor with a small terminal trace."""
    ax.add_patch(Rectangle((cx - s, cy - 0.60*s), 2*s, 1.25*s,
                           fill=False, ec=color, lw=0.9, zorder=4))
    ax.plot([cx - 0.70*s, cx - 0.15*s, cx + 0.10*s, cx + 0.65*s],
            [cy - 0.10*s, cy + 0.20*s, cy - 0.02*s, cy + 0.30*s],
            color=color, lw=0.8, zorder=4)
    ax.plot([cx, cx], [cy - 0.60*s, cy - 0.88*s], color=color, lw=0.8, zorder=4)
    ax.plot([cx - 0.55*s, cx + 0.55*s], [cy - 0.88*s, cy - 0.88*s],
            color=color, lw=0.8, zorder=4)


def _ic_dmm(ax, cx, cy, s=0.30, color=CIRC):
    """Bench DMM: display plus two input terminals."""
    ax.add_patch(Rectangle((cx - s, cy - 0.65*s), 2*s, 1.30*s,
                           fill=False, ec=color, lw=0.85, zorder=4))
    ax.text(cx, cy + 0.15*s, "V", ha="center", va="center",
            fontsize=5.2, color=color, zorder=5)
    for dx in (-0.42, 0.42):
        ax.add_patch(Circle((cx + dx*s, cy - 0.38*s), 0.12*s,
                            fill=False, ec=color, lw=0.75, zorder=4))


def _ic_scope(ax, cx, cy, s=0.30, color=CIRC):
    """Oscilloscope screen with a sinusoidal trace."""
    ax.add_patch(Rectangle((cx - s, cy - 0.62*s), 2*s, 1.24*s,
                           fill=False, ec=color, lw=0.85, zorder=4))
    x = np.linspace(-0.82, 0.82, 80)
    ax.plot(cx + s*x, cy + 0.28*s*np.sin(3*np.pi*x),
            color=color, lw=0.8, zorder=4)


def _ic_siggen(ax, cx, cy, s=0.30, color=CIRC):
    """Signal generator with sine-wave display and output terminal."""
    ax.add_patch(Rectangle((cx - s, cy - 0.62*s), 2*s, 1.24*s,
                           fill=False, ec=color, lw=0.85, zorder=4))
    x = np.linspace(-0.78, 0.48, 70)
    ax.plot(cx + s*x, cy + 0.25*s*np.sin(2.5*np.pi*x),
            color=color, lw=0.8, zorder=4)
    ax.add_patch(Circle((cx + 0.72*s, cy - 0.30*s), 0.12*s,
                        fill=False, ec=color, lw=0.75, zorder=4))


def _ic_specan(ax, cx, cy, s=0.30, color=CIRC):
    """Spectrum analyzer screen with a dominant RF tone."""
    ax.add_patch(Rectangle((cx - s, cy - 0.62*s), 2*s, 1.24*s,
                           fill=False, ec=color, lw=0.85, zorder=4))
    xx = np.array([-0.82, -0.48, -0.25, 0.00, 0.18, 0.42, 0.78]) * s
    yy = np.array([-0.38, -0.30, -0.18, 0.46, -0.16, -0.28, -0.35]) * s
    ax.plot(cx + xx, cy + yy, color=color, lw=0.8, zorder=4)


def _ic_pp10g(ax, cx, cy, s=0.30, color=CIRC):
    """PP-10G optical receiver: PIN detector followed by a TIA/preamp."""
    ax.add_patch(Polygon([[cx - 0.88*s, cy + 0.52*s],
                          [cx - 0.88*s, cy - 0.52*s],
                          [cx - 0.12*s, cy]],
                         closed=True, fill=False, ec=color, lw=0.85, zorder=4))
    ax.plot([cx - 0.02*s, cx - 0.02*s],
            [cy - 0.58*s, cy + 0.58*s], color=color, lw=0.9, zorder=4)
    ax.add_patch(Polygon([[cx + 0.18*s, cy - 0.56*s],
                          [cx + 0.18*s, cy + 0.56*s],
                          [cx + 0.92*s, cy]],
                         closed=True, fill=False, ec=color, lw=0.85, zorder=4))


def fig_setup_mzm(out):
    """Complete measured single-MZM platform, including auxiliary instruments.

    The solid paths are the physical optical/electrical loop used in every lock
    run.  The PC is in the realised feedback loop: STM32 supplies Goertzel H1/H2
    over USB serial, while the PC performs affine inversion and integral control
    before returning the next bias command.  The DMM is the independent DC
    truth branch.  In the RF-load stage the DG922 Pro drives the MZM RF port,
    while the 90% optical output is detected by a PP-10G receiver and measured
    by the FSV30; the analyzer is not an electrical tap on the generator output.
    """
    fig, ax = plt.subplots(figsize=(TW, 3.55))
    ax.set_xlim(0, 18); ax.set_ylim(0, 8.75); ax.axis("off")
    ax.set_aspect("equal")
    yT, yM = 7.35, 4.60
    RF, AUX = "#B23A2B", "#6B7280"

    def cell(cx, cy, w, h, glyph, lab, fc="#F5F8F4", fs=6.2):
        _chip(ax, cx, cy, w, h, fc=fc)
        if glyph is not None:
            glyph(ax, cx, cy + h * 0.21)
            _label(ax, cx, cy - h * 0.25, lab, fs=fs)
        else:
            _label(ax, cx, cy, lab, fs=fs)

    def path_arrow(points, color, lw=1.15, ls="-", arrow=True, z=3):
        xx, yy = zip(*points)
        ax.plot(xx, yy, color=color, lw=lw, ls=ls, zorder=z,
                solid_capstyle="round", solid_joinstyle="round")
        if arrow:
            ax.annotate("", xy=points[-1], xytext=points[-2],
                        arrowprops=dict(arrowstyle="-|>", lw=lw, color=color,
                                        ls=ls, shrinkA=0, shrinkB=0), zorder=z+0.1)

    # The layout uses three strict alignment bands: optical plant, receiver /
    # controller, and auxiliary instruments.  Every external connection ends at
    # a box boundary and uses its own orthogonal routing channel.
    # ---- optical plant ------------------------------------------------------
    cell(1.00, yT, 1.55, 1.45, _ic_laser, "DFB 激光器\n1550 nm, 9 dBm",
         fc="#EAF4FA", fs=5.8)
    cell(3.55, yT, 1.85, 1.45, _ic_mzm, "MZM\n$V_\\pi{=}5.28$ V",
         fc="#EAF4FA", fs=6.0)
    cell(5.95, yT, 1.50, 1.45, _ic_coupler, "1:9 光耦",
         fc="#EAF4FA", fs=6.0)
    path_arrow([(1.78, yT), (2.62, yT)], OPT)
    path_arrow([(4.48, yT), (5.20, yT)], OPT)
    cell(8.65, yT, 1.90, 1.45, _ic_pp10g,
         "光电接收机\nPIN + 前置 TIA", fc="#FAECE9", fs=5.5)
    cell(11.25, yT, 1.95, 1.45, _ic_specan,
         "频谱分析\n输出 RF 频谱", fc="#FAECE9", fs=5.5)
    path_arrow([(6.70, yT + 0.18), (7.18, yT + 0.18),
                (7.18, yT), (7.70, yT)], OPT)
    ax.text(7.22, yT + 0.48, "90% 光口", fontsize=6.0,
            color=OPT, ha="center")
    path_arrow([(9.60, yT), (10.28, yT)], RF, lw=1.05)
    ax.text(9.94, yT + 0.31, r"50 $\Omega$ SMA", fontsize=5.5,
            color=RF, ha="center")

    # 10% monitor branch and realised analog receive path.
    # ---- self-developed controller board: receive, control, and drive ------
    ax.add_patch(FancyBboxPatch((6.05, 1.65), 8.45, 4.45,
                               boxstyle="round,pad=0.05,rounding_size=0.12",
                               fc="#F7F7FC", ec=CTRL, lw=0.9, ls="--", zorder=1))
    ax.text(10.28, 5.84, "自研偏压控制板", ha="center", va="center",
            fontsize=6.3, color=CTRL, zorder=5)

    cell(6.80, yM, 1.20, 1.35, _ic_pd, "PD", fc="#FFF1E8", fs=6.0)
    cell(8.25, yM, 1.10, 1.35, _ic_cap, "隔直", fc="#FFF1E8", fs=5.8)
    cell(9.60, yM, 1.10, 1.35, _ic_opamp, "TIA", fc="#FFF1E8", fs=5.8)
    path_arrow([(6.70, yT - 0.18), (6.80, yT - 0.18),
                (6.80, yM + 0.68)], OPT)
    ax.text(6.55, 6.33, "10% 监测端", fontsize=5.9, color=OPT,
            rotation=90, ha="center", va="center")
    path_arrow([(7.40, yM), (7.70, yM)], ELEC, lw=1.1)
    path_arrow([(8.80, yM), (9.05, yM)], ELEC, lw=1.1)

    cell(10.95, yM, 1.10, 1.30, _ic_adc, "ADC\n64 kSPS",
         fc="#EEF0FA", fs=5.5)
    cell(13.15, yM, 1.95, 1.40, _ic_mcu, "偏压控制器\nGoertzel / 串口接口",
         fc="#EEF0FA", fs=5.5)
    cell(12.95, 2.55, 1.90, 1.45, _ic_dac, "多通道 DAC\n偏压驱动",
         fc="#EEF0FA", fs=5.5)
    path_arrow([(10.15, yM), (10.40, yM)], ELEC, lw=1.1)
    path_arrow([(11.50, yM), (12.18, yM)], CTRL, lw=1.15)
    path_arrow([(13.15, 3.90), (13.15, 3.38),
                (12.95, 3.38), (12.95, 3.28)], CTRL, lw=1.15)

    # The PC is part of the realised feedback loop, not merely a logger.
    cell(16.45, yM, 2.35, 1.55, _ic_pc,
         "PC 上位机\natan2 仿射反演 + 积分",
         fc="#F1ECFA", fs=5.3)
    ax.annotate("", xy=(15.28, yM), xytext=(14.13, yM),
                arrowprops=dict(arrowstyle="<->", lw=1.25, color=CTRL), zorder=4)
    ax.text(14.70, yM + 0.32, "USB 串口", fontsize=5.4, color=CTRL,
            ha="center", bbox=dict(fc="white", ec="none", pad=0.35), zorder=6)

    # DAC bias + pilot uses the empty lane between the DMM and board, then
    # enters the MZM at a separate bias port.  It never crosses another box.
    path_arrow([(12.00, 2.55), (11.65, 2.55), (11.65, 1.30),
                (5.72, 1.30), (5.72, 6.35), (3.95, 6.35),
                (3.95, yT - 0.73)], CTRL, lw=1.2)
    ax.text(8.70, 1.05, "$V_b+m\\sin(\\omega t)$（偏置口）", fontsize=5.9,
            color=CTRL, ha="center", va="center")

    # ---- diagnostic/truth branches ----------------------------------------
    cell(4.35, yM, 2.10, 1.45, _ic_dmm, "独立直流观测\n相位标签/评价",
         fc="#F7F3E8", fs=5.4)
    path_arrow([(6.20, yM), (5.40, yM)], AUX, lw=1.0, ls="--")
    # ---- RF-load-only branch ----------------------------------------------
    cell(1.25, yM, 2.05, 1.35, _ic_siggen,
         "RF 信号源\n50 MHz 单音", fc="#FAECE9", fs=5.5)
    path_arrow([(2.28, yM), (3.15, yM), (3.15, yT - 0.73)], RF, lw=1.05)
    ax.text(2.88, 5.55, "仅 RF 加载试验", fontsize=5.5, color=RF,
            rotation=90, ha="center", va="center")
    ax.text(3.02, 6.28, "RF 口", fontsize=5.2, color=RF,
            ha="right", va="center")

    # PC-orchestrated auxiliary acquisition runs only in the bottom margin;
    # vertical drops are outside the bias-feedback routing channel.
    bus_y = 0.42
    ax.plot([1.25, 16.45], [bus_y, bus_y], color=AUX, lw=0.8,
            ls=(0, (2, 2)), zorder=1)
    aux_routes = [
        [(1.25, bus_y), (1.25, yM - 0.68)],
        [(4.35, bus_y), (4.35, yM - 0.73)],
        [(16.45, bus_y), (16.45, yM - 0.78)],
    ]
    for pts in aux_routes:
        xx, yy = zip(*pts)
        ax.plot(xx, yy, color=AUX, lw=0.8, ls=(0, (2, 2)), zorder=1)
    # FSV30 is controlled by the PC but its RF input comes only from PP-10G.
    ax.plot([12.23, 17.55, 17.55, 17.00, 17.00],
            [7.98, 7.98, 5.72, 5.72, yM + 0.78], color=AUX, lw=0.8,
            ls=(0, (2, 2)), zorder=1)
    ax.text(8.85, 0.15, "PC 仪器控制与数据记录（USB/LAN）", fontsize=5.5,
            color=AUX, ha="center")

    handles = [Line2D([0], [0], color=OPT, lw=1.2, label="光路"),
               Line2D([0], [0], color=ELEC, lw=1.1, label="模拟接收"),
               Line2D([0], [0], color=CTRL, lw=1.1, label="实时数字控制"),
               Line2D([0], [0], color=AUX, lw=1.0, ls="--", label="诊断/仪器通信"),
               Line2D([0], [0], color=RF, lw=1.0, label="RF激励/检测")]
    ax.legend(handles=handles, loc="upper right", ncol=5, frameon=False,
              fontsize=5.2, bbox_to_anchor=(0.995, 0.995), handlelength=1.45,
              columnspacing=0.9, handletextpad=0.35)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    fig.savefig(os.path.join(out, "fig_exp_mzm.pdf"))
    plt.close(fig); print("[fig] fig_exp_mzm.pdf")


def fig_setup_dpmzm(out):
    fig, ax = plt.subplots(figsize=(TW, 2.2)); ax.set_xlim(0, 16)
    ax.set_ylim(0, 4.6); ax.axis("off")
    ax.text(0.1, 4.3, "（实测链路）", fontsize=7, color="0.4")
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
    pullback = "相位标签回归回拉" if fit.get("method") == "phase-ref" else "椭圆--直流规范回拉"
    ax.set_title(f"(b) {pullback}", fontsize=7.5)
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
    ax1.plot(th, V, color=INK, lw=0.8, alpha=0.85)
    ax1.set_ylabel("偏置 $V_b$ (V)", color=INK); ax1.set_xlabel("时间 (h)")
    ax1.set_title(f"(a) 长期稳定性（${hrs:.1f}$ h，偏置漂移 ${vdrift:.2f}$ V，"
                  f"重定标 ${rec}$ 次）", fontsize=7.5)
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
    ax1.axvline(step, color=RED, ls="--", lw=0.9)
    ax1.text(step, ax1.get_ylim()[1] * 0.9, " 突变", color=RED, fontsize=6)
    if recal >= 0:
        ax1.axvline(recal, color=BLU, ls=":", lw=0.9)
        ax1.text(recal, ax1.get_ylim()[1] * 0.55,
                 f" 检测+{lat}\n →重定标", color=BLU, fontsize=6)
    ax1.set_title("(b) 残差触发检测与恢复", fontsize=7.5)
    ax2 = ax1.twinx()
    ax2.plot(rho, color=INK, lw=1.0, alpha=0.85)
    ax2.set_ylabel("残差 $\\bar\\rho$", color=INK)


def fig_drift(data, out):
    """fig:exp3 — (a) 3 h long-term stability + (b) residual-triggered detection.
    Either panel is drawn only if its data exists; missing -> skipped."""
    sp = os.path.join(data, "stability.npz"); dp = os.path.join(data, "drift.npz")
    has_s, has_d = os.path.exists(sp), os.path.exists(dp)
    if not (has_s or has_d):
        print("[skip] fig_exp3: stability.npz / drift.npz not found"); return
    # wide stacked layout (matches fig_recal): both panels have a long x-axis
    # (hours / control cycles), so give each the full width and flatten it.
    nrows = int(has_s) + int(has_d)
    fig, axs = plt.subplots(nrows, 1, figsize=(2 * CW, 1.5 * nrows), squeeze=False)
    r = 0
    if has_s:
        _panel_stability(axs[r, 0], sp); r += 1
    if has_d:
        _panel_drift(axs[r, 0], dp)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp3.pdf"))
    plt.close(fig); print("[fig] fig_exp3.pdf")


def _vpk_from_dbm(dbm, load=50.0):
    """Sine power dBm (into load) -> peak volts."""
    return np.sqrt(2.0) * np.sqrt(1e-3 * 10 ** (dbm / 10.0) * load)


def fig_rf(data, out):
    """fig:exprf — RF-loaded lock robustness (stage 5).
    (a) H1 harmonic fade vs effective RF depth, overlaid with the predicted
        J0(m_RF) (effective RF Vpi fitted from the fade, since it is below the DC
        Vpi); (b) arbitrary-point lock rms vs applied RF power, RF-off reference.
    Skipped if rf_lock.npz is absent."""
    npz = os.path.join(data, "rf_lock.npz")
    if not os.path.exists(npz):
        print("[skip] fig_exprf: rf_lock.npz not found"); return
    from scipy.special import j0 as bessel_j0
    from scipy.optimize import curve_fit
    d = np.load(npz)
    powers = d["powers_dbm"]; rms = d["rms_mrad"]
    h1 = d["h1"]; fade = d["h1_fade"] if "h1_fade" in d.files else h1 / h1[0]
    off = ~np.isfinite(powers); on = np.isfinite(powers)
    vpk = _vpk_from_dbm(powers[on])
    fade_on = fade[on]
    # fit the EFFECTIVE 50 MHz Vpi from the measured fade: fade = J0(pi*Vpk/Vpi)
    try:
        vpi_rf = float(curve_fit(lambda v, vp: bessel_j0(np.pi * v / vp),
                                 vpk, fade_on, p0=[3.0], maxfev=20000)[0][0])
    except Exception:
        vpi_rf = 2.8
    m_eff = np.pi * vpk / vpi_rf
    fig, axs = plt.subplots(1, 2, figsize=(TW * 0.66, 2.1))
    # (a) harmonic fade vs effective m_RF, with the J0 prediction
    ax = axs[0]
    mm = np.linspace(0, float(m_eff.max()) * 1.12 + 1e-3, 200)
    ax.plot(mm, bessel_j0(mm), color=BLU, lw=1.1, label="$J_0(m_{\\rm RF})$（预测）")
    ax.plot(m_eff, fade_on, "o", color=GRN, ms=4, label="实测 H1 衰落")
    ax.set_xlabel("RF 调制深度 $m_{\\rm RF}=\\pi V_{\\rm pk}/V_\\pi^{\\rm RF}$")
    ax.set_ylabel("H1 相对幅度")
    ax.set_title(f"(a) 谐波随 RF 的 $J_0$ 衰落（$V_\\pi^{{\\rm RF}}{{\\approx}}"
                 f"{vpi_rf:.1f}$ V）", fontsize=7.0)
    ax.legend(fontsize=6.3, loc="lower left"); ax.grid(True, alpha=0.25)
    ax.set_ylim(top=1.04, bottom=0)
    # (b) lock rms vs applied RF power, RF-off baseline as a dashed line
    ax = axs[1]
    order = np.argsort(powers[on])
    ax.plot(powers[on][order], rms[on][order], "o-", color=GRN, ms=4,
            label="仿射锁定 (RF 开)")
    if np.any(off):
        rms_off = float(np.mean(rms[off]))
        ax.axhline(rms_off, color=RED, ls="--", lw=1.0,
                   label=f"RF 关参考 ({rms_off:.0f} mrad)")
    ax.set_xlabel("施加 RF 功率 (dBm)")
    ax.set_ylabel("锁定 RMS (mrad)")
    ax.set_title("(b) 任意点锁定 RMS vs RF 功率", fontsize=7.5)
    ax.legend(fontsize=6.3, loc="best"); ax.grid(True, alpha=0.25)
    ax.set_ylim(bottom=0)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exprf.pdf"))
    plt.close(fig); print("[fig] fig_exprf.pdf")


CH_LABELS = ["$Y_1$", "$X_1$", "$Y_2$", "$X_2$", "$Y_3$", "$X_3$",
             "$Z_-$", "$Z_{13}$", "$Z_{23}$"]
FEAT_LABELS = ["$c\\varphi_1$", "$s\\varphi_1$", "$c\\varphi_2$", "$s\\varphi_2$",
               "$ccC$", "$ccS$", "$csC$", "$csS$", "$scC$", "$scS$", "$ssC$", "$ssS$"]


def fig_dp_torus(data, out):
    """fig:exp6 — (a) sub-axis-1 sweep over 4*Vpi showing phi vs phi+2pi
    distinguishability (half-angle / 4*pi period); (b) identified A_hat heatmap
    over the ideal sparse fingerprint A0.  Cross-refs fig:torus / fig:ahat."""
    vp = os.path.join(data, "dp_vpi.npz"); cp = os.path.join(data, "dp_calib.npz")
    if not (os.path.exists(vp) or os.path.exists(cp)):
        print("[skip] fig_exp6: dp_vpi.npz / dp_calib.npz not found"); return
    ncol = int(os.path.exists(vp)) + int(os.path.exists(cp))
    fig, axs = plt.subplots(1, ncol, figsize=(ncol * CW, 2.2), squeeze=False)
    c = 0
    if os.path.exists(vp):
        d = np.load(vp); fb = d["fine_bias"]; fd = d["fine_dc"]
        axidx = int(d["fine_axis"]) if "fine_axis" in d.files else 0
        vpi0 = float(d["vpi"][axidx]); v00 = float(d["v0"][axidx])
        cr = float(d["contrast_rel"])
        th = np.pi * (fb - v00) / vpi0            # selected sub-axis phase in rad
        ax = axs[0, c]; ax.plot(th / np.pi, fd, color=INK, lw=0.9)
        ax.axvline(0, color=GLD, ls=":", lw=0.8); ax.axvline(2, color=GLD, ls=":", lw=0.8)
        ax.set_xlabel(f"$\\varphi_{axidx + 1}/\\pi$")
        ax.set_ylabel("合路 PD 强度 (V)")
        ax.set_title(f"(a) 子轴 {axidx + 1} 扫 $4V_\\pi$：$\\varphi$ vs $\\varphi{{+}}2\\pi$ 可区分"
                     f"（对比度 {cr:.2f}）", fontsize=7.0)
        c += 1
    if os.path.exists(cp):
        d = np.load(cp); Ah = d["Ah"]; A0 = d["A0"]
        ax = axs[0, c]; v = float(np.max(np.abs(Ah)))
        im = ax.imshow(Ah, cmap="RdYlGn", vmin=-v, vmax=v, aspect="auto")
        for r in range(9):
            for cc in range(12):
                if A0[r, cc] != 0:
                    ax.add_patch(Rectangle((cc - 0.5, r - 0.5), 1, 1, fill=False,
                                           ec=INK, lw=1.0))
        ax.set_yticks(range(9)); ax.set_yticklabels(CH_LABELS, fontsize=6)
        ax.set_xticks(range(12)); ax.set_xticklabels(FEAT_LABELS, rotation=60, fontsize=5.5)
        ax.set_title("(b) 辨识 $\\hat A$（框=理想 $A_0$ 稀疏指纹）", fontsize=7.0)
        fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig_exp6.pdf"))
    plt.close(fig); print("[fig] fig_exp6.pdf")


def fig_dp_obs(data, out):
    """fig:exp5 — IMD observability recovery.  (a,b) sigma_min maps over
    (phi1,phi2) at phi3=pi/2 with 6 vs 9 channels (from the measured A_hat);
    (c) measured parent-axis dither reconstruction error, 6 vs 9 ch.  fig:obs."""
    p = os.path.join(data, "dp_obs.npz")
    if not os.path.exists(p):
        print("[skip] fig_exp5: dp_obs.npz not found"); return
    d = np.load(p); f = d["f"]; M6 = d["M6"]; M9 = d["M9"]
    tk = [0, np.pi, 2 * np.pi, 3 * np.pi, 4 * np.pi]
    tl = ["0", "$\\pi$", "$2\\pi$", "$3\\pi$", "$4\\pi$"]
    L6 = np.log10(np.maximum(M6, 1e-6)); L9 = np.log10(np.maximum(M9, 1e-6))
    fig, axs = plt.subplots(1, 3, figsize=(2 * CW, 2.25),
                            gridspec_kw={"width_ratios": [1, 1, 0.78]})
    for ax, (M, tt) in zip(axs[:2], [(L6, "(a) 6 谐波通道"), (L9, "(b) +IMD（9 通道）")]):
        im = ax.pcolormesh(f, f, M, cmap="viridis", vmin=-6, vmax=-0.8,
                           shading="auto", rasterized=True)
        ax.plot(np.pi, np.pi, "o", mfc="none", mec=RED, ms=7, mew=1.4)  # standard pt
        ax.set_xticks(tk); ax.set_xticklabels(tl); ax.set_yticks(tk); ax.set_yticklabels(tl)
        ax.set_title(tt, fontsize=7.5); ax.set_xlabel("$\\varphi_1$")
    axs[0].set_ylabel("$\\varphi_2$")
    fig.colorbar(im, ax=axs[:2], orientation="horizontal",
                 label="$\\log_{10}\\sigma_{\\min}(\\mathcal{J})$",
                 fraction=0.10, pad=0.22)
    ax = axs[2]
    e6 = float(d["err6"]) * 1e3; e9 = float(d["err9"]) * 1e3
    ax.bar([0, 1], [e6, e9], color=[RED, GRN], width=0.6)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["6 谐波", "+IMD(9)"])
    ax.set_ylabel("RMS (mrad)")
    ax.set_title(f"(c) 标准点父轴可观测性\n$\\sigma_{{\\min}}$: {float(d['s6']):.1e}"
                 f"$\\to${float(d['s9']):.3f}", fontsize=7.0)
    fig.savefig(os.path.join(out, "fig_exp5.pdf"), bbox_inches="tight")
    plt.close(fig); print("[fig] fig_exp5.pdf")


def fig_dp_lock(data, out):
    """fig:exp4 — three-axis arbitrary-point lock: GN-affine vs three independent
    loops, at an arbitrary and the standard QPSK target (log error norm).
    Cross-refs fig:dploop."""
    p = os.path.join(data, "dp_lock.npz")
    if not os.path.exists(p):
        print("[skip] fig_exp4: dp_lock.npz not found"); return
    d = np.load(p)
    fig, axs = plt.subplots(1, 2, figsize=(2 * CW, 2.05), sharey=True)
    panels = [("arb", d["arb_eG"], d["arb_eT"], d["arb_target"], "(a) 任意目标点"),
              ("std", d["std_eG"], d["std_eT"], d["std_target"], "(b) 标准 QPSK 点")]
    for ax, (_, eG, eT, tgt, tt) in zip(axs, panels):
        ax.semilogy(np.maximum(eT, 1.0), color=RED, lw=0.7, label="三独立环")
        ax.semilogy(np.maximum(eG, 1.0), color=GRN, lw=0.7, label="GN 仿射（本文）")
        t = ", ".join(f"{x:.1f}" for x in tgt)
        ax.set_xlabel("控制周期"); ax.set_title(f"{tt} $({t})$", fontsize=7.5)
        ax.set_ylim(1, 4000)
    axs[0].set_ylabel("$\\|\\boldsymbol{\\varphi}-\\boldsymbol{\\varphi}^*\\|$ (mrad)")
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, frameon=False, fontsize=7,
               bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.9)); fig.savefig(os.path.join(out, "fig_exp4.pdf"))
    plt.close(fig); print("[fig] fig_exp4.pdf")


# --------------------------------------------------------------------------- #
#  composite cross-column panels for paper_mzm_zh relayout (new, appended)    #
#  This module is offline/deterministic (reads recorded data/exp/*, no RNG),  #
#  so these composites are ordinary new functions -- not capture-replots.     #
# --------------------------------------------------------------------------- #
def fig_expcal_mzm(data, out):
    """Three-panel single-column calibration evidence figure.

    (a) DM858E bidirectional DC transfer; (b) the raw H2/H1 trajectory with
    independently scaled, explicitly ticked axes; (c) affine pull-back. Reads
    only frozen vpi/calibration files and is deterministic.
    """
    vp = os.path.join(data, "vpi.csv")
    cnpz = os.path.join(data, "calib.npz"); cfjs = os.path.join(data, "calib_fit.json")
    have_vpi = os.path.exists(vp)
    have_cal = os.path.exists(cnpz) and os.path.exists(cfjs)
    if not (have_vpi or have_cal):
        print("[skip] fig_expcal_mzm: vpi.csv and calib.npz/calib_fit.json not found")
        return
    fig = plt.figure(figsize=(CW, 3.05))
    gs = fig.add_gridspec(2, 2, height_ratios=(0.82, 1.0))
    axs = [fig.add_subplot(gs[0, :]),
           fig.add_subplot(gs[1, 0]),
           fig.add_subplot(gs[1, 1])]
    c = 0
    if have_vpi:
        rows = _read_csv(vp)
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
        else:
            bu, du = sel(None); bd, dd = np.array([]), np.array([])
            a, b, vpi, v0 = ec.fit_dc_transfer(bu, du)
        ax = axs[c]
        ax.plot(bu, du, ".", ms=1.6, color=GRN, label="上行")
        if has_dir:
            ax.plot(bd, dd, "^", ms=1.6, mew=0, color=RED, label="下行")
        allb = np.concatenate([bu, bd]) if has_dir else bu
        vv = np.linspace(allb.min(), allb.max(), 400)
        ax.plot(vv, a + b * np.cos(np.pi * (vv - v0) / vpi), color=BLU, lw=1.0, label="拟合")
        ax.set_xlabel("偏压 $V_b$ (V)", fontsize=7.2, labelpad=1)
        ax.set_ylabel("PD 直流 (V)", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title(f"(a) 双向直流传递  $V_\\pi{{=}}{vpi:.3f}$ V", fontsize=7.2, pad=2)
        # headroom so the horizontal legend never overlaps the curve
        ax.margins(y=0.05)
        y0, y1 = ax.get_ylim(); ax.set_ylim(y0, y1 + 0.42 * (y1 - y0))
        ax.legend(fontsize=6.4, loc="upper center", ncol=3, frameon=False,
                  handlelength=1.1, handletextpad=0.3, columnspacing=0.8,
                  borderpad=0.1)
        c += 1
    if have_cal:
        d = np.load(cnpz, allow_pickle=True)
        with open(cfjs) as f:
            fit = json.load(f)
        X, Y = d["X"], d["Y"]; c0 = np.array(fit["c0"]); B = np.array(fit["B"])
        us = (B @ np.stack([X - c0[0], Y - c0[1]])).T
        A_hat = np.linalg.inv(B)
        ax = axs[c]
        ax.plot(X, Y, ".", ms=1.2, color=BLU, alpha=0.55)
        t = np.linspace(0, 2 * np.pi, 300)
        ell = (A_hat @ np.stack([np.cos(t), np.sin(t)])) + c0[:, None]
        ax.plot(ell[0], ell[1], color=INK, lw=1.0, ls="--")
        ax.plot(*c0, "+", color=INK, ms=6, mew=1.2)
        ax.annotate("$\\hat{\\mathbf{b}}$", c0, textcoords="offset points",
                    xytext=(4, -9), fontsize=6.5, color=INK)
        ax.set_xlabel("$X$ (H2)", fontsize=7.2, labelpad=1)
        ax.set_ylabel("$Y$ (H1)", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title("(b) H2/H1 观测椭圆", fontsize=7.2, pad=2)
        # The weak H2 direction is about 45 times smaller than H1.  Independent
        # axis spans keep the trajectory readable at single-column size; the
        # numeric ticks retain the actual scale of each recorded observable.
        xspan = 1.08 * max(np.max(np.abs(X - c0[0])),
                           np.max(np.abs(ell[0] - c0[0])))
        yspan = 1.08 * max(np.max(np.abs(Y - c0[1])),
                           np.max(np.abs(ell[1] - c0[1])))
        ax.set_xlim(c0[0] - xspan, c0[0] + xspan)
        ax.set_ylim(c0[1] - yspan, c0[1] + yspan)
        ax.set_aspect("auto")
        c += 1
        ax = axs[c]
        ax.plot(us[:, 0], us[:, 1], ".", ms=1.2, color=GRN)
        ax.add_patch(Circle((0, 0), 1, fill=False, ec=INK, lw=0.8, ls="--"))
        ax.set_xlabel("$\\hat u_x$", fontsize=7.2, labelpad=1)
        ax.set_ylabel("$\\hat u_y$", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        pullback = "相位标签回归回拉" if fit.get("method") == "phase-ref" else "椭圆--直流规范回拉"
        ax.set_title(f"(c) {pullback}", fontsize=6.9, pad=2)
        ax.set_aspect("equal"); ax.set_xlim(-1.25, 1.25); ax.set_ylim(-1.25, 1.25)
        c += 1
    for ax in axs[c:]:
        ax.set_visible(False)
    fig.tight_layout(pad=0.4, h_pad=0.75, w_pad=0.6)
    fig.savefig(os.path.join(out, "fig_expcal_mzm.pdf"))
    plt.close(fig); print("[fig] fig_expcal_mzm.pdf")


def fig_expperf_mzm(data, out):
    """fig_expperf_mzm — 1x4 cross-column strip: (a) kappa(A_hat) vs pilot
    depth m with J1/J2 theory (same data as fig_expkappa), (b) 16-target-point
    lock error affine vs H1 baseline (same data as fig_exp2), (c) RF-loaded H1
    fade vs J0 fit (same data as fig_exprf panel a), (d) lock rms vs RF power
    (same data as fig_exprf panel b). Each panel is skipped independently if
    its source .npz/.csv is missing."""
    pdp = os.path.join(data, "pilot_depth.csv")
    lsp = os.path.join(data, "lock_sweep.npz")
    rfp = os.path.join(data, "rf_lock.npz")
    have_pilot = os.path.exists(pdp)
    have_lock = os.path.exists(lsp)
    have_rf = os.path.exists(rfp)
    if not (have_pilot or have_lock or have_rf):
        print("[skip] fig_expperf_mzm: pilot_depth.csv / lock_sweep.npz / rf_lock.npz not found")
        return
    # single-column 2x2 layout (was cross-column 1x4)
    fig, axg = plt.subplots(2, 2, figsize=(CW, 3.25))
    axs = axg.ravel()
    c = 0
    if have_pilot:
        from scipy.special import jv
        rows = _read_csv(pdp)
        m = np.array([float(r["m"]) for r in rows])
        kap = np.array([float(r["kappa"]) for r in rows])
        order = np.argsort(m); m = m[order]; kap = kap[order]
        ax = axs[c]
        mm = np.linspace(max(0.02, m.min() * 0.8), m.max() * 1.12, 300)
        ax.plot(mm, np.abs(jv(1, mm) / jv(2, mm)), color=BLU, lw=1.0,
                label="$J_1/J_2$")
        ax.plot(m, kap, "o-", color=GRN, ms=3, lw=0.7, label="实测")
        ax.set_yscale("log")
        ax.set_xlabel("导频深度 $m$", fontsize=7.2, labelpad=1)
        ax.set_ylabel("$\\kappa(\\hat A)$", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title("(a) $\\kappa$ vs 导频深度", fontsize=7.2, pad=2)
        ax.legend(fontsize=6.3, loc="best", frameon=False, handlelength=1.3,
                  handletextpad=0.3, borderpad=0.1)
        ax.grid(True, which="both", alpha=0.25)
        c += 1
    if have_lock:
        d = np.load(lsp)
        ps = d["phi_star"]; aff = np.abs(d["affine_err"]) * 1e3
        base = np.abs(d["baseline_err"]) * 1e3
        ax = axs[c]
        ax.semilogy(ps, base, "s-", color=RED, ms=2.5, lw=0.7, label="H1 幅值匹配")
        ax.semilogy(ps, np.maximum(aff, 1e-1), "o-", color=GRN, ms=2.5, lw=0.7,
                    label="二维仿射反演")
        ax.set_xlabel("目标相位 $\\varphi^\\ast$ (rad)", fontsize=7.2, labelpad=1)
        ax.set_ylabel("$|\\varphi_{\\rm lock}-\\varphi^\\ast|$ (mrad)",
                      fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title("(b) 16 目标点静态误差", fontsize=7.2, pad=2)
        # Keep two long method names on separate rows inside the empty top band;
        # a two-column legend overran the narrow single-column panel.
        ax.set_ylim(top=ax.get_ylim()[1] * 22)
        ax.legend(fontsize=6.3, loc="upper center", ncol=1, frameon=False,
                  handlelength=1.3, handletextpad=0.3, labelspacing=0.18,
                  borderpad=0.15)
        ax.grid(True, which="major", alpha=0.25)
        ax.grid(False, which="minor")
        c += 1
    if have_rf:
        from scipy.special import j0 as bessel_j0
        from scipy.optimize import curve_fit
        d = np.load(rfp)
        powers = d["powers_dbm"]; rms = d["rms_mrad"]
        h1 = d["h1"]; fade = d["h1_fade"] if "h1_fade" in d.files else h1 / h1[0]
        off = ~np.isfinite(powers); on = np.isfinite(powers)
        vpk = _vpk_from_dbm(powers[on])
        fade_on = fade[on]
        try:
            vpi_rf = float(curve_fit(lambda v, vp: bessel_j0(np.pi * v / vp),
                                     vpk, fade_on, p0=[3.0], maxfev=20000)[0][0])
        except Exception:
            vpi_rf = 2.8
        m_eff = np.pi * vpk / vpi_rf
        ax = axs[c]
        mm = np.linspace(0, float(m_eff.max()) * 1.12 + 1e-3, 200)
        ax.plot(mm, bessel_j0(mm), color=BLU, lw=1.0, label="$J_0$ 预测")
        ax.plot(m_eff, fade_on, "o", color=GRN, ms=3.5, label="实测衰落")
        ax.set_xlabel("$m_{\\rm RF}$", fontsize=7.2, labelpad=1)
        ax.set_ylabel("H1 相对幅度", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title(f"(c) RF 加载 H1 衰落  $V_\\pi^{{\\rm RF}}{{\\approx}}{vpi_rf:.1f}$ V",
                     fontsize=7.2, pad=2)
        ax.legend(fontsize=6.3, loc="lower left", frameon=False,
                  handlelength=1.3, handletextpad=0.3, borderpad=0.1)
        ax.grid(True, alpha=0.25)
        ax.set_ylim(top=1.04, bottom=0)
        c += 1
        ax = axs[c]
        order = np.argsort(powers[on])
        ax.plot(powers[on][order], rms[on][order], "o-", color=GRN, ms=3.5, lw=0.8,
                label="逐态标定（RF 开）")
        rms_off = None
        if np.any(off):
            rms_off = float(np.mean(rms[off]))
            ax.axhline(rms_off, color=RED, ls="--", lw=0.9,
                       label=f"RF 关 ({rms_off:.0f} mrad)")
        ax.set_xlabel("RF 功率 (dBm)", fontsize=7.2, labelpad=1)
        ax.set_ylabel("锁定 RMS (mrad)", fontsize=7.2, labelpad=1)
        ax.tick_params(labelsize=6.8)
        ax.set_title("(d) 锁定 RMS vs RF 功率", fontsize=7.2, pad=2)
        # top headroom + vertical legend tucked in the empty upper-right corner
        # (labels are long, so ncol=2 overran the axis width -> stack them ncol=1
        # inside the frame; rms descends left-to-right so upper-right is clear)
        top_d = float(rms[on].max()) if rms_off is None else max(float(rms[on].max()), rms_off)
        ax.set_ylim(bottom=0, top=top_d * 1.9)
        ax.legend(fontsize=6.2, loc="upper right", ncol=1, frameon=False,
                  handlelength=1.2, handletextpad=0.3, labelspacing=0.25,
                  borderpad=0.2)
        ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.4, h_pad=0.8, w_pad=0.6)
    fig.savefig(os.path.join(out, "fig_expperf_mzm.pdf"))
    plt.close(fig); print("[fig] fig_expperf_mzm.pdf")


def fig_expstab_mzm(data, out):
    """fig_expstab_mzm — single-column (CW) narrow relayout of fig_exp3's two
    panels: (a) the complete 3 h record, including raw controller commands,
    raw demodulated error, sparse DMM checks and a short-cycle inset; and (b)
    residual-triggered detection/recalibration.  Raw dynamics are deliberately
    retained so smoothing cannot hide a period-2 orbit.  Offline/deterministic
    (reads stability.npz/drift.npz; no RNG)."""
    sp = os.path.join(data, "stability.npz"); dp = os.path.join(data, "drift.npz")
    has_s, has_d = os.path.exists(sp), os.path.exists(dp)
    if not (has_s or has_d):
        print("[skip] fig_expstab_mzm: stability.npz / drift.npz not found"); return
    nrows = int(has_s) + int(has_d)
    fig, axs = plt.subplots(nrows, 1, figsize=(CW, 1.42 * nrows + 0.35), squeeze=False)
    r = 0
    if has_s:
        ax1 = axs[r, 0]
        d = np.load(sp)
        th = d["t"] / 3600.0; V = d["V"]; err = d["err_mrad"]
        dt = d["dmm_t"] / 3600.0; de = d["dmm_err_mrad"]
        rec = int(d["recal_events"]); hrs = float(d["t"][-1]) / 3600
        vrange = float(V.max() - V.min())
        raw_rms = float(np.sqrt(np.mean(err ** 2)))
        lag1 = float(np.corrcoef(err[:-1], err[1:])[0, 1])
        flip = float(np.mean(np.signbit(err[1:]) != np.signbit(err[:-1])))
        # Show both the raw command and its low-frequency trend.  The raw band
        # is evidence: it must not be described as two pilot/dither states.
        w = max(5, (len(V) // 120) | 1)       # odd window ~1/120 of the record
        kern = np.ones(w) / w
        Vtrend = np.convolve(V, kern, mode="same")
        edge = w // 2
        ax1.plot(th, V, color=INK, lw=0.30, alpha=0.20, zorder=1,
                 label="$V_b$ 原始命令")
        ax1.plot(th[edge:-edge], Vtrend[edge:-edge], color=INK, lw=0.85,
                 alpha=0.95, zorder=2, label="$V_b$ 低频趋势")
        ax1.set_ylabel("$V_b$ (V)", color=INK, fontsize=6.8, labelpad=1)
        ax1.set_xlabel("时间 (h)", fontsize=6.8, labelpad=1)
        ax1.tick_params(axis="y", labelcolor=INK, labelsize=6.3, pad=1)
        ax1.tick_params(axis="x", labelsize=6.3, pad=1)
        ax1.xaxis.set_major_locator(plt.MaxNLocator(nbins=5))
        ax1.yaxis.set_major_locator(plt.MaxNLocator(nbins=4))
        vlo, vhi = float(V.min()), float(V.max())
        ax1.set_ylim(vlo - 0.05 * (vhi - vlo), vhi + 0.05 * (vhi - vlo))
        ax1.set_title(f"(a) 3 h 原始动态 (命令范围 {vrange:.2f} V, "
                      f"触发{rec}次)", fontsize=6.5, pad=2)
        ax2 = ax1.twinx()
        ax2.plot(th, err, color=GRN, lw=0.25, alpha=0.18, zorder=2,
                 label="逐周期解调误差")
        ax2.plot(dt, de, "o", mfc="none", mec=RED, mew=0.8, ms=2.8,
                 alpha=0.9, zorder=4, label="稀疏相位评价")
        ax2.set_ylabel("相位误差 (mrad)", color=GRN, fontsize=6.8, labelpad=1)
        ax2.tick_params(axis="y", labelcolor=GRN, labelsize=6.3, pad=1)
        ax2.yaxis.set_major_locator(plt.MaxNLocator(nbins=4))
        elim = max(1000.0, float(np.max(np.abs(err))) * 1.10,
                   float(np.max(np.abs(de))) * 1.20)
        ax2.set_ylim(-elim, elim)
        # A short inset makes the alternating orbit visible instead of leaving
        # it as an uninterpretable dense band over the full 3 h axis.
        nshow = min(24, len(err))
        ins = ax1.inset_axes([0.08, 0.08, 0.37, 0.34], zorder=8)
        ins.plot(np.arange(nshow), err[:nshow], "o-", color=GRN,
                 lw=0.45, ms=1.7)
        ins.axhline(0, color="#777777", lw=0.35)
        ins.set_title(f"前 {nshow} 周期: RMS={raw_rms:.0f} mrad\n"
                      f"lag1={lag1:.3f}, 翻转={flip:.2f}", fontsize=4.8,
                      pad=1.0)
        ins.tick_params(labelsize=4.5, length=1.5, pad=0.5)
        ins.set_xlabel("周期", fontsize=4.8, labelpad=0)
        ins.set_ylabel("mrad", fontsize=4.8, labelpad=0)
        r += 1
    if has_d:
        ax1 = axs[r, 0]
        d = np.load(dp)
        err = np.abs(d["err_mrad"]); rho = d["rho_bar"]
        step = int(d["step_at"]); lat = int(d["latency"])
        recal = int(d["recal_at"]) if "recal_at" in d.files else (
            step + lat if lat >= 0 else -1)
        ax1.plot(err, color=GRN, lw=0.7)
        ax1.set_xlabel("控制周期", fontsize=6.8, labelpad=1)
        ax1.set_ylabel("误差 (mrad)", color=GRN, fontsize=6.8, labelpad=1)
        ax1.tick_params(axis="y", labelcolor=GRN, labelsize=6.3, pad=1)
        ax1.tick_params(axis="x", labelsize=6.3, pad=1)
        ax1.xaxis.set_major_locator(plt.MaxNLocator(nbins=5))
        ax1.yaxis.set_major_locator(plt.MaxNLocator(nbins=4))
        ax1.axvline(step, color=RED, ls="--", lw=0.8)
        ax1.annotate("突变", xy=(step, ax1.get_ylim()[1]), xytext=(-3, -7),
                     textcoords="offset points", color=RED, fontsize=6.0,
                     ha="right", va="top")
        if recal >= 0:
            ax1.axvline(recal, color=BLU, ls=":", lw=0.8)
            ax1.annotate(f"+{lat}→重标", xy=(recal, ax1.get_ylim()[1]),
                         xytext=(3, -18), textcoords="offset points",
                         color=BLU, fontsize=6.0, ha="left", va="top")
        ax1.set_title("(b) 残差触发检测与恢复", fontsize=6.5, pad=2)
        ax2 = ax1.twinx()
        ax2.plot(rho, color=INK, lw=0.8, alpha=0.85)
        ax2.set_ylabel("残差 $\\bar\\rho$", color=INK, fontsize=6.8, labelpad=1)
        ax2.tick_params(axis="y", labelcolor=INK, labelsize=6.3, pad=1)
        ax2.yaxis.set_major_locator(plt.MaxNLocator(nbins=4))
    fig.subplots_adjust(left=0.145, right=0.86, top=0.90, bottom=0.13, hspace=0.65)
    fig.savefig(os.path.join(out, "fig_expstab_mzm.pdf"))
    plt.close(fig); print("[fig] fig_expstab_mzm.pdf")


def fig_exprepeat_mzm(data, out):
    """Render the frozen v1.2 static-repeat result without touching raw data."""
    src = os.path.join(
        data, "diagnostics", "static_repeats",
        "20260717_static_v12_board2", "analysis.json")
    if not os.path.exists(src):
        print(f"[skip] fig_exprepeat_mzm.pdf (missing {src})")
        return
    with open(src, encoding="utf-8") as f:
        analysis = json.load(f)
    if not analysis.get("quality_gate", {}).get("accepted", False):
        print("[skip] fig_exprepeat_mzm.pdf (v1.2 analysis not accepted)")
        return

    blocks = list(analysis["statistics"]["blocks"].values())
    grids = sorted({int(row["grid_index"]) for row in blocks})
    conditions = ["none", "gen", "acq", "both"]
    labels = {"none": "无重启", "gen": "发生器", "acq": "采集器",
              "both": "两者"}
    colors = {"none": INK, "gen": GRN, "acq": BLU, "both": RED}
    styles = {"none": "-", "gen": "--", "acq": "-.", "both": ":"}
    marks = {"none": "o", "gen": "s", "acq": "^", "both": "D"}
    by_key = {(int(row["grid_index"]), row["condition"]): row
              for row in blocks}
    x = np.arange(len(grids))

    fig, axs = plt.subplots(2, 1, figsize=(CW, 3.05), sharex=True)
    for condition in conditions:
        h1 = np.array([1000.0 * by_key[(g, condition)]["h1_phase_cstd_rad"]
                       for g in grids])
        h2 = np.array([1000.0 * by_key[(g, condition)]["h2_phase_cstd_rad"]
                       for g in grids])
        kw = dict(color=colors[condition], ls=styles[condition],
                  marker=marks[condition], ms=3.0, lw=0.85,
                  label=labels[condition])
        axs[0].plot(x, h1, **kw)
        axs[1].plot(x, h2, **kw)

    thresholds = analysis["statistics"]["thresholds"]
    restart_gate = 1000.0 * thresholds["restart_excess_min_rad"]
    environment_gate = 1000.0 * thresholds["environment_h2_cstd_rad"]
    axs[0].axhline(restart_gate, color=GLD, ls=(0, (4, 2)), lw=0.8,
                   label="重启增量门 20 mrad")
    axs[0].set_yscale("log")
    axs[0].set_ylim(0.02, 30.0)
    axs[0].set_ylabel("H1 相位圆标准差 (mrad)", fontsize=6.8, labelpad=1)
    axs[0].set_title("(a) H1 参考相位", fontsize=6.7, pad=2)
    axs[0].text(0.02, 0.06, "最大 0.330 mrad；最大重启增量 0.287 mrad",
                transform=axs[0].transAxes, fontsize=6.0, color=INK)

    axs[1].axhline(environment_gate, color=GLD, ls=(0, (4, 2)), lw=0.8,
                   label="环境门 50 mrad")
    axs[1].set_ylim(0, 55)
    axs[1].set_ylabel("H2 相位圆标准差 (mrad)", fontsize=6.8, labelpad=1)
    axs[1].set_title("(b) H2 弱轴相位", fontsize=6.7, pad=2)
    axs[1].text(0.02, 0.84, "最大 29.9 mrad",
                transform=axs[1].transAxes, fontsize=6.0, color=INK)
    axs[1].set_xlabel("满周期扫描相位", fontsize=6.8, labelpad=1)
    axs[1].set_xticks(x, [r"$0$", r"$\pi/2$", r"$\pi$",
                         r"$3\pi/2$", r"$2\pi$"])

    for ax in axs:
        ax.grid(True, which="major", color="#D8DDD9", lw=0.35)
        ax.tick_params(labelsize=6.3, pad=1, length=2)
        ax.spines[["top", "right"]].set_visible(False)
    handles, legend_labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=3,
               bbox_to_anchor=(0.5, 0.995), frameon=False, fontsize=6.0,
               handlelength=2.2, columnspacing=0.9)
    fig.subplots_adjust(left=0.18, right=0.98, top=0.85, bottom=0.13,
                        hspace=0.42)
    fig.savefig(os.path.join(out, "fig_exprepeat_mzm.pdf"))
    plt.close(fig); print("[fig] fig_exprepeat_mzm.pdf")


def fig_expdiag_mzm(data, out):
    """Compact two-panel hardware-dynamics figure for one IEEE column."""
    stability_path = os.path.join(data, "stability.npz")
    drift_path = os.path.join(data, "drift.npz")
    if not all(os.path.exists(p) for p in (stability_path, drift_path)):
        print("[skip] fig_expdiag_mzm.pdf (missing frozen input)")
        return

    fig, axs = plt.subplots(1, 2, figsize=(CW, 1.58))

    # (a) The full 3 h record is represented by its two alternating branches.
    # This preserves the period-2 evidence without overplotting 6078 samples.
    stable = np.load(stability_path)
    t_h = stable["t"] / 3600.0
    err = stable["err_mrad"]
    dmm_t_h = stable["dmm_t"] / 3600.0
    dmm_err = stable["dmm_err_mrad"]
    ax = axs[0]
    smooth_n = 61
    kernel = np.ones(smooth_n) / smooth_n
    for parity, color, label in ((0, GRN, "偶周期"),
                                 (1, BLU, "奇周期")):
        branch_t = t_h[parity::2]
        branch_e = err[parity::2]
        branch_s = np.convolve(branch_e, kernel, mode="valid")
        half = smooth_n // 2
        ax.plot(branch_t[half:half + len(branch_s)], branch_s,
                color=color, lw=0.75, label=label)
    ax.plot(dmm_t_h, dmm_err, "o", mfc="none", mec=RED, mew=0.55,
            ms=2.0, label="稀疏评价")
    ax.axhline(0, color="#777777", lw=0.35)
    ax.set_xlim(0, 3.0)
    ax.set_ylim(-1100, 1100)
    ax.set_xlabel("时间 (h)", fontsize=6.2, labelpad=1)
    ax.set_ylabel("相位误差 (mrad)", fontsize=6.2, labelpad=1)
    ax.set_title("(a) 3 h 周期--2 分支", fontsize=6.4, pad=2)
    ax.legend(loc="lower center", ncol=3, frameon=False, fontsize=5.2,
              handlelength=1.0, handletextpad=0.25, columnspacing=0.55,
              borderpad=0.1)

    # (b) Show error and residual on the same time support.  Annotations carry
    # the event semantics so a long legend is unnecessary at half-column width.
    drift = np.load(drift_path)
    drift_err = np.abs(drift["err_mrad"])
    rho = drift["rho_bar"]
    step = int(drift["step_at"])
    recal = int(drift["recal_at"])
    threshold = float(drift["thr"])
    ax = axs[1]
    ax.plot(drift_err, color=GRN, lw=0.70)
    ax.axvline(step, color=RED, ls="--", lw=0.70)
    ax.axvline(recal, color=BLU, ls=":", lw=0.75)
    ax.set_xlim(0, len(drift_err) - 1)
    ax.set_ylim(0, 1800)
    ax.set_xlabel("控制周期", fontsize=6.2, labelpad=1)
    ax.set_ylabel("误差 (mrad)", color=GRN, fontsize=6.2, labelpad=1)
    ax.set_title("(b) 残差触发重扫", fontsize=6.4, pad=2)
    ax.text(step - 2, 1730, "突变", color=RED, fontsize=5.3,
            ha="right", va="top")
    ax.text(recal + 2, 1420, "+6 重扫", color=BLU, fontsize=5.3,
            ha="left", va="top")
    ax_r = ax.twinx()
    ax_r.plot(rho, color=INK, lw=0.60, alpha=0.90)
    ax_r.axhline(threshold, color=GLD, ls="--", lw=0.65)
    ax_r.set_ylim(0, 0.25)
    ax_r.set_ylabel(r"残差 $\bar\rho$", color=INK, fontsize=6.2, labelpad=1)
    ax_r.tick_params(axis="y", labelcolor=INK, labelsize=5.4, pad=1)

    for ax in axs:
        ax.tick_params(labelsize=5.4, pad=1, length=2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_locator(ax.xaxis.get_major_locator())
    fig.subplots_adjust(left=0.15, right=0.89, top=0.88, bottom=0.23,
                        wspace=0.68)
    fig.savefig(os.path.join(out, "fig_expdiag_mzm.pdf"))
    plt.close(fig); print("[fig] fig_expdiag_mzm.pdf")


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
    fig_rf(a.data_dir, a.out_dir)
    fig_dp_torus(a.data_dir, a.out_dir)
    fig_dp_obs(a.data_dir, a.out_dir)
    fig_dp_lock(a.data_dir, a.out_dir)
    fig_expcal_mzm(a.data_dir, a.out_dir)
    fig_expperf_mzm(a.data_dir, a.out_dir)
    fig_expstab_mzm(a.data_dir, a.out_dir)
    fig_exprepeat_mzm(a.data_dir, a.out_dir)
    fig_expdiag_mzm(a.data_dir, a.out_dir)


if __name__ == "__main__":
    main()
