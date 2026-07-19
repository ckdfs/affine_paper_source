# MZM 局部双向交错标定诊断协议

版本：2026-07-17 v1.2（A51 后冻结；与控制器 v1.4 preflight 无关）

本协议只诊断“全程 up/down 扫描历史”能否通过逐点局部、时间相邻且方向平衡的
标定消除。它不运行闭环，不选择控制增益，不更新 `data/exp/results.json` 或论文
headline，也不授权 gauge audit、控制器 v1.4 preflight 或 acceptance。

## 1. 固定硬件、pilot 与安全边界

- 固件固定为 A32 RAWADC 版本；pilot 固定为 A44 通过全周期量程门的 0.08 V、1 kHz；
  A51 证明 0.10 V 在长序列正式窗仍有稀有 CH0 rail，故不得继续使用。
- 固定 `Vpi=5.222139048043948 V`、`Vcenter=0.8147635714861232 V`、81 点等间隔
  网格 `Vcenter+-Vpi`，网格步长约 0.130553 V。
- 为标准化端点接近方向，只允许使用网格外一个步长的 approach 点；最大绝对偏压
  约 6.1675 V，仍必须小于 `0.995*9 V`。
- 每个真实 segment 新建
  `data/exp/diagnostics/interleaved_calibration/<run-id>/`。失败、partial 和 discard
  都是审计证据，不得覆盖、删除或续跑拼接。
