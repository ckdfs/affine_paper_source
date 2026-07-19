# MZM 局部双向交错标定诊断协议 v1.3（冻结弱轴杂散表）

版本：2026-07-17 v1.3（A63 后、任何 v1.3 实测前冻结）

本协议只诊断 A57/A63 已定位的弱轴确定性偏压杂散能否由独立标定表消除。它由两个
严格有先后关系的阶段组成：先用独立 run-id 生成冻结的 `d(V)`；再用新的三个
interleaved segment 检验该表。两阶段都不运行闭环、不选择控制增益、不更新
`data/exp/results.json` 或论文 headline，也不授权 gauge audit、控制器 v1.4
preflight 或 acceptance。

A62 已通过静态重复诊断排除 gen/acq restart 归因，故本协议保持固件
`8b1b1c2_rawadc_a3785e95` 不变，`firmware_change_authorized=false`；不得修改或刷写
固件。A63 已用真实数据否定 early/late time-resolved map 和 2phi--4phi 低阶谐波
扩展，二者不得重新引入。

## 1. 两阶段、目录与不可变性

阶段 D（donor）使用一个独立的 derived bundle run-id：

```text
data/exp/diagnostics/interleaved_spur_calibration/<run-id>/
```

其三个采集 segment 各用独立新目录；只有三个 segment 均完成、独立 replay 通过且
全局 donor 门通过后，聚合器才可原子生成 `spur_correction.npz` 与
`spur_correction.json`。校正表必须包含 81 个冻结 grid index/bias、选定 H2/H1
component、`d_A(V)`、`d_B(V)`、最终 `d(V)`、全部源目录与校验和、协议/源码哈希。

阶段 R（recipient）仍使用三个独立 interleaved segment 和一个新的 derived bundle：

```text
data/exp/diagnostics/interleaved_calibration/<new-run-id>/
```

每个 recipient segment 在创建目录前必须装载同一个已 accepted donor bundle，并把
donor `checksums.json`、`spur_correction.npz` 和 `spur_correction.json` 的 SHA-256
写入自身 protocol。三段及最终 bundle 必须逐字节一致；采集开始后不得替换、重估、
平滑或缩放 `d(V)`。recipient 的 sentinel、DMM 或 I/Q 不得回流更新 donor 表。

失败、partial、discard 和 derived rejected 目录全部永久保留，不得覆盖、删除、续跑
或拼接。仿真只写 `build/exp_sim/`。两阶段所有结束路径均执行 `gen reset`、`dac 0`，
并要求程序内及独立新连接确认 `IDLE, 0.000 V, Lock=NO, Cal=INVALID`。

## 2. 共同硬件、schedule 与 headroom

- 固定 `Vpi=5.222139048043948 V`、`Vcenter=0.8147635714861232 V`、81 点
  `Vcenter+-Vpi` 网格和 v1.2 的冻结 target order、UD/DU 平衡、approach、bridge、
  formal/sentinel 划分及 SHA-256。
- donor 与 recipient 都固定单个 1 kHz、**0.09 V** pilot。0.09 V 是 A63
  预注册允许的保守选择：比 0.08 V 提高 H2，同时不采用 A51 在 216 个正式窗中出现
  2 次稀有 rail 的 0.10 V。两阶段使用同一 pilot，禁止依赖跨 pilot 幅度缩放。
- acquisition frequencies 固定为 1000/2000 Hz；每个 segment 在 conditioning 前
  自足执行 `acq reset/add/add/show`，每个 observation 的 `gen show` 再验证恰好一个
  0.09 V pilot 与恰好两个 acquisition frequencies。
- 每个 observation 仍先物理 approach、target，各等待 0.500 s，再保存 6-block
  startup discard。discard 可 rail/guard，但必须完整；正式窗必须零 read-fail、
  timeout、rail、guard 且 `max|raw|<=0.95 V`。
