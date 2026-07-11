# MZM 可选强化实验预注册协议（脚本名 `acceptance`）

版本：2026-07-10 v1

定位：`paper_mzm_zh.tex` 的现有单器件实验已经覆盖 16 个工作点、H1 对照、3~h
运行、重标定和 RF 工况，足以支撑文中限定的硬件可行性结论。本协议不是投稿或
接收的前置条件，而是一套可选的高强度扩展，用于进一步研究无相位标签闭环、
非对角校正的独立收益、跨会话重复性与隔离真值。协议在采集此类扩展数据前固定
控制器、随机化、评价口径和通过条件，避免结果导向的阈值选择。

## 1. 实验单位与会话

- 独立实验单位是一轮“重新扫描、重新标定、重新锁定”的校准块，而不是目标点、
  控制周期或 DMM 时间样本。
- 至少完成 6 个校准块，分布于至少 2 个独立实验会话/日期；每个会话建议 3 个块。
- 每个校准块必须保留，无论标定或锁定是否失败。只有预先记录的硬件通信故障、
  激光器掉电或人工急停可标为无效；算法失败不能删去后重跑。
- 每个块重新执行双向 151 点直流扫描与 181 点满周期观测扫描，不在块内重标定。

## 2. 控制器与公平比较

三个控制器使用相同 H1/H2 原始观测、同一扫描、导频、平均长度、控制增益、迭代数
和初始偏置。

1. `full_affine`：仅由 `calibrate_from_data(X,Y,dc)` 得到椭圆、反射和直流规范，
   闭环中使用完整 `B`。相位标签不得进入 `B`、中心、控制增益或分支选择。
2. `calibrated_h1h2`：强化的 Wang--Kowalczyk 型 H1/H2 基线。保留同一中心、
   规范和 `A` 的两个对角增益，令非对角元为零后用双象限 `atan2`；它只丢弃交叉
   通道校正，不获得额外扫描或标签。
3. `h1_match`：单 H1 幅值匹配，作为结构性失锁的次要诊断，不作为唯一强基线。

每个目标从相对目标相位 `-1.0` 和 `+1.0 rad` 两侧启动。目标顺序按记录种子随机，
控制器顺序采用随目标和会话循环的平衡次序；每个控制器均从相同配对初值重新启动，
不得沿用上一控制器的末态。

固定采集参数：

- 目标：`2*pi*k/16, k=0,...,15`；
- 导频幅度：0.15 V；
- 标定：181 点，`n_blocks=16`，`cal_n_avg=4`；
- 闭环：40 周期，`lock_n_avg=1`，增益 0.3；
- 每个控制器/目标/初值完成后读取 5 次 DMM，作为共享光路敏感性评价；
- 后 40% 控制周期作为稳态窗口。

## 3. 真值与隔离

控制器使用的直流序列只负责规范固定，不是独立真值。可选的隔离真值扩展要求另一路不向
控制进程开放的光学验证通道：未使用的 MZM 输出或稳定抽头接独立 PD/功率计，在每个
校准块前后记录 `P_val(V)`。分析时对两次验证扫描的 `V_pi` 与相位原点按时间插值，
生成 `truth_prepost.npz`；采集完成前控制程序不得读取该文件。

当前 `measure_bench.py acceptance` 使用双向共享光路 DC 映射作为主诊断、局部 DMM
作为敏感性口径，因此即使控制器指标全部通过，也会保持
`independent_optical_truth=false`。在独立验证通道接入并生成预规定文件前，不得把
结果表述为独立绝对相位验证。

当前分析器不会因检测到同名文件就放行：独立通道的采集、时间对齐和盲法评分尚未
实现，因此该门被硬编码为假。实现时必须先冻结 `truth_prepost.npz` 的字段、最小扫描
点数、有限值/扫描跨度检查、块前后相位插值与逐试验评分算法，再通过合成错文件测试。

## 4. 预注册终点

每个目标/控制器/初值记录：最终 wrapped phase error、稳态标准差、整定周期、DAC
饱和、分支失败、圆残差和原始迭代轨迹。

一次试验成功需同时满足：

