# `paper_mzm_zh.tex` 一区投稿前全面审稿报告

审稿日期：2026-07-15  
目标期刊标尺：以 *Journal of Lightwave Technology*（JLT）为主，辅以 *Optics Express* 研究论文标准  
审稿范围：理论、方法、实验、统计、图表、结构、语言、事实、参考文献、IEEE 版式与可复现性  
审稿方式：编辑初筛 + 系统辨识/控制 R1 + MZM/微波光子学 R2 + 表达/图表 R3 + Devil's Advocate；同时审计原始 `.npz`、采集/绘图代码、PDF 和 Zotero 文献库  

## 修订进度（随每批修复更新）

### 2026-07-15，阶段 A1：证据口径与周期--2诊断

| 审稿项 | 状态 | 已完成修复 | 尚需完成 |
|---|---|---|---|
| C1：246 mrad 掩盖目标点极限环 | **PARTIALLY RESOLVED** | `lock_affine`/`lock_h1match` 改为以真实末状态评分；尾段均值仅保留为诊断。`stage_lock` 保存逐目标 tail mean/std/RMS/P95、period-2 amplitude、lag-1、sign-flip 和 rail 状态；headline 门只依赖预先定义的绝对误差与动态健康条件，不再依赖“击败 H1”。稿件已将 246/342 mrad 改称“平均命令静态评价”，明确报告 6/16 个目标极限环与 571 mrad 尾段合并 RMS。 | 重新整定后采集稳定的随机化 full-grid 数据；旧数据仍不能成为锁定性能证据。 |
| C2：3 h 记录被误写为稳定性 | **PARTIALLY RESOLVED** | 长时采集只允许从通过抖动/period-2门的窗口学习残差阈值；不健康运行不再写入稳定性 headline。图 11 改为同时显示原始偏压命令、逐周期误差、DMM 稀疏点及前 24 周期插图。稿件明确报告 827 mrad、lag-1 = −0.995、100% 符号翻转，并撤回“0.99 V 慢漂”和长期稳定性解释。 | 控制器稳定后重做 3 h+ 运行并通过 temporal health gate。 |
| E4：结果导向自动提升 | **RESOLVED IN CODE** | 删除 `affine RMS < 0.5 × H1 RMS` 作为纳入条件；`beats_h1` 和两个同源真值的一致性仅作为描述性字段。 | 新实验仍须保存所有 full-grid run manifest。 |
| M1：闭环稳定性与时延模型缺失 | **PARTIALLY RESOLVED** | 正文新增无时延 `e[k+1]=(1-G)e[k]`、`0<G<2`、单调收敛条件，以及含 `d` 周期时延的特征多项式；明确实际有效增益还受执行斜率与局部解调斜率影响。 | 需要用实物预检测量端到端时延和局部斜率，并报告冻结增益的裕度。 |
| acceptance protocol 动态健康门 | **RESOLVED BEFORE DATA COLLECTION** | 协议由 v1 升至 v1.1；确认升级时尚无真实 acceptance 数据。新增固定候选集的增益预检、period-2 amplitude 门和对应文件字段；`acceptance_lock.npz` 现保存 tail RMS/P95、period-2、lag-1 与符号翻转率。 | 按 v1.1 完成至少 2 个会话/6 个校准块。 |
| R2-1：方法分类与基线误引 | **PARTIALLY RESOLVED** | 引言将单 MZM 任意点、IQ 相关检测和 null/quadrature 优化分开；仿真 H1 曲线改称“本文构造的单坐标消融”，删除 Wang 2010/Yuan 2019/Peng 2025 对该基线的错误背书。 | DOI、页码、nearest-work 表和完整 SOTA 表在文献批次处理。 |
| 数据字典与数字合同 | **RESOLVED FOR LEGACY DATA** | `data/exp/README.md` 明确 `lock_sweep.npz` 和 `stability.npz` 是含周期--2的旧诊断记录；`check.py` 的实验行关键词改为“平均命令静态评价”“长运行诊断”“重定标后尾段”。 | 新实测通过后再更新 `results.json` 和论文 headline。 |

验证记录：代码通过 `py_compile`；`--sim` 标定、16 点 lock、短时 stability 和完整 acceptance 数据合同烟雾测试通过；新 stability 健康门能拒绝未完成/不合格运行；`make exp-figs` 已重生成实验图并人工检查周期--2可见性。`paper_mzm_zh.tex` 编译为 10 页，无 undefined references；双稿 `make check` 为 **0 FAIL / 4 WARN**。WARN 仍是未引用 labels 和 `build/sim_output.txt` 缺失，另有一处 12.45 pt 的既有 minor overfull box。

### 2026-07-15，阶段 A2：台架连通性检查与增益预检自动化

| 审稿项 | 状态 | 已完成修复/检查 | 尚需完成 |
|---|---|---|---|
| 台架连通性 | **BLOCKED AT USB DATA PATH** | 真实 `bringup --no-scope` 在任何偏压输出前安全停止：macOS 未枚举偏压板所需的 `/dev/cu.usbmodem*`。DM858E LAN 通信与身份查询正常（`DM8E275002095`）；USB 树仅见 “STM32 STLink”，`pyocd list` 未见可用探针。 | 检查 MCU 数据 USB 口、数据线和板端供电/固件枚举；CDC 出现后重新运行 bringup。 |
| M1：冻结稳定控制增益 | **IMPLEMENTED; REAL RUN PENDING** | 新增 `gain-preflight` 一键阶段。候选、四目标、双侧初值、40 周期和全部门限在代码中固定；保存最终误差、tail std/RMS/P95、period-2、lag-1、符号翻转率、轨迹、末偏压、逐候选判定、冻结增益和 SHA-256。预检写入独立 `preflight/<run-id>`，不修改论文主结果。 | CDC 恢复后执行真实预检；若无增益通过，停止 acceptance 并修正控制器。 |
| 预检可复现性 | **RESOLVED IN TOOLING** | 仿真烟雾测试完整通过，最大通过候选为 `G=0.20`（仅验证流程，不能用于实物冻结）；协议文档补充真实/仿真命令和文件合同。 | 实物结果必须使用新的真实目录和完整元数据，不能引用仿真选择。 |

本批没有采集、修改或提升任何真实 headline 数据，也没有向台架输出偏压。当前投稿决定不变：关键闭环证据仍等待稳定增益预检和多会话 acceptance 数据。

### 2026-07-15，阶段 A3：预检—验收联锁与异常留痕

| 审稿项 | 状态 | 已完成修复/验证 | 尚需完成 |
|---|---|---|---|
| v1.1 不可绕过性 | **RESOLVED IN CODE** | 真实 `acceptance` 必须引用 `--preflight-run-id`；校验目录完整性、全部 SHA-256、`manifest.status=complete`、非仿真标志、设备/固件/仪器身份与 `measure_bench.py`/`exp_common.py` 哈希。冻结增益从原始 NPZ 的逐轨迹 `passed` 重新计算，并与 NPZ、summary 和显式参数三方核对。 | 真实预检完成前，任何 acceptance 都会被拒绝。 |
| 动态门边界正确性 | **RESOLVED** | 周期--2幅度改为先对偶/奇圆均值差做 wrap、再除以 2；跨 `+3.13/-3.13 rad` 单测得到 `0.01159265 rad`。rail 门覆盖规定初值及全部偏压命令；无法实现 `±1 rad` 初值时中止，不再静默裁剪。 | 在实物预检结果中报告每个候选的最差 tail std、period-2 和 rail fraction。 |
| 中断与数据完整性 | **RESOLVED IN TOOLING** | 预检和正式锁定均逐轨迹原子 checkpoint；异常、人工 Ctrl-C 和无候选通过都会保留 manifest、summary、checksums 与已完成轨迹。合成 `KeyboardInterrupt` 测试确认当前块标记 failed，且会话级 summary/checksums 仍生成。真实退出路径关闭 RF、`gen reset` 并将偏压归零。 | 实际采集期间仍需记录任何人工急停/通信故障原因，失败块不得删除重跑。 |
| 协议参数冻结 | **RESOLVED IN CODE** | 真实预检固定 181 点、16 blocks、cal avg 4、lock avg 1、0.15 V；真实 acceptance 另固定 16 目标、40 周期和 5 次 DMM 评价。只有 `--sim` 可缩减参数做烟雾测试。 | 使用协议命令采集，不在首个真实 run 后修改门限。 |

本批离线验证：`py_compile`、跨分支周期--2单测、完整校验和/冻结增益联锁、冲突增益拒绝、人工中断留痕及双稿 `make check` 均通过；`make check` 仍为 **0 FAIL / 4 WARN**。仿真预检选出的 `G=0.20` 仅验证工具链，不能授权或替代真实台架增益。

### 2026-07-15，阶段 A4：更换偏压板后的固件恢复与模拟量 bringup

| 审稿项 | 状态 | 已完成修复/验证 | 尚需完成 |
|---|---|---|---|
| 偏压板固件 | **RESOLVED** | 从 `/Users/ckdfs/code/biascontrol_h523` 的本地 `main` HEAD `8b1b1c292dd1e06257a93a4a07f3088e96b1d2cf` 全量重建；该提交是唯一包含论文台架所需 generic `gen/acq` 前端的合适版本，支持 12 个采集频点。Debug ELF 为 ARM EABI5/Cortex-M33，FLASH 141,488 B，ELF SHA-256 `07a7e397c06a3a022b3934f96adc703934302465196efd911b5a1451ee4f209f`；BIN 与仓库 6 月产物逐字节一致，SHA-256 `acc2b33e31cf56f70610c85ebe4ee6bc1f6717a6100f37556b1f4836b478d7b6`。使用 pyOCD 0.43.1、目标 `stm32h523cetx`、探针 `066FFF505754675087091823` 成功擦写。 | 固件未内建 commit/version 查询；后续真实会话必须继续在 metadata 中记录上述 commit 和文件哈希。 |
| 刷写后数字链路 | **PASSED** | `/dev/cu.usbmodem2103` 正常枚举；状态为 `IDLE`、`Bias=0.000 V`、`Lock=NO`、`Cal=INVALID`，无 FAULT。`gen reset/bias/pilot/show` 与 `acq reset/add/show/run` 均真机回显，1/2 kHz 双频配置正常；退出后显式清导频并归零偏压。 | 在模拟量链路恢复后，用正式 bringup 再确认无 USB 丢命令和 DRDY 超时。 |
| 更换板后的模拟量链路 | **FAILED; PREFLIGHT BLOCKED** | 四点 bringup（−6/−3/0/+3 V）安全完成，但板载 CH1 固定在约 1.19 V、接近 1.2 V 满量程；DM858E 仅约 −0.06 V 且不随偏压变化。零偏压无导频时 CH0 为约 −0.082 V、CH1 为 1.1906 V；四点 0.10 V 导频的 H1 仅 8–19 µV、H2 仅 3–6 µV，均属噪声量级。结果表明当前没有有效 DAC--MZM--PD 响应，不能进入 Vpi 扫描或增益预检。 | 检查激光器与 PD/TIA 供电、PD/TIA 到新板 CH0/CH1 接线、DAC-A 到 MZM 偏压线及 MZM RF 口接地；恢复后重跑 bringup。 |
| 外部交叉验证 | **PARTIALLY AVAILABLE** | DM858E LAN/SCPI 正常。 | SDS824X HD `192.168.99.157:5025` 当前连接超时；若需要 DE2 交流交叉验证，检查其电源/LAN。 |

本批没有创建或改写 `data/exp/results.json`、acceptance 真实目录或论文实验 headline。固件刷写完成，但实验推进仍被模拟量链路无响应阻塞；在恢复可辨识的直流传输曲线和 H1/H2 之前，不得运行正式增益预检。

### 2026-07-15，阶段 A5：模拟电源恢复后的二次 bringup

| 审稿项 | 状态 | 已完成修复/验证 | 尚需完成 |
|---|---|---|---|
| 板载模拟链路 | **PASSED** | 开启 ±12 V 与 5 V 电源后，四点 board DC 恢复随偏压变化：−6/−3/0/+3 V 对应约 0.883/0.272/0.600/1.178 V，不再固定于 1.19 V。0.10 V 导频下 H1 在四点约 0.022–0.817 V，H2 约 4.3–35.7 mV，明显高于此前微伏噪声，确认 DAC、导频、MZM、PD/TIA 与 Goertzel 主链工作。 | 正式扫描前仍需确认最高 DC 点不持续削顶，并由 DMM 提供未削顶真值。 |
| DM858E 真值通道 | **FAILED; PREFLIGHT STILL BLOCKED** | 仪器 LAN/SCPI 和 IDN 正常，但四点读数仅约 −0.012 至 +0.014 V，重复样本在约 ±20 mV 内漂动，与 board DC 和偏压无相关；表现为 DMM 输入悬空、端子/测试点接错或缺少共地。 | 将 DM858E 直流输入重新接到新板 DE4/PD 直流测试点并确认公共地；预期应得到随偏压变化、与 board CH1 在未削顶区近似一致的正向直流曲线。 |
| SDS824X HD | **NOT REQUIRED** | 本轮按作者确认使用 `--no-scope`；示波器关闭不影响 MZM 正式主路径。 | 无。 |

二次 bringup 与 H1/H2 诊断结束后均执行 `gen reset` 与 `dac 0`；板子保持 `IDLE`、0 V。没有写入真实预检/acceptance 目录或论文 headline。下一步只需恢复 DM858E 的 DE4 直流连接，然后重跑 bringup；在 DMM 曲线有效前不启动正式 Vpi 扫描。

### 2026-07-15，阶段 A6：DM858E 重接后的 bringup 通过

| 审稿项 | 状态 | 已完成修复/验证 | 尚需完成 |
|---|---|---|---|
| DM858E 真值通道 | **PASSED** | 重接 DE4/PD 直流测试点后，−6/−3/0/+3 V 的 DMM 均值为 0.873/0.002/0.784/1.454 V，恢复完整 MZM 传输响应；每点三次读数跨度为 13.4–29.5 mV。板载 CH1 同时为 0.839/0.189/0.604/1.170 V，在高光功率处呈已知满量程压缩，因此后续继续以 DMM 为未削顶直流真值。 | 在真实预检的双向 151 点扫描中量化方向差与拟合质量。 |
| H1/H2 与偏压响应 | **PASSED** | 同一四点 0.10 V 导频测得 H1 约 0.029–0.759 V、H2 约 2.8–31.2 mV，均显著高于噪声且随工作点变化；未见 USB 丢命令、DRDY 超时或板载 FAULT。 | 正式预检使用冻结的 0.15 V 导频和 16-block 采集参数。 |
| 真实增益预检启动门 | **READY; METADATA PENDING** | 固件 commit/hash、探针 ID、DM858E 序列号、匿名器件/光源/PD 标识方案均可在采集前冻结；硬件退出状态为 `IDLE`、0 V、`Lock=NO`。 | 记录当前室温后创建不可变 `data/exp/preflight/<run-id>` 并开始 v1.1 预检。 |

本批仍未创建真实预检目录或修改论文 headline。bringup 已从“模拟量链路失败”转为通过；下一动作是冻结完整元数据并执行真实增益预检。

### 2026-07-15，阶段 A7：首个真实 v1.1 增益预检（未通过）

真实目录：`data/exp/preflight/20260715_gain_board2/`。元数据在采集前冻结：室温 28.0 °C，器件 `MZM-ANON-01`，固件 `8b1b1c2`，板卡探针 `066FFF505754675087091823`，DMM `DM8E275002095`；示波器和 RF 均未使用。目录 8/8 文件 SHA-256 复核通过，`manifest.status=failed`，板卡结束状态为 `IDLE`、0 V、`Lock=NO`。没有启动 acceptance。

| 候选增益 | 通过轨迹 | 最大最终误差 | 最大 tail std | 最大 period-2 | 判定与失败模式 |
|---:|---:|---:|---:|---:|---|
| 0.05 | 3/8 | 425.9 mrad | 100.8 mrad | 8.0 mrad | 主要为 40 周期内收敛不足；无持续周期二 |
| 0.10 | 7/8 | 343.4 mrad | 89.1 mrad | 50.101 mrad | 唯一失败比 50 mrad 门高 0.101 mrad；严格按未取整值失败 |
| 0.15 | 3/8 | 449.3 mrad | 1128.6 mrad | 1128.5 mrad | `π/2` 与 `3π/2` 出现持续两周期极限环 |
| 0.20 | 3/8 | 404.5 mrad | 1167.5 mrad | 1167.5 mrad | 同上，弱轴持续失稳；无撞轨 |

标定结果：双向扫描 `Vπ_up/down=5.2497/5.2371 V`，方向差 12.5 mV，平均 5.2434 V；无标签椭圆 `κ(A)=49.884`，自检中位/P95 为 47.7/101.2 mrad。全部候选 rail fraction 为 0。

逐周期复核区分了瞬态与真正极限环：`G=0.10` 唯一失败轨迹的最后 6/8/10/12 周期最大 period-2 分别为 24.8/41.9/41.7/38.7 mrad，说明 40 周期尾窗仍含较早瞬态；`G=0.15/0.20` 的末四周期仍在约 `+1.1/-1.1 rad` 交替。由此，下一协议版本不得放宽误差、std 或 period-2 门；最小候选修复是保持候选集合不变，将预检和正式控制观察长度从 40 增至 60 周期，再用全新目录重跑全部轨迹。该变化发生在任何 acceptance 数据采集之前，旧 v1.1 失败目录永久保留且不参与新版本通过判定。

### 2026-07-15，阶段 A8：v1.2 最小协议修订冻结

| 审稿项 | 状态 | 已完成修复/证据 | 后续硬门 |
|---|---|---|---|
| 失败后协议修改的可归因性 | **RESOLVED BEFORE ACCEPTANCE** | v1.2 只把预检和正式 acceptance 的控制观察长度由 40 增至 60 周期；候选 `G={0.05,0.10,0.15,0.20}`、四目标、双侧初值、尾段比例及误差/std/period-2/rail 门全部不变。驱动新增独立 `--accept-iters`，真实运行固定为 60，避免 legacy `--iters` 绕过。 | v1.2 必须使用新目录、新 Vpi 扫描、新椭圆标定和全部 32 条轨迹；不得复用 v1.1 的通过轨迹。 |
| v1.1 失败留痕 | **RESOLVED** | `data/exp/preflight/20260715_gain_board2/` 保持 `manifest.status=failed` 与完整 SHA-256，不改写、不删除；v1.2 loader 明确拒绝其授权 acceptance。 | 新预检若仍无候选通过，立即停止并另行预注册控制/采集修改，不再延长周期或放宽门限。 |
| 修改的证据基础 | **SUPPORTED** | 独立只读复核确认：`G=0.05` 失败轨迹单调收敛且 period-2 仅 1.8--8.0 mrad；`G=0.10` 仅一条轨迹以 50.101 mrad 超过 50 mrad 门，其最后 6--12 周期 period-2 已低于门限；`G=0.15/0.20` 的正交点局部斜率约为名义斜率的 9--13 倍，形成持续交替轨道，延长观察不会把它误判为稳定。 | 预期可通过候选是 `G=0.10`，但选择仍由全部预注册轨迹的未取整值决定。 |
| 环境与身份冻结 | **READY** | v1.2 会话沿用稳定器件、固件和仪器身份；环境温度在采集前记录为约 28.0 °C，示波器关闭且不进入本协议数据链。 | 新目录的 protocol/manifest/checksums 必须记录并锁定这些元数据。 |

本批采用直接、可审计的失败后修订口径：v1.1 证据表明较低增益需要更长的预定观察窗，而高增益存在真实不稳定性；v1.2 仅修正观察长度，不改变成功定义。更深层的采集瞬态假设（新偏压写入后先丢弃固定 acquisition）保留为潜在 v1.3，不与本次修改合并，以保持失败归因清晰。

离线验证已通过：`py_compile` 无错误；v1.2 仿真预检的 `protocol.json` 记录 `iters=60`，四项门限逐值保持不变；独立 acceptance 参数出现在 CLI 并与 legacy lock 参数解耦；双稿 `make check` 为 **0 FAIL / 4 WARN**。WARN 与前批一致，仅涉及未引用 labels 和缺少 `build/sim_output.txt` 的仿真侧复核，不影响本次协议冻结。

### 2026-07-15，阶段 A9：真实 v1.2 增益预检通过

真实目录：`data/exp/preflight/20260715_gain_v12_board2/`。该运行在 v1.2 冻结和离线验证完成后启动，耗时 5262 s（87.7 min）；环境温度记录为约 28.0 °C，器件、固件、DMM、光源和 PD/TIA 身份与 A7 一致，示波器未使用。`manifest.status=complete`，8/8 文件 SHA-256 逐文件复核一致，NPZ、summary 与 manifest 均给出冻结增益 `G=0.10`。退出后板卡复核为 `IDLE`、0.000 V、`Lock=NO`。

| 候选增益 | 通过轨迹 | 最大最终误差 | 最大 tail std | 最大 period-2 | rail fraction | 冻结判定 |
|---:|---:|---:|---:|---:|---:|---|
| 0.05 | 8/8 | 275.843 mrad | 86.488 mrad | 5.915 mrad | 0 | 通过，但不是最大合格候选 |
| 0.10 | 8/8 | 240.019 mrad | 40.271 mrad | 11.420 mrad | 0 | **通过并冻结** |
| 0.15 | 4/8 | 254.959 mrad | 1137.315 mrad | 1137.251 mrad | 0 | 两个正交目标持续周期--2，失败 |
| 0.20 | 4/8 | 267.726 mrad | 1169.916 mrad | 1169.875 mrad | 0 | 两个正交目标持续周期--2，失败 |

新鲜扫描得到 `Vπ_up/down=5.2373/5.2011 V`，平均 `5.2192 V`，方向差 36.1 mV；椭圆标定 `κ(A)=50.007`，自检中位/P95 为 50.5/110.7 mrad，局部拟合斜率为 0.6342 rad/V。自检 P95 未通过 legacy headline 更新阈值，脚本因此没有修改 `data/exp/results.json` 或论文数字；它不属于冻结的增益动态门。v1.2 的核心预测得到验证：60 周期使 `G=0.05/0.10` 的慢收敛轨迹完整进入稳态窗口，而 `G=0.15/0.20` 的 1.06--1.17 rad 交替轨道持续存在。该结果授权后续 acceptance 使用 `G=0.10`，但本预检本身不作为论文性能证据。

### 2026-07-15，阶段 A10：acceptance 会话 1，校准块 1/3 完成（中期结果）

真实会话目录：`data/exp/acceptance/20260715_accept_v12_s1_board2/`；首块 `rep_00` 的 96/96 条轨迹完整采集并保留，`manifest.status=complete`，无通信故障、人工重跑或 rail 命中。该 block 使用从 A9 自动加载的冻结增益 `G=0.10`，随机化 16 目标、双侧初值与三控制器执行顺序。扫描得到 `Vπ=5.2122 V`（双向差 34.3 mV）；椭圆 `κ(A)=49.914`，自检中位/P95 `53.0/111.0 mrad`。