- 所有结束路径执行 `gen reset`、`dac 0`，并要求最终
  `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

## 2. 冻结局部 paired schedule

先 `gen reset`，从 0 V 通过不超过一个网格步长的 legacy `dac` 小步进到
`grid[0]-step`；每个 conditioning step 保存真实时间、目标偏压、DMM 读数和命令
回显，但不进入拟合或动态范围评分。

target 顺序不得单调或现场随机生成。固定 seed=20260717：首两点为 `[0,80]`；对
`1..39` 做一次冻结 permutation，按其 ordinal 交替追加 `[i,80-i]` 和
`[80-i,i]`；最后追加 40。完整 81-target 列表与 SHA-256 写入 protocol。跨 target
移动必须用 legacy `dac` bridge 拆成不超过一个网格步长的小步，每步等待 0.500 s
并流式写入 conditioning CSV；不得直接大阶跃到下一 approach。

为隔离 A46 的长时 USB 重枚举风险，真实采集固定分为 3 个 segment，每段恰含连续的
27 个完整 target pair（54 observations）：全局 observation 范围依次为 `[0,54)`、
`[54,108)`、`[108,162)`。不得在 pair 内切段。每段都从安全 0 V 独立小步进到该段
首个 approach，使用新 run-id，独立生成 protocol/source hash、CSV/NPZ、summary、
manifest 和 checksums，并独立安全收尾；segment 只评分采集/文件合同，不独立拟合或
宣称通过科学门。若任一段失败，失败目录保留，只能以新的 run-id 重做该段。

三个完成段只能由只读聚合器按 segment index 0/1/2 各取一个目录。聚合器必须拒绝
缺段、重复段、乱序、全局 sequence 不连续、跨段 pair 破坏、schedule/source/protocol
hash 不同或任一段非安全完成；随后按原始绝对时间合并，重新验证全局 target/time 与
direction/time 正交性及本协议全部科学门。不得用人为压缩的 segment-local 时间替代
真实 wall-clock 时间，也不得把 A46 的 partial 96 点拼入聚合。

每个 target 连续取得两个相反方向观测；target ordinal 为偶数时顺序 UD，奇数时
顺序 DU，使 72 个 formal target 中 up-first/down-first 精确为 36/36：

```text
up:   approach = V_i - step  -> target = V_i
down: approach = V_i + step  -> target = V_i
```

每个观测都独立执行：

```text
gen reset
dac approach; wait 0.500 s
dac target;   wait 0.500 s
gen reset -> gen bias(target) -> gen pilot(1 kHz, 0.08 V)
acq run 6 blocks                    # startup discard，先流式保存
DMM pre
4 x acq run 16 blocks               # 四窗逐窗保存，再等权平均
DMM post
```

每个 observation 均须在配置后立即执行一次 `gen show`，并保存独立验证记录；返回值
必须同时证明 pilot 数量恰为 1、频率为 1 kHz、幅度为 0.08 V，否则当场中止且已写
数据保留。

每个 segment 在任何 conditioning 前必须自足执行 `acq reset`、`acq add 1000`、
`acq add 2000`；随后每个 observation 的同一份 `gen show` 还必须证明 acquisition
frequency 数量恰为 2 且频率恰为 1000/2000 Hz。不得继承前一进程或 USB 重枚举前的
列表；任一验证失败当场中止。

warm-up 与第一正式窗之间不得重配置；warm-up 落盘后第一正式 acquisition 必须在
2.000 s 内开始。四个正式窗不得 silent retry，每窗单独保存真实 start/end/mid、
I/Q、board DC 与完整 RAWADC；任一窗无效即失败。相邻 DAC 命令的物理步长不得超过
一个网格步长；两方向观测必须在同一 grid 连续出现，全部 162 个观测和 648 个正式
子窗 sequence 严格递增。该 schedule 必须在真实 weighted acquisition midpoint 上
同时满足 `|corr(time,direction)|<=0.05` 和 `|corr(time,target_bias)|<=0.05`；还要求
formal 的 `corr(direction,pair_position)=0`、`corr(target,direction)=0`。

`grid_index in {0,10,...,80}` 的两方向观测均为 held-out sentinel，共 18 点；其余
144 点为 formal。sentinel 不得进入 DMM time/direction 模型、共享仿射椭圆、
方向特定映射、pair-position 映射、early/late 映射、通道选择或阈值选择。

## 3. DMM 同时性与逐点真值

对每个观测保存 `dc_dmm_pre/post` 及各自读数中点时间、四窗 acquisition 的真实
开始/结束/中点时间。逐点 DMM 值固定为在 pre/post 两点之间线性插值到四个正式窗
midpoint 的等权平均；禁止使用 board CH1、实验开始时静态 scan map 或时间范围外
外推。必须满足

```text
t_dmm_pre_mid < t_acq_mid < t_dmm_post_mid
```

插值权重必须在 `[0,1]`。每点 `|post-pre|/b(t)` 不超过 `sin(0.05)` 作为 DMM bracket
稳定性硬门，不能删除超限点。board CH1 仍只作有限性监控；
DM858E 是共享光路的外部电子真值，不是独立光学通道，故
`independent_optical_truth=false`。

只用 144 个 formal 点拟合与既有 time-truth 相同的模型：

```text
a(tau)=a0+a1*tau
b(tau)=exp(l0+l1*tau)
V0(tau,d)=v00+v1*tau+h*d
P=a(tau)+b(tau)*cos(pi*(V-V0(tau,d))/Vpi)
```

逐点 `phi_truth=pi*(V-V0(tau,d))/Vpi`。18 个 sentinel 只做 held-out DC 和相位
预测。方向分裂 `pi*|2h|/Vpi` 与 30 min 漂移继续是物理硬门，不能因模型包含这些项
而豁免。

## 4. 观察映射与防泄漏

共享 affine map 只用全部 formal I/Q 与上述逐点 truth 拟合，并在 formal/sentinel
分别评分。另各自只用 formal-up 或 formal-down 拟合两个方向特定 map，固定报告：

- up map -> up formal/sentinel；down map -> down formal/sentinel；
- up map -> down formal/sentinel；down map -> up formal/sentinel；
- 两个 map 的 `c0`、`A_hat`、`kappa`、相对矩阵差和中心差。

通道 I/Q 选择只允许使用全部 formal 点一次完成。任何 sentinel 或另一方向数据都不得
泄漏进方向特定 map。

同样按 pair position（first/second）各拟合一张 formal-only map 并双向交叉评分；再按
冻结 target ordinal 的 early/late 两半各拟合一张 formal-only map 并双向交叉评分。
方向、pair-position、early/late 三组 own/cross formal/sentinel 门必须全部通过，直接
排除启动先后和实验时间导致的 observer-map 变化；矩阵差仍只作 advisory。

## 5. RAWADC 与文件合同

162 个 startup discard 每个必须为精确 6 blocks、7680 samples、1 window；允许其
rail/guard，但必须完整保存实际 extrema/counts，且 telemetry/version/gain/fs/guard、
物理码界、非负计数、`read_fail=0`、timeout=0 全部通过。

162 个正式记录各有 4 个独立 16-block 窗，共 648 窗、13,271,040 samples；每窗和
合并记录必须精确，零 read-fail/timeout/rail/guard，最大绝对 raw 电压不超过 A44
冻结的 0.95 V headroom。逐窗 CSV/NPZ、正式 CSV/NPZ、discard CSV/NPZ、
conditioning CSV、pilot verification、
protocol、analysis、summary、manifest 全部进入精确受保护文件集合。discard 两文件
SHA-256 同时写入 analysis 和 checksums，replay 做三方一致性与全字段镜像检查。

## 6. 预注册通过门

所有门同时通过才可令本诊断 accepted：

- exact schedule、target order、UD/DU 平衡、approach/target、bridge 单步幅度、时间、
  DMM bracket、文件/源码哈希合同；
- `|corr(tau,d)| <= 0.05`、`|corr(tau,target_bias)|<=0.05`、
  `corr(direction,pair_position)=0`、`corr(target,direction)=0`、
  `cond([1,tau,d]) <= 3`；
- formal 与 held-out sentinel 的归一化 DC RMSE 均不超过 `sin(0.05)`；
- 方向 V0 分裂和 30 min 外推漂移均不超过 0.05 rad；
- 共享 map 的 formal/sentinel median/P95 均不超过 50/200 mrad；
- 方向、pair-position、early/late 三组 map 的 own/cross formal/sentinel median/P95
  全部不超过 50/200 mrad；
- 正式 RAWADC 完整、零 rail/guard、全点不超过 0.95 V；discard capture 合同完整；
- 模型、DMM、H1/H2、时间戳全部有限，DMM amplitude 始终为正。

通过也只说明局部标准化方向历史下可获得一个同时性标定；下一步仍须另行冻结随机化
目标、前后 DMM sentinel、固定标定和动态稳定门。不得直接复用 A35 的 0.15 V map。

## 7. 实现前验证

真实运行前必须保留并通过：健康合成；方向 split、drift、DMM sentinel、共享 map、
down-only map、formal raw rail/headroom/sample、discard 缺失/重复/sample、DMM bracket
逆序、approach/sign/schedule 破坏；discard 单独 rail 应保留但不阻止健康正式窗；
“discard 已落盘、formal 前失败”必须非零退出并保留 discard。validator 必须拒绝旧
ABA NPZ 冒充本协议。仿真只写 `build/exp_sim/interleaved_calibration/`。
