# MZM 静态重复诊断协议（restart 分离）

版本：2026-07-17 v1.2（A58 后冻结；v1.0→v1.1 加入 §2 acq 验证重试，由 A60
记录的真实 v1.0 运行首次 acq restart 验证瞬态失败触发；v1.1→v1.2 加入 §2
无效读取的全记录有界重试，由 A61 记录的真实 v1.1 运行 formal `acq run`
返回不完整 tones 触发）

本协议是 A57 全局 bundle 拒绝后的最小化静态分解诊断：在固定偏压点上，不移动
DAC，比较"不重启 / 每轮重启 gen / 每轮重启 acq / 每轮同步重启 gen+acq"四种状态下
弱 H2 幅相波动、H1 参考稳定性、DMM bracket 短时变化与时间漂移。它不运行闭环、
不做标定拟合、不更新 `data/exp/results.json` 或论文 headline，也不授权 gauge
audit、控制器 v1.4 preflight、acceptance 或任何固件修改；固件修改只能在本诊断的
预注册解释规则给出明确 restart 归因后另行决定。

## 1. 固定硬件、pilot 与安全边界

- 固件保持当前 A32 RAWADC 版本不变；运行前记录 `biascontrol_h523` 实际
  source/ELF hash 到 protocol metadata。
- pilot 固定 0.08 V、1 kHz；acquisition 频率固定 {1000, 2000} Hz。
- 固定 `Vpi=5.222139048043948 V`、`Vcenter=0.8147635714861232 V`、81 点等间隔
  网格 `Vcenter±Vpi`（与 v1.2 interleaved 协议同一网格），步长约 0.130553 V。
- 最大绝对偏压（含 approach）必须小于 `0.995*9 V`。
- 每次真实运行新建 `data/exp/diagnostics/static_repeats/<run-id>/`；失败、partial
  目录永久保留，不得覆盖、删除或续写。仿真只写
  `build/exp_sim/static_repeats/<run-id>/`，不得写 `data/exp/`。