| 控制器 | RMS | P95 | 最大绝对误差 | 成功轨迹 | 最大 tail std | 最大 period-2 | rail |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full_affine` | 152.9 mrad | 243.3 mrad | 280.3 mrad | 30/32 | 364.7 mrad | 218.3 mrad | 0 |
| `calibrated_h1h2` | 191.5 mrad | 302.7 mrad | 343.4 mrad | 31/32 | 184.6 mrad | 77.0 mrad | 0 |
| `h1_match` | 2071.9 mrad | 2992.6 mrad | 3114.3 mrad | 2/32 | 901.8 mrad | 53.0 mrad | 0 |

`full_affine` 的两条失败均位于非基数中间目标：`φ*=1.18, start=+1` 的 tail std 为 288.4 mrad（period-2 144.6 mrad）；`φ*=4.32, start=+1` 的 tail std/period-2 为 364.7/218.3 mrad。两条轨迹的最终误差分别仅 128.5/90.8 mrad，且均无 rail，证明 acceptance 动态门阻止了“末态看似准确”掩盖交替抖动。强化 H1/H2 在后一个配对点也出现动态失败，说明该局部不稳定性并非完整非对角校正独有。

该 block 的 full RMS、P95 和 30/32 成功率具有积极信号，但不能单独满足预注册证据要求，也不能支持“全周期所有轨迹稳定”。`rep_01` 已自动开始新鲜扫描；在本会话 3 个 block、第二独立会话及成组分析完成前，不更新论文 headline。

### 2026-07-16，阶段 A11：acceptance 会话 1 完成但证据门失败

会话 1 的三个校准块和 288 条控制轨迹均已完成，23/23 文件 SHA-256 复核一致，`complete_acquisition=true`。板卡退出后再次显式执行 `gen reset` 与 `dac 0`，状态为 `IDLE`、0.000 V、`Lock=NO`。会话总体 `controller_evidence_passed=false`，没有更新 `data/exp/results.json` 或论文 headline。

| 校准块 | full RMS | full P95 | full 成功 | H1/H2 RMS | H1/H2 成功 | H1-only RMS | 关键判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| `rep_00` | 152.9 mrad | 243.3 mrad | 30/32 | 191.5 mrad | 31/32 | 2071.9 mrad | 有效标定；full 两条中间目标动态失败 |
| `rep_01` | 188.5 mrad | 272.5 mrad | 30/32 | 188.3 mrad | 26/32 | 2053.7 mrad | 有效标定；full 一条误差门失败、一条动态失败 |
| `rep_02` | 2279.1 mrad | 2721.2 mrad | 0/32 | 2334.8 mrad | 0/32 | 1615.2 mrad | 标定分支/拟合失败后仍错误进入锁定矩阵 |

`rep_02` 的双向 Vpi 数值本身一致（`5.2027/5.1879 V`），但两个等价相位原点由非线性拟合返回在相隔约一个光学周期的分支上，原代码直接作算术平均，打印出 `V0 split=10.6991 V` 并生成错误扫描中心 `−3.4449 V`。随后，恰好一个周期的 DC 标定曲线又被无约束拟合吸引到局部解 `Vpi_ref=1.1657 V`（扫描值 `5.1953 V`），`b_dc` 降为 0.1063 V，无标签自检中位/P95 恶化到 1.410/2.960 rad。采集器仅把它标为“diagnostic only”，却仍执行全部 96 条锁定轨迹，最终 full/H1H2 各 6 次 rail。该 block 必须作为算法失败保留，不能删除或按仪器故障排除。

前两个有效 block 也表明四基数预检不足以保证全网格稳定：`G=0.10` 在每块均有 2/32 条 full 失败，集中于非基数或弱轴邻近目标；失败包括末态误差超 0.35 rad 和 tail std/period-2 超门。v1.2 会话因此不能支持“全周期稳定锁定”，也不能与修复后的数据混合进入主要统计。

下一独立会话暂停。进入 v1.3 前必须同时解决两类已观测失效：其一，将双向 V0 先按 `2Vpi` 等价类对齐再平均，并把单周期 DC refit 约束在扫描 Vpi 的邻域；其二，在进入锁定矩阵前设置不可绕过的标定有效性门，并把增益预检覆盖扩展到正式 16 点网格。阈值、候选和停止规则需在任何 v1.3 实测前冻结；v1.2 全目录永久保留为失败证据。

### 2026-07-16，阶段 A12：v1.3 分支修复、标定硬门与全网格预检冻结

| 审稿项 | 状态 | 已完成修复/验证 | 后续硬门 |
|---|---|---|---|
| V0 周期分支平均错误 | **RESOLVED IN CODE** | `stage_vpi` 现在先把下扫 V0 按 `2Vpi` 移到最接近上扫 V0 的等价分支，再计算平均值；原始 V0、周期平移数、对齐前后 split 及其相位量均写入结果。双向 Vpi 差和对齐后 V0 差均以 0.35 rad 为不可绕过门。 | v1.3 真实扫描必须通过两个方向一致性门；失败目录保留但不得进入标定或锁定。 |
| 单周期 DC 局部拟合 | **RESOLVED IN CODE** | DC refit 使用同块新鲜双向扫描的 Vpi/V0 初始化，Vpi 限制在扫描值 ±15%，`b>0`，V0 限制在相邻物理分支。rep_02 离线回放由错误 `Vpi_ref=1.1657 V` 恢复为 `5.1799 V`，相关系数 0.99908，`RMSE/|b|=0.03043`。 | 真实块要求 `RMSE/|b|<=sin(0.05)` 且 refit/scan Vpi 差折算相位不超过 0.35 rad。 |
| 坏标定仍进入锁定矩阵 | **RESOLVED IN CODE** | 预检和 acceptance 的 Vpi/标定调用均启用 `require_valid=True`；有限正参数、自检中位/P95 ≤50/200 mrad、DC 拟合和 Vpi 一致性任一失败，都会先写数据与质量字段，再抛错并停止该块闭环。旧 v1.2 三块按新口径回放的自检中位数为 53.0、55.1、66.1 mrad，故都会被 v1.3 如实拒绝。 | 50 mrad 门沿用既有 headline 门，不因已观察到的轻微超限事后放宽；若新鲜预检失败，则停止而不是调门。 |
| 四基数预检遗漏中间目标 | **RESOLVED IN PROTOCOL/CODE** | v1.3 预检与正式实验使用相同 16 点网格和双侧初值；重复呈周期--2的 `G=0.15/0.20` 从安全候选集中删除，只评估 `G={0.05,0.10}`，并选择通过全部 64 条轨迹的最大候选。60 周期、后 40% 尾窗及误差/std/period--2/rail 门保持不变。 | 只有新 v1.3 完整预检、校验和、身份和源码哈希全部通过，才能授权新 acceptance；v1.2 数据不得混合。 |

协议文件已升至 2026-07-16 v1.3，并明确本轮不加入额外 acquisition discard，以避免同时改变多个因素。离线验证包括：`py_compile`；rep_02 原始数据断言回放（对齐后 `V0=1.75035 V`）；完整 16 点仿真预检（两档候选 64/64 轨迹合同生成，选择 `G=0.10`）；短仿真 acceptance 的标定、manifest、summary 和失败 gate 留痕；`git diff --check`；双稿 `make check` 为 **0 FAIL / 4 WARN**。WARN 仍仅为未引用 labels 与缺少 `build/sim_output.txt` 的仿真侧复核。尚未创建任何 v1.3 真实目录，也未修改论文 headline。

### 2026-07-16，阶段 A13：真实 v1.3 全网格预检失败（未授权 acceptance）

真实目录：`data/exp/preflight/20260716_gain_v13_board2/`。运行在 A12 的代码、协议、离线回放和仿真 gate 全部冻结后启动，耗时 8664 s（144.4 min）；温度记录约 28.0 °C，器件、固件与仪器身份延续前序会话，示波器关闭。64/64 条预检轨迹完整采集，8/8 文件 SHA-256 独立复核一致；`manifest.status=failed`、`selected_gain=null`，因此没有启动或创建新的 acceptance 会话。退出后再次执行 `gen reset` 和 `dac 0`，板卡状态为 `IDLE`、0.000 V、`Lock=NO`、`Cal=INVALID`。

双向扫描和标定硬门均按预期工作。`Vpi_up/down=5.2115/5.1924 V`，平均 `5.2020 V`；Vpi 方向差折算 0.0115 rad，V0 对齐后差 0.3599 V、折算 0.2173 rad，均低于 0.35 rad。受约束 DC refit 的 `RMSE/|b|=0.02228`，refit/scan Vpi 差折算 0.2277 rad；无标签椭圆 `kappa(A)=49.985`，自检中位/P95 为 48.804/107.777 mrad。全部标定 gate 通过，证明本次停止不是 rep_02 型错误分支或局部拟合故障。

| 候选增益 | 通过轨迹 | 最大绝对误差 | 最大 tail std | 最大 period--2 | rail | 失败性质 |
|---:|---:|---:|---:|---:|---:|---|
| 0.05 | 12/32 | 584.830 mrad | 98.974 mrad | 8.849 mrad | 0 | 动态稳定，但有限观察窗下存在大且方向相关的负误差 |
| 0.10 | 7/32 | 568.660 mrad | 69.406 mrad | 13.797 mrad | 0 | 动态稳定，多数目标收敛到与 DMM 评价相差约 0.35--0.57 rad 的固定点 |

两档的所有失败都来自最终绝对误差门；没有 tail-std、period--2 或 rail 失败。G=0.10 在 v1.2 曾发生交替振荡的中间目标本轮也保持低 period--2，说明 v1.3 已把主要故障从“动态不稳定/坏标定仍运行”推进到更清晰的“无标签椭圆内部相位与 DMM 评价相位的全周期系统偏差”。尤其在 `phi*=2.36 rad`，G=0.10 双侧分别稳定到 −537.2/−526.0 mrad、tail std 仅 8.5/5.5 mrad；这不能通过延长观察窗或放宽误差门解释。

本次 full-grid 还直接否定了四基数预检的充分性：同一台架的 v1.2 四基数曾给出 G=0.10 的 8/8 通过，而本轮完整 16 点仅 7/32。下一版不得继续调增益或事后改 0.35 rad 门；应先用本目录保存的 demod/bias 轨迹分解内部闭环残差与 DMM 外部残差，检查 DC gauge 的旋转/反射锚定、目标相位定义和局部 bias-to-phase truth 是否一致。v1.3 目录永久作为完整失败证据保留，不与任何后续数据混合，也不更新论文 headline。

### 2026-07-16，阶段 A14：truth-map estimand 缺陷确认与规范诊断工具冻结

独立方法学审计和原始数据回放得到一致结论：G=0.10 的 32/32 条轨迹全部通过 temporal gates，最后一次内部 demod 误差 RMS 仅 13.8 mrad；固定 scan map 与内部 tail mean 的公共差在 G=0.05/0.10 分别约为 −405.9/−407.6 mrad。60 周期不足、wrap 算术和标定时的 O(2) 反射/π 分支均不能解释该共同偏移。v1.3 的 `−0.35` 至 `−0.57 rad` 只能表述为“早期固定电压 map 与在线内部相位参考的系统差”，不能声称已经用 contemporaneous external truth 证实了真实相位误差。

同时确认一个明确的 gate 覆盖缺口：当前标定自检比较 ellipse 与后续单周期 refit map，而预检起点和终点评分使用更早的 bidirectional scan map。在同一 `calib.npz` 上，ellipse 对 primary scan map 的 median/P95/max 差为 108.8/294.2/334.8 mrad；按既有 50/200 mrad 预算，本应在锁前失败。refit/scan 的 Vpi mismatch 0.2277 rad 虽低于 0.35 rad 上限，却已显著消耗终点误差预算。下一控制协议若仍使用 scan map，必须增加不可绕过的 primary-map concurrence gate；同时仍需 contemporaneous truth，因为整个预检历时 2.407 h，目标顺序又与时间完全混杂。

为避免在根因未分离时继续修改控制协议，新增并在首个实测前冻结：

- `reviews/mzm_gauge_audit_protocol.md`：排除于主分析的 no-feedback 诊断；
- `scripts/audit_mzm_gauge.py`：新鲜 Vpi/ellipse 后，在四基点、双侧接近、`continuous/frontend_reset/post_reset_delay60` 三条件下，连续保留第 1--6 次原始 I/Q、board DC、同步 DMM 和时间戳；保存 partial NPZ、manifest 与 SHA-256，异常也不删除。

该诊断专门区分首采瞬态、慢 settling/滞回、物理 V0 漂移和 AC observer gauge 变化，不选择增益、不更新论文 headline，也不得追认 v1.3。工具已通过 `py_compile`、既有 calibration 的目标偏压内插测试（四基点约 2.571/4.844/7.282/−0.014 V）和 `git diff --check`。在诊断结果出来前，v1.4 preflight/acceptance 保持未冻结、不得启动。

### 2026-07-16，阶段 A15：首个 gauge-audit 外部中断与留痕恢复

首个真实诊断目录 `data/exp/diagnostics/gauge_audit/20260716_gauge_v1_board2/` 在完成 Vpi 上扫 151 点和下扫前 9 点后，被前台 PTY 会话的外部中断终止；这不是硬件通信、算法 gate 或人工按结果停止。由于进程未获得 Python `finally` 执行机会，恢复审计显式补写 `manifest.status=failed` 与三文件 SHA-256，永久保留 160 条 `vpi.csv`，不覆盖、不拼接到下一运行。中断后板卡已执行 `gen reset/dac 0` 并复核为 `IDLE`、0.000 V、`Lock=NO`。

工具随后增加 SIGINT/SIGTERM 路由，使正常终止信号先进入原有 manifest/checksum `finally`；新的长采集改为独立后台进程并记录外部日志，避免用户状态消息再次切断采集 PTY。该修复不改变冻结的 gauge-audit 目标、采集次数、条件或判别规则。下一运行必须使用全新 run-id，从 302 点双向扫描重新开始。

### 2026-07-16，阶段 A16：gauge-audit v1.0 被标定硬门正确拦截

第二个真实诊断目录 `data/exp/diagnostics/gauge_audit/20260716_gauge_v1b_board2/` 在独立后台会话中完成 302 点双向 Vpi 扫描和 181 点椭圆标定，随后因预先冻结的标定中位误差门失败而停止。`manifest.status=failed` 明确记录 `calibration quality gate failed: selfcheck_median_pass`；三种 reset 条件、四基点和双侧接近均未执行，`gauge_audit.npz` 的正式与预偏压行数均为 0。因此本轮没有闭环、没有 acceptance 授权，也没有修改 `data/exp/results.json` 或论文 headline。7 个数据/元数据文件的 SHA-256 已逐项复核一致；退出后再次执行 `gen reset/dac 0`，清理前后板卡均为 `IDLE`、0.000 V、`Lock=NO`、`Cal=INVALID`。

本轮把 v1.3 的“约 0.4 rad map 差”进一步定位为显著的时间变化 DC 工作点，而非 Vpi 数值或坏局部拟合。运行总长 31.23 min，其中 Vpi 扫描约 9.3 min、标定约 22 min。双向扫描给出 `Vpi_up/down=5.3081/5.1362 V`、平均 `5.2221 V`，方向差折算 0.1034 rad；上/下扫 V0 仅差 0.0570 V、折算 0.0343 rad，均通过既有 0.35 rad 门。但扫描的 DMM 峰值原点为 `V0=0.1929 V`，随后同轮单周期 DC refit 已移至 `V0=0.8148 V`，相差 0.6219 V，按 refit `Vpi=5.1595 V` 折算约 0.379 rad。primary scan 与 refit phase map 的 median/P95/RMS 差为 378.7/413.0/379.3 mrad；若固定原 scan 的 Vpi/V0，标定 DC 曲线仅有相关系数 0.9308、`RMSE/|b|=0.2785`，允许 V0 更新后则恢复至 0.99924/0.02770。refit/scan 的 Vpi 差仅折算 0.0377 rad，完整 DC refit 的相关系数 0.99931、`RMSE/|b|=0.02645`，说明主导项是相位原点移动而非 Vpi 尺度。失败仅来自 ellipse--contemporaneous-refit 自检中位/P95 `65.764/131.877 mrad` 中的中位项超过 50 mrad。与 A13 预检的扫描 `V0=2.5642 V` 相比，本轮新鲜扫描又移动约 2.371 V（约 1.43 rad），而 Vpi 仍处于约 5.2 V。

这些结果支持“分钟级有效 DC 传输曲线漂移已经消耗标定误差预算”，同时也揭示当前单调扫描把时间漂移与偏压方向/历史混杂。由于 v1.0 在进入预定三条件诊断前即被硬门拦截，本轮尚不能判断 frontend reset 是否引入额外 AC gauge 旋转，也不能据此选择 acquisition discard。下一步不得重跑相同协议、延长控制周期或放宽 50/200 mrad 门；应先冻结一个更短的稳定性诊断，用重复/交错 DC 锚点量化 `V0(t)`，规定热稳定等待和漂移率门，再决定采用缩短/随机化标定、时间插值规范还是硬件热稳定修复。v1.4 preflight 和新 acceptance 继续保持未授权。

### 2026-07-16，阶段 A17：短时 V0 稳定性门冻结并实现

在再次输出真实偏压前新增 `reviews/mzm_v0_stability_protocol.md` 和 `scripts/monitor_mzm_v0.py`。该纯 DMM、无闭环诊断固定使用 A16 的 `Vpi=5.222139 V` 和 contemporaneous `V0=0.814764 V`，在约 −3.102/−0.491/2.120/4.731 V 四个安全偏压上执行正四点--逆四点回文采样；6 个 epoch 的起点间隔 120 s，总跨度约 10 min。逐点保存绝对时间、方向、顺序、偏压和 DMM 值，异常也生成 partial summary、manifest 与 SHA-256，结束路径强制 `gen reset/dac 0`。

通过定义在任何实测前固定为四门同时成立：每个 epoch 的正/逆 `V0` 分裂不超过 0.05 rad；每个 epoch 的固定 Vpi 余弦拟合 `RMSE/amp<=sin(0.05)`；最后 5 个 epoch 的 `V0` 峰峰值不超过 0.05 rad；Theil--Sen 斜率外推 30 min 不超过 0.05 rad。该预算不替代也不放宽 50/200 mrad 标定门或 0.35 rad 锁定终点门。脚本已通过 `py_compile`、无噪声合成曲线的 V0/残差断言和 `git diff --check`。

同时补记 A16 的幅度风险：181 点标定中 board CH1 有 50 点精确到 1.2000 V，明确属于已知 DC 监视通道钳位；所选 AC 观察分量的合成幅度最高约 1.1895 V，距 ±1.2 V 仅约 0.9%，但当前固件未保存 ADC raw min/max 或 near-rail count，故不能证明或排除 CH0 瞬时削顶。短时 V0 门使用未削顶 DMM，避免把 CH1 钳位误作 DC 真值；下一 gauge 版本仍必须加入逐点时间戳、交错 DMM sentinel，并在固件/采集输出 raw extrema 与 near-rail 计数后才评估 AC 削顶。由于 A16 的时间、第二次 frontend prepare 和单向偏压顺序彼此混杂，现阶段统一称“时间/配置/偏压历史相关漂移”，不直接归因为温度。

### 2026-07-16，阶段 A18：首个 V0-stability 运行暴露静态 DAC 路径错误

首个目录 `data/exp/diagnostics/v0_stability/20260716_v0stab_v1_board2/` 在 epoch 1 后被主动停止并永久保留。首个回文块的拟合幅度仅 2.62 mV、`RMSE/amp=5.143`、正逆分裂 2.755 rad，明显不是已知约 1.5 V 峰峰值的 MZM 传输曲线。根因是初版工具在明确“不运行 acq”的同时使用了 `gen bias`：该命令只更新波形发生器配置，必须由 `acq run/gen start` 才实际执行；因此四个命令偏压没有施加到静态 DAC。该 epoch 不能用于判断台架漂移，也不是按结果停止。

收到异常后在第二个 epoch 前发送 SIGINT；信号按预定路径生成 `manifest.status=failed`、8 行 partial CSV、summary 与 4/4 匹配的 SHA-256，并清理到 `IDLE`、0.000 V、`Lock=NO`。工具已把唯一输出调用改为直接 `dac <V>`，这与冻结协议的“无导频、静态四点”语义一致，不改变偏压点、epoch、时长或成功门。修复后重新通过 `py_compile` 与 `git diff --check`；下一运行必须使用新 run-id，从 epoch 1 完整重做。

### 2026-07-16，阶段 A19：V0-stability v1.0 完成但暴露换偏压首读瞬态

修复后的真实目录 `data/exp/diagnostics/v0_stability/20260716_v0stab_v1b_board2/` 完成预定 6 个 epoch、48 个正式访问点和约 10 min 时间跨度。`manifest.status=complete` 但 `quality_gate.accepted=false`：6 个 epoch 的方向分裂依次为 0.836/0.058/0.905/1.122/0.912/0.523 rad，只有第 2 个接近 0.05 rad 门；`RMSE/amp` 依次为 0.499/0.0259/0.463/0.930/0.448/0.518；末 5 个 epoch 的 V0 峰峰值 0.3389 rad，稳健斜率外推 30 min 为 0.1592 rad，四项冻结门均未通过。4/4 文件 SHA-256 独立复核一致；板卡清理前后均为 `IDLE`、0.000 V、`Lock=NO`。

这些表面指标不能直接解释为 MZM 在两分钟内反复移动 0.5--1 rad。原始访问顺序显示换偏压后的首个 DMM `READ?` 偶尔仍反映前一状态：例如 epoch 3 从 2.120 V 切到 4.731 V 后首读 1.428 V，几乎等于前一偏压的 1.409 V；在不改变 4.731 V 的下一次读数则降到 0.443 V。六个回文转向点的连续同偏压首/次读差中，有 3 个约为 0.619--0.985 V，另 3 个仅约 0.005--0.011 V，说明该瞬态并非固定一拍、也不能用全序列简单移位修复。它可能来自 DMM 触发/缓冲，也可能来自 DAC--MZM--PD 在大阶跃后的未完成 settling；v1.0 每点只取一次读数，无法区分二者。

因此 A19 只证明“当前无导频快速四点实现没有提供 contemporaneous DC truth”，不能否定或确认 A16 的分钟级 V0 漂移。旧 `stage_vpi/stage_calib` 的 DMM 读取发生在多块 `acq_run` 之后，具有更长驻留时间，故不能把 A19 的首读污染自动追溯到 A16。下一版若继续，必须在每次 DAC 阶跃后保存 priming 读数和至少两个不再换偏压的确认读数，并以确认读数间一致性作为新增硬门；v1.0 数据保留为失败诊断，不做事后删点、移位或重评分。

### 2026-07-16，阶段 A20：V0-stability v1.1 三读确认路径冻结

独立只读取证确认：24 次可辨别电平转换中有 6 次首读陈旧；统一将全部序列移一拍反而恶化拟合，故不是固定通信延迟。仅删除明确陈旧点后，各 epoch 的 `RMSE/amp` 从 0.499/0.026/0.463/0.930/0.448/0.518 变为 0.033/0.026/0.123/0.155/0.154/0.028，仍有三块超过 `sin(0.05)`，证明“只丢一读”不足。

新文件 `reviews/mzm_v0_stability_protocol_v1.1.md` 在首个 v1.1 实测前冻结；工具版本同步为 `v0-stability-v1.1`。每次静态 DAC 阶跃返回后固定等待 0.75 s，连续保存 `priming/confirm_1/confirm_2`，只用后两读均值评分；新增每个 epoch 所有点的 `|confirm_2-confirm_1|/amplitude<=sin(0.05)` 硬门。四偏压、6 epoch、120 s 间隔、正逆分裂、余弦残差、末五块峰峰值和 30 min 外推门完全不变。若两次确认仍不一致，本版失败并停止继续增加 discard。实现已通过 `py_compile`、固定 Vpi 合成曲线断言和 `git diff --check`；旧 v1.0 两目录保持原 manifest 和校验和，不按新路径重评分。

### 2026-07-16，阶段 A21：V0-stability v1.1 仍失败，暂停继续增加等待

真实目录 `data/exp/diagnostics/v0_stability/20260716_v0stab_v11_board2/` 完成 6 个 epoch、48 次偏压访问和每次 3 个 DMM 读数。`manifest.status=complete`、4/4 SHA-256 复核一致，但 `quality_gate.accepted=false`。各 epoch 的方向分裂为 0.124/0.193/2.227/1.116/0.587/1.909 rad，`RMSE/amp` 为 0.735/0.116/3.117/0.597/0.514/1.263，最大确认差/幅度为 0.0456/0.0526/0.1463/0.0663/0.0878/0.1404；只有首块的确认一致性通过，且没有任何 epoch 同时通过原有曲线门。末 5 块 V0 峰峰值为 0.9684 rad，Theil--Sen 斜率外推 30 min 为 2.939 rad。清理前后板卡均为 `IDLE`、0.000 V、`Lock=NO`。

首块已消除明显首读陈旧，但仍出现不可能由单一 V0 平移解释的互补性破坏：相隔一个冻结 Vpi 的两对偏压，其 DMM 功率和分别约为 2.69 V 与 1.59 V；随后各 epoch 又在不同方向和幅度上失真。这说明 v1.1 已把问题从“偶发首帧”推进为“快速大阶跃的 direct-dac 测试条件或路径本身不等价于论文的 gen/acq 条件”。当前数据不能提供稳定 V0 估计，也不能把 2.94 rad 外推解释成真实热漂移。

本轮之后停止继续增加等待、discard 或确认次数，不冻结 v1.2 stability。下一最小动作改为只读审查固件中 legacy `dac` 与 `gen bias + acq run/gen start` 的实际更新路径，并在任何新实测前冻结同偏压、同顺序、同驻留时间的路径对照；若两路径不等价，短时稳定性监测必须使用与 `stage_vpi/stage_calib` 相同的 gen/acq 驱动。gauge audit、v1.4 preflight 和 acceptance 继续未授权。

### 2026-07-16，阶段 A22：固件路径审查排除双 DAC 标度假设

对 `/Users/ckdfs/code/biascontrol_h523` 固件 `8b1b1c2` 的只读审查确认：legacy `dac V` 与 `gen bias A V` 最终都写物理 CH_A，并共享 `board_voltage_to_dac_code()`、`dac8568_write_channel()` 和同一固定 gain/offset；没有两套通道标度、板级校准或隐藏斜坡。`dac` 在命令处理时立即写出；`gen bias` 只更新 RAM，直到 `acq run/gen start` 才实际输出。带 pilot 的 `acq run` 每个 64 kS/s 样点写 `bias+pilot`，结束后恢复静态 bias，再由主机读取 DMM；`gen reset` 只清配置，不自动归零，direct/gen 两套状态也不互相同步。

因此 A21 不能归因于 direct DAC 使用了错误通道或不同换算。真正未匹配的条件是激励历史：短时 monitor 在四点间每次跳约 2.61 V、无 pilot；`stage_vpi` 每点约 0.12 V 连续步进，并在读取 DMM 前执行 1 kHz pilot acquisition。固件源码还将全板 `SUBTRACTOR_GAIN=4` 标为 “To be verified”，但该固定换算会共同影响两条路径，不能解释只在四点大阶跃序列中出现的非互补曲线。

下一诊断不再做 direct/gen 二选一比较，而应直接复制论文真实路径：以 gen/acq、0.15 V pilot、6 blocks 和约 0.13 V 的稠密连续步进，在一个完整光学周期内重复双向扫描，逐点保存时间戳和 DMM。先用小步进 conditioning ramp 到扫描起点，避免把首次 4 V 跳变混入 epoch。只有多 epoch 的方向分裂、固定 Vpi 余弦残差、V0 范围和 30 min 外推全部通过，才重新授权 gauge audit。

### 2026-07-16，阶段 A23：生产路径稠密 V0 诊断冻结并实现

新增 `reviews/mzm_v0_dense_sweep_protocol.md` 与 `scripts/monitor_mzm_v0_dense.py`。首个实测前固定：沿用 `Vpi=5.222139 V`、参考 `V0=0.814764 V`，扫描 `[-4.4074,6.0369] V`；每方向 81 点、步进 0.13055 V、3 个连续双向 epoch。输出/读取完全复制 `stage_vpi`：`gen bias`、0.15 V/1 kHz pilot、`acq run 6 blocks` 后读取 DMM；正式点前从 0 V 以不大于正式步长的 conditioning ramp 到下边界。逐点保存时间戳、DMM、board DC 和四个原始 I/Q 分量。

成功门在实测前冻结为：六个方向的固定 Vpi 余弦拟合 `RMSE/amp<=sin(0.05)`；三个 epoch 的正逆 V0 分裂各不超过 0.05 rad；三块平均 V0 峰峰值不超过 0.05 rad；稳健斜率外推 30 min 不超过 0.05 rad。协议无基于首块结果的早停，硬件故障外必须完成 3 块。脚本已通过 `py_compile`、无噪声固定 Vpi 曲线断言、conditioning 最大步长断言和 `git diff --check`。该诊断仍不更新论文数据，也不授权 v1.4/acceptance。

### 2026-07-16，阶段 A24：生产路径曲线健康，但方向/时间门失败

真实目录 `data/exp/diagnostics/v0_dense/20260716_v0dense_v1_board2/` 完成 34 个 conditioning 点、3 个双向 epoch 和共 520 行原始记录；`manifest.status=complete`，4/4 SHA-256 复核一致，结束后板卡为 `IDLE`、0.000 V、`Lock=NO`。所有六个方向的固定 Vpi 余弦拟合 `RMSE/amp=0.0272--0.0328`，均低于 `sin(0.05)=0.04998`；幅度稳定在 0.729--0.741 V。这证明 gen/acq、0.15 V pilot 和小步进条件下，DAC--MZM--PD 的生产传输曲线形状健康，也证实 A19--A21 的非互补曲线主要由 direct-DAC 大阶跃测试条件造成。

稳定性总门仍失败。三个 epoch 的上/下扫 V0 分别为 1.5409/1.3551、1.5013/1.3262、1.4861/1.3292 V，对应方向分裂 0.1118/0.1054/0.0943 rad，均超过 0.05 rad。三块方向平均 V0 为 1.4480/1.4137/1.4077 V，峰峰值仅 0.02426 rad并通过，但 Theil--Sen 斜率为 `-6.905e-5 V/s`，外推 30 min 为 0.07477 rad，仍超过 0.05 rad。`quality_gate.accepted=false`，因此不授权 gauge audit、v1.4 preflight 或 acceptance。

该模式把根因进一步收敛为“扫描时间与方向历史不可忽略”，而非曲线形状失真或 Vpi 数值崩溃。每个双向 epoch 约 4.8 min；在此时间尺度内，单一静态 V0 已不足以同时解释上下扫。下一代码批次应先给 `vpi.csv/calib.npz` 增加逐点时间戳和实际顺序；标定改为双向或交错顺序，并插入独立 DMM sentinel，使 V0(t) 可估计且目标编号不与时间共线。论文实际评分必须使用 contemporaneous/interpolated external truth，而不是开始时的静态 scan map。现有 0.05 rad 门不放宽，也不以方向平均通过替代方向门。

### 2026-07-16，阶段 A25：Vpi/标定逐点时间合同补齐

`stage_vpi` 的新文件现在在原 `bias,dc_dmm,dc_board,dir` 后追加 `timestamp_unix,sequence_index`；既有四列保持名称和顺序兼容，绘图仍按字段名读取。`stage_calib` 的新 NPZ 追加每点 `timestamp_unix`、`sequence_index` 和当前单向扫描的 `sweep_direction='up'`。`scripts/exp_common.py` 与 `data/exp/README.md` 已同步说明新旧文件差异；历史数据不伪造缺失时间戳，也不重新生成。

验证包括 `py_compile`、完整 sim Vpi 双向 302 点和 21 点 ellipse calibration 烟雾测试：新 CSV 的序号为 0--301，NPZ 时间单调、序号为 0--20、方向字段完整；`git diff --check` 通过。该批只补可观测性，没有拟合或门限变化，也没有真实台架输出、论文数字更新或 v1.4 授权。

### 2026-07-16，阶段 A26：primary scan concurrence 硬门落地

`stage_calib` 现在除既有 ellipse/selected demodulator 对 contemporaneous refit map 的 50/200 mrad 自检外，还计算同一 demodulator 对更早 bidirectional primary scan map 的 median/P95，并以相同 50/200 mrad 作为 `require_valid=True` 的不可绕过门。`calib_fit.json`、summary 和 quality gate 均保存两套 estimand；失败列表明确区分 `primary_scan_median_pass` 与 `primary_scan_p95_pass`。这修复了 A14 指出的“标定检查 refit map、闭环起止却使用 scan map”覆盖缺口。

验证结果：匹配真值的完整 181 点 ellipse 仿真给出 contemporaneous 与 primary scan 自检均为 4.04/11.76 mrad，质量门通过；对真实失败目录 `20260716_gain_v13_board2` 的只读回放得到 primary scan concurrence 108.77/294.25 mrad，故新 gate 会在任何锁定矩阵之前以 median 和 P95 两项明确拒绝。阈值没有根据结果修改；旧目录保持原数据和 manifest，不事后重写。`py_compile` 与 `git diff --check` 通过，v1.4/acceptance 仍未授权。

### 2026-07-16，阶段 A27：ABA 时间分辨标定协议、离线真值模型与真实入口冻结

在任何新台架输出前新增 `reviews/mzm_time_resolved_calibration_protocol.md`。本诊断固定使用 A24 已验证的小步进生产路径：固定 `Vpi=5.222139048 V` 和仅用于扫描坐标的 `Vcenter=0.814763571 V`，81 点完整周期按 `up -> down -> up` 三条 leg 执行，共 243 个访问；每条 leg 的 `grid_index=0,10,...,80` 为 held-out DMM sentinel，共 27 点，其余 216 点用于拟合。ABA 设计使 formal 点的时间坐标与方向符号相关性在理论 schedule 上为零，同时保持最大步进约 0.13055 V，避免重新引入 direct-DAC 大阶跃历史。sentinel 沿自然扫描路径采集，完全排除于 DC 模型、椭圆几何和规范固定，只用于留出预测与相位 concurrence；它仍是共享光路 DMM，不构成独立光学真值。

新增纯离线模块 `scripts/mzm_time_truth.py`，冻结点级模型
`a=a0+a1*tau`、`b=exp(l0+l1*tau)`、`V0=v00+v1*tau+h*d`，并以逐点
`phi_truth(t)=pi[V-V0(t,d)]/Vpi` 同时评分 formal 和 sentinel。质量门保持：设计
`|corr|<=0.05`、条件数不超过 3；formal/sentinel 归一化 DC RMS 均不超过
`sin(0.05)`；方向分裂与 30 min 外推均不超过 0.05 rad；无标签椭圆在 formal
和 held-out sentinel 上均满足 50/200 mrad。方向项和时间项即使可拟合也仍受原门
约束，不能被模型解释后忽略。未来目标顺序助手使用记录种子 permutation `p` 与
`p[::-1]`，16 个目标在配对块中的平均零基时间位置均严格为 7.5，避免目标相位与
时间共线。

硬件无关验证全部通过。确定性合成 ABA 数据为 243 点、216 formal、27 sentinel；
设计 `|corr|=1.49e-17`、条件数 1.978，formal/sentinel 自检 median/P95 分别为
0.388/1.011 和 0.356/1.348 mrad，全部门通过。单独污染 sentinel 不改变 formal
拟合但会被 held-out DC 门拒绝；方向分裂超过 0.05 rad、重复时间戳、重复序号均
硬失败；另一个强线性漂移合成例证明 time-resolved truth 可恢复已知逐点相位，而
静态 map 明显偏离，同时物理漂移门仍正确拒绝该 run。

A24 稠密真实目录的只读回放没有被新模型“修成通过”：formal/sentinel 归一化 DC
RMS 为 0.0302/0.0378，说明点级余弦模型本身健康；但旧六-leg schedule 的
`|corr(tau,d)|=0.2888`，拟合方向分裂为 0.09953 rad，30 min 漂移为
0.08885 rad；board DC 最大值又达到 1.200 V，新增的已记录 rail 门也失败。该回放
只验证 DC 时间/方向分解，不把 6-block I/Q
冒充新协议的 16-block、`n_avg=4` 椭圆。真实 v1.3 目录先因
`manifest.status=failed` 被 replay-calib 拒绝；其 `calib.npz` 还缺少 role、
sequence、direction 和 timestamp 合同，即使绕开状态也不具备 time-truth
回放资格，没有伪造字段。

新增 `scripts/validate_mzm_time_truth.py`，只允许仿真/只读回放且输出限于 `build/`；
新增 `scripts/diagnose_mzm_time_calibration.py` 作为未来真实采集入口，逐点流式保存
conditioning 与正式 raw CSV、实际 acquisition/DMM 起止和中点时间、I/Q、DMM、
board DC，并在完整后原子生成 NPZ、analysis、manifest 和 checksums。该入口没有
闭环、preflight loader 或 headline 写入路径，且缺少显式
`--i-understand-this-writes-real-hardware` 时在创建目录和打开仪器前拒绝。no-ack
测试确认非零退出且未创建实验目录。该入口的 `--sim` 文件合同烟雾测试只写入
`build/exp_sim/time_calibration/smoke_aba_v1g_20260716/`，完成 34 个 conditioning、
243/243 个 ABA 点、216 formal、27 sentinel，manifest 为 complete、质量门通过，
6/6 文件 SHA-256 复核一致；注入第 17 个 ABA 点失败的独立仿真目录则非零退出、
保留 34 个 conditioning 与 17/243 个正式点、`manifest.status=failed` 和 4/4
匹配校验和。完整仿真 NPZ 又经独立 replay-calib 路径重评分通过。本阶段没有调用
真实硬件路径。A26 的 preflight
`protocol.json` 声明也补齐 primary scan 50/200 mrad 两项记录字段，使执行硬门与
元数据一致。

真实入口最终安全审计又补齐四处合同：sentinel 不再参与 `choose_comps`；time-truth
总门新增模型参数有限/正幅度、椭圆正定、命令偏压 `<8.955 V` 和 board DC
`<1.199 V`；清理异常或非 IDLE/非 0 V 状态会把 manifest 改为 failed 并非零退出；
replay-calib 逐项复核 sibling checksums、complete manifest、协议版本、冻结 schedule
SHA-256 以及 role/direction/bias/order，不接受只含同名 NPZ 的文件。目录创建后立即
建立 failed initialization manifest 和 checksums audit envelope，随后才计算源码哈希
和写 protocol/CSV，缩小初始化异常留下无审计目录的窗口。AC raw extrema 仍未由
固件提供，因此 board DC rail 门只能发现已记录的 CH1 削顶，不能证明 AC 通道无
瞬时 rail；因此分析固定输出 `adc_raw_extrema_available=false` 和
`v1_4_authorization_ready=false`，time-truth 门通过也不能越过该缺口。完整采集后
注入 cleanup failure 的仿真又确认：即使
分析门本身通过，manifest 仍改为 failed、最终状态标为 unsafe 且进程非零退出。

最终 replay 合同不允许缺字段时静默减少必需门：新协议 NPZ 必须同时含 raw
I1/Q1/I2/Q2、formal-only `comps`、可重算的 X/Y、board DC、完整 schedule 字段和
hash；replay 会从 formal raw 方差重新选择通道并逐字节核对 X/Y。time-resolved
self-check 之外，analysis 还保存冻结 `Vpi/Vcenter` 静态 coordinate map 在
formal/sentinel 上的描述性 concurrence，明确作为旧 scan-map 口径的反事实而非
本轮新鲜 primary scan。

验证已完成：新增/相关脚本 `py_compile`、离线 self-test、合成仿真、A24 只读
回放、v1.3 不合格合同拒绝、no-ack 安全测试和 `git diff --check` 均通过。没有
修改 `data/exp/results.json`、论文 headline 或任何既有实验目录；真实
time-calibration、gauge audit、v1.4 preflight 和 acceptance 均仍未授权。下一步
只有得到明确授权后，才可复核当时温度/身份并用新 run-id 执行首个
time-calibration 诊断；未通过其全部门之前，后三项继续禁止。

### 2026-07-16，阶段 A28：首个真实 ABA 时间标定完成，但方向历史、观察映射与 rail 门均失败

在明确继续推进后，仅执行了 A27 已冻结的首个真实 time-calibration 诊断，没有
启动 gauge audit、v1.4 preflight 或 acceptance。新目录为
`data/exp/diagnostics/time_calibration/20260716_timecal_v1_board2/`；运行前目录不存在，
板卡为 `IDLE`、0.000 V、`Lock=NO`、`Cal=INVALID`，DM858E 身份为
`Rigol Technologies,DM858E,DM8E275002095,00.01.00.00.22`。运行完成 34 个
conditioning 点和冻结的 243/243 个 `up -> down -> up` 点，其中 216 个 formal、
27 个 held-out sentinel；`manifest.status=complete`、`failure=null`，六个受保护文件
的 SHA-256 全部独立复核一致。清理后板卡重新为 `IDLE`、0.000 V、`Lock=NO`、
`Cal=INVALID`。失败目录保持原样，不覆盖、不删除、不重跑同一 run-id。

正式总门为 `quality_gate.accepted=false`，且独立 `replay-calib` 从 NPZ、manifest、
冻结 schedule、raw I/Q、X/Y 与 checksums 重新计算得到逐项相同结果。ABA 设计本身
健康：`|corr(tau,d)|=0.001374`、条件数 1.9746；formal/sentinel 的归一化 DC RMS
为 0.03242/0.03161，均通过 `sin(0.05)` 门；命令偏压最大绝对值 6.0369 V，椭圆和
点级模型均有限且正定。失败项为：方向分裂 0.15010 rad、全局点模型 30 min 外推
0.06829 rad、board DC 最大值 1.200 V（冻结门要求 `<1.199 V`），以及无标签仿射
自检 formal median/P95 为 97.44/388.51 mrad、sentinel 为 77.93/412.53 mrad，均未
同时满足 50/200 mrad。固件仍不输出 AC raw extrema，因此
`adc_raw_extrema_available=false`、`v1_4_authorization_ready=false`。静态
`Vcenter` map 的反事实误差更差：formal 723.05/937.72 mrad、sentinel
756.01/943.09 mrad，确认不能继续使用实验开始时的静态 scan map 评分。

对同一原始数据的只读、非门控归因进一步区分了时间和方向。逐 leg 固定 Vpi 的
DMM 余弦拟合仍健康，三个 midpoint 的 V0 为 2.02086、1.74743、1.96855 V，
`RMSE/amp=0.03093/0.02711/0.03570`；首个 up 与 down、末个 up 与 down 的分裂分别
为 0.16449 和 0.13302 rad。两条同方向 up 的 V0 只相差 0.03147 rad，按其 1176.7 s
间隔线性外推 30 min 为 0.04814 rad，略低于 0.05 rad。该数值只能用于说明全局
0.06829 rad 漂移项混入了方向/模型耦合，不能事后替代预注册总门；正式结论仍是
drift 门失败。

观察链也不是三条 leg 共用的静态仿射映射。用 contemporaneous DMM 点级相位作
只读诊断标签时，各 leg 自身的 phase-reference 标定 formal median/P95 为
46.89/206.83、47.71/143.17、46.56/207.78 mrad；两条 up 的标定交叉使用仍约为
45--57 mrad median，而任一 up 标定用于 down 时变为约 208--219 mrad median，
down 标定用于 up 时为约 116--139 mrad median。up/down 的标定中心相差约
0.032 V，`A_hat` 的相对 Frobenius 变化约 1.2--1.8%；由于椭圆条件数约 49--51，
这类小矩阵变化会被显著放大。按升序重排 down leg 后，原先单独对 down 调用
`calibrate_from_data` 的 winding 符号伪差消失，但方向间的交叉不一致仍存在，故
不能把总失败归因于离线排序错误。

因此 A28 把问题收敛为两个同时存在的效应：MZM/DC 真值具有约 0.13--0.16 rad 的
方向历史；高条件数 I/Q 仿射观察映射也随方向/时间变化。下一步必须先在离线协议和
仿真中加入可检验的 direction-contemporaneous 观察映射稳定性门，并解决 board DC
削顶及 AC raw extrema 不可见性；不能仅把 `V0(t)` 插值接入旧静态椭圆，也不能
根据同方向 0.04814 rad 事后放宽或替换原门。本阶段不修改 `data/exp/results.json`、
论文 headline 或任何既有实验目录；不授权后续真实 time-calibration、gauge audit、
v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A29：纠正 CH1 board DC rail 的错误硬门

对 A28 的 rail 解释做了源代码级复核。固件 `ctrl_bias.h:125--133` 和
`ctrl_bias.c:195--201` 明确规定：ADS131M02 CH0 样本送入 H1/H2 Goertzel，CH1
只累加为 debug/monitor DC；仓库实验代码则明确以 DM858E 作为未削顶 DC truth。
因此 `dc_board=1.200 V` 只说明 CH1 monitor 到达其显示/输入上限，既不污染 DMM
truth，也不能证明独立 CH0 的 H1/H2 acquisition 已削顶。A27 把
`board_dc_rail_pass` 列入 time-truth 的必需门属于过度约束，现予纠正。

`reviews/mzm_time_resolved_calibration_protocol.md` 升为 v1.1；ABA schedule、DMM
模型、方向/漂移 0.05 rad 门和 50/200 mrad concurrence 门均不变。后续分析仍要求
CH1 monitor 字段存在且有限，并保存 `board_dc_max_V`、1.199 V advisory 和
`board_dc_rail_pass` 描述值，但该 rail 不再出现在 `required_pass_fields`。真正与
仿射观察器削顶相关的缺口是 CH0 acquisition 窗内 raw min/max 或 clip count；在
它尚未记录前仍固定 `adc_raw_extrema_available=false` 和
`v1_4_authorization_ready=false`，但不得再用 CH1 替代 CH0 证据。新采集入口版本
相应升为 `mzm-time-resolved-calibration-v1.1`，只读 validator 同时接受已封存的
v1.0 和未来 v1.1，并在输出中保留实际记录版本；没有改写 A28 目录中的任何文件。

硬件无关回归新增“全部 CH1 monitor 值均为 1.200 V、但 DMM truth 与 CH0 I/Q
健康”的合成记录：新分析正确给出 accepted=true，同时
`board_dc_rail_advisory=true` 且 rail pass 不在 required 列表。A28 真实 NPZ 的
v1.1 逻辑只读重放仍为 accepted=false：方向分裂 0.15010 rad、30 min 全局外推
0.06829 rad、formal 97.44/388.51 mrad 和 sentinel 77.93/412.53 mrad 四类核心门
均未改变。A24 dense replay 也仍因 schedule 相关性 0.28876、方向分裂
0.09953 rad 和 30 min 外推 0.08885 rad 失败。故本次纠错删除了一个无效拒绝理由，
没有把任何真实失败实验改判为通过，也不授权新的硬件阶段。

### 2026-07-17，阶段 A30：方向同时性观察映射门冻结、实现并回放

新增 `reviews/mzm_direction_contemporaneous_mapping_protocol.md`，在实现前冻结
direction-contemporaneous 映射审计。三条 ABA leg 各自只用本 leg 的 72 个 formal
点和 time-resolved DMM `phi_truth(t)` 拟合 phase-reference affine map；随后完整
报告 own-leg、两条 up 的双向交叉和 up/down 四个有向交叉，并分别评分 target
formal 与 9 个 held-out sentinel。所有 median/P95 继续使用 A26--A29 的
50/200 mrad 门，不根据 A28 结果放宽；任一 own、same-direction 或
cross-direction 子门失败都会使 `observer_mapping_stability_pass=false`。矩阵中心、
`A_hat`、条件数和两两差异同时保存，但不以较小的矩阵范数变化替代相位误差门。

纯离线实现加入 `scripts/mzm_time_truth.py`，并把下一采集/文件合同升为
`mzm-time-resolved-calibration-v1.2`。稳定静态映射的确定性 ABA 自测全部通过；
只在 down leg 施加 affine perturbation 时，DMM time-truth 参数逐项不变而
cross-direction gate 正确失败；只污染 sentinel I/Q 时，三条 source calibration
逐元素不变而 sentinel gate 失败。缺失 leg、leg/direction 不一致、每 leg
72/9 数量破坏和非有限 I/Q 均硬拒绝。完整 v1.2 文件烟雾目录
`build/exp_sim/time_calibration/smoke_aba_v12_20260717/` 为 243/243 点、总门通过；
独立 replay 从 manifest、schedule、checksums 和 raw I/Q 重算后仍通过，所有有向
交叉约为 0.78--1.51 mrad median、2.16--3.65 mrad P95。

A28 真实 v1.0 NPZ 的新增诊断为
`own_leg_mapping_pass=false`、`same_direction_mapping_pass=false`、
`cross_direction_mapping_pass=false`。两条 up 明显比跨方向接近，但仍不能称为通过：
`0 -> 2` formal/sentinel 为 57.04/199.68 和 97.31/171.20 mrad，`2 -> 0` 为
40.33/214.86 和 77.90/199.62 mrad；四个 up/down 有向交叉的 formal median 为
112.68--213.38 mrad、P95 为 545.82--616.27 mrad，sentinel median 为
151.41--237.22 mrad、P95 为 535.84--586.83 mrad。三条 own-leg 中只有 down leg
同时通过；两条 up 各有 median 或 P95 轻微越门。因此 A28 的高条件数观察映射在
约 30 min ABA 窗口内连同方向重复性也未达到预注册精度，不能为下一闭环冻结单一
静态椭圆。

固件 `8b1b1c2` 的并行只读审查还确认：`dc_board=1.200000` 不是软件 clamp，而是
CH1 原始码按 `code*1.2/8388608` 换算、整窗求均值后六位打印；正满量程码会舍入为
1.200000。CH0/CH1 同步且均 gain=1、标称正负 1.2 V，但模拟路径不同；现有
`acq run` 的 I/Q 只来自 CH0，DC monitor 只来自 CH1。现有 `adc N` 是另一次、无同窗
pilot 的采集，不能补证产生 I/Q 的 CH0 样本。最小可观测性改动是在
`app_main.c` 的 `acq run` 读取循环内累计 CH0/CH1 raw min/max、exact-rail 与
1.199 V guard counts，采集结束后另起版本化 `RAWADC`/`RAWADC_CH` 行；保持原
`ACQ` 行不变，旧 helper 可忽略新行。固件、helper 和硬件均未在本阶段修改或运行。

下一步若获准修改偏压板固件，应先实现并做 host/unit/file-contract 验证，再考虑
闪写和新的真实 v1.2 诊断。无论是否补齐 raw extrema，A28 已揭示的方向历史和映射
不稳定仍须独立通过，故当前继续不授权 gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A31：CH0 同窗 raw-extrema 固件、主机和 v1.3 文件门完成

在未闪写、未连接硬件的前提下，新增并冻结
`reviews/mzm_adc_raw_extrema_protocol.md`。固件输出保持既有机器可读 `ACQ` 行不变，
在 acquisition 和 pilot 完全停止后追加版本化 `RAWADC` 与 `RAWADC_CH` 两行。字段
固定记录 `expected/used/read_fail/blocks/complete/timeout`、gain=1、标称
`fs_uv=1200000`、guard code 8381618、当前 `crc=0`，以及真正进入 Goertzel 的 CH0
原始码 min/max、exact rail 和 1.199 V guard 两侧计数。首版只记录直接生成 I/Q 的
CH0；CH1 不再作为替代证据。

`/Users/ckdfs/code/biascontrol_h523/src/app/app_main.c` 在原固件
`8b1b1c292dd1e06257a93a4a07f3088e96b1d2cf` 的未提交工作树上新增 71 行：统计更新
发生在 `ads131m02_read_sample()` 成功且同一 `smp.ch0` 送入 Goertzel 的路径；失败读
单独计数；活跃采样循环内没有 UART。两条新行按最大整数宽度分别为 161/135 bytes，
低于 256-byte buffer。现有三个 native tests 全部通过；ARM GNU 15.2.1 对
STM32H523 完整交叉编译成功，产物 RAM 25,368 B、FLASH 142,288 B，ELF SHA-256 为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`。构建中的 warning
仅来自既有 CubeMX HAL 未使用参数；新 `app_main.c` 无 warning。没有执行 pyocd、
OpenOCD、ST-Link、GDB 或任何板卡命令。

