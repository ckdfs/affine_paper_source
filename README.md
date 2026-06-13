# 仿射框架 MZM/DPMZM 任意点偏压控制 — 论文源

MZM / DPMZM 任意工作点偏压控制的仿射框架推导与仿真。提供中英双语手稿、绘图脚本与渲染图。

## 目录结构

```
.
├── paper.tex            # 英文手稿
├── paper_zh.tex         # 中文手稿
├── figs/                # 渲染好的 PDF 图（被 tex 引用，已纳入版本管理）
├── scripts/             # 绘图脚本（重新生成 figs/ 下的图）
│   ├── make_figs.py         # fig_arch/ellipse/bessel/mzmloop/torus/obs/dploop/ahat
│   ├── make_extra_figs.py   # fig_gauge/mcdp/sweep
│   └── make_algo_figs.py    # fig_acq/flow/recal/step
└── notes/               # HTML 推导笔记
```

## 重新生成图

脚本里的输出路径 `figs/` 是相对当前工作目录的，**请在仓库根目录运行**：

```bash
python scripts/make_figs.py
python scripts/make_extra_figs.py
python scripts/make_algo_figs.py
```

> 注：绘图需用 miniconda3 的 Python 环境。脚本含随机数生成，重跑会令个别数值发生微小漂移，故 `figs/` 已随源码一并提交。

## 编译论文

在仓库根目录下：

```bash
latexmk -xelatex paper.tex      # 英文
latexmk -xelatex paper_zh.tex   # 中文
```

中间产物（`*.aux *.log *.fls *.fdb_latexmk *.xdv` 等）与编译输出 `paper.pdf` / `paper_zh.pdf` 已在 `.gitignore` 中忽略。
