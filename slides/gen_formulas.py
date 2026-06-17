#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emit formulas.json: display + table-cell equations, plus every « »-marked
inline fragment collected from build.py. Run before render_math_assets.py."""
import json, os, sys
from pathlib import Path

_SKILL_DIR = os.environ.get("CLAUDE_SKILL_DIR") or r"C:\Users\ckdfs\.claude\skills\group-meeting-pptx"
sys.path.insert(0, str(Path(_SKILL_DIR) / "scripts"))
import mathmark

D = "display"

DISPLAY = [
    ("mzm", r"P_{\mathrm{out}}(t)=\tfrac{P_0}{2}\bigl[1+\eta\cos\varphi(t)\bigr],\quad \eta=\tfrac{2\sqrt{r}}{1+r}\le 1"),
    ("lockin", r"\mathcal{L}_1[f]=\overline{2f(t)\sin(\omega t+\theta_1)},\quad \mathcal{L}_2[f]=\overline{2f(t)\cos(2\omega t+\theta_2)}"),
    ("ideal", r"Y=-\eta\kappa_1\sin\varphi_b,\quad X=\eta\kappa_2\cos\varphi_b,\quad \kappa_n=G_n\rho P_0 J_n(m)"),
    ("sQN", r"\Delta\varphi_{\mathrm{Q}}=\frac{A_{12}+b_X}{A_{11}},\qquad \Delta\varphi_{\mathrm{N}}=\frac{b_Y-A_{21}}{A_{22}}"),
    ("sAM", r"\Delta\varphi_{\mathrm{AM}}=-\frac{A_{21}\cos\varphi^\ast+(A_{22}+\kappa_1^{\mathrm{nom}})\sin\varphi^\ast+b_Y}{A_{22}\cos\varphi^\ast-A_{21}\sin\varphi^\ast}"),
    ("ratio", r"X/Y=-(\kappa_2/\kappa_1)\cot\varphi_b"),
    ("lemma", r"\cos(\varphi_b+\xi(t))=\cos\varphi_b\cos\xi(t)-\sin\varphi_b\sin\xi(t)"),
    ("affine", r"\mathbf{z}=A\,\mathbf{u}(\varphi_b)+\mathbf{b}+\mathbf{n},\qquad \mathbf{u}=(\cos\varphi_b,\sin\varphi_b)^{\mathsf{T}}"),
    ("Amat", r"A=\frac{\eta\rho P_0}{2}\begin{pmatrix}G_2\mathcal{L}_2[\cos\xi] & -G_2\mathcal{L}_2[\sin\xi]\\[2pt] G_1\mathcal{L}_1[\cos\xi] & -G_1\mathcal{L}_1[\sin\xi]\end{pmatrix}"),
    ("bnvec", r"\mathbf{b}=\begin{pmatrix}G_2\mathcal{L}_2[i_x]+O_X\\[2pt] G_1\mathcal{L}_1[i_x]+O_Y\end{pmatrix},\quad \mathbf{n}=\begin{pmatrix}G_2\mathcal{L}_2[i_n]\\[2pt] G_1\mathcal{L}_1[i_n]\end{pmatrix}"),
    ("Adiag", r"A_{11}=\eta\kappa_2\cos\theta_2,\qquad A_{22}=-\eta\kappa_1\cos\theta_1"),
    ("ellipse", r"(\mathbf{z}-\mathbf{b})^{\mathsf{T}}M(\mathbf{z}-\mathbf{b})=1,\qquad M\triangleq(AA^{\mathsf{T}})^{-1}\succ0"),
    ("demod", r"B\triangleq R(-\hat\varphi_c)\,F\,M^{1/2},\qquad \hat\varphi_b=\operatorname{atan2}\!\bigl(B(\mathbf{z}-\hat{\mathbf{b}})\bigr)"),
    ("var", r"\sigma^2_{\hat\varphi}(\varphi)=\mathbf{t}^{\mathsf{T}}A^{-1}\Sigma_n A^{-\mathsf{T}}\mathbf{t}\;\xrightarrow{\;\Sigma_n=\sigma^2 I\;}\;\sigma^2\,\mathbf{t}^{\mathsf{T}}(A^{\mathsf{T}}A)^{-1}\mathbf{t}\le\frac{\sigma^2}{\sigma^2_{\min}(A)}"),
    ("kappa", r"\kappa(A)=\sqrt{\lambda_{\max}(M)/\lambda_{\min}(M)},\qquad \kappa(A)=J_1(m)/J_2(m)\to 4/m"),
    ("dpfield", r"E_{\mathrm{out}}=\frac{E_{\mathrm{in}}}{2}\Bigl[\cos\tfrac{\Theta_1}{2}+e^{j\Theta_3}\cos\tfrac{\Theta_2}{2}\Bigr],\quad \Theta_i=\varphi_i+\xi_i(t)"),
    ("dppower", r"P_{\mathrm{out}}=\frac{P_0}{8}\bigl[2+\cos\Theta_1+\cos\Theta_2\bigr]+\frac{P_0}{2}\cos\tfrac{\Theta_1}{2}\cos\tfrac{\Theta_2}{2}\cos\Theta_3"),
    ("klein", r"T_1:(\varphi_1+2\pi,\ \varphi_2,\ \varphi_3+\pi),\qquad T_2:(\varphi_1,\ \varphi_2+2\pi,\ \varphi_3+\pi)"),
    ("feature", r"\Phi(\boldsymbol{\varphi})=\bigl(\cos\varphi_1,\sin\varphi_1,\cos\varphi_2,\sin\varphi_2,\ \mathbf{v}_1\!\otimes\!\mathbf{v}_2\!\otimes\!\mathbf{v}_3\bigr),\ \ \mathbf{v}_1=(c_1,s_1),\ \mathbf{v}_2=(c_2,s_2),\ \mathbf{v}_3=(C_3,S_3)"),
    ("dpaffine", r"\mathbf{z}=A\,\Phi(\boldsymbol{\varphi})+\mathbf{b}+\mathbf{n},\qquad A\in\mathbb{R}^{K\times 12}"),
    ("jac", r"\mathcal{J}(\boldsymbol{\varphi})=A\,D\Phi(\boldsymbol{\varphi})\in\mathbb{R}^{K\times 3},\qquad \sigma_{\min}(\mathcal{J})>0"),
    ("regress", r"[\hat A\,|\,\hat{\mathbf{b}}]=\Bigl(\sum_k \mathbf{z}_k\tilde\Phi_k^{\mathsf{T}}\Bigr)\Bigl(\sum_k \tilde\Phi_k\tilde\Phi_k^{\mathsf{T}}\Bigr)^{-1},\quad \tilde\Phi=\begin{pmatrix}\Phi\\1\end{pmatrix}"),
    ("gn", r"\hat{\boldsymbol{\varphi}}\leftarrow\hat{\boldsymbol{\varphi}}+(\mathcal{J}^{\mathsf{T}}\mathcal{J}+\lambda I)^{-1}\mathcal{J}^{\mathsf{T}}\bigl[\mathbf{z}-\hat A\Phi(\hat{\boldsymbol{\varphi}})-\hat{\mathbf{b}}\bigr]"),
    ("covcrb", r"\Sigma_{\hat{\boldsymbol{\varphi}}}=(\mathcal{J}^{\mathsf{T}}\Sigma_n^{-1}\mathcal{J})^{-1}"),
    ("parentnoise", r"\sigma^2_{\hat\varphi_3}\approx\frac{\sigma^2}{\bigl[j_1^{(1)}j_1^{(2)}J_0(m_3)\bigr]^2}\approx\Bigl(\frac{16}{m_1 m_2}\Bigr)^{2}\sigma^2"),
    ("appL", r"\begin{aligned}\mathcal{L}_1[\cos\xi]&=-\varepsilon m\bigl[J_1\sin(\theta_1-\psi)+J_3\sin(\theta_1+\psi)\bigr],\\ \mathcal{L}_2[\sin\xi]&=\varepsilon m\bigl[J_0\sin(\psi-\theta_2)+J_4\sin(\psi+\theta_2)\bigr]\end{aligned}"),
    ("Aoff", r"\begin{aligned}A_{12}&=-\tfrac{\eta\rho P_0 G_2}{2}\varepsilon m\bigl[J_0(m)\sin(\psi-\theta_2)+J_4(m)\sin(\psi+\theta_2)\bigr],\\ A_{21}&=-\tfrac{\eta\rho P_0 G_1}{2}\varepsilon m\bigl[J_1(m)\sin(\theta_1-\psi)+J_3(m)\sin(\theta_1+\psi)\bigr]\end{aligned}"),
    ("dphic", r"\delta\varphi_c\approx\varepsilon m J_2(m)\sin\psi/J_0(m)"),
    # ---- table cells ----
    ("hm_dc", r"\tfrac{\rho P_0}{2}\bigl[1+\eta J_0(m)\cos\varphi_b\bigr]"),
    ("hm_w", r"-\eta\rho P_0 J_1(m)\sin\varphi_b"),
    ("hm_2w", r"+\eta\rho P_0 J_2(m)\cos\varphi_b"),
    ("hm_3w", r"-\eta\rho P_0 J_3(m)\sin\varphi_b"),
    ("dep_c", r"\cos\varphi_b"),
    ("dep_s", r"\sin\varphi_b"),
    ("sQ", r"\dfrac{A_{12}+b_X}{A_{11}}"),
    ("sN", r"\dfrac{b_Y-A_{21}}{A_{22}}"),
    ("ch_y1", r"-\tfrac14 J_1^{(1)}\sin\varphi_1-j_1^{(1)}j_0^{(2)}J_0(m_3)\,s_1c_2C_3"),
    ("ch_x1", r"+\tfrac14 J_2^{(1)}\cos\varphi_1+j_2^{(1)}j_0^{(2)}J_0(m_3)\,c_1c_2C_3"),
    ("ch_y2", r"-\tfrac14 J_1^{(2)}\sin\varphi_2-j_0^{(1)}j_1^{(2)}J_0(m_3)\,c_1s_2C_3"),
    ("ch_x2", r"+\tfrac14 J_2^{(2)}\cos\varphi_2+j_0^{(1)}j_2^{(2)}J_0(m_3)\,c_1c_2C_3"),
    ("ch_y3", r"-j_0^{(1)}j_0^{(2)}J_1(m_3)\,c_1c_2S_3"),
    ("ch_x3", r"+j_0^{(1)}j_0^{(2)}J_2(m_3)\,c_1c_2C_3"),
    ("ch_zm", r"+j_1^{(1)}j_1^{(2)}J_0(m_3)\,s_1s_2C_3"),
    ("ch_z13", r"+j_1^{(1)}j_0^{(2)}J_1(m_3)\,s_1c_2S_3"),
    ("ch_z23", r"+j_0^{(1)}j_1^{(2)}J_1(m_3)\,c_1s_2S_3"),
]

formulas = [{"id": i, "latex": l, "mode": D} for i, l in DISPLAY]
inline = mathmark.collect_file("build.py")
formulas += [{"id": i, "latex": l, "mode": "inline"} for i, l in inline.items()]

Path("formulas.json").write_text(
    json.dumps({"formulas": formulas}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote formulas.json: {len(DISPLAY)} display/table + {len(inline)} inline = {len(formulas)} total")