论文侧 `scripts/measure_bench.py` 新增可选 parser 和多窗聚合。旧 helper 仍只需解析
原 ACQ 行；论文代码从其 `_raw` 文本附加 `rawadc` 子结构。`n_avg=4` 现在对四个短窗
求 expected/used/counts 之和、min 的最小值、max 的最大值、complete 的逻辑与和
timeout 的逻辑或；任一缺行或版本/配置不一致都返回 unavailable，不能只保留最后
一窗。永久 self-test 覆盖 healthy、missing、版本错配和四窗中单窗失败。

time-calibration 文件合同升为 `mzm-time-resolved-calibration-v1.3`。CSV/NPZ 每点
保存 19 个 raw telemetry 字段；conditioning 与 243 个 ABA 点全部参与 raw gate。
冻结必需门为：合同字段一致、`complete=1`、无 timeout/read failure、used=expected、
四个 rail/guard count 均为零且 min/max 严格位于 guard 内。纯离线 analyzer 对
missing、read failure、timeout、exact rail、guard-only 和 extrema 到界均硬失败。
完整 v1.3 仿真目录 `build/exp_sim/time_calibration/smoke_aba_v13_20260717/` 为
243/243 点，总门和 `adc_raw_telemetry_pass` 均通过；独立 replay 又逐项核对受 checksum
保护的 CSV/NPZ raw 字段并通过。A28 v1.0 仍可只读回放，明确
`adc_raw_extrema_available=false`，没有伪造历史 telemetry。

本阶段仍没有真实 v1.3 数据，也没有改变 A28 的方向/漂移/映射失败结论。下一步只有
在用户明确允许固件闪写后，才可先做 0 V/短窗 telemetry smoke test并复核板卡回到
`IDLE, 0.000 V, Lock=NO`；在该 smoke test 通过前不运行 30 min ABA，更不授权
gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A32：RAWADC 候选固件已刷写，真实 CH0 同窗冒烟门通过

经用户明确授权后，先复核偏压板为 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`，并仅用
`pyocd` 将 A31 的候选 ELF 刷入 STM32H523。刷写命令固定探针 UID
`066FFF505754675087091823` 和 target `stm32h523cetx`；返回码为 0，日志记录擦除
122,880 bytes、写入 117,760 bytes。实际刷写 ELF SHA-256 为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`，与 A31 的
已测试构建产物一致；固件基线仍为 `8b1b1c292dd1e06257a93a4a07f3088e96b1d2cf`，
`app_main.c` 的 raw-extrema 修改仍未提交。

真实诊断目录为
`data/exp/diagnostics/rawadc_smoke/20260717_rawadc_smoke_v1_board2/`，协议冻结在
0.000 V bias、0.150 V/1 kHz pilot 和 2 个 acquisition blocks，不含 DMM、ABA、闭环
或 headline promotion。唯一采集窗返回 `expected=used=2560`、`read_fail=0`、
`complete=1`、`timeout=0`；真正进入 H1/H2 Goertzel 的 CH0 原始码范围为
`[-1163776, 1790378]`，远在 1.199 V guard code `\pm8381618` 内。exact negative/positive
rail 与 guard-low/guard-high 四个计数均为 0，H1/H2 两个 tone 均完整，因此冻结的
CH0 raw gate 通过。与此同时 CH1 monitor 仍报告 `dc=1.200000 V`；这次同窗原始证据
直接证明该 CH1 顶格不能替代、也不能否定独立 CH0 AC 路径的健康性。

清理后脚本记录板卡为 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`，随后独立重新查询得到
相同状态；未遗留 `pyocd` 或采集进程。`analysis.json`、`flash.json`、`manifest.json`、
`protocol.json` 和 `raw_response.json` 共 5 个文件的 SHA-256 均与
`checksums.json` 独立匹配。该目录状态为 `complete`、质量门 `accepted=true`，但
`v1_4_authorization_ready=false`：本次只补齐固件与单窗 telemetry 的最小实证，
没有运行 30 min v1.3 ABA，也不改变 A28 的方向历史、漂移和观察映射失败结论；
仍不授权 gauge audit、v1.4 preflight 或 acceptance。实验后双仓库
`git diff --check` 均通过；双稿 `make check` 为 `0 FAIL / 4 WARN`，WARN 仍只是两稿
未引用标签和缺少 `build/sim_output.txt`，没有新增失败。

### 2026-07-17，阶段 A33：首个真实 v1.3 运行因源码仿真哈希前置缺口主动中止

在 A32 通过后启动了唯一新目录
`data/exp/diagnostics/time_calibration/20260717_timecal_v13_board2/`。联机前独立确认
板卡 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`，DM858E live identity 为
`Rigol Technologies,DM858E,DM8E275002095,00.01.00.00.22`，现场 DC 读数
1.46143886 V。运行完成 34 个 conditioning 点和 5/243 个 ABA 点后，并行只读
readiness 审计发现：既有全量 v1.3 仿真协议记录的 `measure_bench.py` SHA-256 为
`f5b45d...dd84c6`，而本次真实协议冻结的当前源码为
`5c5c32bdd42f0fbdb55e1c0f9c23338f0417ac59e85c88b1900779fb42debd15`。A32 已用
当前源码完成单窗真实 smoke，但还没有用同一哈希重新完成 243 点全文件合同仿真与
replay；继续采集会违反“当前源码先全量仿真、后真实运行”的预注册顺序。

因此通过 SIGINT 主动中止，没有删除或覆盖目录，也没有把该 partial run 用于评分。
manifest 固定为 `status=failed`、`failure=KeyboardInterrupt: received signal 2`，保存
34 个 conditioning、4 个 formal 和 1 个 sentinel，共 39 行原始 CSV；未生成 NPZ
或 analysis。`manifest/protocol/summary/time_calibration.csv` 四个文件与
`checksums.json` 独立匹配。脚本清理和随后独立查询均确认板卡回到
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`，没有遗留采集或 pyocd 进程。

该失败是执行顺序审计证据，不反映器件或 RAWADC 门的物理失败。下一步固定为：用
当前源码新建全量 v1.3 仿真目录并 replay；若通过，再用不同的新 run-id 从头运行
完整真实 ABA。不得续跑或复用 `20260717_timecal_v13_board2`。

### 2026-07-17，阶段 A34：当前源码哈希的全量 v1.3 仿真与 replay 补齐

新建 `build/exp_sim/time_calibration/smoke_aba_v13_current_20260717/`，使用与下一次
真实运行相同的当前源码完成 34 个 conditioning 和 243/243 个 ABA 点。protocol 中
`measure_bench.py` SHA-256 为
`5c5c32bdd42f0fbdb55e1c0f9c23338f0417ac59e85c88b1900779fb42debd15`，与 A33
真实 partial 目录一致。manifest 为 `complete`、`failure=null`、总门
`accepted=true`；277 行 CSV、216 formal、27 sentinel 和全部 raw telemetry 合同
完整，6 个受保护文件的 SHA-256 独立匹配。

独立 `validate_mzm_time_truth.py --replay-calib` 从 NPZ 重算后再次通过：formal
median/P95 为 1.139/3.065 mrad，sentinel 为 1.073/3.360 mrad，方向分裂和 30 min
漂移均为 0，own/same/cross observer mapping 与 CH0 raw telemetry 门均通过。
至此 A33 的执行顺序缺口已经消除；下一真实运行必须使用新目录
`20260717_timecal_v13b_board2` 从头采集，不得使用 A33 partial 数据。

### 2026-07-17，阶段 A35：完整真实 v1.3 ABA 完成，首次直接确认 CH0 全周期削顶

在 A34 当前源码全量仿真通过后，新建并完成
`data/exp/diagnostics/time_calibration/20260717_timecal_v13b_board2/`。运行耗时约
1841.7 s，保存 34 个 conditioning 和 243/243 个 ABA 点；CSV 共 277 行，其中
216 formal、27 held-out sentinel，schedule index 0--242 连续且逐点时间严格单调。
manifest 为 `status=complete`、`failure=null`，但冻结质量门
`quality_gate_accepted=false`。脚本清理和随后独立查询均确认板卡
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`，无遗留采集或 pyocd 进程；6 个受保护文件的
SHA-256 与 `checksums.json` 全部独立匹配。独立 replay 从 NPZ 重算后复现相同结果。

CH0 同窗 telemetry 合同本身完整：总计 `20,167,680/20,167,680` 样本，
`read_fail=0`、timeout=0，全部窗均有版本化 RAWADC 行。但三个 leg 各有恰好
52/81 点触发 1.199 V guard 或 exact rail；leg 0/1/2 的 exact negative rail 计数为
118193/121274/117841，positive rail 为 118464/115985/119216，原始极值达到
`-8388608/+8388607`。因此 `adc_raw_telemetry_pass=false` 和
`adc_raw_extrema_available=false`。这是真正生成 H1/H2 的 CH0 全周期削顶；A32 的
0 V 单点 smoke 只能证明该工作点健康，不能外推到任意相位。CH1 monitor 仍到
1.200 V，但只保留 advisory；DM858E 外部 DC truth 正常越过该显示上限。

除削顶外，A28 的时间/方向结论也再次复现。方向 V0 分裂为 0.16404 rad，30 min
外推漂移为 0.07403 rad，均超过 0.05 rad；formal concurrence 为
92.86/431.53 mrad，sentinel 为 92.59/355.11 mrad，均未通过 50/200 mrad。
own-leg、same-direction 和 cross-direction observer mapping 三个子门全部失败；
两条 up 的有向 formal 交叉约 60.1--61.4/251.9--253.8 mrad，而 up/down 交叉约
163.0--205.4/577.0--670.3 mrad。DMM train/sentinel normalized RMSE 分别为
0.03017/0.03161，设计相关性与条件数门通过，说明 schedule 和 time-truth 拟合合同
健康；不能把总失败归因于点缺失或时间/方向共线。

本轮不得通过降低 RAWADC 阈值、删除削顶点或放宽 0.05 rad、50/200 mrad 来追认。
下一步必须先冻结前端动态范围修正及其全周期 raw sweep 验证；在 CH0 全周期不削顶
前，不得重跑完整 ABA、gauge audit、v1.4 preflight 或 acceptance。`results.json`
和论文 headline 继续不变。

### 2026-07-17，阶段 A36：全周期量程修正协议冻结，所需统一衰减修正为约 -8 dB

新增 `reviews/mzm_ch0_dynamic_range_protocol.md`。对 A35 三条 leg 中 87 个未削顶
正式点做只读回归，raw peak 与 Goertzel `|H1|` 满足
`raw_peak_V = 1.857 |H1| + 0.009 V`，`R^2=0.9878`，残差 P95/max 为
0.0345/0.0449 V。分别用每条 leg 的未削顶 I/Q 正弦拟合外推 H1 峰值后，预测完整
raw 峰约 2.24--2.27 V；pooled 外推加最大残差的保守值约 2.33 V。因此仅由 rail
占空比得到的 -0.69 dB 是不可采用的下界，约 -3 dB 也不足；退到 1.199 V guard
至少需约 -5.76 dB，达到冻结的 `max|raw|<=0.95 V` 裕量需约 -7.78 dB，工程候选
固定为统一 AC 链约 -8 dB。