- 全局 162 observations 固定分为三个连续 54-observation segment，边界仍为
  `[0,54)`、`[54,108)`、`[108,162)`；每段独立从 0 V conditioning、独立落盘与安全
  收尾。全局 bundle 继续拒绝缺段、重复、乱序、时间重叠、schedule/source/protocol
  hash 或硬件 metadata 不同。

## 3. DMM 多读 bracket 与时间真值

每个 observation 在 discard 后、正式 acquisition 前连续读取 DM858E 8 次
（pre[0..7]），四/八个正式窗后再连续读取 8 次（post[0..7]）。每次读数都保存
start/end/midpoint、side、read index 和 observation sequence 到独立受保护的
`dmm_reads.csv/.npz`，禁止只保存平均值。

pre/post 代表值分别是 8 次读数的算术平均，代表时间分别是 8 个 midpoint 的算术
平均。逐点 DMM truth 仍在 pre/post mean 之间线性插值到正式窗等权平均 midpoint。
必须满足全部 pre 读数结束不晚于第一正式窗开始、最后正式窗结束不晚于全部 post
读数开始，插值权重在 `[0,1]`。bracket 稳定门固定为

```text
|mean(post[0:8]) - mean(pre[0:8])| / b(t) <= sin(0.05)
```

不能删除超限点。另报告每侧单读标准差、极差及相邻差，用来验证 A62 的 DM858E
加性噪声模型；这些描述值不替代 mean bracket 硬门。board CH1 clipping 继续只作
advisory，不得当作 DM858E truth 失败。

DC time-truth 模型、formal/sentinel 防泄漏、方向分裂和 30 min 漂移门均与 v1.2
相同：formal/sentinel normalized DC RMSE 不超过 `sin(0.05)`，方向 split 与外推
漂移不超过 0.05 rad。

## 4. 全记录有界读取重试

两阶段复用 static-repeat v1.2 已真实验证的模式。若 `acq run` 返回完全无效记录
（tones、DC 或 RAWADC 缺失，因而没有任何可用测量），discard 或正式窗均允许最多
3 次尝试（含首次）。每次失败尝试必须立即流式写入 `acq_read_failures.json`，包括
stage、segment、observation、window、attempt、start/end 和失败原因；成功记录保存
实际 attempt count。失败尝试不能被当作 startup discard，也不能改变 schedule。

有效但 rail、guard、headroom 不足、噪声大或科学残差差的记录一律不得 retry；三次
均无效则非零退出并保留目录。discard 结束至第一个正式窗的 2.000 s 门按正式窗的
**首次尝试**开始时刻评价。analysis、summary、manifest 与 validator 必须逐条对账
失败记录、各窗 retry count 和总 retry count。

## 5. 阶段 D：高平均 donor 与 `d(V)` 定义

donor 使用共同的 162-observation paired schedule，但每个 observation 固定保存
`8 x acq run 16 blocks` 正式窗。八窗按 index 偶/奇分为两个预先固定的独立半样本：

```text
A = windows {0,2,4,6};  B = windows {1,3,5,7}
```

每半样本分别等权平均 I/Q。只用 donor formal 的 DMM time-truth 选择一次 components，
并冻结为 `X=selected H2 component`、`Y=selected H1 component`；recipient 必须使用
同一 component 名称。对 A、B 半样本分别只用 formal 拟合

```text
z = c0 + A_hat [cos(phi_truth), sin(phi_truth)]^T .
```

弱轴原始残差固定为 X 坐标残差

```text
r_X = X - c0_X - A_hat[0,:] [cos(phi_truth), sin(phi_truth)]^T .
```

同一 grid 的 up/down `r_X` 等权平均，得到 81 点 `d_A(V)`、`d_B(V)`。为使校正表与
常数/理想一、二维基函数可辨识，每张表都在 81 点上投影去除
`span{1, cos(phi_grid), sin(phi_grid)}`；`phi_grid` 固定为 donor time-truth 在该 grid
的 up/down 平均。最终冻结表为 `d(V)=(d_A+d_B)/2`，只允许按精确 grid index查表，
不插值、不外推。

