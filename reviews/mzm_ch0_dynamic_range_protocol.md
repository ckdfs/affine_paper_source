# MZM CH0 全周期动态范围候选协议

版本：2026-07-17 v1.3（新增受审计的 pilot 启动丢弃窗；A42 后、任何新 ABA 前冻结）

本协议只选择一个不会使 ADS131M02 CH0 在全周期内削顶的 pilot 候选。它不拟合
`V0(t)`、不运行闭环、不更新 `data/exp/results.json` 或论文 headline，也不追认 A35。
A35 的 0.15 V pilot 已在三个 leg 各有 52/81 点到达 1.199 V guard 或 exact rail，
不得再把 0 V 单点 smoke 当作全周期量程证据。

## 1. 固定硬件与候选

- 固件必须为 A32 已刷写且通过 smoke 的 RAWADC 版本；每个 `acq run` 必须返回
  `RAWADC v=1` 和 `RAWADC_CH ch=0`。
- ADS131M02 固定 gain=1、64 kS/s；不得用数字缩放、GCAL 或放宽 rail 阈值冒充
  模拟动态范围扩大。
- 候选 pilot amplitude 固定为 `0.06, 0.08, 0.10 V`，频率固定 1 kHz；A35 的
  0.15 V 只作既有失败参照，不重跑。
- 固定 `Vpi=5.222139048043948 V`、坐标中心
  `Vcenter=0.8147635714861232 V`，81 点从 `Vcenter-Vpi` 单调小步进至
  `Vcenter+Vpi`，步进约 0.130553 V。

## 2. 冻结 schedule 与采集合同

先从 0 V 用不大于正式步长的小步进 conditioning 到下边界，conditioning 使用最大
候选 0.10 V、`acq run 6 blocks`，全部保存并参与 0.10 V raw 安全门。

正式 81 个偏压点中，每个偏压保持不变，依次采集三个 pilot 候选；候选顺序按
`grid_index mod 3` 循环轮换：

```text
0: [0.06, 0.08, 0.10]
1: [0.08, 0.10, 0.06]
2: [0.10, 0.06, 0.08]
```

这样 pilot 与时间位置不完全共线，且偏压始终单调小步进。每个候选只采一窗
`6 blocks = 7680 samples`；目的为 raw extrema 和 H1/H2 幅度，不用它替代 v1.3
time-calibration 协议的 `4 x 16 blocks` 标定精度。每行流式保存真实开始/结束/中点
时间、bias、pilot、
H1/H2 I/Q、board CH1 monitor，以及完整 CH0 raw telemetry。SIGINT、通信或分析失败
保留 partial 目录，结束路径始终执行 `gen reset`、`dac 0` 并保存最终状态。

固件 `gen pilot` 的语义是**追加** tone，不是按频率替换。故每次候选采集前必须依次
执行 `gen reset -> gen bias -> gen pilot`，再运行已预先配置频率的 `acq run`；不得
只重复发送 `gen pilot`。每个 pilot 首次使用时必须以 `gen show` 确认恰好 1 个
pilot、频率 1 kHz、幅度与候选一致，并把原始回显写入受 checksum 保护的文件。

`gen bias` 只修改 generator 配置；pilot channel 的物理 DAC 在下一次 `acq run` 开始
后才更新。为排除首窗 bias 阶跃瞬态，每个新 conditioning bias 和每个正式 grid 组
开始前必须先 `gen reset`，再用 legacy `dac <bias>` 物理预置 CH-A，固定等待
0.500 s；随后同一 bias 的三个候选都不得再改变物理静态偏压。每行保存本组实际
`t_bias_set_unix`、`bias_prepositioned` 和冻结 settle；conditioning 全部、每个正式
grid 的 `candidate_order_index=0` 必须且只能标记为 prepositioned。该文件合同也是
accepted 的必需门。

A42 表明物理预置已排除 bias 阶跃，但 `dac` 静态输出切换到 generator pilot 后的
第一次 acquisition 仍可包含启动瞬态：正式 12 个触轨点全部在每组 order 0，而
order 1/2 各 81 点均无 rail/guard。故每次物理预置后必须先按该组首候选执行完整
`gen reset -> gen bias -> gen pilot`，再运行一窗同样的 `acq run 6 blocks` 作为
startup discard；该窗的时间、H1/H2、board monitor 和完整 RAWADC telemetry 全部写入
独立 `startup_discard.csv/.npz` 并受 checksum 保护。warm-up 后不得再次 reset、改 bias
或改 pilot，必须在 warm-up 结束后 0.250 s 内以原配置启动正式首窗。同组后两个候选
维持原循环顺序，不另加
warm-up。34 个 conditioning 点和 81 个 formal bias 组应恰好产生 115 个 discard，
不得删除触轨 discard 或将其混入正式评分。