硬件/网表只读审计确认 ADS131M02 已处于最小 PGA gain=1，没有小于 1 的软件档位；
CH0 为 `PD+ -> C19 -> DE1 -> U4/OPA140`，U4 反馈 `R10=100 kOhm || C21=10 pF`，
再经 DE2、R12=1 kOhm 进入 AIN0P。DE1/DE2 是焊接短接点，不是软件或插拔跳线；
数字缩放和 GCAL 不能恢复 ADC 前的物理平顶。优先方案是降低入射光功率或统一 TIA
增益，使 H1/H2 同比缩放并保持约 49--51 的条件数；板级备选为经稳定性验证后降低
R10 或设计 DE2 处衰减网络，不能只串联大电阻。

在不改光路/板卡前，协议先用 0.06/0.08/0.10 V pilot 做 81 点全周期交错 bracket，
每个 bias 内循环轮换候选顺序并记录 6-block 同窗 raw telemetry。pilot-only 达到
-8 dB 需把 0.15 V 降到约 0.060 V，此时 H1 约缩放 0.398、H2 约缩放 0.159，
预期 `kappa(A)` 恶化约 2.51 倍到 122--129；因此该短诊断同时检验 raw 安全和弱轴
代价，不把“无削顶”等同于可用于下一 ABA。真实运行前仍须先完成脚本、自测和仿真。

### 2026-07-17，阶段 A37：CH0 全周期 pilot bracket 实现、故障注入与 replay 通过

新增 `scripts/diagnose_mzm_ch0_dynamic_range.py` 和只读
`scripts/validate_mzm_ch0_dynamic_range.py`。冻结 schedule 为 34 个 0.10 V
conditioning 点，加 81 个单调 bias 上的 0.06/0.08/0.10 V 三候选循环轮换，共
277 行；每次固定 6 blocks，并流式保存同窗 CH0 raw telemetry、I/Q、board CH1
monitor 和真实时间戳。选择规则只在全 81 点样本完整、零 rail/guard 且
`max|raw|<=0.95 V` 的候选中取最大 pilot；`pilot_only_aba_ready` 始终为 false，
避免把 raw 安全误写成弱轴精度已经通过。

健康仿真目录
`build/exp_sim/ch0_dynamic_range/smoke_ch0range_v1_healthy_20260717/` 完成
277/277，三候选均通过并按规则选择 0.10 V；6 个受保护文件哈希一致，独立 replay
再次得到相同选择、逐候选 headroom 和 `kappa`。另建 rail、guard、0.96 V
headroom-only、sample mismatch 和 conditioning headroom 故障目录：被污染候选均
正确失败，其他候选仍可按冻结规则选择；conditioning 故障使 0.10 V 失败并降选
0.08 V。missing telemetry 与第 50 行中断注入均以非零退出，manifest 为 failed、
partial 行数分别为 35/50，已有文件哈希仍一致。所有仿真只写 `build/`。

两个脚本 `py_compile`、仓库 `git diff --check` 均通过；双稿 `make check` 仍为
`0 FAIL / 4 WARN`，WARN 仅为既有未引用标签和缺少 `build/sim_output.txt`。下一步可
运行唯一真实短诊断 `20260717_ch0range_v1_board2`；无论结果如何均不得覆盖目录或
直接启动完整 ABA。

### 2026-07-17，阶段 A38：首个 pilot bracket 完成但暴露 additive pilot 配置错误

真实目录 `data/exp/diagnostics/ch0_dynamic_range/20260717_ch0range_v1_board2/` 在界面
会话中断期间仍完整运行并安全结束：277/277 行、manifest `status=complete`、
`failure=null`，6 个受保护文件哈希独立匹配；脚本清理与随后独立查询均为
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`，无遗留进程。冻结质量门为 false，三个候选
均显示 81/81 点 exact rail，0.10 V conditioning 也为 34/34 点 rail；0.06/0.08/0.10 V
的 H1/H2 幅度几乎不随名义设置变化。该结果与 pilot 小信号缩放不相容，不能解释为
降低 pilot 无效。

源代码复核找到确定性主机配置错误：偏压板固件的 `gen pilot` 命令把每次调用追加到
`s_gen_pilots[]`，最大 8 项，并不替换同频 tone；原脚本先由
`prepare_mzm_frontend()` 添加 0.10 V pilot，又在每个候选前继续调用 `gen_pilot()`，
使同频振幅逐次相加，达到 8 项后后续命令被拒绝。故本目录测试的是累积多 tone
过驱，不是 0.06/0.08/0.10 V 单 tone bracket。目录永久保留为失败审计证据，不得
用于估算所需衰减或选择候选。

协议已补充非协商配置语义：每个候选前执行
`gen reset -> gen bias -> gen pilot`，首次使用每档 pilot 时以 `gen show` 验证恰好
一个 1 kHz tone 和正确 amplitude，并保存回显。修复后必须用新仿真目录重做所有
故障注入，再用新的真实 run-id 从头运行；不得复用 A38 目录。

### 2026-07-17，阶段 A39：single-pilot v1.1 修复、回归与全量仿真通过

`mzm_ch0_dynamic_range` 协议和采集入口升为 v1.1。新增
`_configure_single_pilot()`，每次严格执行 `gen reset -> gen bias -> gen pilot`；
永久 fake-board 回归连续调用两次必须得到两段各自仅含一个 pilot 的命令序列。真实
路径首次遇到 0.06/0.08/0.10 V 时调用 `gen show`，硬检查 `pilots: 1`、1 kHz 和
精确 amplitude，并将三份原始回显写入受 checksum 保护的
`pilot_verification.json`。只有三个候选均验证后，top-level accepted 才可能为 true。

新建 v1.1 健康仿真
`build/exp_sim/ch0_dynamic_range/smoke_ch0range_v11_healthy_20260717/`，完成
277/277，single-pilot verification、三候选 raw/headroom 和选择规则均通过，选择
0.10 V；7 个受保护文件哈希一致，独立 replay 得到相同逐候选结果。rail、guard、
headroom-only、sample mismatch、conditioning、missing telemetry 与第 50 行中断
故障均在新的 v1.1 目录重做，行为与冻结规则一致；missing/partial 仍非零退出并保留
失败目录。下一次真实运行固定使用新目录 `20260717_ch0range_v11_board2`，A38 的
additive-pilot 数据继续排除。

### 2026-07-17，阶段 A40：真实 single-pilot v1.1 完成，首窗 bias 阶跃瞬态被隔离

真实目录 `data/exp/diagnostics/ch0_dynamic_range/20260717_ch0range_v11_board2/`
完成 277/277，三档 `gen show` 均确认恰好一个 1 kHz tone 和正确 amplitude；总计
2,127,360/2,127,360 样本，`read_fail=0`、timeout=0。manifest 为 complete、
failure=null、7 个受保护文件哈希一致，独立 replay 完全复现。脚本清理和独立查询
均确认板卡 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

三个候选的 H1 峰值随 pilot 正常缩放为 0.499/0.661/0.828 V，`kappa(A)` 则为
128.04/97.16/77.32，直接确认降低 pilot 会显著恶化弱轴。raw 门表面上三档均失败，
但 44 个 formal guard 命中中有 42 个发生在每个新 bias 的
`candidate_order_index=0`，仅 2 个发生在 order 2。逐点检查显示每个 bias 首档可有
约数十至数百个 exact rail，随后同 bias 的另两档恢复健康；由于候选顺序按 grid
轮换，rail 也依次落到三档，不与 pilot amplitude 固定绑定。

固件 `genacq_run()` 只在 acquisition 开始后才把新 bias 写入 pilot channel，当前
脚本的 `gen bias` 只改配置，故每个 bias 的首窗同时包含从上一静态偏压到新偏压的
阶跃瞬态。A40 测到的是“稳态 pilot + 首窗 bias transition”的混合 extrema，不能
用于全周期稳态候选选择。下一版必须在每个新 bias 组开始前用 legacy `dac` 物理预置
偏压并固定 settle，再配置 single pilot；preposition/settle 时间戳与标志必须进入
文件合同。A40 目录保留但不授权 ABA。

### 2026-07-17，阶段 A41：bias preposition/settle v1.2 实现与仿真门通过

动态范围协议和采集入口升为 v1.2。每个 conditioning 点及每个正式 grid 的首候选
现在先执行 `gen reset`、legacy `dac <bias>` 物理预置 CH-A，并固定等待 0.500 s；
随后同一 grid 的三候选共享静态 bias，只重建 single pilot。CSV/NPZ 新增
`bias_prepositioned`、`bias_settle_s` 和 `t_bias_set_unix`；accepted 必须验证
34 个 conditioning 与 81 个 formal 组各恰好一次 preposition，并且每行 acquisition
开始相对本组 bias-set 时间不少于冻结 settle。fake-board 永久回归同时检查
`reset+dac+settle` 和每候选单 tone 命令序列。

首次 v1.2 仿真因 conditioning 末点与 formal grid 0 数值相同而按浮点 bias 变化错误
跳过正式组 preposition，新文件门正确拒绝。实现随即改为按 `role` 和
`candidate_order_index=0` 显式触发，不再从 bias 数值推断。修正后的健康目录
`build/exp_sim/ch0_dynamic_range/smoke_ch0range_v12b_healthy_20260717/` 为
277/277、preposition 合同通过、三候选通过并选择 0.10 V；7 个哈希一致，独立 replay
通过。全部 raw 故障重新运行；另增 preposition 标志和 0.400 s settle 破坏，二者均
令 top-level accepted=false、selected pilot=null。missing/partial 继续非零退出并
保留审计目录。下一真实运行固定为 `20260717_ch0range_v12_board2`。

### 2026-07-17，阶段 A42：真实 v1.2 完成，偏压阶跃已排除但 pilot 启动首窗仍需丢弃

真实目录 `data/exp/diagnostics/ch0_dynamic_range/20260717_ch0range_v12_board2/`
完成 277/277；2,127,360/2,127,360 个 RAWADC 样本均被解析，`read_fail=0`、
timeout=0。single-pilot verification 和 bias-preposition 合同均通过，7 个受保护文件
哈希一致，独立 replay 完全复现 `accepted=false`、`selected_pilot_V=null`。程序清理
后独立查询确认板卡 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

v1.2 成功把 A40 的 bias 阶跃从正式记录前移，但全量分层显示还有更窄的 generator
启动首窗效应：81 个正式 bias 组的 order 0 中有 12 点触轨，而 order 1 和 order 2
各 81 点均为 0 触轨、0 guard。由于候选顺序循环平衡，order-0 触轨分别落到
0.06/0.08/0.10 V 的 4/5/3 点，不能归因于某一 pilot 幅度。同一 pilot 在非首候选
位置的最大绝对 raw 电压分别为 0.520/0.681/0.853 V，均低于冻结的 0.95 V
headroom 门；尤其 0.10 V 的后续窗并未显示稳态动态范围不足。conditioning 的 8 个
触轨点同样全部位于 `dac` 预置后第一次启动 pilot 的记录，不能单独解释为稳态削顶。

因此 A42 不授权 ABA，也不支持改变 TIA 或光功率。下一版只做最小协议修复：每次
物理预置 bias 后，先以该组首候选的完全相同 single-pilot 配置执行一次有 RAWADC
遥测的 warm-up acquisition，将其保存为独立 startup-discard 审计记录；不重置
generator，紧接着才记录该候选的正式 acquisition。正式 accepted 必须同时验证每个
conditioning/formal 组恰好一个 warm-up、warm-up 文件哈希和正式窗无 rail/guard。
该改动须先通过 fake-board 调用序列、健康仿真、warm-up 缺失/重复/遥测故障注入及
独立 replay，再用新 run-id 运行；A42 目录永久保留。

### 2026-07-17，阶段 A43：startup-discard v1.3 协议、文件合同和仿真门冻结

`reviews/mzm_ch0_dynamic_range_protocol.md`、采集脚本和只读 validator 已升为 v1.3。
每个 conditioning 点及每个 formal bias 组现在固定执行物理 bias 预置、0.500 s settle、
single-pilot 配置、`6 blocks` warm-up、紧接的 `6 blocks` 正式首窗；warm-up 返回后先
流式写入 `startup_discard.csv`，再启动正式窗，二者间不得重配置且最大间隔为
0.250 s。同组 order 1/2 不重复预置或 warm-up。115 个 discard 与正式首窗通过
index、role/grid/sequence、bias/pilot 和时间戳一一链接，discard rail/guard 只作审计
而不评分，但完整 7680 样本、blocks/windows、ADC 常数、物理码界、有限观测和非负计数
均为硬门。

健康仿真目录
`build/exp_sim/ch0_dynamic_range/smoke_ch0range_v13e_healthy_20260717/` 完成
277 个正式窗和 115 个 discard，三档候选均通过并按预注册规则选择 0.10 V；
schedule、single-pilot、preposition、startup capture/映射/哈希门均通过。两份 discard
文件的实际 SHA-256 写入 analysis，并与最终 checksums 三方核对；9 个受保护文件、两套
CSV/NPZ 的精确 schema/全字段镜像、summary/manifest 计数、源码/协议哈希和最终状态均
由独立 replay 通过。

最终源码上重新运行 rail、guard、headroom、formal sample、conditioning、preposition、
settle、warm-up 缺失/重复/sample/重配置/0.500 s 间隔及 warm-up rail 共 13 个完成型
故障目录，全部通过 replay。正式 raw 故障令相应候选失败；conditioning 故障令 0.10 V
失败；preposition/settle 和全部 warm-up 合同故障均令 top-level accepted=false、
selected=null。单独 warm-up rail 保留 rail/guard 计数但正式窗仍通过，锁定了“discard
可触轨、遥测不可缺失”的语义。另有 `warmup_raw_missing`、formal `missing` 和
`after_warmup` 三个预期非零退出目录；后者在 0 个正式行前已保留 1 条 discard，证明
正式采集失败不会丢失已完成的启动窗。一次 `v13d_healthy` 初始化仿真因局部变量定义
位置错误在任何采集前退出，空目录保留；修正后才生成上述 v13e 证据。当前仍未运行
新真实 v1.3，也未授权或启动 ABA、gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A44：真实 startup-discard v1.3 通过，选择 0.10 V

真实目录 `data/exp/diagnostics/ch0_dynamic_range/20260717_ch0range_v13_board2/`
完成 277 个正式窗和 115 个 startup discard，共 3,010,560/3,010,560 个 RAWADC
样本；所有窗 `read_fail=0`、timeout=0、精确 blocks/windows/ADC 常数合同通过。
schedule、single-pilot、preposition、startup capture/映射/哈希门均通过，9 个受保护
文件哈希一致，独立全字段 replay 复现 `accepted=true`、`selected_pilot_V=0.10`。
程序清理及独立查询均确认板卡 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

三个正式候选均为 81/81 点零 rail、零 guard，最大绝对 raw 电压依次为
0.51745/0.68471/0.85134 V；0.10 V 的 34 个 conditioning 正式窗也为零 rail/guard，
最大 0.85219 V，全部低于 0.95 V headroom 门。115 个 discard 中仅第 10 个启动窗
触及正 rail（260 exact-rail、261 guard 样本），其余完整；该瞬态被原样保留且未进入
正式评分，直接解释并消除了 A42 的首候选伪失败。正式椭圆的 H1 峰值为
0.498/0.659/0.822 V，`kappa(A)` 为 125.13/94.20/74.84，故按“动态范围通过者中取
最大 pilot”选择 0.10 V，同时确认继续降 pilot 会恶化弱轴。

A44 只完成 CH0 稳态量程选择，不把 board CH1 当作 DC 真值，也不更新
`data/exp/results.json` 或论文 headline。下一步可在新冻结协议中把 0.10 V、每次静态
bias 预置后的 startup discard、逐点时间戳、独立 DM858E sentinel 和 contemporaneous/
interpolated truth 一并带入新的双向/交错 calibration 诊断；仍不得直接启动 gauge
audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A45：双向交错 calibration v1.0 协议与离线证据链冻结

新增 `reviews/mzm_interleaved_calibration_protocol.md`、共享真值/设计模块、真实采集
脚本及只读 validator。冻结设计为 81 个非单调、确定性随机化 target，每点相邻执行
up/down 两次观测且按 target ordinal 平衡 UD/DU；模 10 的 9 个 target 两方向共 18
点作为 held-out sentinel，其余 144 点标定。跨 target 的大移动拆为 2506 条不超过一个
grid step 的 conditioning 记录。每个 observation 均执行独立 `gen reset`、单 pilot
配置和 `gen show` 验证，再流式保存 6-block startup discard、DMM pre、4 个独立
16-block 正式窗及 DMM post；真值在四窗平均 midpoint 上由 DMM pre/post 线性插值，
不再使用实验开始时的静态 scan map。

硬门同时覆盖真实 acquisition midpoint 上的 direction--time 与 target--time 相关、
target--direction 和 pair-position 正交性、DMM bracket/短时变化、正式与 sentinel 的
DC RMSE、方向分裂、30 min 外推漂移、共享相位参考自检，以及 direction、pair
position、early/late 三种 own/cross mapping stability。正式 648 窗要求零 rail/guard、
完整 13,271,040 个 RAWADC 样本且绝对值不超过 0.95 V；162 个 discard 要求完整
1,244,160 个样本和双文件哈希，但允许削顶并原样留证。DM858E 是外部光学 DC 真值，
board DC 仅作有限性/监视项，`independent_optical_truth=false` 明示该诊断仍不是 gauge
audit。

最终冻结源码的健康仿真目录
`build/exp_sim/interleaved_calibration/smoke_interleaved_v10d_healthy_20260717/`
完成 162/162 个观测、648/648 个正式窗、162/162 个 discard 和 2506/2506 条
conditioning；target--time 相关系数 0.00344，正式 raw 最大 0.71526 V，全部硬门
通过。12 个受保护文件哈希、CSV/NPZ 精确 schema/全字段镜像、schedule/source hash、
完整 analysis、summary/manifest 与最终 SIM 安全状态均由只读 replay 复现。

同一冻结源码上完成 12 个完成型故障注入和 1 个中断型注入：正式 rail/headroom/sample、
discard 缺失/重复/sample、DMM bracket、错误 approach、方向 mapping 污染、sentinel
污染和 DMM 方向偏移均被相应硬门拒绝；单独 discard rail 保留触轨计数但因捕获完整而
仍通过，锁定“discard 可削顶、不可缺失”的语义。`after_discard` 在首个 discard 已流式
落盘后非零退出，manifest 为 failed、0 个正式 observation、1 个 discard 和 35 条
conditioning 均保留，最终 SIM 状态安全。discard 缺失/重复目录的 replay 在 summary
计数合同处明确拒绝，其余完成目录均完整复现。v10a、v10b 和 v10c 是协议/源码继续冻结
过程中的旧哈希或故障强度不足证据，全部原样保留且不作为最终通过依据。

A45 只授权在相同冻结协议下启动新的真实 interleaved calibration 诊断；不更新
`data/exp/results.json` 或论文 headline，也不授权 gauge audit、v1.4 preflight 或
acceptance。

### 2026-07-17，阶段 A46：首个真实 interleaved v1.0 因 USB 重枚举中断

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v10_board2/`
从安全初态启动，并在约 53 min 后于第 97 个 observation 的 `gen show` 读取期间发生
macOS/pyserial `SerialException: [Errno 6] Device not configured`。失败前已流式保存 96
个完整 observation、384 个正式窗、96 个 startup discard、1536 条 conditioning 和
96 份 single-pilot verification；manifest 明确为 `status=failed`、
`quality_gate_accepted=null`，清理命令因同一掉线无法在原句柄上执行。该目录永久保留，
不得补写、删除或作为通过数据使用。

板卡随后以 `/dev/cu.usbmodem2103` 重新枚举；新连接独立查询确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。部分目录的 8 个现存文件哈希已保存，独立
validator 因缺少完成运行才应产生的 analysis 和三份 NPZ 明确非零拒绝。中断没有产生
headline、`results.json`、gauge audit、preflight 或 acceptance 授权。

下一步不盲目覆盖重跑 v1.0。应先冻结可审计的分段/断点协议，使每段在完整 target
pair 边界结束、各段使用新目录并独立回到安全状态，最终聚合器验证无缺段/重复、全局
schedule 与时间正交性、源码/协议哈希和全部原始门；完成健康仿真、断段/重复/乱序及
重枚举故障回放后，才用新 run-id 做真实分段采集。

### 2026-07-17，阶段 A47：interleaved v1.1 分段采集与全局聚合门冻结

为避免 A46 的 53 min 单句柄故障再次报废整轮，协议与实现升为 v1.1。全局 81 个
target pair 在 pair 边界固定切为三个连续 segment，global observation 范围为
`[0,54)`、`[54,108)`、`[108,162)`；每段独立从安全 0 V 开始并独立安全收尾，bridge
合同分别为 872/791/826 条，总计 2489 条。每段只声明采集、RAWADC、DMM bracket、
文件和安全合同，不独立拟合科学结果；只有三个 segment 的全局聚合可以产生最终
`accepted`。

新增全局聚合器与独立 bundle replay。聚合器要求 segment index 恰为 0/1/2 且输入
有序，三段 source hash、完整 schedule、device/firmware/instrument metadata 一致，
initial/final 状态安全，真实 wall-clock 与 acquisition 时间不重叠；窗口、discard、
pilot 和 conditioning 重编号后重新运行原 v1.0 的全部 162 点科学门。聚合算法和 bundle
validator 自身也进入采集前 source hash，禁止采集后改判据。A46 的 v1.0 partial 目录
因 failed manifest、缺 analysis/NPZ、版本和安全状态合同被明确拒绝，不能拼入。

最终冻结源码的 v11d 健康仿真三段各完成 54 observations、216 正式窗、54 discard，
12 个受保护文件分别通过全字段 replay；聚合为 162 observations、648 正式窗、162
discard、2489 conditioning，`|corr(target,time)|=0.00279`，方向分裂与 30 min 漂移
均为 0，全部门通过，独立 bundle replay 完全复现。缺段、重复段、输入乱序、旧 partial
和旧 source hash 均非零拒绝。

最终源码上，segment 层的 formal rail/headroom/sample、discard missing/duplicate/
sample、DMM bracket 和 approach 故障均被拒绝；discard-only rail 正确允许。mapping、
sentinel 与 DMM direction 污染在 segment 层只作为完整采集保留，但 mapping/sentinel
在全局聚合被拒绝；三段同时注入 DMM direction 后全局方向分裂为 0.06016 rad，超过
0.05 rad 并被拒绝。上述 fault bundles 均由独立 replay 复现；首 discard 后中断继续
非零退出并保留 partial 目录。

A47 只授权用三个新 run-id 依次执行真实 segment 0/1/2，并在三段均独立完成后建立
新的 derived bundle；任一段失败均保留且只能用新 run-id 重做该段。仍不更新
`data/exp/results.json`、论文 headline、gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A48：真实 v1.1 segment 0 首次尝试在首个 discard 拒绝

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v11s0_board2/`
从已验证的安全初态启动，完成首个 observation 前的 35 条 conditioning 后，首个
6-block startup discard 返回中没有可解析 RAWADC telemetry，按冻结硬门以
`RuntimeError: transition-discard RAWADC telemetry missing` 非零退出。目录保留 0 个
discard、0 个正式窗、0 个 observation，manifest 为 failed、analysis 为空，validator
因缺完成运行的 analysis/NPZ 明确拒绝；不得补写或拼入 bundle。

程序清理和随后独立新连接均确认板卡
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`，initial/final 状态也已写入 manifest。该失败
不改变 v1.1 协议或判据；下一步只允许用新 run-id 从安全初态完整重做 segment 0，
仍不启动 segment 1/2、聚合、gauge audit、preflight 或 acceptance，直到 segment 0
独立通过。

### 2026-07-17，阶段 A49：segment 0 第二次首窗失败定位为 acquisition 列表未显式配置

新目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v11s0b_board2/`
再次在 35 条 conditioning 后的首个 startup discard 以相同 RAWADC telemetry missing
失败，0 discard/0 formal/0 observation，目录与 manifest 原样保留。程序和独立新连接
均确认最终 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

两次可重复失败已定位到确定性初始化遗漏：A46 的 USB 重枚举清空了板卡 acquisition
frequency 列表，而 interleaved 脚本每点只重配 generator，没有在每段开始显式执行
`acq reset`、`acq add 1000`、`acq add 2000` 并验证 `acq show`。旧 v1.0 能运行 96 点是
继承先前进程留下的 acquisition 列表，不能视为自足初始化。下一修复必须把两频率配置
与实际回显写入受保护文件和 segment 硬门，完成新源码健康仿真、缺频故障注入及 replay
后才可用新 run-id 第三次执行 segment 0；不得复用前两目录。

### 2026-07-17，阶段 A50：每段 acquisition frequency 自足初始化门已冻结

interleaved v1.1 现在在每个 segment 的任何 conditioning 前显式执行 `acq reset`、
`acq add 1000`、`acq add 2000`；每个 observation 已有的 `gen show` 记录同时硬验证
`freqs: 2` 和 1000/2000 Hz 两条频率，不再依赖板卡残留状态。该验证进入每段
pilot verification、analysis、checksums、source hash 和独立 replay。

最终 v11e 冻结源码的三个健康 segment 均为 54/216/54，分别通过 872/791/826 条
conditioning 及 12 文件 replay；全局 162/648/162/2489 bundle 再次 accepted，独立
bundle replay 完全复现。`acq_frequency` 故障注入保留完整采集但令 segment
`accepted=false`，独立 replay 同样拒绝。A48/A49 两个真实失败目录永久保留；下一步
用第三个新 run-id 重做 segment 0，仍不得复用或补写旧目录。

### 2026-07-17，阶段 A51：真实 segment 0 完成但被两次正式 CH0 瞬态削顶拒绝

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v11s0c_board2/`
完整取得 54 observations、216 正式窗、54 discard 和 872 conditioning；显式
1/2 kHz acquisition 验证、schedule、DMM bracket、preposition、discard、文件哈希与
独立 replay 全部通过，程序和独立新连接均确认最终
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。但 segment `accepted=false`，不得进入后续
bundle。

失败仅来自正式 CH0 RAWADC：window sequence 90（observation 22, window 2）和 162
（observation 40, window 2）分别触及负/正 rail，累计 rail low/high 491/149、guard
493/150，最大绝对 raw 为 1.2 V；其余最高窗为 0.9272 V。两次都发生在每个 observation
的第 3 个正式窗而非 startup discard，不能按 warm-up 例外删除。A44 的 0.10 V 稠密
量程门只证明短窗稳态通常低于 0.95 V，未覆盖本次约半小时序列中的稀有瞬态。

下一步不得简单重跑碰运气。应把 interleaved pilot 降为 A44 同样全周期通过、典型
最大 raw 约 0.685 V 的 0.08 V，保留相同 0.95 V/零 rail 硬门；更新协议/source hash，
重新完成三段健康仿真、弱轴/映射门与 replay 后，才用新 run-id 重做真实 segment 0。
board CH1 DC 削顶仍不参与此结论；这里拒绝的是正式 CH0 解调输入的真实 RAWADC rail。

### 2026-07-17，阶段 A52：interleaved v1.2 将 pilot 降为 0.08 V

协议与 source hash 已升为 v1.2，唯一物理改动是把 pilot 从 0.10 V 降为 A44 已通过
全周期量程门的 0.08 V；正式零 rail/guard、0.95 V headroom、DMM、时间、mapping 和
全部科学门均保持不变。显式 1/2 kHz acquisition 初始化和逐 observation 验证继续保留。

最终 v12a 三个健康 segment 均完成 54/216/54 和 872/791/826 conditioning，12 文件
replay 全部通过；全局 162/648/162/2489 bundle accepted，独立 bundle replay 复现
`|corr(target,time)|=0.00279`、方向分裂 0、30 min 漂移 0。下一步只能用新 v1.2
run-id 重做真实 segment 0；A51 的完整但 raw 失败目录不得进入 bundle。