donor accepted 要求共同采集/DC/RAW 门全部通过，并同时满足：

- `corr(d_A,d_B) >= 0.95`；
- `RMS(d_A-d_B)/RMS((d_A+d_B)/2) <= 0.35`，且分母为有限正数；
- 交叉半样本验证：用 `d_A` 修正 B、用 `d_B` 修正 A 后，各自在 formal-only 拟合
  shared map；formal 与 held-out sentinel 的 median/P95 全部不超过 50/200 mrad；
- 81 个 grid 的两张半表与最终表均有限，bias/index 与冻结网格逐元素一致；
- 校正只作用于 X，Y 和 DMM truth 逐元素保持不变。

上述门只验证表的可重复性和跨半样本预测性；不把 donor 自身当作 recipient 的通过
证据。若 profile 接近零导致相对门无定义，donor 失败并停止，而不是生成空修正表。

## 6. 阶段 R：冻结表的独立 recipient 检验

recipient 每 observation 仍固定 `4 x acq run 16 blocks`。原始 `X_raw/Y`、全部 I/Q
和窗记录永久保存；分析只按 grid index 计算

```text
X_corrected = X_raw - d[grid_index],  Y_corrected = Y .
```

component 不匹配、donor 未 accepted、校正表或其 source/checksum/hash 不一致、grid
缺失/重复/偏压不等、任何非有限值均为硬失败。shared、direction、pair-position 与
early/late map 全部只用 corrected X/Y 运行原 v1.2 formal/sentinel 防泄漏和
50/200 mrad 门。未修正的全部同名指标仍作为 `uncorrected_*` 描述性结果保存，不能
用于选择、缩放或回拟 `d(V)`。

recipient 继续要求 schedule、真实 midpoint 正交性、DMM/DC、方向 split、30 min
漂移、正式/丢弃 RAWADC、headroom、文件哈希和安全收尾全部通过。只有三个 recipient
segment 独立通过且全局 corrected bundle 的全部门通过，v1.3 才可
`accepted=true`。通过也只说明独立弱轴表能支持一次同时性标定，不授权后续闭环。

## 7. 文件合同

每个 donor/recipient segment 至少保护：主 observation、formal windows、transition
discard、conditioning、DMM reads 的 CSV+NPZ；`pilot_verification.json`、
`acq_read_failures.json`、protocol、analysis、summary、manifest 和 checksums。
derived donor bundle 另保护 `spur_correction.npz/json`；recipient protocol 保护 donor
三份 hash。CSV/NPZ 精确 schema、全字段镜像、summary/manifest count、源码/协议 hash
及 checksums 均由独立 validator 重算，不信任已存 analysis。

## 8. 首次真实运行前的离线门

必须在最终源码 hash 上全部通过并保留：

1. donor 三段健康仿真、聚合、独立 replay、校正表 A/B 重复性与 cross-half 门；
2. recipient 三段装载该 donor 表后的健康仿真、聚合与独立 replay；
3. donor 故障：profile decorrelation、split disagreement、cross-half sentinel、表 grid/
   component/finite/hash、DMM 单读缺失与 mean bracket、formal RAW rail/headroom/sample、
   discard 缺失/重复/sample；
4. recipient 故障：未应用/错误符号/缩放/替换表、donor hash、component、sentinel、
   mapping、DMM reads、schedule、RAWADC 与缺段/重复/乱序；
5. 两阶段 invalid window/discard 一次失败后恢复能 accepted 且完整记账，三次耗尽
   非零安全退出；有效 rail 记录不得被 retry；
6. 在首个 discard 已落盘后失败、在 DMM reads 中途失败、cleanup failure 均保留
   partial 审计文件并令 manifest failed；validator 拒绝旧 v1.2 bundle 冒充 v1.3。

只有上述全部通过，才可依次运行新的 donor 三段、独立生成冻结表，再运行新的
recipient 三段。不得提前启动 gauge audit、v1.4 preflight 或 acceptance。