- 所有结束路径执行 `gen reset`、`dac 0`，程序内验证并在运行后用独立新连接确认
  `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

## 2. 冻结 schedule

- 固定 5 个网格点，按冻结非单调顺序执行：`grid_index = (40, 0, 60, 20, 80)`
  （覆盖条纹两个极值、中心与两个中间点）。
- 每个点依次执行 4 个连续 condition block；condition 顺序按点序号 p 旋转冻结
  基序 `("none", "gen", "acq", "both")`：点 p 使用
  `base[p mod 4:] + base[:p mod 4]`。该 Latin 旋转使 condition 与实验时间在点间
  去相关。
- 每个 block 固定 `R=12` 个 repeat。合计 `5×4×12=240` repeats、480 个正式窗、
  240 个 discard 窗。
- 换点时用 legacy `dac` bridge 从当前偏压小步进（每步不超过一个网格步长，
  每步 settle 0.500 s，逐步流式写 conditioning CSV 并读一次 DMM）到
  `target - step`（统一 up 方向 approach），settle 0.500 s，再 `dac target`，
  settle 0.500 s。同一点内换 block 不移动偏压。
- 每个 block 开始时无论 condition 都做一次完整基线配置（保证四种 condition 的
  初态一致）：`acq reset`、`acq add 1000`、`acq add 2000`、等待 0.4 s、`acq show`
  验证恰好 2 个频率且为 1000/2000 Hz；随后 `gen reset` → `gen bias(target)` →
  `gen pilot(1 kHz, 0.08 V)`。
- 每个 repeat 依次执行：
  1. 按 condition 重启：`none` 不动作；`gen` 执行 `gen reset → gen bias(target)
     → gen pilot`；`acq` 执行 `acq reset → acq add 1000 → acq add 2000 → 0.4 s
     → acq show 验证`；`both` 先 acq 序列再 gen 序列。重启动作与时间戳逐条保存。
     acq 序列的 `acq show` 验证允许最多 3 次完整重试（每次都重做
     reset→add→add→show，全部响应与时间戳逐次保存，不允许静默重试）；3 次全部
     失败才中止。block 基线配置的 acq 验证同样适用。每个 repeat/block 的实际
     尝试次数进入数据文件，重试总数作为 acq restart 链路可靠性统计在 analysis
     中上报——USB 链路偶发掉频率列表本身即为本诊断的证据之一。
  2. `gen show` 验证：pilot 数恰为 1、频率 1 kHz、幅度 0.08 V、acquisition
     频率数恰为 2 且为 1000/2000 Hz。任一失败当场中止，已写数据保留。
  3. discard：`acq run 6 blocks`（同时把 gen bias 落到 DAC——已知 `gen bias`
     只在下一次 `acq run` 生效），完整保存 I/Q、board DC、RAWADC。
  4. DMM pre：连续 2 次 DM858E 读数，各自保存 start/end 时间戳。
  5. 正式窗：2 × `acq run 16 blocks`，逐窗保存真实 start/end/mid、I/Q、
     board DC、完整 RAWADC；不得 silent retry，任一窗无效即失败。
  6. DMM post：连续 2 次读数，同样保存时间戳。
- 无效读取重试：若某次 `acq run`（discard 或正式窗）返回完全无效的结果
  （tones 缺失、DC 缺失或 RAWADC 缺失，即不含任何可用测量），允许最多 3 次
  尝试（含首次）；每次失败尝试的时间戳与序号逐条写入
  `acq_read_failures.json`，逐 repeat 的 discard/formal 重试计数写入主 CSV，
  总数作为链路可靠性统计进入 analysis。有效但难看的窗不允许重试——只有
  "无数据"才能重试，因此不产生选择偏倚。3 次全部无效即中止。
- discard 结束到第一个正式窗"首次尝试"开始不超过 2.000 s（首次尝试时间戳
  `t_acq_first_attempt_start` 单独入档，失败尝试计入该时刻）。repeat 内
  时间序必须满足
  `pre1 < pre2 ≤ acq_start < acq_end ≤ post1 < post2`（按各读数中点时间）。
  全部 240 repeat 与 480 窗 sequence 严格递增。

## 3. 硬采集门（全部通过才 accepted）

- exact schedule：点顺序、condition 旋转、repeat 计数、restart 动作与冻结合同
  完全一致；conditioning bridge 与期望路径逐行一致且单步不超一个网格步长。
- 每个 repeat 的 `gen show` 验证记录齐全且全部通过。
- 240 discard 各为精确 6 blocks、7680 samples、1 window，telemetry 合同通过
  （允许 rail/guard 但必须如实保存 extrema/counts）。
- 480 正式窗各为精确 16 blocks，零 read-fail/timeout/rail/guard，最大绝对 raw
  不超过 0.95 V（code 6,640,981）；repeat 级合并 RAWADC 与逐窗合并一致。
- DMM 四读数全部有限，时间序满足第 2 节约束；settle 时长合同满足。
- 文件合同：repeats/formal_windows/transition_discard 的 CSV+NPZ、
  conditioning CSV、pilot_verification、block_config、acq_read_failures、
  protocol、analysis、summary、manifest、checksums 齐备且 SHA-256 一致；
  失败尝试记录与主 CSV 的逐 repeat 重试计数必须逐条对账；独立 validator
  全字段 replay 复现 analysis。
- 程序内与独立新连接均确认最终 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

accepted 只指采集合同；本诊断不设科学 pass/fail 门，比较结论由下述预注册
统计与解释规则给出，不得事后更改。

## 4. 预注册统计量

对每个 (point, condition) block：

- 每 repeat 用 2 个正式窗等权平均得 `H1=(I1,Q1)`、`H2=(I2,Q2)`；报告 block 内
  12 个 repeat 的：H1/H2 相位圆标准差、H1/H2 幅值相对标准差、
  `wrap(phase(H2) − 2·phase(H1))` 的圆标准差、以及对 repeat 序号的线性时间趋势。
- 窗内对照：每 repeat 两窗差 `|Δphase|`、`|Δmag|/mag`，作为无重启的
  短时基线。
- DMM：每 repeat `|mean(post) − mean(pre)|` 归一化后（见下）在 block 内的
  median/P95/max；读数对内差 `|pre2−pre1|`、`|post2−post1|` 作为仪表噪声界。
- 归一化幅度 `b_hat = (max_p median(DC_p) − min_p median(DC_p))/2`，其中
  `DC_p` 为点 p 全部 DMM 读数（点 0/40/80 覆盖条纹极值），冻结不得改。

## 5. 预注册解释规则

- 记 `s ∈ {gen, acq}`。若在至少 3/5 个点上，仅重启 s 的单独 condition（即
  `gen` 或 `acq` 本身，不含 `both`）的 H2 相位圆标准差（或 `wrap(ΔH2−2ΔH1)`
  圆标准差）同时满足 ≥2× 同点 `none` 值且超出 `none` 值至少 0.02 rad，则 s 的
  重启被实证牵连，可授权后续固件调查。`both` condition 的超限只作旁证单独
  报告，不独立定罪（它无法区分两个子系统）。
- 若 `none` condition 自身的 H2 相位圆标准差在多数点已达 0.05 rad 量级，或
  DMM 归一化 bracket 变化在 `none` 下即复现 bundle 量级
  （max > sin(0.05)=0.04998），则失败归因于环境/弱 H2/DMM 自身而非重启，
  不授权固件修改。
- H1 相位圆标准差在所有 condition 均应远小于 H2（A58 离线结论的在线复核）；
  若 H1 在重启 condition 下显著增大（同规则 ≥2× 且 ≥0.02 rad），则参考相位
  假设需重新审视。
- 上述规则只产生"牵连/不牵连"结论与后续调查方向，不产生论文数字。

## 6. 实现前验证

真实运行前必须全部通过并保留输出：

- 健康仿真 accepted=true 且独立 validator 全字段 replay 通过；
- 故障注入逐项拒绝：formal rail、formal headroom、formal 样本缺失、discard
  缺失、DMM 时间序破坏、`gen show` 验证失败、schedule/condition 顺序破坏、
  restart 动作缺失；
- 分析注入自检：向 gen-restart condition 注入额外 H2 相位噪声时解释规则输出
  "gen 牵连"；向全部 condition 注入等量噪声时输出"不牵连"；
- validator 拒绝 checksum 篡改与旧协议 NPZ 冒充。

仿真与故障注入只写 `build/exp_sim/static_repeats/`。