### 2026-07-17，阶段 A53：真实 v1.2 segment 0 完整通过

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v12s0_board2/`
完成 54 observations、216 正式窗、54 startup discard 和 872 conditioning；显式
1/2 kHz acquisition 验证、schedule、DMM bracket、preposition、正式/丢弃窗捕获、
文件哈希与全部 segment 硬门均通过。12 个受保护文件的独立全字段 replay 复现
`accepted=true`。

0.08 V pilot 的正式 CH0 最大绝对 raw 为 0.66646 V，216 个正式窗与 54 个 discard
均为零 rail、零 guard，显著低于冻结的 0.95 V 门，消除了 A51 的稀有正式窗触轨。
程序记录的 initial/final 状态及随后独立新连接均确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。A53 只完成 segment 0；下一步按同一 v1.2
源码和协议执行 segment 1，尚不得聚合或启动 segment 2 之后的任何阶段。

### 2026-07-17，阶段 A54：真实 v1.2 segment 1 完整通过

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v12s1_board2/`
完成 global observations `[54,108)` 的 54 observations、216 正式窗、54 discard 和
791 conditioning；全部 segment 硬门与 12 文件独立 replay 通过。正式和 discard
均为零 rail、零 guard；正式最大绝对 raw 为 0.94939 V，低于但接近冻结的 0.95 V
headroom 门，按预注册规则通过且不作事后放宽。

程序 initial/final 状态及独立新连接均确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。A54 只完成 segment 1；下一步按同一 v1.2
源码执行最后的 segment 2，三段完成前仍不得建立真实 bundle。

### 2026-07-17，阶段 A55：segment 2 首次尝试因 DM858E 初始化超时退出

目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v12s2_board2/`
在任何 conditioning、discard 或正式 acquisition 前，DM858E 到
`192.168.99.147:5025` 的首次连接超时，manifest 为 failed、全部采集计数为 0、
quality gate 为空；该空失败目录永久保留且不得续写。

随后网络检查显示首次 ping 延迟约 1 s、第二次恢复到 7.4 ms，SCPI 5025 端口和
DM858E 身份查询恢复正常；板卡独立查询为
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。该故障发生在证据采集前，不改变协议或门；
下一步用新 run-id 从安全初态完整重启 segment 2。

### 2026-07-17，阶段 A56：真实 v1.2 segment 2 完整通过

真实目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v12s2b_board2/`
完成 global observations `[108,162)` 的 54 observations、216 正式窗、54 discard 和
826 conditioning；全部 segment 硬门与 12 文件独立 replay 通过。正式和 discard
均为零 rail、零 guard，正式最大绝对 raw 为 0.74780 V，低于 0.95 V headroom 门。

程序 initial/final 状态及独立新连接均确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。至此三个 v1.2 真实 segment 均独立完成；
下一步只允许用冻结聚合器建立一个新的 derived bundle 并运行全局科学门，聚合结果
出来前不得更新 `results.json`、论文 headline 或启动后续实验。

### 2026-07-17，阶段 A57：真实 v1.2 全局 bundle 拒绝，但方向/时间历史问题已消除

derived 目录
`data/exp/diagnostics/interleaved_calibration/20260717_interleaved_v12_bundle_board2/`
由三个独立通过且安全收尾的 v1.2 segment 生成，合并 162 observations、648 正式窗、
162 discard 和 2489 conditioning；独立 bundle replay 完全复现 `accepted=false`。
原始三个 segment 和失败目录均未修改。

本轮最关键的正结果是 A26 的方向/时间历史问题已经消除：实际 midpoint 上
`|corr(target,time)|=0.00306`、`|corr(direction,time)|` 对应设计值约
`5.95e-7`，方向 V0 分裂仅 0.00276 rad，30 min 外推漂移仅 0.00635 rad，均显著低于
0.05 rad；formal/sentinel DC 归一化 RMSE 为 0.04834/0.04841，也刚好通过
`sin(0.05)` 门。全部 schedule、DMM bracket 时序、RAWADC、headroom、文件和全局
正交性合同通过。

拒绝来自两个独立硬门族：其一，逐 observation DMM pre/post 归一化变化的
median/P95/max 为 0.02045/0.06135/0.14407，最大值超过 `sin(0.05)`，故 bracket
stability 失败；其二，0.08 V pilot 的共享 map formal median/P95 为
177.6/531.0 mrad，sentinel 为 84.9/678.2 mrad，方向、pair-position 和 early/late
own/cross mapping 全部未过 50/200 mrad。方向 up/down map 本身十分接近（相对
`A_hat` 差约 0.21%），说明失败不是方向映射分裂；early/late `A_hat` 差约 8.75%，
同时 0.08 V 的 `kappa(A)` 约 94，提示弱 H2 与时间变化共同限制相位映射。

`board_dc_rail_pass=false` 仅是 monitor/advisory，未列入 required fields，也不是本次
拒绝原因。A57 不更新 `results.json` 或论文 headline，不授权 gauge audit、preflight
或 acceptance。下一步先做只读离线分解，区分 DMM bracket 短时变化、弱 H2 噪声和
跨 segment observer-map 变化；任何新硬件调整必须另用新协议和 run-id。

### 2026-07-17，阶段 A58：离线否定“每点 gen reset 导致统一参考相位随机旋转”

对 v1.2 全局 bundle 中 81 对同目标、相反方向观测的复谐波
`H1=I1+jQ1` 与 `H2=I2+jQ2` 做了只读相位差分解。`|delta phase(H1)|`
的 median/P95/max 仅为 0.000377/0.000649/0.00369 rad；若存在宽带 DDS
启动相位旋转，H1 应同样显著变动，故该假设不被数据支持。H2 相位差
的 median/P95/max 为 0.00530/0.06390/0.19849 rad，
`wrap(delta phase(H2)-2 delta phase(H1))` 为
0.00539/0.06450/0.19911 rad，表明异常主要位于弱 H2 通道而不是两谐波共同参考。

同对幅值相对差的 H1 median/P95/max 为 0.00925/0.15294/1.34096，H2 为
0.00870/0.06740/0.10828；H1 的极端相对值可能包含近零分母，不得单独解释为硬件
崩溃。因此暂不因该假设刷写固件；下一步应预注册一个小型静态重复诊断，用固定偏压、
不重启与重启 gen/acq 的对照，分离弱 H2 的幅相波动、时间漂移和 DMM bracket 变化。
A58 未修改任何原始/派生实验目录，也不更新 `results.json` 或论文 headline。

### 2026-07-17，阶段 A59：静态重复诊断协议冻结并完成全部离线验证

按 A58 结论预注册了最小化静态重复诊断
`reviews/mzm_static_repeat_protocol.md`（v1.0）：5 个固定网格点
`(40,0,60,20,80)`，每点 4 个连续 condition block（`none`/每轮重启 gen/每轮重启
acq/每轮同步重启，Latin 旋转去时间相关），每 block 12 个 repeat，共 240
repeats、480 个 16-block 正式窗、240 个 6-block discard；每 repeat 保存重启
动作时间戳、`gen show` 验证、逐窗 I/Q 与完整 RAWADC、以及 2+2 次带时间戳的
DM858E 读数。归一化幅度 `b_hat` 与解释阈值（≥2× 且超出 `none` 至少
0.02 rad，≥3/5 点）全部冻结；`both` condition 超限只作旁证，不独立定罪，
使 gen/acq 可分离归因。accepted 只覆盖采集合同，科学结论由预注册解释规则
产出，不进入论文数字。

实现为 `scripts/mzm_static_repeat_truth.py`（冻结 schedule、圆统计与解释
规则，自检含三向注入判别）、`scripts/diagnose_mzm_static_repeats.py`（采集
驱动，`--sim` 只写 `build/exp_sim/static_repeats/`）与
`scripts/validate_mzm_static_repeats.py`（只读全字段 replay）。离线验证全部
通过：健康仿真 accepted=true 且独立 replay 复现；formal rail/headroom/样本、
discard 缺失、DMM 时间序、schedule 破坏、restart 缺失七类采集故障全部
accepted=false；`gen show` 验证失败与中途失败均以 failed manifest 安全退出且
已写数据保留；解释注入自检三向正确（gen 注入→仅 gen 牵连+固件调查授权；
全局注入→环境牵连、不授权；DMM 注入→bracket 无重启复现标志）；validator
拒绝 CSV 篡改与 v1.2 interleaved 目录冒充。A59 未接触任何真实实验目录，
不更新 `results.json` 或论文 headline；下一步以新 run-id 执行真实静态重复
诊断（固件保持 `8b1b1c2_rawadc_a3785e95` 不变）。

### 2026-07-17，阶段 A60：真实 v1.0 静态诊断在首次 acq restart 验证瞬态失败，协议升 v1.1

真实目录 `data/exp/diagnostics/static_repeats/20260717_static_v10_board2/`
在完成 point 0 的 `none` 与 `gen` 两个 block（24/240 repeats）后，于第一个
`acq` condition repeat 的 `acq show` 验证失败中止；已写数据与 failed manifest
永久保留。板卡按安全路径收尾，独立新连接确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。事后手动背靠背
`acq reset→add→add→show` 无法复现失败且响应格式与解析完全一致，结合既有
"USB 链路偶发掉 acquisition 频率列表"记录，判定为链路瞬态而非解析或固件回归。

协议升 v1.1（`mzm-static-repeat-v1.1`）：唯一改动是 acq 验证允许最多 3 次
完整 reset→add→show 重试，每次响应与时间戳逐条保存、不允许静默重试，重试
总数作为 acq restart 链路可靠性统计进入 analysis——该统计本身就是 acq 路径
不稳定假设的证据。v1.1 离线验证全部重新通过：健康 accepted、`acq_retry`
注入（1 次失败后恢复）accepted 且 retries=1 如实上报、3 次耗尽安全失败、
formal rail 仍拒绝、healthy 与 retry 目录独立 replay 均复现。A60 不更新
`results.json` 或论文 headline；下一步以新 run-id 重跑真实 v1.1 诊断。

### 2026-07-17，阶段 A61：真实 v1.1 在 formal 读取瞬态失败，协议升 v1.2

真实目录 `data/exp/diagnostics/static_repeats/20260717_static_v11_board2/`
完成 point 0 全部 4 个 block（含 24 次 acq/both 重启，v1.1 重试机制工作正常）
及 point 1 的 6 个 repeat 后，第 55 个 repeat 的一个 formal `acq run` 返回
不完整 tones（`_valid_acq` 失败）中止；54 repeats、108 窗、55 discard 与
failed manifest 永久保留，板卡安全收尾并独立确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。该失败模式与 DPMZM 阶段记录的
"`acq run` 偶发 <9 tones、需一次重试"一致，属 USB 链路读取瞬态。

协议升 v1.2（`mzm-static-repeat-v1.2`）：对"完全无效"的读取（tones/DC/
RAWADC 缺失，即不含任何可用测量）允许最多 3 次尝试；每次失败尝试的时间戳
逐条写入 `acq_read_failures.json`，逐 repeat 重试计数入主 CSV 并与失败记录
逐条对账（`read_failure_contract_pass` 硬门），discard→formal 2 s 门改按
"首次尝试"时刻评价。有效但难看的窗仍不允许重试，故不产生选择偏倚；重试
总数作为链路可靠性统计上报。v1.2 离线验证全部通过：健康 accepted、
window/discard 重试注入 accepted 且 fret/dret=1 如实上报、3 次耗尽安全
失败、formal rail 仍拒绝、三个目录独立 replay 复现。A61 不更新
`results.json` 或论文 headline；下一步以新 run-id 重跑真实 v1.2 诊断。

### 2026-07-17，阶段 A62：真实 v1.2 静态诊断完整通过，重启假设被排除，DMM 读数噪声被定位

真实目录 `data/exp/diagnostics/static_repeats/20260717_static_v12_board2/`
完整取得 240 repeats、480 正式窗、240 discard、211 conditioning，全部采集
硬门通过，`accepted=true`，独立全字段 replay 复现；正式 CH0 最大绝对 raw
0.67207 V、零 rail/guard；程序与独立新连接均确认
`IDLE, 0.000 V, Lock=NO, Cal=INVALID`。全程 35.7 min，acq restart 重试 0
次、discard 读取重试 0 次、formal 读取重试 1 次（v1.2 重试机制被真实用到
一次，且如实入档）。

预注册解释规则输出全阴性：gen/acq/both 各 5 点均无牵连、
`firmware_change_authorized=false`、H1 参考无需复审、环境不牵连、DMM
bracket 未在 `none` 下超限复现。因此**不修改、不刷写固件**。关键数字：

- H1 相位圆标准差全部 ≤0.00033 rad（A58 离线结论的在线复核）；强 H2 点
  （grid 0/40/80）H2 相位圆标准差 0.0017–0.0037 rad。固定偏压下弱 H2 幅相
  波动比 bundle 的 177.6/531.0 mrad mapping 残差小两个数量级，静态噪声与
  重启均不能解释 A57 的 mapping 失败——结合 early/late `A_hat` 差 8.75%、
  up/down map 差仅 0.21%，mapping 失败最可能来自 observer map 随 ~30 min
  实验时间的慢变化（热漂移），应以时间分辨 map 处理。
- 正交点（grid 60）重启 condition 的 H2 圆标准差有亚阈值抬升
  （acq 0.0299 / both 0.0248 / gen 0.0217 vs none 0.0109 rad，超额
  <0.02 rad 未定罪），仅作 advisory 记录。
- **DMM bracket 失败的主因定位为读数噪声地板**：背靠背两次 DM858E 读数
  （间隔 ~0.1 s、完全静态、无重启无移动）典型差 ~15 mV、尾部达
  61.7 mV（归一化 0.083，已超 sin(0.05) 门）；该噪声与 |sin φ| 无关、与
  DC 电平（0.10–1.58 V）无关，为加性电子噪声而非 pilot 泄漏或激光强度
  噪声。bracket 门阈值 `sin(0.05)*b≈37 mV` 位于单次读数噪声尾内，bundle
  的 median/P95=0.020/0.061 与静态分布一致；其 max 0.144 超出静态尾部，
  未被完全复现。对策是测量协议而非硬件：下一版 interleaved 协议应对每个
  bracket 点取多次 DMM 读数平均（如 4–8 次，噪声 /√N）或提高 NPLC。

下一步（均为协议/分析层，不动固件）：预注册 interleaved v1.3——(a) DMM
bracket 多读平均；(b) observer map 允许时间分辨（如按时间两段或线性
时变），用 held-out sentinel 交叉验证；离线仿真与故障注入通过后再真实
重跑三段。A62 不更新 `results.json` 或论文 headline，不授权 gauge audit、
preflight 或 acceptance。

### 2026-07-17，阶段 A63：离线定谱 mapping 失败根因——弱轴偏压周期性确定性杂散，时间分辨 map 方案被否定

对 v1.2 bundle 的只读残差分解（管线自校验：order-1 复现冻结的
177.6/531.0 与 84.9/678.2 mrad）得到根因链：

1. **残差是确定性偏压函数，不是噪声或漂移**：同一 target 相隔数分钟的
   up/down 两次观测残差相关 0.9989；逐 grid 系统轮廓解释残差方差的
   99.9%，扣除后中位残差仅 5.1 mrad。bundle 自身的 early/late own-half
   残差仍 ~165–172 mrad，故 A62 提出的"时间分辨 observer map"方案被
   **数据否定**，不再实施。
2. **杂散位于弱观测轴（H2 方向），随偏压快速准周期振荡**：残差包络
   ∝|sinφ|（加性弱轴污染的指纹），周期约 5.4–6.8 个网格步（~0.7–0.9 V），
   啁啾且包络不均，故 2φ–4φ 低阶谐波扩展模型完全无效（已测，残差不降）；
   与 DC 模型残差不相关（corr 0.118），排除相位真值非线性。
3. **绝对幅度跨 run、跨 pilot 深度稳定**：0.08 V bundle 与 0.10 V
   v11s0c/v10 目录的弱轴原始残差轮廓相关 0.975，绝对 RMS 1.94 vs
   1.49 mV，而弱轴信号按 J2∝m² 缩放（6.14→8.97 mV）——杂散近似加性
   常值，浅 pilot 下相对污染 32%（0.08 V）对 17%（0.10 V），定量解释
   为何 0.08 V mapping 惨败而 A35 的 0.15 V map 曾达 27 mrad。
4. **可标定扣除（严格跨数据集验证）**：仅用 0.10 V 两个旧目录估计的
   48-grid 杂散轮廓（每格 2–4 次观测的粗估计）冻结后应用于 0.08 V
   bundle，formal median/P95 183.8/530.7 → **54.7/287.9** mrad，
   sentinel 68.0/680.3 → **24.9/254.6** mrad，接近但未过 50/200 门；
   瓶颈是 donor 轮廓的采样噪声与 0.08 V 的最不利相对污染。

结论与下一步：interleaved v1.3 应改为两阶段——(i) 专用高平均密集偏压
杂散标定 sweep（生成冻结的 d(V) 弱轴修正表，独立 run-id）；(ii) 在
0.10 V pilot（相对污染 ~1.9× 更小；A51 的 rail 为 216 窗中 2 窗的稀有
事件，需配套 headroom 策略）或 0.09 V 下重跑三段 interleaved，标定链
应用冻结 d(V) 修正，并叠加 A62 的 DMM 多读平均修 bracket 门。杂散物理
来源（疑与 DAC 码相关的 2 kHz 谱杂散）可另行用频谱仪/固件侧诊断，但
不阻塞标定路线。A63 全程只读，未修改任何实验目录，不更新
`results.json` 或论文 headline，不授权 gauge audit、preflight 或
acceptance。

### 2026-07-17，阶段 A64：interleaved v1.3 两阶段协议在实测前冻结

按 A63 的跨数据集根因证据新增
`reviews/mzm_interleaved_calibration_protocol_v1.3.md`，在任何 v1.3 实测前把
弱轴修正路线冻结为严格独立的 donor/recipient 两阶段。donor 使用与 v1.2 相同的
81 点 paired schedule、同一 0.09 V pilot、每 observation 8 个 16-block 正式窗，
以偶/奇窗形成 A/B 半样本；分别从 formal-only DMM time-truth 仿射残差生成
`d_A(V)`/`d_B(V)`，去除常数与理想 cos/sin 子空间后冻结 81 点精确查表
`d(V)=(d_A+d_B)/2`。表的预注册门为 A/B 相关不低于 0.95、相对差 RMS 不高于
0.35，并要求用 A 修正 B、用 B 修正 A 的 formal/sentinel 交叉半样本结果均通过
50/200 mrad；recipient 不能重新估计、缩放、平滑或用 sentinel 回流更新该表。

donor 与 recipient 均固定 8+8 次 DM858E pre/post 读数并保存逐次时间戳，以均值
修复 A62 定位的单读噪声地板；两阶段还强制复用 static-repeat v1.2 已真实验证的
“全记录有界重试”，只允许完全无数据的 discard/formal 最多 3 次尝试，全部失败
尝试逐条落盘，有效但 rail/guard/headroom 或科学质量差的窗不得 retry。recipient
使用同一 0.09 V pilot，避免跨 pilot 缩放假设，同时比 0.08 V 提高弱轴信号并避开
A51 的 0.10 V 稀有 rail 风险。原 v1.2 schedule、formal/sentinel 防泄漏、
0.05 rad DC 物理门、50/200 mrad mapping 门、0.95 V RAW headroom 和三段独立安全
收尾全部保持不变。

A64 只冻结协议和文件/故障注入合同，未连接仪器、未修改任何既有实验目录、固件、
`results.json` 或论文 headline。下一步是按最终源码 hash 实现 donor/recipient
驱动、聚合器和独立 validator，并完成协议第 8 节的全部离线仿真与故障注入；这些门
通过前不得运行真实 v1.3，更不得启动 gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-17，阶段 A65：v1.3 弱轴表数学、防泄漏和多读合同的纯离线层通过

新增 `scripts/mzm_interleaved_v13_truth.py`，保持 v1.2 的 162-observation schedule
和 SHA-256 不变，固定 v1.3 的 0.09 V pilot、donor 8 窗/recipient 4 窗、每侧 8 次
DMM 读数与最多 3 次完全无数据读取尝试。纯函数严格验证 81 个 grid 各有 up/down
两点；按偶/奇窗半样本分别拟合 formal-only phase-reference map，从 H2 选定坐标残差
形成 `d_A/d_B`，投影去除 `span{1,cos(phi),sin(phi)}` 后冻结最终表及内部 SHA-256。
recipient 只允许精确 grid-index 查表并验证 bias、component、schedule 和 table hash，
不提供插值、缩放或重估入口。

确定性合成把约 1.8 mV 的准周期弱轴杂散叠加到约 6 mV 弱轴上：未修正 formal
median 为 204.52 mrad；A/B profile 相关为 0.999879、相对差 RMS 为 0.01559，
cross-half 修正后 formal median/P95 为 1.906/7.335 mrad、sentinel 为
2.725/9.022 mrad，全部通过冻结 50/200 门。反向/乱序 profile 相关故障、grid
重复、table 内容与 hash 不一致、recipient component 不匹配均被拒绝。

新增 `scripts/mzm_interleaved_v13_contract.py`，定义逐次 `dmm_reads`、窗/丢弃读取
attempt 和主记录镜像字段。合成 162 observations 生成精确 2592 条 DMM raw reads，
8+8 次计数、全局/局部次序、每读 start/end/mid、acquisition bracket、mean value/
mean time 与主记录逐项 replay 全部通过；删除任一读数即拒绝。两个模块均通过
`py_compile`、自测和 `git diff --check`。

A65 仍是硬件无关层，未创建或修改任何实验目录、固件、`results.json` 或论文
headline。下一步接入 segment 采集/聚合与独立文件 validator，并把全记录重试、
DMM CSV/NPZ 和 donor table 文件合同落到最终驱动；离线全门完成前不运行真实硬件。

### 2026-07-17，阶段 A66：新 A/B 表定义在 A57 真实窗上的只读压力测试通过

为在接入硬件驱动前检验 A65 数学不是只对合成数据成立，对 A57 v1.2 bundle 做了
一次不写盘的真实数据压力测试：保持原始 DMM time-truth、schedule 和 selected
components `('Q','Q')`，把每 observation 的四个正式窗预先按偶/奇拆为两个两窗
半样本，并用 A65 的同一投影、A→B/B→A 交叉算法重算。两张弱轴表相关为
0.999970，相对差 RMS 为 0.00787；A→B 的 formal median/P95 为
19.46/50.86 mrad、sentinel 为 22.40/44.27 mrad，B→A 分别为
19.23/53.33 和 22.81/45.56 mrad，均通过冻结 50/200 门。

该结果直接支持 A63 的“杂散是跨窗可重复的确定性偏压函数”，也表明 v1.3 的
cross-half 门在真实噪声量级下有充足裕量；但它使用同一 A57 bundle 的两个半样本，
**不具备 donor/recipient 独立性，不能追认 A57 或替代新 donor run**。本测试只读，
未修改 A57 bundle 或任何实验目录，也未更新论文数字。下一步仍按 A64 先实现并通过
独立 donor 文件链，再允许新的 recipient 采集。

### 2026-07-17，阶段 A67：v1.3 分段采集、聚合和独立 replay 的离线文件链完成

新增 `scripts/diagnose_mzm_interleaved_v13.py`、
`scripts/analyze_mzm_interleaved_v13_segments.py`、
`scripts/validate_mzm_interleaved_v13_segment.py` 和
`scripts/validate_mzm_interleaved_v13_bundle.py`，把 A64 的冻结合同落实为 donor/recipient
各三段、每段独立 run-id 的采集与只读 replay。每段保存 main/formal/discard/DMM 的
CSV+NPZ 镜像、逐次 DMM 时间戳、完整读取失败记录、conditioning、pilot verification、
protocol/analysis/summary/manifest/checksums；聚合器只接受严格按 0/1/2 排列、源码 hash
一致、采集时间不重叠且硬件元数据一致的三段。donor 只有在全局门通过时才发布带内部
SHA-256 的 `spur_correction.{npz,json}`；recipient 冻结 donor bundle 路径及其 checksum/
table hash，不能在本次数据上重估修正。

离线健康链已证明完整机制可闭合：最终一组 donor 合成 bundle 的 A/B profile 相关为
0.999966、相对差 RMS 为 0.00827，A→B/B→A 的 formal median/P95 分别为
1.395/4.477 与 1.353/4.421 mrad，sentinel 为 1.040/4.273 与
1.921/4.090 mrad；独立 recipient 的未修正 formal 为 121.679/345.314 mrad、
sentinel 为 194.934/300.642 mrad，而冻结表修正后分别降至 1.130/3.642 与
1.530/3.937 mrad，bundle replay 为 `accepted=true`。每个完整 bundle 均含 162
observations；donor 为 1296 formal windows，recipient 为 648 windows；两者各含
162 discard 和 2592 条 DMM raw reads。

协议要求的主要故障注入也均按预期被拒绝或被可审计地恢复：discard/formal 的一次
完全无数据读取会记录一次失败后成功；连续三次无数据会失败并保留 0 数据目录；有效
但 rail/headroom 的 formal 窗不触发 retry；缺失 DMM raw read、均值 bracket 漂移、
profile 反相关、A/B 分裂、sentinel-only 杂散、recipient 反号不匹配、segment 重排/
重复以及用旧 v1.2 validator 解释 v1.3 文件均被拒绝。开发期间首个聚合 smoke 因把
`Path` 直接传给只接受字符串的 JSON helper 而失败；该目录永久保留，修复仅把路径显式
转换为 `str`，之后使用新 run-id 重跑通过，未改写失败目录。

A67 尚未连接真实仪器，也未修改既有实验目录、固件、`results.json` 或论文 headline。
在真实运行前还需把 segment validator 从当前部分源码核验收紧为协议记录的全部源码
键集合与逐项 hash 均完全一致；此修改会按设计使上述开发期 final-sim 失效，因此必须
再用新 run-id 重跑最终健康链和关键故障 replay，全部通过后才允许 donor 实测。

### 2026-07-18，阶段 A68：v1.3 最终源码哈希上的完整离线门通过

`validate_mzm_interleaved_v13_segment.py` 已从开发期的部分源码检查收紧为：协议记录的
11 个采集/分析/validator/协议文件键集合必须完全一致，并逐项与当前文件 SHA-256
相等。随后使用新 `freeze3_*` run-id 在该最终采集源码哈希上重新生成 donor 三段、
donor bundle、独立 recipient 三段和 recipient bundle；所有 segment 与 bundle 均由
独立 replay 复现 `accepted=true`。最终 donor 仍为 162 observations、1296 formal
windows、162 discards、2592 DMM reads，A/B profile correlation 0.999966、relative
RMS 0.00827，A→B/B→A formal P95 4.477/4.421 mrad；recipient 为 162/648/162/
2592，未修正 mapping 失败，冻结表修正后的全部 formal/sentinel 50/200 mrad 门通过，
table SHA-256 为 `488b08e907791ab96dc660c08424665f186cd0f92bc01887ae3d7ef25858ccea`。

协议第 8 节的目录级故障在相同采集源码哈希下全部执行并独立 replay：DMM 单读缺失、
formal rail/headroom/sample、discard sample/缺失/重复均令 segment `accepted=false`，
且有效 rail/headroom 记录没有触发 retry；donor profile decorrelation、split、
sentinel-only spur 和 mean-bracket bundle 均只在对应全局门失败；donor 与 recipient
的 discard/formal 单次完全无数据读取各记录一次失败后 `accepted=true`，三次耗尽均
非零退出；首个 discard 落盘后失败保留 1 条 discard，DMM 中途失败保留 4 条 raw
reads，cleanup failure 保留完整数据但 manifest 为 failed，三者均被 validator 拒绝。
segment 缺段、重复、乱序和旧 v1.2 validator 冒充 v1.3 也均在创建 bundle 前拒绝。

recipient 的反号、替换、sentinel-only 和全三段错误缩放 bundle 均被 corrected science
门拒绝。仅对三段中的第 0 段施加 0.45 缩放时，聚合结果仍落在 50/200 mrad 数值门内，
该目录按事实保留，不能冒充协议要求的全局缩放故障；三段全部同样缩放的新 bundle
随后按预期 `accepted=false`。新增只读
`scripts/validate_mzm_interleaved_v13_fault_matrix.py`，在内存或临时副本中进一步验证
table grid/component/finite/internal-hash、recipient bias/component、未应用/反号/
缩放/替代表以及 donor checksum/未 accepted 引用均被拒绝；报告
`build/exp_sim/interleaved_calibration_v13/freeze3_v13_fault_matrix.json` 为
`accepted=true` 并记录 validator 与两个健康 bundle 的哈希。

A68 完成了 A64 冻结的首次真实运行前离线门，但尚未连接真实仪器、未修改任何既有
实验目录、固件、`results.json` 或论文 headline。下一步只允许先做板卡/DMM/固件
基线的只读确认，再按新 run-id 顺序执行真实 donor 0/1/2 段；donor 全局门未通过前
不得运行 recipient，更不得启动 gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-18，阶段 A69：真实 v1.3 donor segment 0 完成并独立 replay 通过

