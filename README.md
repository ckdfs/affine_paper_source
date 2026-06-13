# 仿射框架 MZM/DPMZM 任意点偏压控制 — 论文源

MZM / DPMZM 任意工作点偏压控制的仿射框架推导与仿真。提供中英双语手稿、绘图脚本与渲染图。

## 目录结构

```
.
├── paper.tex            # 英文手稿
├── paper_zh.tex         # 中文手稿
├── figs/                # 渲染好的 PDF 图（被 tex 引用，已纳入版本管理）
├── scripts/             # 绘图脚本 + 维护脚手架
│   ├── make_figs.py         # fig_arch/ellipse/bessel/mzmloop/torus/obs/dploop/ahat + fig_exp_setup
│   ├── make_extra_figs.py   # fig_gauge/mcdp/sweep
│   ├── make_algo_figs.py    # fig_acq/flow/recal/step
│   ├── build.py             # 一键编排：选对解释器、重生成图、捕获仿真输出、编译
│   ├── check.py             # 校验器：交叉引用/引文/图文件/数值对账
│   └── paper_metrics.json   # 数值契约（论文里每个关键数字 ↔ 仿真输出）
├── notes/               # HTML 推导笔记
├── Makefile             # make figs|pdf|check|verify|clean
└── CLAUDE.md            # AI 维护手册（约定、坑、工作流）
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

## 维护与校验（脚手架）

推荐用脚手架一键完成「重生成 → 编译 → 校验」：

```bash
make figs      # 用对解释器重生成图，并把仿真 stdout 存到 build/sim_output.txt
make pdf       # latexmk -xelatex paper_zh.tex
make check     # 校验：交叉引用、引文、图文件是否齐全，以及论文数字 ↔ 仿真对账
make verify    # 以上全部（figs + pdf + check）
```

没有 `make` 时直接用任意 python3 调用（脚本会自动切到带 numpy 的解释器）：
`python scripts/build.py figs|pdf|all`、`python scripts/check.py`。

`check.py` 的数值对账以 `scripts/paper_metrics.json` 为契约，双向校验：论文里必须出现该数字、且仿真能复现它（容差内）。**改动任何数字/图/参考文献后，请跑 `make check` 直到 `0 FAIL`。** 详细约定见 [CLAUDE.md](CLAUDE.md)。
