# MZM `V0` 短时稳定性诊断协议

版本：2026-07-16 v1.0（在首个真实运行前冻结）

本诊断不属于 acceptance 证据，不运行闭环，不更新 `data/exp/results.json`
或论文 headline。它只判断台架的 DMM 直流传输曲线在约 10 min 内是否稳定到
足以重新开始无标签标定。冻结参考来自失败但完整留痕的
`20260716_gauge_v1b_board2`：`Vpi=5.222139048 V`，contemporaneous DC refit
`V0=0.814763571 V`。本诊断不重新估计或选择 `Vpi`。

## 固定采集

1. 新建不可变目录 `data/exp/diagnostics/v0_stability/<run-id>/`，在输出偏压前
   写入器件、固件、仪器、温度、会话、代码 SHA-256 和全部固定参数。
2. 关闭导频并确认板载 lock 未启用。四个固定偏压为
   `V0 + Vpi*[-0.75,-0.25,0.25,0.75]`，即约
   `[-3.102,-0.491,2.120,4.731] V`，均远离 ±9 V 证据边界。
3. 每个 epoch 按四点正序、再按四点逆序采集，共 8 个 DMM 点；不删除转向点，
   保存每点绝对时间戳、方向、顺序、命令偏压和 DMM 电压。
4. 共 6 个 epoch，相邻 epoch 起点固定间隔 120 s，总跨度约 10 min。异常和人工
   中断均保留 partial CSV、summary、manifest 与 SHA-256。
5. 每个 epoch 在固定 `Vpi` 下拟合
   `P=a+c*cos(pi*V/Vpi)+d*sin(pi*V/Vpi)`，由 `atan2(d,c)` 得到 `V0`；
   正序、逆序分别拟合以量化方向/历史分裂。
6. 结束后执行 `gen reset` 与 `dac 0`，并复核板卡状态。无论通过或失败，本目录
   均不得删除、覆盖或提升为论文数据。

## 预先规定的通过门

所有门必须同时通过：

- 每个 epoch 的正/逆序 `V0` 分裂折算相位不超过 0.05 rad；
- 每个 epoch 的全 8 点余弦拟合 `RMSE/amplitude <= sin(0.05)`；
- 最后 5 个 epoch 的 `V0` 峰峰值折算相位不超过 0.05 rad；
- 以 epoch 中点作全部两两斜率中位数，外推 30 min 的相位漂移不超过 0.05 rad。

这里的 0.05 rad 是标定稳定性预算，不替代现有 50/200 mrad 椭圆自检门或
0.35 rad 锁定终点门。任一门失败都禁止直接重跑 gauge audit、v1.4 preflight
或 acceptance；先检查温度、光源/PD/TIA 稳定、DC 历史效应和偏压扫描策略。

## 范围限制

该四点诊断可以识别有效 `V0(t)`、方向分裂和曲线拟合残差，但不能单独区分环境
温度、光源功率、器件电荷历史或前端电子学漂移，也不测 AC observer 的 `O(2)`
规范。只有本门通过后，才允许设计带逐点时间戳、交错 DMM sentinel 和 ADC
raw min/max/near-rail 计数的下一版 gauge audit。