只读台架基线首先确认 `/dev/cu.usbmodem2103` 无 FAULT，板卡为
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`；DM858E 身份为
`DM8E275002095`；冻结 ELF
`/Users/ckdfs/code/biascontrol_h523/build-codex-rawadc/biascontrol.elf` 的 SHA-256 为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`，与
`firmware_rev=8b1b1c2_rawadc_a3785e95` 一致，未修改或刷写固件。

随后用新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v13_donor_s0_board2/`
完成冻结 schedule 的 donor segment 0。用时 2798.8 s；54 observations、432 formal
windows、54 discards、864 条逐次 DMM reads 全部落盘，读取失败/retry 为 0；正式窗
最大绝对 RAW 为 0.837607 V，低于 0.95 V headroom 门。DMM 每侧 8 次读数的 side-std
median/P95 为 13.23/20.81 mV，adjacent absolute difference median/P95 为
13.41/44.24 mV，与 A62 的快读噪声地板一致且由均值合同完整吸收。驱动质量门为
`accepted=true`，独立 `validate_mzm_interleaved_v13_segment.py` replay 精确复现
54/432/54/864 和 `accepted=true`。

驱动退出后的 manifest 与另一次独立串口查询均确认
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。A69 不聚合、不生成校正表，不修改
`results.json` 或论文 headline；下一步只能运行新的 donor segment 1，待 0/1/2
三段全部独立通过后再聚合 donor。

### 2026-07-18，阶段 A70：真实 v1.3 donor segment 1 完整落盘但被 RAW headroom 门拒绝

新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v13_donor_s1_board2/`
按冻结参数完成 segment 1 的全部 54 observations、432 formal windows、54 discards
和 864 条 DMM reads，用时 2680.7 s，读取失败/retry 为 0。独立 replay 精确复现
`accepted=false`，唯一失败项为 `formal_headroom_pass=false`；schedule、conditioning、
pilot、discard、RAW 完整性/rail/guard、DMM、retry 和 timing 其余门全部通过。

超限只发生在一个有效正式窗：global sequence 105、window 2、formal/down、grid 42、
bias 1.075871 V，CH0 min/max code 为 -2890384/+6859010，对应最大绝对 RAW
0.981189 V，超过冻结的 0.95 V headroom 门；该窗没有 rail 或 guard flag。协议明确
禁止对有效但 headroom 不足的窗 retry，因此未删除、未重测、未放宽阈值。DMM 8-read
side-std median/P95 为 13.07/22.42 mV，adjacent difference median/P95 为
13.41/40.55 mV，DMM 合同本身通过。

驱动 manifest 与另一次独立串口查询均确认
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。该完整 rejected 目录永久保留，不覆盖、
续跑或挑窗拼接；也不只重跑 s1 以追求通过。为避免 outcome-dependent 提前停止，仍按
原冻结 schedule 完成新的 donor segment 2，之后仅生成/验证一个如实 rejected 的
derived donor bundle；不得发布修正表或运行 recipient。A70 不修改固件、
`results.json` 或论文 headline。

### 2026-07-18，阶段 A71：真实 v1.3 donor segment 2 完成并独立 replay 通过

新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v13_donor_s2_board2/`
按冻结 schedule 完成 segment 2，用时 2729.7 s；54 observations、432 formal
windows、54 discards、864 条 DMM reads 全部落盘，读取失败/retry 为 0。驱动与独立
segment replay 均为 `accepted=true`，正式窗最大绝对 RAW 为 0.841520 V，低于
0.95 V headroom 门；DMM side-std median/P95 为 13.64/21.83 mV，adjacent
difference median/P95 为 13.41/40.55 mV，DMM 多读合同通过。

驱动 manifest 与又一次独立串口查询均确认
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。至此真实 donor 的三个预注册 segment
均完整采集：s0 与 s2 通过，s1 因一个有效 formal 窗的 0.981189 V headroom 超限而
拒绝。下一步只允许用这三个不可变目录生成并独立 replay 一个如实 rejected 的 derived
donor bundle；`all_segments_pass` 必须为 false，聚合器不得发布
`spur_correction.npz/json`，recipient 继续被阻断。A71 不修改固件、`results.json`
或论文 headline。

### 2026-07-18，阶段 A72：真实 v1.3 donor bundle 如实拒绝，recipient 前置门未满足

用 A69–A71 的三个不可变真实 segment 生成新 derived 目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v13_donor_board2_bundle_rejected/`。
聚合器与独立 bundle replay 均复现 162 observations、1296 formal windows、162
discards、2592 DMM reads、0 read failures，并按预注册得到 `accepted=false`：唯一全局
阻断项是 `all_segments_pass=false`，来源即 A70 的 s1 单窗 headroom 失败。time-truth、
target-time 正交性、8-read mean bracket 和 spur-correction science 门均通过；聚合器
按合同没有生成 `spur_correction.npz` 或 `spur_correction.json`。

尽管不能发布表，完整 donor 数据的只读诊断支持 A63 的物理结论：选定 components 为
`('Q','Q')`，`d_A/d_B` 相关为 0.999964、relative split RMS 为 0.00849，profile
RMS 为 2.040 mV；A→B/B→A cross-half 的 formal median/P95 为 15.54/45.17 与
16.15/48.28 mrad，sentinel 为 18.09/54.21 与 17.99/59.16 mrad，均通过
50/200 mrad 门。DMM normalized mean-bracket median/P95/max 为
0.01102/0.03038/0.03869，低于 `sin(0.05)`；direction split 4.51 mrad、30 min
drift 22.39 mrad，time-truth 门通过。board DC rail 仍仅为 advisory，没有被误作
DM858E truth 失败。

A72 的结论是严格的前置门失败，而不是杂散校正数学失败：不得从 rejected bundle
手工导出或使用修正表，不得运行任何 recipient segment，也不得启动 gauge audit、
v1.4 preflight 或 acceptance。三个真实 segment、rejected bundle 和所有失败事实永久
保留；不更新 `data/exp/results.json`、论文 headline 或固件。若继续实验路线，必须先
另行预注册一个不依赖 A72 结果挑窗、且要求完整新 campaign 的 headroom 处理协议；
不能只重跑 s1 或放宽 0.95 V 门。

### 2026-07-18，阶段 A73：v1.3.1 headroom 修订冻结并通过最终源码离线门

新增 `reviews/mzm_interleaved_calibration_protocol_v1.3.1.md` 及一组独立版本化
`v131` 采集、分析和 validator 文件，未修改已冻结 v1.3 源码。v1.3.1 的唯一物理
修订是在任何新实测前把 donor/recipient 的共同 pilot 从 0.09 V 固定降为 0.07 V；
0.95 V、零 rail/guard、50/200 mrad、DMM 8+8 多读、全记录有界重试且只限完全无
数据读取等门全部不变。新协议要求从 donor segment 0 开始完整新 campaign，禁止
只补 A70 的 s1、挑窗或按结果再次改 pilot。0.07 V 位于 A44 已实测通过的
0.06/0.08 V 之间，并针对 A57 的 0.08 V 尾值 0.949388 V 与 A72 的 0.09 V 尾值
0.981189 V 预留幅度余量，同时比 0.06 V 保留更强 H2。

纯数学和 DMM 合同自测通过。首次 `freeze4` recipient 聚合暴露一个开发期路径命名
错误：采集段已写 `interleaved_calibration_v131`，聚合器仍写旧 `v13` 目录；该批
开发目录永久保留。只修正输出目录名后，在最终源码 hash 上用全新 `freeze5` run-id
完整重做 donor 三段、donor bundle、独立 recipient 三段和 recipient bundle；全部
segment 与两个 bundle 的独立 replay 均为 `accepted=true`。donor 为 162 observations、
1296 formal windows、162 discards、2592 DMM reads，三段仿真最大 raw 均为
0.715256 V；profile correlation 0.999966、relative split RMS 0.00827，A->B/B->A
formal P95 7.388/7.468 mrad。recipient 为 162/648/162/2592，未修正 mapping 按预期
失败，冻结表修正后 corrected science 全部通过。

最终源码故障门也已闭合：discard/formal 单次无数据失败后完整记账并通过，三次耗尽、
DMM 中途失败、discard 后失败和 cleanup failure 均非零退出并保留 partial；formal
rail/headroom/sample、discard sample/缺失/重复和 DMM 单读缺失均被 segment 拒绝，
有效 headroom 记录没有 retry。donor mean-bracket、profile decorrelation/split、
sentinel-only spur，以及 recipient 反号/替换/sentinel-only/全三段错误缩放均只在对应
全局科学门失败；table grid/component/finite/hash、donor checksum/未 accepted 引用、
segment 重排/重复及旧 v1.3 validator 冒充 v1.3.1 均被拒绝。只读 fault matrix
`freeze5_v131_fault_matrix.json` 为 `accepted=true`。

A73 未连接真实仪器，未修改固件、`data/exp/results.json` 或论文 headline。离线前置门
现已满足；下一步只允许先做串口、DM858E、ELF hash 和安全状态的只读确认，然后按新
run-id 顺序执行完整真实 v1.3.1 donor 0/1/2。donor 全局门通过前仍不得运行 recipient、
gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-18，阶段 A74：v1.3.1 真实 donor 前置检查被板卡 USB 未枚举阻断

在任何新实验目录或偏压输出前执行只读台架检查。冻结 ELF 的 SHA-256 仍为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`；DM858E 正常
在线，身份为 `Rigol Technologies,DM858E,DM8E275002095,00.01.00.00.22`。但系统中
不存在 `/dev/cu.usbmodem*`，USB 设备树和 `pyocd list` 也均未发现板卡或调试探针，
故现有受审计驱动在创建真实 run-id 和输出偏压前安全停止。未执行复位、刷写、采集或
任何硬件写操作；没有新真实实验目录，因而也没有需要拼接或重跑的数据。

已启动只读端口监测；板卡 USB/供电恢复并重新枚举后，必须重新确认无 FAULT 且状态为
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`，再从全新 donor segment 0 run-id 开始。
DM858E 在线不能替代板卡缺失，本阻断也不授权跳过 donor、运行 recipient 或后续
gauge/preflight/acceptance。

### 2026-07-18，阶段 A75：真实 v1.3.1 donor segment 0 完成并独立通过

板卡重新连接后，只读基线重新确认 `/dev/cu.usbmodem2103` 无 FAULT，状态为
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`；DM858E 身份仍为 `DM8E275002095`，冻结
ELF SHA-256 仍精确为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`，未复位、修改
或刷写固件。

随后用全新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v131_donor_s0_board2/`
完成 0.07 V 的 v1.3.1 donor segment 0。用时 2797.1 s；54 observations、432 formal
windows、54 discards、864 条逐次 DMM reads 全部落盘，读取失败/retry 为 0。正式窗
最大绝对 RAW 为 0.919598 V，低于冻结的 0.95 V headroom 门；零 rail/guard，驱动
质量门为 `accepted=true`，独立 `validate_mzm_interleaved_v131_segment.py` 精确 replay
同样为 `accepted=true`。

DMM 8-read side-std median/P95 为 13.55/21.35 mV，adjacent absolute difference
median/P95 为 14.75/40.22 mV，与 A62 噪声地板一致且由多读均值合同吸收。驱动
manifest 和退出后的另一条独立串口连接均确认精确
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。A75 不聚合、不生成修正表，不修改
`results.json` 或论文 headline；下一步只运行全新 donor segment 1。

### 2026-07-18，阶段 A76：真实 v1.3.1 donor segment 1 完整落盘但被单窗 RAW rail 拒绝

新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v131_donor_s1_board2/`
完成全部 54 observations、432 formal windows、54 discards 和 864 条 DMM reads；读取
失败/retry 为 0。驱动与独立 replay 均为 `accepted=false`，失败项为
`formal_raw_pass=false` 和 `formal_headroom_pass=false`；schedule、conditioning、pilot、
discard、DMM、retry 和 timing 其余门全部通过。

超限只发生在一个有效正式窗：window sequence 81、global observation 64、window 1、
formal/up、grid 77、bias 5.645242 V。CH0 min/max code 为 -3370393/+8388607，正 rail/
guard 计数为 1276/1277，最大绝对 RAW 为 1.200000 V。该记录是第二个正式窗而非 startup
discard，且有完整 tones/DC/RAWADC，因此按冻结规则不得 retry、删除或改作无数据失败。
这表明把 pilot 从 0.09 V 降至 0.07 V 仍不能排除长序列中的稀有瞬态削顶。

DMM 合同通过：8-read side-std median/P95 为 14.47/21.88 mV，adjacent difference
median/P95 为 14.75/42.90 mV。驱动 manifest 与独立串口查询均确认退出后精确
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。本完整 rejected 目录永久保留；不得只重跑
s1。为避免 outcome-dependent 提前停止，下一步仍完成全新 donor s2，随后只生成并
验证一个如实 rejected 的 derived bundle；不得发布修正表或运行 recipient。

### 2026-07-18，阶段 A77：首次 v1.3.1 donor s2 在零数据启动阶段被主机进程中断

首次 s2 新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v131_donor_s2_board2/`
已写入 protocol、空 CSV、acquisition/pilot 配置校验；在首条 discard、DMM 或正式窗
落盘前主机进程异常终止。目录保持 `manifest.status=failed`、
`failure=initialization incomplete`，计数为 0 observations、0 windows、0 discards、
0 DMM reads；没有可与后续数据拼接的有效测量。进程退出后独立确认系统仍枚举
`/dev/cu.usbmodem2103`，板卡无 FAULT 且为
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。

该空失败目录永久保留，不续跑、不覆盖。因为中断发生在完全无数据的启动阶段，按 A73
全记录有界失败原则，下一步允许用全新 `s2b` run-id 从 segment 2 起点完整重做；不得
读取或复用该目录的 pilot verification 作为新运行证据。s2b 结束前仍不聚合。

### 2026-07-18，阶段 A78：真实 v1.3.1 donor segment 2b 完成并独立通过

用全新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v131_donor_s2b_board2/`
从 segment 2 起点完整重做，未读取或拼接 A77 的空失败目录。运行用时 2733.5 s；
54 observations、432 formal windows、54 discards、864 条 DMM reads 全部落盘，读取
失败/retry 为 0。驱动和独立 replay 均为 `accepted=true`，正式窗最大绝对 RAW
为 0.677197 V，低于 0.95 V 且零 rail/guard。

DMM 8-read side-std median/P95 为 13.92/21.68 mV，adjacent difference median/P95
为 14.75/40.22 mV；多读合同通过。驱动 manifest 与独立串口查询再次确认退出后精确
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。至此 v1.3.1 的完整真实 donor 数据为：
s0 通过、s1 因一个有效正式窗正 rail 拒绝、s2b 通过；A77 的零数据 s2 不参与。
下一步只允许用 s0/s1/s2b 生成并独立 replay 一个如实 rejected 的 derived donor
bundle，`all_segments_pass` 必须为 false，不得发布修正表或运行 recipient。

### 2026-07-18，阶段 A79：真实 v1.3.1 donor bundle 如实拒绝，0.07 V 未消除稀有 RAW 瞬态

使用 A75/A76/A78 的不可变 s0/s1/s2b 目录生成新 derived 目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v131_donor_board2_bundle_rejected/`。
聚合器与独立 bundle replay 均复现 162 observations、1296 formal windows、162
discards、2592 DMM reads、0 read failures，并按预注册得到 `accepted=false`。唯一全局
阻断是 `all_segments_pass=false`，来源为 A76 s1 的单窗正 rail；聚合器按合同没有生成
`spur_correction.npz` 或 `spur_correction.json`。

完整数据的科学门仍全部通过：components 为 `('Q','Q')`；`d_A/d_B` profile correlation
0.999255、relative split RMS 0.03894、profile RMS 1.938 mV；A->B/B->A cross-half 的
formal median/P95 为 15.32/54.10 与 17.22/56.77 mrad，sentinel 为 14.48/54.53 与
16.43/50.39 mrad。DMM normalized mean-bracket median/P95/max 为
0.01051/0.03467/0.04606，低于 `sin(0.05)`；方向分裂 1.22 mrad、30 min 漂移
9.55 mrad，time-truth 门通过。board DC clipping 继续仅为 advisory。

A79 证明 0.07 V 已保留足够的弱轴校正科学裕量，却仍不能可靠避开长序列稀有 RAW
瞬态；继续只靠小幅降 pilot、重跑碰运气不是可接受方案。不得从 rejected bundle
手工发布表或运行 recipient。下一步必须在任何新实测前另行冻结一个完整新 campaign
协议：进一步提供明确模拟量余量，并用预先增加的 formal averaging 抵消 H2 二次下降；
仍不得放宽 0.95 V/rail 门，也不得允许有效 rail/headroom 记录 retry。

### 2026-07-18，阶段 A80：v1.3.2 余量修订冻结并通过最终离线与故障门

新增独立版本化协议 `reviews/mzm_interleaved_calibration_protocol_v1.3.2.md` 及 `v132`
采集、纯合同、聚合和独立 validator 文件；v1.3/v1.3.1 的源码和真实目录均未修改。
根据 A75 的 0.07 V 最大 RAW 0.919598 V 线性估算和 A44 的 0.06 V full-grid 实测，
共同 donor/recipient pilot 在任何 v1.3.2 数据前冻结为 **0.04 V**。为抵消弱轴 H2
约随 pilot 平方下降，donor formal averaging 从 8 增为 16 窗（偶/奇各 8 窗独立
半样本），recipient 从 4 增为 8 窗；DMM 仍为 8+8。0.95 V、零 formal rail/guard、
50/200 mrad、相同 schedule、只允许完全无数据读取最多三次且全记录的重试合同均不变；
必须从 donor s0 开始完整新 campaign，不能补跑 A76 或复用 A79。

首次 `freeze6` 健康仿真正确暴露 donor 平均数翻倍后模拟 session 的固定 1200 s 时间轴
间距不足，聚合器因 acquisition time overlap 拒绝。该开发目录保留；只把 v1.3.2
模拟时轴间距增至 2400 s 后，在新 `freeze7` run-id 和最终采集源码 hash 上从头完成
donor 三段、donor bundle、独立 recipient 三段和 recipient bundle。所有 segment 与
bundle 独立 replay 均为 `accepted=true`。donor 为 162 observations、2592 formal
windows、162 discards、2592 DMM reads；profile correlation 0.999980、relative split
RMS 0.00635，A->B/B->A formal median/P95 为 3.78/15.20 与 3.99/16.59 mrad，
sentinel 为 3.19/13.05 与 4.91/10.90 mrad。recipient 为 162/1296/162/2592，未修正
mapping 按预期失败，冻结表修正后的 direction、pair-position、early/late formal 与
sentinel 门全部通过；健康仿真的各段最大 RAW 为 0.715256 V。冻结 table SHA-256 为
`9fead207e24f1fa81aa247c19de91cf105e2fa39c6ab1a86f09104f7e9809482`（仅模拟表）。

最终目录级故障门也全部闭合。donor/recipient 的 discard/formal 单次完全无数据读取
各记录一次失败后恢复并 accepted；三次耗尽、首 discard 后中断、DMM 第四次读取后
中断和 cleanup failure 均非零退出、保留 partial/完整审计数据并被 validator 拒绝。
formal rail/headroom/sample、discard missing/duplicate/sample、DMM 单读缺失均被
segment 门拒绝，有效 rail/headroom 窗 read-failure 仍为 0，证明不会误 retry。
donor 的 mean-bracket、profile decorrelation/split、sentinel-only spur，以及 recipient
的 mean-bracket、反号、缩放、替换和 sentinel-only 故障均由全局 bundle replay 复现
`accepted=false`。只读 `freeze7b_v132_fault_matrix.json` 为 `accepted=true`，17 项覆盖
table grid/component/finite/hash、recipient bias/component/未修正/错误表、donor
checksum/未 accepted 引用、schedule 篡改、缺段/重复/乱序及旧 v1.3.1 validator。

A80 未连接或写入真实仪器，未修改固件、`data/exp/results.json` 或论文 headline。
v1.3.2 首次真实运行前置门现已满足；下一步只允许先独立确认板卡/DMM/ELF 与精确安全
状态，再按全新 run-id 顺序执行真实 donor s0/s1/s2。donor 全局门通过前不得运行
recipient、gauge audit、v1.4 preflight 或 acceptance。

### 2026-07-18，阶段 A81：真实 v1.3.2 donor segment 0 完整落盘但再次被 RAW 瞬态拒绝

真实前置只读检查确认 `/dev/cu.usbmodem2103` 无 FAULT，板卡精确为
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`，DM858E 为 `DM8E275002095`，冻结 ELF
完整 SHA-256 仍为
`a3785e95a056ea2dab278985feb34b1dbc4d8f9fe886d0be2b278e3927534db1`；未 reset/flash。
全新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v132_donor_s0_board2/`
按 0.04 V pilot、16 formal windows 和 8+8 DMM 完成全部 54 observations、864 formal
windows、54 discards、864 DMM reads、872 conditioning rows，用时 3795.9 s。所有读取
一次成功，read failures/retries 为 0；DMM side std median/P95 为 13.59/20.04 mV，
adjacent difference median/P95 为 13.41/38.88 mV。

驱动和独立 replay 均如实得到 `accepted=false`，只有 `formal_raw_pass` 与
`formal_headroom_pass` 失败。共有两个有效正式窗超出硬门，均为首次读取且不得 retry：

- window 210，global observation 13，window 2，formal/down，grid 37，bias 0.423103 V：
  CH0 `-2106771/+8243820`，无 rail/guard 计数但最大绝对 RAW 1.179288 V，超过 0.95 V；
- window 768，global observation 48，window 0，formal/up，grid 79，bias 5.906349 V：
  CH0 `-1643954/+8388607`，1974 个正 rail、1977 个正 guard，最大绝对 RAW 1.200000 V。

其余 schedule、conditioning、pilot、discard、window 数量、DMM、多读重试与 timing
合同全部通过。manifest 的程序内最终状态和随后独立新连接均确认精确安全状态
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。A81 证明稀有正向 RAW 瞬态不能靠把 pilot
从 0.07 V 进一步降到 0.04 V 消除，因而更像 pilot 无关的偶发增益/前端事件；不得重跑
s0、删窗、发布表或运行 recipient。v1.3.2 已冻结为完整新 campaign 且没有 outcome-
dependent 早停，下一步仍用全新 run-id 完成 donor s1/s2，再生成一个如实 rejected 的
bundle，以量化完整校正科学和瞬态发生率；期间不启动 gauge、v1.4 或 acceptance。

### 2026-07-18，阶段 A82：真实 v1.3.2 donor segment 1 完成并独立通过

全新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v132_donor_s1_board2/`
按冻结 schedule 完成 54 observations、864 formal windows、54 discards、864 DMM
reads，用时 3677.6 s；读取失败/retry 为 0。驱动和独立 replay 均为
`accepted=true`，正式窗最大绝对 RAW 仅 0.371290 V，低于 0.95 V 且全段零
rail/guard。DMM side std median/P95 为 13.25/20.16 mV，adjacent difference
median/P95 为 12.74/37.54 mV，多读合同通过。

程序内 manifest 与随后独立串口查询均确认精确安全状态
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。A82 与 A81 的巨大 RAW 尾值差异进一步支持
“稀有、非稳态、pilot 非主导”的判断；但不得用 s1 通过覆盖 s0 失败。下一步只允许
全新 donor s2，随后用 s0/s1/s2 生成并 replay 一个如实 rejected 的完整 bundle；不发布
修正表、不运行 recipient/gauge/v1.4/acceptance。

### 2026-07-18，阶段 A83：真实 v1.3.2 donor segment 2 完成并独立通过