- 最终绝对相位误差不超过 0.35 rad；
- 稳态标准差不超过 0.15 rad；
- 无 DAC 饱和；
- 无分支失败，即绝对相位误差小于 `pi/2`。

主要汇总量为每校准块 16 目标、两初值的 RMS 和成功率。次要量为绝对误差中位、
P95、最大值、整定周期、稳态抖动、圆残差 P95、`sigma_min(A)`、`kappa(A)`、规范
幅度/残差比和标定耗时。

## 5. 统计分析

- 完整仿射与基线在校准块、目标和初值上配对。
- bootstrap 先重采样实验会话，再在会话内重采样校准块，最后在块内重采样目标；
  控制周期不作为独立样本。
- 报告 `RMS_baseline - RMS_full` 的双侧 95% 置信区间和全部逐块结果。
- 若原生链路的非对角能量比
  `norm(A-diag(A),'fro')/norm(A,'fro') < 0.1`，只检验完整仿射对 H1/H2 基线的
  非劣性，不声称交叉校正优越。

## 6. 强化证据通过条件

控制器证据门要求全部满足：

- 至少 2 个会话、6 个校准块；至少 5 个校准块满足正定椭圆、径向残差 P95
  不超过 0.15、规范幅度/残差比不低于 10；
- 完整仿射成功率不低于 `92/96`，每个目标至少在 `5/6` 校准块成功；
- pooled RMS 不超过 0.40 rad，P95 不超过 0.75 rad，任一块 RMS 不超过 0.50 rad；
- 对强化 H1/H2 基线非劣：`RMS_full-RMS_H1H2` 的单侧 95% 上界小于 0.05 rad；
- 完整仿射相对 H1-only 基线的成组置信区间排除零。

完整强化证据还要求：上述控制器证据门通过，且每个块都有隔离的
`truth_prepost.npz` 和稳定的独立验证通道 ID。若缺后者，分析器必须输出
`enhanced_evidence_ready=false`。该字段只评价本协议定义的扩展证据，不评价论文
是否可以投稿或接收。

任何中断或异常块都必须保留 `manifest.json` 并计入失败块；不得删除后做完整案例分析。

## 7. 数据目录与命令

真实数据写入新目录 `data/exp/acceptance/<run-id>/`，不会覆盖现有
`data/exp/results.json`。每个会话运行示例：

```bash
/opt/miniconda3/bin/python scripts/measure_bench.py acceptance \
  --accept-run-id 20260710_day1 --session-id 20260710_day1 \
  --accept-repeats 3 --device-id MZM-ANON-01 \
  --firmware-rev <git-commit> --ambient-c <temperature> \
  --operator <initials> --instrument-ids <stable-id-list>
```

第二个日期使用新的 `run-id` 与 `session-id`。完成后聚合：

```bash
/opt/miniconda3/bin/python scripts/analyze_mzm_acceptance.py \
  data/exp/acceptance/20260710_day1 \
  data/exp/acceptance/20260711_day2 \
  --output build/mzm_acceptance_analysis.json
```

工具链烟雾测试只能写入 `build/exp_sim/`，且永远不能通过强化证据门：

```bash
/opt/miniconda3/bin/python scripts/measure_bench.py acceptance --sim \
  --accept-run-id smoke --accept-repeats 2 --n-grid 4 --iters 8 \
  --n-points 31 --n-blocks 4 --accept-eval-repeats 2
```

## 8. 文件合同

- `protocol.json`：固定参数、随机种子、控制器、真值口径、仓库 commit 和元数据；
- `checksums.json`：会话内全部数据文件 SHA-256；
- `rep_XX/vpi.csv`、`calib.npz`、`calib_fit.json`：独立标定块；
- `rep_XX/acceptance_lock.npz`：执行顺序、初值、全部误差/轨迹/成功标志；
- `rep_XX/truth_prepost.npz`：隔离验证通道的块前/块后扫描；
- `summary.json`：单会话描述性结果，不自动回填论文；
- 聚合分析 JSON：跨会话 bootstrap、逐项 gate 和限制说明。

任何论文数值回填都必须在真实数据、校验值、双稿 `make check` 和重新审稿同时通过后
进行；仿真目录中的结果不得进入论文实验表。
