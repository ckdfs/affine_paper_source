# MZM 时间分辨交错标定诊断协议

版本：2026-07-17 v1.3（新增 CH0 同窗 raw telemetry；v1.2 新增映射稳定性门）

v1.3 还必须执行 `reviews/mzm_adc_raw_extrema_protocol.md`。每个 `acq run` 保存产生
H1/H2 的同窗 CH0 raw min/max、rail/guard counts、sample completeness 和失败计数；
`n_avg=4` 不得只保留最后一窗。全部 conditioning 与 formal 点通过后才可令
`adc_raw_extrema_available=true`，并把 `adc_raw_telemetry_pass` 加入 accepted 的
必需项。历史 v1.0 目录继续明确为 telemetry unavailable，不伪造字段。

v1.2 的下一次采集入口必须执行
`reviews/mzm_direction_contemporaneous_mapping_protocol.md`：三条 leg 各自只用 formal
点拟合 phase-reference 仿射映射，并完成 own-leg、up/up 和 up/down 的全有向
formal/sentinel 交叉预测；`observer_mapping_stability_pass` 以同一 50/200 mrad 门
作为 time-calibration accepted 的必需项。v1.0 历史目录只读回放可以显示该新增
诊断，但不追溯改写其原始 manifest 或 protocol。

v1.1 不改动 ABA schedule、DMM truth、方向/漂移门或 50/200 mrad 自检门。它只
修正 v1.0 将 board CH1 DC rail 当成必需通过项的错误：DM858E 提供未削顶 DC
truth，ADS131M02 CH0 提供 H1/H2，而 `dc_board` 是独立 CH1 的监控均值。因此 CH1
到 1.200 V 既不污染 DMM truth，也不能证明 CH0 削顶。历史 v1.0 目录及其 analysis
保持不变；后续 v1.1 分析仍记录 CH1 rail advisory，但不把它列入 accepted 的
`required_pass_fields`。CH0 raw extrema/clip count 缺失仍单独阻止 v1.4 授权。

本诊断是 A24--A26 之后、v1.4 增益预检之前的 calibration-time 诊断。它不运行
闭环，不选择控制增益，不更新 `data/exp/results.json` 或论文 headline，也不追认
任何 v1.2/v1.3 失败目录。目的只有三个：用与生产标定相同的 gen/acq 路径把时间
漂移和方向历史分开；验证逐点 contemporaneous/interpolated DMM truth；在 held-out
sentinel 上检验该真值和无标签椭圆规范，而不是继续用实验开始时的静态 scan map。

这里的 DMM sentinel 是同一共享光路中、从拟合和椭圆标定完全留出的外部电子真值
样本，不是独立光学验证通道；无论本诊断是否通过，`independent_optical_truth` 都
保持为 false。

## 1. 不可变目录与安全边界

1. 每个真实运行新建
   `data/exp/diagnostics/time_calibration/<run-id>/`，在输出偏压前写入设备、固件、
   仪器、温度、会话、操作者、仓库 commit、相关源码 SHA-256、完整 schedule 和
   schedule SHA-256；目录不得覆盖、删除或拼接续跑。
2. 固定 `Vpi=5.222139048043948 V`，只作为本诊断的尺度；固定扫描坐标中心
   `Vcenter=0.8147635714861232 V`，范围为
   `Vcenter±Vpi=[-4.4073754766, 6.0369026195] V`。该中心只定义安全扫描窗口，
   不作为相位真值或 V0 先验。
3. 正式点使用 `gen bias`、0.15 V/1 kHz pilot、`acq run 16 blocks`、
   `n_avg=4`，随后读取 DM858E。正式采集前从 0 V 以不大于正式步长的小步进
   conditioning 到下边界；conditioning 全部保存但不评分。
4. 每点流式保存 raw CSV，字段至少包括 `role, leg, direction, grid_index,
   sequence_index, bias, t_start_unix, t_end_unix, t_mid_unix, dc_dmm,
   dc_board, I1, Q1, I2, Q2`。时间戳不得在采完后合成；`t_mid` 固定为实际
   acquisition/DMM 区间的中点。
5. SIGINT、SIGTERM、通信故障或分析失败均保留 partial CSV、protocol、summary、
   manifest 和 checksums。结束路径始终执行 `gen reset`、`dac 0` 并保存最终状态。

## 2. 冻结的 ABA 小步进 schedule 与 sentinel

正式网格为 81 个等间隔偏压，步进约 0.130553 V。三条完整 leg 按
`up -> down -> up` 执行，每条均保留全部 81 点，包括转向端点，共 243 个正式
访问。该 ABA 结构使线性时间项与方向符号在冻结 schedule 上正交，同时保持每次
偏压变化不超过 A24 已验证的小步进；不得改成随机大阶跃。

每条 leg 中 `grid_index in {0,10,20,...,80}` 的 9 个点预先标记为
`role=sentinel`，三条 leg 共 27 个 held-out sentinel；其余 216 点为
`role=formal`。sentinel 沿自然小步进路径取得，不引入额外大阶跃。它们不得进入：

- 时间/方向 DC 模型拟合；
- 椭圆几何、中心、规范或通道选择；
- formal 自检或任何阈值选择。

sentinel 只用于预注册的留出预测残差和留出相位 concurrence。缺失 sentinel、
非有限值、时间不单调、重复/跳号 sequence、缺少双方向或 formal 点超出 sentinel
总体时间覆盖范围都硬失败；不得插值范围外外推。