全新目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v132_donor_s2_board2/`
完成 54 observations、864 formal windows、54 discards、864 DMM reads，用时
3733.1 s；读取失败/retry 为 0。驱动与独立 replay 均为 `accepted=true`，正式窗最大
绝对 RAW 为 0.856639 V，低于 0.95 V 且零 rail/guard。DMM side std median/P95 为
12.99/19.93 mV，adjacent difference median/P95 为 13.41/37.54 mV；全部多读合同通过。

程序 manifest 与独立串口查询均确认退出后精确
`IDLE / 0.000 V / Lock=NO / Cal=INVALID`。v1.3.2 完整真实 donor campaign 现为：s0
因两个有效正式窗 headroom/rail 失败，s1 与 s2 通过，三段均 0 retry。下一步只允许
聚合 s0/s1/s2 并独立 replay 如实 rejected 的 derived bundle；`all_segments_pass` 必须
为 false，不能生成 `spur_correction`、运行 recipient 或启动 gauge/v1.4/acceptance。

### 2026-07-18，阶段 A84：真实 v1.3.2 donor bundle 如实拒绝，pilot 路线判定耗尽

使用 A81/A82/A83 的不可变 s0/s1/s2 目录生成 derived 目录
`data/exp/diagnostics/interleaved_spur_calibration/20260718_interleaved_v132_donor_board2_bundle_rejected/`。
聚合器和独立 bundle replay 均复现 162 observations、2592 formal windows、162
discards、2592 DMM reads、0 read failures，并得到 `accepted=false`。`all_segments_pass`
因 A81 s0 的两个有效 RAW 窗失败；聚合器按合同没有生成 `spur_correction.npz/json`。

全局 DMM mean-bracket 门也失败：normalized median/P95/max 为
0.01271/0.04842/0.20738。最大值恰好位于 A81 的 rail observation 48：同一 bias 的
8-read DMM 均值从 0.373529 V 变到 0.208131 V，绝对差 165.398 mV，表明该事件同时
影响独立光学 DC，而不是单纯 ADC 码溢出或 DM858E 单读噪声；P95 仍低于
`sin(0.05)`。time-truth 其余门通过：direction split 5.04 mrad、30 min drift
10.69 mrad、target-time correlation 0.00270，board DC clipping 继续只作 advisory。

弱轴表的科学重复性仍通过：components `('Q','Q')`，profile correlation 0.999950、
relative split RMS 0.01009、profile RMS 1.198 mV；A->B/B->A formal median/P95 为
23.53/74.98 与 23.80/91.79 mrad，sentinel 为 28.01/61.79 与 21.07/68.19 mrad，
均低于 50/200 门。但 rejected bundle 绝不能手工导出该表。

A72/A79/A84 已分别证明 0.09/0.07/0.04 V 均会出现稀有有效正式窗 RAW 瞬态，继续降
pilot 或重跑碰运气的路线到此耗尽；0.04 V 事件还伴随 165 mV 光学 DC 跃变。下一步
不得启动 recipient/gauge/v1.4/acceptance，而应只读审计模拟前端/PD-TIA 链与现有可调
衰减/增益能力，并冻结一个不改固件的前端 headroom/光功率稳定化诊断。若台架没有
可程序控制或可人工固定的衰减/增益手段，则这是需要作者物理接线的真实硬阻断，不能
用软件门或删窗规避。

### 2026-07-18，阶段 A85：单 MZM 投稿稿完成证据重定位与反防御性语言修订

按截止期主线，仅使用已经完成且可追溯的真实实验修订 `paper_mzm_zh.tex`，未启动
recipient/gauge/v1.4/acceptance，也未修改 `data/exp/results.json`、固件或任何既有实验
目录。标题调整为“面向 MZM 任意点偏压控制的精确仿射建模与全周期辨识”，使稿件主张
与现有证据一致：理论主线是精确仿射结构、`O(2)` 规范和全周期可辨识性；硬件主线是
模型拟合、静态全周期目标映射、采集重复性和逐 RF 状态重辨识，不宣称已取得健康的
长期稳定闭环或相对公开强基线的性能优越性。

摘要、引言贡献、实验流程、表格与图注、讨论和结论完成反防御性改写。原先散布在高影响
位置的“不能证明/不作为证据/留待后续”等措辞被改为正面说明各指标的任务：尾段中心评价
静态设定点映射，逐周期序列评价动态稳定性；H1 是共用数据通路的单坐标结构消融；周期--2
记录直接用于识别弱轴噪声、增益与端到端时延的耦合。被 A84 拒绝的 v1.3.2 bundle 未被
写入稿件或选择性引用。

新增一项已冻结并完整通过的真实证据：v1.2 静态重复实验覆盖 5 点 × 4 种重启状态 ×
12 次，共 240 repeats / 480 formal windows。独立执行
`validate_mzm_static_repeats.py --replay-dir .../20260717_static_v12_board2` 复现
`accepted=true`；正式窗最大绝对 RAW 为 0.672072 V，各块 H1 参考相位最大圆标准差为
0.330405 mrad，发生器/采集器/联合重启均未达到预注册异常阈值。稿件按合理精度报告为
0.672 V 和 0.330 mrad。作者姓名与通信邮箱在仓库中没有真实值，正文只保留一个明确的
投稿元数据替换块，不推测作者身份。

### 2026-07-18，阶段 A86：投稿 PDF、事实语言复核与仓库质量门完成

新增独立只读审查报告 `reviews/mzm_submission_factual_language_review_2026-07-18.md`，
逐项建立理论主张、仿真合同、`data/exp/results.json`、静态重复 v1.2 replay 与正文表述的
映射。结论是：按“精确仿射建模 + 全周期可辨识性 + 真实硬件验证”的定位，正文主张与
证据一致；静态目标中心和逐周期动态已分开，A84 rejected bundle 未进入任何正面结论。

使用仓库 TeX Live/XeLaTeX 工具链重建 `paper_mzm_zh.pdf`，产物为 10 页 letter 版；日志
无 undefined reference/citation，无 >=20 pt overfull，仅保留既有 12.45 pt 轻微 overfull。
以 110 dpi 渲染并逐页检查 10 页，标题、中文字体、公式、算法、图 1--12、表 I--III、
新增静态重复行及参考文献均无裁切、重叠、空白页或不可读字形。最终 `make check` 对
MZM/DPMZM 双稿均为 0 FAIL，总计 4 个既有 WARN（未引用标签与
`build/sim_output.txt` 缺失）；未为消除 WARN 重跑随机图。`git diff --check` 通过，
`data/exp/results.json` 无差异。

科学正文与 PDF 已完成。提交前唯一外部元数据项是首页真实作者姓名、通信邮箱，以及投稿
系统所需基金/作者信息；仓库没有这些事实，仍保留明确替换块。

### 2026-07-19，阶段 A87：实验节按 IEEE 图证叙事重构并补齐静态重复可视化

只读对照 Zotero 中 Wang 2010、Sotoodeh 2011、Li 2018、Zhang 2023 和 Weller 2025
等 IEEE 实验论文后，将 `paper_mzm_zh.tex` 的实验节从七阶段流程清单重构为“平台与评价
协议—标定与样本外反演—全周期响应与闭环动态—RF 状态重辨识与采集重复性”四个问题。
正文以图证后的趋势和物理解释为主，保留表格作为跨实验摘要；静态设定点评价与逐周期
动态仍严格分开，未把周期--2 记录改写成稳定锁定。

在 `scripts/make_exp_figs.py` 的既有绘图顺序末尾追加离线图
`figs/fig_exprepeat_mzm.pdf`，只读取冻结目录
`data/exp/diagnostics/static_repeats/20260717_static_v12_board2/analysis.json`。图中展开
5 个满周期点、none/gen/acq/both 四种条件和每种 12 次重复：H1 最大圆标准差
0.330 mrad、最大重启增量 0.287 mrad，H2 最大圆标准差 29.9 mrad，并同时显示
20 mrad 重启增量尺度与 50 mrad 环境判据。长运行动态与静态重复图在稿件中合并为
一张双栏证据图，使全部实验图在讨论前收束且 PDF 保持 10 页。

本阶段没有重跑实验、修改任何既有实验目录、`data/exp/results.json`、固件或论文
headline。XeLaTeX 重建成功；相关页面逐页检查无裁切、重叠或不可读字形；MZM 数字、
图文件与实验合同检查为 0 FAIL / 2 个既有 WARN，双稿最终门另行复核。

### 2026-07-19，阶段 A88：图 7/8/12 重绘与实验图占位压缩

按最终单栏宽度修复三处图形问题。`scripts/make_algo_figs.py` 将图 7(b) 图例移至左上角；
图 8(a) 删除会越过坐标轴上边界的自动 inset 连接线，改用轴内半透明窗口标记，31 周期
局部放大与红/蓝事件线保持不变。两图均在临时目录按固定 RNG 顺序重建，仅将对应
`fig_acqstep_mzm.pdf` 和 `fig_recal_mzm.pdf` 产物更新到稿件目录，没有重生成或覆盖其余
算法图。

新增 `figs/fig_expdiag_mzm.pdf`，由 `scripts/make_exp_figs.py` 直接读取既有
`stability.npz`、`drift.npz` 与冻结 static-repeat v1.2 `analysis.json`，不再把两张双面板
PDF 二次缩放拼接。新图按单栏 2×2 排列：(a) 3 h 奇偶周期误差的 61 点移动均值与 DMM
稀疏点，直接显示周期--2 双分支；(b) 阶跃、残差阈值与 +6 周期重扫；(c)(d) H1/H2
静态重复性。稿件图 12 改用该单栏图，双栏占位被释放，整稿仍为 10 页。

本阶段只改变可视化与浮动排版，没有重跑真实实验，没有修改实验目录、
`data/exp/results.json`、数值合同、固件或 headline。最终 PDF 中图 7(b) 图例位置正确，
图 8(a) 无越界/裁切，图 12 四面板无重叠且轴、图例和阈值线在最终栏宽下可辨。

### 2026-07-19，阶段 A89：删减低信息量方案表并重绘图 3 决策流程

删除原表 1“MZM 锁定方案统一对照”。该表仅压缩重复第 II 节已给出的传统读出局限、
静差公式和本文方法条件，没有新增定量证据；必要结论已迁回“一致增益闭环”首次使用处，
明确在 $A$ 满秩且规范固定时获得全周期反演和目标点无关的小信号增益。原数值验证表与
硬件验证表由 LaTeX 自动顺延为表 1、表 2，交叉引用仍使用标签。

重绘 `figs/fig_flow_mzm.pdf`：自检与残差阈值两个判断节点由圆角矩形改为菱形；删除
“触发重定标（满周期重扫）”中间框，阈值“是”分支改为沿左侧长回路直接指向
“上电 / 重定标请求”，“否”分支沿右侧返回锁相读出。各分支的“是/否/重扫/
下一周期”标签统一置于对应线段的几何中点并保持水平，避免旋转文字和手工偏移造成的
错位。修改仅涉及绘图代码与投稿排版，没有重跑实验、改变 RNG 消耗顺序、修改
`data/exp/results.json`、固件或任何实验目录。

### 2026-07-19，阶段 A90：图 6 改为单栏内左右双列并压缩占位

将 `figs/fig_gauge_mzm.pdf` 从单栏内 2×1 上下堆叠改为 1×2 左右双列，保持原有
`bias_reg`、`bias_arg`、`Ns`、`med_reg` 与 `med_arg` 数组不变，仅在既有计算之后
重排绘图。面板标题缩短为“(a) $N=360$”与“(b) 随 $N$ 的标度”；(b) 的对数横轴
仅标出 90、360、1440 三个主刻度，全部五个采样点仍完整显示。图例、轴标题和散点尺寸
按最终单栏宽度重新整定，图高由约 3.5 in 降至约 1.72 in，释放的版面使图 7 可进入
同页右栏。

本阶段没有重跑实验或改变仿真数组与 RNG 消耗顺序；没有修改实验目录、
`data/exp/results.json`、数值合同、固件或 headline。

### 2026-07-19，阶段 A91：全稿图 1--12 必要性与信息增量复核

以 105 dpi 重渲染并逐页检查当前 10 页投稿 PDF，同时逐图核对正文引用、图注、表 1--2
与算法 1--3。所有图均有引用且无裁切、重叠或字体失真，但主文存在明显的示意图、算法和
单点仿真重复。建议保留图 1、5、6、7、9、10、11 以及图 12(a)(b)：它们分别承担核心
仿射几何、全周期与噪声、规范固定标度、目标无关动态、真实平台、实测模型闭合、主要硬件
结果和真实闭环动态，均有不可替代的信息增量。

建议从主文删除图 2、3、4、8。图 2 与图 9、算法 1 重复；图 3 与算法 2--3 及第 VI 节
流程文字逐项重复，且是占位最高的单栏图；图 4 的单目标比较已由表 1、图 5(a) 的全周期
比较和图 7 的动态行为覆盖；图 8 的仿真重定标已由表 1、状态机/算法及图 12(b) 的真实
触发记录覆盖。面板级建议是删除图 10(b) 的相位标签重参数化，并将图 12(c)(d) 的静态
重启诊断移至补充材料或开放数据说明，主文保留 240 次重复的摘要数值。

发现一个需在下一轮绘图修复的视觉语义问题：图 10(c) 的 $X(\mathrm{H2})$ 与
$Y(\mathrm{H1})$ 轴分别自动缩放，使 $\kappa(\hat A)=45.24$ 的强各向异性轨迹看起来
近似圆形。应改为能直接显示弱轴比例的共同物理尺度，或明确标注“坐标轴分别缩放”，避免
图形与条件数结论产生表观冲突。本阶段仅形成审查结论，没有修改正文、图文件、实验数据、
固件或 headline。

### 2026-07-19，阶段 A92：主文图形删减、实验图重构与结果表重排

按投稿主线删去原图 4 的单点闭环比较和原图 8 的仿真重定标记录；两图中的定量结果仍由
正文与数值表给出，源绘图代码和 PDF 作为可复现档案保留。原图 10 由四面板压缩为三面板，
删除由直流拟合重复生成的相位标签图；实测 H2/H1 椭圆改用相同观测单位、相同轴跨度与等比例
坐标，直接显示 $\kappa(\hat A)=45.24$ 对应的弱轴。原图 12 删除静态重复实验的 (c)(d)，
仅保留 3 h 周期--2 诊断和残差触发重扫；240 次静态重复的预注册口径与关键数值保留在正文。

数值表按“模型闭合与标定／闭环与监督动态”分组，统一为“验证项—结果—设置”；硬件表删除
跨协议并列的仿真列，改为“验证任务—协议—实验结果”，并按“标定与静态映射／闭环动态／
RF 状态与采集重复性”分组。实验数值、检查器唯一行键和来源合同均未改变。本阶段没有重跑
实验，没有修改任何实验目录、`data/exp/results.json`、固件或论文 headline。

XeLaTeX 最终重建为 9 页；逐页复看确认两张表、共同尺度观测椭圆和两面板闭环动态图在
IEEE 单栏尺寸下无裁切、遮挡或不可读标注。`make check` 对 MZM 与 DPMZM 双稿均为
0 FAIL / 4 个既有 WARN；WARN 仍仅为未引用标签和缺失 `build/sim_output.txt`，未重跑会
扰动 RNG 顺序的仿真图。

### 2026-07-19，阶段 A93：全文术语、缩写与首次定义一致性审计

逐节核对摘要、引言、理论、算法、数值与实验部分后，确认投稿前需要处理三类语言问题。
第一类是会改变技术语义的高风险混用：有标签“监督回归”与残差“监督层”共用“监督”；
同一 H1 基线被称为“幅值匹配／H1 匹配／H1 消融／H1 对照”；模型辨识、标定、重定标、
逐状态重辨识的层级未显式区分；“纯椭圆”与“监督式”两条硬件路径也有多套名称。

第二类是符号和专用量首次使用不完整。探测器响应度与圆残差均使用 $\rho$，椭圆矩阵与连续
越限周期数均使用 $M$，反射矩阵与噪声因子均使用 $F$；实验导频幅度 $A_p$ 未与理论的
$V_d,m$ 建立关系，$m_{\rm RF}$、$V_\pi^{\rm RF}$、$A_0$、$g_X/g_Y$、$\delta$ 等亦未完整
定义。噪声预算式中的 $q,\bar I,k_B,T,F,R_T,\mathrm{RIN},B_{\rm eq}$ 需要逐项解释。

第三类是实验口径名称不自足：“五折交错留出”“拟合内／样本外”“跨目标 rms”“尾段中心／
平均命令”“周期--2”“圆标准差”“DMM 括号”“正式原始窗”“调度合同”“环境判据”均需在
首次出现处给出一句定义或改为期刊读者可直接理解的表述。H1/H2、rms、P95、EWMA、RIN、
CORDIC、DMM、DFB 等缩写也存在先用后释或始终未释。该阶段只形成审计清单，未修改正文、
图表、实验数据、固件或 headline。

### 2026-07-19，阶段 A94：术语体系、首次定义与实验评价口径完成统一

按 A93 的投稿前必改项完成全文修订。两条硬件标定路径统一命名为“相位标签回归路径”和
“椭圆--直流规范路径”；传统单坐标基线统一为“H1 幅值匹配基线”；残差状态机统一使用
“监控”，不再与有标签回归共用“监督”。正文显式区分模型辨识、规范固定、标定、漂移后的
重定标以及 RF 功率态的独立重新标定。全文统一使用“全周期”“观测平移向量”“弱观测方向”
和大写 RMS，并把等信息对角二维基线定义为保留同一观测平移与两轴增益、仅去除非对角混合。

消除了符号冲突：探测器响应度由 `$\rho$` 改为 `$\mathcal R$`，圆残差保留 `$\rho_k$`；连续
越限周期数由与椭圆矩阵冲突的 `$M$` 改为 `$N_{\rm p}$`；噪声因子改为 `$F_n$`，反射矩阵仍为
`$F$`；理论导频二次谐波系数改为 `$\varepsilon_h$`，与仿真的交叉耦合 `$\varepsilon$` 分离。
首次使用处补齐 `$P_0,\eta,V_b,V_\pi,\varphi_0,V_d,m,\omega,J_n,R(\alpha),A_p,m_{\rm RF},
V_\pi^{\rm RF}$` 及噪声预算各量；H1/H2、RMS、P95、EWMA、CORDIC、DFB、PD、TIA、ADC、
DAC、DMM、USB 与 PC 均在首次出现处解释。

实验节把五折交错留出的模 5 分组与四折训练/一折测试规则写入正文，并按统计轴区分跨目标
静态 RMS 和逐控制周期时间 RMS。16 点静态评价明确为后 40% 偏压命令均值回写后读取 DMM，
分别报告 DMM 局部线性标尺和全周期宽扫映射；RF 的 192.5 mrad 明确为 RF 开启功率态的最大
跨目标 RMS。静态重复实验改用期刊化表述，直接报告 240 次重复、480 个 16 块采集窗、前后
DMM 读数、0.672 V 输入余量、0.330/29.9 mrad 圆标准差和冻结的重启异常判据，不再把版本号、
内部窗口名、DMM bracket 或调度合同写进正文。

图内文字同步更新：流程图连续越限量改为 `$N_{\rm p}$`；标定图使用固定路径名并缩短标题以
消除截断；硬件性能图统一“二维仿射反演／H1 幅值匹配”和 RMS；平台图删除未解释的内部
`DE4` 标识。表 II 仍按三类证据分组，但行名压缩为“对象 + 统计量”，结果列只保留数值。
抗防御性语言复核将假想质疑式表述改为直接的结构、证据与适用范围陈述，必要模型边界集中
保留在理论和讨论部分。

只读复核确认静态重复 `accepted=true`，H1/H2 最大圆标准差分别为 0.3304049/29.9291 mrad，
最大 H1 重启增量为 0.2872060 mrad；`rf_lock.npz` 复现 RF 开启最大 192.5 mrad、RF 关闭
166.1 mrad。没有重跑真实实验、修改既有实验目录、`data/exp/results.json`、固件或实验
headline。受文字变更影响的图均由既有数据离线重绘并逐图检查；平台段与图注去除重复说明，
并删除仅支撑持续激励常识句、未承担具体结论的通用系统辨识教材条目，避免形成单条参考文献
孤页。XeLaTeX 重建为 9 页，无未定义引用，无大于 20 pt 的 overfull box。双稿 `make check`
为 **0 FAIL / 4 WARN**，WARN
仍仅为既有未引用标签和缺失 `build/sim_output.txt`，按 RNG 约束未重跑整套仿真图。

### 2026-07-19，阶段 A95：摘要主线改为“建模—控制—控制精度”

核对实验驱动、`calib_fit.json` 与 `results.json` 后确认：53.7/61.7 mrad 分别是相位标签
回归和椭圆--直流规范回放的五折交错留出相位反演 RMS，衡量标定在未参与拟合样本上的
泛化误差；1.052 与 0.986 分别是 16 点静态目标映射的响应斜率和决定系数，衡量映射线性度。
两组数均不是本文任意点控制精度的直接统计量。现有硬件证据中，与论文任务最直接对应的
控制精度是 16 个全周期目标点经后 40% 偏压命令均值回写、再由 DMM 局部相位标尺评价的
跨目标静态相位 RMS：二维仿射反演为 246 mrad，H1 幅值匹配基线为 1241 mrad；全周期
宽扫映射给出的 342/2491 mrad 保留为正文中的独立评价。

据此重写摘要，按任意点控制需求、精确仿射模型、全周期参数辨识与规范固定、闭式相位反演
和统一积分控制、数值验证、16 点真实硬件控制精度的顺序展开。摘要不再以前述两条标定路径
和 53.7/61.7 mrad 为主结果，而以 246 mrad 的跨目标静态相位 RMS 及 1241 mrad 基线作为
核心实验数字；1.052 和 0.986 仅保留在实验正文，作为静态映射保真度的补充指标。

同时核清当前实现关系：默认硬件闭环的 `cal_method` 为 `phase-ref`，即相位标签回归；
椭圆--直流规范在该数据集中始终计算为不使用逐点相位标签的离线诊断，只有显式指定
`cal_method='ellipse'` 时才用于控制。正文因此不再把二者表述成两套并列的任意点控制方案：
贡献点改为“任意点控制与硬件验证”，实验小节改为“仿射模型标定与样本外相位反演”，并
明确椭圆--直流规范是对模型辨识和规范固定的独立回放，不构成另一套控制律。结论同步将
246/1241 mrad 提升为主实验结果。没有重跑实验、修改实验目录、`data/exp/results.json`、
固件或实验 headline。XeLaTeX 重建仍为 9 页，首页摘要无溢出或断裂；双稿 `make check`
为 **0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失 `build/sim_output.txt`。

### 2026-07-19，阶段 A96：实验叙述与具体测量仪器解耦

全文扫描确认，A95 后摘要、评价协议、硬件表、图注、结果段和静态重复段仍多次使用
`DM858E` 或 `DMM` 指代标定与评价方法，平台图也重复标出具体控制器、DAC、直流仪表、
RF 源、光电接收机和频谱分析仪型号。这种写法混淆了“本次实验采用的实现设备”和“方法
所需的观测量”：本文算法需要的是可同步采集的直流观测及其生成的相位标签，并不要求某一
类台式万用表；在满足带宽、量程、线性度和同步要求时，ADC、示波器或其他电压采集通道均
可实现同一接口。

据此将具体设备型号集中保留在实验平台首段，作为本次实测配置记录；后续统一使用“独立
直流观测支路”“静态相位标签”“直流局部标尺”“局部相位标尺”和“稀疏相位评价”。摘要
直接报告 16 点静态相位标签评价的 246 mrad 控制精度；实验协议明确由直流观测和局部标尺
生成标签；表 II、标定图注、目标响应段、动态诊断图注和静态重复段均去除仪器名称。平台图
同步改成功能模块表达，不再在图内重复厂商或型号。实验检查器的唯一行键随表 II 改为
“3 h 稀疏相位评价 RMS”；底层数据字段名保持不变，以保存原始采集合同和可复现性。

本阶段只改写设备无关的论文接口和离线图形标签，没有重跑真实实验、修改任何实验目录、
`data/exp/results.json`、固件或实验 headline。实验图由冻结数据离线重绘，平台图和动态诊断
图在最终尺寸下复看无文字截断、遮挡或型号残留；XeLaTeX 重建仍为 9 页。双稿
`make check` 为 **0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失
`build/sim_output.txt`。

### 2026-07-19，阶段 A97：标题改为“核心模型—控制任务”结构

对照本稿已引用的任意点偏压控制论文及 JLT 同类标题后，确认该领域常用的标题结构是直接
给出控制任务，并以核心方法作限定，例如 any-point locking、arbitrary bias point control
based on dither-correlation detection 和 model-based bias controller。A96 前标题“面向 MZM
任意点偏压控制的精确仿射建模与全周期辨识”同时使用“面向”和两个并列过程名词，使最终
控制贡献不够突出；“全周期辨识”是由仿射模型通向任意点控制的关键环节，不是与控制并列的
论文终点。

标题因此改为“基于精确仿射模型的 MZM 任意点偏压控制”。新标题直接表达论文的因果主线：
建立精确仿射模型，并基于该模型完成任意点偏压控制；“精确”明确修饰模型，避免把当前
246 mrad 静态评价和已记录的逐周期动态约束包装成未经数据充分支持的“精确控制”。running
header 与 DPMZM 配套稿中的 `mzmaffine` 文献题名同步更新。没有修改实验数据、headline、
固件或图形。双稿 XeLaTeX 重建成功；MZM 首页标题单行居中，无挤压或异常断行。双稿
`make check` 为 **0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失
`build/sim_output.txt`。

### 2026-07-19，阶段 A98：实验平台图校正板内链路与光学分支

复核图 7 的硬件归属后，确认原图的自研偏压控制板边界只包围 ADC、控制器和 DAC，错误地
把板载 PD、隔直和 TIA 表示成板外器件；1:9 光耦也仅以单一圆点表示，90% 主光路与 10%
监测支路的分叉关系不够直观。图中若干模块的图标与文字整体偏下，缩放到双栏页宽后下边距
尤其局促。

据此重绘平台矢量图：自研板虚线边界现完整包围 PD、隔直、TIA、ADC、偏压控制器和多通道
DAC；1:9 光耦改成“一入、圆环、二出分叉”的 `-O<` 结构，上支路明确标为 90% 光口并接入
光电接收机，下支路明确标为 10% 监测并进入板内 PD。激光器至 MZM、MZM 至光耦以及两条
分光路径均重新走线，避免箭头方向与器件归属含混。所有模块内图标和文字统一上移，增加文字
至下边框的留白；独立直流观测仍保留为板外评价支路。实验平台首段与图注同步明确板载接收链
的范围。

仅离线重绘 `fig_exp_mzm.pdf`，没有重跑真实实验、修改实验目录、`data/exp/results.json`、
固件或实验 headline。单图原始尺寸和论文第 7 页的最终双栏尺寸均已渲染复核，分光关系、板框
归属、箭头和文字均清晰，无截断或遮挡。MZM 稿 XeLaTeX 重建成功；双稿 `make check` 为
**0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失 `build/sim_output.txt`。

### 2026-07-19，阶段 A99：实验平台图按网格和独立走线通道重新排版

A98 修正了器件归属，但最终页宽复核仍发现版式问题：偏置反馈线穿过独立直流观测模块，
USB 标注压住板框，频谱仪通信线未准确落到 PC 边界；光学层、板内接收链与板外仪器没有
形成稳定的对齐网格，局部折线和文字因而显得拥挤。

本阶段按三个水平带重排整图：顶层统一放置激光器、MZM、1:9 光耦、光电接收机和频谱分析；
中层将 RF 信号源、独立直流观测以及板内 PD--隔直--TIA--ADC--偏压控制器全部按同一基线
对齐；下层保留 DAC、偏置反馈和仪器通信总线。RF 激励和偏置反馈分别接入 MZM 下边缘的
独立端口；偏置反馈使用直流观测模块与板框之间的专用垂直通道，不再穿过任何模块。10% 光路
垂直落入 PD，90% 光路经单独折线进入光电接收机；板内模拟接收箭头、ADC 到控制器以及
控制器到 DAC 的数字路径均严格水平或垂直，并终止于模块边界。USB 双向箭头改为连接控制器
右边界与 PC 左边界，文字使用净空底色；频谱仪通信线最终落至 PC 上边界。所有线路均使用
正交折线，唯一斜线只保留在光耦内部的物理分叉符号中。

仅离线重绘 `fig_exp_mzm.pdf`，没有重跑真实实验、修改实验目录、`data/exp/results.json`、
固件或实验 headline。分别以 180 dpi 检查独立矢量图，并以 170 dpi 检查论文第 7 页的最终
双栏缩放；未发现箭头穿框、文字遮挡、悬空连接、非预期交叉或模块错位。MZM 稿 XeLaTeX
重建成功；双稿 `make check` 为 **0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失
`build/sim_output.txt`。

### 2026-07-19，阶段 A100：图 8(b) 改为独立轴尺度

图 8(b) 的 H2 弱轴幅度约为 H1 的四十分之一；A94 将横纵轴强制为共同物理跨度并设置等比例
显示后，真实各向异性虽然直观，但在单栏 2×2 版式中把实测轨迹压成近乎一条窄线，无法辨认
点云、拟合轮廓和中心位置。

本阶段取消图 8(b) 的等比例坐标，横纵轴分别按 H2 与 H1 的实际数据范围设置对称显示区间。
两轴仍保留原始观测刻度：H2 约为 $\pm0.02$，H1 约为 $\pm1$，因此没有改变数据或隐去量级
差，只把几何形状改为适合单栏阅读的视觉比例。子图标题由“共同尺度观测椭圆”改为“H2/H1
观测椭圆”；图注明确说明两轴分别缩放，并将 $\kappa(\hat A)=45.24$ 作为弱观测方向的定量
依据，避免读者从屏幕几何比例误读条件数。

仅由冻结的 `calib.npz` 与 `calib_fit.json` 离线重绘 `fig_expcal_mzm.pdf`，没有重跑实验、修改
实验目录、`data/exp/results.json`、固件或实验 headline。独立图以 220 dpi 检查，论文第 8 页
以 170 dpi 检查；图 8(b) 的点云、拟合椭圆、中心、两轴刻度和标题均清晰。MZM 稿 XeLaTeX
重建成功；双稿 `make check` 为 **0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失
`build/sim_output.txt`。

### 2026-07-19，阶段 A101：图 9(b) 图例改为两行

图 9(b) 在单栏 2×2 版式中同时显示“H1 幅值匹配”和“二维仿射反演”两个较长方法名；原先
使用两列单行图例，整体宽度超过子图坐标框，右侧文字发生溢出。

本阶段将图例改为单列两行，仍居中放在坐标框顶部的预留空白带中，并压缩行间距；原有纵轴
上方余量保持不变，因此图例不与两条误差曲线、数据点、标题或刻度重叠。仅由冻结的
`lock_sweep.npz` 离线重绘 `fig_expperf_mzm.pdf`，没有重跑实验、修改实验目录、
`data/exp/results.json`、固件或实验 headline。独立图以 240 dpi 检查，论文第 8 页以 170 dpi
检查，图例完整位于图框内且两行均清晰。MZM 稿 XeLaTeX 重建成功；双稿 `make check` 为
**0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失 `build/sim_output.txt`。

### 2026-07-19，阶段 A102：补齐 A97 遗漏的主标题与运行页眉

复核新生成 PDF 时发现，A97 虽已更新本审查记录和 DPMZM 配套稿中的 `mzmaffine` 引用题名，
但 `paper_mzm_zh.tex` 的 `\title` 与 `\markboth` 实际仍保留旧标题“面向 MZM 任意点偏压
控制的精确仿射建模与全周期辨识”。因此此前 PDF 首页和运行页眉没有发生变化；这是源码落盘
遗漏，不是 LaTeX 缓存问题。

本阶段将正文主标题改为“基于精确仿射模型的 MZM 任意点偏压控制”，并将左右运行页眉同步
为同一题名。DPMZM 配套稿中的投稿中文献题名已在 A97 更新，无需再次修改。XeLaTeX 两轮
重建后，论文首页主标题单行居中，各页左侧运行页眉显示新标题，无截断、溢出或旧题名残留。
没有修改实验数据、数字、图形、固件或实验 headline。双稿 `make check` 为
**0 FAIL / 4 WARN**，WARN 仍仅为既有未引用标签和缺失 `build/sim_output.txt`。

## 1. 编辑结论

**当前决定：Reject and Resubmit；若目标期刊允许以大修补充关键新实验，可视为高风险 Major Revision。当前版本不建议直接投稿。**

这不是因为仿射理论主线失效。相反，稿件最有价值的部分——未知二维线性观测链下的精确仿射表示、`O(2)` 规范自由度、绝对相位锚定以及满秩可辨识条件——具备形成一区论文的潜力。阻止当前版本投稿的是实验主张与逐周期原始记录之间存在实质性冲突：

1. 16 点“锁定 RMS = 246 mrad”是对末 40% 控制命令取均值后重新写入、再作一次 DMM 评价；逐周期记录显示 6/16 个目标存在明显两周期极限环。
2. 3 h 记录并非健康稳态跟踪，而是全程近乎 100% 相邻符号翻转的两周期振荡；图中平滑后的偏压曲线掩盖了这一动态。

因此，当前证据最多支持“二维仿射解调与平均控制命令能够覆盖全周期目标”的探索性演示，不能支持“16 点稳定闭环锁定”和“3 h 稳定性验证”。该问题不能通过文字弱化、补充免责声明或版式优化解决，必须重新整定并重做关键实验。

### 综合评分（一区投稿标尺）

| 维度 | 分数/100 | 评价 |
|---|---:|---|
| 原创性与潜在影响 | 72 | `O(2)` 规范和未知全矩阵通道可辨识性有明确增量，但需与既有 H1/H2、vector mapping 方法正面区分 |
| 理论与方法严谨性 | 58 | 主定理成立；前提、闭环时延稳定性、标定不确定度传播仍不足 |
| 实验证据 | 32 | 原始时间序列与核心锁定/稳定性表述冲突；单次、单器件、弱基线、非独立真值 |
| 事实与文献定位 | 55 | 文献骨架较完整，但存在方法误分类、基线误引和若干关键 SOTA 缺口 |
| 结构、语言与可读性 | 67 | 中文总体准确，但信息密度过高、重复防御性限定较多，算法与图表冗余 |
| 图表与投稿格式 | 60 | PDF 无严重裁切，平台图较好；多图字体偏小、表格过密、10 页且仍有占位信息 |
| 可复现性与审计性 | 85 | 数据、脚本、数值合同和检查器优秀；也正因此暴露了当前动态问题 |

**加权总体：约 55/100。** 对一区期刊而言，实验主张—原始数据冲突属于门槛性问题，不能用平均分抵消。

## 2. 五位审稿角色的独立判断

| 角色 | 建议 | 置信度 | 核心理由 |
|---|---|---:|---|
| EIC / JLT 编辑初筛 | Reject and Resubmit | 0.95 | 理论有潜力，但核心硬件结论尚不可信；当前也不满足成熟英文投稿稿件的篇幅与元信息要求 |
| R1 系统辨识与闭环控制 | Reject and Resubmit | 1.00 | 246 mrad 与 3 h 稳定性指标掩盖两周期极限环；需重做实验及闭环稳定性分析 |
| R2 MZM / 微波光子学与 Zotero 文献 | Major Revision | 0.93 | novelty 定位可救，但 H1 基线误引、SOTA 比较和材料机理引用未达一区标准 |
| R3 图表、结构与工程表达 | Major Revision | 0.90 | 视觉可读但过密；摘要、算法、表格、图组和实验叙事需要重构 |
| Devil's Advocate | Reject | 0.90 | 实测全矩阵非对角占比仅 0.85%，完整/对角二维留出 RMS 仅 53.7/60.3 mrad；最独特的无标签路径未做闭环，且优效只对弱 H1 消融成立 |

## 3. 两项必须先解决的证据问题

### C1. 246 mrad 不是连续闭环误差，6/16 个目标存在明显两周期极限环

**稿件位置：** 摘要、实验流程、表 II、图 10(b)、实测结果与结论（约第 91、544、561、593、608、627 行）。  
**代码位置：** `scripts/measure_bench.py:909–938, 1023–1060`。  
**数据：** `data/exp/lock_sweep.npz`。

现有实现每个目标运行 26 个控制周期，随后将末 40% 的偏压命令取均值 `V_ss`，把该均值重新写入，再用一次 DMM 测量作为 headline error。这个指标评价的是“平均控制命令对应的静态点”，不是控制器实际运行时的时间序列误差。

对原始 `affine_trace` 的独立审计得到：

- 末段合并解调 RMS：约 **571 mrad**；
- 6/16 个目标末段误差标准差：约 **0.716–1.067 rad**；
- 这些目标的末段 RMS：约 **0.717–1.075 rad**；
- 只有 10/16 个目标的末段 RMS 小于 350 mrad；
- 典型失稳点在两个相反误差状态间交替，均值偏压恰好接近目标，但并非锁定。

**结论：** 当前 246 mrad 只能命名为“末段平均控制命令的 DMM 静态评价 RMS”。不能继续称为“16 点闭环锁定 RMS”，也不能据此声称 16 个点均完成稳定锁定。

**投稿前强制动作：**

1. 降低有效增益、增加合理平均/滤波或修正延迟补偿，先消除两周期极限环。
2. 逐目标用真实连续闭环序列评分，而不是先平均命令再评价。
3. 预注册锁定成功判据，例如末 `K` 周期同时满足 `|mean(error)|`、std、RMS、P95、无饱和和无显著周期-2分量。
4. 展示典型点、弱轴最差点和全周期最差点的原始逐周期误差与偏压命令。
5. 所有完成的 full-grid runs 均进入 manifest；排除条件只能是仪器故障或数据完整性，不能依赖“仿射优于基线”。

### C2. 当前 3 h 数据表现为持续两周期振荡，不是健康的长期稳定锁定

**稿件位置：** 摘要、表 II、图 11(a)、第 610、622、627 行。  
**代码位置：** `scripts/measure_bench.py:1559–1647`、`scripts/make_exp_figs.py:1059–1069`。  
**数据：** `data/exp/stability.npz`。

原始 6078 个逐周期样本显示：

- 解调误差 RMS：约 **827 mrad**；
- lag-1 correlation：约 **−0.995**；
- 相邻周期符号翻转率：**100%**；
- 从起点到终点基本持续在约 `+0.81/-0.81 rad` 间交替；
- DMM 仅每 180 s 采一次，共 60 点，RMS 为 487 mrad；
- 原始偏压命令全范围约 0.99 V，其中主要成分是快交替，不能解释成“0.99 V 慢漂”。

绘图脚本将原始偏压命令做滚动均值，并注释为“两种 dither states”；但存储的 `V` 是每个控制周期更新后的直流偏压命令，不是导频波形的两个状态。这一注释和由此产生的“漂移趋势”表达均不准确。残差阈值又是在前 60 s 已振荡的状态下学习，因此“零次触发”不能证明控制器健康。

**投稿前强制动作：**

1. 控制器稳定后重新进行 3 h 或更长实验。
2. 同时绘制原始逐周期误差、偏压命令、低频趋势与 DMM 稀疏真值；不得只展示平滑趋势。
3. 分离报告 mean tracking bias、短期 jitter、周期-2分量、长期 drift 与重标定事件。
4. 健康判据必须包含“无持续极限环”；阈值学习只能在健康稳态确认后开始。
5. 在新数据完成前，删除或彻底撤回“3 h 稳定性验证”“0.99 V 慢漂”等结论性说法。

## 4. 理论与方法学大修项

### M1. 补齐离散闭环稳定性与时延模型

稿件在理想模型中使用 `e_{k+1}=(1-G)e_k` 的包络，却没有正式给出稳定条件，也未把 20 ms Goertzel 块、16 块采集、串口、执行器、非线性 `atan2`、饱和与 wrap 纳入模型。理想无延迟时局部稳定至少要求 `0<G<2`，单调收敛要求 `0<G≤1`；真实链路还需考虑总时延和局部有效斜率。

建议增加：离散小信号模型、实际时延阶数、特征方程/稳定裕度、抗饱和、wrap 边界和各目标实测 `∂φ_hat/∂V`。新实验的增益选择必须由该分析支撑，而不是只沿用仿真 `G`。

### M2. 收紧“任意线性链/精确”的定理前提

定理本身的代数结构成立，但还依赖：单余弦功率传递；导频相位与偏置相位可加分离；`P0, η, ρ` 对偏置不变；偏置无关串扰；窗口及满扫描期间链路冻结；有记忆链每个窗充分沉降。应把这些条件放进定理陈述，而不是散落在讨论中。

标题可以保留“精确”，但摘要首次出现时应写成“在单余弦功率传递、参数冻结与线性接收—解调假设下精确”。“任意”指导频波形与线性泛函，而不是对真实器件非线性无条件成立。

### M3. 噪声式只是在已知标定参数条件下的一阶方差

式 `var` 忽略 `A,b` 与规范角估计误差、H1/H2 相关/有色噪声、高条件数下 `atan2` 偏差和标定—运行漂移。应明确其为“小噪声、已知标定参数、给定观测协方差”条件下的一阶近似，并增加

`Var(phi_hat) ≈ J_z Σ_z J_z^T + J_theta Σ_theta J_theta^T`，

其中 `theta=(vec(A),b,phi_c)`。至少用独立扫描或独立时间窗估计标定不确定度并验证区间覆盖。

### M4. 仿真比较混合了不同 estimand

当前相位网格图混合：线性化并截断的 H1 静差、oracle 分支的无噪声比值根、无噪声对角二维误差和含噪/漂移的仿射闭环 RMS。它们不能直接作为公平性能曲线。

应在相同标定预算、噪声、漂移、初值、执行器约束、时延和评分窗下运行所有方法，分别报告 deterministic bias、temporal RMS、capture success、settling time 和 failure rate。式 `staticQ/staticAM` 要明确标为局部一阶近似，不能在死区附近当作精确全周期误差。

### M5. 需要多随机实现的稳健性图，而不是单一固定种子实例

在不破坏现有 RNG 合同的前提下，把新 Monte Carlo 追加到脚本末尾，扫描 `kappa(A)`、非对角占比、绝对弱轴尺度、噪声协方差、标定点数、漂移率、时延和 `G`；报告中位数、P95、失败率与置信区间。零噪声闭合仅是同模型自洽检查，不是模型失配稳健性证据。

## 5. 实验设计与统计大修项

### E1. 16 个目标不是 16 次独立重复

当前是单器件、单标定、各目标一次、固定顺序、单阶跃、单次 3 h、RF 功率顺序固定。16 个相位是设计点，不是样本量。五折交错留出仍共享同一次扫描，也不能估计跨扫描/跨会话泛化。

最低要求：多独立会话，每个会话重新标定；目标顺序、控制器顺序和起始侧随机化/平衡；以会话为 cluster 给 bootstrap CI。冲击一区时，跨日重复和至少第二器件会显著增强外部有效性。

### E2. H1 基线既弱，又被错误地包装为文献范式

当前 H1 幅值匹配是作者构造的单坐标消融，不是 Wang 2010、Yuan 2019 或 Peng 2025 的复现。硬件比较应至少加入：

1. 同一扫描、同中心、同 H1/H2 和同控制律的 calibrated diagonal 2-D baseline；
2. 一个真正实现的公开强基线（优先 Wang 2010 H2/H1 比值映射）；
3. 相同运行时间、终止判据、初值与时间序列评分；
4. 方法顺序和目标顺序随机化。

实测全矩阵非对角 Frobenius 占比只有 0.85%，完整与对角二维的留出 RMS 是 53.7/60.3 mrad；因此实物链路尚未证明“非对角校正”带来实质收益。可以把硬件定位为模型可行性验证，但不能用弱 H1 基线宣称完整仿射校正的优效。

### E3. 两种“真值”同源，不是独立验证

监督训练标签、局部线性化真值和宽扫偏压—相位映射都来自同一 DM858E/直流余弦模型。246 与 342 mrad 的差异已经说明 truth-model uncertainty 不可忽略。应使用独立时间、双向、盲化的 validation map，或引入独立相位参考；同时传播 `V_pi, phi_0`、漂移与局部斜率不确定度。不要称两者为“独立真值”。

### E4. 自动提升规则存在 outcome-dependent selection 风险

`measure_bench.py:1064–1069` 只有在 `affine RMS < 0.5 × H1 RMS` 且两个同源评价“concur”时才自动写入 headline。把明显优效作为纳入门槛会产生选择性报告风险。

应保留所有完整运行的不可变 manifest；质量门只依赖预先定义的仪器、饱和、丢包、覆盖度与真值完整性。论文需说明是否存在未进入 `results.json` 的 full-grid runs，以及排除理由。

### E5. 最独特的无标签路径尚未完成硬件闭环

硬件主结果使用 DMM 相位标签监督回归；纯椭圆 + DC 规范只在同批扫描上离线诊断。当前证据支持的是“监督二维仿射闭环”，而不是完整自标定闭环。

一区版本应让纯椭圆 + DC 规范真正生成控制矩阵并闭环运行，监督回归作为 oracle upper bound。若暂时不做，摘要、贡献、结论都必须把无标签路径降为理论/仿真方案。

### E6. 采用已有 enhanced-evidence protocol 的核心门槛

仓库中的 `reviews/mzm_acceptance_experiment_protocol.md` 已设计多块、多会话、随机顺序、等信息基线和尾段抖动门。此前它被定义为“可选增强证据”；基于本次逐周期审计，其中至少以下部分现在应视为必需：

- 原始时间序列而非平均命令评分；
- 无持续两周期极限环；
- 随机化方法/目标顺序；
- 多会话 full-grid runs；
- 所有完成运行的 manifest；
- 等信息二维与强公开基线。

协议中是否必须做到全部六块和独立光学真值，可按资源调整；但稳定控制器和时间序列门槛不可省略。

## 6. 文献、事实与 novelty 审查

### L1. 第 120、478 行存在方法误分类和实质性误引

- Svarny & Chladek 2022 现有实现是 quadrature 偏差控制，不是全周期任意点；DOI [10.1109/JLT.2021.3122460](https://doi.org/10.1109/JLT.2021.3122460)。
- Weller et al. 2025 实现 null/quadrature，不是连续任意点；DOI [10.1109/TMTT.2025.3602740](https://doi.org/10.1109/TMTT.2025.3602740)。
- Peng et al. 2025 是 IQ-OCS-SSB 特定状态的相关检测 + AEKF；DOI [10.1364/OE.572797](https://doi.org/10.1364/OE.572797)。
- Wang & Kowalcyzk 2010 使用 H2/H1 比值、相位符号与预标定映射，不是 H1 幅值匹配；DOI [10.1109/JLT.2010.2048553](https://doi.org/10.1109/JLT.2010.2048553)。
- Yuan 2019 使用平均功率及其变化，不是本文合成 H1 基线；DOI [10.1016/j.ijleo.2018.10.091](https://doi.org/10.1016/j.ijleo.2018.10.091)。

应把相关工作拆成：单 MZM 连续任意点、特殊点/系统指标优化、IQ/DP-IQ 多偏压、学习/相关检测四类。当前 H1 基线统一改称“本文构造的单坐标消融基线”，删除“按传统范式 [文献] 重构”的暗示。

### L2. SOTA 性能差距必须正面报告，但不得做不公平排名

当前硬件结果是 246 mrad（14.1°）、单器件/单次/Hz 量级/监督标签/50 MHz 逐态重标定。相邻工作包括：

| 工作 | 公开口径 | 与本文关系 |
|---|---|---|
| Wang & Kowalcyzk, JLT 2010 | 代表点 any-point、报告优于 ±0.1°、80 h | 最接近的单 MZM H1/H2 任意点强基线 |
| Li et al., JLT 2018 | IQ 任意偏压，约 0.4° | 多偏压相关检测，不同器件/真值 |
| Ning et al., 2016 | 约 1.3 `V_pi` RF 下 ±2.6° | 强 RF 驱动场景，口径不同 |
| Lopez Cabrera et al., 2024 | DP-IQ testbed、28 h、10–128 Gb/s | 系统级与业务负载验证 |
| Weller et al., TMTT 2025 | 20 GHz、RF/温度/长期漂移，null/quadrature | 特殊点鲁棒性标尺 |
| Choi et al., 2025 | 30 h NRZ-OOK 闭环和 BER | 系统性能/长期证据标尺 |

这些数字不可直接横向排名，但审稿人会要求解释为何新结构原型的绝对误差高出一个到两个数量级。论文应明确：主贡献是**未知线性通道的结构建模、可辨识性和闭式反演**，不是当前原型的精度纪录。

新增 SOTA 表至少列：器件类型、任意/特殊点、观测量、是否需要标签/预标定、导频深度、控制带宽/跟踪时间、RF/业务负载、运行时长、误差定义和真值来源。

### L3. 最接近工作的 novelty 对照还不够尖锐

不能把“读取 H1/H2 + atan2”本身当作 novelty。Wang 2010 已同时利用 H1/H2；Li 2018 已使用多维 dither-correlation；Li 2022 已提出 dither vector mapping，DOI [10.1364/OFC.2022.Th1C.7](https://doi.org/10.1364/OFC.2022.Th1C.7)；Li–Zhang–Huang 2013 已用 H1/DC 比值实现任意点并观察 72 h BER，DOI [10.1109/LPT.2013.2285184](https://doi.org/10.1109/LPT.2013.2285184)。

推荐把 novelty 压缩为一句可审查的主张：

> 既有方法通常预设理想对角谐波响应或直接标定/学习工作点映射；本文新增的是对未知全矩阵线性观测链的仿射辨识、`O(2)` 规范分解、绝对相位锚定以及由此得到的可检验全周期可辨识条件。

然后用一张 4–6 行表逐项比较 Wang 2010、Li 2018、Li 2022 vector mapping、DLA2C 与本文。

### L4. 材料漂移机理需要分开写

LiNbO3 的 DC drift、电荷与光折变机理不能无差别套用到 InP。Wang et al. 2018 的 Nature 论文主要证明 TFLN 调制性能，不直接支持 bias drift；Wang et al. 2022 才直接涉及偏置/温度补偿，DOI [10.1364/OE.474594](https://doi.org/10.1364/OE.474594)。

应分别陈述 bulk LiNbO3、TFLN 与 InP；InP 最好引用偏置相关吸收或热漂移的原始器件论文。第 618 行的“秒—分钟/分钟—小时”也应注明材料和机理，而不是跨材料泛化。

### L5. 应补入或讨论的近年相邻工作

- Liu et al., Optics Express 2023，low-LFM dither + FrFT、20-Gbaud 16QAM，DOI [10.1364/OE.503490](https://doi.org/10.1364/OE.503490)。
- D'Ingillo et al., 2023，InP DP-IQ 机器学习数字模型，DOI [10.1109/PSC57974.2023.10297214](https://doi.org/10.1109/PSC57974.2023.10297214)。
- Lopez Cabrera et al., 2024，DP-IQ universal bias-controller testbed，DOI [10.1109/ARGENCON62399.2024.10735854](https://doi.org/10.1109/ARGENCON62399.2024.10735854)。
- Choi et al., 2025，RMSProp feedback optimization，DOI [10.1007/s11082-025-08391-x](https://doi.org/10.1007/s11082-025-08391-x)。

它们不全是任意点方法，但定义了近年审稿人会关注的弱导频、免 H2、业务负载、长期稳定、优化/学习与多偏压扩展维度。

### L6. 参考文献元数据和 DOI 风格需统一

至少修正：

- `li2017`：`pp. 9333–9345`，DOI `10.1364/OE.25.009333`；
- `peng2025`：`pp. 43221–43233`，DOI `10.1364/OE.572797`；
- 补齐 `wang2010, yuan2019, li2018, teng2023, weller2025, svarny2022, salvestrini2011, wang2022, heydemann1981, fitzgibbon1999` 的 DOI；
- `Wang 2010` 作者 `Kowalcyzk` 虽看似异常，但与出版物署名一致，不应擅自改拼写。

## 7. 结构、语言、图表与格式

### S1. 摘要过密，且把未成立的实验结论放在核心位置

当前摘要是一整段高密度“理论 + 方法 + 仿真 + 十余个实验数字 + 边界条件”。建议改成 180–230 个英文词对应的信息量，只保留：问题、理论增量、辨识条件、方法、经过重做后可信的 2–3 个核心结果、适用边界。新实验完成前不要在摘要中保留 246 mrad 和 3 h 稳定性结论。

JLT 官方作者要求摘要简洁、自包含、单段，并建议 3–4 个关键词；当前关键词有 6 个。参见 [JLT Author Information](https://ieeephotonics.org/publications/ieee-optica-journal-of-lightwave-technology/)。

### S2. 引言要从“方法罗列”改成“最近邻差距—本文唯一增量”

推荐四段结构：

1. 实际偏压漂移问题与连续任意点需求；
2. 特殊点、比值/映射、相关检测/学习的现状；
3. 最近邻方法共同未显式处理的“未知全矩阵线性观测链 + 规范自由度”；
4. 本文贡献和实验范围。

当前贡献 2“传统方案统一解释”可缩为支撑性结果，不应与精确仿射定理和规范可辨识性同等突出。最强贡献应集中在“未知通道的仿射可辨识性”。

### S3. 符号表、三套算法和多张说明图造成篇幅拥挤

- 首页符号表占用较大，JLT 研究论文中不常见；可删去并在首次出现处定义，或移到补充材料。
- Algorithm 1 与后续标定/运行算法内容重叠，应合并为一套主算法；把实现细节放伪代码附录。
- 架构图与后续完整实验平台图功能部分重复；前者可压缩为理论框图小插图，或由平台图承担硬件叙事。
- gauge、acquisition、recalibration 等验证图可合并成 1–2 张主图，其余放补充材料。

### S4. 表格需要按“可比较性”重构，而不是继续堆注释

现有方案表和实验表字体很小，表 I 在日志中产生约 12.45 pt overfull box。实验表将仿真与实验放在同一列组，但导频深度、带宽和标定方法不同，只能靠长注释解释不可比较性。

建议：

- 方案表只保留观测维数、先验/标定、全周期单射性、死区、核心假设；静差公式放正文。
- 实验表改为“指标—估计量—统计单位—结果—限制”，删除不可直接比较的仿真列。
- 新增独立 SOTA 表，统一比较口径。
- 表中不使用 `scriptsize` 作为常态；必要时跨双栏。

### S5. 图中文字普遍小于正文/图注，达不到 JLT 可读性要求

渲染 PDF 无严重裁切或空白字形，完整平台图是当前视觉上最强的一张。但多子图使用约 6.2–7.2 pt 字体，接近或小于图注，打印和双栏缩放后阅读吃力。JLT 官方明确要求图中文字不能小于默认图注字号，并应在最终栏宽下可读，参见 [JLT Author Information](https://ieeephotonics.org/publications/ieee-optica-journal-of-lightwave-technology/)。

所有图应按最终单栏/双栏宽度检查：轴标题、刻度、图例、子图标签至少与图注一致；减少同图曲线数量；用颜色 + 线型双编码；避免依赖浅色；关键动态必须展示原始数据而不是只展示平滑趋势。

### S6. 语言准确但过度防御，核心论点被边界说明淹没

稿件的边界意识值得保留，但同一限定在摘要、表下注、实验结果、讨论和结论多次重复。建议每项限制只在最有信息价值的位置完整说一次：方法前提放定理，统计限制放实验设计，外推限制放讨论。这样可以删除大量“仅指”“不构成”“不可直接”“需另行”等重复句式，同时保持诚实。

需要改正的术语：

- “相干串扰”首次写成“导频同步（相干）电串扰”，避免被理解为 optical coherent crosstalk；
- “漂移恢复”不能用于 110 mrad → 396 mrad 的结果，可称“检测并重标定后的残余误差”；
- 在极限环未解决前不用“稳定性”“稳定锁定”；
- 50 MHz 每状态重标定只证明“静态状态可重新辨识”，不是固定标定下的 RF robustness。

### S7. 页数、作者信息与投稿元数据尚未就绪

当前 PDF 10 页。JLT 官方页面说明 contributed paper 超过 8 页会产生强制超页费；这不是学术拒稿条件，但说明主文仍需压缩。JLT 还要求不超过 100 词的 impact statement。参见 [JLT Author Information](https://ieeephotonics.org/publications/ieee-optica-journal-of-lightwave-technology/)。

作者、日期、基金、单位、邮箱和 running header 仍是占位符；中文稿也不是最终 JLT 投稿文件。英文转换不能逐句直译，应在证据和结构稳定后重写为自然学术英语。

## 8. 建议的新主线

最稳健的一区定位不是“精度优于现有控制器”，而是：

> 本文研究未知线性接收—解调链如何破坏理想 H1/H2 任意点偏压读出。证明二维观测在明确物理前提下是单位圆的精确仿射像，指出无序椭圆只确定 `AA^T` 而绝对相位还需固定 `O(2)` 规范，并给出可检验的全周期可辨识条件与闭式反演。硬件实验用于验证该结构及其闭环可实现性，不宣称当前原型达到绝对精度纪录。

围绕这条主线，论文可按以下顺序重构：

1. 最近邻工作与未解决的未知全矩阵通道问题；
2. 物理前提、精确仿射定理和可辨识性；
3. 规范固定与两条标定路径；
4. 噪声/闭环稳定性/重标定条件；
5. 公平仿真消融；
6. 稳定、随机化、多会话硬件实验；
7. SOTA 口径对照与适用边界。

## 9. 分阶段修订路线图与验收门

### 阶段 A：先修证据，不改写主文结论

- 解释并消除 lock sweep 与 3 h 数据中的两周期极限环；
- 修正时间序列评分、稳定性门和数据 manifest；
- 取消 outcome-dependent auto-promotion；
- 确定新实验协议与强基线。

**通过门：** 所有目标的预注册尾段稳定性指标通过；原始图与汇总指标一致；无隐匿 full-grid runs。

### 阶段 B：补充一区级实验

- 多会话随机化 16 点 full-grid；
- 完整仿射、等信息对角二维、一个公开强基线；
- 无标签椭圆 + DC 规范真实闭环；
- 健康的 3 h+ 长运行；
- 若保留 RF 主张，至少固定标定切换或明确只做逐态可辨识性。

**通过门：** 以会话为单位报告 CI/失败率；动态稳定而非平均命令正确；真值独立性和不确定度说明完整。

### 阶段 C：重做理论边界与公平仿真

- 补定理前提、闭环时延稳定性和标定不确定度传播；
- 所有算法使用同一 estimand 和资源预算；
- 新 Monte Carlo 追加到脚本末尾，遵守仓库 RNG 顺序规则。

**通过门：** 仿真图每条曲线都能回答明确问题，且不把局部近似与真实闭环 RMS 混合。

### 阶段 D：文献、结构、语言和图表重写

- 修正方法分类、误引、页码和 DOI；
- 新增 nearest-work novelty 表与 SOTA 表；
- 压缩至 8–9 页主文目标，合并算法和次要图；
- 提升所有图字号；
- 最后进行英文母语级重写，而非逐句翻译。

**通过门：** 摘要与结论只含新数据支持的主张；标题/贡献/实验范围一致；图表在最终栏宽打印可读。

### 阶段 E：仓库级验证

- `make figs` 后核对 `build/sim_output.txt`；
- 更新 `paper_metrics.json` 与稿件数字合同；
- `make exp-figs`；
- `make pdf`；
- `make check` 对两稿均为 `0 FAIL`；
- 110 dpi 渲染逐页视觉检查。

## 10. 本次核验记录与局限

已完成：

- `make check MAIN=paper_mzm_zh.tex`：**0 FAIL，2 WARN**；WARN 为未引用 equation labels，以及 `build/sim_output.txt` 缺失导致本轮未复核仿真 stdout 数值侧。
- `make pdf MAIN=paper_mzm_zh.tex`：成功，10 页，无 undefined references；有一处约 12.45 pt overfull box。
- 110 dpi 渲染并逐页检查：CJK、公式、表格和图均能显示，无严重裁切/重叠。
- 直接审计 `lock_sweep.npz`、`stability.npz`、`measure_bench.py` 与 `make_exp_figs.py`。
- 运行现有只读再分析脚本，核对 246/342/1241/2491 mrad、53.7/60.3 mrad、斜率和 `R^2` 等数值。
- Zotero 语义库 3812 条目，更新时间 2026-07-14；抽查 Wang 2010、Li 2018、Weller 2025、Choi 2025、DLA2C 等原文/元数据。
- 对照 [JLT 官方 scope 与作者要求](https://ieeephotonics.org/publications/ieee-optica-journal-of-lightwave-technology/)、[JLT scope/topic categories](https://ieeephotonics.org/wp-content/uploads/2025/12/jltscopeandtopiccategories2024.pdf) 与 [Optics Express research article criteria](https://opg.optica.org/resources/author/Optics_Express_Research_Article_criteria_Oct2025.pdf)。

本轮没有执行 `make figs`，因为工作树已有用户的实验图与脚本改动，且缺少 `build/sim_output.txt`；为避免扰动已提交的 RNG 产物，本轮只做只读审计。机械 `0 FAIL` 说明引用、数字合同的实验侧和文件完整性通过，但它不能检测闭环极限环或结论口径问题。

## 11. 给作者的四个必须回答的问题

1. 除当前 `lock_sweep.npz` 外，是否存在任何完成但未进入 `results.json` 的 16 点 full-grid runs？每次运行为何被保留或排除？
2. 如何解释 6 个目标以及整段 3 h 数据中的逐周期正负交替？为何将末段偏压均值后的单次 DMM 读数定义为锁定误差？
3. 在 `kappa≈45`、Hz 量级端到端环路和 `G=0.3` 下，增益/时延稳定裕度依据是什么？是否测过各相位的有效斜率？
4. 能否提供独立于监督标签的验证相位，并以随机化、多会话实验完成纯椭圆 + DC 规范闭环？

## 12. 最终判断

**论文值得继续做，而且理论骨架不需要推倒重来；但当前稿件距离一区投稿的主要差距不在语言，而在实验证据的定义和闭环动态。** 最优顺序是：先稳定控制器并重做关键实验，再重构 SOTA 定位和理论边界，最后压缩图表、改写摘要和英文全文。若只做文字、参考文献和版式修饰，最可能的审稿结果仍是因“实验结论与原始时间序列不一致、基线不公平、novelty 定位不充分”而拒稿。