## 3. 预注册通过门与选择规则

每个候选分别在其 81 个正式点检查：

- telemetry 合同一致，`version=1`、`scope=acq`、`expected=used=7680`、
  `blocks=6`、`windows=1`、gain/fs/guard 与固件常数一致、`complete=1`、
  `read_fail=0`、`timeout=0`；
- exact rail 与 1.199 V guard 四个计数全部为 0；
- raw min/max 严格在 `+-8381618` guard 内；
- 为保留约 0.249 V 的瞬时余量，全部点的
  `max(abs(raw_min),abs(raw_max))*1.2/8388608 <= 0.95 V`；
- H1/H2 I/Q 与 board CH1 monitor 全部有限，81 点无缺失、重复或乱序。

top-level accepted 还要求 startup-discard 合同通过：115 条记录与预置组一一对应，
bias、pilot、grid/sequence 完全匹配；每条同样满足完整 telemetry 合同、物理码界、
`raw_min <= raw_max`、非负计数和有限 H1/H2/DC；且满足
`t_bias_set + 0.500 s <= t_warmup_start < t_warmup_end <= t_formal_start`。discard 中
允许 rail/guard，因为其用途正是隔离启动瞬态，但必须原样计数和保存。正式首窗必须
记录 `startup_discard_index` 及“未重配置即跟随”标志；非首窗该索引固定为 -1。
两份 discard 文件的实际 SHA-256 必须同时写入 `analysis.json` 和最终
`checksums.json`，replay 做三方一致性检查；哈希或受保护文件集合不完整时不得通过。

0.10 V 还必须让全部 conditioning 点通过相同 raw 合同和 0.95 V headroom 门。
对每个候选分别用 81 点无标签椭圆报告所选 I/Q 分量、`kappa(A)`、H1/H2 magnitude
范围和相对于冻结 coordinate map 的非门控 concurrence；这些量用于判断 pilot-only
降低是否让弱轴不可用，但不得事后修改 raw 门。

候选选择固定为：在全部 raw 必需门通过的候选中选 pilot amplitude 最大者，以尽量
保留 H2；若没有候选通过，则本协议失败。A35 未削顶点的只读回归给出
`raw_peak_V = 1.857 |H1| + 0.009 V`、`R^2=0.9878`，结合 H1 正弦外推得到最坏 raw
峰值约 2.24--2.33 V；因此达到 0.95 V 目标需要约 -7.8 dB 的统一电压衰减。若只有
0.06 V 左右的 pilot 能通过 raw 门，则还必须明确报告 H2 的二次下降和 `kappa(A)`
恶化，不能仅因“无削顶”就直接进入 ABA。下一步优先采用约 -8 dB 的统一光功率/TIA
衰减后另行冻结验证，不能继续降低阈值。

即使选出候选，本协议也只授权用该设置设计下一次 time/direction 诊断；它不授权
gauge audit、v1.4 preflight 或 acceptance。任何后续 ABA 必须在新协议中显式记录
pilot 改变及其仿真/replay，不能混用 A35 的 0.15 V 标定。

## 4. 实现前验证

真实运行前必须通过硬件无关测试：健康候选可选出最高档；单个正式点 exact rail、
guard-only、0.95 V headroom 超限、缺失 RAWADC、sample mismatch 和 conditioning
失败分别被拒绝；candidate order 与 bias schedule 哈希固定；失败注入仍保留目录并
执行安全清理。另以 fake board 永久回归测试连续候选之间必有 `gen reset` 且每段只有
一个 `gen pilot`，并验证每个新 bias 组在首个 acquisition 前出现 `dac + settle`、
随后同配置连续调用 warm-up 与 formal acquisition、二者之间无任何重配置；同组后两
候选不重复 bias 阶跃。健康仿真以及 startup-discard 缺失、重复、sample mismatch 和
“warm-up 后重配置”合同破坏必须分别证明 top-level 拒绝；replay 必须同时重建正式与
discard 两套 NPZ/CSV 决策。仿真输出只写 `build/exp_sim/ch0_dynamic_range/`。