## 3. 时间分辨 DMM truth 模型

令 `tau=(t-t_ref)/Tscale`，其中 `t_ref` 是 formal 点时间均值，`Tscale` 是 formal
点半时间跨度；方向 `d=+1/-1` 分别代表 up/down。只用 formal DMM 点拟合

```text
a(tau)  = a0 + a1*tau
b(tau)  = exp(l0 + l1*tau)
V0(tau,d) = v00 + v1*tau + h*d
P(V,t,d) = a(tau) + b(tau)*cos(pi*(V-V0(tau,d))/Vpi).
```

`exp` 参数化保证幅度为正。`V0` 必须先对齐到同一 `2Vpi` 等价分支；设计矩阵
`[1,tau,d]` 必须满秩。逐点外部真值固定为

```text
phi_truth(t_i) = pi*(V_i - V0(tau_i,d_i))/Vpi.
```

无标签椭圆只在 formal 的 I/Q 上拟合，并用 formal 的规范化 DMM
`(P-a(t))/b(t)` 固定 `O(2)` 规范。formal 和 sentinel 的 self-check 都比较同一个
逐点 `phi_truth`；不得再用 primary scan 的静态 `V0` 评分。

方向历史和时间漂移虽然进入真值模型，但不能被模型“解释后忽略”：冻结的物理量为

- 上/下方向 V0 分裂：`pi*|2h|/Vpi`；
- 30 min 线性外推：`pi*|v1|*(1800/Tscale)/Vpi`。

## 4. 预注册通过门

所有门必须同时通过：

- `|corr(tau,d)| <= 0.05` 且 `cond([1,tau,d]) <= 3`；
- formal DC 与 held-out sentinel DC 的归一化 RMS 均不超过 `sin(0.05)`；
- 方向 V0 分裂不超过 0.05 rad；
- 30 min 外推 V0 漂移不超过 0.05 rad；
- 无标签椭圆对 time-resolved truth 的 formal median/P95 不超过 50/200 mrad；
- 同一冻结椭圆在 held-out sentinel 上的 median/P95 也不超过 50/200 mrad；
- 椭圆正定、全部参数有限、DMM 幅度始终为正；全部命令偏压绝对值小于
  `0.995*9 V`；board CH1 DC 必须有限，但达到 1.199 V 只记录 monitor advisory，
  不参与 time-truth accepted。CH1 rail 不能代替 CH0 AC raw extrema，不能据此
  宣称已排除所选 AC 通道的瞬时削顶。

冻结 `Vpi/Vcenter` 的静态 coordinate-map concurrence（代表旧式 scan-map 评分
口径的反事实，不是假称本轮另有新鲜 primary scan）仍分别在 formal/sentinel 保存，
但不参与 time-truth 放行。任一门失败都禁止
gauge audit、v1.4 preflight 或 acceptance；不得放宽 0.05 rad、50/200 mrad，
不得删除 sentinel 或选择较有利的 leg。

由于当前固件没有 CH0 AC acquisition 窗内的 raw min/max 或 near-rail count，本协议即使
time-truth 全部门通过也必须输出 `adc_raw_extrema_available=false` 和
`v1_4_authorization_ready=false`。只有后续真实接入并冻结该遥测及门限，才可把后者
改为 true；board CH1 DC 无论是否低于 1.199 V 都不能替代 CH0 瞬时 rail 证据。

## 5. 离线验证和历史数据口径

首个真实运行前必须完成并保留以下硬件无关验证：

1. 合成无漂移数据通过全部门；已知 `a(t), b(t), V0(t)` 与方向偏移可按预设精度
   恢复，静态 map 在有漂移时明确劣于 time-resolved truth。
2. sentinel 污染、缺失、时间逆序、单方向、跨 `2Vpi` 分支和非有限值均被拒绝；
   sentinel 不得泄漏进拟合。
3. A24 的
   `data/exp/diagnostics/v0_dense/20260716_v0dense_v1_board2/` 只读回放必须继续
   报告约 0.10 rad 方向分裂和超过 0.05 rad 的 30 min 漂移，不能被新模型改判
   为通过。该目录的 6-block I/Q 不等价于本协议的 16-block、`n_avg=4` 椭圆，
   回放只验证 DC time-truth 分解。
4. A13 及更早单向、无完整时间合同的 `calib.npz` 明确判为不具备本协议回放资格；
   不伪造时间戳或方向。

仿真与回放输出只能写入 `build/`。只有上述验证全部通过，才可以实现或审核真实采集
入口；实现完成也不等于授权运行。

## 6. 后续 v1.4 的非协商接口（本诊断不执行）

若本诊断将来通过，v1.4 仍须另行冻结。至少包含：

- 每条控制轨迹保存开始、结束和逐周期时间戳；最终误差使用由前后 DMM sentinel
  包围的插值 truth，禁止实验开始时静态 scan map 和禁止时间范围外外推；
- 目标使用记录种子的 permutation `p`，配对初始侧使用 `p[::-1]`，使每个目标在
  配对块中的平均时间位置相同；控制器顺序继续使用平衡循环；
- gain、target、start side 都不得与时间形成单调顺序；preflight 也不能继续按
  “先全部 G=0.05，再全部 G=0.10”的旧顺序；
- 新 loader 必须拒绝 v1.3 preflight，并从原始 time-truth error、动态指标和 rail
  重新计算 passed；不能信任旧 boolean 数组或混合版本聚合；
- DMM sentinel 仍不把 `independent_optical_truth` 置为 true。
